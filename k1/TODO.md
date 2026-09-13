# K1 Pipeline — TODO, Concerns, and Status

Living document. Update it in the same commit as the change it describes.
Design spec: [`../Notes/08-k1-pipeline.md`](../Notes/08-k1-pipeline.md) · Eval protocol: [`../Notes/09-k1-evaluation.md`](../Notes/09-k1-evaluation.md)

Status legend: `[ ]` open · `[~]` partially done · `[x]` done and verified

---

## A. Blocking bugs (fix before the first real run)

Both were reproduced locally with a scratch script, not just read off the code.

### A1. Temperature regex rejects almost every node
**Where:** `src/k1_pipeline/critic/critic.py` — `_TEMP_RE` and `_deterministic_check`
**Also:** `src/k1_pipeline/eval/metrics.py` — same pattern, same flaw

`_TEMP_RE = re.compile(r"\b(\d{2,3})\b")` runs over `node.model_dump_json()`, so it matches
any 2–3 digit number anywhere in the serialised node. Reproduced:

```
node json: {"step_number": 2, "confidence": 0.95, "action_phrase": "whisk 3 eggs for 30 seconds",
            "timing_constraints": {"duration_s": 90}}
matches:   ['95', '30', '90']
```

`95` (confidence), `90` (duration) and `30` (seconds) are not in the step text and not in
`physics_bounds.yaml` `{62, 70, 140, 150}`, so `_deterministic_check` appends
"Invented temperature" and the verdict becomes **reject**. Nearly every node is dropped
and the fused graph comes out near-empty.

- [ ] Only scan temperature-bearing fields, not the whole JSON blob. Best option: have the
      generator emit an explicit `temperature_c: Optional[float]` field and check only that.
- [ ] Require a unit in the pattern when scanning free text (`\d{2,3}\s*°?\s*[CF]\b`).
- [ ] Exclude `confidence`, `duration_s`, `step_number`, and any `_id` field from the scan.
- [ ] Add a regression test: a node with `confidence=0.95`, `duration_s=90` and no temperature
      anywhere must produce **zero** invented-temperature issues.

### A2. REQUIRES edges create cycles, so Gate 2 aborts the pipeline
**Where:** `src/k1_pipeline/fuse/dag_builder.py` — Phase 4 (REQUIRES edge construction)

The rule links *any* node whose `post_conditions` match a `pre_condition`, in both directions.
Two steps that both consume and produce `egg:liquid` (for example "whisk the eggs" and
"season the raw eggs") produce `A→C` and `C→A`. Reproduced:

```
acyclic: False
cycles:  [['A', 'C']]
```

`validate/gates.py` Gate 2 includes REQUIRES edges in the acyclicity check, so
`k1 validate` exits non-zero and `k1 run` stops before `store`.

- [ ] Constrain REQUIRES to respect recipe step order: only add `other → node` when the
      producing step index is lower than the consuming step index.
- [ ] Skip self-loops and identical `(k2_pre, k2_post)` pairs where the label does not change.
- [ ] Decide explicitly whether Gate 2 should check NEXT only, or NEXT + REQUIRES. Document
      the choice in `Notes/08-k1-pipeline.md`.
- [ ] Add a regression test for the A↔C scenario above.
- [ ] Phase 4 is O(n²) over all node pairs. Fine at ~70 nodes; revisit if the corpus grows.

---

## B. Metrics that silently report wrong numbers

### B1. Safety-bound coverage is always 0%
**Where:** `src/k1_pipeline/eval/metrics.py:187` — `gold_comparison`

It reads `extracted.get("safety_bounds")` from the **L2** `.gen.json` files, but
`ExtractedNode` has no `safety_bounds` field. Bounds are attached later, in L3, on `K1Node`
(`fuse/dag_builder.py:126`). The lookup always returns falsy, so the metric reports 0%
regardless of actual behaviour.

