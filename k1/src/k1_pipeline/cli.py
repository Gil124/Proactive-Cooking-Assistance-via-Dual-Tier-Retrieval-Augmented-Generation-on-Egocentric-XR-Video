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
  k1 store    -- L4: write graph.json + graph.cypher (--final: load the reviewed graph)
  k1 eval     -- compare to the reviewed steps, write report
  k1 finalize -- build the final graph from the reviewed steps
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
    from k1_pipeline.config_loader import get_excluded_recipes
    from k1_pipeline.models import CanonicalRecipe
    excluded = get_excluded_recipes()
    result = {}
    for path in sorted(recipes_dir.glob("*/canonical.json")):
        try:
            recipe = CanonicalRecipe.model_validate_json(path.read_text())
            if recipe.recipe_id in excluded:
                # Not a variation of the dish (config/dish.yaml); skipped by every stage.
                continue
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
    from k1_pipeline.scope import complete_to_goal, filter_recipe_pairs

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

    # Trim every node to the station inventory and drop steps outside the dish.
    all_pairs = filter_recipe_pairs(all_pairs, run_dir / "L3")
    scope_report = json.loads((run_dir / "L3" / "scope_report.json").read_text())
    console.print(
        f"  Scope: {scope_report['steps_dropped']} steps dropped, "
        f"{scope_report['steps_trimmed']} trimmed -> L3/scope_report.json"
    )

    # Every path must end at the goal: add a closing Plate step where a source has none.
    all_pairs = complete_to_goal(all_pairs, run_dir / "L3")
    goal_report = json.loads((run_dir / "L3" / "goal_completion.json").read_text())
    if goal_report["plate_step_added"]:
        console.print(
            "  Goal: closing Plate step added by rule to "
            + ", ".join(r["recipe_id"] for r in goal_report["plate_step_added"])
        )
    for r in goal_report["goal_not_reached"]:
        console.print(
            f"  [yellow]Goal not reached: {r['recipe_id']} ends with eggs "
            f"{r['last_state']}; no Plate step added.[/yellow]"
        )

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
        console.print("  [green]All 7 gates passed.[/green]")
    else:
        report = (run_dir / "L4" / "validation_report.txt").read_text()
        console.print(f"[red]{report}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--run", "run_id", default=None, help="Pipeline run to store (not with --final)")
