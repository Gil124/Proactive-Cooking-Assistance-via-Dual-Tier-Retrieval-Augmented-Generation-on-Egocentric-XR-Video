"""
gold.py -- Human review of K1 steps.

One reviewed step (data/gold/{recipe_id}_stepNN.gold.json) serves two purposes:
  - it is the gold label the pipeline output is scored against, and
  - it is the corrected step the final graph is built from (`k1 finalize`).

Each file records how it was made (`mode`), how long it took (`seconds_spent`),
and the definition it was made under (`definition_version`). Protocol:
Notes/09-k1-evaluation.md.

No model is called here. Used by viz/app.py, eval/correction.py, and cli.py.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import yaml

from k1_pipeline.config_loader import _CONFIG_DIR, get_excluded_recipes, load_dish
from k1_pipeline.fuse.entity_resolver import resolve_entity
from k1_pipeline.models import (
    CanonicalRecipe,
    CriticOutput,
    CriticVerdict,
    ExtractedNode,
    GoldNode,
    NodeType,
    StateCondition,
    TimingConstraints,
)
from k1_pipeline.physics import is_thermal_action
from k1_pipeline.scope import INGREDIENTS, apply_scope

DEFINITION_VERSION: str = str(load_dish()["definition_version"])

MODE_CORRECTED = "corrected"
MODE_FROM_SCRATCH = "from_scratch"

_K2_LABELS = ("liquid", "coagulating", "solid", "scorched")


# ── Review configuration and queue ────────────────────────────────────────────

def load_review_config() -> dict:
    path = _CONFIG_DIR / "gold_review.yaml"
    return (yaml.safe_load(path.read_text()) if path.exists() else None) or {}


def mode_for(recipe_id: str) -> str:
    scratch = load_review_config().get("from_scratch") or []
    return MODE_FROM_SCRATCH if recipe_id in scratch else MODE_CORRECTED


def idle_cap_seconds() -> float:
    return float(load_review_config().get("idle_cap_seconds", 120))


def load_queue(recipes_dir: Path) -> list[CanonicalRecipe]:
    """Every ingested recipe that is not excluded, in recipe_id order."""
    excluded = get_excluded_recipes()
    queue = []
    for path in sorted(recipes_dir.glob("*/canonical.json")):
        try:
            recipe = CanonicalRecipe.model_validate_json(path.read_text())
        except Exception:
            continue
        if recipe.recipe_id not in excluded:
            queue.append(recipe)
    return queue


# ── Gold files ────────────────────────────────────────────────────────────────

def gold_path(gold_dir: Path, recipe_id: str, step_n: int) -> Path:
    return gold_dir / f"{recipe_id}_step{step_n:02d}.gold.json"


def load_gold(gold_dir: Path, recipe_id: str, step_n: int) -> GoldNode | None:
    path = gold_path(gold_dir, recipe_id, step_n)
    if not path.exists():
        return None
    try:
        return GoldNode.model_validate_json(path.read_text())
    except Exception:
        return None


def is_current(gold: GoldNode | None) -> bool:
    """A gold file counts only when it was saved under the current definition."""
    return gold is not None and gold.definition_version == DEFINITION_VERSION


def step_status(gold_dir: Path, recipe_id: str, step_n: int) -> str:
    """'done', 'outdated' (saved under another definition), or 'open'."""
    gold = load_gold(gold_dir, recipe_id, step_n)
    if gold is None:
        return "open"
    return "done" if is_current(gold) else "outdated"


def clean_conditions(rows: list[dict] | None) -> list[dict]:
    """Drop blank rows, resolve aliases, and remove duplicates."""
    out: list[dict] = []
    for row in rows or []:
        entity = str(row.get("entity_id") or "").strip()
        label = str(row.get("k2_label") or "").strip()
        if not entity or label not in _K2_LABELS:
            continue
        item = {"entity_id": resolve_entity(entity), "k2_label": label}
        if item not in out:
            out.append(item)
    return out


def clean_tools(names: list[str] | None) -> list[str]:
    out: list[str] = []
    for name in names or []:
        name = str(name or "").strip()
        if name:
            resolved = resolve_entity(name)
            if resolved not in out:
                out.append(resolved)
    return out


def save_gold(
    gold_dir: Path,
    *,
    recipe_id: str,
    step_n: int,
    expected: dict,
    mode: str,
    seconds_spent: float,
    seeded_from_run: str,
    annotator: str,
    notes: str = "",
) -> Path:
    """
    Write one reviewed step. Time adds to what an earlier save under the same
    definition recorded, so reopening a step does not lose the first pass.
    """
    previous = load_gold(gold_dir, recipe_id, step_n)
    carried = previous.seconds_spent or 0.0 if is_current(previous) else 0.0
    entry = GoldNode.model_validate({
        "recipe_id": recipe_id,
        "step_number": step_n,
        "expected": {
            "node_type": expected["node_type"],
            "action_phrase": str(expected.get("action_phrase", "")).strip(),
            "pre_conditions": clean_conditions(expected.get("pre_conditions")),
            "post_conditions": clean_conditions(expected.get("post_conditions")),
            "tools": clean_tools(expected.get("tools")),
            "has_safety_bound": bool(expected.get("has_safety_bound", False)),
            "in_scope": bool(expected.get("in_scope", True)),
        },
        "annotator": annotator,
        "annotation_date": str(date.today()),
        "notes": notes.strip(),
        "mode": mode,
        "seconds_spent": round(carried + max(seconds_spent, 0.0), 1),
        "seeded_from_run": seeded_from_run,
        "definition_version": DEFINITION_VERSION,
    })
    gold_dir.mkdir(parents=True, exist_ok=True)
    path = gold_path(gold_dir, recipe_id, step_n)
    path.write_text(entry.model_dump_json(indent=2))
    return path


# ── Work timer ────────────────────────────────────────────────────────────────

class WorkTimer:
    """
    Active time on one step. `tick` is called on every interaction; a gap longer
    than the idle cap counts as the cap, so a break is not billed as work.
    The state is a plain dict so it can live in Streamlit's session_state.
    """

    @staticmethod
    def tick(state: dict, key: str, cap: float, now: float | None = None) -> float:
        now = time.time() if now is None else now
        if state.get("key") != key:
            state.clear()
            state.update({"key": key, "active": 0.0, "last": now})
            return 0.0
        state["active"] += min(max(now - state["last"], 0.0), cap)
        state["last"] = now
        return state["active"]

    @staticmethod
    def reset(state: dict) -> None:
        state.clear()


# ── Pipeline output for one step ──────────────────────────────────────────────

def auto_step(run_dir: Path, recipe_id: str, step_n: int) -> dict:
    """
    What the pipeline did with one step in a run, after the scope rule:
      {"status": "kept" | "dropped" | "missing", "reason": str, "expected": dict | None}
    `expected` has the same shape as GoldExpected. For a dropped step it still
    holds the raw extraction, so the reviewer can see what was thrown away.
    """
    gen_file = run_dir / "L2" / "gen" / f"{recipe_id}_step{step_n:02d}.gen.json"
    if not gen_file.exists():
        return {"status": "missing", "reason": "no extraction for this step", "expected": None}
    try:
        node = ExtractedNode.model_validate_json(gen_file.read_text())
    except Exception as e:
        return {"status": "missing", "reason": f"unreadable extraction: {e}", "expected": None}

    critic_dir = run_dir / "L2" / "critic"
    r2 = critic_dir / f"{recipe_id}_step{step_n:02d}.critic.r2.json"
    r1 = critic_dir / f"{recipe_id}_step{step_n:02d}.critic.json"
    critic_file = r2 if r2.exists() else r1
    rejected = False
    if critic_file.exists():
        try:
            rejected = json.loads(critic_file.read_text()).get("verdict") == "reject"
        except json.JSONDecodeError:
            pass

    raw = node.model_copy(deep=True)
    trimmed, record = apply_scope(node)
    shown = trimmed if trimmed is not None else raw

    expected = {
        "node_type": shown.node_type.value,
        "action_phrase": shown.action_phrase,
        "pre_conditions": clean_conditions(
            [{"entity_id": c.entity_id, "k2_label": c.k2_label.value} for c in shown.pre_conditions]
        ),
        "post_conditions": clean_conditions(
            [{"entity_id": c.entity_id, "k2_label": c.k2_label.value} for c in shown.post_conditions]
        ),
        "tools": clean_tools(shown.tools),
        # Safety bounds are attached at fusion to thermal Process nodes.
        "has_safety_bound": shown.node_type == NodeType.Process and is_thermal_action(shown.action_phrase),
        "in_scope": trimmed is not None and not rejected,
    }
    if rejected:
        return {"status": "dropped", "reason": "critic rejected the extraction", "expected": expected}
    if trimmed is None:
        return {"status": "dropped", "reason": record["reason"], "expected": expected}
    return {"status": "kept", "reason": "", "expected": expected}


# ── Reviewed step -> graph node ───────────────────────────────────────────────

def gold_to_pair(
    gold: GoldNode,
    recipe: CanonicalRecipe,
    run_dir: Path | None = None,
) -> tuple[ExtractedNode, CriticOutput]:
    """
    Turn a reviewed step into the (node, critic) pair that fusion consumes.
    The source span is the pipeline's when it is still a substring of the step,
    otherwise the whole step text. Timing constraints are not part of the review
    form, so the pipeline's are carried over as extracted.
    """
    step = next(s for s in recipe.steps if s.number == gold.step_number)
    span = step.text
    timing = None
    if run_dir is not None:
        gen_file = run_dir / "L2" / "gen" / f"{gold.recipe_id}_step{gold.step_number:02d}.gen.json"
        if gen_file.exists():
            try:
                gen = json.loads(gen_file.read_text())
                candidate = gen.get("source_span", "")
                if candidate and candidate in step.text:
                    span = candidate
                if gen.get("timing_constraints"):
                    timing = TimingConstraints.model_validate(gen["timing_constraints"])
            except (json.JSONDecodeError, ValueError):
                pass

    exp = gold.expected
    conditions = lambda items: [  # noqa: E731
        StateCondition(entity_id=c.entity_id, physics_state=c.k2_label.value, k2_label=c.k2_label)
        for c in items
    ]
    entities = [c.entity_id for c in exp.pre_conditions + exp.post_conditions]
    node = ExtractedNode(
        recipe_id=gold.recipe_id,
        step_number=gold.step_number,
        node_type=exp.node_type,
        action_phrase=exp.action_phrase,
        pre_conditions=conditions(exp.pre_conditions),
        post_conditions=conditions(exp.post_conditions),
        timing_constraints=timing,
        ingredients=list(dict.fromkeys(e for e in entities if e in INGREDIENTS)),
        tools=list(exp.tools),
        source_span=span,
        confidence=1.0,
        extractor_model=f"human/{gold.annotator}",
    )
    critic = CriticOutput(
        node_id=node.node_id,
        verdict=CriticVerdict.accept,
        grounding_quote=span,
        critic_model=f"human/{gold.annotator}",
    )
    return node, critic
