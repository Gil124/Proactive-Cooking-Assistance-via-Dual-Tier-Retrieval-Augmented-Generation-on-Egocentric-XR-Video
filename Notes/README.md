# PIC notes

Source document: [`Documents/PIC submitted_fenix.pdf`](../Documents/PIC%20submitted_fenix.pdf)

These notes are a structured transcription of the PIC2 research plan by **Gil Cruz Arroteia (112466)**, *Proactive Cooking Assistance via Dual-Tier Retrieval-Augmented Generation on Egocentric XR Video* (Instituto Superior Técnico, Universidade de Lisboa). Advisors: Augusto Esteves, Atabak Dehban.

They exist so people and coding agents can work from the plan without reopening the PDF.

## How to use this folder

| If you need… | Read |
| --- | --- |
| A one-page briefing before writing code | [`00-agent-briefing.md`](00-agent-briefing.md) |
| Problem, RQs, objectives, contributions | [`01-overview.md`](01-overview.md) |
| Definitions of RAG, K1/K2, streaming, proactivity | [`02-background.md`](02-background.md) |
| Literature gaps and hypotheses H1–H3 | [`03-related-work.md`](03-related-work.md) |
| Module-by-module system spec | [`04-architecture.md`](04-architecture.md) |
| User-study design, metrics, procedure | [`05-evaluation.md`](05-evaluation.md) |
| Timeline (Sep 2026 – May 2027) | [`06-schedule.md`](06-schedule.md) |
| Cited papers with links | [`07-bibliography.md`](07-bibliography.md) |
| K1 pipeline design spec (agents, ontology, module contracts) | [`08-k1-pipeline.md`](08-k1-pipeline.md) |
| K1 evaluation protocol (gold set, metrics, bias controls) | [`09-k1-evaluation.md`](09-k1-evaluation.md) |
| Notation and terms | [`glossary.md`](glossary.md) |

**Coding agents should start with `00-agent-briefing.md`, then `04-architecture.md`.** Do not invent a dialogue interface, a cloud-every-frame topology, or a multi-recipe scope. Those are out of spec.

## Project in one sentence

Build an XR cooking assistant that watches egocentric video, fuses a static recipe graph (`K1`) with a live object-state buffer (`K2`), and **intervenes without being asked**.

## Status of this corpus

- These files describe the **plan** (PIC), not a finished implementation in this repository.
- Sibling work on recipe-graph construction lives in [`../../../Cooking-Advisor`](../../../Cooking-Advisor) (blog scraping, LLM step extraction, Neo4j/Cypher graph synthesis for scrambled eggs). That is relevant to `K1`, not to capture, gating, `K2`, fusion, or the user study.
