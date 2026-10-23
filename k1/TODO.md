# K1 Pipeline — TODO, Concerns, and Status

Living document. Update it in the same commit as the change it describes.
Design spec: [`../Notes/08-k1-pipeline.md`](../Notes/08-k1-pipeline.md) · Eval protocol: [`../Notes/09-k1-evaluation.md`](../Notes/09-k1-evaluation.md)

Status legend: `[ ]` open · `[~]` partially done · `[x]` done and verified

---

## D. Closing K1 (k1-0.4.2)

Review and measurement are done: 42/42 steps reviewed (14 from scratch), `k1 eval` tables
in `CHANGELOG.md` under k1-0.4.0, `graph.final.json` built and passing all 7 gates.

- [x] **`from_scratch` recipes confirmed** (`jamie_oliver`, `the_kitchn_soft_creamy`).
- [x] **Frozen run picked:** `scope02`.
- [x] **Every step reviewed** in the Gold set tab.
- [x] **2026-09-28 files resolved.** The 4 `epicurious_bain_marie` files (excluded recipe)
      and the 3 `PLACEHOLDER_*.md` files moved to `data/gold/archive/`.
- [x] **`k1 finalize` and `k1 eval` run**, tables copied into `CHANGELOG.md`.
- [x] **Cypher for the reviewed graph.** `k1 finalize` and `k1 store --final` write
      `data/k1/graph.final.cypher`. `k1 store --run` still writes `graph.cypher` from the
      pipeline graph. `--clear` removes a previous K1 graph before loading.
- [x] **Fusion query interface.** `k1_pipeline/query.py` (`K1Query.step(branch, node_id)`
      returns post-conditions, safety bounds and next node IDs). `tests/test_query.py`
      runs it against `graph.final.json`: every branch walks from one entry node to a
      Plate node at the goal state.
- [x] **Live Neo4j load of the reviewed graph** (2026-10-23, Neo4j 5.26 in Docker on the
      Mac mini): `k1 store --final --apply-schema --clear` gives 55 nodes, 302
      relationships, 6 constraints, matching `graph.final.json`. Next steps and safety
      bounds read from Neo4j agree with `K1Query` on every branch step. The first load
      lost one node and one constraint to a statement-splitting bug, now fixed.
- [ ] **Commit and tag** the closed K1 (`k1-1.0`). Author step.
- [x] **Never-ingested recipes.** The 10 allowlisted recipes that never ingested are marked
      `excluded` in `config/recipes.yaml`: not a variation of the dish (author decision,
      2026-10-23). Stale `gold: true` flags removed. Recorded in `Notes/10` B.4.
- [x] **Safety bounds on heat-off steps.** Only `pingo_doce` step 3 was wrong: a lost
      edit left the on-heat stirring step without heat/`heat_source`. Fixed; the
      remove-from-heat steps follow the residual-heat rule and are correct. Graph rebuilt
      (307 edges), Neo4j reloaded, eval rerun (CHANGELOG k1-0.4.2).
- [x] **Oregano** removed from the station (`config/dish.yaml`, `Notes/10` B.6).

### Known limitations (fix or state in the dissertation)

- [ ] **Transition-based node merging** is not implemented. Nodes still merge on the action
      string, so the 7 branches are 7 linear recipes with few shared nodes. Runtime branch
      selection therefore means picking a recipe.
- [ ] **Heat and duration as coupled parameter tuples** are not stored on nodes, so low-heat
      and high-heat branches cannot be told apart from the graph.
- [ ] **Timing is sparse and unreviewed.** 11 of 39 nodes have `timing_constraints`,
      carried over from the pipeline without review (k1-0.4.1).

## E. To test once API keys are in place

Updated after the first live smoke test (`smoke01`, k1-0.2.1). Items below are re-annotated
`[x]` (verified), `[~]` (partially verified / new follow-up found), or left `[ ]` (still open).
Full findings are in `CHANGELOG.md` under `k1-0.2.1`.

- [x] **Smoke test on one recipe.** Ran on all 10 allowlisted recipes, not just one.
      4/10 ingested cleanly; `L2/gen/*.gen.json` inspected by hand for `jamie_oliver`.
- [x] **Instructor schema adherence.** `temperature_c` behaved correctly in the live run:
      0 invented-temperature issues across 16 extracted steps, confirmed by `k1 eval`
      (`Invented temperature count: 0`).
- [x] **`model_validator` retry behaviour.** No `ExtractedNode` validation errors surfaced
      during the live run; Instructor's retry handled Process pre/post-condition requirements
      without crashing the pipeline.
- [x] **Critic output quality.** `gemini-2.0-flash-lite` is retired (see k1-0.2.1 model pin
      fix); `gemini-3.5-flash` was used instead and reliably returned grounded verdicts —
      100% span groundedness in the eval report. No post-check needed yet.
