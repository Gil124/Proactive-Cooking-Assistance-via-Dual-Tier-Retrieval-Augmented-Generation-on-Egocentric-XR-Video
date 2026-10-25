"""
query.py -- The read-only K1 interface that Fusion uses at runtime.

Notes/08-k1-pipeline.md ("What Fusion will query") fixes the contract.
Fusion passes the current branch and the node ID of the current expected step.
K1 returns:

- the step's post_conditions (expected K2 state once the step is done)
- the step's HAS_SAFETY_BOUND bounds
- the next node ID(s) in the DAG

`step()` returns all three in one call, so Fusion makes one K1 lookup per
cycle. The reasons behind the order are there too (Notes/10, A.3):
`required_before()` gives a step's physical prerequisites with their reasons,
and `preferences()` the alternatives a branch takes at each variation point,
with the outcome each serves. A branch is a source recipe: NEXT edges carry it as `source_recipe_id`.
Shared nodes have one outgoing NEXT edge per branch that uses them.

Reads graph.final.json (the reviewed graph, merges applied) by default. The graph is
immutable during a session, so it is loaded once and indexed in memory.
No model is called here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from k1_pipeline.models import K1Graph, K1Node, SafetyBound, StateCondition

FINAL_GRAPH = Path(__file__).parent.parent.parent / "data" / "k1" / "graph.final.json"
# The reviewed graph before merges; merge labels refer to its node IDs.
UNMERGED_GRAPH = FINAL_GRAPH.with_name("graph.unmerged.json")


@dataclass(frozen=True)
class StepContext:
    """What Fusion receives for the current expected step."""

    node: K1Node
    branch: str
    post_conditions: list[StateCondition]
    safety_bounds: list[SafetyBound]
    next_node_ids: list[str]


class K1Query:
    def __init__(self, graph: K1Graph):
        self.graph = graph
        self._nodes = {n.node_id: n for n in graph.nodes}
        # node_id -> branch -> [next node_ids]
        self._next: dict[str, dict[str, list[str]]] = {}
        self._has_incoming: dict[str, set[str]] = {}
        self._branch_nodes: dict[str, set[str]] = {}
        for e in graph.edges:
            if e.edge_type != "NEXT" or e.source_recipe_id is None:
                continue
            nxt = self._next.setdefault(e.from_node_id, {}).setdefault(e.source_recipe_id, [])
            if e.to_node_id not in nxt:
                nxt.append(e.to_node_id)
            self._has_incoming.setdefault(e.source_recipe_id, set()).add(e.to_node_id)
            members = self._branch_nodes.setdefault(e.source_recipe_id, set())
            members.update((e.from_node_id, e.to_node_id))
        self._bound_edges: dict[str, set[str]] = {}
        for e in graph.edges:
            if e.edge_type == "HAS_SAFETY_BOUND":
                self._bound_edges.setdefault(e.from_node_id, set()).add(e.to_node_id)

    @classmethod
    def from_json(cls, path: Path = FINAL_GRAPH) -> K1Query:
        return cls(K1Graph.model_validate_json(Path(path).read_text()))

    def branches(self) -> list[str]:
        return list(self.graph.branch_labels)

    def node(self, node_id: str) -> K1Node:
        try:
            return self._nodes[node_id]
        except KeyError:
            raise KeyError(f"No K1 node with id {node_id!r}") from None

    def entry_nodes(self, branch: str) -> list[K1Node]:
        """First step(s) of a branch: nodes on it with no incoming NEXT edge."""
        self._check_branch(branch)
        incoming = self._has_incoming.get(branch, set())
        return [self._nodes[i] for i in sorted(self._branch_nodes[branch] - incoming)]

    def post_conditions(self, node_id: str) -> list[StateCondition]:
        return list(self.node(node_id).post_conditions)

    def safety_bounds(self, node_id: str) -> list[SafetyBound]:
        """Bounds reached by the node's HAS_SAFETY_BOUND edges."""
        node = self.node(node_id)
        targets = self._bound_edges.get(node_id, set())
        return [b for b in node.safety_bounds if f"bound_{b.bound_id}" in targets]

    def next_node_ids(self, node_id: str, branch: str | None = None) -> list[str]:
        """Next step(s). With a branch, only that branch's edge; without, every branch's."""
        self.node(node_id)
        by_branch = self._next.get(node_id, {})
        if branch is not None:
            self._check_branch(branch)
            return list(by_branch.get(branch, []))
        out: list[str] = []
        for ids in by_branch.values():
            out.extend(i for i in ids if i not in out)
        return out

    def step(self, branch: str, node_id: str) -> StepContext:
        """The one lookup Fusion makes per cycle."""
        self._check_branch(branch)
        if node_id not in self._branch_nodes.get(branch, set()):
            raise ValueError(f"Node {node_id!r} is not on branch {branch!r}")
        return StepContext(
            node=self.node(node_id),
            branch=branch,
            post_conditions=self.post_conditions(node_id),
            safety_bounds=self.safety_bounds(node_id),
            next_node_ids=self.next_node_ids(node_id, branch),
        )

    def required_before(self, node_id: str) -> list[dict]:
        """
        Steps that must come before this one, from the physical order rules:
        [{"node_id", "action_phrase", "rule_id", "reason"}].
        """
        self.node(node_id)
        return [
            {
                "node_id": e.from_node_id,
                "action_phrase": self._nodes[e.from_node_id].action_phrase,
                "rule_id": e.properties.get("rule_id"),
                "reason": e.properties.get("reason"),
            }
            for e in self.graph.edges
            if e.edge_type == "REQUIRES" and e.to_node_id == node_id and e.from_node_id in self._nodes
        ]

    def preferences(self, branch: str) -> list[dict]:
        """
        The alternative this branch takes at each variation point it is part of:
        [{"point", "kind", "choice", "outcome", "source"}]. An `outcome` of None
        means no source states why.
        """
        self._check_branch(branch)
        out = []
        for point in self.graph.preference_points:
            for alt in point.get("alternatives", []):
                if branch in (alt.get("recipes") or []):
                    out.append({
                        "point": point["id"],
                        "kind": point["kind"],
                        "choice": alt["choice"],
                        "outcome": alt.get("outcome"),
                        "source": alt.get("source"),
                    })
        return out

    def _check_branch(self, branch: str) -> None:
        if branch not in self._branch_nodes:
            raise KeyError(f"No K1 branch {branch!r}; known: {sorted(self._branch_nodes)}")
