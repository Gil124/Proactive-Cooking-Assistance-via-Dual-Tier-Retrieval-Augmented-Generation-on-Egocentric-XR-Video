"""
Tests for the dish scope rule (config/dish.yaml, Notes/10-recipe-variation.md).
No LLM calls.
"""

from k1_pipeline.config_loader import get_excluded_recipes
from k1_pipeline.models import (
    ExtractedNode,
    K1Graph,
    K1Node,
    K2Label,
    NodeType,
    StateCondition,
)
from k1_pipeline.scope import (
    INGREDIENTS,
    UTENSILS,
    action_scope_issues,
    apply_scope,
    out_of_inventory_mentions,
)
from k1_pipeline.validate.gates import validate


def _cond(entity: str, k2: K2Label = K2Label.liquid) -> StateCondition:
    return StateCondition(entity_id=entity, physics_state="test", k2_label=k2)


def _node(**overrides) -> ExtractedNode:
    defaults = dict(
        recipe_id="r1",
        step_number=1,
        node_type=NodeType.Process,
        action_phrase="whisk eggs",
        pre_conditions=[_cond("egg")],
        post_conditions=[_cond("egg")],
        ingredients=["egg"],
        tools=["bowl"],
        source_span="whisk",
        confidence=0.9,
    )
    defaults.update(overrides)
    return ExtractedNode(**defaults)


def test_inventory_matches_the_agreed_station():
    assert INGREDIENTS == {"egg", "salt", "pepper", "butter", "oil"}
    assert UTENSILS == {"pan", "bowl", "spatula", "whisk", "plate", "heat_source"}


def test_out_of_inventory_entities_are_trimmed_and_node_kept():
    node = _node(
        action_phrase="whisk eggs with salt",
        pre_conditions=[_cond("egg"), _cond("milk"), _cond("salt", K2Label.solid)],
        post_conditions=[_cond("egg"), _cond("milk")],
        ingredients=["eggs", "milk", "sea salt"],
        tools=["small bowl", "measuring cup"],
    )
    trimmed, record = apply_scope(node)
    assert trimmed is not None
    assert [c.entity_id for c in trimmed.pre_conditions] == ["egg", "salt"]
    assert [c.entity_id for c in trimmed.post_conditions] == ["egg"]
    assert trimmed.ingredients == ["egg", "salt"]
    assert trimmed.tools == ["bowl"]
    assert set(record["removed_entities"]) == {"milk", "measuring cup"}


def test_portuguese_and_interchangeable_names_resolve_into_inventory():
    node = _node(
        action_phrase="bata com um garfo",
        pre_conditions=[_cond("ovos")],
        post_conditions=[_cond("ovo")],
        ingredients=["ovos", "manteiga", "azeite", "pimenta preta"],
        tools=["garfo", "frigideira", "wooden spoon", "taça", "fogo"],
    )
    trimmed, record = apply_scope(node)
    assert trimmed is not None
    assert trimmed.ingredients == ["egg", "butter", "oil", "pepper"]
    assert trimmed.tools == ["whisk", "pan", "spatula", "bowl", "heat_source"]
    assert record["removed_entities"] == []


def test_step_marked_out_of_scope_is_dropped():
    node = _node(
        node_type=NodeType.Plate,
        action_phrase="serve with bread",
        pre_conditions=[],
        post_conditions=[],
        in_scope=False,
    )
    trimmed, record = apply_scope(node)
    assert trimmed is None
    assert record["dropped"]


def test_action_naming_out_of_inventory_item_is_dropped():
    # Entities look clean, but the action still says toast.
    node = _node(node_type=NodeType.Plate, action_phrase="Serve with lightly buttered toast")
    assert action_scope_issues(node) == ["toast"]
    trimmed, record = apply_scope(node)
    assert trimmed is None
    assert "toast" in record["reason"]


def test_action_naming_an_entity_the_node_lost_is_dropped():
    # "truffle" is not in the known list; it is caught because the node listed it.
    node = _node(action_phrase="fold truffle into eggs", ingredients=["egg", "truffle"])
    assert action_scope_issues(node) == ["truffle"]
    assert apply_scope(node)[0] is None


def test_process_with_no_inventory_state_change_is_dropped():
    node = _node(
        action_phrase="assemble the pots",
        pre_conditions=[_cond("water")],
        post_conditions=[_cond("water")],
        ingredients=[],
        tools=["pan"],
    )
    trimmed, record = apply_scope(node)
    assert trimmed is None
    assert "Process" in record["reason"]