@click.option(
    "--final", is_flag=True, default=False,
    help="Load the reviewed graph (data/k1/graph.final.json) instead of a run",
)
@click.option("--no-neo4j", is_flag=True, default=False)
@click.option("--apply-schema", is_flag=True, default=False, help="Apply graph_schema.cypher constraints before ingestion")
@click.option(
    "--clear", is_flag=True, default=False,
    help="Delete the previous K1 graph from Neo4j before ingestion",
)
def store(run_id, final, no_neo4j, apply_schema, clear):
    """L4: Write graph.json, graph.cypher, optionally ingest into Neo4j."""
    from k1_pipeline.models import K1Graph
    from k1_pipeline.store.writer import ingest_neo4j, write_cypher, write_json

    if final == (run_id is not None):
        console.print("[red]Pass either --run <id> or --final.[/red]")
        sys.exit(1)

    console.print("[bold]L4: Store[/bold]")
    K1_OUT.mkdir(parents=True, exist_ok=True)
    if final:
        final_path = K1_OUT / "graph.final.json"
        if not final_path.exists():
            console.print("[red]graph.final.json not found. Run 'k1 finalize' first.[/red]")
            sys.exit(1)
        graph = K1Graph.model_validate_json(final_path.read_text())
        cypher_text, cypher_path = write_cypher(graph, K1_OUT, "graph.final.cypher")
        console.print(f"  Cypher -> {cypher_path}")
    else:
        run_dir = RUNS_DIR / run_id
        fused_path = run_dir / "L3" / "fused_dag.json"
        if not fused_path.exists():
            console.print("[red]fused_dag.json not found. Run 'k1 validate' first.[/red]")
            sys.exit(1)

        graph = K1Graph.model_validate_json(fused_path.read_text())
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
            console.print(f"  Ingesting {graph.version} into Neo4j...")
            schema_path = ROOT / "config" / "graph_schema.cypher" if apply_schema else None
            ingest_neo4j(graph, cypher_text=cypher_text, schema_path=schema_path, clear=clear)
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
@click.option("--run", "run_id", required=True, help="Run the steps were reviewed against")
@click.option(
    "--allow-unreviewed", is_flag=True, default=False,
    help="Use the pipeline output for steps that have no current review",
)
def finalize(run_id, allow_unreviewed):
    """Build the final K1 graph from the reviewed steps in data/gold/."""
    from k1_pipeline.fuse.dag_builder import build_k1_graph
    from k1_pipeline.gold import gold_to_pair, is_current, load_gold
    from k1_pipeline.models import CriticOutput as CO, CriticVerdict, ExtractedNode, NodeType
    from k1_pipeline.physics import is_thermal_action
    from k1_pipeline.scope import complete_to_goal, filter_recipe_pairs
    from k1_pipeline.store.writer import write_cypher
    from k1_pipeline.validate.gates import run_validation

    run_dir = RUNS_DIR / run_id
    final_dir = run_dir / "final"
    gold_dir = DATA / "gold"
    gen_dir = run_dir / "L2" / "gen"
    recipes = _load_canonical_recipes(DATA / "recipes")

    console.print("[bold]Finalize: reviewed steps -> final graph[/bold]")
    all_pairs: list[tuple[list, str]] = []
    unreviewed: list[str] = []
    problems: list[str] = []
    safety: dict[tuple[str, int], bool] = {}
    for recipe in recipes.values():
        pairs = []
        for step in recipe.steps:
            label = f"{recipe.recipe_id} step {step.number}"
            gold = load_gold(gold_dir, recipe.recipe_id, step.number)
            if is_current(gold):
                if not gold.expected.in_scope:
                    continue
                try:
                    pairs.append(gold_to_pair(gold, recipe, run_dir))
                except Exception as e:
                    problems.append(f"{label}: {e}")
                # The reviewer's heat decision decides the safety bounds.
                safety[(recipe.recipe_id, step.number)] = gold.expected.has_safety_bound
                if (
                    gold.expected.node_type == NodeType.Process
                    and is_thermal_action(gold.expected.action_phrase)
                    and not gold.expected.has_safety_bound
                ):
                    problems.append(
                        f"{label}: '{gold.expected.action_phrase}' is a heating action "
                        "but 'Heat can coagulate or scorch' is not ticked"
                    )
                continue
            unreviewed.append(label)
            gen_file = gen_dir / f"{recipe.recipe_id}_step{step.number:02d}.gen.json"
            if allow_unreviewed and gen_file.exists():
                node = ExtractedNode.model_validate_json(gen_file.read_text())
                pairs.append((node, CO(verdict=CriticVerdict.accept, grounding_quote=node.source_span)))
        all_pairs.append((pairs, recipe.recipe_id))

    if problems:
        console.print("[red]Reviewed steps that cannot become nodes:[/red]")
        for p in problems:
            console.print(f"  {p}")
        sys.exit(1)
    if unreviewed and not allow_unreviewed:
        console.print(f"[red]{len(unreviewed)} steps have no current review:[/red]")
        for label in unreviewed:
            console.print(f"  {label}")
        console.print("Review them in `k1 viz`, or pass --allow-unreviewed.")
        sys.exit(1)

    all_pairs = filter_recipe_pairs(all_pairs, final_dir / "L3")
    scope_report = json.loads((final_dir / "L3" / "scope_report.json").read_text())
    # A reviewed step should already fit the inventory. If the scope rule still
    # removes one, the review and config/dish.yaml disagree: stop and say where.
    dropped = [r for r in scope_report["records"] if r["dropped"]]
    if dropped and not allow_unreviewed:
        console.print("[red]Reviewed steps the scope rule would drop:[/red]")
        for r in dropped:
            console.print(f"  {r['recipe_id']} step {r['step_number']}: {r['reason']}")
        sys.exit(1)
    trimmed = [r for r in scope_report["records"] if not r["dropped"]]
    if trimmed:
        console.print(
            f"  [yellow]{len(trimmed)} steps had out-of-inventory entities removed "
            "-> final/L3/scope_report.json[/yellow]"
        )

    # Every path must end at the goal: add a closing Plate step where a source has none.
    all_pairs = complete_to_goal(all_pairs, final_dir / "L3")
    goal_report = json.loads((final_dir / "L3" / "goal_completion.json").read_text())
    if goal_report["plate_step_added"]:
        console.print(
            "  Goal: closing Plate step added by rule to "
            + ", ".join(r["recipe_id"] for r in goal_report["plate_step_added"])
        )
    for r in goal_report["goal_not_reached"]:
        console.print(
            f"  [yellow]Goal not reached: {r['recipe_id']} ends with eggs "
            f"{r['last_state']}; no Plate step added.[/yellow]"
        )

    graph = build_k1_graph(all_pairs, final_dir, safety_overrides=safety)
    graph.version = f"k1-final/{run_id}"
    (final_dir / "L3" / "fused_dag.json").write_text(graph.model_dump_json(indent=2))
    console.print(f"  [green]Final DAG:[/green] {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    if not run_validation(graph, recipes, final_dir):
        console.print(f"[red]{(final_dir / 'L4' / 'validation_report.txt').read_text()}[/red]")
        sys.exit(1)
    console.print("  [green]All 7 gates passed.[/green]")

    K1_OUT.mkdir(parents=True, exist_ok=True)
    final_path = K1_OUT / "graph.final.json"
    final_path.write_text(graph.model_dump_json(indent=2))
    auto_src = run_dir / "L3" / "fused_dag.json"
    if auto_src.exists():
        (K1_OUT / "graph.auto.json").write_text(auto_src.read_text())
    _, cypher_path = write_cypher(graph, K1_OUT, "graph.final.cypher")
    console.print(f"  Final (reviewed) -> {final_path}")
    console.print(f"  Final Cypher     -> {cypher_path}")
    console.print(f"  Auto (pipeline)  -> {K1_OUT / 'graph.auto.json'}")
    if unreviewed:
        console.print(f"  [yellow]{len(unreviewed)} steps came from the pipeline unreviewed.[/yellow]")
    console.print(f"  Compare them: k1 eval --run {run_id}")


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
