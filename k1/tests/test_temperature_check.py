"""
Regression tests for the physics.py temperature helpers.

Key invariants:
- Bare numbers (confidence=0.95, duration_s=90) do NOT trigger invented-temp detection.
- A unit-bearing temp in step_text ("70 C") does NOT count as invented.
- A unit-bearing temp in the node ("200 C") absent from step_text AND KNOWN_TEMPS IS flagged.
"""
from __future__ import annotations

import pytest

from k1_pipeline.models import (
    ExtractedNode,
    K2Label,
    NodeType,
    StateCondition,
    TimingConstraints,
)
from k1_pipeline.physics import (
    KNOWN_TEMPS,
    extract_temperatures,
    find_invented_temperatures,
    is_thermal_action,
)


def _process_node(**kwargs) -> ExtractedNode:
    defaults = dict(
        recipe_id="r1",
        step_number=1,
        node_type=NodeType.Process,
        action_phrase="heat gently",
        pre_conditions=[StateCondition(entity_id="egg", physics_state="raw", k2_label=K2Label.liquid)],
        post_conditions=[StateCondition(entity_id="egg", physics_state="soft_curd", k2_label=K2Label.coagulating)],
        source_span="heat gently",
        confidence=0.95,
        extractor_model="test",
    )
    defaults.update(kwargs)
    return ExtractedNode(**defaults)


# ── extract_temperatures ──────────────────────────────────────────────────────

def test_bare_number_not_matched():
    """Bare integers like 90 or 95 should not be detected as temperatures."""
    assert extract_temperatures("confidence 0.95 duration 90") == set()


def test_unit_bearing_matched():
    assert extract_temperatures("cook to 70 C") == {70.0}
    assert extract_temperatures("set to 62°C") == {62.0}
    assert extract_temperatures("140 F") == {140.0}


def test_no_match_on_json_dump():
    """Sanity check: scanning a JSON dump of a node doesn't produce false positives."""
    node = _process_node()
    json_text = node.model_dump_json()
    # The JSON contains "confidence":0.95 and step_number:1 etc.
    temps = extract_temperatures(json_text)
    # Only unit-bearing values count — there are none in a typical node dump
    assert temps == set()


# ── find_invented_temperatures ────────────────────────────────────────────────

def test_no_invented_when_step_has_temp():
    """Temperature present in step text should NOT be flagged."""
    node = _process_node(
        source_span="cook at 70 C until set",
        temperature_c=70.0,
    )
    step_text = "Gently cook at 70 C until the eggs just set."
    assert find_invented_temperatures(node, step_text) == []


def test_known_temp_not_flagged():
    """A temperature from KNOWN_TEMPS should not be flagged even if absent from step text."""
    known = next(iter(KNOWN_TEMPS))  # grab any known temp
    node = _process_node(temperature_c=known)
    step_text = "Cook gently."
    assert find_invented_temperatures(node, step_text) == []


def test_invented_temp_flagged():
    """A temperature that's not in step text and not in KNOWN_TEMPS should be flagged."""
    # Pick a value unlikely to be in KNOWN_TEMPS
    invented = 999.0
    assert invented not in KNOWN_TEMPS
    node = _process_node(temperature_c=invented)
    step_text = "Cook gently."
    result = find_invented_temperatures(node, step_text)
    assert invented in result


def test_confidence_field_not_flagged():
    """confidence=0.95 must never cause an invented-temperature hit."""
    node = _process_node(confidence=0.95)
    step_text = "Whisk eggs in a bowl."
    assert find_invented_temperatures(node, step_text) == []


def test_duration_field_not_flagged():
    """duration_s=90 is a number; it should not be treated as a temperature."""
    node = _process_node(timing_constraints=TimingConstraints(duration_s=90.0))
    step_text = "Stir for a while."
    assert find_invented_temperatures(node, step_text) == []


# ── is_thermal_action ─────────────────────────────────────────────────────────

def test_thermal_keywords_detected():
    assert is_thermal_action("heat the pan over medium")
    assert is_thermal_action("melt the butter")
    assert is_thermal_action("simmer gently")
    assert is_thermal_action("fry until golden")


def test_non_thermal_not_detected():
    assert not is_thermal_action("whisk eggs together")
    assert not is_thermal_action("season with salt")
    assert not is_thermal_action("plate the dish")
