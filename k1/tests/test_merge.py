"""
Tests for merge-pair labelling (merge.py). Candidates are checked against
data/k1/graph.unmerged.json; storage and conflicts use a temporary gold folder.
No LLM calls.
"""

import json

import pytest

from k1_pipeline.merge import (
    block_key,
    candidate_pairs,
    conflicts,
    delete_label,
    is_current,
    load_labels,
    merge_groups,
    oriented_label,
    pair_id,
    save_label,
)
from k1_pipeline.models import K1Graph
from k1_pipeline.query import UNMERGED_GRAPH


@pytest.fixture(scope="module")
def graph() -> K1Graph:
    return K1Graph.model_validate_json(UNMERGED_GRAPH.read_text())


def test_candidates_share_type_and_transition(graph):
    nodes = {n.node_id: n for n in graph.nodes}
    pairs = candidate_pairs(graph)
    assert pairs
    for block, a, b in pairs:
        assert a < b
        assert block_key(nodes[a]) == block_key(nodes[b]) == block
    assert len({pair_id(a, b) for _, a, b in pairs}) == len(pairs)


def test_pair_id_is_order_free():
    assert pair_id("x", "y") == pair_id("y", "x")
    with pytest.raises(ValueError):
        pair_id("x", "x")


def test_save_load_and_orientation(tmp_path, graph):
    _, a, b = candidate_pairs(graph)[0]
    save_label(tmp_path, graph, node_a=b, node_b=a, label="a_contains_b",
               seconds_spent=10, annotator="t")
    entry = load_labels(tmp_path)[pair_id(a, b)]
    assert entry["a"]["node_id"] == b
    assert oriented_label(entry, b) == "a_contains_b"
    assert oriented_label(entry, a) == "b_contains_a"
    assert is_current(entry, graph)

    # Time adds up across saves of the same pair.
    save_label(tmp_path, graph, node_a=a, node_b=b, label="same", seconds_spent=5, annotator="t")
    assert load_labels(tmp_path)[pair_id(a, b)]["seconds_spent"] == 15

    delete_label(tmp_path, pair_id(a, b))
    assert load_labels(tmp_path) == {}


def test_rejects_unknown_label_and_node(tmp_path, graph):
    _, a, b = candidate_pairs(graph)[0]
    with pytest.raises(ValueError):
        save_label(tmp_path, graph, node_a=a, node_b=b, label="maybe", seconds_spent=0, annotator="t")
    with pytest.raises(KeyError):
        save_label(tmp_path, graph, node_a=a, node_b="gone", label="same", seconds_spent=0, annotator="t")


def test_label_on_missing_node_is_not_current(tmp_path, graph):
    _, a, b = candidate_pairs(graph)[0]
    save_label(tmp_path, graph, node_a=a, node_b=b, label="same", seconds_spent=0, annotator="t")
    path = tmp_path / "merge_labels.json"
    body = json.loads(path.read_text())
    body["labels"][0]["b"]["node_id"] = "edited-since"
    path.write_text(json.dumps(body))
    entry = next(iter(load_labels(tmp_path).values()))
    assert not is_current(entry, graph)
    assert merge_groups(load_labels(tmp_path), graph) == []


def test_groups_and_not_transitive(tmp_path, graph):
    # Three nodes from the largest group: A=B and B=C but A!=C cannot all hold.
    block, _, _ = candidate_pairs(graph)[0]
    ids = sorted(n.node_id for n in graph.nodes if block_key(n) == block)[:3]
    a, b, c = ids
    for x, y, lab in ((a, b, "same"), (b, c, "same"), (a, c, "different")):
        save_label(tmp_path, graph, node_a=x, node_b=y, label=lab, seconds_spent=0, annotator="t")
    labels = load_labels(tmp_path)
    assert merge_groups(labels, graph) == [sorted([a, b, c])]
    kinds = [x["kind"] for x in conflicts(labels, graph)]
    assert "not_transitive" in kinds


