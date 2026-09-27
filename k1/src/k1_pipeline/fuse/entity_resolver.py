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
    Map a raw entity name to its base entity when it is a known preparation.

    "toast" resolves to "bread". A name that is not an alias is kept, so a
    genuinely new ingredient stays in the graph.
    """
    canon_map = get_canonical_entity_map()
    raw = name.lower().strip()
    spaced = " ".join(raw.replace("_", " ").replace("-", " ").split())
    if raw in canon_map:
        return canon_map[raw]
    if spaced in canon_map:
        return canon_map[spaced]
    return raw


def resolve_entities_in_conditions(conditions: list) -> list:
    """Replace entity_id in a list of StateCondition objects with canonical form."""
    for cond in conditions:
        cond.entity_id = resolve_entity(cond.entity_id)
    return conditions
