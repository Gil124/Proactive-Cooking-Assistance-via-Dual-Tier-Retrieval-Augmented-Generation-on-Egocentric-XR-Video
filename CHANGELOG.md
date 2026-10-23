# Changelog

All notable changes to the K1 Knowledge Graph pipeline are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [k1-0.4.1] — 2026-10-12

### Added — every recipe ends at the goal
A recipe with no `Plate` step gets one closing "transfer eggs to plate" step by rule
(`scope.complete_to_goal`), in fusion and in `k1 finalize`. It keeps the egg state of the
last step, has no source span, and names `rule/goal_completion` as its extractor. A recipe
that never reaches a goal state is reported in `L3/goal_completion.json`, not plated.
In the reviewed `scope02` graph four recipes needed it (`continente`, `jamie_oliver`,
`love_and_lemons`, `tudo_gostoso`); they share one node. Reviewed graph: 39 nodes, 290 edges.
The frozen `scope02` pipeline graph was not rebuilt, so it does not have this node.

### Fixed
- **Timing lost in the reviewed graph.** The review form has no timing field, so
  `k1 finalize` now carries the pipeline's `timing_constraints` over, unreviewed.

---

## [k1-0.4.0] — 2026-10-11

### Added — review workflow that measures itself
K1 construction is not a thesis contribution, so the evaluation asks one question: was
building K1 with the pipeline and correcting it by hand worth it? Protocol in
`Notes/09-k1-evaluation.md`.

- A reviewed step (`data/gold/*.gold.json`) is now both the gold label and the corrected
  step the final graph is built from. New fields: `expected.in_scope`, `mode`,
  `seconds_spent`, `seeded_from_run`, `definition_version`.
- **Gold set tab** rewritten: one step at a time, every in-scope recipe queued, a keep/drop
  checkbox, active time recorded with an idle cap. Recipes under `from_scratch` in
  `config/gold_review.yaml` start blank with the pipeline output hidden, here and on the
  Review tab.
- **`k1 finalize --run <id>`** builds `data/k1/graph.final.json` from the reviewed steps,
  keeps the pipeline graph as `graph.auto.json`, and runs the gates on the final graph.
- **`k1 eval`** now reports accuracy (keep/drop agreement, per-field accuracy, condition
  P/R/F1), correction effort (edits per step and by field), time (per mode, with the saving
  against annotating by hand), and a pipeline-vs-reviewed graph comparison. Also written as
  `eval/correction.json` and `eval/correction_steps.csv`.

### Changed
- `config/gold_review.yaml` no longer lists candidates. It names the `from_scratch` recipes
  (`jamie_oliver`, `the_kitchn_soft_creamy`) and the idle cap.
- Gold files saved under another `definition_version` are out of date: kept on disk, shown
  as such, and left out of every metric. The 15 files from 2026-09-28 are in this state.
- The old "Gold Comparison" table is replaced by the "Human review" section of the report.

### Fixed
- **HTML entities in step text.** JSON-LD text kept `&#x27;` and `&oacute;`, so a quote the
  model wrote with a real apostrophe failed the substring check. Decoded at ingest; the
  three affected `canonical.json` files were decoded in place (step numbers unchanged).
- **Typographic quotes in `source_span`.** A span that differs from the step only by curly
  versus straight quotes or dashes is replaced by the verbatim slice
  (`generator.ground_span`). This had failed Gate 6 on `jamie_oliver` step 5.

### Changed — `serious_eats` excluded after review (2026-10-12)
The scraper returned the whole recipe as a single step, twice, so no step-level label can
be right or wrong for it. It is excluded in `recipes.yaml` and reported as an ingest
failure (1 of the 8 recipes that ingested), not scored as an extraction error. The frozen
`scope02` pipeline graph still contains its one node. Review queue: 7 recipes, 42 steps.

### Review of run `scope02` (2026-10-12)
42 of 42 steps reviewed by the author; 14 from scratch, 28 corrected. Full tables in
`k1/data/artifacts/runs/scope02/eval/report.md`.

| Metric | All reviewed | From scratch only |
|---|---|---|
| Keep/drop decision agrees | 97.6% | 100.0% |
| `node_type` correct | 84.6% | 84.6% |
| `pre_conditions` F1 | 0.724 | 0.722 |
| `post_conditions` F1 | 0.644 | 0.500 |
| Steps needing no change, ignoring wording | 35.7% | 28.6% |

77 edits, 1.83 per step. Mean time per step: 45.4 s corrected (median 36.9 s) against
75.2 s from scratch (median 69.6 s), a 40% saving. Times include a second pass in which
the author fixed inconsistencies found in a review of the gold set. Reviewed graph:
39 nodes, 302 edges, all 7 gates passed, written to `k1/data/k1/graph.final.json`.

