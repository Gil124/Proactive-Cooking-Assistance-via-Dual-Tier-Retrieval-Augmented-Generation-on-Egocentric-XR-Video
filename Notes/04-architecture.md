# System architecture

The three literature gaps require an agent that watches continuously, knows what the recipe expects, tracks what the food is doing, and acts before failure is irreversible, **with no user prompt**.

Every labelled module below corresponds to Figure 1 in the PIC (“High Level System Architecture Overview”).

## Governing constraints

| Constraint | Requirement |
| --- | --- |
| Closed-loop latency | Capture → notification well below the seconds-scale cooking transition window |
| Bounded memory | Infinite ego stream must be segmented into clearable windows; no linear token growth [1, 18] |
| One-way output | Compact notifications only; never open a dialogue |
| Hardware-agnostic capture | Pipeline decoupled from any specific headset |

## 4.1 System overview

```text
Capture
  → Transport (low-latency)
  → Proactive Gate          # drop redundant frames before expensive inference
  → Perception / Tier-2 Extractor
       updates K2 (live object-state buffer)
  → Fusion & Reasoning
       compare K2 vs K1 (static recipe store)
       on conflict, invoke multimodal LM for a suggestion
  → Intervention Policy
       φ(s_t, K1, K2) → D_t ∈ {0, 1, 2}
  → Notification to XR      # only if D_t ≥ 1
```

## 4.2 Capture module

- Head-worn XR egocentric camera: continuous first-person video.
- Distinguishing properties vs third-person: rapid FOV shifts, hand occlusions, motion blur, non-stationary workspace [7].
- Sampling: research on frame-density saturation shows **≈8 frames per short interval** hits a performance ceiling for real-time egocentric assistants; denser sampling adds latency without accuracy benefit [6]. Set capture rate in this range.
- Exposes a **uniform frame-packet interface** to Transport, independent of headset vendor.

## 4.3 Transport module

- Forward frame packets XR → processing node over a low-latency channel: **WebRTC or WebSocket**, depending on deployment.
- **Only gated frames** go to heavy processing. Gate-suppressed frames are discarded at source to cut bandwidth and RTT.
- Network round-trip is a **fixed term** in the closed-loop latency budget.

## 4.4 Proactive Gate

First and cheapest stage. Continuous loop. Screens every frame before any model inference. Same role as YETI’s binary gate [8].

### Signal 1 — frame similarity

Pixel-level **SSIM** between consecutive frames. Low-change (high-SSIM / redundant) frames are suppressed [8].

### Signal 2 — depth score (event boundaries)

ViT-based similarity, analogous to StreamRAG Stream Event Segmentation [1]:

```text
          c_ViT_l_i + c_ViT_r_i − 2 c_ViT_i
d_i  =  ------------------------------------
                         2
```

Frames at **local maxima of `d_i`** mark onset of a new cooking event (pouring, stirring, overheating) and are forwarded.

### Throughput rationale

Together the two signals are a coarse binary screen that keeps throughput stable.

- YETI: **1 FPS SSIM gate** competitive with heavy frameworks on recall/F1.
- Em-Garde: decoupling cheap gating from expensive reasoning sustains **10–15 fps on a single GPU** because the streaming loop never calls the large model [25].

## 4.5 Perception and Tier-2 Extractor

Implements Em-Garde **propose–match** [25]: one-time heavy reasoning vs lightweight continuous matching.

### Propose phase (offline / startup)

Before the session, **Gemma 4 E4B** (open-weight 4B multimodal model) parses `K1` and builds a library of **visual proposals**: embeddings of the expected perceptual signature of each recipe transition.

Example: “egg mixture loses transparency and firms” → concrete visual embedding.

Why Gemma 4 E4B, not a proprietary API:

1. Open weights let `K2` object-centric trajectory tokens be injected **directly** into the prompt alongside image tokens.
2. Pinned-checkpoint inference is deterministic and reproducible.
3. 4B at 4-bit quantisation fits a local GPU server; no cloud round-trip per alert [2].

VRAM envelope cited: **≈10–12 GB** at 4-bit.

### Match phase (streaming)

For each gated frame, a lightweight embedding comparator checks the visual-proposal library.

State-label assignment (SPOC recommendation [15]):

- **CLIP** — local semantic matching (“is this egg liquid or solid?”)
- **DINOv2** — global frame context / spatial scene structure

