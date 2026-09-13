"""
Config loader — reads YAML config files and returns typed dicts/objects.
All config is loaded from k1/config/. Never hardcode paths elsewhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def _load(filename: str) -> Any:
    path = _CONFIG_DIR / filename
    with open(path) as f:
        return yaml.safe_load(f)


def load_recipes() -> list[dict]:
    return _load("recipes.yaml")["recipes"]


def load_ontology() -> dict:
    return _load("ontology.yaml")


def load_physics_bounds() -> list[dict]:
    return _load("physics_bounds.yaml")["bounds"]


def load_models() -> dict:
    return _load("models.yaml")


def get_k2_compile_map() -> dict[str, str]:
    """
    Returns {physics_state_string: k2_label} for all aliases in the compile map.
    Keys are lowercased and stripped.
    """
    ontology = load_ontology()
    result: dict[str, str] = {}
    for label, aliases in ontology["k2_compile_map"].items():
        for alias in aliases:
            result[alias.lower().strip()] = label
        result[label.lower().strip()] = label  # identity mapping
    return result


def get_canonical_entity_map() -> dict[str, str]:
    """Returns {alias: canonical_name} for all entity aliases."""
    ontology = load_ontology()
    result: dict[str, str] = {}
    for entry in ontology.get("canonical_entities", []):
        canonical = entry["canonical"]
        result[canonical.lower()] = canonical
        for alias in entry.get("aliases", []):
            result[alias.lower()] = canonical
    return result
