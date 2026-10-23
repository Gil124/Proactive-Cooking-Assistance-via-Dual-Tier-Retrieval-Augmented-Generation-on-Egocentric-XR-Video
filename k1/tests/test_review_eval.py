"""
Tests for the human-review workflow: gold files, timing, pipeline-vs-review
metrics, and building the final graph. No LLM calls, no network.
"""

import json
from pathlib import Path

import pytest

from k1_pipeline.eval.correction import compare_step, correction_metrics, render_section, write_outputs
from k1_pipeline.gold import (
    DEFINITION_VERSION,
    MODE_CORRECTED,
    MODE_FROM_SCRATCH,
    WorkTimer,
    auto_step,
    gold_to_pair,
    is_current,
    load_gold,
    save_gold,
    step_status,
)
from k1_pipeline.models import CanonicalRecipe, GoldNode, RecipeStep


def _recipe(recipe_id: str = "r1") -> CanonicalRecipe:
    return CanonicalRecipe(
        recipe_id=recipe_id,
        title="t",
        source_url="http://example.com",
        variant_label="v",
        ingredients=[],
        tools=[],
        steps=[
            RecipeStep(number=1, text="Whisk the eggs and milk in a bowl."),
            RecipeStep(number=2, text="Cook the eggs in the pan, stirring."),
            RecipeStep(number=3, text="Serve with toast."),
        ],
    )


def _gen(run_dir: Path, recipe_id: str, step_n: int, **fields) -> None:
    node = {
        "recipe_id": recipe_id,
        "step_number": step_n,
        "node_type": "Process",
        "action_phrase": "whisk eggs",
        "pre_conditions": [{"entity_id": "egg", "physics_state": "raw", "k2_label": "liquid"}],
        "post_conditions": [{"entity_id": "egg", "physics_state": "whisked", "k2_label": "liquid"}],
        "ingredients": ["egg"],
        "tools": ["bowl"],
        "source_span": "Whisk the eggs",
        "confidence": 0.9,
    }
    node.update(fields)
    gen_dir = run_dir / "L2" / "gen"
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / f"{recipe_id}_step{step_n:02d}.gen.json").write_text(json.dumps(node))


def _expected(**fields) -> dict:
    base = {
        "node_type": "Process",
        "action_phrase": "whisk eggs",
        "pre_conditions": [{"entity_id": "egg", "k2_label": "liquid"}],
        "post_conditions": [{"entity_id": "egg", "k2_label": "liquid"}],
        "tools": ["bowl"],
        "has_safety_bound": False,
        "in_scope": True,
    }
    base.update(fields)
    return base


def _save(gold_dir: Path, step_n: int, mode=MODE_CORRECTED, seconds=30.0, **fields) -> Path:
    return save_gold(
        gold_dir, recipe_id="r1", step_n=step_n, expected=_expected(**fields),
        mode=mode, seconds_spent=seconds, seeded_from_run="run1", annotator="tester",
    )


# ── Gold files ────────────────────────────────────────────────────────────────

def test_save_records_mode_time_and_definition(tmp_path):
    _save(tmp_path, 1, seconds=42.0)
    gold = load_gold(tmp_path, "r1", 1)
    assert gold.mode == MODE_CORRECTED
    assert gold.seconds_spent == 42.0
    assert gold.seeded_from_run == "run1"
    assert gold.definition_version == DEFINITION_VERSION
    assert step_status(tmp_path, "r1", 1) == "done"


def test_resaving_adds_time(tmp_path):
    _save(tmp_path, 1, seconds=40.0)
    _save(tmp_path, 1, seconds=15.0)
    assert load_gold(tmp_path, "r1", 1).seconds_spent == 55.0


def test_file_from_older_definition_is_outdated_and_time_restarts(tmp_path):
    legacy = {
        "recipe_id": "r1", "step_number": 1,
        "expected": {"node_type": "Process", "action_phrase": "add milk and whisk"},
        "annotator": "gil", "annotation_date": "2026-09-28",
    }
    (tmp_path / "r1_step01.gold.json").write_text(json.dumps(legacy))
    assert not is_current(load_gold(tmp_path, "r1", 1))
    assert step_status(tmp_path, "r1", 1) == "outdated"
    _save(tmp_path, 1, seconds=20.0)
    assert load_gold(tmp_path, "r1", 1).seconds_spent == 20.0


def test_save_resolves_aliases_and_drops_blank_rows(tmp_path):
    _save(
        tmp_path, 1,
        pre_conditions=[{"entity_id": "ovos", "k2_label": "liquid"}, {"entity_id": "", "k2_label": "liquid"}],
        tools=["frigideira", "", "wooden spoon"],
    )
    exp = load_gold(tmp_path, "r1", 1).expected
    assert [c.entity_id for c in exp.pre_conditions] == ["egg"]
    assert exp.tools == ["pan", "spatula"]