def _small_graph(tmp_path, recipes):
    from k1_pipeline.fuse.dag_builder import build_k1_graph
    from k1_pipeline.models import CriticOutput, CriticVerdict, ExtractedNode

    def node(recipe, step, phrase, entity, pre="solid", post="liquid"):
        n = ExtractedNode(
            recipe_id=recipe, step_number=step, node_type="Process", action_phrase=phrase,
            pre_conditions=[{"entity_id": entity, "physics_state": "x", "k2_label": pre}],
            post_conditions=[{"entity_id": entity, "physics_state": "x", "k2_label": post}],
            source_span="x", confidence=0.9,
        )
        return n, CriticOutput(verdict=CriticVerdict.accept, grounding_quote="x")

    return build_k1_graph(
        [([node(r, i + 1, *spec) for i, spec in enumerate(steps)], r) for r, steps in recipes.items()],
        tmp_path / "g",
    )


def test_flexible_order_differences_still_merge(tmp_path):
    # Recipe a whisks then melts butter; recipe b melts butter then whisks. No rule
    # orders the two, so the merges apply and each recipe keeps its own order.
    from k1_pipeline.merge import apply_merges

    graph = _small_graph(tmp_path, {
        "a": [("whisk eggs", "egg"), ("melt butter", "butter")],
        "b": [("heat pan, melt butter", "butter"), ("beat eggs", "egg")],
    })
    ids = {n.action_phrase: n.node_id for n in graph.nodes}
    for x, y in (("whisk eggs", "beat eggs"), ("melt butter", "heat pan, melt butter")):
        save_label(tmp_path, graph, node_a=ids[x], node_b=ids[y], label="same",
                   seconds_spent=0, annotator="t")
    labels = load_labels(tmp_path)
    assert conflicts(labels, graph) == []
    merged, report = apply_merges(graph, labels)
    assert len(merged.nodes) == 2 and not report["skipped"]
    by_phrase = {n.action_phrase: n for n in merged.nodes}
    assert by_phrase["melt butter"].variant_phrases == ["heat pan, melt butter"]
    assert sorted(by_phrase["melt butter"].source_recipe_ids) == ["a", "b"]


def test_merge_that_loops_one_recipe_is_skipped(tmp_path):
    # In one recipe, X ... Y ... Z with X and Z labelled the same: merging them
    # would send the recipe back to an earlier step.
    from k1_pipeline.merge import apply_merges

    graph = _small_graph(tmp_path, {
        "a": [("stir eggs", "egg", "liquid", "coagulating"),
              ("add butter", "butter"),
              ("keep stirring", "egg", "liquid", "coagulating")],
    })
    ids = {n.action_phrase: n.node_id for n in graph.nodes}
    save_label(tmp_path, graph, node_a=ids["stir eggs"], node_b=ids["keep stirring"],
               label="same", seconds_spent=0, annotator="t")
    labels = load_labels(tmp_path)
    assert [c["kind"] for c in conflicts(labels, graph)] == ["order_cycle"]
    merged, report = apply_merges(graph, labels)
    assert len(merged.nodes) == 3 and report["skipped"]


def test_merging_two_consecutive_actions_makes_one_step(tmp_path):
    from k1_pipeline.merge import apply_merges

    graph = _small_graph(tmp_path, {
        "a": [("stir eggs", "egg", "liquid", "coagulating"),
              ("keep stirring", "egg", "liquid", "coagulating"),
              ("add butter", "butter")],
    })
    ids = {n.action_phrase: n.node_id for n in graph.nodes}
    save_label(tmp_path, graph, node_a=ids["stir eggs"], node_b=ids["keep stirring"],
               label="same", seconds_spent=0, annotator="t")
    merged, report = apply_merges(graph, load_labels(tmp_path))
    nxt = [e for e in merged.edges if e.edge_type == "NEXT"]
    assert len(merged.nodes) == 2 and len(nxt) == 1 and not report["skipped"]


def test_no_labels_no_conflicts(tmp_path, graph):
    assert conflicts(load_labels(tmp_path), graph) == []