Caveats. 25 rule-based changes were applied to 18 gold files after the timed review, at
the author's request, and are noted in each file: heat ticked on on-heat steps,
`heat_source` listed on those steps, one wording fix. They are in the edit counts
(`tools`, `has_safety_bound`) but not in the times. `finalize` now takes safety bounds from
the reviewer's heat tick instead of the action wording. The "identical nodes" figure is
sensitive to wording because node ids hash the action phrase.

### Run `scope02` (k1-0.3.0 + k1-0.4.0, frozen for review)
8 recipes, 44 steps. 37 nodes, 237 edges, 4 nodes shared by more than one recipe. All 7
gates passed. Ingredient nodes: egg, salt, oil, pepper, butter. Tool nodes: bowl, whisk,
pan, heat_source, spatula, plate. One step dropped by the scope rule, one rejected by the
critic. Span groundedness 100%, no invented temperatures. Critic first pass: 54.5% accept,
43.2% revise, 2.3% reject. Before the scope rule the same pipeline gave 53 nodes from 11
recipes with 25 ingredient and 27 tool names. No steps reviewed yet.

---

## [k1-0.3.0] — 2026-10-11

### Added — the graph only holds what is a recipe variation
Definition in `Notes/10-recipe-variation.md`. Enforcement described in
`Notes/08-k1-pipeline.md` ("Scope enforcement").

- **`config/dish.yaml`**: the dish specification. Ingredients: egg, salt, pepper, oregano,
  butter, oil. Utensils: pan, bowl, spatula, whisk, plate, heat_source. Goal: eggs
  coagulating or solid, on the plate.
- **`k1_pipeline/scope.py`**: entities are checked against the inventory after alias
  resolution; `action_phrase` is scanned for known out-of-inventory terms.
- **Generator** is told the inventory, extracts only the inventory part of a step, and sets
  the new `in_scope` flag to false when nothing remains.
- **Critic**: an `action_phrase` naming an out-of-inventory item is a deterministic `revise`.
  Jev and the generative critic are told that left-out items are intended.
- **Fuse** trims and drops before building the DAG and writes `L3/scope_report.json`.
- **Gate 7** fails the graph on any out-of-inventory entity or term, or any node from an
  excluded recipe.

### Changed
- **Five recipes excluded** with an `excluded:` reason in `recipes.yaml`:
  `epicurious_bain_marie`, `heston_blumenthal` (double boiler), `food_network_goat_cheese`
  (charcoal griddle, 16 eggs), `couple_cooks_goat_cheese`, `food52_fluffiest` (defined by
  out-of-inventory ingredients). Every stage skips them.
- **`ontology.yaml` aliases extended**: Portuguese names, parts of the egg, `pepper`,
  `oregano`, `heat_source`, and `jug` as `bowl`.

---

## [k1-0.2.10] — 2026-09-28

### Added — tools on a gold step
The Gold set tab has a Tools table. Saved names go in `expected.tools`. They are not given a k2 state.

---

## [k1-0.2.9] — 2026-09-28

### Fixed — chat calls time out
OpenRouter chat clients now give up after 180 seconds. A laptop sleep had left one critic call waiting on a dead connection.

---

## [k1-0.2.8] — 2026-09-27

### Added — Gold set review tab
`k1 viz` has a Gold set tab for the five recipes in `k1/config/gold_review.yaml`.
Saving a step writes `data/gold/{recipe_id}_stepNN.gold.json` from the form, not from the model output.

---

## [k1-0.2.7] — 2026-09-27

### Added — technique variants that are still scrambled eggs
Training corpus only. Global dishes that are not a plain scramble stay out of
the allowlist (see Notes/08 corpus scope).

| recipe_id | variant_label |
|---|---|
| `alton_brown` | High-to-low heat |
| `ina_garten_fluffy` | Extra yolks half-and-half |
| `epicurious_bain_marie` | Bain-marie custard |
| `heston_blumenthal` | Brown butter bain-marie |
| `couple_cooks_goat_cheese` | Goat cheese |

---

## [k1-0.2.6] — 2026-09-27

### Added — eight scrambled-egg recipes
Training corpus only (`gold: false`). None of these are few-shot examples or gold hold-outs.

| recipe_id | variant_label |
|---|---|
| `recipe_tin_eats` | Butter milk medium |
| `love_and_lemons` | Milk olive-oil |
| `inspired_taste` | No-dairy low-heat |
| `woks_of_life` | Butter low-heat |
| `pingo_doce` | Butter medium-low |
| `continente` | Home-style |
| `tudo_gostoso` | Late milk low-heat |
| `primor` | Whites-first butter milk |

