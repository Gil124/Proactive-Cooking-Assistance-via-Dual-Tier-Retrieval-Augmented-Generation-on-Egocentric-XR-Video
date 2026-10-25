"""
Tests for splitting a recipe step into atomic actions: gold storage, building
graph nodes from sub-steps, reading multi-node pipeline output, and the
generator's per-action files. No LLM calls (the generator call is stubbed).
"""

import json
from pathlib import Path

import pytest

from k1_pipeline.eval.correction import correction_metrics, render_section
from k1_pipeline.fuse.dag_builder import build_k1_graph
from k1_pipeline.gold import (
    MODE_CORRECTED,
    auto_step,
    gold_to_pairs,
    load_gold,
    may_be_compound,
    save_gold,
    save_split,
)
from k1_pipeline.models import (
    CanonicalRecipe,
    ExtractedNode,
    ExtractedStep,
    GoldNode,
    RecipeStep,
    artifact_stem,
)


def _recipe() -> CanonicalRecipe:
    return CanonicalRecipe(
        recipe_id="r1", title="t", source_url="http://example.com", variant_label="v",
        ingredients=[], tools=[],
        steps=[
            RecipeStep(number=1, text="Crack the eggs into a bowl and whisk them."),
            RecipeStep(number=2, text="Melt the butter, then cook the eggs for 2 minutes."),
        ],
    )


def _action(phrase, pre="liquid", post="liquid", **fields) -> dict:
    base = {
        "node_type": "Process",
        "action_phrase": phrase,
        "pre_conditions": [{"entity_id": "egg", "k2_label": pre}],
        "post_conditions": [{"entity_id": "egg", "k2_label": post}],
        "tools": ["bowl"],
        "has_safety_bound": False,
        "in_scope": True,
    }
    base.update(fields)
    return base


def _review(gold_dir: Path, step_n: int, phrase: str, seconds=30.0, **fields) -> None:
    save_gold(
        gold_dir, recipe_id="r1", step_n=step_n, expected=_action(phrase, **fields),
        mode=MODE_CORRECTED, seconds_spent=seconds, seeded_from_run="run1", annotator="tester",
    )


# ── Gold storage ──────────────────────────────────────────────────────────────

def test_save_split_keeps_review_and_time(tmp_path):
    _review(tmp_path, 1, "crack and whisk eggs", seconds=30)
    save_split(tmp_path, recipe_id="r1", step_n=1, seconds_spent=12,
               sub_steps=[_action("crack eggs into bowl"), _action("whisk eggs")])
    gold = load_gold(tmp_path, "r1", 1)
    assert [a.action_phrase for a in gold.graph_steps()] == ["crack eggs into bowl", "whisk eggs"]
    assert gold.expected.action_phrase == "crack and whisk eggs"  # step-level label unchanged
    assert gold.seconds_spent == 30 and gold.split_seconds_spent == 12
    assert gold.split_checked


def test_one_action_means_keep_as_one(tmp_path):
    _review(tmp_path, 1, "whisk eggs")
    save_split(tmp_path, recipe_id="r1", step_n=1, seconds_spent=3, sub_steps=[_action("whisk eggs")])
    gold = load_gold(tmp_path, "r1", 1)
    assert gold.sub_steps == [] and gold.split_checked
    assert [a.action_phrase for a in gold.graph_steps()] == ["whisk eggs"]


def test_resaving_the_review_keeps_the_split(tmp_path):
    _review(tmp_path, 1, "crack and whisk eggs")
    save_split(tmp_path, recipe_id="r1", step_n=1, seconds_spent=5,
               sub_steps=[_action("crack eggs into bowl"), _action("whisk eggs")])
    _review(tmp_path, 1, "crack and whisk eggs in bowl", seconds=4)
    gold = load_gold(tmp_path, "r1", 1)
    assert len(gold.sub_steps) == 2 and gold.split_seconds_spent == 5


