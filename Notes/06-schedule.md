# Work schedule

PIC Gantt (Figure 2). Weeks 1–4 of each month, **September 2026 – May 2027**.

Today’s date in this workspace is **13 September 2026**, so Architecture & Implementation is the current phase.

## Phases

### Architecture & Implementation

| Work package | Timing (from Gantt) |
| --- | --- |
| `K1` knowledge graph construction | Sep W1–Oct W4 (starts immediately; heaviest early) |
| `K2` live state buffer & perception pipeline | Sep W3–Dec W2 (overlaps `K1`, then continues) |
| Fusion module & intervention policy | Oct W3–Jan W2 |

### System Integration & Testing

| Work package | Timing |
| --- | --- |
| End-to-end pipeline integration | Dec W1–Feb W2 |
| System validation & debugging | Jan W1–Feb W4 |
| Pilot testing / dry run | Feb W3–Mar W2 |

### User Study

| Work package | Timing |
| --- | --- |
| Ethics approval & participant recruitment | Jan W3–Mar W2 (start before pilots finish) |
| Data collection | Mar W1–Apr W2 |
| Analysis & evaluation | Apr W1–May W2 |

### Writing Dissertation

| Work package | Timing |
| --- | --- |
| Alpha version | Mar W3–Apr W4 |
| Advisor revision | Apr W3–May W2 |
| Beta version | May W1–May W4 |

## Approximate calendar (week-level)

Legend: `█` = active in that week of the month.

```text
                                Sep     Oct     Nov     Dec     Jan     Feb     Mar     Apr     May
                               1 2 3 4 1 2 3 4 1 2 3 4 1 2 3 4 1 2 3 4 1 2 3 4 1 2 3 4 1 2 3 4 1 2 3 4

K1 knowledge graph             █ █ █ █ █ █ █ █
K2 buffer & perception               █ █ █ █ █ █ █ █ █ █ █ █
Fusion & intervention policy               █ █ █ █ █ █ █ █ █ █ █ █

E2E integration                                        █ █ █ █ █ █ █ █ █ █
Validation & debugging                                         █ █ █ █ █ █ █ █
Pilot / dry run                                                          █ █ █ █

Ethics & recruitment                                                 █ █ █ █ █ █ █ █
Data collection                                                                █ █ █ █ █ █
Analysis & evaluation                                                                █ █ █ █ █ █

Dissertation alpha                                                                   █ █ █ █ █ █
Advisor revision                                                                           █ █ █ █
Dissertation beta                                                                          █ █ █ █
```

The ASCII chart is a reconstruction from the PIC figure; treat the phase table as authoritative if a bar looks ambiguous.

## Implied build order for agents

1. `K1` graph (Neo4j, multi-path DAG, safety bounds) — can reuse `Cooking-Advisor` ingestion.
2. Capture → Transport → Gate (SSIM + ViT depth), even with a dummy extractor.
3. Perception propose–match → `K2` SES buffer with bounded clearing.
4. Fusion conflict score + `D_t` policy + cooldown + notification stubs.
5. Gemma 4 E4B only on the propose pass and on high-conflict cycles.
6. Logging for `t_int`, `D_t`, snapshots (needed before any pilot).
7. Reactive baseline path (`u_t` query) for the study, not as the product UX.
8. Pilot in a real kitchen with the headset that is actually available.
