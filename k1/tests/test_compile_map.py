"""
Tests for the K2 compile map and deterministic validators.
No LLM calls -- these must always pass without API keys.
"""

import pytest

from k1_pipeline.config_loader import get_k2_compile_map
from k1_pipeline.extract.generator import compile_k2_label
from k1_pipeline.models import K2Label


def test_compile_map_covers_all_k2_labels():
    """Every K2 label must appear at least once as a mapped value."""
    k2_map = get_k2_compile_map()
    mapped_values = set(k2_map.values())
    for label in K2Label:
        assert label.value in mapped_values, f"K2Label '{label.value}' has no entries in compile map"


def test_compile_map_no_invalid_values():
    """All values in the compile map must be valid K2Label strings."""
    valid = {lbl.value for lbl in K2Label}
    k2_map = get_k2_compile_map()
    for key, value in k2_map.items():
        assert value in valid, f"Compile map key '{key}' maps to invalid value '{value}'"


@pytest.mark.parametrize("physics_state,expected", [
    ("raw", "liquid"),
    ("HETEROGENEOUS_LIQUID", "liquid"),
    ("whisked", "liquid"),
    ("soft_curd", "coagulating"),
    ("gel", "coagulating"),
    ("thickening", "coagulating"),
    ("solid", "solid"),
    ("SOLID_CURD", "solid"),
    ("firm", "solid"),
    ("scorched", "scorched"),
    ("burnt", "scorched"),
    ("rubbery", "scorched"),
    ("syneresis_weeping", "scorched"),
])
def test_compile_k2_label(physics_state, expected):
    result = compile_k2_label(physics_state)
    assert result.value == expected, f"compile_k2_label('{physics_state}') = '{result.value}', expected '{expected}'"


def test_compile_k2_label_unknown_defaults_to_liquid():
    """Unknown physics state should default to 'liquid' (safest for eggs)."""
    result = compile_k2_label("completely_unknown_state_xyz")
    assert result == K2Label.liquid