def test_split_needs_a_review_and_action_phrases(tmp_path):
    with pytest.raises(ValueError):
        save_split(tmp_path, recipe_id="r1", step_n=1, seconds_spent=0, sub_steps=[_action("x")])
    _review(tmp_path, 1, "crack and whisk eggs")
    with pytest.raises(ValueError):
        save_split(tmp_path, recipe_id="r1", step_n=1, seconds_spent=0,
                   sub_steps=[_action("crack eggs"), _action("")])


def test_single_sub_step_is_invalid():
    with pytest.raises(ValueError):
        GoldNode.model_validate({
            "recipe_id": "r1", "step_number": 1, "expected": _action("x"),
            "sub_steps": [_action("x")], "annotator": "t", "annotation_date": "2026-10-23",
        })


def test_compound_hint(tmp_path):
    _review(tmp_path, 1, "crack and whisk eggs")
    _review(tmp_path, 2, "cook eggs over low heat folding slowly")
    assert may_be_compound(load_gold(tmp_path, "r1", 1))
    assert not may_be_compound(load_gold(tmp_path, "r1", 2))
    assert may_be_compound(load_gold(tmp_path, "r1", 2), {"cook eggs over low heat folding slowly"})


# ── Sub-steps -> graph ────────────────────────────────────────────────────────

def test_split_step_becomes_ordered_nodes_with_own_heat(tmp_path):
    run_dir = tmp_path / "run"
    gen = run_dir / "L2" / "gen"
    gen.mkdir(parents=True)
    (gen / "r1_step02.gen.json").write_text(json.dumps({
        "recipe_id": "r1", "step_number": 2, "node_type": "Process", "action_phrase": "x",
        "pre_conditions": [{"entity_id": "egg", "physics_state": "raw", "k2_label": "liquid"}],
        "post_conditions": [{"entity_id": "egg", "physics_state": "set", "k2_label": "solid"}],
        "source_span": "Melt the butter", "confidence": 0.9,
        "timing_constraints": {"duration_s": 120.0, "deadline": None},
    }))
    _review(tmp_path, 1, "crack and whisk eggs")
    _review(tmp_path, 2, "melt butter and cook eggs", has_safety_bound=True, post="coagulating")
    save_split(tmp_path, recipe_id="r1", step_n=2, seconds_spent=0, sub_steps=[
        _action("melt butter", pre="liquid", post="liquid", has_safety_bound=False,
                pre_conditions=[{"entity_id": "butter", "k2_label": "solid"}],
                post_conditions=[{"entity_id": "butter", "k2_label": "liquid"}]),
        _action("cook eggs", post="coagulating", has_safety_bound=True),
    ])

    pairs, safety = [], {}
    for step_n in (1, 2):
        for node, critic, action in gold_to_pairs(load_gold(tmp_path, "r1", step_n), _recipe(), run_dir):
            pairs.append((node, critic))
            safety[str(node.node_id)] = action.has_safety_bound

    assert [(n.step_number, n.sub_step) for n, _ in pairs] == [(1, 1), (2, 1), (2, 2)]
    melt, cook = pairs[1][0], pairs[2][0]
    assert melt.timing_constraints is None
    assert cook.timing_constraints.duration_s == 120.0  # goes to the action with heat
    assert cook.source_span == _recipe().steps[1].text

    graph = build_k1_graph([(pairs, "r1")], tmp_path / "g", safety_overrides=safety)
    by_phrase = {n.action_phrase: n for n in graph.nodes}
    assert not by_phrase["melt butter"].safety_bounds
    assert by_phrase["cook eggs"].safety_bounds
    nxt = {(e.from_node_id, e.to_node_id) for e in graph.edges if e.edge_type == "NEXT"}
    assert (by_phrase["crack and whisk eggs"].node_id, by_phrase["melt butter"].node_id) in nxt
    assert (by_phrase["melt butter"].node_id, by_phrase["cook eggs"].node_id) in nxt


