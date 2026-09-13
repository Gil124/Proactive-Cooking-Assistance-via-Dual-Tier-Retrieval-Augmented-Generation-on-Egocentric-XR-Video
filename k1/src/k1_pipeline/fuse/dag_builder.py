"""
L3 Fuse -- Multi-path DAG builder
Merges ExtractedNode objects from multiple recipes into a fused K1Graph.

Strategy:
  - Fingerprint = sha256(node_type + canonical_action + k2_pre + k2_post)
  - Nodes with identical fingerprints are merged (provenance lists merged).
  - Parallel branches (butter vs oil; low-heat vs high-heat) preserved as separate nodes
    sharing compatible pre/post states.
  - HAS_SAFETY_BOUND edges are attached from physics_bounds.yaml (not from extraction).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from k1_pipeline.config_loader import get_canonical_entity_map, load_physics_bounds
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

_PHYSICS_BOUNDS = load_physics_bounds()

# Thermal action keywords -- any Process with these words gets safety bounds
_THERMAL_KEYWORDS = re.compile(
    r"\b(heat|cook|warm|melt|fry|saut|simmer|boil|scorch|burn|flame)\b",
    re.IGNORECASE,
)


def _is_thermal(node: ExtractedNode) -> bool:
    if node.node_type != NodeType.Process:
        return False
    return bool(_THERMAL_KEYWORDS.search(node.action_phrase))


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
    if not _is_thermal(node):
        return []
    # Attach egg-related and fat-related bounds where relevant
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

    # Phase 1: collect all nodes with resolved entities
    all_nodes: list[tuple[ExtractedNode, CriticOutput, str]] = []  # (node, critic, recipe_id)
    for pairs, recipe_id in verified_nodes:
        for node, critic in pairs:
            # Resolve entities
            node.pre_conditions = resolve_entities_in_conditions(node.pre_conditions)
            node.post_conditions = resolve_entities_in_conditions(node.post_conditions)
            node.ingredients = [resolve_entity(e) for e in node.ingredients]
            all_nodes.append((node, critic, recipe_id))

    # Phase 2: fingerprint-based deduplication
    fingerprint_map: dict[str, K1Node] = {}
    ordered_fingerprints: list[str] = []  # preserve recipe ordering for NEXT edges

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
                ingredients=list(dict.fromkeys(node.ingredients)),  # deduplicate
                tools=list(dict.fromkeys(node.tools)),
                safety_bounds=_safety_bounds_for_node(node),
                source_recipe_ids=[recipe_id],
                source_step_indices=[node.step_number],
                source_spans=[node.source_span],
                extractor_models=[node.extractor_model],
                critic_verdicts=[critic.verdict.value],
                mean_confidence=node.confidence,
            )
            fingerprint_map[fp] = k1_node
            ordered_fingerprints.append(fp)
        else:
            # Merge provenance
            existing = fingerprint_map[fp]
            if recipe_id not in existing.source_recipe_ids:
                existing.source_recipe_ids.append(recipe_id)
            existing.source_step_indices.append(node.step_number)
            existing.source_spans.append(node.source_span)
            existing.extractor_models.append(node.extractor_model)
            existing.critic_verdicts.append(critic.verdict.value)
            n = len(existing.source_recipe_ids)
            existing.mean_confidence = (
                existing.mean_confidence * (n - 1) + node.confidence
            ) / n
            # Merge ingredients/tools
            for ing in node.ingredients:
                if ing not in existing.ingredients:
                    existing.ingredients.append(ing)
            for tool in node.tools:
                if tool not in existing.tools:
                    existing.tools.append(tool)

    k1_nodes = list(fingerprint_map.values())

    # Phase 3: build NEXT edges (per recipe ordering)
    edges: list[K1Edge] = []
    # Rebuild per-recipe fingerprint sequences for NEXT
    recipe_sequences: dict[str, list[str]] = {}
    for node, critic, recipe_id in all_nodes:
        fp = _fingerprint(node)
        recipe_sequences.setdefault(recipe_id, []).append(fp)

    for recipe_id, seq in recipe_sequences.items():
        for i in range(len(seq) - 1):
            edges.append(K1Edge(
                from_node_id=seq[i],
                to_node_id=seq[i + 1],
                edge_type="NEXT",
                source_recipe_id=recipe_id,
                weight=1.0,
            ))

    # Phase 4: REQUIRES edges from pre_conditions
    for k1_node in k1_nodes:
        for cond in k1_node.pre_conditions:
            # Find any node whose post_conditions produce this entity+k2_label
            for other in k1_nodes:
                if other.node_id == k1_node.node_id:
                    continue
                for post in other.post_conditions:
                    if post.entity_id == cond.entity_id and post.k2_label == cond.k2_label:
                        edges.append(K1Edge(
                            from_node_id=other.node_id,
                            to_node_id=k1_node.node_id,
                            edge_type="REQUIRES",
                            weight=1.0,
                        ))
                        break

    # Phase 5: HAS_SAFETY_BOUND edges (from physics_bounds, not from extraction)
    for k1_node in k1_nodes:
        for bound in k1_node.safety_bounds:
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
            edges.append(K1Edge(
                from_node_id=f"ingredient_{ing}",
                to_node_id=k1_node.node_id,
                edge_type="INGREDIENT_OF",
            ))
        for tool in k1_node.tools:
            if tool not in seen_tool:
                tool_nodes.append({"id": f"tool_{tool}", "name": tool, "labels": ["Tool"]})
                seen_tool.add(tool)
            edges.append(K1Edge(
                from_node_id=f"tool_{tool}",
                to_node_id=k1_node.node_id,
                edge_type="USES_TOOL",
            ))

    # Collect branch labels
    branch_labels = sorted(recipe_sequences.keys())

    graph = K1Graph(
        nodes=k1_nodes,
        edges=edges,
        ingredient_nodes=ingredient_nodes,
        tool_nodes=tool_nodes,
        branch_labels=branch_labels,
    )

    # Persist L3 artifact
    (l3_dir / "fused_dag.json").write_text(graph.model_dump_json(indent=2))
    return graph
