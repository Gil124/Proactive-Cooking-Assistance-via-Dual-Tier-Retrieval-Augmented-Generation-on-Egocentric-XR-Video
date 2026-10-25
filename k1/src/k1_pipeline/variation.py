"""
variation.py -- Why K1 steps are ordered, and why recipes differ.

Reads config/variation_points.yaml (Notes/10-recipe-variation.md, A.3):

- action classes: each reviewed action phrase belongs to one class;
- order rules: the physical partial order between classes, each with a reason;
- preference points: where valid variations differ, each alternative with the
  outcome it serves.

REQUIRES edges are built from the order rules (fuse/dag_builder.py), so a
REQUIRES edge always means "must come before, for this physical reason". Order
that no rule fixes is a preference and lives only in each recipe's NEXT edges.

`check_config` verifies the file itself: the rules form no cycle, every class a
rule names exists, every quote is a verbatim substring of its recipe step, and
every recipe named exists. No model is called here.

Used by fuse/dag_builder.py, cli.py and tests.
"""

from __future__ import annotations

from functools import lru_cache

import networkx as nx

from k1_pipeline.config_loader import load_variation_points

PHYSICAL = "physical"
PREFERENCE = "preference"


def _norm(phrase: str) -> str:
    return " ".join(str(phrase).lower().split())


@lru_cache(maxsize=1)
def _config() -> dict:
    return load_variation_points()


@lru_cache(maxsize=1)
def _class_of_phrase() -> dict[str, str]:
    out: dict[str, str] = {}
    for cls, phrases in (_config().get("action_classes") or {}).items():
        for p in phrases or []:
            out[_norm(p)] = cls
    return out


def action_class(phrase: str) -> str | None:
    """The action class of a reviewed action phrase, or None when it is not listed."""
    return _class_of_phrase().get(_norm(phrase))


def order_rules() -> list[dict]:
    return list(_config().get("order_rules") or [])


def preference_points() -> list[dict]:
    return list(_config().get("preference_points") or [])


def required_pairs(classes: list[str | None]) -> tuple[list[tuple[int, int, dict]], list[dict]]:
    """
    For one recipe's actions in order (their classes), return
      - (i, j, rule) for every earlier action i and later action j that a rule orders,
      - one record per pair done against a rule (the `after` class came first).
    """
    pairs: list[tuple[int, int, dict]] = []
    violations: list[dict] = []
    for rule in order_rules():
        before, after = set(rule["before"]), set(rule["after"])
        for i, ci in enumerate(classes):
            for j in range(i + 1, len(classes)):
                cj = classes[j]
                if ci in before and cj in after:
                    pairs.append((i, j, rule))
                elif ci in after and cj in before:
                    violations.append({"rule_id": rule["id"], "first": i, "then": j})
    return pairs, violations


def check_config(recipes: dict) -> list[str]:
    """
    Problems in variation_points.yaml, as messages (empty = fine).
    `recipes` maps recipe_id -> CanonicalRecipe for the recipes in the corpus.
    """
    cfg = _config()
    problems: list[str] = []
    classes = set((cfg.get("action_classes") or {}).keys())

    seen: dict[str, str] = {}
    for cls, phrases in (cfg.get("action_classes") or {}).items():
        for p in phrases or []:
            if _norm(p) in seen and seen[_norm(p)] != cls:
                problems.append(f"'{p}' is in two classes: {seen[_norm(p)]} and {cls}")
            seen[_norm(p)] = cls

    order = nx.DiGraph()
    for rule in cfg.get("order_rules") or []:
        for side in ("before", "after"):
            for cls in rule.get(side) or []:
                if cls not in classes:
                    problems.append(f"rule {rule['id']}: unknown class '{cls}'")
        if not str(rule.get("reason") or "").strip():
            problems.append(f"rule {rule['id']}: no reason")
        problems += _check_source(rule.get("source"), f"rule {rule['id']}", recipes, allow_curated=True)
        for b in rule.get("before") or []:
            for a in rule.get("after") or []:
                order.add_edge(b, a)
    if not nx.is_directed_acyclic_graph(order):
        problems.append(f"order rules form a cycle: {nx.find_cycle(order)}")

    for point in cfg.get("preference_points") or []:
        if point.get("kind") not in ("structural", "parametric"):
            problems.append(f"preference {point['id']}: kind must be structural or parametric")
        alts = point.get("alternatives") or []
        if len(alts) < 2:
            problems.append(f"preference {point['id']}: needs at least two alternatives")
        for alt in alts:
            label = f"preference {point['id']} / {alt.get('choice')}"
            for rid in alt.get("recipes") or []:
                if rid not in recipes:
                    problems.append(f"{label}: unknown recipe '{rid}'")
            problems += _check_source(alt.get("source"), label, recipes, allow_curated=False)
    return problems


def _check_source(source, label: str, recipes: dict, allow_curated: bool) -> list[str]:
    if source is None:
        return []
    if source == "curated":
        return [] if allow_curated else [f"{label}: 'curated' is for physical rules only"]
    if not isinstance(source, dict):
        return [f"{label}: source must be a quote, 'curated' or null"]
    recipe = recipes.get(source.get("recipe_id"))
    if recipe is None:
        return [f"{label}: unknown recipe '{source.get('recipe_id')}'"]
    step = next((s for s in recipe.steps if s.number == source.get("step")), None)
    if step is None:
        return [f"{label}: {recipe.recipe_id} has no step {source.get('step')}"]
    if str(source.get("quote", "")) not in step.text:
        return [f"{label}: quote not found in {recipe.recipe_id} step {step.number}"]
    return []