def test_out_of_scope_step_needs_no_action_phrase(tmp_path):
    _save(tmp_path, 3, in_scope=False, action_phrase="", pre_conditions=[], post_conditions=[], tools=[])
    assert load_gold(tmp_path, "r1", 3).expected.in_scope is False


# ── Timer ─────────────────────────────────────────────────────────────────────

def test_timer_sums_gaps_and_caps_idle_time():
    state: dict = {}
    assert WorkTimer.tick(state, "a", cap=120, now=1000) == 0.0
    assert WorkTimer.tick(state, "a", cap=120, now=1030) == 30.0
    # A 20-minute break counts as the cap, not as work.
    assert WorkTimer.tick(state, "a", cap=120, now=2230) == 150.0


def test_timer_restarts_on_another_step():
    state: dict = {}
    WorkTimer.tick(state, "a", cap=120, now=1000)
    WorkTimer.tick(state, "a", cap=120, now=1050)
    assert WorkTimer.tick(state, "b", cap=120, now=1060) == 0.0


# ── Pipeline output for a step ────────────────────────────────────────────────

def test_auto_step_kept_is_trimmed_to_inventory(tmp_path):
    _gen(tmp_path, "r1", 1, ingredients=["egg", "milk"],
         pre_conditions=[
             {"entity_id": "egg", "physics_state": "raw", "k2_label": "liquid"},
             {"entity_id": "milk", "physics_state": "raw", "k2_label": "liquid"},
         ])
    auto = auto_step(tmp_path, "r1", 1)
    assert auto["status"] == "kept"
    assert auto["expected"]["pre_conditions"] == [{"entity_id": "egg", "k2_label": "liquid"}]
    assert auto["expected"]["in_scope"] is True


def test_auto_step_dropped_by_scope_and_by_critic(tmp_path):
    _gen(tmp_path, "r1", 3, node_type="Plate", action_phrase="serve with toast")
    assert auto_step(tmp_path, "r1", 3)["status"] == "dropped"

    _gen(tmp_path, "r1", 2)
    critic_dir = tmp_path / "L2" / "critic"
    critic_dir.mkdir(parents=True)
    (critic_dir / "r1_step02.critic.json").write_text(json.dumps({"verdict": "reject"}))
    auto = auto_step(tmp_path, "r1", 2)
    assert auto["status"] == "dropped" and "critic" in auto["reason"]


def test_auto_step_missing(tmp_path):
    assert auto_step(tmp_path, "r1", 9)["status"] == "missing"


def test_auto_step_marks_thermal_process_as_safety_bound(tmp_path):
    _gen(tmp_path, "r1", 2, action_phrase="cook eggs over low heat")
    assert auto_step(tmp_path, "r1", 2)["expected"]["has_safety_bound"] is True


# ── Comparison ────────────────────────────────────────────────────────────────

def _auto(status="kept", **fields) -> dict:
    return {"status": status, "reason": "", "expected": _expected(**fields)}


def test_identical_step_is_unchanged():
    row = compare_step(_auto(), _expected())
    assert row["unchanged"] and row["scope_agrees"] and row["fields_changed"] == []


def test_reworded_action_is_unchanged_only_when_ignoring_wording():
    row = compare_step(_auto(action_phrase="whisk the eggs"), _expected(action_phrase="beat eggs"))
    assert row["fields_changed"] == ["action_phrase"]
    assert not row["unchanged"] and row["unchanged_ignoring_wording"]


def test_condition_difference_is_counted():
    row = compare_step(
        _auto(post_conditions=[{"entity_id": "egg", "k2_label": "solid"}]),
        _expected(post_conditions=[{"entity_id": "egg", "k2_label": "coagulating"}]),
    )
    assert row["fields_changed"] == ["post_conditions"]
    assert (row["post_conditions_tp"], row["post_conditions_fp"], row["post_conditions_fn"]) == (0, 1, 1)


def test_scope_disagreement_both_ways():
    kept_wrongly = compare_step(_auto(), _expected(in_scope=False))
    assert not kept_wrongly["scope_agrees"] and not kept_wrongly["unchanged"]
    dropped_wrongly = compare_step(_auto(status="dropped"), _expected())
    assert not dropped_wrongly["scope_agrees"]
    both_drop = compare_step(_auto(status="dropped"), _expected(in_scope=False))
    assert both_drop["scope_agrees"] and both_drop["unchanged"]


# ── End-to-end metrics ────────────────────────────────────────────────────────

@pytest.fixture
def workspace(tmp_path):
    recipes_dir = tmp_path / "recipes"
    (recipes_dir / "r1").mkdir(parents=True)
    (recipes_dir / "r1" / "canonical.json").write_text(_recipe().model_dump_json())
    run_dir = tmp_path / "runs" / "run1"
    _gen(run_dir, "r1", 1)                                      # correct
    _gen(run_dir, "r1", 2, action_phrase="cook eggs",           # wrong post label
         post_conditions=[{"entity_id": "egg", "physics_state": "set", "k2_label": "solid"}])
    _gen(run_dir, "r1", 3, node_type="Plate", action_phrase="serve eggs")  # should be dropped
    gold_dir = tmp_path / "gold"
    return recipes_dir, run_dir, gold_dir