Object-centric trajectories per tracked entity, unary property transitions, consistent with STEMO-Track / Tracking the Truth chunk-wise state extraction [10].

Write to `K2`:

```text
(entity_id, state_label, confidence, t)
```

Example trajectory: `egg: liquid → coagulating → solid → scorched`.

## 4.6 `K1`: static knowledge tier

Single unified **Neo4j** knowledge graph, built **offline**, immutable during a session (cold archival tier [17]).

### Ingestion / enrichment

Follows KAG [33]:

```text
T_semantic = T_fact ⊕ T_concept
```

Recipe action nodes (`T_fact`) are augmented at ingestion with domain-physics safety bounds (`T_concept`). Fusion retrieves **both in one graph traversal**, not two sequential store lookups [17].

Pipeline:

1. Scrape raw recipe text from cooking blogs and food sites.
2. LLM-driven ingestion strips prose to canonical action form: atomic steps, ingredients, quantities, timing cues [34].
3. Output is a **multi-path DAG**, not one linear recipe. Variations (butter vs oil; low-heat slow scramble vs high-heat fast scramble) become parallel branches with shared pre/post-condition nodes.

Sibling codebase `Cooking-Advisor` already explores blog extraction and Cypher graph synthesis for scrambled eggs; treat it as a `K1` starting point, not the full assistant.

### Node typing [14]

Each node is **Process**, **Transfer**, or **Plate**, and carries:

| Field | Meaning |
| --- | --- |
| Pre-conditions | What must be true before execution |
| Post-conditions | Expected ingredient state after execution |
| Timing constraints | Expected duration or deadline |
| `HAS_SAFETY_BOUND` | Typed attribute edge on **Process** nodes: domain-physics upper bound |

Safety-bound examples:

- coagulation onset ≈ **62 °C**
- full coagulation ≈ **70 °C**
- Maillard browning onset

If `K2` reports visual proxies consistent with exceeding a bound (colour change, texture shift), the attribute edge can raise **`D_t = 2` regardless of recipe-step position**, independently of the recipe conflict score.

### Edges and runtime branch selection

Edges are causal dependencies: branch `B` cannot activate until `K2` verifies the post-condition of parent `A`.

At runtime, Fusion selects the branch whose pre-conditions **best match current `K2`**, so advice tracks how the user is actually cooking.

At reasoning time, the relevant node subgraph is serialised to structured text and injected into the Gemma 4 E4B prompt alongside `K2` state [28].

## 4.7 `K2`: live knowledge tier

Bounded, time-indexed **in-memory** buffer of extractor records. Hot tier: high-velocity, volatile, recency-optimised [17].

**Boundedness:** clear records once the corresponding recipe step is recognised complete. Prevents linear memory growth [18].

Native storage unit is SES:

```text
S_{t-1}  --E_t-->  S_t
```

`K2` holds the most recent SES chain per tracked entity — the live **actual trajectory** compared against `K1`’s expected trajectory.

Analogous to the internal-memory tier of the M² architecture [32]: compressed recent events informing the next decision.

## 4.8 Fusion and reasoning module

Each gate-triggered cycle:

1. Query `K1` for the expected post-condition of the current recipe step.
2. Query `K2` for the latest observed state of each relevant entity.
3. Compute a **conflict/confidence score** (deviation between expectation and observation).

Example of large deviation: `K1` expects `egg: coagulating` while `K2` reports `egg: scorched`.

**Gemma 4 E4B is invoked only if conflict exceeds a threshold** — not every frame [8, 25].

Scoring grounded in MultiRAG Multi-level Confidence Computing [35]:

- graph-level structural consistency from `K1`
- node-level local accuracy from `K2`

KAG mapping at fusion time:

- `K1` provides `T_fact` (static recipe nodes/edges)
- `K2` dynamically generates runtime concept nodes (`T_concept`)

When invoked, the model receives conflicting `K2` state + relevant `K1` subgraph as text, and is instructed to produce:

1. one **warning** sentence
2. one **corrective suggestion** sentence

## 4.9 Proactive intervention policy

Evaluate `φ(s_t, K1, K2)` → `D_t ∈ {0, 1, 2}` [8, 19].