def test_mentions_match_whole_words_only():
    assert out_of_inventory_mentions("add the cream and stir") == ["cream"]
    assert out_of_inventory_mentions("stir until creamy") == []
    assert out_of_inventory_mentions("season with salt") == []


def test_out_of_scope_process_may_have_no_conditions():
    # The Process pre/post requirement only applies to steps that stay in the graph.
    _node(pre_conditions=[], post_conditions=[], in_scope=False)


def _k1_node(**overrides) -> K1Node:
    defaults = dict(
        node_id="n1",
        node_type=NodeType.Process,
        action_phrase="whisk eggs",
        canonical_action="whisk_eggs",
        pre_conditions=[_cond("egg")],
        post_conditions=[_cond("egg")],
        ingredients=["egg"],
        tools=["bowl"],
        source_recipe_ids=["jamie_oliver"],
        source_step_indices=[1],
        source_spans=["x"],
        extractor_models=["test"],
        critic_verdicts=["accept"],
        confidences=[0.9],
        mean_confidence=0.9,
    )
    defaults.update(overrides)
    return K1Node(**defaults)


def _gate7(node: K1Node) -> list[str]:
    return [e for e in validate(K1Graph(nodes=[node], edges=[]), {}) if "Gate 7" in e]


def test_gate_7_passes_for_in_inventory_node():
    assert _gate7(_k1_node()) == []


def test_gate_7_fails_on_out_of_inventory_entity():
    assert _gate7(_k1_node(ingredients=["egg", "goat cheese"]))
    assert _gate7(_k1_node(tools=["double boiler"]))
    assert _gate7(_k1_node(post_conditions=[_cond("bread", K2Label.solid)]))


def test_gate_7_fails_on_action_naming_out_of_inventory_item():
    assert _gate7(_k1_node(action_phrase="serve on toast"))


def test_gate_7_fails_on_node_from_excluded_recipe():
    excluded = get_excluded_recipes()
    assert "epicurious_bain_marie" in excluded
    assert _gate7(_k1_node(source_recipe_ids=["epicurious_bain_marie"]))


def test_ground_span_recovers_typographic_quotes():
    from k1_pipeline.extract.generator import ground_span

    text = "Stir slowly, or a spatula if you’ve got one – keep going."
    assert ground_span("a spatula if you've got one - keep", text) == "a spatula if you’ve got one – keep"
    assert ground_span("Stir slowly", text) == "Stir slowly"
    # Not in the text at all: returned unchanged for the critic to flag.
    assert ground_span("add the milk", text) == "add the milk"


def _pair(node):
    from k1_pipeline.models import CriticOutput, CriticVerdict
    return node, CriticOutput(verdict=CriticVerdict.accept, grounding_quote="")


def test_recipe_without_plate_step_gets_one_by_rule(tmp_path):
    from k1_pipeline.scope import GOAL_ACTION, RULE_MODEL, complete_to_goal

    cook = _node(step_number=4, action_phrase="cook eggs", post_conditions=[_cond("egg", K2Label.coagulating)])
    (pairs, rid), = complete_to_goal([([_pair(_node()), _pair(cook)], "r1")], tmp_path)
    plate = pairs[-1][0]
    assert len(pairs) == 3
    assert plate.node_type == NodeType.Plate and plate.action_phrase == GOAL_ACTION
    assert plate.step_number == 5
    assert [(c.entity_id, c.k2_label) for c in plate.pre_conditions] == [("egg", K2Label.coagulating)]
    assert plate.tools == ["plate"] and plate.extractor_model == RULE_MODEL
    # The added step stays inside the inventory.
    assert apply_scope(plate)[0] is not None


def test_recipe_with_plate_step_is_left_alone(tmp_path):
    from k1_pipeline.scope import complete_to_goal

    plate = _node(node_type=NodeType.Plate, action_phrase="serve eggs",
                  post_conditions=[_cond("egg", K2Label.solid)])
    (pairs, _), = complete_to_goal([([_pair(_node()), _pair(plate)], "r1")], tmp_path)
    assert len(pairs) == 2


def test_recipe_that_never_cooks_the_eggs_is_reported_not_plated(tmp_path):
    import json
    from k1_pipeline.scope import complete_to_goal

    (pairs, _), = complete_to_goal([([_pair(_node())], "r1")], tmp_path)  # eggs still liquid
    assert len(pairs) == 1
    report = json.loads((tmp_path / "goal_completion.json").read_text())
    assert report["goal_not_reached"] == [{"recipe_id": "r1", "last_state": "liquid"}]
