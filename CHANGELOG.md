# Changelog

All notable changes to the K1 Knowledge Graph pipeline are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [k1-0.2.1] — 2026-09-14

### Fixed — smoke test findings (provider drift since k1-0.2.0 was pinned)
First live smoke test run (`k1 ingest` → `k1 extract` → `k1 critic`) surfaced three
provider-side breaking changes that had happened since the k1-0.2.0 model pins were chosen:
- **Groq retired `llama-3.3-70b-versatile`.** `uv run k1 extract` returned
  `404 model_not_found`. Confirmed via `client.models.list()` that Groq's catalog no longer
  includes any Llama 3.3 model; current catalog is dominated by `openai/gpt-oss-*` and
  `qwen/qwen3.x-27b`.
- **OpenRouter's free-tier fallback slugs are gone.** `qwen/qwen-2.5-72b-instruct:free` and
  `meta-llama/llama-3.3-70b-instruct:free` both now 404 with "this model is unavailable for
  free" — OpenRouter moved them to paid-only slugs.
- **`gemini-2.0-flash-lite` retired; the `google.generativeai` SDK is fully deprecated.**
  Google's REST API confirmed via `GET /v1beta/models` that `gemini-2.0-flash-lite` no longer
  exists; the closest available replacements are `gemini-3.5-flash` / `gemini-3.5-flash-lite`.
  `google.generativeai.GenerativeModel` also emits a hard `FutureWarning` that all support has
  ended.

