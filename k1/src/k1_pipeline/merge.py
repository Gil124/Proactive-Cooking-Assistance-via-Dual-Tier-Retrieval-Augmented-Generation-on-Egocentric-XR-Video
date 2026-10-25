"""
merge.py -- Hand labels for which K1 nodes are the same step.

Nodes merge on an exact fingerprint (fuse/dag_builder.py), so the same step in
different wording stays as separate nodes. This module lists candidate pairs
from the reviewed graph and stores a human label for each one:

  same          -- one step; merge them
  a_contains_b  -- A is a larger step that includes B ("crack and whisk" vs "whisk")
  b_contains_a  -- the reverse
  different     -- different steps

Candidates are pairs with the same node_type and the same K2 transition
(pre and post (entity, k2_label) sets). That transition is necessary for a
merge, not sufficient: "whisk eggs" and "push spatula through eggs" are both
egg liquid -> liquid. A pair outside those groups can be added by hand.

Labels live in data/gold/merge_labels.json, keyed by the two node IDs of the
reviewed graph before merging (data/k1/graph.unmerged.json). Node IDs hash the
action phrase, so a label whose nodes are no longer in that graph is reported
as out of date, not silently reused. The labels are the merge decision for the
reviewed graph and the test set for any automatic judge.

`apply_merges` folds each group of `same` nodes into one node (`k1 finalize`),
skipping a group that would break the graph; see its docstring.

No model is called here. Used by viz/app.py and cli.py.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from itertools import combinations
from pathlib import Path

import networkx as nx

from k1_pipeline.models import K1Graph, K1Node, StateCondition

LABELS = ("same", "a_contains_b", "b_contains_a", "different")
LABEL_TEXT = {
    "same": "Same step: merge",
    "a_contains_b": "A contains B (A is a larger step)",
    "b_contains_a": "B contains A (B is a larger step)",
    "different": "Different steps",
}


def _transition_key(conditions: list[StateCondition]) -> str:
    return "|".join(sorted(f"{c.entity_id}:{c.k2_label.value}" for c in conditions))


def block_key(node: K1Node) -> str:
    """Node type and K2 transition, e.g. 'Process | egg:liquid -> egg:coagulating'."""
    return (
        f"{node.node_type.value} | {_transition_key(node.pre_conditions)}"
        f" -> {_transition_key(node.post_conditions)}"
    )


def pair_id(a: str, b: str) -> str:
    """Order-free ID for a pair of node IDs."""
    if a == b:
        raise ValueError("A node cannot be paired with itself")
    return "__".join(sorted((a, b)))


def candidate_pairs(graph: K1Graph) -> list[tuple[str, str, str]]:
    """(block, node_id_a, node_id_b) for every pair inside a block, A < B by node ID."""
    blocks: dict[str, list[str]] = defaultdict(list)
    for node in graph.nodes:
        blocks[block_key(node)].append(node.node_id)
    out = []
    for block in sorted(blocks, key=lambda k: (-len(blocks[k]), k)):
        for a, b in combinations(sorted(blocks[block]), 2):
            out.append((block, a, b))
    return out


# ── Storage ───────────────────────────────────────────────────────────────────

def labels_path(gold_dir: Path) -> Path:
    return gold_dir / "merge_labels.json"


def load_labels(gold_dir: Path) -> dict[str, dict]:
    path = labels_path(gold_dir)
    if not path.exists():
        return {}
    return {entry["pair_id"]: entry for entry in json.loads(path.read_text())["labels"]}


def save_label(
    gold_dir: Path,
    graph: K1Graph,
    *,
    node_a: str,
    node_b: str,
    label: str,
    seconds_spent: float,
    annotator: str,
    added_by_hand: bool = False,
    notes: str = "",
) -> dict:
    """
    Write one pair label. A and B are stored in the order they were shown, since
    `a_contains_b` depends on it. Time adds to an earlier save of the same pair.
    """
    if label not in LABELS:
        raise ValueError(f"Unknown label {label!r}; expected one of {LABELS}")
    nodes = {n.node_id: n for n in graph.nodes}
    for nid in (node_a, node_b):
        if nid not in nodes:
            raise KeyError(f"Node {nid} is not in graph {graph.version}")
    labels = load_labels(gold_dir)
    pid = pair_id(node_a, node_b)
    previous = labels.get(pid)
    carried = previous["seconds_spent"] if previous and is_current(previous, graph) else 0.0
    entry = {
        "pair_id": pid,
        "a": _snapshot(nodes[node_a]),
        "b": _snapshot(nodes[node_b]),
        "label": label,
        "added_by_hand": added_by_hand,
        "annotator": annotator,
        "annotation_date": str(date.today()),
        "seconds_spent": round(carried + max(seconds_spent, 0.0), 1),
        "graph_version": graph.version,
        "notes": notes.strip(),
    }
    labels[pid] = entry
    gold_dir.mkdir(parents=True, exist_ok=True)
    body = {"labels": [labels[k] for k in sorted(labels)]}
    labels_path(gold_dir).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
    return entry


def delete_label(gold_dir: Path, pid: str) -> None:
    labels = load_labels(gold_dir)
    if labels.pop(pid, None) is None:
        return
    body = {"labels": [labels[k] for k in sorted(labels)]}
    labels_path(gold_dir).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")


def _snapshot(node: K1Node) -> dict:
    # Enough to read the label without the graph, and to see what it was made against.
    return {
        "node_id": node.node_id,
        "action_phrase": node.action_phrase,
        "block": block_key(node),
        "source_recipe_ids": list(dict.fromkeys(node.source_recipe_ids)),
    }


def is_current(entry: dict, graph: K1Graph) -> bool:
    """Both nodes are still in the graph (node IDs change when a step is edited)."""
    ids = {n.node_id for n in graph.nodes}
    return entry["a"]["node_id"] in ids and entry["b"]["node_id"] in ids


def oriented_label(entry: dict, node_a: str) -> str:
    """The stored label as seen with `node_a` shown first."""
    label = entry["label"]
    if entry["a"]["node_id"] == node_a:
        return label
    return {"a_contains_b": "b_contains_a", "b_contains_a": "a_contains_b"}.get(label, label)


# ── What the labels imply ─────────────────────────────────────────────────────

def merge_groups(labels: dict[str, dict], graph: K1Graph) -> list[list[str]]:
    """Connected groups of current `same` labels, largest first. Singletons left out."""
    g = nx.Graph()
    for entry in labels.values():
        if entry["label"] == "same" and is_current(entry, graph):
            g.add_edge(entry["a"]["node_id"], entry["b"]["node_id"])
    groups = [sorted(c) for c in nx.connected_components(g)]
    return sorted(groups, key=lambda c: (-len(c), c))


def _representative(members: list[K1Node]) -> K1Node:
    """The node whose wording a merged group keeps: most recipes, then the shortest phrase."""
    return sorted(
        members,
        key=lambda n: (-len(set(n.source_recipe_ids)), len(n.action_phrase), n.node_id),
    )[0]


def _merge_group(graph: K1Graph, group: list[str]) -> K1Graph:
    """The graph with `group` folded into its representative node."""
    nodes = {n.node_id: n for n in graph.nodes}
    members = [nodes[i] for i in group]
    rep = _representative(members).model_copy(deep=True)
    for m in members:
        if m.node_id == rep.node_id:
            continue
        rep.variant_phrases.append(m.action_phrase)
        rep.source_recipe_ids += m.source_recipe_ids
        rep.source_step_indices += m.source_step_indices
        rep.source_spans += m.source_spans
        rep.extractor_models += m.extractor_models
        rep.critic_verdicts += m.critic_verdicts
        rep.confidences += m.confidences
        for x in m.ingredients:
            if x not in rep.ingredients:
                rep.ingredients.append(x)
        for x in m.tools:
            if x not in rep.tools:
                rep.tools.append(x)
        have = {b.bound_id for b in rep.safety_bounds}
        rep.safety_bounds += [b for b in m.safety_bounds if b.bound_id not in have]
        if rep.timing_constraints is None:
            rep.timing_constraints = m.timing_constraints
    rep.mean_confidence = sum(rep.confidences) / len(rep.confidences)

    to_rep = {i: rep.node_id for i in group}
    edges, seen = [], set()
    for e in graph.edges:
        u, v = to_rep.get(e.from_node_id, e.from_node_id), to_rep.get(e.to_node_id, e.to_node_id)
        if u == v:
            continue  # two merged actions in a row become one step
        key = (u, v, e.edge_type, e.source_recipe_id if e.edge_type == "NEXT" else None)
        if key in seen:
            continue
        seen.add(key)
        edges.append(e.model_copy(update={"from_node_id": u, "to_node_id": v}))
    return graph.model_copy(update={
        "nodes": [rep if n.node_id == rep.node_id else n for n in graph.nodes
                  if n.node_id not in to_rep or n.node_id == rep.node_id],
        "edges": edges,
    })


def _order_cycles(graph: K1Graph) -> list[str]:
    from k1_pipeline.fuse.dag_builder import order_subgraphs

    names = {n.node_id: n.action_phrase for n in graph.nodes}
    out = []
    for scope, sub in order_subgraphs(graph.edges).items():
        g = nx.DiGraph([(e.from_node_id, e.to_node_id) for e in sub])
        for cycle in nx.simple_cycles(g):
            where = "physical order" if scope == "*requires*" else scope
            out.append(f"{where}: " + " -> ".join(f"'{names.get(n, n)}'" for n in cycle + cycle[:1]))
    return out


def apply_merges(graph: K1Graph, labels: dict[str, dict]) -> tuple[K1Graph, dict]:
    """
    Fold each group of nodes joined by current `same` labels into one node.

    The merged node keeps the wording of its representative (the member used by
    most recipes, then the shortest phrase), lists the others in
    `variant_phrases`, and takes the union of provenance, tools, ingredients and
    safety bounds. Edges move to it; two merged actions in a row in one recipe
    become one step. A group is skipped, and reported, when
      - one of its pairs is labelled something other than `same` (not transitive),
      - its members differ in node type or K2 transition, or
      - merging it would put a cycle into one recipe's order or the physical order.
    Returns (merged graph, report).
    """
    current = {k: v for k, v in labels.items() if is_current(v, graph)}
    nodes = {n.node_id: n for n in graph.nodes}
    report: dict = {"merged": [], "skipped": []}
    merged = graph
    for group in merge_groups(current, graph):
        phrases = [nodes[i].action_phrase for i in group]
        inside = [
            e for e in current.values()
            if e["label"] != "same" and e["a"]["node_id"] in group and e["b"]["node_id"] in group
        ]
        if inside:
            report["skipped"].append({"group": phrases, "reason": "not transitive: " + "; ".join(
                f"'{e['a']['action_phrase']}' / '{e['b']['action_phrase']}' is {e['label']}" for e in inside
            )})
            continue
        if len({block_key(nodes[i]) for i in group}) > 1:
            report["skipped"].append({"group": phrases, "reason": "members differ in node type or K2 transition"})
            continue
        candidate = _merge_group(merged, group)
        cycles = _order_cycles(candidate)
        if cycles:
            report["skipped"].append({"group": phrases, "reason": "order cycle: " + "; ".join(cycles)})
            continue
        merged = candidate
        rep = _representative([nodes[i] for i in group])
        report["merged"].append({"kept": rep.action_phrase, "node_id": rep.node_id, "group": phrases})
    report["nodes_before"] = len(graph.nodes)
    report["nodes_after"] = len(merged.nodes)
    return merged, report


def conflicts(labels: dict[str, dict], graph: K1Graph) -> list[dict]:
    """
    What would stop the current labels from being applied (as apply_merges does):
      - not_transitive: two nodes end up in one group through `same` labels,
        but their own pair is labelled something else.
      - order_cycle: merging a group would put a cycle into one recipe's order or
        into the physical order. Recipes that order a flexible step differently
        are not a conflict (Notes/10, A.3).
    """
    current = {k: v for k, v in labels.items() if is_current(v, graph)}
    _, report = apply_merges(graph, current)
    out: list[dict] = []
    for entry in current.values():
        a, b = entry["a"]["node_id"], entry["b"]["node_id"]
        groups = merge_groups(current, graph)
        rep = {nid: tuple(g) for g in groups for nid in g}
        if entry["label"] != "same" and a in rep and rep.get(a) == rep.get(b):
            out.append({
                "kind": "not_transitive",
                "pair_id": entry["pair_id"],
                "detail": (
                    f"'{entry['a']['action_phrase']}' and '{entry['b']['action_phrase']}' "
                    f"are labelled {entry['label']} but are merged through other 'same' labels"
                ),
            })
    for s in report["skipped"]:
        if s["reason"].startswith("order cycle"):
            out.append({"kind": "order_cycle", "pair_id": None,
                        "detail": f"{' = '.join(s['group'])} — {s['reason']}"})
    return out
