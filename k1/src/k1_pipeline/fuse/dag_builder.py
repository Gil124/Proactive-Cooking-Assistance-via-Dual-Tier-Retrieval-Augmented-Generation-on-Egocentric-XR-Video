"""
L3 Fuse -- Multi-path DAG builder
Merges ExtractedNode objects from multiple recipes into a fused K1Graph.

Strategy:
  - Fingerprint = sha256(node_type + canonical_action + k2_pre + k2_post)
  - Nodes with identical fingerprints are merged (provenance lists merged).
  - Parallel branches (butter vs oil; low-heat vs high-heat) preserved as separate nodes
    sharing compatible pre/post states.
  - HAS_SAFETY_BOUND edges are attached from physics_bounds.yaml (not from extraction).

REQUIRES edges are built within each recipe's step sequence (earlier producer ->
later consumer).  A cycle-breaking pass removes edges (preferring REQUIRES > NEXT,
lowest weight first) until the NEXT+REQUIRES digraph is acyclic.  Removed edges
are written to L3/removed_edges.json for inspection.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from k1_pipeline.config_loader import load_physics_bounds
from k1_pipeline.fuse.entity_resolver import resolve_entity, resolve_entities_in_conditions
from k1_pipeline.models import (
    CriticOutput,
    ExtractedNode,
    K1Edge,
    K1Graph,
    K1Node,
    NodeType,
    SafetyBound,
    StateCondition,
)
from k1_pipeline.physics import is_thermal_action

_PHYSICS_BOUNDS = load_physics_bounds()


def _canonical_action(phrase: str) -> str:
    """Normalize action phrase for fingerprinting."""
    return re.sub(r"\s+", "_", phrase.lower().strip())


def _k2_labels_key(conditions: list[StateCondition]) -> str:
    parts = sorted(f"{c.entity_id}:{c.k2_label.value}" for c in conditions)
    return "|".join(parts)


def _fingerprint(node: ExtractedNode) -> str:
    canon_action = _canonical_action(node.action_phrase)
    k2_pre = _k2_labels_key(node.pre_conditions)
    k2_post = _k2_labels_key(node.post_conditions)
    raw = f"{node.node_type.value}|{canon_action}|{k2_pre}|{k2_post}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _safety_bounds_for_node(node: ExtractedNode) -> list[SafetyBound]:
    if not is_thermal_action(node.action_phrase):
        return []
    relevant_entities = {c.entity_id for c in node.pre_conditions + node.post_conditions}
    bounds = []
    for b in _PHYSICS_BOUNDS:
        if b.get("entity") in relevant_entities or b.get("entity") == "egg":
            bounds.append(SafetyBound(
                bound_id=b["id"],
                label=b["label"],
                temperature_c=b.get("temperature_c"),
                description=b["description"],
                k2_transition=b.get("k2_transition"),
                severity=b["severity"],
            ))
    return bounds


def _break_cycles(
    node_ids: set[str],
    edges: list[K1Edge],
    l3_dir: Path,
) -> list[K1Edge]:
    """
    Remove minimum set of edges (preferring REQUIRES over NEXT, lowest weight first)
    to make the NEXT+REQUIRES subgraph acyclic.
    Writes removed edges to l3_dir/removed_edges.json.
    Returns the surviving edge list.
    """
    import networkx as nx  # type: ignore

    traversal_types = {"NEXT", "REQUIRES"}
    traversal_edges = [e for e in edges if e.edge_type in traversal_types]
    other_edges = [e for e in edges if e.edge_type not in traversal_types]

    def _build_graph(edge_list: list[K1Edge]) -> nx.DiGraph:
        g: nx.DiGraph = nx.DiGraph()
        g.add_nodes_from(node_ids)
        for e in edge_list:
            g.add_edge(e.from_node_id, e.to_node_id, edge_obj=e)
        return g

    removed: list[dict] = []
    current = list(traversal_edges)

    while True:
        g = _build_graph(current)
        try:
            cycles = list(nx.find_cycle(g, orientation="original"))
        except nx.NetworkXNoCycle:
            break

        # Sort edges in cycle by priority: prefer removing REQUIRES, then lowest weight
        cycle_edge_objs = []
        for u, v, _ in cycles:
            edge_data = g.get_edge_data(u, v)
            if edge_data and "edge_obj" in edge_data:
                cycle_edge_objs.append(edge_data["edge_obj"])

        def _removal_priority(e: K1Edge) -> tuple[int, float]:
            return (0 if e.edge_type == "REQUIRES" else 1, e.weight)

        cycle_edge_objs.sort(key=_removal_priority)
        to_remove = cycle_edge_objs[0]
        removed.append({
            "from": to_remove.from_node_id,
            "to": to_remove.to_node_id,
            "type": to_remove.edge_type,
            "weight": to_remove.weight,
        })
        current = [e for e in current if not (
            e.from_node_id == to_remove.from_node_id
            and e.to_node_id == to_remove.to_node_id
            and e.edge_type == to_remove.edge_type
        )]

    removed_path = l3_dir / "removed_edges.json"
    removed_path.write_text(json.dumps(removed, indent=2))

    return current + other_edges


def build_k1_graph(
    verified_nodes: list[tuple[list[tuple[ExtractedNode, CriticOutput]], str]],
    run_dir: Path,
) -> K1Graph:
    """
    Build the fused K1Graph from all verified (node, critic) pairs across all recipes.

    Args:
        verified_nodes: list of (recipe_pairs, recipe_id) where recipe_pairs is
                        list of (ExtractedNode, CriticOutput).
        run_dir: artifacts directory for L3 output.
    """
    l3_dir = run_dir / "L3"
    l3_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: collect all nodes with resolved entities, preserving per-recipe ordering
    all_nodes: list[tuple[ExtractedNode, CriticOutput, str]] = []  # (node, critic, recipe_id)
    for pairs, recipe_id in verified_nodes:
        for node, critic in pairs:
            node.pre_conditions = resolve_entities_in_conditions(node.pre_conditions)
            node.post_conditions = resolve_entities_in_conditions(node.post_conditions)
            node.ingredients = [resolve_entity(e) for e in node.ingredients]
            all_nodes.append((node, critic, recipe_id))

    # Phase 2: fingerprint-based deduplication with correct provenance tracking
    # Provenance lists are parallel: one entry per observation (one per recipe×step).
    fingerprint_map: dict[str, K1Node] = {}

    for node, critic, recipe_id in all_nodes:
        fp = _fingerprint(node)
        if fp not in fingerprint_map:
            k1_node = K1Node(
                node_id=fp,
                node_type=node.node_type,
                action_phrase=node.action_phrase,
                canonical_action=_canonical_action(node.action_phrase),
                pre_conditions=node.pre_conditions,
                post_conditions=node.post_conditions,
                timing_constraints=node.timing_constraints,
                ingredients=list(dict.fromkeys(node.ingredients)),
                tools=list(dict.fromkeys(node.tools)),
                safety_bounds=_safety_bounds_for_node(node),
                source_recipe_ids=[recipe_id],
                source_step_indices=[node.step_number],
                source_spans=[node.source_span],
                extractor_models=[node.extractor_model],
                critic_verdicts=[critic.verdict.value],
                confidences=[node.confidence],
                mean_confidence=node.confidence,
            )
            fingerprint_map[fp] = k1_node
        else:
            # Merge provenance: always append to ALL lists, one entry per observation
            existing = fingerprint_map[fp]
            existing.source_recipe_ids.append(recipe_id)
            existing.source_step_indices.append(node.step_number)
            existing.source_spans.append(node.source_span)
            existing.extractor_models.append(node.extractor_model)
            existing.critic_verdicts.append(critic.verdict.value)
            existing.confidences.append(node.confidence)
            existing.mean_confidence = sum(existing.confidences) / len(existing.confidences)
            # Merge ingredients/tools
            for ing in node.ingredients:
                if ing not in existing.ingredients:
                    existing.ingredients.append(ing)
            for tool in node.tools:
                if tool not in existing.tools:
                    existing.tools.append(tool)

    k1_nodes = list(fingerprint_map.values())
    node_ids = {n.node_id for n in k1_nodes}

    # Phase 3: build NEXT edges per recipe ordering
    edges: list[K1Edge] = []
    edge_set: set[tuple[str, str, str]] = set()  # (from, to, type) dedup

    recipe_sequences: dict[str, list[tuple[str, int]]] = {}
    for node, critic, recipe_id in all_nodes:
        fp = _fingerprint(node)
        recipe_sequences.setdefault(recipe_id, []).append((fp, node.step_number))

    for recipe_id, seq in recipe_sequences.items():
        for i in range(len(seq) - 1):
            key = (seq[i][0], seq[i + 1][0], "NEXT")
            if key not in edge_set:
                edge_set.add(key)
                edges.append(K1Edge(
                    from_node_id=seq[i][0],
                    to_node_id=seq[i + 1][0],
                    edge_type="NEXT",
                    source_recipe_id=recipe_id,
                    weight=1.0,
                ))

    # Phase 4: REQUIRES edges -- built within each recipe, earlier producer -> later consumer
    # For each recipe: find nodes where an earlier step's post_conditions match a later step's pre_condition
    for recipe_id, seq in recipe_sequences.items():
        for i, (fp_i, step_i) in enumerate(seq):
            k1_i = fingerprint_map[fp_i]
            # Check all later steps in this recipe
            for j, (fp_j, step_j) in enumerate(seq):
                if step_j <= step_i:
                    continue  # only later steps
                k1_j = fingerprint_map[fp_j]
                for post_cond in k1_i.post_conditions:
                    for pre_cond in k1_j.pre_conditions:
                        if post_cond.entity_id == pre_cond.entity_id and post_cond.k2_label == pre_cond.k2_label:
                            key = (fp_i, fp_j, "REQUIRES")
                            if key not in edge_set:
                                edge_set.add(key)
                                edges.append(K1Edge(
                                    from_node_id=fp_i,
                                    to_node_id=fp_j,
                                    edge_type="REQUIRES",
                                    source_recipe_id=recipe_id,
                                    weight=1.0,
                                ))
                            break  # one match sufficient per (i, j) pair

    # Phase 4b: cycle-breaking pass on NEXT+REQUIRES subgraph
    edges = _break_cycles(node_ids, edges, l3_dir)

    # Phase 5: HAS_SAFETY_BOUND edges
    for k1_node in k1_nodes:
        for bound in k1_node.safety_bounds:
            key = (k1_node.node_id, f"bound_{bound.bound_id}", "HAS_SAFETY_BOUND")
            if key not in edge_set:
                edge_set.add(key)
                edges.append(K1Edge(
                    from_node_id=k1_node.node_id,
                    to_node_id=f"bound_{bound.bound_id}",
                    edge_type="HAS_SAFETY_BOUND",
                    properties={
                        "bound_id": bound.bound_id,
                        "temperature_c": bound.temperature_c,
                        "severity": bound.severity,
                        "k2_transition": bound.k2_transition,
                    },
                ))

    # Phase 6: Ingredient + Tool nodes
    ingredient_nodes: list[dict] = []
    tool_nodes: list[dict] = []
    seen_ing: set[str] = set()
    seen_tool: set[str] = set()
    for k1_node in k1_nodes:
        for ing in k1_node.ingredients:
            if ing not in seen_ing:
                ingredient_nodes.append({"id": f"ingredient_{ing}", "name": ing, "labels": ["Ingredient"]})
                seen_ing.add(ing)
            key = (f"ingredient_{ing}", k1_node.node_id, "INGREDIENT_OF")
            if key not in edge_set:
                edge_set.add(key)
                edges.append(K1Edge(
                    from_node_id=f"ingredient_{ing}",
                    to_node_id=k1_node.node_id,
                    edge_type="INGREDIENT_OF",
                ))
        for tool in k1_node.tools:
            if tool not in seen_tool:
                tool_nodes.append({"id": f"tool_{tool}", "name": tool, "labels": ["Tool"]})
                seen_tool.add(tool)
            key = (f"tool_{tool}", k1_node.node_id, "USES_TOOL")
            if key not in edge_set:
                edge_set.add(key)
                edges.append(K1Edge(
                    from_node_id=f"tool_{tool}",
                    to_node_id=k1_node.node_id,
                    edge_type="USES_TOOL",
                ))

    branch_labels = sorted(recipe_sequences.keys())

    graph = K1Graph(
        nodes=k1_nodes,
        edges=edges,
        ingredient_nodes=ingredient_nodes,
        tool_nodes=tool_nodes,
        branch_labels=branch_labels,
    )

    (l3_dir / "fused_dag.json").write_text(graph.model_dump_json(indent=2))
    return graph
