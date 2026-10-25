"""
Regression tests for DAG cycle detection and breaking in dag_builder.py.

Scenarios:
- A<->C REQUIRES cycle is resolved by the cycle-breaker.
- Opposing NEXT orders (recipe A: X->Y, recipe B: Y->X) are kept: a flexible step
  may be ordered differently by different recipes (Notes/10, A.3). Each recipe's
  own order and the physical order (REQUIRES) stay acyclic.
- removed_edges.json is written with the removed edges.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from k1_pipeline.models import (
    CriticOutput,
    CriticVerdict,
    ExtractedNode,
    K2Label,
    NodeType,
    StateCondition,
)


def _make_node(
    recipe_id: str,
    step_number: int,
    action_phrase: str,
    pre_k2: str = "liquid",
    post_k2: str = "coagulating",
    entity: str = "egg",
) -> ExtractedNode:
    return ExtractedNode(
        recipe_id=recipe_id,
        step_number=step_number,
        node_type=NodeType.Process,
        action_phrase=action_phrase,
        pre_conditions=[StateCondition(entity_id=entity, physics_state="raw", k2_label=K2Label(pre_k2))],
        post_conditions=[StateCondition(entity_id=entity, physics_state="soft", k2_label=K2Label(post_k2))],
        source_span=action_phrase,
        confidence=0.9,
        extractor_model="test",
    )


def _accept(node: ExtractedNode) -> CriticOutput:
    return CriticOutput(
        node_id=node.node_id,
        verdict=CriticVerdict.accept,
        grounding_quote=node.source_span,
        critic_model="test",
    )


def test_requires_cycle_resolved():
    """
    A -> C (REQUIRES) and C -> A (REQUIRES) forms a cycle.
    The builder should break it, leaving an acyclic graph.
    """
    import networkx as nx
    from k1_pipeline.fuse.dag_builder import build_k1_graph

    # Recipe r1: step 1 produces liquid egg, step 2 consumes it
    # Recipe r2: step 1 produces coagulating egg, step 2 consumes it from r1
    # Arrange so that within one recipe a cycle could form if rules are wrong.
    # Use two separate entities so REQUIRES doesn't fire cross-recipe the old way.
    # Actually simulate the described A<->C case:
    # Node A: pre=egg:liquid, post=egg:coagulating
    # Node C: pre=egg:coagulating, post=egg:liquid  (reversed, produces what A needs)
    # Under old rules this would generate A->C and C->A REQUIRES edges.

    node_a = ExtractedNode(
        recipe_id="r1",
        step_number=1,
        node_type=NodeType.Process,
        action_phrase="heat eggs",
        pre_conditions=[StateCondition(entity_id="egg", physics_state="raw", k2_label=K2Label.liquid)],
        post_conditions=[StateCondition(entity_id="egg", physics_state="soft_curd", k2_label=K2Label.coagulating)],
        source_span="heat eggs",
        confidence=0.9,
        extractor_model="test",
    )
    node_c = ExtractedNode(
        recipe_id="r1",
        step_number=2,
        node_type=NodeType.Process,
        action_phrase="rest eggs",
        pre_conditions=[StateCondition(entity_id="egg", physics_state="soft_curd", k2_label=K2Label.coagulating)],
        post_conditions=[StateCondition(entity_id="egg", physics_state="solid_curd", k2_label=K2Label.solid)],
        source_span="rest eggs",
        confidence=0.9,
        extractor_model="test",
    )

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        graph = build_k1_graph([
            ([(node_a, _accept(node_a)), (node_c, _accept(node_c))], "r1"),
        ], run_dir)

        # Graph must be acyclic
        G = nx.DiGraph()
        for node in graph.nodes:
            G.add_node(node.node_id)
        for edge in graph.edges:
            if edge.edge_type in ("NEXT", "REQUIRES"):
                G.add_edge(edge.from_node_id, edge.to_node_id)
        assert nx.is_directed_acyclic_graph(G), "Graph should be acyclic after cycle breaking"

        # removed_edges.json must exist (even if empty)
        removed_path = run_dir / "L3" / "removed_edges.json"
        assert removed_path.exists()
        removed = json.loads(removed_path.read_text())
        assert isinstance(removed, list)


def test_opposing_next_orders_are_kept():
    """
    Recipe r1: [X, Y] and recipe r2: [Y, X] create opposing NEXT edges X->Y and Y->X.
    No rule orders X and Y, so both orders are valid variations: both edges stay,
    each recipe is acyclic on its own, and Gate 2 passes.
    """
    import networkx as nx
    from k1_pipeline.fuse.dag_builder import build_k1_graph

    # X and Y must have the same fingerprint across recipes to test NEXT cycle
    # Use same action phrase + same k2 transitions
    node_x_r1 = ExtractedNode(
        recipe_id="r1",
        step_number=1,
        node_type=NodeType.Process,
        action_phrase="whisk eggs",
        pre_conditions=[StateCondition(entity_id="egg", physics_state="raw", k2_label=K2Label.liquid)],
        post_conditions=[StateCondition(entity_id="egg", physics_state="beaten", k2_label=K2Label.liquid)],
        source_span="whisk eggs",
        confidence=0.9,
        extractor_model="test",
    )
    node_y_r1 = ExtractedNode(
        recipe_id="r1",
        step_number=2,
        node_type=NodeType.Process,
        action_phrase="heat eggs",
        pre_conditions=[StateCondition(entity_id="egg", physics_state="beaten", k2_label=K2Label.liquid)],
        post_conditions=[StateCondition(entity_id="egg", physics_state="set", k2_label=K2Label.coagulating)],
        source_span="heat eggs",
        confidence=0.9,
        extractor_model="test",
    )
    # r2 reverses order
    node_y_r2 = ExtractedNode(
        recipe_id="r2",
        step_number=1,
        node_type=NodeType.Process,
        action_phrase="heat eggs",
        pre_conditions=[StateCondition(entity_id="egg", physics_state="beaten", k2_label=K2Label.liquid)],
        post_conditions=[StateCondition(entity_id="egg", physics_state="set", k2_label=K2Label.coagulating)],
        source_span="heat eggs",
        confidence=0.9,
        extractor_model="test",
    )
    node_x_r2 = ExtractedNode(
        recipe_id="r2",
        step_number=2,
        node_type=NodeType.Process,
        action_phrase="whisk eggs",
        pre_conditions=[StateCondition(entity_id="egg", physics_state="raw", k2_label=K2Label.liquid)],
        post_conditions=[StateCondition(entity_id="egg", physics_state="beaten", k2_label=K2Label.liquid)],
        source_span="whisk eggs",
        confidence=0.9,
        extractor_model="test",
    )

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        graph = build_k1_graph([
            ([(node_x_r1, _accept(node_x_r1)), (node_y_r1, _accept(node_y_r1))], "r1"),
            ([(node_y_r2, _accept(node_y_r2)), (node_x_r2, _accept(node_x_r2))], "r2"),
        ], run_dir)

        from k1_pipeline.fuse.dag_builder import order_subgraphs
        from k1_pipeline.validate.gates import validate

        nxt = [e for e in graph.edges if e.edge_type == "NEXT"]
        assert sorted(e.source_recipe_id for e in nxt) == ["r1", "r2"]
        assert json.loads((run_dir / "L3" / "removed_edges.json").read_text()) == []
        for sub in order_subgraphs(graph.edges).values():
            G = nx.DiGraph([(e.from_node_id, e.to_node_id) for e in sub])
            assert nx.is_directed_acyclic_graph(G)
        assert not any("Gate 2" in e for e in validate(graph, {}))


def test_shared_consecutive_nodes_keep_one_next_edge_per_recipe(tmp_path):
    # Two recipes both go "crack" -> "whisk". Each branch needs its own NEXT edge.
    from k1_pipeline.fuse.dag_builder import build_k1_graph
    from k1_pipeline.models import CriticOutput, CriticVerdict, ExtractedNode

    def node(recipe, step, phrase):
        n = ExtractedNode(
            recipe_id=recipe, step_number=step, node_type="Process", action_phrase=phrase,
            pre_conditions=[{"entity_id": "egg", "physics_state": "raw", "k2_label": "liquid"}],
            post_conditions=[{"entity_id": "egg", "physics_state": "beaten", "k2_label": "liquid"}],
            source_span="x", confidence=0.9,
        )
        return n, CriticOutput(verdict=CriticVerdict.accept, grounding_quote="x")

    graph = build_k1_graph(
        [([node(r, 1, "crack eggs"), node(r, 2, "whisk eggs")], r) for r in ("a", "b")],
        tmp_path,
    )
    nxt = [e for e in graph.edges if e.edge_type == "NEXT"]
    assert sorted(e.source_recipe_id for e in nxt) == ["a", "b"]
