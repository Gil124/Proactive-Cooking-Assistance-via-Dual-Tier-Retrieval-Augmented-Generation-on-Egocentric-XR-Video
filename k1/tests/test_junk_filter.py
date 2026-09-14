"""
Tests for L1 junk filter.
No LLM calls.
"""

import pytest

from k1_pipeline.ingest.parser import _is_junk, _filter_steps
from k1_pipeline.models import RecipeStep


def test_is_junk_short_text():
    assert _is_junk("Ok") is True


def test_is_junk_other_recipes():
    assert _is_junk("Other Egg Recipes to Try: Boiled Eggs") is True


def test_is_junk_see_also():
    assert _is_junk("See also: Perfect Omelet, Fried Eggs") is True


def test_not_junk_normal_step():
    assert _is_junk("Melt butter in a non-stick pan over low heat until foaming.") is False


def test_filter_steps_removes_junk():
    steps = [
        RecipeStep(number=1, text="Crack 3 eggs into a bowl and whisk until uniform."),
        RecipeStep(number=2, text="Melt butter in a non-stick pan over low heat."),
        RecipeStep(number=3, text="Other Egg Recipes to Try: Boiled, Fried"),
    ]
    filtered, dropped = _filter_steps(steps)
    assert len(filtered) == 2
    assert dropped == 1
    assert all("Other" not in s.text for s in filtered)


def test_filter_steps_raises_if_too_few():
    steps = [
        RecipeStep(number=1, text="Ok"),
        RecipeStep(number=2, text="See also: Nothing"),
    ]
    with pytest.raises(ValueError, match="junk filtering"):
        _filter_steps(steps)