def test_requires_links_sub_steps_of_one_step(tmp_path):
    _review(tmp_path, 1, "crack and whisk eggs")
    save_split(tmp_path, recipe_id="r1", step_n=1, seconds_spent=0, sub_steps=[
        _action("crack the eggs into a bowl", pre="liquid", post="liquid"),
        _action("whisk eggs", pre="liquid", post="liquid"),
    ])
    pairs = [(n, c) for n, c, _ in gold_to_pairs(load_gold(tmp_path, "r1", 1), _recipe())]
    graph = build_k1_graph([(pairs, "r1")], tmp_path / "g")
    req = [e for e in graph.edges if e.edge_type == "REQUIRES"]
    assert [e.properties["rule_id"] for e in req] == ["crack_before_mix"]


# ── Pipeline output with several actions per step ─────────────────────────────

def _gen_file(gen_dir: Path, step_n: int, sub: int, phrase: str) -> None:
    gen_dir.mkdir(parents=True, exist_ok=True)
    node = {
        "recipe_id": "r1", "step_number": step_n, "sub_step": sub, "node_type": "Process",
        "action_phrase": phrase,
        "pre_conditions": [{"entity_id": "egg", "physics_state": "raw", "k2_label": "liquid"}],
        "post_conditions": [{"entity_id": "egg", "physics_state": "beaten", "k2_label": "liquid"}],
        "tools": ["bowl"], "source_span": "Crack the eggs", "confidence": 0.9,
    }
    (gen_dir / f"{artifact_stem('r1', step_n, sub)}.gen.json").write_text(json.dumps(node))


def test_artifact_stem_keeps_old_name_for_first_action():
    assert artifact_stem("r1", 3) == "r1_step03"
    assert artifact_stem("r1", 3, 2) == "r1_step03.2"


def test_auto_step_reads_every_action(tmp_path):
    gen = tmp_path / "run" / "L2" / "gen"
    _gen_file(gen, 1, 1, "crack eggs into bowl")
    _gen_file(gen, 1, 2, "whisk eggs")
    auto = auto_step(tmp_path / "run", "r1", 1)
    assert auto["status"] == "kept"
    assert auto["expected"]["action_phrase"] == "crack eggs into bowl"
    assert [x["action_phrase"] for x in auto["sub_steps"]] == ["crack eggs into bowl", "whisk eggs"]


def test_eval_reports_split_agreement(tmp_path):
    run_dir, gold_dir, recipes_dir = tmp_path / "run", tmp_path / "gold", tmp_path / "recipes"
    (recipes_dir / "r1").mkdir(parents=True)
    (recipes_dir / "r1" / "canonical.json").write_text(_recipe().model_dump_json())
    gen = run_dir / "L2" / "gen"
    _gen_file(gen, 1, 1, "crack eggs into bowl")
    _gen_file(gen, 1, 2, "whisk eggs")
    _gen_file(gen, 2, 1, "melt butter and cook eggs")
    _review(gold_dir, 1, "crack and whisk eggs")
    save_split(gold_dir, recipe_id="r1", step_n=1, seconds_spent=6,
               sub_steps=[_action("crack eggs into bowl"), _action("whisk eggs")])
    _review(gold_dir, 2, "melt butter and cook eggs")
    save_split(gold_dir, recipe_id="r1", step_n=2, seconds_spent=4,
               sub_steps=[_action("melt butter"), _action("cook eggs")])

    sp = correction_metrics("run1", run_dir, recipes_dir, gold_dir)["splitting"]
    assert sp["steps_split_by_reviewer"] == 2
    assert sp["steps_split_by_pipeline"] == 1
    assert sp["actions_reviewer"] == 4 and sp["actions_pipeline"] == 3
    assert sp["action_count_agrees_pct"] == 50.0
    assert sp["split_minutes"] == round(10 / 60, 1)
    assert "Splitting into atomic steps" in render_section(
        correction_metrics("run1", run_dir, recipes_dir, gold_dir)
    )


