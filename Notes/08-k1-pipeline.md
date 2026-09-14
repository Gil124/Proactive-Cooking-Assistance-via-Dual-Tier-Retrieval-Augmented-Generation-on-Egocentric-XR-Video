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

### L2 extract contract — temperature field

The generator must set `temperature_c: Optional[float]` only when the step text explicitly
states a temperature. This field is checked directly by the critic for invented-temperature
detection. **Never infer it from digit patterns; leave it null if no temperature is stated.**

### L3 fuse contracts

Input: all accepted/revised generator outputs from L2 (gold recipes included — see below).
Output: `data/artifacts/runs/{run_id}/L3/fused_dag.json` and `L3/removed_edges.json`.

Fingerprint for node dedup: `sha256(node_type + canonical_action + k2_pre + k2_post)`.
Entity aliases resolved via **dictionary-only lookup** from `k1/config/ontology.yaml` (v1).
Embedding + LLM pairwise disambiguation is documented as a future upgrade.

**REQUIRES edge construction (k1-0.2.0 rule):**
- REQUIRES edges are built *within a single recipe*, using that recipe's step ordering.
- An edge is added from node i to node j only when `step_index(i) < step_index(j)` and
  a post-condition of step i matches a pre-condition of step j (`entity_id` + `k2_label`).
- All edges (NEXT and REQUIRES) are deduplicated via a `(from_id, to_id, edge_type)` set.

**Cycle-breaking pass:**
After all NEXT and REQUIRES edges are added, `_break_cycles` runs:
- While any cycle exists in the NEXT + REQUIRES subgraph, remove one edge per cycle:
  prefer removing REQUIRES over NEXT; among ties prefer the lowest-weight edge.
- Removed edges are written to `L3/removed_edges.json` for inspection.

### L4 validate gates (all must pass before store)

1. Pydantic schema valid.
2. Graph (NEXT + REQUIRES edges) is acyclic.
3. Every `Process` node has ≥ 1 pre_condition and ≥ 1 post_condition.
4. **Gate 4 thermal rule (k1-0.2.0):** Thermality is re-derived from `physics.is_thermal_action(node.action_phrase)` — it is **not** inferred from the presence of `safety_bounds`. A thermal `Process` that is missing `safety_bounds` OR is missing a `HAS_SAFETY_BOUND` edge **fails** this gate.
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
**Gold hold-out (clarified in k1-0.2.0):** Serious Eats, Gordon Ramsay, Bon Appétit are extracted and included in the fused graph like any other recipe. Hold-out strictly means they are **never placed in the generator prompt as few-shot examples**. The current generator prompt carries no few-shot examples, so this is already enforced.
