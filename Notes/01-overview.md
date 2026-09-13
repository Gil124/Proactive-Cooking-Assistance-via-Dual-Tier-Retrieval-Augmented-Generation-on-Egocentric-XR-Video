# Overview

**Title.** Proactive Cooking Assistance via Dual-Tier Retrieval-Augmented Generation on Egocentric XR Video

**Document.** PIC2 — Master in Computer Science and Engineering  
**Institution.** Instituto Superior Técnico, Universidade de Lisboa  
**Author.** Gil Cruz Arroteia — 112466 — gil.arroteia@tecnico.ulisboa.pt  
**Advisors.** Augusto Esteves, Atabak Dehban

**Keywords.** Extended Reality, Egocentric Video, Retrieval-Augmented Generation, Proactive AI Agent, Cooking Assistance

## Abstract

As multimodal AI and extended reality advance, their use in procedural task assistance raises a hard interaction problem. Cooking is the paradigmatic case: users keep both hands busy, manage concurrent steps under time pressure, and cannot pause to query an assistant. Effective cooking help must therefore be **entirely proactive**: the agent decides *when* and *what* to communicate from continuous visual observation alone.

Prior work covers recipe RAG and egocentric video understanding, but two gaps remain:

1. **Proactive RAG Activation** — how an agent autonomously decides when to retrieve from a knowledge source and issue an unprompted safety alert or step correction.
2. **Dual-tier knowledge retrieval** — how to fuse static recipe domain knowledge with live egocentric object-state perception in real time.

This work proposes and evaluates a proactive multimodal cooking assistant built around:

- a **dual-tier memory** that separates a static recipe knowledge graph (`K1`) from a live object-state buffer (`K2`);
- an **endogenous intervention policy** that fires without any user query.

A mixed-design user study is planned on a scrambled-egg task in a controlled laboratory kitchen: memory tier is **between subjects**, intervention mode (reactive vs proactive) is **within subjects**, each participant cooks twice. The evaluation tests three pre-registered hypotheses on interruption-timing accuracy, procedural error rate, perceived intrusiveness, and guidance relevance.

The intended contribution is both scientific (proactive intervention in time-critical procedural tasks) and engineering (dual-tier RAG for hands-free cooking assistance).

## Problem setting

XR headsets now provide continuous first-person video of hands, tools, and the workspace. Efficient multimodal models can do low-latency visual-language inference on consumer / local hardware, which is required because cloud round-trips are too slow for time-critical cooking. RAG is the standard way to ground generation in inspectable domain knowledge and reduce hallucination.

Cooking is uniquely demanding:

- time-critical procedure (temperature, ingredient state, sequence, timing);
- hands and visual attention fully occupied;
- novices overload when following digital instructions while acting;
- failures happen exactly when pausing to query is least feasible.

A system that waits for a question **reproduces the bottleneck it should remove**.

### What prior work covers, and what it does not

| Line of work | What it shows | What it does not do |
| --- | --- | --- |
| RecipeRAG-style culinary RAG | Structured recipe retrieval given a **text query** | Live, unprompted kitchen use |
| LifeEval, Minerva-Ego | SOTA VLMs can reason over egocentric video **when prompted** | Intervene without a query |
| YETI, SensibleAgent | Agents can detect intervention opportunities from continuous streams | Unify with recipe-grounded dual-tier retrieval in a live cook |
| StreamRAG | Streaming video RAG | Still evaluated as streaming **QA**; user still issues a query |

Video RAG models retrieve from **video history only**. They have no real-time cross-reference against a structured recipe knowledge base.

Supporting framings cited in the PIC:

- **Evidence–Decision–Feedback** [11]: separate evidence extraction, decision-making, and response generation. No cooking assistant has done this with egocentric video as evidence.
- **Centaur Evaluations** [12]: judge AI on quality of **human augmentation**, not autonomous task performance. No existing cooking benchmark captures this.

### Scope choice

Evaluation is intentionally limited to **one standardized benchmark recipe** (scrambled eggs) so recipe complexity and ingredient diversity do not confound measurement of the architectural variables (proactivity and memory tier).

## Research questions

Each RQ maps to a literature gap.

**RQ1.** To what extent does a proactive intervention policy improve **interruption-timing accuracy** and reduce **procedural error rate** during a hands-busy cooking task, compared to a reactive, query-driven baseline?

**RQ2.** Does a well-timed proactive policy increase, decrease, or leave unchanged the **perceived intrusiveness** of assistance relative to a system that responds only when explicitly queried?

**RQ3.** To what extent does a dual-tier RAG architecture, fusing static recipe knowledge with a live object-state buffer, yield higher **guidance relevance** than a single-tier baseline that retrieves from either source alone?

## Work objectives

Primary objective: design, implement, and evaluate a proactive multimodal cooking agent that operates **without user prompting**.

Sequential objectives:

1. Streaming egocentric video pipeline for XR: low-latency frame ingestion and event segmentation.
2. Object-centric state monitoring: culinary events such as ingredient state transitions and temperature cues in real time.
3. Dual-tier RAG: static recipe domain knowledge (`K1`) vs live object-state buffer (`K2`), fused at inference.
4. Mixed-design user study: between-subjects memory-tier group; within-subjects both intervention modes; scrambled eggs twice per session.

## Expected contributions

1. **Proactive intervention architecture** for real-time egocentric cooking assistance: continuous monitoring, unprompted suggestions and alerts, no user-initiated queries.
2. **Dual-tier RAG design**: `K1` static recipe knowledge vs `K2` live object-state buffer, fused at inference for state-aware suggestions.
3. **Empirical mixed-design user study**: first systematic comparison of proactive vs reactive cooking assistance and single-tier vs dual-tier retrieval under controlled conditions, evidence for three pre-registered hypotheses.