- [ ] Read safety bounds from `L3/fused_dag.json`, or from `K1Node`, not from the L2 artifacts.
- [ ] Map gold `step_number` to the fused node via `source_recipe_ids` + `source_step_indices`
      (fingerprint merging means it is not a 1:1 mapping).

### B2. Alias accuracy is promised but never computed
**Where:** `Notes/09-k1-evaluation.md` L3 table vs `src/k1_pipeline/eval/metrics.py` — `l3_metrics`

The eval protocol lists "Alias accuracy — % entity aliases correctly merged vs gold synonym
table". `l3_metrics` returns node/edge/branch counts only. `data/gold/entity_aliases.yaml`
exists and is unused by any metric.

- [ ] Implement alias accuracy in `l3_metrics` against `data/gold/entity_aliases.yaml`.
- [ ] Or remove the row from `Notes/09-k1-evaluation.md` if it is not worth measuring at this size.

### B3. Gate 4 cannot fail (tautology)
**Where:** `src/k1_pipeline/validate/gates.py:69`

```python
if node.node_type == NodeType.Process and node.safety_bounds:
```

It only inspects nodes that **already have** `safety_bounds`, then checks that a matching
edge exists. The stated purpose in `Notes/08-k1-pipeline.md` is the opposite: catch a thermal
Process that is *missing* its bounds. A thermal step whose bounds were never attached passes
the gate.

- [ ] Re-derive "is thermal" inside the gate (reuse `_THERMAL_KEYWORDS` from `dag_builder.py`,
      moved to a shared module) and fail when a thermal Process has no bounds.
- [ ] Add a test with a thermal Process and zero bounds; it must fail Gate 4.

### B4. `l1_metrics` conflates two different things
**Where:** `src/k1_pipeline/eval/metrics.py` — `l1_metrics`

`schema_valid_pct` is computed as "has a non-empty ingredients list", which is the
missing-ingredient check, not Pydantic schema validity. Step-count match and junk-step rate
from the protocol table are not implemented at all.

- [ ] Validate with `CanonicalRecipe.model_validate_json` for the real schema figure.
- [ ] Record junk-drop counts during L1 and persist them so the rate can be reported.

---

## C. Gaps against the plan

### C1. Entity resolution is exact-match only
**Where:** `src/k1_pipeline/fuse/entity_resolver.py`

The plan specifies embedding top-K retrieval followed by LLM pairwise disambiguation on the
ambiguous band (cosine 0.75–0.95). Only the frozen alias dictionary from `ontology.yaml` is
implemented. `sentence-transformers` is declared in `pyproject.toml` and never imported, and
`config/models.yaml` pins an embedding model that is never loaded.

- [ ] Implement embedding candidate retrieval + LLM pairwise on ambiguous pairs only.
- [ ] Or drop the dependency and the `embedding:` pin and state in the changelog that v1 is
      dictionary-only. For a single-dish corpus this may well be the right call.

### C2. The revision loop is a no-op re-roll
**Where:** `src/k1_pipeline/critic/critic.py` — `verify_recipe`, revise branch

On `revise` the code deletes the cached `.gen.json` and calls `extract_node` again with the
**identical** prompt. `critic_out.revision_instructions` is produced and then discarded, so
at temperature 0 the same output is very likely regenerated.

- [ ] Add a `revision_hint: str | None` parameter to `extract_node` / `_build_prompt` and
      inject the critic's instructions.
- [ ] Re-run the critic on the revised node and persist both passes
      (`*.critic.json` and `*.critic.r2.json`) so the loop is auditable.
- [ ] Cap at one revision, as specified.

### C3. Neo4j schema constraints file does not exist
**Where:** `src/k1_pipeline/store/writer.py:53` writes the header
`"// Schema constraints must be applied first (k1 validate --schema)"`

There is no constraints file and no `--schema` flag anywhere in `cli.py`. Ingesting into a
fresh database creates no uniqueness constraints or indexes.

