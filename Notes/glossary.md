# Glossary and notation

Use this spelling and casing in code, comments, and papers unless a library API forces otherwise.

## People and document

| Term | Meaning |
| --- | --- |
| PIC / PIC2 | Research plan document this corpus transcribes |
| IST / Técnico | Instituto Superior Técnico, Universidade de Lisboa |
| Centaur | Human + AI joint performance framing [12]; evaluation target is augmentation quality, not fully autonomous cooking |

## Research constructs

| Term | Meaning |
| --- | --- |
| Proactive RAG Activation | Deciding from vision alone when to retrieve and issue an unprompted intervention |
| Dual-tier knowledge retrieval | Fusing static recipe knowledge with live object-state perception |
| JITAI | Just-in-Time Adaptive Intervention: bind help to a task decision point [19] |
| Split-attention cost | Working-memory cost of a physical task plus an AI feedback channel [20] |
| Guidance relevance | Match of a suggestion to current `K2` and the applicable `K1` rule |
| Interruption timing accuracy | Alignment of `t_int` with the optimal point in a recipe-critical window |
| Perceived intrusiveness | How much an unprompted alert displaces primary-task attention |
| SES | State–Event–State: `S_{t-1} --E_t--> S_t` [18] |
| KAG | Knowledge Augmented Generation: `T_semantic = T_fact ⊕ T_concept` [33] |
| MCC | Multi-level Confidence Computing (MultiRAG) [35] |

## Architecture symbols

| Symbol | Meaning |
| --- | --- |
| `K1` | Static / cold recipe knowledge graph (Neo4j). Immutable during a session |
| `K2` | Live / hot object-state buffer. Bounded, time-indexed |
| `s_t` | Observed culinary state at time `t` |
| `u_t` | Explicit user prompt (reactive baseline only) |
| `φ(s_t, K1, K2)` | Endogenous predicate that may fire retrieval/intervention with no `u_t` |
| `D_t ∈ {0,1,2}` | Severity: 0 silent, 1 suggestion, 2 alert |
| `τ1`, `τ2` | Conflict-score thresholds mapping to `D_t` |
| `t_int` | Timestamp of a system intervention |
| `t*` | Annotator-defined optimal intervention time |
| `δt = \|t_int − t*\|` | Interruption timing error (lower is better) |
| `d_i` | ViT-based stream event-segmentation depth score at frame `i` |
| `T_fact` | Recipe action nodes (facts) |
| `T_concept` | Domain-physics / safety concept nodes |
| `T_semantic` | `T_fact ⊕ T_concept` |

## `K1` ontology (Kumbhakern et al. [14])

| Node type | Role |
| --- | --- |
| Process | A cooking action/process with optional `HAS_SAFETY_BOUND` |
| Transfer | Movement of an ingredient/item |
| Plate | Plating / serving |

Node fields: `pre_conditions`, `post_conditions`, `timing_constraints`.

Physics examples encoded on Process bounds:

- coagulation onset ≈ 62 °C
- full coagulation ≈ 70 °C
- Maillard browning onset

## `K2` record

```text
(entity_id, state_label, confidence, t)
```

Canonical egg trajectory: `liquid → coagulating → solid → scorched`.

## Models named in the PIC

| Name | Use |
| --- | --- |
| Gemma 4 E4B | Propose visual embeddings from `K1`; generate warning + suggestion when conflict is high. Local, 4-bit, open weights |
| CLIP | Local semantic matching for state labels |
| DINOv2 | Global frame context |
| SSIM | Consecutive-frame similarity for the Proactive Gate |
| ViT depth score | Event-boundary detection (StreamRAG-style) |

## Study conditions

| Factor | Levels |
| --- | --- |
| Memory tier (between subjects) | Single-tier (`K1` only) vs Dual-tier (`K1`+`K2`) |
| Intervention mode (within subjects) | Reactive (query-driven) vs Proactive (endogenous) |

Instruments: 7-point Likert (intrusiveness, relevance, helpfulness, annoyance), SUS (once), abbreviated NASA-TLX (Mental Demand + Frustration per block), semi-structured interview.

## Acronyms

| Acronym | Expansion |
| --- | --- |
| XR | Extended Reality |
| RAG | Retrieval-Augmented Generation |
| MLLM / VLM | Multimodal / vision-language model |
| FOV | Field of view |
| FPS | Frames per second |
| SSIM | Structural Similarity Index |
| SUS | System Usability Scale |
| NASA-TLX | NASA Task Load Index |
| DAG | Directed acyclic graph |
