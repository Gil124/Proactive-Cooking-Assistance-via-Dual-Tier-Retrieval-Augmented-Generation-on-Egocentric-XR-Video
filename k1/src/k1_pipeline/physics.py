"""
physics.py -- Shared source of truth for all temperature and thermal-action logic.

Rules:
- KNOWN_TEMPS: float values sourced from physics_bounds.yaml only. Never edited by a model.
- Temperature scanning only matches unit-bearing patterns (digits + C or F).
  It never scans the whole serialised node -- only designated free-text fields.
- Thermal detection uses a fixed keyword set, not heuristics.

Imported by: critic/critic.py, eval/metrics.py, fuse/dag_builder.py, validate/gates.py.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from k1_pipeline.config_loader import load_physics_bounds

if TYPE_CHECKING:
    from k1_pipeline.models import ExtractedNode

# ── Curated physics constants (from physics_bounds.yaml) ─────────────────────

_BOUNDS = load_physics_bounds()

KNOWN_TEMPS: set[float] = {
    b["temperature_c"] for b in _BOUNDS if b.get("temperature_c") is not None
}

# ── Patterns ──────────────────────────────────────────────────────────────────

# Matches ONLY unit-bearing temperatures: "70 C", "62°C", "140 °F", "150C".
# A bare number like "90" or "0.95" does NOT match.
TEMP_UNIT_RE = re.compile(
    r"\b(\d{1,4})\s*(?:\u00b0\s*)?([CF])\b",
    re.IGNORECASE,
)

# Thermal-action keywords for detecting whether a Process node involves heat.
THERMAL_KEYWORDS = re.compile(
    r"\b(heat|cook|warm|melt|fry|saut|simmer|boil|scorch|burn|flame|brown|toast)\b",
    re.IGNORECASE,
)

# ── Public helpers ────────────────────────────────────────────────────────────


def extract_temperatures(text: str) -> set[float]:
    """
    Return all unit-bearing temperature values found in `text`.
    Only matches patterns like "70C", "62 °C", "140 F".
    Does NOT match bare numbers.
    """
    return {float(m.group(1)) for m in TEMP_UNIT_RE.finditer(text)}


def is_thermal_action(action_phrase: str) -> bool:
    """Return True if the action phrase contains a thermal-action keyword."""
    return bool(THERMAL_KEYWORDS.search(action_phrase))


def _free_text_fields(node: "ExtractedNode") -> list[str]:
    """
    Return the free-text strings from an ExtractedNode that may legitimately
    contain temperature values. Excludes numeric metadata (confidence, step_number, etc.).
    """
    fields: list[str] = [
        node.action_phrase,
        node.source_span,
    ]
    for cond in node.pre_conditions + node.post_conditions:
        fields.append(cond.physics_state)
    if node.timing_constraints and node.timing_constraints.deadline:
        fields.append(node.timing_constraints.deadline)
    return fields


def find_invented_temperatures(node: "ExtractedNode", step_text: str) -> list[float]:
    """
    Return temperature values in the node that are NOT grounded in either:
      - the step text (unit-bearing match), OR
      - the curated KNOWN_TEMPS set.

    Also checks the optional node.temperature_c field explicitly.
    A temperature is invented when it is in the node but not in either source.

    Returns a list of the offending values (empty = none found).
    """
    step_temps = extract_temperatures(step_text)

    invented: list[float] = []

    # Check the dedicated temperature_c field if set
    if node.temperature_c is not None:
        t = node.temperature_c
        if t not in step_temps and t not in KNOWN_TEMPS:
            invented.append(t)

    # Check unit-bearing mentions in free-text fields
    for field_text in _free_text_fields(node):
        for t in extract_temperatures(field_text):
            if t not in step_temps and t not in KNOWN_TEMPS and t not in invented:
                invented.append(t)

    return invented