- [ ] Add `config/graph_schema.cypher` (uniqueness on `node_id` per label, indexes on
      `node_type` and `canonical_action`). `Cooking-Advisor/config/graph_schema.cypher` is a
      reasonable starting point.
- [ ] Add `k1 store --apply-schema`, and fix or remove the header comment.

### C4. `ingest_neo4j` writes to `/tmp`
**Where:** `src/k1_pipeline/store/writer.py` — `ingest_neo4j`

It calls `write_cypher(graph, Path("/tmp/k1_neo4j_temp"))` and reads the file back rather than
using the string it just generated. Works, but leaves files outside the project and makes the
function harder to test.

- [ ] Have `write_cypher` return the Cypher string as well as the path, and pass it directly.

---

## D. Consistency and cleanup

- [ ] **`GoldNode` model does not match the gold JSON schema.** `models.py` declares
      `expected_pre_k2_labels: list[tuple[str, K2Label]]`; `data/gold/ANNOTATION_PROTOCOL.md`
      and `eval/metrics.py` use a nested `expected.pre_conditions` list of dicts.
      `GoldNode` is currently unused (metrics parses raw JSON). Align the model to the protocol
      and validate gold files with it, or delete the model.
- [ ] **Gold files are never schema-checked.** A typo in a hand-written gold file fails silently.
      Add `k1 eval --check-gold` that validates every `*.gold.json` before scoring.
- [ ] **Dead code:** `_build_nx` in `validate/gates.py` is defined and never called.
- [ ] **`viz/app.py` ignores `--run`.** `cli.py viz` forwards `-- --run <id>` but the app never
      parses `sys.argv`; the run is always chosen from the sidebar selectbox. Either parse it
      or drop the flag.
- [ ] **`pyproject.toml` has an empty `[tool.uv.sources]`** block that can be removed.
- [ ] **`requires-python = ">=3.11"`** but the local venv resolved to Python 3.14.3. Confirm the
      target version and pin it, so the thesis environment is reproducible.
- [ ] **`data/k1/graph.json` is intentionally not gitignored** (it is the committed artifact).
      Confirm that is what you want before the first commit that contains a real graph.

---

## E. To test once API keys are in place

Nothing in this list has been exercised yet — see Section G.

- [ ] **Smoke test on one recipe.** `k1 ingest` then `k1 extract` on `jamie_oliver` only.
      Inspect `L2/gen/*.gen.json` by hand before trusting any aggregate number.
- [ ] **Instructor schema adherence.** `ExtractedNode` asks the LLM to fill `node_id`,
      `recipe_id`, `step_number` and `extractor_model`, all of which are overwritten in
      `generator.py` immediately afterwards. Check whether the model wastes tokens or fails
      validation on them; consider a slimmer `LLMExtraction` model with the provenance fields
      added in Python.
- [ ] **`model_validator` retry behaviour.** `ExtractedNode` raises when a `Process` lacks
      pre/post conditions. Confirm Instructor retries cleanly rather than raising all the way up
      and killing the run.
- [ ] **Critic output quality.** Does `gemini-2.0-flash-lite` reliably return a
      `grounding_quote` that is actually a substring? If not, add a post-check.
- [ ] **Scraper coverage.** Which of the 10 allowlisted URLs yield schema.org JSON-LD and which
      fall through to the heuristic path? Bon Appétit and Serious Eats are known to be
      bot-hostile; have a manual HTML fallback ready.
- [ ] **Junk filter on real pages.** Confirm the Martha Stewart SEO tail is dropped and that no
      genuine step is lost.
- [ ] **Fingerprint merge rate.** Too aggressive collapses distinct techniques; too weak leaves
      duplicates. Inspect `L3/fused_dag.json` node count against the sum of per-recipe steps.
- [ ] **Branch preservation.** Confirm butter vs oil and low-heat vs high-heat survive fusion as
      distinct paths, since H3 depends on them.
