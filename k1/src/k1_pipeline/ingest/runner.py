"""
L1 Ingest — Runner
Orchestrates fetching + parsing for all recipes in the allowlist.
Writes canonical.json artifacts and returns per-recipe results.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from k1_pipeline.config_loader import load_recipes
from k1_pipeline.ingest.fetcher import fetch_html
from k1_pipeline.ingest.parser import parse_recipe
from k1_pipeline.models import CanonicalRecipe

console = Console()


def run_ingest(
    recipes_dir: Path,
    run_artifacts_dir: Path,
    *,
    force: bool = False,
    gold_only: bool = False,
) -> list[CanonicalRecipe]:
    """
    Fetch + parse all recipes from the allowlist.

    Args:
        recipes_dir: `data/recipes/` — where raw.html and canonical.json are stored.
        run_artifacts_dir: `data/artifacts/runs/{run_id}/L1/` — run-specific copies.
        force: Re-fetch even if raw.html already exists.
        gold_only: Only process gold-labelled recipes.

    Returns:
        List of successfully parsed CanonicalRecipe objects.
    """
    recipe_list = load_recipes()
    if gold_only:
        recipe_list = [r for r in recipe_list if r.get("gold", False)]

    l1_dir = run_artifacts_dir / "L1"
    l1_dir.mkdir(parents=True, exist_ok=True)

    results: list[CanonicalRecipe] = []
    errors: list[tuple[str, str]] = []

    table = Table(title="L1 Ingest", show_lines=True)
    table.add_column("Recipe ID")
    table.add_column("Steps")
    table.add_column("Gold")
    table.add_column("Status")

    for entry in recipe_list:
        recipe_id = entry["recipe_id"]
        url = entry["url"]
        variant_label = entry.get("variant_label", "")
        gold = entry.get("gold", False)

        dest = recipes_dir / recipe_id
        dest.mkdir(parents=True, exist_ok=True)

        canonical_path = dest / "canonical.json"

        # Skip if already done and not force
        if canonical_path.exists() and not force:
            try:
                recipe = CanonicalRecipe.model_validate_json(canonical_path.read_text())
                results.append(recipe)
                table.add_row(recipe_id, str(len(recipe.steps)), "✓" if gold else "", "[green]cached[/green]")
                continue
            except Exception:
                pass  # will re-parse below

        console.print(f"  Fetching [bold]{recipe_id}[/bold] from {url} ...")
        try:
            html = fetch_html(url, dest, force=force)
            recipe = parse_recipe(html, recipe_id, url, variant_label, gold)
        except Exception as e:
            errors.append((recipe_id, str(e)))
            table.add_row(recipe_id, "-", "✓" if gold else "", f"[red]ERROR: {e}[/red]")
            continue

        # Save canonical.json
        canonical_path.write_text(recipe.model_dump_json(indent=2))

        # Also copy to run artifacts
        (l1_dir / f"{recipe_id}.canonical.json").write_text(recipe.model_dump_json(indent=2))

        results.append(recipe)
        table.add_row(recipe_id, str(len(recipe.steps)), "✓" if gold else "", "[green]OK[/green]")

    console.print(table)

    if errors:
        console.print(f"\n[yellow]⚠ {len(errors)} recipe(s) failed:[/yellow]")
        for rid, err in errors:
            console.print(f"  {rid}: {err}")

    console.print(f"\n[green]✓ Ingested {len(results)}/{len(recipe_list)} recipes[/green]")
    return results
