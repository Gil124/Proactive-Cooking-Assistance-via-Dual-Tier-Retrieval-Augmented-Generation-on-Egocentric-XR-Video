"""
Tests for L4 deterministic validation gates.
No LLM calls.
"""

from pathlib import Path
from uuid import uuid4

import pytest

from k1_pipeline.models import (
    K1Edge,
    K1Graph,
    K1Node,
    K2Label,
    NodeType,
    StateCondition,
)
from k1_pipeline.validate.gates import validate


def _make_cond(entity: str, k2: K2Label) -> StateCondition:
    return StateCondition(entity_id=entity, physics_state="test", k2_label=k2)


def _minimal_node(node_type=NodeType.Process) -> K1Node:
    nid = uuid4().hex[:8]
    return K1Node(
        node_id=nid,
        node_type=node_type,
        action_phrase="test action",
        canonical_action="test_action",
        pre_conditions=[_make_cond("egg", K2Label.liquid)],
        post_conditions=[_make_cond("egg", K2Label.coagulating)],
        ingredients=["egg"],
        tools=[],
        source_recipe_ids=["jamie_oliver"],
        source_step_indices=[1],
        source_spans=["Crack 3 eggs"],
        extractor_models=["test"],
        critic_verdicts=["accept"],
        confidences=[0.9],
        mean_confidence=0.9,
    )


def _make_recipe_stubs(node: K1Node) -> dict:
    """Fake canonical recipe dict for groundedness gate."""
    from k1_pipeline.models import CanonicalRecipe, RecipeStep
    recipe = CanonicalRecipe(
        recipe_id="jamie_oliver",
        title="Test",
        source_url="http://example.com",
        variant_label="Test",
        ingredients=["egg"],
        tools=[],
        steps=[RecipeStep(number=1, text="Crack 3 eggs into a bowl and whisk.")],
    )
    return {"jamie_oliver": recipe}


def test_gate_2_acyclic_passes():
    node_a = _minimal_node()
    node_b = _minimal_node()
    graph = K1Graph(
        nodes=[node_a, node_b],
        edges=[K1Edge(from_node_id=node_a.node_id, to_node_id=node_b.node_id, edge_type="NEXT")],
    )
    errors = validate(graph, _make_recipe_stubs(node_a))
    assert not any("Gate 2" in e for e in errors), errors


def test_gate_2_cyclic_fails():
    node_a = _minimal_node()
    node_b = _minimal_node()
    graph = K1Graph(
        nodes=[node_a, node_b],
        edges=[
            K1Edge(from_node_id=node_a.node_id, to_node_id=node_b.node_id, edge_type="NEXT"),
            K1Edge(from_node_id=node_b.node_id, to_node_id=node_a.node_id, edge_type="NEXT"),
        ],
    )
    errors = validate(graph, _make_recipe_stubs(node_a))
    assert any("Gate 2" in e for e in errors), "Should fail cycle check"


def test_gate_3_process_missing_pre():
    node = _minimal_node()
    node.pre_conditions = []
    graph = K1Graph(nodes=[node], edges=[])
    errors = validate(graph, _make_recipe_stubs(node))
    assert any("Gate 3" in e for e in errors)


def test_gate_5_valid_k2_labels():
    node = _minimal_node()
    graph = K1Graph(nodes=[node], edges=[])
    errors = validate(graph, _make_recipe_stubs(node))
    assert not any("Gate 5" in e for e in errors)


def test_gate_6_span_groundedness_pass():
    node = _minimal_node()
    node.source_spans = ["Crack 3 eggs"]  # present in fake recipe step
    graph = K1Graph(nodes=[node], edges=[])
    errors = validate(graph, _make_recipe_stubs(node))
    assert not any("Gate 6" in e for e in errors)


def test_gate_6_span_groundedness_fail():
    node = _minimal_node()
    node.source_spans = ["This text is not in the recipe step at all"]
    graph = K1Graph(nodes=[node], edges=[])
    errors = validate(graph, _make_recipe_stubs(node))
    assert any("Gate 6" in e for e in errors)
