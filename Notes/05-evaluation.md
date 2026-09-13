# Evaluation plan

## 5.1 Study design

**Mixed design.**

| Factor | Type | Levels |
| --- | --- | --- |
| Memory tier | Between subjects | Single-tier vs Dual-tier |
| Intervention mode | Within subjects | Reactive vs Proactive |

Each participant is assigned to **one** tier group and cooks scrambled eggs **twice** (once Reactive, once Proactive). Order is **counterbalanced** within each group.

### Groups

**Group 1 — Single-tier** (baseline for H1/H2 and H3)

1. Reactive + Single-tier: `K1` recipe text only; assistant silent until queried.
2. Proactive + Single-tier: `K1` only; gate fires without a user prompt.

**Group 2 — Dual-tier** (H3 contrast vs Group 1)

1. Reactive + Dual-tier: `K1`+`K2` fusion, fires only on a user query.
2. Proactive + Dual-tier: **full system** (architecture §4.9).

### What tests what

| Comparison | Tests |
| --- | --- |
| Within-subjects Reactive vs Proactive (both groups) | H1, H2 |
| Between-subjects Single-tier vs Dual-tier on guidance relevance | H3 |

Learning effect on Trial 2 is expected because everyone cooks the same recipe twice. Strict counterbalancing: half of each tier group gets Proactive first, half Reactive first, so adaptation is not confounded with system utility.

### Task

Prepare **one serving of scrambled eggs** while wearing an XR headset in a **controlled laboratory kitchen**.

Why this task: time-critical, non-uniform intra-object transitions `liquid → coagulating → solid → scorched` — the architecture’s canonical test case, which static final-outcome models fail to capture [15, 23].

Controls:

- same standardised kitchen;
- identical equipment (same pan model, induction hob, egg source);
- XR headset confirmed later based on hardware availability.

### Population

- Adults with **no professional cooking training**
- Comfortable wearing a head-mounted display
- Exclude severe visual or hearing impairment that would preclude XR display or audio alerts

## 5.2 Metrics and instruments

### 5.2.1 Dependent variables

#### H1 — interruption timing accuracy and procedural error rate

**Interruption timing accuracy**

```text
δt = |t_int − t*|
```

- `t_int` — system intervention timestamp
- `t*` — annotator-defined optimal intervention window for each critical recipe step [19]
- Source: session video logs
- Lower `δt` is better

**Procedural error rate**

Count of **unrecoverable** errors per session (burnt eggs, skipped steps with lasting consequences), scored from **blinded video review**.

Prediction: a proactive policy that fires before the state is beyond recovery reduces both `δt` and error rate vs reactive [26].

#### H2 — perceived intrusiveness

7-point Likert adapted from AR Cooking and Sensible Agent [4, 9]:

> “The assistant interrupted me at the wrong moment.”

Two supplementary items: **helpfulness** and **annoyance**.

Administered **immediately after each condition block** (not a retrospective average).

Prediction: proactive will **not** score higher on intrusiveness than reactive querying, because well-timed interruptions cost less split-attention than formulating and issuing a query [20].

#### H3 — guidance relevance

**Subjective relevance.** 7-point Likert per intervention (or per self-initiated query in reactive conditions), via post-hoc **video-replay**:

> “The suggestion matched what was happening at that moment.”

**Objective correctness.** Blinded rater classifies each delivered suggestion as:

- `correct-step`
- `incorrect-step`
- `safety-critical`

Proxy = proportion of `correct-step` + `safety-critical` per condition [15].

### 5.2.2 Shared instruments

| Instrument | When | Purpose |
| --- | --- | --- |
| **SUS** (10-item, 5-point, scored 0–100) | Once after both blocks | Literature-comparable usability [4, 9] |
| **Abbreviated NASA-TLX** — Mental Demand and Frustration only | After each condition block | Proxy for cognitive load / split-attention [20] |
| **Semi-structured interview** (~5–10 min) | End of session | Triangulate Likert data; patterns Likert misses [11] |

Interview topics:

- when the assistant helped or hindered;
- whether the participant felt in control;
- whether they would use such a system while cooking unsupervised.

Thematic analysis of responses.

## 5.3 Procedure

Estimated **45–60 minutes** total.

1. **Screening and consent (~10 min).** Eligibility, informed consent, headset fit and calibration.
2. **Familiarisation (~5 min).** One practice serving of scrambled eggs **with the system off**. Baseline recipe familiarity and headset comfort. **No data collected.**
3. **Condition block 1.** Experimenter silently configures the first assigned intervention mode. Participant cooks one serving with the system active. Video-logged. Immediately after: post-condition Likert items + abbreviated NASA-TLX (~5 min).
4. **Short break and kitchen reset (~5 min).** Station returned to standardised start (fresh pan, fresh eggs).
5. **Condition block 2.** Repeat step 3 under the second intervention mode.
6. **Post-session SUS (~5 min).** Once after both blocks.
7. **Semi-structured interview (~5–10 min).**

Ethics: protocol submitted for review before data collection, following SIGSOFT open-science policies: https://github.com/acmsigsoft/open-science-policies

## 5.4 Expected outcomes and limitations

### If hypotheses hold

| Hypothesis | Support looks like |
| --- | --- |
| H1 | Lower `δt` and fewer unrecoverable errors in Proactive vs Reactive |
| H2 | Equal or lower intrusiveness in Proactive vs Reactive |
| H3 | Higher subjective and objective guidance relevance in Dual-tier vs Single-tier |

### Limitations (pre-registered in the PIC)

1. **Lab kitchen** maximises internal validity; may not generalise to home cooking variability.
2. **Single short recipe.** Longer/more complex recipes may expose latency and memory-management issues invisible in a ~five-minute cook.
3. **Subjective relevance ratings** are vulnerable to response-format effects; the blinded-rater correctness proxy is the independent check.

## Logging requirements for the implementation

To make this study runnable, the system must record:

- condition flags: group (single/dual), mode (reactive/proactive), order;
- `t_int` and `D_t` for every notification;
- generated warning + suggestion text;
- `K2` state snapshot and `K1` node/branch used at fire time;
- conflict score and whether a `HAS_SAFETY_BOUND` edge fired;
- cooldown enter/exit;
- aligned session video for `t*` annotation and error coding;
- in reactive conditions: query timestamps and responses (same relevance coding).