### Changed — `llm_client.py`
- `_get_gemini()` no longer uses the `google.generativeai` SDK. It now calls Google's
  OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`)
  through the same `instructor.from_openai` path already used for Groq/OpenRouter, so the
  model name is passed per-call instead of being fixed at client-construction time.
- `_get_groq()` switched from `instructor.Mode.TOOLS` to `instructor.Mode.JSON`. The Groq
  `openai/gpt-oss-120b` OSS model returned `400 Tool choice is required, but model did not
  call a tool` under tool-calling mode; JSON mode is reliable across Groq's current catalog.

### Changed — model pins (`k1/config/models.yaml`)
Generator/critic model-family separation (bias control) is preserved with new providers:

| Role | k1-0.2.0 pin (dead) | k1-0.2.1 pin (verified live) |
|---|---|---|
| Generator | `groq/llama-3.3-70b-versatile` | `groq/qwen/qwen3.8-27b` |
| Critic | `openrouter/google/gemini-2.0-flash-lite` | `gemini/gemini-3.5-flash` |
| Fallback generators | `openrouter/qwen/qwen-2.5-72b-instruct:free`, `openrouter/meta-llama/llama-3.3-70b-instruct:free`, `gemini/gemini-2.0-flash-lite` | `groq/qwen/qwen3.6-27b`, `gemini/gemini-3.5-flash-lite`, `openrouter/google/gemini-2.5-flash` |
| Fallback critics | `openrouter/qwen/qwen-2.5-72b-instruct:free`, `groq/llama-3.3-70b-versatile` | `gemini/gemini-3.5-flash-lite`, `openrouter/google/gemini-2.5-flash`, `groq/qwen/qwen3.8-27b` |

### Fixed — two more bugs found by running the smoke test to completion
- **Mojibake in scraped recipe text** (`ingest/fetcher.py`): `requests` defaults to
  ISO-8859-1 when a server's `Content-Type` header omits an explicit charset (the HTTP
  spec default), which mis-decoded UTF-8 curly quotes/apostrophes byte-by-byte
  (`’` U+2019, bytes `E2 89 99` → three separate Latin-1 codepoints `â\x80\x99`).
  This silently broke `source_span` substring grounding on `jamie_oliver` steps 5–6
  (`"youâ\x80\x99ve got"` never matches `"you've got"` in the raw HTML), which the critic
  correctly caught as Gate 6 `source_span not found` failures. Fixed by preferring
  `resp.apparent_encoding` (content-sniffed) over the header-default encoding before
  reading `resp.text`. Re-fetching `jamie_oliver` after the fix turned both failures into
  clean `accept` verdicts on the next critic pass.
- **`fuse` command ignored the critic's second-pass (`.critic.r2.json`) verdict**
  (`cli.py`): after a `revise` round, `fuse` only ever read the *first-pass*
  `*.critic.json` file and included the node if that verdict was not `reject` — it never
  looked for `*.critic.r2.json`. A node that was correctly `reject`-ed on the revision
  pass would still have been silently included in the fused graph, because its stale
  first-pass verdict was `revise`, not `reject`. Fixed to prefer the R2 file when present.
  Did not change node counts in this run (no R2 verdict happened to be a `reject`), but is
  a real latent correctness bug fixed regardless.
- **`l3_metrics` alias-accuracy crashed on the real gold file** (`eval/metrics.py`):
  assumed `entity_aliases.yaml` was a flat `{canonical: [alias, ...]}` mapping. The actual
  frozen file (`data/gold/entity_aliases.yaml`) uses
  `{"aliases": [{"canonical": ..., "aliases": [...]}, ...]}` (a list of dicts, chosen so
  each entry can later carry provenance/notes). Crashed `k1 eval` with
  `AttributeError: 'dict' object has no attribute 'lower'`. Fixed to read the correct
  nested shape. New tests: `test_alias_accuracy.py` (3 cases). **55/55 tests pass.**

### Verified live (full run, end to end)
- `k1 ingest --run smoke01`: 4/10 recipes ingested (`serious_eats`, `jamie_oliver`,
  `food_network_goat_cheese`, `food52_fluffiest`). The other 6 failed on the *scraper* side,
  not the pipeline: `gordon_ramsay` hit a transient 503; `bon_appetit` produced 0 steps after
  junk filtering (parser needs a site-specific selector); `martha_stewart`,
  `the_kitchn_soft_creamy`, `simply_recipes_creme_fraiche`, `food_wine_brown_butter` all
  returned `403 Forbidden` (bot-blocked). Tracked as a new open item.
- `k1 extract --run smoke01`: all 16 steps across the 4 ingested recipes extracted
  successfully once the model pins above were live. One Groq 429 (free-tier
  output-tokens-per-minute limit) was absorbed cleanly by the fallback chain.
- `k1 critic --run smoke01`: 11/16 accepted on first pass; all `revise` verdicts went
  through the R2 revision loop; **0 rejects**. Final: 68.8% accept, 31.2% revise-then-kept,
  0% reject.
- `k1 fuse --run smoke01`: 16 nodes, 121 edges, 4 branch labels.
- `k1 validate --run smoke01`: **all 6 gates passed** (first time this has been true —
  Gate 6 failed twice before the mojibake fix above).
- `k1 store --run smoke01 --no-neo4j`: `graph.json` and `graph.cypher` written to
  `k1/data/k1/`.
- `k1 eval --run smoke01`: L1 schema-valid 100%, L2 span-groundedness 100%, K2-label
  validity 100%, invented-temp count 0, L3 alias accuracy 70.2% (47 aliases checked),
  L4 all gates passed. Gold comparison: 0 gold recipes evaluated — none of the 3 gold
  recipes (`serious_eats`, `gordon_ramsay`, `bon_appetit`) have been hand-annotated yet, and
  `gordon_ramsay`/`bon_appetit` also failed to ingest this run (see above). `serious_eats`
  did ingest and extract but has no `*.gold.json` file yet.

### Not yet done
- Junk-filter / scraper fixes for the 6 recipes that failed to ingest.
- Gold annotation for the 3 gold recipes (needed before `gold_comparison` reports anything).
- Live Neo4j ingestion (`--apply-schema` path) has not been exercised.
- Streamlit viz has not been launched against this run's `graph.json`.

---

## [k1-0.2.0] — 2026-09-13

### Fixed — blocking bugs
- **A1 Temperature regex** (`critic.py`, `eval/metrics.py`): bare-number scan over the
  whole JSON was replaced with `physics.find_invented_temperatures`, which only checks
  unit-bearing patterns (`\d{1,4}°?[CF]`) in free-text fields, plus the new explicit
  `temperature_c: Optional[float]` field on `ExtractedNode`. `confidence=0.95` and
  `duration_s=90` no longer trigger false positives.
- **A2 REQUIRES cycles** (`fuse/dag_builder.py`): REQUIRES edges are now built within a
  single recipe, from the earlier producing step to the later consuming step.
  A `_break_cycles` pass removes the minimum edge set (REQUIRES preferred over NEXT,
  lowest weight first) to guarantee acyclicity. Removed edges are written to
  `L3/removed_edges.json`. All edges are deduplicated via a `(from, to, type)` set.

### Fixed — additional bugs found during review
- **Provenance list drift** (`fuse/dag_builder.py`): all five parallel provenance lists
  (`source_recipe_ids`, `source_step_indices`, `source_spans`, `extractor_models`,
  `critic_verdicts`) are now appended unconditionally on every merge observation.
  Added `confidences: list[float]` to `K1Node`; `mean_confidence` is derived from it.
  Deduplicated only at display time in `store/writer.py`.
- **Gold recipes skipped** (`cli.py`): `extract` and `fuse` no longer skip gold recipes.
  Gold hold-out means "never used as a few-shot example", not "never extracted or graphed".

### Fixed — wrong metrics (B1–B4)
- **B1** `gold_comparison` now reads `safety_bounds` from `L3/fused_dag.json` (via
  `source_recipe_ids` + `source_step_indices`), not from L2 `.gen.json` artifacts.
- **B2** Alias accuracy implemented in `l3_metrics` against `data/gold/entity_aliases.yaml`.
- **B3** Gate 4 re-derives thermality with `physics.is_thermal_action`; a thermal `Process`
  with no `safety_bounds` now actually fails the gate.
- **B4** `l1_metrics` validates with `CanonicalRecipe.model_validate_json` (real schema
  check); `_filter_steps` returns `(kept, dropped_count)`; runner writes `L1/ingest_stats.json`.

### Added — plan gaps (C1–C4)
- **C2** `revision_hint` threaded through `extract_node` / `_build_prompt`; second critic
  pass persisted as `*.critic.r2.json`.
- **C3** `config/graph_schema.cypher` added (uniqueness constraints + indexes for Neo4j 5.x);
  `k1 store --apply-schema` flag added.
- **C4** `write_cypher` returns `(text, path)`; `ingest_neo4j` uses the string directly.

### Added — cleanup (D)
- `GoldNode` aligned to nested `expected` shape from `ANNOTATION_PROTOCOL.md`.
- `k1 eval --check-gold` validates every `*.gold.json` before scoring.
- Dead `_build_nx` function deleted from `gates.py`.
- `viz/app.py` parses `sys.argv` for `--run` to preselect the run.
- Empty `[tool.uv.sources]` block removed from `pyproject.toml`.
- Redundant `from k1_pipeline.critic.critic import CriticOutput` import removed from `cli.py`.
- `.python-version` added, pinning interpreter to `3.14.3`.

### Changed — decisions
- **Entity resolution is dictionary-only for v1.** `sentence-transformers` removed from
  `pyproject.toml` and the `embedding:` block removed from `models.yaml`. The fixed alias
  dictionary from `ontology.yaml` is sufficient for a single-dish corpus.
- **Gold recipes are extracted and graphed.** Hold-out strictly means they are never placed
  in few-shot prompt examples. Documented in `Notes/09-k1-evaluation.md`.

### Regression tests (52/52 pass)
New: `test_temperature_check.py` (10), `test_dag_cycles.py` (2), `test_gate4_thermal.py` (4),
`test_provenance_alignment.py` (2), `test_gold_schema.py` (6). All 28 pre-existing tests
continue to pass.

### Model pins (k1-0.2.0)
See `k1/config/models.yaml`.

| Role | Model |
|---|---|
| Generator | `groq/llama-3.3-70b-versatile` |
| Critic | `openrouter/google/gemini-2.0-flash-lite` (different family) |
| Embedding (ER) | _removed — dictionary-only in v1_ |

No end-to-end run has been executed at this version; the graph has not yet been produced.

---

## [k1-0.1.0] — 2026-09-13

### Added
- Initial `k1/` package scaffold with four-layer pipeline architecture
- Root `CHANGELOG.md` (this file)
- `Notes/08-k1-pipeline.md` — K1 pipeline design spec
- `Notes/09-k1-evaluation.md` — evaluation protocol and bias controls
- `k1/TODO.md` — open work, known bugs, and verified status

No end-to-end run has been executed at this version; the graph has not yet been produced.
(Two blocking bugs found at scaffold time — temperature regex false positives and
REQUIRES-edge cycles — are recorded and fixed under `k1-0.2.0` above.)

### Architecture decisions (frozen in this release)
- **Ontology:** schema-driven, not GraphRAG. Node types `Process`, `Transfer`, `Plate` per Kumbhakern [14] + PIC §4.6. Frozen in `k1/config/ontology.yaml`.
- **K2 compile map:** four labels only — `liquid`, `coagulating`, `solid`, `scorched`. Frozen in `k1/config/ontology.yaml`.
- **Physics bounds:** curated, not LLM-invented. Coagulation onset 62 °C, full coagulation 70 °C, Maillard browning onset ~140 °C. Frozen in `k1/config/physics_bounds.yaml`.
- **Corpus allowlist:** scrambled-egg recipes only. Non-scrambled-egg dishes (Menemen, Egg Bhurji, tomato-egg stir-fry, Huevos a la Mexicana) are **excluded**. Frozen in `k1/config/recipes.yaml`.
- **Cooking-Advisor graph not ingested.** `data/kag/full_graph.json` from the prototype is not re-used as the runtime K1 store. Re-extraction through this pipeline is required.
- **LLM policy:** construction may use Groq/OpenRouter. Runtime Fusion uses local Gemma 4 E4B only (unchanged).

### Model pins (k1-0.1.0)
See `k1/config/models.yaml` for pinned model IDs. Superseded by `k1-0.2.1` once Groq
retired these models and the Gemini SDK was deprecated — see that entry above.

| Role | Model |
|---|---|
| Generator | `groq/llama-3.3-70b-versatile` |
| Critic | `openrouter/google/gemini-2.0-flash-lite` (different family) |
| Embedding (ER) | `sentence-transformers/all-MiniLM-L6-v2` (local) |

---

*Evaluation reports are appended as sub-sections of each version entry after a run completes.*
