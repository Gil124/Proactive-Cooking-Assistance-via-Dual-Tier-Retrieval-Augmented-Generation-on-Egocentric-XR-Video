# Changelog

All notable changes to the K1 Knowledge Graph pipeline are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [k1-0.1.0] — 2026-09-13

### Added
- Initial `k1/` package scaffold with four-layer pipeline architecture
- Root `CHANGELOG.md` (this file)
- `Notes/08-k1-pipeline.md` — K1 pipeline design spec
- `Notes/09-k1-evaluation.md` — evaluation protocol and bias controls
- `k1/TODO.md` — open work, known bugs, and verified status

### Known issues (see `k1/TODO.md` Section A)
- Critic temperature regex matches any 2–3 digit number in the serialised node, so confidence
  and duration values are misread as invented temperatures and nearly every node is rejected.
- REQUIRES edge construction can produce cycles between steps that both consume and produce the
  same K2 label, which makes validation Gate 2 fail and aborts `k1 run`.

No end-to-end run has been executed at this version; the graph has not yet been produced.

### Architecture decisions (frozen in this release)
- **Ontology:** schema-driven, not GraphRAG. Node types `Process`, `Transfer`, `Plate` per Kumbhakern [14] + PIC §4.6. Frozen in `k1/config/ontology.yaml`.
- **K2 compile map:** four labels only — `liquid`, `coagulating`, `solid`, `scorched`. Frozen in `k1/config/ontology.yaml`.
- **Physics bounds:** curated, not LLM-invented. Coagulation onset 62 °C, full coagulation 70 °C, Maillard browning onset ~140 °C. Frozen in `k1/config/physics_bounds.yaml`.
- **Corpus allowlist:** scrambled-egg recipes only. Non-scrambled-egg dishes (Menemen, Egg Bhurji, tomato-egg stir-fry, Huevos a la Mexicana) are **excluded**. Frozen in `k1/config/recipes.yaml`.
- **Cooking-Advisor graph not ingested.** `data/kag/full_graph.json` from the prototype is not re-used as the runtime K1 store. Re-extraction through this pipeline is required.
- **LLM policy:** construction may use Groq/OpenRouter. Runtime Fusion uses local Gemma 4 E4B only (unchanged).

### Model pins (k1-0.1.0)
See `k1/config/models.yaml` for pinned model IDs.

| Role | Model |
|---|---|
| Generator | `groq/llama-3.3-70b-versatile` |
| Critic | `openrouter/google/gemini-2.0-flash-lite` (different family) |
| Embedding (ER) | `sentence-transformers/all-MiniLM-L6-v2` (local) |

---

*Evaluation reports are appended as sub-sections of each version entry after a run completes.*