---

## [k1-0.2.5] — 2026-09-27

### Changed — preparations are states, new ingredients stay
`toast` was fused as its own ingredient beside `bread`. A preparation is now
an alias of the base food: `toast`, `buttered toast`, and `toasted bread`
resolve to `bread`; `scrambled_eggs` resolves to `egg`. Names that are not
aliases are kept, so goat cheese, cream, and herbs remain new entities.

The generator prompt and the critic, including a new Jev Noul
`entities_are_objects`, say the same thing. `baked_bread` compiles to `solid`
instead of the unknown-state default `liquid`.

---

## [k1-0.2.3] — 2026-09-26

### Changed — chat models are OpenRouter-only
Generator and prose critic no longer call Groq or the Gemini API directly.
Both go through `https://openrouter.ai/api/v1`, same key as the Jev gate.
Family split is unchanged: Qwen extracts, Gemini writes revision text, Jev
only classifies.

| Role | k1-0.2.2 pin | k1-0.2.3 pin |
|---|---|---|
| Generator | `groq/qwen/qwen3.8-27b` | `openrouter/qwen/qwen3.5-397b-a17b` |
| Prose critic | `gemini/gemini-3.5-flash` | `openrouter/google/gemini-3.7-flash` |
| Semantic gate | `typesafe/jev-1.13` | unchanged |
| Fallback generators | Groq Qwen 3.6, Gemini 3.5 Flash Lite, OpenRouter Gemini 2.5 Flash | `openrouter/qwen/qwen3.6-flash`, `openrouter/qwen/qwen3.5-flash-02-23` |
| Fallback critics | Gemini 3.5 Flash Lite, OpenRouter Gemini 2.5 Flash, Groq Qwen 3.8 | `openrouter/google/gemini-3.5-flash` |

Qwen slugs use Instructor JSON mode. Tool calling on that family already
failed on Groq in k1-0.2.1. Gemini slugs still use tool calling.
Fallbacks stay in the same family as the primary, so a fallback no longer
lets Qwen grade a Qwen extraction.

Slugs confirmed on the OpenRouter model pages:
[qwen/qwen3.5-397b-a17b](https://openrouter.ai/qwen/qwen3.5-397b-a17b),
[google/gemini-3.7-flash](https://openrouter.ai/google/gemini-3.7-flash).
Not yet verified with a live completion: the OpenRouter key in `k1/.env`
was over its total limit during k1-0.2.2.

The first live attempt (`or01`) authenticated, then died on
`food52_fluffiest` step 3 with `IncompleteOutputException`: Qwen 3.5 spends
reasoning tokens inside `max_tokens`, and 2048 cut the JSON off. Extraction
cap is now 16384 and the prose critic cap is 8192. A truncated completion
falls through to the next model instead of aborting the run.

---

## [k1-0.2.2] — 2026-09-26

### Added — Jev semantic gate in front of the generative critic
The L2 critic was spending a Gemini call on every node that already passed the
deterministic checks, including the ones a yes/no judgment can accept. Those
judgments are now a [Jev](https://openrouter.ai/docs/guides/community/jev) request
(`typesafe/jev-1.13` via `POST https://openrouter.ai/api/alpha/decisions`). Jev
does not write text, so it only decides whether the extraction is faithful.
Gemini still writes `revision_instructions` and `grounding_quote` when it is not.

Cascade in `critic/critic.py`, after the existing deterministic pre-checks:

1. Jev is asked four Noul questions in one request — node type, pre-conditions,
   post-conditions, action faithfulness — plus a Choice of `accept` / `revise` /
   `reject`. The questions are answered independently, so the code requires them
   to agree rather than asking the Choice to read the Nouls.
2. The node is accepted with `critic_model` set to the served Jev id when every
   Noul and the Choice probability of `accept` are at least `noul_accept_threshold`
   (0.85 in `config/models.yaml`). The threshold is set high because a false
   accept never gets a second look, while a false escalate only costs one Gemini
   call. `grounding_quote` is the `source_span`, which the deterministic check
   has already shown is a substring of the step.
3. Otherwise, or if the Decisions API errors, the existing Gemini critic runs.
   The prompt includes the Jev flags that fell short. Probabilities are stored
   on `CriticOutput.jev_scores` either way, and are empty when the deterministic
   checks decided the verdict before Jev ran.

Generator stays Qwen and the prose critic stays Gemini, so the two text models
remain different families. Jev is a third family and is not on the generator
fallback list. A Jev outage does not fail the pipeline.

### Tests
`tests/test_jev_critic.py`: threshold logic, the Decisions API request shape,
and the three cascade paths (deterministic skip, Jev accept, Jev miss or outage
falling through to Gemini).

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
