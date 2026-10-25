"""
L3 Fuse -- Multi-path DAG builder
Merges ExtractedNode objects from multiple recipes into a fused K1Graph.

Strategy:
  - Fingerprint = sha256(node_type + canonical_action + k2_pre + k2_post)
  - Nodes with identical fingerprints are merged (provenance lists merged).
  - Parallel branches (butter vs oil; low-heat vs high-heat) preserved as separate nodes
    sharing compatible pre/post states.
  - HAS_SAFETY_BOUND edges are attached from physics_bounds.yaml (not from extraction).

NEXT edges are each recipe's own order. REQUIRES edges are the physical order:
built from the order rules in config/variation_points.yaml (variation.py), each
carrying its rule id and reason. Order that no rule fixes is a preference and is
only in NEXT. Actions without an action class get no REQUIRES edge; they and any
recipe that breaks a rule are listed in L3/order_report.json.

Acyclicity (Notes/10, A.3): REQUIRES over all recipes, and each recipe's NEXT plus
the REQUIRES among its nodes. Different recipes may order flexible steps differently,
so NEXT edges of several recipes together may form a cycle. A cycle-breaking pass
removes single edges of one recipe until that recipe is acyclic; removed edges are
written to L3/removed_edges.json for inspection.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from k1_pipeline.config_loader import load_physics_bounds
from k1_pipeline.variation import action_class, required_pairs
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


def _safety_bounds_for_node(node: ExtractedNode, thermal: bool | None = None) -> list[SafetyBound]:
    """`thermal` is a reviewer's decision; None derives it from the action wording."""
    if thermal is None:
        thermal = is_thermal_action(node.action_phrase)
    if not thermal:
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


def recipe_paths(edges: list[K1Edge]) -> dict[str, set[str]]:
    """Nodes on each recipe's path, from its NEXT edges."""
    paths: dict[str, set[str]] = {}
    for e in edges:
        if e.edge_type == "NEXT" and e.source_recipe_id:
            paths.setdefault(e.source_recipe_id, set()).update((e.from_node_id, e.to_node_id))
    return paths


def order_subgraphs(edges: list[K1Edge]) -> dict[str, list[K1Edge]]:
    """
    The edges that must be acyclic together: "*requires*" -> every REQUIRES edge;
    each recipe -> its NEXT edges plus the REQUIRES edges among its nodes.
    """
    requires = [e for e in edges if e.edge_type == "REQUIRES"]
    out: dict[str, list[K1Edge]] = {"*requires*": requires}
    loose = [e for e in edges if e.edge_type == "NEXT" and not e.source_recipe_id]
    if loose:
        # NEXT edges that name no recipe are checked as one sequence.
        out["*no recipe*"] = loose
    for recipe_id, nodes in recipe_paths(edges).items():
        out[recipe_id] = [
            e for e in edges if e.edge_type == "NEXT" and e.source_recipe_id == recipe_id
        ] + [e for e in requires if e.from_node_id in nodes and e.to_node_id in nodes]
    return out


def _break_cycles(
    node_ids: set[str],
    edges: list[K1Edge],
    l3_dir: Path,
) -> list[K1Edge]:
    """
    Remove single edges until every order subgraph (order_subgraphs) is acyclic,
    preferring a recipe's NEXT edge over a REQUIRES edge (REQUIRES is physical),
    lowest weight first. Writes removed edges to l3_dir/removed_edges.json.
    Returns the surviving edge list.
    """
    import networkx as nx  # type: ignore

    removed: list[dict] = []
    current = list(edges)

    while True:
        found = None
        for name, sub in order_subgraphs(current).items():
            g: nx.MultiDiGraph = nx.MultiDiGraph()
            g.add_nodes_from(node_ids)
            for e in sub:
                g.add_edge(e.from_node_id, e.to_node_id, edge_obj=e)
            try:
                cycle = nx.find_cycle(g, orientation="original")
            except nx.NetworkXNoCycle:
                continue
            found = [g.edges[u, v, k]["edge_obj"] for u, v, k, _ in cycle]
            break
        if found is None:
            break

        def _removal_priority(e: K1Edge) -> tuple[int, float]:
            return (0 if e.edge_type == "NEXT" else 1, e.weight)

        to_remove = sorted(found, key=_removal_priority)[0]
        removed.append({
            "from": to_remove.from_node_id,
            "to": to_remove.to_node_id,
            "type": to_remove.edge_type,
            "recipe": to_remove.source_recipe_id,
            "weight": to_remove.weight,
        })
        current = [e for e in current if e is not to_remove]

    removed_path = l3_dir / "removed_edges.json"
    removed_path.write_text(json.dumps(removed, indent=2))

    return current


