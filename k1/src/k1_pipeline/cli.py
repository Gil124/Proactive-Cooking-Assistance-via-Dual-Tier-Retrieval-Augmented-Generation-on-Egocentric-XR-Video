"""
K1 Pipeline CLI
Entry point for all pipeline stages.

Usage:
  k1 run      -- run all stages in sequence
  k1 ingest   -- L1: fetch + parse recipes
  k1 extract  -- L2: LLM extraction (generator)
  k1 critic   -- L2: critic verification
  k1 fuse     -- L3: entity resolution + DAG building
  k1 validate -- L4: deterministic gate checks
  k1 store    -- L4: write graph.json + graph.cypher
  k1 eval     -- compare to gold, write report
  k1 viz      -- launch Streamlit visualizer
  k1 review   -- alias for viz
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

ROOT = Path(__file__).parent.parent.parent  # k1/
DATA = ROOT / "data"
RUNS_DIR = DATA / "artifacts" / "runs"
K1_OUT = DATA / "k1"

console = Console()


def _new_run_id() -> str:
    return uuid.uuid4().hex[:8]


def _load_canonical_recipes(recipes_dir: Path) -> dict:
    from k1_pipeline.models import CanonicalRecipe
    result = {}
    for path in sorted(recipes_dir.glob("*/canonical.json")):
        try:
            recipe = CanonicalRecipe.model_validate_json(path.read_text())
            result[recipe.recipe_id] = recipe
        except Exception as e:
            console.print(f"[yellow]Warning: could not load {path}: {e}[/yellow]")
    return result


@click.group()
def cli():
    """K1 Knowledge Graph construction pipeline."""
    pass


@cli.command()
@click.option("--run", "run_id", default=None, help="Existing run ID to resume")
@click.option("--force", is_flag=True, default=False, help="Re-fetch even if cached")
@click.option("--no-neo4j", is_flag=True, default=False, help="Skip live Neo4j ingestion")
@click.option("--gold-only", is_flag=True, default=False, help="Only process gold recipes")
def run(run_id, force, no_neo4j, gold_only):
    """Run all pipeline stages in sequence."""
    if run_id is None:
        run_id = _new_run_id()
    console.print(f"\n[bold green]K1 Pipeline run:[/bold green] {run_id}\n")

    ctx = click.get_current_context()
    ctx.invoke(ingest, run_id=run_id, force=force, gold_only=gold_only)
    ctx.invoke(extract, run_id=run_id)
    ctx.invoke(critic, run_id=run_id)
    ctx.invoke(fuse, run_id=run_id)
    ctx.invoke(validate, run_id=run_id)
    ctx.invoke(store, run_id=run_id, no_neo4j=no_neo4j)
    ctx.invoke(eval_, run_id=run_id)
    console.print(f"\n[bold green]Pipeline complete.[/bold green] Run ID: {run_id}")
    console.print(f"  Graph:  {K1_OUT / 'graph.json'}")
    console.print(f"  Report: {RUNS_DIR / run_id / 'eval' / 'report.md'}")
    console.print(f"  Viz:    k1 viz --run {run_id}")


@cli.command()
@click.option("--run", "run_id", required=True)
@click.option("--force", is_flag=True, default=False)
@click.option("--gold-only", is_flag=True, default=False)
def ingest(run_id, force, gold_only):
    """L1: Fetch and parse recipes from the allowlist."""
    from k1_pipeline.ingest.runner import run_ingest

    run_dir = RUNS_DIR / run_id
    recipes_dir = DATA / "recipes"
    console.print("[bold]L1: Ingest[/bold]")
    run_ingest(recipes_dir, run_dir, force=force, gold_only=gold_only)


@cli.command()
@click.option("--run", "run_id", required=True)
def extract(run_id):
    """L2 Generator: extract K1 nodes from each recipe step."""
    from k1_pipeline.extract.generator import extract_recipe

    run_dir = RUNS_DIR / run_id
    recipes = _load_canonical_recipes(DATA / "recipes")
    if not recipes:
        console.print("[red]No canonical recipes found. Run 'k1 ingest' first.[/red]")
        sys.exit(1)

    console.print("[bold]L2: Extract (generator)[/bold]")
    for recipe in recipes.values():
        # Gold recipes ARE extracted and graphed; hold-out = not used as few-shot examples.
        console.print(f"  Extracting {recipe.recipe_id} ({len(recipe.steps)} steps)...")
        nodes = extract_recipe(recipe, run_dir)
        console.print(f"    [green]OK[/green] {len(nodes)} nodes extracted")


@cli.command()
@click.option("--run", "run_id", required=True)
def critic(run_id):
    """L2 Critic: verify extracted nodes for groundedness."""
    from k1_pipeline.critic.critic import verify_recipe
    from k1_pipeline.models import ExtractedNode

    run_dir = RUNS_DIR / run_id
    gen_dir = run_dir / "L2" / "gen"
    recipes = _load_canonical_recipes(DATA / "recipes")

    console.print("[bold]L2: Critic[/bold]")
    for recipe in recipes.values():
        # Load extracted nodes for this recipe
        gen_files = sorted(gen_dir.glob(f"{recipe.recipe_id}_*.gen.json"))
        if not gen_files:
            continue
        nodes = [ExtractedNode.model_validate_json(f.read_text()) for f in gen_files]
        pairs = verify_recipe(recipe, nodes, run_dir)
        accepted = sum(1 for _, c in pairs if c.verdict.value == "accept")
        console.print(f"  {recipe.recipe_id}: {accepted}/{len(nodes)} accepted")


@cli.command()
@click.option("--run", "run_id", required=True)
def fuse(run_id):
    """L3: Resolve entities and build the fused multi-path DAG."""
    from k1_pipeline.fuse.dag_builder import build_k1_graph
    from k1_pipeline.models import CriticOutput as CO, ExtractedNode

    run_dir = RUNS_DIR / run_id
    gen_dir = run_dir / "L2" / "gen"
    critic_dir = run_dir / "L2" / "critic"
    recipes = _load_canonical_recipes(DATA / "recipes")

    console.print("[bold]L3: Fuse[/bold]")
    all_pairs: list[tuple[list, str]] = []
    for recipe in recipes.values():
        gen_files = sorted(gen_dir.glob(f"{recipe.recipe_id}_*.gen.json"))
        if not gen_files:
            continue
        pairs = []
        for gf in gen_files:
            node = ExtractedNode.model_validate_json(gf.read_text())
            step_n = node.step_number

            # Prefer the R2 critic verdict when a revision round happened -- that is
            # the FINAL verdict on the (already-revised) node currently on disk.
            # Falling back to the first-pass verdict only when no revision occurred.
            r2_file = critic_dir / f"{recipe.recipe_id}_step{step_n:02d}.critic.r2.json"
            r1_file = critic_dir / f"{recipe.recipe_id}_step{step_n:02d}.critic.json"

            critic_file = r2_file if r2_file.exists() else r1_file
            if critic_file.exists():
                critic_out = CO.model_validate_json(critic_file.read_text())
                if critic_out.verdict.value != "reject":
                    pairs.append((node, critic_out))
        all_pairs.append((pairs, recipe.recipe_id))

    graph = build_k1_graph(all_pairs, run_dir)
    console.print(f"  [green]Fused DAG:[/green] {len(graph.nodes)} nodes, {len(graph.edges)} edges")


@cli.command()
@click.option("--run", "run_id", required=True)
def validate(run_id):
    """L4: Run deterministic validation gates."""
    from k1_pipeline.models import K1Graph
    from k1_pipeline.validate.gates import run_validation

    run_dir = RUNS_DIR / run_id
    fused_path = run_dir / "L3" / "fused_dag.json"
    if not fused_path.exists():
        console.print("[red]fused_dag.json not found. Run 'k1 fuse' first.[/red]")
        sys.exit(1)

    graph = K1Graph.model_validate_json(fused_path.read_text())
    recipes = _load_canonical_recipes(DATA / "recipes")

    console.print("[bold]L4: Validate[/bold]")
    passed = run_validation(graph, recipes, run_dir)
    if passed:
        console.print("  [green]All 6 gates passed.[/green]")
    else:
        report = (run_dir / "L4" / "validation_report.txt").read_text()
        console.print(f"[red]{report}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--run", "run_id", required=True)
@click.option("--no-neo4j", is_flag=True, default=False)
@click.option("--apply-schema", is_flag=True, default=False, help="Apply graph_schema.cypher constraints before ingestion")
def store(run_id, no_neo4j, apply_schema):
    """L4: Write graph.json, graph.cypher, optionally ingest into Neo4j."""
    from k1_pipeline.models import K1Graph
    from k1_pipeline.store.writer import ingest_neo4j, write_cypher, write_json

    run_dir = RUNS_DIR / run_id
    fused_path = run_dir / "L3" / "fused_dag.json"
    if not fused_path.exists():
        console.print("[red]fused_dag.json not found. Run 'k1 validate' first.[/red]")
        sys.exit(1)

    graph = K1Graph.model_validate_json(fused_path.read_text())
    K1_OUT.mkdir(parents=True, exist_ok=True)

    console.print("[bold]L4: Store[/bold]")
    json_path = write_json(graph, K1_OUT)
    console.print(f"  JSON  -> {json_path}")

    cypher_text, cypher_path = write_cypher(graph, K1_OUT)
    console.print(f"  Cypher -> {cypher_path}")

    # Also copy to run artifacts
    (run_dir / "L4").mkdir(parents=True, exist_ok=True)
    (run_dir / "L4" / "graph.json").write_text(fused_path.read_text())

    if not no_neo4j:
        import os
        if os.environ.get("NEO4J_URI"):
            console.print("  Ingesting into Neo4j...")
            schema_path = ROOT / "config" / "graph_schema.cypher" if apply_schema else None
            ingest_neo4j(graph, cypher_text=cypher_text, schema_path=schema_path)
        else:
            console.print("  [yellow]NEO4J_URI not set — skipping live ingestion.[/yellow]")


@cli.command("eval")
@click.option("--run", "run_id", required=True)
@click.option("--check-gold", is_flag=True, default=False, help="Validate gold files against GoldNode schema before scoring")
def eval_(run_id, check_gold):
    """Compute per-stage metrics and write an eval report."""
    from k1_pipeline.eval.metrics import validate_gold_files, write_report

    run_dir = RUNS_DIR / run_id
    gold_dir = DATA / "gold"
    recipes_dir = DATA / "recipes"

    if check_gold:
        console.print("[bold]Checking gold file schemas...[/bold]")
        errors = validate_gold_files(gold_dir)
        if errors:
            for e in errors:
                console.print(f"  [red]{e}[/red]")
            sys.exit(1)
        console.print("  [green]All gold files valid.[/green]")

    console.print("[bold]Eval[/bold]")
    report = write_report(run_id, run_dir, recipes_dir, gold_dir)
    report_path = run_dir / "eval" / "report.md"
    console.print(f"  Report -> {report_path}")
    console.print(report[:2000])  # preview first 2 KB


@cli.command()
@click.option("--run", "run_id", default=None, help="Run ID to pre-select in the UI")
def viz(run_id):
    """Launch the Streamlit graph visualizer and review UI."""
    app_path = Path(__file__).parent / "viz" / "app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path)]
    if run_id:
        cmd += ["--", "--run", run_id]
    subprocess.run(cmd)


@cli.command()
@click.option("--run", "run_id", default=None)
def review(run_id):
    """Alias for 'k1 viz' -- launches the review UI."""
    ctx = click.get_current_context()
    ctx.invoke(viz, run_id=run_id)


if __name__ == "__main__":
    cli()
