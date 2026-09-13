# Background

The architecture and evaluation rest on three concept clusters. Concrete systems are in [`03-related-work.md`](03-related-work.md). Implementation is in [`04-architecture.md`](04-architecture.md).

## Retrieval-augmented generation and dual-tier memory

**RAG** couples a generative model with an external knowledge base queried at inference time. Baseline pipeline: embed the input → retrieve similar entries → inject into context → generate conditioned on that evidence [13]. RAG is external, inspectable memory; it offloads facts from model weights.

### Two knowledge surfaces

| Store | Role | Update rate | Content |
| --- | --- | --- | --- |
| **`K1` (Tier-1, static / cold)** | Persistent domain knowledge | Slow; immutable during a session | Cooking procedure as a **DAG**: nodes = ingredients and actions; edges = pre-conditions, post-conditions, timing constraints [3, 14] |
| **`K2` (Tier-2, dynamic / hot)** | Live perception memory | High velocity | Time-indexed, object-centric trajectories of unary property transitions (e.g. egg: liquid → coagulating → solid) [10, 15] |

- **Single-tier:** one homogeneous retrieval surface.
- **Dual-tier:** both stores at distinct update rates, fused at inference [16, 17].

Canonical monitoring primitive:

```text
S_{t-1}  --E_t-->  S_t
```

`K1` encodes **expected** transitions. `K2` records **observed** ones [18].

### Two execution triggers

| Trigger | Fires when | Conditions generation on |
| --- | --- | --- |
| **Reactive** | Explicit user prompt `u_t` | `Retrieve(u_t, K)` — standard RAG baseline |
| **Proactive** | Endogenous predicate `φ(s_t, K1, K2)` with **no** user prompt | Retrieval + communication gated by severity `D_t ∈ {0, 1, 2}` [8, 19] |

`D_t` decides whether to retrieve and communicate, and at what urgency.

## Egocentric XR streaming pipeline

An **egocentric stream** is head-mounted, first-person video: rapid FOV shifts, hand occlusions, motion blur, non-stationary workspace. Structurally different from a fixed third-person camera [7].

Closed-loop assistance is **device-agnostic** and has five blocks:

1. **Capture** — headset camera frames at a configurable rate.
2. **Transport** — low-latency packets to a processing node.
3. **Perception** — object-state extractor that updates `K2`.
4. **Reasoning** — fusion of `K1` and `K2` into the intervention policy.
5. **Feedback** — low-latency response to the user.

Requirements:

- End-to-end latency **well below** the task-critical transition time.
- Bounded sliding windows or event segmentation so token/memory growth stays finite on an unbounded stream [1, 18].
- `K2` is the structural component that enforces boundedness (see architecture §4.7).

## Proactive assistance and study variables

**Proactivity:** the agent is not an obedient tool that acts only on `u_t`. It is an autonomous collaborator that initiates communication when `φ` holds. Grounded in **Just-in-Time Adaptive Intervention (JITAI)**: map a decision point and tailoring variables to an intervention option [19].

### Outcome constructs

| Construct | Definition |
| --- | --- |
| **Guidance relevance** | Semantic match between a delivered suggestion and both current `K2` state and the applicable `K1` rule |
| **Interruption timing accuracy** | Temporal alignment of intervention time `t_int` with the optimal point inside a recipe-critical decision window |
| **Perceived intrusiveness** | Degree to which an unprompted alert displaces primary-task attention; split-attention and working-memory cost of managing a physical task and an AI channel at once [20] |

Following the **centaur** framing, success is **joint human–system performance**, not autonomous task completion [12].
