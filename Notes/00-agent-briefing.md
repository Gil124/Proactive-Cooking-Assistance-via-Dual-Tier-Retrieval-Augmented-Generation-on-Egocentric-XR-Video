# Agent briefing

Read this before changing architecture, models, data schemas, or evaluation code. Full module detail is in [`04-architecture.md`](04-architecture.md). Research framing is in [`01-overview.md`](01-overview.md).

## What we are building

A **proactive multimodal cooking assistant** that:

1. Streams first-person XR video.
2. Tracks culinary object state in real time (`K2`).
3. Knows the recipe as a static knowledge graph (`K1`).
4. Decides **when** and **what** to say with **no user query**.
5. Delivers compact notifications only (never a conversation).

Canonical task: **one serving of scrambled eggs**. Do not expand recipe scope unless the author explicitly asks.

## Two research problems (must remain distinct)

| Problem | Meaning | System implication |
| --- | --- | --- |
| **Proactive RAG Activation** | Decide from vision alone when to retrieve and issue an unprompted safety alert or step correction | Endogenous trigger `φ(s_t, K1, K2)`; no `u_t` required |
| **Dual-tier knowledge retrieval** | Fuse static recipe knowledge with live object-state perception | Keep `K1` and `K2` as separate stores with different update rates; fuse at inference |

## Hard design constraints

Do not violate these. They govern every module.

1. **Closed-loop latency.** Capture → notification must stay well below the seconds-scale window of a cooking state transition.
2. **Bounded memory.** The egocentric stream is unbounded. `K2` must use clearable SES windows. No linear token growth.
3. **One-way output.** Compact notifications only. No dialogue. No waiting for a reply before continuing to monitor.
4. **Hardware-agnostic capture.** Uniform frame-packet interface. Do not couple the pipeline to one headset vendor.
5. **Hybrid compute.** Cheap loop on/near device (capture, transport, gate). Gemma 4 E4B on a **local GPU server**, invoked **only when `D_t ≥ 1`**. Not on-device full MLLM. Not cloud-every-frame.

## Pipeline (data flow)

```
XR camera
  → Capture (≈8 fps class sampling)
  → Transport (WebRTC or WebSocket)
  → Proactive Gate (SSIM + ViT depth score)   # discard most frames
  → Perception / Tier-2 Extractor             # CLIP + DINOv2 match vs visual proposals
  → K2 live buffer                            # (entity_id, state_label, confidence, t)
  → Fusion & Reasoning                        # conflict vs K1; Gemma 4 E4B only if conflict high
  → Intervention Policy                       # D_t ∈ {0, 1, 2}
  → Notification on XR                        # 1 = visual suggestion, 2 = visual + audio alert
```

`K1` is ingested **offline once** (Neo4j) and is **immutable during a session**.

## Severity variable `D_t`

| `D_t` | Meaning | Delivery |
| --- | --- | --- |
| `0` | Within tolerance | Silent; keep monitoring |
| `1` Suggestion | Minor, reversible deviation | Visual-only, peripheral, dismissible, no audio |
| `2` Alert | Irreversible / safety | Central visual + audio; non-dismissible until resolved or acknowledged |

Mapping: conflict score `< τ1` → 0; `τ1…τ2` → 1; `> τ2` **or** physics-bound violation on a `HAS_SAFETY_BOUND` edge → 2.

After any `D_t ≥ 1`, enter **cooldown suppression** until `K2` moves toward the expected `K1` post-condition or the window times out.

## Models and stores (named in the PIC)

| Role | Choice | Why |
| --- | --- | --- |
| Recipe parse + visual proposals + suggestion generation | **Gemma 4 E4B**, 4-bit, local GPU | Open weights, prompt injection of `K2` tokens, deterministic pinned checkpoint, ~10–12 GB VRAM |
| Local semantic state label | **CLIP** | Fine-grained (“liquid vs solid egg”) |
| Global frame context | **DINOv2** | Spatial scene structure (SPOC) |
| Static knowledge | **Neo4j** graph `K1` | Single traversal of facts + safety bounds |
| Live knowledge | In-memory bounded `K2` | Recency queries; clear completed steps |

Do not default to proprietary APIs for the reasoning loop. The PIC rejects them because they block token injection, determinism, and local latency.

## Schemas to implement

### `K2` record

```text
(entity_id, state_label, confidence, t)
```

Native unit is an SES transition: `S_{t-1} --E_t--> S_t`.

Example entity trajectory: `egg: liquid → coagulating → solid → scorched`.

### `K1` node (Process / Transfer / Plate)

- `pre_conditions`
- `post_conditions`
- `timing_constraints`
- Process nodes: `HAS_SAFETY_BOUND` edge (domain physics), e.g. coagulation onset ≈62 °C, full coagulation ≈70 °C, Maillard browning onset

Graph is **multi-path DAG** (variations such as butter vs oil, low-heat vs high-heat scramble), not a single linear recipe. Runtime selects the branch whose pre-conditions best match current `K2`.

KAG enrichment: `T_semantic = T_fact ⊕ T_concept` (recipe actions ⊕ physics/safety), ingested so Fusion does **one** graph lookup, not two stores.

### Gate signals

- **SSIM** between consecutive frames: low change → suppress (YETI-style, ~1 FPS class gate is acceptable).
- **ViT depth score** (StreamRAG-style event segmentation):

```text
d_i = (c_ViT_l_i + c_ViT_r_i − 2 c_ViT_i) / 2
```

Local maxima of `d_i` mark event onsets (pouring, stirring, overheating) and are forwarded.

### Fusion output to the LLM

When conflict exceeds threshold, Gemma receives:

1. Conflicting `K2` state (text)
2. Relevant `K1` subgraph serialised as text

And must produce **exactly two sentences**: one warning, one corrective suggestion.

## Perception: propose–match (Em-Garde)

- **Propose (offline / startup):** Gemma 4 E4B reads `K1` and builds a library of visual embeddings for expected transitions (e.g. “egg mixture loses transparency and firms”).
- **Match (streaming):** gated frames compared to that library with CLIP + DINOv2. Object-centric trajectories follow STEMO-Track / Tracking the Truth.

## Evaluation hooks (if you log behaviour)

The user study needs, per session:

- Intervention timestamps `t_int` (for `δt = |t_int − t*|`)
- Delivered messages and `D_t`
- Video log of the cook
- Condition flags: `{Reactive, Proactive} × {Single-tier, Dual-tier}`

Single-tier = `K1` recipe text only (no live `K2` fusion). Reactive = silent until queried. Dual-tier + Proactive = full system.

See [`05-evaluation.md`](05-evaluation.md).

## What not to build

- User-initiated chat as the main interaction model (reactive is only a **study baseline**)
- Retrieving from video history alone with no recipe graph
- A static AR step-by-step overlay with no live state
- On-headset 4B model inference
- Cloud MLLM on every frame
- Unbounded video-token context
- Multi-recipe or multi-dish evaluation in v1

## Implementation order implied by the Gantt

1. `K1` knowledge graph construction
2. `K2` live state buffer and perception pipeline
3. Fusion module and intervention policy
4. End-to-end integration, validation, pilot
5. Ethics, recruitment, data collection
6. Dissertation writing

Existing `Cooking-Advisor` work is a starting point for step 1 only.

## Notation cheat sheet

See [`glossary.md`](glossary.md). Minimum: `K1`, `K2`, `φ`, `D_t`, `τ1`, `τ2`, `u_t`, SES, JITAI.
