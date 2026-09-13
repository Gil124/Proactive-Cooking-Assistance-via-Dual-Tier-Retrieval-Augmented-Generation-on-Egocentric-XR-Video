# Related work

The PIC organises literature into three buckets and critiques each against kitchen constraints: hands and vision occupied, unbounded streaming video, high cognitive load, state transitions that become irreversible in seconds. Each subsection’s limitation motivates a hypothesis.

Kitchen constraints used as the critique lens:

- hands-busy, vision-busy user;
- unbounded streaming video;
- high cognitive load;
- irreversible state changes within seconds.

## Egocentric video understanding and procedural tasks

### Offline corpora, not live agents

Ego4D [21] and EPIC-KITCHENS [22] are the modern baselines for objects, hands, and kitchen step tracking. They are **offline corpora for retrospective analysis**, not substrates for live inference under a latency budget. Models answer questions about recorded video; they do not commit to actions while the video is still unfolding.

### Still query-triggered even when “real-time”

**Minerva-Ego** [7]: SOTA VLMs fail on cooking primitives (object ID during manipulation, temporal grounding). Remedy is post-hoc visual prompt engineering, not an agent that chooses its own spatial/temporal focus.

**LifeEval** [6]: models assistive, real-time-looking scenarios, but evaluation is **query-triggered**. Proprietary models degrade from recognition to dynamic reasoning / goal-oriented planning. Safety-and-feasibility is scored only in response to a user question. The benchmark never asks the model to intervene unprompted.

### Semantically shallow perception

Networks label actions (“stirring”, “pouring”) without recipe pre-/post-conditions. Cooking’s salient event is often an **intra-object state change** (egg liquid → coagulating → solid): non-uniform, spatially progressing. Frame-level uniform-state perception cannot capture this (**SPOC** [15]).

On-device models can recognise events such as overheating in real time [2], but **recognition is not a temporal policy for when to act**.

Food computing remains tied to **static final-outcome** imagery/text and lacks live egocentric streams and intermediate cooking states [23].

### Gap used in this thesis

The perception substrate is increasingly capable, but still **offline, passive, query-triggered, and shallow w.r.t. recipe rules**. A hands-busy cook needs:

1. autonomy to decide **when to speak**;
2. structured memory of **evolving physical state**.

Those two requirements drive H1/H2 (proactivity) and H3 (memory).

## AI cooking assistants and intelligent guidance systems

### Reactive majority

DietQA [24] and RecipeRAG [3] parse complex requests but need a **textual query**. Incompatible with messy hands and food already on heat.

AR guidance keeps hands free and can beat manuals/tablets for spatial cooking [4], but is typically **static step-by-step**, which can produce mindless instruction-following rather than understanding [5].

Cognitive-ergonomics: splitting attention between physical action and an AI channel inflates extraneous load [20]. JITAI: help should bind to a **task decision point**, not an explicit prompt [19]. A purely reactive UI recreates the bottleneck as cognitive friction.

### Proactive but incomplete

| System | Contribution | Limitation vs this kitchen |
| --- | --- | --- |
| **YETI** [8] | Ultra-light gate: egocentric feed → binary intervene/wait | No semantic recipe checklist or state machine tied to a master plan |
| **Sensible Agent** [9] | What assistance to offer and how, in AR; reduces interaction effort | Not designed for high-stakes continuously mutating physical state |
| **Em-Garde** [25] | Proactive streaming understanding at stable FPS on one GPU by decoupling cheap perception from semantic reasoning | Feasibility on wearable-class hardware; not a recipe-grounded cook |
| **ProAssist** [26] | Proactive dialogue from streaming ego video | Real-world execution below human-rated thresholds **because of poor response timing** — *when* to speak is the open problem |

Human–AI collaboration literature: interruption is friction-laden; judge **joint** performance and the tension between task performance and behavioural comfort [11, 12, 27].

### Dichotomy → H1 and H2

Assistants are either **reactive** (query bottleneck) or **proactive** (unreliable timing, no recipe-grounded state, intrusiveness unmeasured in a time-critical culinary task).

**H1.** Replacing a reactive, query-driven interface with a proactive intervention policy improves interruption-timing accuracy and lowers procedural error rate during a hands-busy cooking task.

**H2.** A well-timed proactive policy does not increase, and may reduce, perceived intrusiveness relative to the cognitive cost of user-initiated querying, despite delivering unprompted alerts.

## Multimodal RAG and knowledge fusion architectures

Surveys [13]: LLM + structured knowledge ranges from a single homogeneous text-retrieval surface up to context-aware mechanisms that track environmental state. Real-time construction/update of knowledge is still an unresolved overhead — exactly the cooking-stream regime.

### Failure mode 1: static culinary stores only

Action-centric recipe DAGs [14], KG recipe generators [3], context-aware KG messaging [28], food substitution graphs/surveys [29, 30], commonsense substitution [31] encode rich culinary knowledge but are **uniformly static**. Predicates stay symbolic. No architecture verifies them against live sensors. Cannot react to dropped, burned, or already-past-target ingredients.

### Failure mode 2: live visual state as a single tier

- Event-Causal RAG: stream → State–Event–State to avoid temporal fragmentation [18].
- Tracking the Truth: object-centric historical trajectories improve consistency [10].
- StreamRAG-class pipelines: low latency via event segmentation and token reuse [1].

These are evaluated as **passive post-hoc viewers** answering questions about a stream. They retrieve from **video history alone**, with no recipe rule base.

Outside cooking, hot/cold versioned vector architectures [17] and dual-memory agents (internal trajectory + external knowledge) [32] show the value of separating fast state from slow archives. Neither is grounded in egocentric culinary perception.

### Gap → H3

No existing system fuses both surfaces a cook needs. Static recipe KBs cannot track live ingredient transitions; live video indices cannot interpret those transitions against recipe rules. A single-tier baseline (recipe text **or** latest frame) degrades relevance exactly when physical state diverges from the plan.

**H3.** A dual-tier memory architecture, fusing static recipe rules with a live object-state buffer, yields higher guidance relevance than a single-tier baseline that retrieves from either source alone.

## Hypothesis map

| Hypothesis | Independent variable | Dependent variables | RQ |
| --- | --- | --- | --- |
| H1 | Reactive vs proactive policy | Interruption timing `δt`, procedural error rate | RQ1 |
| H2 | Reactive vs proactive policy | Perceived intrusiveness (and supplementary helpfulness/annoyance) | RQ2 |
| H3 | Single-tier vs dual-tier memory | Guidance relevance (subjective Likert + objective rater correctness) | RQ3 |
