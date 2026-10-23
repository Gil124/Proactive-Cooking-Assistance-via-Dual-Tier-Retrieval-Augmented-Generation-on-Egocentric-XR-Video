"""
Tests for the Fusion query interface (query.py) and the reviewed-graph Cypher
export. Run against data/k1/graph.final.json, the graph the assistant uses.
No LLM calls, no Neo4j.
"""

import tempfile
from pathlib import Path

import pytest

from k1_pipeline.models import K1Graph
from k1_pipeline.query import FINAL_GRAPH, K1Query
from k1_pipeline.store.writer import cypher_statements, write_cypher


@pytest.fixture(scope="module")
def q() -> K1Query:
    return K1Query.from_json(FINAL_GRAPH)


def _walk(q: K1Query, branch: str) -> list[str]:
    entries = q.entry_nodes(branch)
    assert len(entries) == 1, f"{branch} has {len(entries)} entry nodes"
    path, cur = [], entries[0].node_id
    while cur is not None:
        assert cur not in path, f"{branch} loops at {cur}"
        path.append(cur)
        nxt = q.step(branch, cur).next_node_ids
        assert len(nxt) <= 1, f"{branch} forks at {cur}"
        cur = nxt[0] if nxt else None
    return path


def test_every_branch_walks_from_entry_to_plate(q):
    assert q.branches()
    for branch in q.branches():
        path = _walk(q, branch)
        assert q.node(path[-1]).node_type.value == "Plate", branch


def test_walk_covers_every_branch_node(q):
    # No step of a branch is unreachable from its entry node.
    for branch in q.branches():
        assert set(_walk(q, branch)) == q._branch_nodes[branch], branch


def test_branch_ends_at_goal_state(q):
    # config/dish.yaml goal: egg coagulating or solid, on the plate.
    for branch in q.branches():
        last = q.step(branch, _walk(q, branch)[-1])
        egg = [c.k2_label.value for c in last.post_conditions if c.entity_id == "egg"]
        assert egg and egg[0] in {"coagulating", "solid"}, branch


def test_safety_bounds_match_edges(q):
    edges = {
        (e.from_node_id, e.to_node_id)
        for e in q.graph.edges
        if e.edge_type == "HAS_SAFETY_BOUND"
    }
    for node in q.graph.nodes:
        got = {(node.node_id, f"bound_{b.bound_id}") for b in q.safety_bounds(node.node_id)}
        assert got == {e for e in edges if e[0] == node.node_id}, node.action_phrase


def test_bounds_have_valid_severity(q):
    for node in q.graph.nodes:
        for b in q.safety_bounds(node.node_id):
            assert b.severity in {"suggestion", "alert"}, b.bound_id


def test_next_without_branch_is_union(q):
    for node in q.graph.nodes:
        union = q.next_node_ids(node.node_id)
        for branch in q.branches():
            assert set(q.next_node_ids(node.node_id, branch)) <= set(union)


def test_step_rejects_node_off_branch(q):
    a, b = q.branches()[:2]
    only_a = q._branch_nodes[a] - q._branch_nodes[b]
    with pytest.raises(ValueError):
        q.step(b, next(iter(only_a)))


def test_unknown_ids_raise(q):
    with pytest.raises(KeyError):
        q.node("nope")
    with pytest.raises(KeyError):
        q.entry_nodes("nope")


def test_final_cypher_is_written_from_final_graph(tmp_path):
    graph = K1Graph.model_validate_json(FINAL_GRAPH.read_text())
    text, path = write_cypher(graph, tmp_path, "graph.final.cypher")
    assert path.name == "graph.final.cypher"
    assert f"// Graph version: {graph.version}" in text
    for node in graph.nodes:
        assert f"node_id: '{node.node_id}'" in text
    assert text.count("MERGE (a)-[:") == len(graph.edges)


def test_cypher_statements_keep_statement_under_header():
    # Regression: the first statement sits under the file's comment header and
    # was skipped whole, losing the first node and the first schema constraint.
    graph = K1Graph.model_validate_json(FINAL_GRAPH.read_text())
    text, _ = write_cypher(graph, Path(tempfile.mkdtemp()))
    stmts = cypher_statements(text, sep=";\n")
    expected = len(graph.nodes) + len(graph.ingredient_nodes) + len(graph.tool_nodes)
    expected += len({b.bound_id for n in graph.nodes for b in n.safety_bounds})
    expected += len(graph.edges)
    assert len(stmts) == expected
    assert not any(s.lstrip().startswith("//") for s in stmts)

    schema = (Path(__file__).parent.parent / "config" / "graph_schema.cypher").read_text()
    schema_stmts = cypher_statements(schema)
    assert sum(s.startswith("CREATE CONSTRAINT") for s in schema_stmts) == 6