- [x] **Revision loop quality.** Confirmed positive: `jamie_oliver` steps 5 and 6 went from
      `revise` (broken `source_span`, later found to be a mojibake bug, see k1-0.2.1) to
      `accept` after the R2 pass once the underlying text was fixed. Other R2 verdicts stayed
      `revise` (kept, not rejected) after one round, matching the capped-revision design.
- [x] **Scraper coverage.** 4/10 succeed via schema.org JSON-LD or heuristic fallback
      (`jamie_oliver`, `serious_eats`, `food_network_goat_cheese`, `food52_fluffiest`).
      6/10 fail: `gordon_ramsay` (transient 503, retry should work), `bon_appetit` (0 steps
      survive junk filtering — needs a site-specific selector), and 4 sites return
      `403 Forbidden` (`martha_stewart`, `the_kitchn_soft_creamy`,
      `simply_recipes_creme_fraiche`, `food_wine_brown_butter` — bot-blocked, no schema.org
      fallback attempted yet). **New open item, see below.**
- [x] **Junk filter on real pages.** 0% drop rate across the 4 recipes that ingested
      (`k1 eval` → `Junk drop rate: 0.0%`) — no genuine step lost, but also nothing to prove
      the filter fires correctly on `martha_stewart`'s known SEO tail since that recipe
      403s before reaching the parser. Re-test once the 403 issue is fixed.
- [x] **Fingerprint merge rate.** 16 nodes fused from 16 extracted steps (4 recipes, no
      cross-recipe merges yet at this corpus size) — expected, since the 4 recipes ingested
      have little step-level overlap. Re-check once more of the 10 are ingesting.
- [ ] **Branch preservation.** Not yet meaningfully testable — only 4/10 recipes ingested,
      and none of the intended-to-be-parallel branches (butter vs oil, low vs high heat)
      landed in this batch. Re-test once scraper coverage improves.
- [ ] **Pyvis rendering at full size.** `graph.json` (16 nodes, 121 edges) now exists at
      `k1/data/k1/graph.json`, but the Streamlit app has not yet been launched against it.
- [x] **REQUIRES cycle-breaker tuning.** `L3/removed_edges.json` written; acyclicity gate
      (Gate 2) passed cleanly on the real 16-node/121-edge graph. No excessive edge removal
      observed at this size.

### Items found during the smoke test (k1-0.2.1) — status at k1-0.4.2

- [~] **Recipe URLs that fail to scrape.** Superseded by the never-ingested list in §D.
- [x] **Gold annotation.** Done in k1-0.4.0 (42/42 steps).
- [x] **Live Neo4j ingestion.** Done, see §D.
- [x] **Streamlit viz against real data.** Used for the whole review.

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

### k1-0.1.0 scaffold
- [x] **Package scaffold** — `k1/` with `ingest`, `extract`, `critic`, `fuse`, `validate`,
      `store`, `viz`, `eval` subpackages and a `k1` console entry point.
- [x] **CLI registers all 10 commands** — `uv run k1 --help` verified.
- [x] **Dependencies install** — `uv sync` completes.
- [x] **Frozen config in place** — `ontology.yaml`, `physics_bounds.yaml`, `models.yaml`,
      `recipes.yaml`.
- [x] **Generator and critic are different model families** — bias control confirmed.
- [x] **Non-scrambled dishes excluded** from the corpus.
- [x] **Cooking-Advisor graph is not ingested** by any `k1/` code.
- [x] **Docs written and cross-linked** — `Notes/08`, `Notes/09`, `Notes/README.md`,
      `Notes/00-agent-briefing.md`.
- [x] **Gold scaffolding ready** — `ANNOTATION_PROTOCOL.md`, `entity_aliases.yaml`, three
      placeholder files.

### k1-0.2.0 fix pass (all fixed and regression-tested; `uv run pytest tests/ -v` 52/52)
- [x] **A1 Temperature regex** — added `temperature_c: Optional[float]` to `ExtractedNode`;
      replaced whole-JSON digit scan with `physics.find_invented_temperatures` (unit-bearing
      only). `test_temperature_check.py` (10 cases).
- [x] **A2 REQUIRES cycles** — REQUIRES now built within-recipe (earlier producer → later
      consumer only); dedup via `set`; `_break_cycles` pass writes `L3/removed_edges.json`.
      `test_dag_cycles.py` (2 cases).
- [x] **Provenance drift** — all five parallel lists always appended together; `confidences`
      field added to `K1Node`; `mean_confidence` derived from `confidences`. `test_provenance_alignment.py` (2 cases).
- [x] **Gold recipe skips removed** — `extract` and `fuse` no longer skip gold recipes;
      hold-out means "not a few-shot example" only.
- [x] **B1 Safety-bound coverage** — `gold_comparison` now reads from `L3/fused_dag.json`.
- [x] **B2 Alias accuracy** — implemented in `l3_metrics` against `entity_aliases.yaml`.
- [x] **B3 Gate 4 tautology** — thermality re-derived from `physics.is_thermal_action`;
      thermal Process without bounds now fails. `test_gate4_thermal.py` (4 cases).