def test_generator_writes_one_file_per_action_and_reads_cache(tmp_path, monkeypatch):
    from k1_pipeline.extract import generator

    def fake_call(models, response_model, messages, max_tokens):
        assert response_model is ExtractedStep
        node = lambda phrase: ExtractedNode(  # noqa: E731
            node_type="Process", action_phrase=phrase,
            pre_conditions=[{"entity_id": "egg", "physics_state": "raw", "k2_label": "liquid"}],
            post_conditions=[{"entity_id": "egg", "physics_state": "whisked", "k2_label": "liquid"}],
            source_span="whisk them", confidence=0.9,
        )
        return ExtractedStep(nodes=[node("crack eggs into bowl"), node("whisk eggs")])

    monkeypatch.setattr(generator, "call_with_fallback", fake_call)
    nodes = generator.extract_step(_recipe(), 1, tmp_path)
    assert [(n.sub_step, n.action_phrase) for n in nodes] == [(1, "crack eggs into bowl"), (2, "whisk eggs")]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["r1_step01.2.gen.json", "r1_step01.gen.json"]

    monkeypatch.setattr(generator, "call_with_fallback", lambda *a, **k: pytest.fail("cache not used"))
    assert [n.action_phrase for n in generator.extract_step(_recipe(), 1, tmp_path)] == [
        "crack eggs into bowl", "whisk eggs"]

    generator.clear_step(tmp_path, "r1", 1)
    assert list(tmp_path.iterdir()) == []


def test_atomic_rule_is_in_the_prompt():
    from k1_pipeline.extract.generator import _SYSTEM_PROMPT
    assert "ATOMIC STEPS" in _SYSTEM_PROMPT


def test_critic_revises_the_whole_step(tmp_path, monkeypatch):
    from k1_pipeline.critic import critic
    from k1_pipeline.extract import generator
    from k1_pipeline.models import CriticOutput, CriticVerdict

    def node(step_n, sub, phrase):
        return ExtractedNode(
            recipe_id="r1", step_number=step_n, sub_step=sub, node_type="Process",
            action_phrase=phrase,
            pre_conditions=[{"entity_id": "egg", "physics_state": "raw", "k2_label": "liquid"}],
            post_conditions=[{"entity_id": "egg", "physics_state": "whisked", "k2_label": "liquid"}],
            source_span="Crack the eggs", confidence=0.9,
        )

    first = [node(1, 1, "crack eggs"), node(1, 2, "whisk eggs badly"), node(2, 1, "melt butter")]
    revised = [node(1, 1, "crack eggs into bowl"), node(1, 2, "whisk eggs")]
    seen = []

    def fake_verify(recipe, sn, n, artifact_dir, revision_hint=None, suffix="critic"):
        seen.append((suffix, sn, n.sub_step, n.action_phrase))
        bad = n.action_phrase == "whisk eggs badly"
        return CriticOutput(
            verdict=CriticVerdict.revise if bad else CriticVerdict.accept,
            grounding_quote="Crack the eggs", issues=["vague"] if bad else [],
            revision_instructions="name the action" if bad else None,
        )

    hints = []
    monkeypatch.setattr(critic, "verify_node", fake_verify)
    monkeypatch.setattr(generator, "clear_step", lambda *a: None)
    monkeypatch.setattr(
        generator, "extract_step",
        lambda recipe, sn, d, revision_hint=None: hints.append(revision_hint) or revised,
    )
    results = critic.verify_recipe(_recipe(), first, tmp_path)

    assert [n.action_phrase for n, _ in results] == ["crack eggs into bowl", "whisk eggs", "melt butter"]
    assert "action 2 (whisk eggs badly): name the action" in hints[0]
    assert [s for s in seen if s[0] == "critic.r2"] == [
        ("critic.r2", 1, 1, "crack eggs into bowl"), ("critic.r2", 1, 2, "whisk eggs")]
