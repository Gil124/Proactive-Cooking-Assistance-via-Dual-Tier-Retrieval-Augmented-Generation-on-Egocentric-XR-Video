"""Preparations collapse onto a base entity. Unknown foods stay new entities."""
from k1_pipeline.extract.generator import compile_k2_label
from k1_pipeline.fuse.entity_resolver import resolve_entity
from k1_pipeline.models import K2Label


def test_toast_is_bread():
    assert resolve_entity("toast") == "bread"
    assert resolve_entity("lightly buttered toast") == "bread"
    assert resolve_entity("Toasted Bread") == "bread"


def test_scrambled_eggs_are_egg():
    assert resolve_entity("scrambled_eggs") == "egg"
    assert resolve_entity("scrambled eggs") == "egg"


def test_new_ingredient_is_kept():
    assert resolve_entity("goat cheese") == "goat cheese"
    assert resolve_entity("crème fraîche") == "crème fraîche"


def test_baked_bread_compiles_to_solid():
    assert compile_k2_label("baked_bread") == K2Label.solid
    assert compile_k2_label("toasted") == K2Label.solid
