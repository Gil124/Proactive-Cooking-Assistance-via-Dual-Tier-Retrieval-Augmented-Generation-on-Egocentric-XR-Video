# K1 Evaluation Protocol

## Bias controls

**Core rule:** the extractor never scores itself.

| What | How it is enforced |
|---|---|
| Ontology | Frozen in `k1/config/ontology.yaml` before any LLM call. Never updated by a model. |
| Physics bounds | Frozen in `k1/config/physics_bounds.yaml`. Temperature values are never invented by the generator. |
| Gold labels | Reviewed by the thesis author against the runtime node schema. Stored in `k1/data/gold/`. A file is re-reviewed only when `definition_version` changes. |
| Generator ≠ Critic | Generator model and critic model are different model families (see `CHANGELOG.md` model pins). |
| No few-shot leakage | The generator prompt carries no recipe examples, so no reviewed recipe can leak into extraction. |
| Frozen run | Review and scoring use one run. The pipeline is not changed between the run and the report. |

## Purpose of this evaluation

K1 construction is not a research contribution of the thesis. K1 only has to exist and be
correct. The evaluation therefore answers one practical question: **was building K1 with an
LLM pipeline and then correcting it by hand a good decision?** It reports three things.

1. **Accuracy.** How often the pipeline got a step right.
2. **Correction effort.** How much the author had to change to make the graph correct.
3. **Time.** How long correcting took, against annotating the same kind of step from scratch.

The K1 used in the user study is the reviewed graph, not the raw pipeline output, so
extraction errors cannot reach the study results.

## Reviewed steps (the gold set)

The unit is one recipe step. Every ingested recipe that is not `excluded` in `recipes.yaml`
is in the review queue. One reviewed step, `k1/data/gold/{recipe_id}_stepNN.gold.json`, is
used twice:

- as the **gold label** the pipeline output is scored against;
- as the **corrected step** the final graph is built from (`k1 finalize`).

Each file records how it was made:

| Field | Meaning |
|---|---|
| `expected.in_scope` | `false` when the step is outside the dish and must not become a node |
| `mode` | `corrected` (form started from the pipeline output) or `from_scratch` (blank form, output hidden) |
| `seconds_spent` | Active time on the step, summed over saves. Gaps longer than `idle_cap_seconds` count as the cap |
| `seeded_from_run` | The run whose output was shown or hidden |
| `definition_version` | `definition_version` in `config/dish.yaml` at save time |

A file whose `definition_version` is not the current one is **out of date**. It is kept on
disk, shown as such in the review tab, and left out of every metric until reviewed again.
The fifteen files annotated on 2026-09-28 predate the definition in
[`10-recipe-variation.md`](10-recipe-variation.md) and are in this state.

### Two modes

`k1/config/gold_review.yaml` lists the recipes annotated **from scratch**. All others are
**corrected**.

| Mode | What the reviewer sees | What it measures |
|---|---|---|
| `corrected` | The pipeline's step, already trimmed to the inventory, in an editable form | Correction effort and correction time |
| `from_scratch` | A blank form. The Review tab hides these recipes until they are saved | Time to build a step by hand, and accuracy not anchored by the pipeline output |

Decide the `from_scratch` list before annotating and do not look at those recipes on the
Graph tab first.

### Workflow

```bash
uv run k1 run --run <run_id> --no-neo4j   # 1. freeze one pipeline run
uv run k1 viz --run <run_id>              # 2. Gold set tab: review every step, one at a time
uv run k1 finalize --run <run_id>         # 3. build the final graph from the reviewed steps
uv run k1 eval --run <run_id>             # 4. write the report
```

Step 3 writes `k1/data/k1/graph.final.json` (reviewed) and `graph.auto.json` (pipeline) and
runs the validation gates on the final graph. It stops if a step has no current review;
`--allow-unreviewed` uses the pipeline output for those steps.

Step 4 writes, in `data/artifacts/runs/{run_id}/eval/`:

| File | Content |
|---|---|
| `report.md` | All tables below, ready to copy |
| `correction.json` | The same numbers, machine-readable |
| `correction_steps.csv` | One row per reviewed step: mode, time, keep/drop outcome, fields changed |

Do not change the pipeline between steps 1 and 4. Measure once, then fix what remains by hand.

### Metrics (computed by `eval/correction.py`)

**Accuracy**, reported for all reviewed steps and for `from_scratch` steps alone:

| Metric | Computation |
|---|---|
| Keep/drop agreement | % steps where pipeline and reviewer agree on `in_scope`; plus counts of wrongly kept and wrongly dropped |
| Field accuracy | % steps kept by both where `node_type`, `pre_conditions`, `post_conditions`, `tools`, `has_safety_bound`, `action_phrase` match. Conditions and tools compare as sets after alias resolution |
| Condition P / R / F1 | Micro-averaged over `(entity, k2_label)` pairs, for pre- and post-conditions |
| Steps needing no change | % steps with nothing to fix; also reported ignoring `action_phrase` wording |

**Correction effort:** total edits (one per changed field, one per keep/drop fix), edits per
step, and edits by field.

**Time:** total minutes, mean and median seconds per step, per mode; seconds saved per step;
and the projected minutes for the whole queue by hand against correcting.

**Graph:** node and `NEXT` edge counts and nodes shared by several recipes, pipeline against
reviewed; nodes identical in both, only in the pipeline graph, only in the reviewed graph.

### Limits to state in the thesis

- One annotator, who is also the author of the pipeline.
- `corrected` labels are anchored by the pipeline output. The `from_scratch` column is the
  unanchored accuracy figure.
- The author had seen earlier pipeline output for some recipes before this protocol existed.
- Time is self-paced active time in a review tool, not a controlled timing study.

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

Against the reviewed steps: see "Metrics" above.

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
| Validation gate pass | % nodes/edges passing all 7 gates | 100% |
| Required fields present | All PIC fields present on all nodes | 100% |

## Second annotator (optional, later)

1. A second annotator reviews the `from_scratch` recipes independently, into a separate folder.
2. Compute Cohen's kappa on `in_scope`, `node_type`, and `k2_label`.
3. Record it in `gold/second_annotator_kappa.json`. Do not modify the original files.

## Improvement protocol after a run

This applies to trial runs, before the frozen run that is reviewed and reported.

1. Read the error taxonomy breakdown in the eval report.
2. If `invented_temp` > 0%: strengthen the critic prompt (not the generator). Re-run.
3. If `wrong_k2_label` > 10%: update compile map in `ontology.yaml`, re-run L2 only.
4. If `alias accuracy` < 80%: tighten ER embedding threshold, re-run L3 only.
5. Record every change in `CHANGELOG.md` as a new version entry.