def build_k1_graph(
    verified_nodes: list[tuple[list[tuple[ExtractedNode, CriticOutput]], str]],
    run_dir: Path,
    safety_overrides: dict[str, bool] | None = None,
) -> K1Graph:
    """
    Build the fused K1Graph from all verified (node, critic) pairs across all recipes.

    Args:
        verified_nodes: list of (recipe_pairs, recipe_id) where recipe_pairs is
                        list of (ExtractedNode, CriticOutput).
        run_dir: artifacts directory for L3 output.
        safety_overrides: {str(ExtractedNode.node_id): has_safety_bound} from human
                        review (`k1 finalize`), one entry per reviewed action, so
                        the sub-steps of one step can differ. Nodes not listed are
                        decided by the action wording, as in a pipeline run.
    """
    safety_overrides = safety_overrides or {}
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
        thermal = safety_overrides.get(str(node.node_id))
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
                safety_bounds=_safety_bounds_for_node(node, thermal),
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
            if not existing.safety_bounds:
                existing.safety_bounds = _safety_bounds_for_node(node, thermal)
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
    edge_set: set[tuple] = set()  # (from, to, type) dedup; NEXT also keyed by recipe

    recipe_sequences: dict[str, list[tuple[str, int]]] = {}
    for node, critic, recipe_id in all_nodes:
        fp = _fingerprint(node)
        recipe_sequences.setdefault(recipe_id, []).append((fp, node.step_number))

    for recipe_id, seq in recipe_sequences.items():
        for i in range(len(seq) - 1):
            # NEXT is a branch's order. Two recipes can share the same consecutive
            # pair of nodes; each keeps its own edge, or the second branch breaks.
            key = (seq[i][0], seq[i + 1][0], "NEXT", recipe_id)
            if key not in edge_set:
                edge_set.add(key)
                edges.append(K1Edge(
                    from_node_id=seq[i][0],
                    to_node_id=seq[i + 1][0],
                    edge_type="NEXT",
                    source_recipe_id=recipe_id,
                    weight=1.0,
                ))

    # Phase 4: REQUIRES edges -- the physical order rules (variation_points.yaml),
    # applied inside each recipe: an earlier action of a rule's `before` class
    # precedes a later action of its `after` class.
    order_report: dict = {"unclassified": [], "violations": [], "requires_edges": 0}
    observed = {}  # (recipe_id, position) -> ExtractedNode, for the report
    for node, _, recipe_id in all_nodes:
        observed.setdefault(recipe_id, []).append(node)
    for recipe_id, seq in recipe_sequences.items():
        nodes_in_order = observed[recipe_id]
        classes = [action_class(fingerprint_map[fp].action_phrase) for fp, _ in seq]
        for n, cls in zip(nodes_in_order, classes):
            if cls is None:
                order_report["unclassified"].append({
                    "recipe_id": recipe_id, "step_number": n.step_number,
                    "sub_step": n.sub_step, "action_phrase": n.action_phrase,
                })
        pairs, violations = required_pairs(classes)
        for i, j, rule in pairs:
            fp_i, fp_j = seq[i][0], seq[j][0]
            key = (fp_i, fp_j, "REQUIRES")
            if fp_i == fp_j or key in edge_set:
                continue
            edge_set.add(key)
            edges.append(K1Edge(
                from_node_id=fp_i,
                to_node_id=fp_j,
                edge_type="REQUIRES",
                source_recipe_id=recipe_id,
                weight=1.0,
                properties={"rule_id": rule["id"], "reason": rule["reason"]},
            ))
            order_report["requires_edges"] += 1
        for v in violations:
            order_report["violations"].append({
                "recipe_id": recipe_id,
                "rule_id": v["rule_id"],
                "first": fingerprint_map[seq[v["first"]][0]].action_phrase,
                "then": fingerprint_map[seq[v["then"]][0]].action_phrase,
            })
    (l3_dir / "order_report.json").write_text(
        json.dumps(order_report, indent=2, ensure_ascii=False)
    )

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
