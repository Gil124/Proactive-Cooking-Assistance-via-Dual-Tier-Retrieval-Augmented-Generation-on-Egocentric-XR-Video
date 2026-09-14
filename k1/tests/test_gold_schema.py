"""
Regression tests for the GoldNode Pydantic schema.
Verifies that the nested 'expected' structure matches ANNOTATION_PROTOCOL.md.
"""
from __future__ import annotations

import json

import pytest

from k1_pipeline.models import GoldNode, GoldExpected, GoldCondition, K2Label, NodeType


# A representative gold annotation as it would appear in a *.gold.json file
PROTOCOL_EXAMPLE = {
    "recipe_id": "serious_eats_scrambled",
    "step_number": 3,
    "expected": {
        "node_type": "Process",
        "action_phrase": "heat eggs gently",
        "pre_conditions": [
            {"entity_id": "egg", "k2_label": "liquid"}
        ],
        "post_conditions": [
            {"entity_id": "egg", "k2_label": "coagulating"}
        ],
        "has_safety_bound": True,
    },
    "annotator": "test_annotator",
    "annotation_date": "2026-09-13",
    "notes": "benchmark step",
}


def test_protocol_example_validates():
    """The protocol example must parse without errors."""
    gold = GoldNode.model_validate(PROTOCOL_EXAMPLE)
    assert gold.recipe_id == "serious_eats_scrambled"
    assert gold.step_number == 3
    assert gold.expected.node_type == NodeType.Process
    assert gold.expected.has_safety_bound is True
    assert gold.expected.pre_conditions[0].entity_id == "egg"
    assert gold.expected.pre_conditions[0].k2_label == K2Label.liquid


def test_json_round_trip():
    """GoldNode must survive a JSON round-trip."""
    gold = GoldNode.model_validate(PROTOCOL_EXAMPLE)
    reloaded = GoldNode.model_validate_json(gold.model_dump_json())
    assert reloaded == gold


def test_missing_expected_fails():
    """A gold dict without 'expected' must fail validation."""
    bad = {k: v for k, v in PROTOCOL_EXAMPLE.items() if k != "expected"}
    with pytest.raises(Exception):
        GoldNode.model_validate(bad)


def test_invalid_k2_label_fails():
    """An unknown k2_label in conditions must fail validation."""
    bad = json.loads(json.dumps(PROTOCOL_EXAMPLE))
    bad["expected"]["pre_conditions"][0]["k2_label"] = "runny"
    with pytest.raises(Exception):
        GoldNode.model_validate(bad)


def test_invalid_node_type_fails():
    """An unknown node_type must fail validation."""
    bad = json.loads(json.dumps(PROTOCOL_EXAMPLE))
    bad["expected"]["node_type"] = "Action"
    with pytest.raises(Exception):
        GoldNode.model_validate(bad)


def test_notes_optional():
    """notes field must be optional (default empty string)."""
    no_notes = {k: v for k, v in PROTOCOL_EXAMPLE.items() if k != "notes"}
    gold = GoldNode.model_validate(no_notes)
    assert gold.notes == ""