| `D_t` | Name | Semantics | Channel |
| --- | --- | --- | --- |
| 0 | Silent | Observed state within `K1` tolerance | Continue monitoring |
| 1 | Suggestion | Minor, reversible deviation | Visual-only overlay: brief, dismissible, no audio, at a JITAI decision point where correction helps but inaction is not immediately fatal [9, 11] |
| 2 | Alert | Major deviation; inaction → irreversible (burning, timer expiry, safety) | Visual overlay + audio; not dismissible until state resolves or user acknowledges [19] |

### Severity determination

Let `c` be the Fusion conflict score:

- `c < τ1` → `D_t = 0`
- `τ1 ≤ c ≤ τ2` → `D_t = 1`
- `c > τ2` **or** a physics constraint edge in `K1` is violated → `D_t = 2`

Two-threshold design grounded in MultiRAG MCC [35].

### Cooldown suppression

After any `D_t ≥ 1`, enter a suppression window. Repeat firing blocked until:

- `K2` confirms motion toward the `K1` expected post-condition, or
- the window times out.

Prevents flooding while a bad condition persists [8, 9].

### Worked example (scrambled eggs)

`K1` expected:

```text
S0 (liquid egg, low heat)  --E1-->  S1 (softly coagulated, off heat)
```

`K2` observed:

```text
E1 escalates to E1′ (overheating, rising colour change) → S1′ (scorched solid)
```

1. Conflict crosses `τ1` → `D_t = 1`: “Your eggs are cooking faster than expected: consider lowering the heat.”
2. State worsens past `τ2` → `D_t = 2` with audio: “Your eggs are burning: remove from heat immediately.”

SES-chain escalation adapted from Dual-Sentinel / EC-RAG [18].

The policy is **purely endogenous**: no `u_t`. That is the structural distinction from reactive RAG [13].

## 4.10 Notification delivery

| Type | When | Form |
| --- | --- | --- |
| Suggestion | `D_t = 1` | One sentence, visual-only, dismissible, peripheral FOV to minimise split-attention cost [9, 20] |
| Alert | `D_t = 2` | Visual + short audio, non-dismissible until resolve/ack, central, higher salience. Audio-visual co-delivery for high-urgency hands-busy contexts where visual-only may be missed [4, 9] |

No user input channel in either case. After delivery, cooldown activates; `D_t` returns to 0 once resolution is confirmed.

## 4.11 Compute topology

Naïve on-device 4B 4-bit inference (~10–12 GB VRAM) exceeds current XR budgets. Cloud-every-frame RTT is unacceptable. **Hybrid decoupled topology:**

| Layer | What runs | Why |
| --- | --- | --- |
| Edge / on-device | Capture, Transport, Proactive Gate | Continuous loop stays latency-local; minimal compute |
| Local GPU server | Fusion & Reasoning (Gemma 4 E4B) | Called only when `D_t ≥ 1`. Cooking transitions unfold over seconds, so infrequent RTT fits the budget. Local (not cloud API) keeps open-weight determinism |

Supporting empirical results from the corpus:

| Result | Implication |
| --- | --- |
| Em-Garde 10–15 fps on one GPU because the large model is called mainly at startup [25] | Decouple gate from LLM |
| YETI 1 FPS SSIM gate matches heavy frameworks on recall [8] | Gate does most detection work |
| StreamRAG −27% generation latency via visual-textual context reuse [1] | Reuse context across events |
| EC-RAG: unbounded streaming without windowing → linear OOM [18] | Bounded SES windows in `K2` |
| MiniCPM-V 4.5: 4B-scale models viable for real-time egocentric reasoning [2] | Size class of Gemma 4 E4B is realistic |

## Module contract summary (for implementers)

| Module | Inputs | Outputs | Heavy model? |
| --- | --- | --- | --- |
| Capture | Headset camera | Frame packets @ ~8 fps class | No |
| Transport | Frame packets | Packets on WebRTC/WebSocket | No |
| Gate | Consecutive frames | Forward or drop | SSIM + ViT, not Gemma |
| Extractor (propose) | `K1` at startup | Visual-proposal library | Gemma 4 E4B once |
| Extractor (match) | Gated frame + library | `K2` records | CLIP + DINOv2 |
| `K1` | Offline recipes + physics | Immutable Neo4j DAG | LLM ingestion offline |
| `K2` | Extractor records | Bounded SES chains | No |
| Fusion | `K1` subgraph + `K2` state | Conflict score; optional two-sentence generation | Gemma only if conflict high |
| Policy | Conflict score + safety edges | `D_t`, cooldown | No |
| Notify | `D_t`, generated text | XR overlay ± audio | No |
