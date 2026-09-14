"""
Regression tests for Gate 4 (thermal Process must have safety bounds).

Key: Gate 4 must derive thermality from the action_phrase keyword check,
NOT from the presence of safety_bounds. A thermal Process without bounds fails.
"""
from __future__ import annotations

from k1_pipeline.models import (
    K1Edge,
    K1Graph,
    K1Node,
    K2Label,
    NodeType,
    SafetyBound,
    StateCondition,
)
from k1_pipeline.validate.gates import validate


def _make_process_node(action_phrase: str, has_bounds: bool = False) -> K1Node:
    bounds = []
    if has_bounds:
        bounds = [SafetyBound(
            bound_id="egg_coag",
            label="Egg coagulation onset",
            temperature_c=62.0,
            description="Egg whites begin to coagulate",
            k2_transition="liquid->coagulating",
            severity="alert",
        )]
    return K1Node(
        node_id="n1",
        node_type=NodeType.Process,
        action_phrase=action_phrase,
        canonical_action=action_phrase.lower().replace(" ", "_"),
        pre_conditions=[StateCondition(entity_id="egg", physics_state="raw", k2_label=K2Label.liquid)],
        post_conditions=[StateCondition(entity_id="egg", physics_state="soft_curd", k2_label=K2Label.coagulating)],
        ingredients=[],
        tools=[],
        safety_bounds=bounds,
        source_recipe_ids=["r1"],
        source_step_indices=[1],
        source_spans=["heat eggs gently"],
        extractor_models=["test"],
        critic_verdicts=["accept"],
        confidences=[0.9],
        mean_confidence=0.9,
    )


def _graph_with_node(node: K1Node, with_safety_edge: bool = False) -> K1Graph:
    edges = []
    if with_safety_edge and node.safety_bounds:
        edges.append(K1Edge(
            from_node_id=node.node_id,
            to_node_id=f"bound_{node.safety_bounds[0].bound_id}",
            edge_type="HAS_SAFETY_BOUND",
        ))
    return K1Graph(nodes=[node], edges=edges)


def test_thermal_without_bounds_fails_gate4():
    """A thermal action phrase with no safety_bounds MUST fail Gate 4."""
    node = _make_process_node("heat eggs gently", has_bounds=False)
    graph = _graph_with_node(node)
    errors = validate(graph, {})
    gate4_errors = [e for e in errors if "Gate 4" in e]
    assert gate4_errors, "Gate 4 should fail for thermal Process with no safety_bounds"


def test_thermal_with_bounds_and_edge_passes_gate4():
    """Thermal Process with bounds AND edge should pass Gate 4."""
    node = _make_process_node("heat eggs gently", has_bounds=True)
    graph = _graph_with_node(node, with_safety_edge=True)
    errors = validate(graph, {})
    gate4_errors = [e for e in errors if "Gate 4" in e]
    assert not gate4_errors, f"Gate 4 should pass: {gate4_errors}"


def test_thermal_with_bounds_but_no_edge_fails():
    """Thermal Process with bounds but missing the edge should fail Gate 4."""
    node = _make_process_node("cook eggs", has_bounds=True)
    graph = _graph_with_node(node, with_safety_edge=False)
    errors = validate(graph, {})
    gate4_errors = [e for e in errors if "Gate 4" in e]
    assert gate4_errors, "Gate 4 should fail when edge is missing"


def test_non_thermal_without_bounds_passes_gate4():
    """A non-thermal action phrase with no bounds should NOT fail Gate 4."""
    node = _make_process_node("whisk eggs vigorously", has_bounds=False)
    graph = _graph_with_node(node)
    errors = validate(graph, {})
    gate4_errors = [e for e in errors if "Gate 4" in e]
    assert not gate4_errors, f"Gate 4 should pass for non-thermal: {gate4_errors}"
