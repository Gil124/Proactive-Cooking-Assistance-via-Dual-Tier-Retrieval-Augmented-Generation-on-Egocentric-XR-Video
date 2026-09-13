# K1 Evaluation Protocol

## Bias controls

**Core rule:** the extractor never scores itself.

| What | How it is enforced |
|---|---|
| Ontology | Frozen in `k1/config/ontology.yaml` before any LLM call. Never updated by a model. |
| Physics bounds | Frozen in `k1/config/physics_bounds.yaml`. Temperature values are never invented by the generator. |
| Gold labels | Annotated by the thesis author against the runtime node schema. Stored in `k1/data/gold/`. Committed and never modified after first annotation. |
| Generator ≠ Critic | Generator model and critic model are different model families (see `CHANGELOG.md` model pins). |
| Gold hold-out | The 3 gold recipes are never used as few-shot examples in extraction prompts. |

## Gold set v1

Three held-out scrambled-egg recipes, annotated once by the thesis author.

| Recipe | File | Status |
|---|---|---|
| Serious Eats — Fluffy Scrambled Eggs | `gold/serious_eats.gold.json` | annotate before first eval run |
| Gordon Ramsay — Scrambled Eggs | `gold/gordon_ramsay.gold.json` | annotate before first eval run |
| Bon Appétit — Best Scrambled Eggs | `gold/bon_appetit.gold.json` | annotate before first eval run |

Gold file schema per node:
```json
{
  "recipe_id": "string",
  "step_number": 1,
  "expected": {
    "node_type": "Process|Transfer|Plate",
    "action_phrase": "string",
    "pre_conditions": [{"entity_id": "string", "k2_label": "liquid|coagulating|solid|scorched"}],
    "post_conditions": [{"entity_id": "string", "k2_label": "liquid|coagulating|solid|scorched"}],
    "has_safety_bound": true
  },
  "annotator": "gil.arroteia",
  "annotation_date": "YYYY-MM-DD",
  "notes": ""
}
```

## Per-stage metrics

### L1 — Ingest

| Metric | Computation | Pass threshold |
|---|---|---|
| Schema validity | % canonical.json files passing Pydantic | 100% |
| Step count match | Steps found vs. expected count per recipe source | ≥ 90% |
| Junk-step rate | % steps dropped by junk filter | report only |
| Missing ingredient rate | % recipes with empty ingredients list | 0% |

### L2 — Extraction

Automatic (no LLM judge):

| Metric | Computation |
|---|---|
| Span groundedness | `source_span ⊆ step_text` — boolean per step; report mean |
| Schema fill rate | % non-null fields across all extractions |
| K2-label validity | % `k2_label ∈ {liquid, coagulating, solid, scorched}` |
| Critic accept rate | % verdicts = `accept` on first pass |
| Critic revise rate | % verdicts = `revise` (one revision loop triggered) |
| Critic reject rate | % verdicts = `reject` (node dropped) |

Human (vs gold, on 3 gold recipes):

| Metric | Computation |
|---|---|
| Node-type precision/recall | TP/FP/FN on `node_type` field vs gold |
| K2-label accuracy | % steps where predicted k2_label matches gold |
| Safety-bound coverage | % thermal Process nodes that have `HAS_SAFETY_BOUND` in gold AND in extraction |
| Invented-temperature rate | % extractions where temperature value is not in source text and not in `physics_bounds.yaml` |

Error taxonomy:
- `wrong_type` — `node_type` mismatch
- `wrong_k2_label` — k2_label mismatch
- `missing_safety` — thermal Process without `HAS_SAFETY_BOUND`
- `invented_temp` — hallucinated temperature value
- `span_not_found` — source_span not a substring of step text

### L3 — Fusion

| Metric | Computation |
|---|---|
| Alias accuracy | % entity aliases correctly merged vs gold synonym table in `gold/entity_aliases.yaml` |
| Branch count | Number of distinct parallel branches in fused DAG |
| DAG acyclicity | Boolean — must be True |
| Dedup rate | % duplicate nodes removed by fingerprint |

### L4 — Store

| Metric | Computation | Pass threshold |
|---|---|---|
| Validation gate pass | % nodes/edges passing all 6 gates | 100% |
| Required fields present | All PIC fields present on all nodes | 100% |

## Running an evaluation

```bash
uv run k1 eval --run <run_id>
```

This produces `data/artifacts/runs/{run_id}/eval/report.md`.
Copy the summary table into `CHANGELOG.md` under the version entry that produced the run.

**The same 3 gold recipes must be used across all pipeline versions.** This is the trend line.
Do not add or remove gold recipes after v1 annotation.

## Adding a second annotator (optional, later)

1. Have the second annotator annotate the same 3 recipes independently using the same schema.
2. Compute Cohen's kappa on `node_type` and `k2_label` fields.
3. Record in a new `gold/second_annotator_kappa.json` file.
4. Do not modify the original gold files.

## Improvement protocol after a run

1. Read the error taxonomy breakdown in the eval report.
2. If `invented_temp` > 0%: strengthen the critic prompt (not the generator). Re-run.
3. If `wrong_k2_label` > 10%: update compile map in `ontology.yaml`, re-run L2 only.
4. If `alias accuracy` < 80%: tighten ER embedding threshold, re-run L3 only.
5. Record every change in `CHANGELOG.md` as a new version entry.