- [ ] **Pyvis rendering at full size.** The graph has not been rendered with real data; check
      that ~70 nodes plus ingredient, tool and bound nodes stay readable.

---

## F. Open questions for the advisors

- [ ] **Is a single author-annotated gold set defensible for the dissertation?** The protocol
      supports adding a second annotator and Cohen's kappa later
      (`Notes/09-k1-evaluation.md`), but v1 is single-annotator. Worth raising early.
- [ ] **Is three gold recipes enough** to detect regressions between pipeline versions, given
      roughly 4–8 steps each?
- [ ] **Should non-scrambled egg dishes** (Menemen, Bhurji, tomato-egg) return later as explicit
      variant branches, or stay permanently out of scope? Currently excluded in
      `config/recipes.yaml`.
- [ ] **Does Fusion need `Ingredient` and `Tool` nodes at runtime,** or are they only useful for
      inspection? They add edges to every traversal.

---

## G. Done and verified

- [x] **Package scaffold** — `k1/` with `ingest`, `extract`, `critic`, `fuse`, `validate`,
      `store`, `viz`, `eval` subpackages and a `k1` console entry point.
- [x] **CLI registers all 10 commands** — `uv run k1 --help` verified:
      `run, ingest, extract, critic, fuse, validate, store, eval, viz, review`.
- [x] **Dependencies install** — `uv sync` completes; `uv.lock` committed.
- [x] **28/28 tests pass** — `uv run pytest tests/ -v`. Coverage is the K2 compile map
      (16 cases), the junk filter (6), and validation gates 2/3/5/6 (6).
- [x] **Frozen config in place** — `ontology.yaml` (3 node types, 5 edge types, K2 compile map,
      canonical entities), `physics_bounds.yaml` (62 °C, 70 °C, 140 °C, 150 °C, syneresis),
      `models.yaml` (generator and critic from different families), `recipes.yaml`
      (10 scrambled-egg URLs, 3 marked `gold: true`).
- [x] **Generator and critic are different model families** — `groq/llama-3.3-70b-versatile`
      vs `openrouter/google/gemini-2.0-flash-lite`, per the bias control in the eval protocol.
- [x] **Non-scrambled dishes excluded** from the corpus, unlike the Cooking-Advisor prototype.
- [x] **Cooking-Advisor graph is not ingested** — `data/kag/full_graph.json` is not read
      anywhere in `k1/`. Recorded in `CHANGELOG.md`.
- [x] **Docs written and cross-linked** — `Notes/08-k1-pipeline.md`, `Notes/09-k1-evaluation.md`,
      both added to `Notes/README.md`; `Notes/00-agent-briefing.md` points at `k1/`.
- [x] **Gold scaffolding ready** — `ANNOTATION_PROTOCOL.md`, `entity_aliases.yaml`, and three
      placeholder files for the held-out recipes.
- [x] **Bugs A1 and A2 reproduced locally** with scratch scripts, so they are confirmed rather
      than suspected.

### Explicitly not done yet

- [ ] No end-to-end run has been executed. No network fetch, no LLM call, no `graph.json`.
- [ ] Gold files are placeholders; no recipe has been annotated.
- [ ] The Streamlit app has never been launched against real data.
- [ ] Neo4j ingestion has never been run against a live database.

---

## Suggested order of work

1. Fix A1 and A2, with regression tests for both. Nothing downstream is trustworthy until then.
2. Smoke test on one recipe; read the extracted JSON by hand.
3. Fix B1 and B3 so the eval report is not misleading.
4. Annotate the three gold recipes (Section 1 of `Notes/09-k1-evaluation.md`).
5. Full `k1 run`, then `k1 eval`, then paste the summary into `CHANGELOG.md` under `k1-0.1.0`.
6. Work through Section C gaps and re-run; every change gets a new changelog entry.
