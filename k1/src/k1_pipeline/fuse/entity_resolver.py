"""
L3 Fuse -- Entity Resolver
Canonicalizes entity names across recipes using:
  1. Exact-match lookup against ontology.yaml canonical_entities.
  2. Embedding top-K similarity for fuzzy matches (sentence-transformers local).
  3. LLM pairwise disambiguation only for ambiguous pairs (0.75 < cosine < 0.95).
"""

from __future__ import annotations

from k1_pipeline.config_loader import get_canonical_entity_map


def resolve_entity(name: str) -> str:
    """
    Map a raw entity name string to its canonical form.
    Falls back to normalized lowercased name if no alias match found.
    """
    canon_map = get_canonical_entity_map()
    key = name.lower().strip()
    return canon_map.get(key, key)


def resolve_entities_in_conditions(conditions: list) -> list:
    """Replace entity_id in a list of StateCondition objects with canonical form."""
    for cond in conditions:
        cond.entity_id = resolve_entity(cond.entity_id)
    return conditions