def test_metrics_count_edits_time_and_scope(workspace):
    recipes_dir, run_dir, gold_dir = workspace
    _save(gold_dir, 1, seconds=20.0)
    _save(gold_dir, 2, seconds=60.0, action_phrase="cook eggs", has_safety_bound=True,
          post_conditions=[{"entity_id": "egg", "k2_label": "coagulating"}])
    _save(gold_dir, 3, mode=MODE_FROM_SCRATCH, seconds=100.0, in_scope=False)

    m = correction_metrics("run1", run_dir, recipes_dir, gold_dir)
    assert m["coverage"]["steps_reviewed"] == 3
    assert m["accuracy_all"]["wrongly_kept"] == 1
    assert m["accuracy_all"]["scope_agreement_pct"] == 66.7
    assert m["accuracy_all"]["field_accuracy_pct"]["post_conditions"] == 50.0
    assert m["accuracy_all"]["unchanged_pct"] == 33.3
    assert m["effort"]["scope_fixes"] == 1
    assert m["effort"]["edits_by_field"]["post_conditions"] == 1
    assert m["effort"]["total_edits"] == 2
    assert m["time"]["corrected"]["mean_seconds_per_step"] == 40.0
    assert m["time"]["from_scratch"]["mean_seconds_per_step"] == 100.0
    assert m["time"]["saving"]["seconds_saved_per_step"] == 60.0
    assert m["graph"] is None

    section = render_section(m)
    assert "Steps reviewed | 3/3" in section
    write_outputs(m, run_dir / "eval")
    csv_text = (run_dir / "eval" / "correction_steps.csv").read_text()
    assert len(csv_text.splitlines()) == 4
    assert json.loads((run_dir / "eval" / "correction.json").read_text())["run_id"] == "run1"


def test_metrics_ignore_outdated_gold(workspace):
    recipes_dir, run_dir, gold_dir = workspace
    gold_dir.mkdir()
    (gold_dir / "r1_step01.gold.json").write_text(json.dumps({
        "recipe_id": "r1", "step_number": 1,
        "expected": {"node_type": "Process", "action_phrase": "x"},
        "annotator": "gil", "annotation_date": "2026-09-28",
    }))
    m = correction_metrics("run1", run_dir, recipes_dir, gold_dir)
    assert m["coverage"]["steps_reviewed"] == 0
    assert m["coverage"]["gold_files_out_of_date"] == 1
    render_section(m)  # no reviewed steps must still render


# ── Reviewed step -> node ─────────────────────────────────────────────────────

def test_gold_to_pair_builds_a_grounded_human_node(tmp_path):
    _save(tmp_path, 1, pre_conditions=[{"entity_id": "egg", "k2_label": "liquid"},
                                       {"entity_id": "salt", "k2_label": "solid"}])
    gold = load_gold(tmp_path, "r1", 1)
    node, critic = gold_to_pair(gold, _recipe())
    assert node.source_span in _recipe().steps[0].text
    assert node.ingredients == ["egg", "salt"]
    assert node.tools == ["bowl"]
    assert node.extractor_model == "human/tester"
    assert critic.verdict.value == "accept"


def test_existing_legacy_gold_files_still_parse():
    gold_dir = Path(__file__).parent.parent / "data" / "gold"
    for path in gold_dir.glob("*.gold.json"):
        GoldNode.model_validate_json(path.read_text())


def test_reviewed_heat_decision_sets_safety_bounds(tmp_path):
    from k1_pipeline.fuse.dag_builder import build_k1_graph

    # "stir eggs" has no heating word, so the wording alone attaches no bounds.
    _save(tmp_path, 2, action_phrase="stir eggs", has_safety_bound=True,
          post_conditions=[{"entity_id": "egg", "k2_label": "coagulating"}])
    pair = gold_to_pair(load_gold(tmp_path, "r1", 2), _recipe())

    by_wording = build_k1_graph([([pair], "r1")], tmp_path / "a")
    assert by_wording.nodes[0].safety_bounds == []

    pair = gold_to_pair(load_gold(tmp_path, "r1", 2), _recipe())
    reviewed = build_k1_graph([([pair], "r1")], tmp_path / "b", safety_overrides={("r1", 2): True})
    assert reviewed.nodes[0].safety_bounds
    assert any(e.edge_type == "HAS_SAFETY_BOUND" for e in reviewed.edges)


def test_gold_to_pair_carries_pipeline_timing(tmp_path):
    run_dir = tmp_path / "run"
    _gen(run_dir, "r1", 2, source_span="Cook the eggs",
         timing_constraints={"duration_s": 60.0, "deadline": None})
    _save(tmp_path, 2, action_phrase="cook eggs", has_safety_bound=True)
    node, _ = gold_to_pair(load_gold(tmp_path, "r1", 2), _recipe(), run_dir)
    assert node.timing_constraints.duration_s == 60.0
    assert node.source_span == "Cook the eggs"
