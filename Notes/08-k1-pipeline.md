# K1 Pipeline — Design Specification

This note is the authoritative reference for the offline K1 knowledge graph construction pipeline.
Agents and implementers: read this after `00-agent-briefing.md`.

Current implementation status, open bugs, and things still to verify live in
[`../k1/TODO.md`](../k1/TODO.md). This note describes the intended design; `TODO.md` records
where the code does not yet match it.

## What K1 must be (from PIC §4.6)

An **offline, immutable, multi-path Neo4j DAG** of `Process` / `Transfer` / `Plate` nodes with:

| Field | Required on all nodes |
|---|---|
| `pre_conditions` | List of `(entity_id, physics_state, k2_label)` tuples |
| `post_conditions` | List of `(entity_id, physics_state, k2_label)` tuples |
| `timing_constraints` | Optional duration/deadline |
| `HAS_SAFETY_BOUND` | Typed attribute edge on every thermal `Process` |

KAG enrichment: `T_semantic = T_fact ⊕ T_concept`.

- `T_fact` — recipe action nodes and causal edges extracted from recipe text.
- `T_concept` — curated physics/safety concept nodes attached as `HAS_SAFETY_BOUND` edges. **Not LLM-extracted.** Source is `k1/config/physics_bounds.yaml`.

Runtime: Fusion does a **single graph traversal** per cycle. Community summaries or free predicates are not usable by Fusion.

## K2 compile map (frozen)

Physics states extracted by the generator are compiled to these four K2 labels before storage. The compile map is frozen in `k1/config/ontology.yaml` and never updated by the LLM.

| K2 label | Physics states that map to it |
|---|---|
| `liquid` | raw, heterogeneous, homogenized-aerated-liquid, unwhisked |
| `coagulating` | gel, soft-curd, semi-solid, partial-set, warming |
| `solid` | solid-curd, fully-set, firm, cross-linked |
| `scorched` | over-contracted, browning, scorched, maillard-advanced, syneresis-weeping |

Syneresis is stored as a `physics_detail` property on the node but compiles to `scorched` for K2 matching.

## Ontology (frozen node types)

Source: Kumbhakern et al. [14] + PIC §4.6. Never extend without updating this note and `CHANGELOG.md`.

| Node type | Semantics |
|---|---|
| `Process` | A cooking action that changes ingredient state. Must have `HAS_SAFETY_BOUND` if thermal. |
| `Transfer` | Movement of ingredient or item (e.g. pour into pan, remove from heat). |
| `Plate` | Plating or serving step. Final graph node in any recipe branch. |

Edge types:

| Edge | Semantics |
|---|---|
| `NEXT` | Sequential ordering within a recipe branch |
| `REQUIRES` | Pre-condition dependency across nodes |
| `HAS_SAFETY_BOUND` | Typed physics constraint on a Process node |
| `INGREDIENT_OF` | Ingredient → Process |
| `USES_TOOL` | Tool → Process |

## Pipeline module contracts

```
k1/
  src/k1_pipeline/
    ingest/     # L1 — fetch, parse, chunk, junk filter
    extract/    # L2 Generator — constrained Pydantic extraction
    critic/     # L2 Critic — grounded accept/revise/reject
    fuse/       # L3 — entity resolution + multi-path DAG
    validate/   # L4 — schema + acyclicity + groundedness gates
    store/      # L4 — graph.json, graph.cypher, optional Neo4j
    viz/        # L4 — Streamlit graph + Review UI
    eval/       # offline — gold comparison reports
    cli.py      # entry point for all stages
```

### L1 ingest contracts

Input: `k1/config/recipes.yaml` — list of `{url, recipe_id, variant_label}`.
Output per recipe: `data/recipes/{recipe_id}/raw.html`, `data/recipes/{recipe_id}/canonical.json`.

`canonical.json` schema:
```json
{
  "recipe_id": "string",
  "title": "string",
  "source_url": "string",
  "variant_label": "string",
  "ingredients": ["string"],
  "tools": ["string"],
  "steps": [{"number": 1, "text": "string"}],
  "temperatures_mentioned": ["string"],
  "timings_mentioned": ["string"]
}
```

Junk filter rules (deterministic, no LLM):
- Drop any step whose text length < 15 chars.
- Drop any step whose text matches the pattern `Other .* [Rr]ecipes`, `[Ss]ee also`, `[Tt]ry:`.
- If step count after filtering < 2, fail loudly (do not silently skip).

### L2 extract + critic contracts

Generator output per step (`data/artifacts/runs/{run_id}/L2/gen/{recipe_id}_{step_n}.json`):
```json
{
  "node_type": "Process|Transfer|Plate",
  "action_phrase": "string",
  "pre_conditions": [{"entity_id": "egg", "physics_state": "string", "k2_label": "liquid|coagulating|solid|scorched"}],
  "post_conditions": [{"entity_id": "egg", "physics_state": "string", "k2_label": "..."}],
  "timing_constraints": {"duration_s": null, "deadline": null},
  "ingredients": ["egg", "butter"],
  "tools": ["non-stick pan"],
  "source_span": "verbatim quote from step text",
  "confidence": 0.95,
  "extractor_model": "groq/llama-3.3-70b-versatile"
}
```

Critic output (`data/artifacts/runs/{run_id}/L2/critic/{recipe_id}_{step_n}.json`):
```json
{
  "verdict": "accept|revise|reject",
  "grounding_quote": "substring of source step",
  "issues": ["optional list of issues"],
  "critic_model": "openrouter/google/gemini-2.0-flash-lite"
}
```

Rules enforced by critic:
- Any temperature value in the extraction must be a substring of the recipe text OR be in `physics_bounds.yaml`. Invented temperatures → `reject`.
- `source_span` must be a substring of the step text. If not → `revise`.
- `k2_label` must be one of the four valid labels. If not → `reject`.

### L3 fuse contracts

Input: all accepted/revised generator outputs from L2.
Output: `data/artifacts/runs/{run_id}/L3/fused_dag.json`.

Fingerprint for node dedup: `sha256(node_type + canonical_action + k2_pre + k2_post)`.
Entity aliases resolved via embedding top-3 then LLM pairwise only on pairs with cosine similarity > 0.75 and < 0.95 (the ambiguous band).

### L4 validate gates (all must pass before store)

1. Pydantic schema valid.
2. Graph is acyclic (DFS).
3. Every `Process` node has ≥ 1 pre_condition and ≥ 1 post_condition.
4. Every `Process` with `node_type=Process` and any thermal action has a `HAS_SAFETY_BOUND` edge.
5. Every `k2_label ∈ {liquid, coagulating, solid, scorched}`.
6. Every `source_span` is a substring of the recipe step text from `canonical.json`.

## What Fusion will query

At runtime, Fusion calls K1 with:
- Current branch (selected at session start from K2 pre-conditions)
- Node ID of the current expected recipe step

K1 returns:
- The `post_conditions` of that step (expected K2 state after completion)
- The `HAS_SAFETY_BOUND` edges on that step (temperature thresholds)
- The next node ID(s) in the DAG

Fusion **does not** query ImpactVariable, OutcomeVariable, or community summaries.
Do not add those node types to the runtime graph.

## Corpus scope

**Allowed:** scrambled-egg recipes in `k1/config/recipes.yaml`.
**Excluded:** Menemen, Egg Bhurji, Chinese tomato-egg stir-fry, Huevos a la Mexicana, any non-scrambled dish.
**Gold hold-out:** Serious Eats, Gordon Ramsay, Bon Appétit — must not be used as prompt examples.