- [x] **B4 L1 metrics** — real Pydantic schema validation; `_filter_steps` returns
      `(kept, dropped_count)`; `ingest/runner.py` writes `L1/ingest_stats.json`.
- [x] **C1 sentence-transformers removed** — from `pyproject.toml` and `models.yaml`.
      ER is dictionary-only for v1; recorded in `CHANGELOG.md`.
- [x] **C2 Revision hint wired** — `revision_hint` threaded through `extract_node` and
      `_build_prompt`; second critic pass persisted as `*.critic.r2.json`.
- [x] **C3 Graph schema** — `config/graph_schema.cypher` added; `k1 store --apply-schema`
      flag added to CLI.
- [x] **C4 ingest_neo4j `/tmp` round-trip** — `write_cypher` returns `(text, path)`;
      `ingest_neo4j` uses the string directly.
- [x] **GoldNode aligned** — nested `expected` shape matching `ANNOTATION_PROTOCOL.md`.
      `test_gold_schema.py` (6 cases).
- [x] **`k1 eval --check-gold`** added.
- [x] **`_build_nx` deleted** from `gates.py`.
- [x] **`viz --run` parsing** — `app.py` parses `sys.argv` for `--run` to preselect run.
- [x] **Empty `[tool.uv.sources]` removed** from `pyproject.toml`.
- [x] **Redundant `CriticOutput` import removed** from `cli.py`.
- [x] **`.python-version` added** — pinned to `3.14.3`.

### k1-0.2.1 first live smoke test (`smoke01`) — full findings in `CHANGELOG.md`
- [x] **Model pins repaired.** Groq retired `llama-3.3-70b-versatile`; OpenRouter's free-tier
      fallback slugs went paid-only; Gemini retired `gemini-2.0-flash-lite` and deprecated the
      `google.generativeai` SDK. New pins: generator `groq/qwen/qwen3.8-27b`, critic
      `gemini/gemini-3.5-flash`. `_get_gemini()` now uses Google's OpenAI-compatible endpoint;
      `_get_groq()` switched to `instructor.Mode.JSON` (tool-calling mode failed on Groq's
      current OSS models).
- [x] **Mojibake bug fixed** (`ingest/fetcher.py`) — `requests` was decoding UTF-8 apostrophes
      as ISO-8859-1 when a site omitted an explicit charset header, breaking `source_span`
      grounding. Fixed via `resp.apparent_encoding`.
- [x] **`fuse` command's stale critic-verdict bug fixed** (`cli.py`) — it only ever checked
      the first-pass `.critic.json`, never `.critic.r2.json`. Fixed to prefer R2 when present.
- [x] **`l3_metrics` alias-accuracy crash fixed** (`eval/metrics.py`) — assumed the wrong
      YAML shape for `entity_aliases.yaml`. Fixed to read the real nested
      `{"aliases": [{"canonical": ..., "aliases": [...]}]}` schema. `test_alias_accuracy.py`
      (3 cases). **55/55 tests pass.**
- [x] **First full end-to-end run completed:** `k1 ingest → extract → critic → fuse →
      validate → store → eval` all ran successfully on `smoke01` (4/10 recipes; see Section E
      for scraper gaps on the other 6). All 6 validation gates passed. `graph.json` and
      `graph.cypher` exist at `k1/data/k1/`.

### k1-0.2.3 OpenRouter-only chat pins
- [x] **Generator and prose critic moved to OpenRouter.** Generator
      `openrouter/qwen/qwen3.5-397b-a17b` (JSON mode). Prose critic
      `openrouter/google/gemini-3.7-flash`. Jev gate unchanged. Fallbacks
      stay on OpenRouter and in the same family. See `CHANGELOG.md`.

### k1-0.2.2 Jev semantic gate
- [x] **Critic cascade.** Deterministic checks still run first. Jev
      (`typesafe/jev-1.13`) accepts a node on its own when every semantic Noul
      and the Choice probability of `accept` clear 0.85. Gemini runs only on a
      Jev miss or a Jev outage, because the revision loop needs written
      instructions. See `CHANGELOG.md` under `k1-0.2.2`.

### k1-0.4.2 closing pass
- [x] **Reviewed graph exported to Cypher** (`graph.final.cypher`, `k1 store --final`,
      `--clear`).
- [x] **`query.py` Fusion interface** and `tests/test_query.py`. **120/120 tests pass.**
- [x] **Neo4j loader bug fixed** (`store/writer.py` `cypher_statements`).
- [x] **Stale gold files archived** to `data/gold/archive/`.

---

## Suggested order of work

1. Commit and tag `k1-1.0`. From then on K1 changes only through a new version entry.
2. Hand over to K2: the label set K2 must produce is every `(entity, k2_label)` used in
   `graph.final.json` conditions (egg, butter, oil, salt, pepper) plus `scorched`.
