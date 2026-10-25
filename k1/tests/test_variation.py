"""
Tests for the order rules and preference points (config/variation_points.yaml,
variation.py) and the REQUIRES edges built from them. No LLM calls.
"""

import json
from pathlib import Path

import networkx as nx

from k1_pipeline.fuse.dag_builder import build_k1_graph
from k1_pipeline.gold import load_queue
from k1_pipeline.models import CriticOutput, CriticVerdict, ExtractedNode, K1Edge, K1Graph
from k1_pipeline.query import UNMERGED_GRAPH
from k1_pipeline.validate.gates import validate
from k1_pipeline.variation import (
    action_class,
    check_config,
    order_rules,
    preference_points,
    required_pairs,
)

DATA = Path(__file__).parent.parent / "data"


def _node(recipe, step, phrase):
    n = ExtractedNode(
        recipe_id=recipe, step_number=step, node_type="Process", action_phrase=phrase,
        pre_conditions=[{"entity_id": "egg", "physics_state": "x", "k2_label": "liquid"}],
        post_conditions=[{"entity_id": "egg", "physics_state": "x", "k2_label": "coagulating"}],
        source_span="x", confidence=0.9,
    )
    return n, CriticOutput(verdict=CriticVerdict.accept, grounding_quote="x")


def test_config_is_grounded_and_acyclic():
    recipes = {r.recipe_id: r for r in load_queue(DATA / "recipes")}
    assert check_config(recipes) == []


def test_every_reviewed_action_has_a_class():
    graph = K1Graph.model_validate_json(UNMERGED_GRAPH.read_text())
    assert [n.action_phrase for n in graph.nodes if action_class(n.action_phrase) is None] == []


def test_class_match_ignores_case_and_spacing():
    assert action_class("  Whisk   EGGS ") == "mix_eggs"
    assert action_class("juggle eggs") is None


def test_every_rule_and_preference_has_a_reason_kind():
    for rule in order_rules():
        assert rule["reason"] and rule["source"] is not None
    for point in preference_points():
        assert point["kind"] in ("structural", "parametric")
        assert len(point["alternatives"]) >= 2


def test_required_pairs_and_violations():
    pairs, violations = required_pairs(["crack", "mix_eggs", "season"])
    assert [(i, j, r["id"]) for i, j, r in pairs] == [(0, 1, "crack_before_mix")]
    assert violations == []
    _, violations = required_pairs(["mix_eggs", "crack"])
    assert [v["rule_id"] for v in violations] == ["crack_before_mix"]


def test_requires_edges_come_from_rules_with_reasons(tmp_path):
    graph = build_k1_graph([([
        _node("r", 1, "crack the eggs into a bowl"),
        _node("r", 2, "add salt"),
        _node("r", 3, "whisk eggs"),
    ], "r")], tmp_path)
    req = [e for e in graph.edges if e.edge_type == "REQUIRES"]
    # Salt has no physical order with either step: only crack -> whisk is required.
    assert len(req) == 1 and req[0].properties["rule_id"] == "crack_before_mix"
    assert req[0].properties["reason"]
    report = json.loads((tmp_path / "L3" / "order_report.json").read_text())
    assert report["unclassified"] == [] and report["violations"] == []


def test_unclassified_and_violating_actions_are_reported(tmp_path):
    build_k1_graph([([
        _node("r", 1, "whisk eggs"),
        _node("r", 2, "crack the eggs into a bowl"),
        _node("r", 3, "juggle eggs"),
    ], "r")], tmp_path)
    report = json.loads((tmp_path / "L3" / "order_report.json").read_text())
    assert [u["action_phrase"] for u in report["unclassified"]] == ["juggle eggs"]
    assert [v["rule_id"] for v in report["violations"]] == ["crack_before_mix"]


def test_gate_2_fails_on_a_physical_order_cycle():
    graph = K1Graph(nodes=[], edges=[
        K1Edge(from_node_id="x", to_node_id="y", edge_type="REQUIRES", source_recipe_id="r"),
        K1Edge(from_node_id="y", to_node_id="x", edge_type="REQUIRES", source_recipe_id="s"),
    ])
    assert any("physical order" in e for e in validate(graph, {}))


def test_reviewed_graph_physical_order_is_acyclic():
    graph = K1Graph.model_validate_json(UNMERGED_GRAPH.read_text())
    req = nx.DiGraph([(e.from_node_id, e.to_node_id) for e in graph.edges if e.edge_type == "REQUIRES"])
    assert nx.is_directed_acyclic_graph(req)
    assert all(e.properties.get("rule_id") for e in graph.edges if e.edge_type == "REQUIRES")
