# K1 Knowledge Graph — Construction Pipeline

Builds the static recipe knowledge graph (`K1`) used by the Fusion module
of the Proactive Cooking Assistance system.

Design spec: [`../Notes/08-k1-pipeline.md`](../Notes/08-k1-pipeline.md)
Evaluation protocol: [`../Notes/09-k1-evaluation.md`](../Notes/09-k1-evaluation.md)
Open work, concerns, and status: [`TODO.md`](TODO.md)

What belongs in the graph: [`../Notes/10-recipe-variation.md`](../Notes/10-recipe-variation.md)
and [`config/dish.yaml`](config/dish.yaml).

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

## Review and measure

```bash
uv run k1 run --run <run_id> --no-neo4j   # 1. freeze one pipeline run
uv run k1 viz --run <run_id>              # 2. Gold set tab: review every step
uv run k1 finalize --run <run_id>         # 3. final graph from the reviewed steps
uv run k1 eval --run <run_id>             # 4. accuracy, correction effort, time
```

Protocol: [`../Notes/09-k1-evaluation.md`](../Notes/09-k1-evaluation.md).

## Output

| File | Description |
|---|---|
| `data/k1/graph.json` | Fused K1 DAG from the last pipeline run |
| `data/k1/graph.final.json` | Reviewed K1 DAG, written by `k1 finalize`. This is the graph the assistant uses |
| `data/k1/graph.auto.json` | Pipeline DAG of the run that was reviewed, kept for comparison |
| `data/artifacts/runs/<run_id>/L3/scope_report.json` | Every entity trimmed and step dropped by the scope rule |
| `data/artifacts/runs/<run_id>/eval/correction.json`, `correction_steps.csv` | Pipeline vs review, machine-readable |
| `data/k1/graph.cypher` | Neo4j ingest script (generated from graph.json) |
| `data/artifacts/runs/<run_id>/eval/report.md` | Per-stage evaluation metrics |

## Flags

```
k1 run --no-neo4j     # skip live Neo4j ingestion (Cypher export only)
k1 run --gold-only    # only process recipes marked gold: true
k1 finalize --allow-unreviewed   # use the pipeline output for steps not reviewed yet
k1 ingest --force     # re-fetch all recipe HTML
```

## What Fusion queries

At runtime, Fusion queries K1 for:
- `post_conditions` of the current recipe step (expected K2 state)
- `HAS_SAFETY_BOUND` edges (temperature thresholds, severity)
- Next node ID(s) in the DAG (for branch selection)

Do not add node types other than `Process`, `Transfer`, `Plate`, `Ingredient`, `Tool`, `SafetyBound`.
