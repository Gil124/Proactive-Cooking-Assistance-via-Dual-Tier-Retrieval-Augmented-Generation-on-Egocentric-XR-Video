"""
scope.py -- Shared source of truth for what belongs to the dish.

The dish specification (config/dish.yaml) fixes a closed inventory of
ingredients and utensils. A recipe variation may only use that inventory
(Notes/10-recipe-variation.md). This module applies the rule deterministically:

- Entities (conditions, ingredients, tools) are checked against the inventory
  allowlist after alias resolution. Anything else is removed from the node.
- Free text (action_phrase) cannot be checked against an allowlist, so it is
  scanned for the `known_out_of_inventory` terms and for the names of entities
  the node itself listed and lost.
- A node that has nothing left, or whose action still names an
  out-of-inventory item, is dropped.
- A recipe whose steps stop before the goal (eggs on the plate) gets one closing
  Plate step added by rule, marked as such.

No model is called here.

Imported by: extract/generator.py, critic/critic.py, critic/jev.py, cli.py,
validate/gates.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from k1_pipeline.config_loader import load_dish
from k1_pipeline.fuse.entity_resolver import resolve_entity
from k1_pipeline.models import (
    CriticOutput as _CriticOutput,
    CriticVerdict,
    ExtractedNode as _ExtractedNode,
    K2Label,
    NodeType,
    StateCondition,
)

if TYPE_CHECKING:
    from k1_pipeline.models import CriticOutput, ExtractedNode

_DISH = load_dish()

INGREDIENTS: frozenset[str] = frozenset(_DISH["inventory"]["ingredients"])
UTENSILS: frozenset[str] = frozenset(_DISH["inventory"]["utensils"])
INVENTORY: frozenset[str] = INGREDIENTS | UTENSILS

GOAL_ENTITY: str = _DISH["goal"]["entity"]
GOAL_LABELS: frozenset[str] = frozenset(_DISH["goal"]["k2_labels"])
GOAL_LOCATION: str = _DISH["goal"]["location"]

# Marks a step that no source states. It is added so every path ends at the goal.
RULE_MODEL = "rule/goal_completion"
GOAL_ACTION = f"transfer {GOAL_ENTITY}s to {GOAL_LOCATION}"

_KNOWN_OUT: tuple[str, ...] = tuple(t.lower() for t in _DISH.get("known_out_of_inventory", []))


def _mentions(term: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE) is not None


def out_of_inventory_mentions(text: str, extra_terms: list[str] | None = None) -> list[str]:
    """Out-of-inventory terms named in `text`, matched on whole words."""
    terms = list(_KNOWN_OUT) + [t.lower() for t in (extra_terms or [])]
    found = [t for t in dict.fromkeys(terms) if t and _mentions(t, text)]
    return found


def out_of_inventory_entities(node: "ExtractedNode") -> list[str]:
    """Entity names on the node, as written, that do not resolve into the inventory."""
    names = (
        [c.entity_id for c in node.pre_conditions + node.post_conditions]
        + list(node.ingredients)
        + list(node.tools)
    )
    return list(dict.fromkeys(n for n in names if resolve_entity(n) not in INVENTORY))


def action_scope_issues(node: "ExtractedNode") -> list[str]:
    """Out-of-inventory terms the action_phrase still names."""
    extra = [n.replace("_", " ") for n in out_of_inventory_entities(node)]
    return out_of_inventory_mentions(node.action_phrase, extra)


def scope_prompt_block() -> str:
    """The inventory and trimming rules, worded for the generator and the critic."""
    return (
        "The dish is one serving of scrambled eggs made at a fixed station.\n"
        f"Ingredients on the station: {', '.join(sorted(INGREDIENTS))}.\n"
        f"Utensils on the station: {', '.join(sorted(UTENSILS))}.\n"
        "Interchangeable items count as the inventory item and take its name: a fork "
        "is the whisk, a wooden spoon is the spatula, a jug is the bowl, a skillet or "
        "saucepan is the pan, a stove or hob is the heat_source.\n"
        "The dish is finished when the eggs are on the plate.\n"
        "Nothing else exists. Milk, cream, cheese, bread or toast, other herbs, "
        "garnishes, sauces, and other equipment are outside the dish."
    )


def _dedupe_conditions(conditions: list) -> list:
    seen: set[tuple[str, str]] = set()
    kept = []
    for c in conditions:
        key = (c.entity_id, c.k2_label.value)
        if key not in seen:
            seen.add(key)
            kept.append(c)
    return kept


def apply_scope(node: "ExtractedNode") -> tuple["ExtractedNode | None", dict]:
    """
    Trim one extracted node to the inventory.

    Returns (node, record). `node` is None when the step is dropped. `record`
    says what was removed and why, for L3/scope_report.json.
    """
    record: dict = {
        "recipe_id": node.recipe_id,
        "step_number": node.step_number,
        "action_phrase": node.action_phrase,
        "removed_entities": [],
        "dropped": False,
        "reason": "",
    }

    def _drop(reason: str) -> tuple[None, dict]:
        record["dropped"] = True
        record["reason"] = reason
        return None, record

    if not node.in_scope:
        return _drop("generator marked the step as outside the dish")

    mentions = action_scope_issues(node)
    record["removed_entities"] = out_of_inventory_entities(node)

    for cond in node.pre_conditions + node.post_conditions:
        cond.entity_id = resolve_entity(cond.entity_id)
    node.pre_conditions = _dedupe_conditions(
        [c for c in node.pre_conditions if c.entity_id in INVENTORY]
    )
    node.post_conditions = _dedupe_conditions(
        [c for c in node.post_conditions if c.entity_id in INVENTORY]
    )
    node.ingredients = list(dict.fromkeys(
        e for e in (resolve_entity(i) for i in node.ingredients) if e in INGREDIENTS
    ))
    node.tools = list(dict.fromkeys(
        e for e in (resolve_entity(t) for t in node.tools) if e in UTENSILS
    ))

    if mentions:
        return _drop(f"action_phrase names out-of-inventory items: {', '.join(mentions)}")

    if not (node.pre_conditions or node.post_conditions or node.ingredients or node.tools):
        return _drop("no inventory item is involved")

    if node.node_type == NodeType.Process and not (node.pre_conditions and node.post_conditions):
        return _drop("Process has no state change on an inventory item")

    return node, record


def filter_recipe_pairs(
    all_pairs: list[tuple[list[tuple["ExtractedNode", "CriticOutput"]], str]],
    l3_dir: Path,
) -> list[tuple[list[tuple["ExtractedNode", "CriticOutput"]], str]]:
    """
    Apply the scope rule to every (node, critic) pair before fusion.
    Writes L3/scope_report.json with every trimmed entity and dropped step.
    """
    l3_dir.mkdir(parents=True, exist_ok=True)
    kept_all = []
    records: list[dict] = []
    for pairs, recipe_id in all_pairs:
        kept = []
        for node, critic in pairs:
            trimmed, record = apply_scope(node)
            if record["dropped"] or record["removed_entities"]:
                records.append(record)
            if trimmed is not None:
                kept.append((trimmed, critic))
        kept_all.append((kept, recipe_id))

    report = {
        "steps_dropped": sum(1 for r in records if r["dropped"]),
        "steps_trimmed": sum(1 for r in records if not r["dropped"]),
        "records": records,
    }
    (l3_dir / "scope_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return kept_all


def complete_to_goal(
    all_pairs: list[tuple[list[tuple["ExtractedNode", "CriticOutput"]], str]],
    l3_dir: Path,
) -> list[tuple[list[tuple["ExtractedNode", "CriticOutput"]], str]]:
    """
    Make every recipe end at the goal state of the dish (config/dish.yaml).

    A source often stops at the pan, or ends with a serving line that is outside
    the dish and was dropped. For a recipe with no Plate step, one closing Plate
    step is appended: the eggs keep the state the last step left them in and move
    to the plate. It carries no source span and names RULE_MODEL as its extractor,
    so it can always be told apart from a step a source states.

    A recipe whose eggs never reach a goal state is left as it is and reported.
    Writes L3/goal_completion.json.
    """
    l3_dir.mkdir(parents=True, exist_ok=True)
    added: list[dict] = []
    not_reaching: list[dict] = []
    completed = []

    for pairs, recipe_id in all_pairs:
        if not pairs or any(n.node_type == NodeType.Plate for n, _ in pairs):
            completed.append((pairs, recipe_id))
            continue

        last_state = None
        for node, _ in pairs:
            for cond in node.post_conditions:
                if cond.entity_id == GOAL_ENTITY:
                    last_state = cond.k2_label.value
        if last_state not in GOAL_LABELS:
            not_reaching.append({"recipe_id": recipe_id, "last_state": last_state})
            completed.append((pairs, recipe_id))
            continue

        state = StateCondition(
            entity_id=GOAL_ENTITY, physics_state=last_state, k2_label=K2Label(last_state)
        )
        node = _ExtractedNode(
            recipe_id=recipe_id,
            step_number=max(n.step_number for n, _ in pairs) + 1,
            node_type=NodeType.Plate,
            action_phrase=GOAL_ACTION,
            pre_conditions=[state],
            post_conditions=[state.model_copy()],
            ingredients=[GOAL_ENTITY],
            tools=[GOAL_LOCATION],
            source_span="",
            confidence=1.0,
            extractor_model=RULE_MODEL,
        )
        critic = _CriticOutput(
            node_id=node.node_id,
            verdict=CriticVerdict.accept,
            grounding_quote="",
            critic_model=RULE_MODEL,
        )
        added.append({"recipe_id": recipe_id, "step_number": node.step_number, "state": last_state})
        completed.append((pairs + [(node, critic)], recipe_id))

    (l3_dir / "goal_completion.json").write_text(
        json.dumps({"plate_step_added": added, "goal_not_reached": not_reaching}, indent=2)
    )
    return completed
