"""
Regression tests for provenance list alignment in dag_builder.py.

A K1Node merged from N observations must have all five provenance lists
of exactly the same length (== N), and mean_confidence must equal mean(confidences).
"""
from __future__ import annotations

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
from k1_pipeline.fuse.dag_builder import build_k1_graph


def _same_node(recipe_id: str, step_number: int, confidence: float) -> ExtractedNode:
    """Returns an ExtractedNode that will fingerprint to the same K1Node ID regardless of recipe."""
    return ExtractedNode(
        recipe_id=recipe_id,
        step_number=step_number,
        node_type=NodeType.Process,
        action_phrase="heat eggs gently",
        pre_conditions=[StateCondition(entity_id="egg", physics_state="raw", k2_label=K2Label.liquid)],
        post_conditions=[StateCondition(entity_id="egg", physics_state="soft_curd", k2_label=K2Label.coagulating)],
        source_span=f"heat eggs gently (step {step_number})",
        confidence=confidence,
        extractor_model=f"model_{recipe_id}",
    )


def _accept(node: ExtractedNode) -> CriticOutput:
    return CriticOutput(
        node_id=node.node_id,
        verdict=CriticVerdict.accept,
        grounding_quote=node.source_span,
        critic_model="test",
    )


def test_three_observations_provenance_length():
    """Three identical-fingerprint observations must yield lists of length 3."""
    node_r1 = _same_node("r1", 1, 0.8)
    node_r2 = _same_node("r2", 2, 0.9)
    node_r3 = _same_node("r3", 3, 0.7)

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        graph = build_k1_graph([
            ([(node_r1, _accept(node_r1))], "r1"),
            ([(node_r2, _accept(node_r2))], "r2"),
            ([(node_r3, _accept(node_r3))], "r3"),
        ], run_dir)

    # Find the merged node (there should be exactly one due to same fingerprint)
    process_nodes = [n for n in graph.nodes if n.node_type == NodeType.Process]
    assert len(process_nodes) == 1, "Same-fingerprint nodes must merge"
    n = process_nodes[0]

    N = 3
    assert len(n.source_recipe_ids) == N
    assert len(n.source_step_indices) == N
    assert len(n.source_spans) == N
    assert len(n.extractor_models) == N
    assert len(n.critic_verdicts) == N
    assert len(n.confidences) == N


def test_mean_confidence_is_correct():
    """mean_confidence must equal mean(confidences), not some other formula."""
    confidences = [0.8, 0.9, 0.7]
    nodes = [_same_node(f"r{i+1}", i+1, c) for i, c in enumerate(confidences)]

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        graph = build_k1_graph([
            ([(n, _accept(n))], f"r{i+1}") for i, n in enumerate(nodes)
        ], run_dir)

    process_nodes = [n for n in graph.nodes if n.node_type == NodeType.Process]
    assert len(process_nodes) == 1
    n = process_nodes[0]

    expected_mean = sum(confidences) / len(confidences)
    assert abs(n.mean_confidence - expected_mean) < 1e-9
    assert n.confidences == confidences
