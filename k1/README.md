# K1 Knowledge Graph — Construction Pipeline

Builds the static recipe knowledge graph (`K1`) used by the Fusion module
of the Proactive Cooking Assistance system.

Design spec: [`../Notes/08-k1-pipeline.md`](../Notes/08-k1-pipeline.md)
Evaluation protocol: [`../Notes/09-k1-evaluation.md`](../Notes/09-k1-evaluation.md)
Open work, concerns, and status: [`TODO.md`](TODO.md)

> **Before running:** two blocking bugs are open (temperature regex false positives, and
> REQUIRES edge cycles that abort `k1 validate`). See Section A of [`TODO.md`](TODO.md).

## Quick start

```bash
cd k1/
cp .env.example .env    # fill in GROQ_API_KEY and OPENROUTER_API_KEY
uv sync

# Run the full pipeline (creates a new run ID)
uv run k1 run

# Or step by step
uv run k1 ingest   --run <run_id>
uv run k1 extract  --run <run_id>
uv run k1 critic   --run <run_id>
uv run k1 fuse     --run <run_id>
uv run k1 validate --run <run_id>
uv run k1 store    --run <run_id>
uv run k1 eval     --run <run_id>

# Visualize and review
uv run k1 viz --run <run_id>
```

## Output

| File | Description |
|---|---|
| `data/k1/graph.json` | Fused K1 DAG — git-committed source of truth |
| `data/k1/graph.cypher` | Neo4j ingest script (generated from graph.json) |
| `data/artifacts/runs/<run_id>/eval/report.md` | Per-stage evaluation metrics |

## Flags

```
k1 run --no-neo4j     # skip live Neo4j ingestion (Cypher export only)
k1 run --gold-only    # only process the 3 held-out gold recipes (for annotation)
k1 ingest --force     # re-fetch all recipe HTML
```

## What Fusion queries

At runtime, Fusion queries K1 for:
- `post_conditions` of the current recipe step (expected K2 state)
- `HAS_SAFETY_BOUND` edges (temperature thresholds, severity)
- Next node ID(s) in the DAG (for branch selection)

Do not add node types other than `Process`, `Transfer`, `Plate`, `Ingredient`, `Tool`, `SafetyBound`.
