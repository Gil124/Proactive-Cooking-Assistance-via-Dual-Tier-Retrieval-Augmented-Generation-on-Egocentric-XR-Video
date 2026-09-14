"""
L4 Validate -- Deterministic gates
All six gates must pass before the graph is written to store.

Gates:
  1. Pydantic schema valid (implicit -- graph was already Pydantic-constructed)
  2. DAG is acyclic (DFS)
  3. Every Process node has >= 1 pre_condition and >= 1 post_condition
  4. Every thermal Process has >= 1 HAS_SAFETY_BOUND edge
  5. Every k2_label in {liquid, coagulating, solid, scorched}
  6. Every source_span is a substring of its recipe's step text
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from k1_pipeline.models import K1Graph, K2Label, NodeType
from k1_pipeline.physics import is_thermal_action


def validate(graph: K1Graph, canonical_recipes: dict[str, "CanonicalRecipe"]) -> list[str]:  # noqa: F821
    """
    Run all validation gates.
    Returns a list of error messages. Empty list = pass.
    """
    errors: list[str] = []

    # Gate 1: Pydantic already enforced (no-op here)

    # Gate 2: Acyclicity -- only check NEXT/REQUIRES edges (not cross-entity)
    G = nx.DiGraph()
    for node in graph.nodes:
        G.add_node(node.node_id)
    for edge in graph.edges:
        if edge.edge_type in ("NEXT", "REQUIRES"):
            G.add_edge(edge.from_node_id, edge.to_node_id)
    if not nx.is_directed_acyclic_graph(G):
        cycles = list(nx.simple_cycles(G))
        errors.append(f"Gate 2 FAIL: Graph contains cycles: {cycles[:3]}")

    # Gate 3: Process pre/post conditions
    for node in graph.nodes:
        if node.node_type == NodeType.Process:
            if not node.pre_conditions:
                errors.append(f"Gate 3 FAIL: Process node '{node.node_id}' has no pre_conditions")
            if not node.post_conditions:
                errors.append(f"Gate 3 FAIL: Process node '{node.node_id}' has no post_conditions")

    # Gate 4: Every thermal Process must have >= 1 HAS_SAFETY_BOUND edge.
    # Thermality is re-derived from action_phrase (not from the presence of safety_bounds)
    # so nodes that should have bounds but don't are caught.
    safety_from_nodes = {
        e.from_node_id for e in graph.edges if e.edge_type == "HAS_SAFETY_BOUND"
    }
    for node in graph.nodes:
        if node.node_type == NodeType.Process and is_thermal_action(node.action_phrase):
            if not node.safety_bounds:
                errors.append(
                    f"Gate 4 FAIL: Thermal Process '{node.node_id}' "
                    f"(action='{node.action_phrase}') has no safety_bounds"
                )
            elif node.node_id not in safety_from_nodes:
                errors.append(
                    f"Gate 4 FAIL: Thermal Process '{node.node_id}' has safety_bounds "
                    "but no HAS_SAFETY_BOUND edge in graph.edges"
                )

    # Gate 5: k2_label validity
    valid_labels = {lbl.value for lbl in K2Label}
    for node in graph.nodes:
        for cond in node.pre_conditions + node.post_conditions:
            if cond.k2_label.value not in valid_labels:
                errors.append(
                    f"Gate 5 FAIL: Node '{node.node_id}' has invalid k2_label '{cond.k2_label}'"
                )

    # Gate 6: source_span groundedness
    for node in graph.nodes:
        for i, (span, recipe_id, step_idx) in enumerate(
            zip(node.source_spans, node.source_recipe_ids, node.source_step_indices)
        ):
            recipe = canonical_recipes.get(recipe_id)
            if recipe is None:
                continue
            step = next((s for s in recipe.steps if s.number == step_idx), None)
            if step is None:
                continue
            if span not in step.text:
                errors.append(
                    f"Gate 6 FAIL: Node '{node.node_id}' source_span not found in "
                    f"recipe '{recipe_id}' step {step_idx}: '{span[:60]}'"
                )

    return errors


def run_validation(
    graph: K1Graph,
    canonical_recipes: dict,
    run_dir: Path,
) -> bool:
    """
    Run validation, write report, return True if all gates pass.
    """
    errors = validate(graph, canonical_recipes)
    report_path = run_dir / "L4" / "validation_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    if errors:
        report_path.write_text("\n".join(errors))
        return False
    else:
        report_path.write_text("All 6 validation gates passed.\n")
        return True
