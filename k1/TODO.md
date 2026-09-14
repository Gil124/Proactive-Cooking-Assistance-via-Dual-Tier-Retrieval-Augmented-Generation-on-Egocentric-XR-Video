# K1 Pipeline — TODO, Concerns, and Status

Living document. Update it in the same commit as the change it describes.
Design spec: [`../Notes/08-k1-pipeline.md`](../Notes/08-k1-pipeline.md) · Eval protocol: [`../Notes/09-k1-evaluation.md`](../Notes/09-k1-evaluation.md)

Status legend: `[ ]` open · `[~]` partially done · `[x]` done and verified

---

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

### New items found during the smoke test (k1-0.2.1)

- [ ] **6/10 recipe URLs fail to scrape.** `gordon_ramsay` (503, likely transient — retry),
      `bon_appetit` (0 steps after junk filtering — needs a per-site selector or manual HTML
      fallback), `martha_stewart` / `the_kitchn_soft_creamy` / `simply_recipes_creme_fraiche` /
      `food_wine_brown_butter` (403 Forbidden — bot-blocked, consider a different User-Agent,
      a headless browser, or manually saved HTML as a last resort).
- [ ] **Gold annotation still not done.** `k1 eval` reports `Gold recipes evaluated: 0`.
      `serious_eats` did ingest and extract successfully in this run, so at minimum that one
      could be annotated next; `gordon_ramsay` and `bon_appetit` need the scraper fix first.
- [ ] **Live Neo4j ingestion untested.** `k1 store --apply-schema` was not exercised against
      a live database this run (`--no-neo4j` was used deliberately to keep the smoke test
      fast). Worth doing once the corpus is bigger.
- [ ] **Streamlit viz untested against real data.** `k1 viz --run smoke01` has not been
      launched yet.

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

### Explicitly not done yet

- [ ] 6/10 recipe URLs still fail to scrape (503 / 403 / junk-filtered-to-zero) — see
      Section E "New items found during the smoke test".
- [ ] Gold files are still placeholders; no recipe has been annotated, so `gold_comparison`
      reports 0 recipes evaluated even though the pipeline itself now runs cleanly.
- [ ] The Streamlit app has never been launched against real data.
- [ ] Neo4j ingestion (including the new `--apply-schema` path) has never been run against a
      live database.

---

## Suggested order of work

1. Fix the 6 failing scraper URLs (503 retry, junk-filter selector, 403 bot-blocking).
2. Annotate the three gold recipes (Section 1 of `Notes/09-k1-evaluation.md`) — at least
   `serious_eats`, which already ingests and extracts cleanly.
3. Re-run `k1 run` on the full corpus, then `k1 eval`, and paste the summary into
   `CHANGELOG.md` under a new version entry.
4. Launch `k1 viz --run <id>` and `k1 store --apply-schema` against a live Neo4j instance.
