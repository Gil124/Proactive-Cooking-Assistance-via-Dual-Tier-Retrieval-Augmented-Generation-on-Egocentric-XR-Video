"""
L1 Ingest — Parser
Extracts structured recipe data from raw HTML.
Strategy:
  1. Try schema.org JSON-LD (covers most modern food blogs).
  2. Fall back to heuristic BeautifulSoup extraction.
  3. Junk-filter all step texts.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from bs4 import BeautifulSoup

from k1_pipeline.models import CanonicalRecipe, RecipeStep

# ── Junk filter rules ─────────────────────────────────────────────────────────

_JUNK_PATTERNS = [
    re.compile(r"[Oo]ther\s+\w+\s+[Rr]ecipes"),
    re.compile(r"[Ss]ee\s+also"),
    re.compile(r"[Tt]ry\s*:"),
    re.compile(r"[Pp]rint\s+[Rr]ecipe"),
    re.compile(r"[Ss]ubscribe"),
    re.compile(r"[Pp]in\s+[Tt]his"),
    re.compile(r"^\s*notes?\s*:?\s*$", re.IGNORECASE),
]


def _is_junk(text: str) -> bool:
    if len(text.strip()) < 15:
        return True
    for pattern in _JUNK_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _filter_steps(steps: list[RecipeStep]) -> tuple[list[RecipeStep], int]:
    """Return (kept_steps, dropped_count)."""
    filtered = [s for s in steps if not _is_junk(s.text)]
    dropped = len(steps) - len(filtered)
    if len(filtered) < 2:
        raise ValueError(
            f"After junk filtering, only {len(filtered)} step(s) remain. "
            "Check the recipe URL or add a junk filter exception."
        )
    return filtered, dropped


# ── Temperature / timing extraction ──────────────────────────────────────────

_TEMP_RE = re.compile(r"\b(\d{2,3})\s*°?\s*[CF]\b|\b(low|medium|high)\s+heat\b", re.IGNORECASE)
_TIME_RE = re.compile(
    r"\b(\d+)\s*(second|minute|hour|sec|min|hr)s?\b|\b(constantly|until set|until firm)\b",
    re.IGNORECASE,
)


def _extract_temps(text: str) -> list[str]:
    return [m.group(0) for m in _TEMP_RE.finditer(text)]


def _extract_timings(text: str) -> list[str]:
    return [m.group(0) for m in _TIME_RE.finditer(text)]


# ── schema.org JSON-LD extraction ─────────────────────────────────────────────

def _try_schema_org(html: str) -> Optional[dict]:
    """Try to parse schema.org Recipe JSON-LD from the page."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, AttributeError):
            continue
        # Can be a list or a single object or a @graph
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") in ("Recipe", "recipe"):
                    return item
        elif isinstance(data, dict):
            if data.get("@type") in ("Recipe", "recipe"):
                return data
            for item in data.get("@graph", []):
                if isinstance(item, dict) and item.get("@type") in ("Recipe", "recipe"):
                    return item
    return None


def _parse_instructions(instructions) -> list[str]:
    """Normalize schema.org recipeInstructions to a list of step strings."""
    if not instructions:
        return []
    if isinstance(instructions, str):
        # Sometimes a single blob of text
        return [s.strip() for s in instructions.split("\n") if s.strip()]
    if isinstance(instructions, list):
        steps = []
        for item in instructions:
            if isinstance(item, str):
                steps.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text", "")
                if text:
                    steps.append(text.strip())
        return steps
    return []


def _schema_org_to_canonical(data: dict, recipe_id: str, source_url: str, variant_label: str, gold: bool) -> CanonicalRecipe:
    title = data.get("name", "Unknown Recipe")
    raw_ingredients = data.get("recipeIngredient", [])
    ingredients = [str(i).strip() for i in raw_ingredients if str(i).strip()]

    raw_steps = _parse_instructions(data.get("recipeInstructions", []))
    recipe_steps = [RecipeStep(number=i + 1, text=s) for i, s in enumerate(raw_steps) if s]
    recipe_steps, dropped = _filter_steps(recipe_steps)

    all_text = " ".join(s.text for s in recipe_steps)
    temps = list(set(_extract_temps(all_text)))
    timings = list(set(_extract_timings(all_text)))

    # Tools are rarely in schema.org; try utensils field
    tools = list(data.get("tool", [])) or []

    return CanonicalRecipe(
        recipe_id=recipe_id,
        title=title,
        source_url=source_url,
        variant_label=variant_label,
        gold=gold,
        ingredients=ingredients,
        tools=tools,
        steps=recipe_steps,
        temperatures_mentioned=temps,
        timings_mentioned=timings,
    ), dropped


# ── Heuristic HTML extraction ─────────────────────────────────────────────────

_INGREDIENT_SELECTORS = [
    "[class*='ingredient']",
    "[itemprop='recipeIngredient']",
    "li[class*='ingredient']",
]

_STEP_SELECTORS = [
    "[class*='instruction']",
    "[class*='step']",
    "[itemprop='recipeInstructions']",
    "li[class*='step']",
    "ol li",
]

_TITLE_SELECTORS = [
    "h1[class*='title']",
    "h1[class*='recipe']",
    "h1",
]


def _heuristic_extract(html: str, recipe_id: str, source_url: str, variant_label: str, gold: bool) -> CanonicalRecipe:
    soup = BeautifulSoup(html, "lxml")

    # Title
    title = "Unknown Recipe"
    for sel in _TITLE_SELECTORS:
        el = soup.select_one(sel)
        if el:
            title = el.get_text(strip=True)
            break

    # Ingredients
    ingredients: list[str] = []
    for sel in _INGREDIENT_SELECTORS:
        els = soup.select(sel)
        if els:
            ingredients = [e.get_text(strip=True) for e in els if e.get_text(strip=True)]
            break

    # Steps
    steps_texts: list[str] = []
    for sel in _STEP_SELECTORS:
        els = soup.select(sel)
        if els and len(els) >= 2:
            steps_texts = [e.get_text(separator=" ", strip=True) for e in els]
            break

    recipe_steps = [RecipeStep(number=i + 1, text=s) for i, s in enumerate(steps_texts) if s]
    recipe_steps, dropped = _filter_steps(recipe_steps)

    all_text = " ".join(s.text for s in recipe_steps)
    temps = list(set(_extract_temps(all_text)))
    timings = list(set(_extract_timings(all_text)))

    return CanonicalRecipe(
        recipe_id=recipe_id,
        title=title,
        source_url=source_url,
        variant_label=variant_label,
        gold=gold,
        ingredients=ingredients,
        tools=[],
        steps=recipe_steps,
        temperatures_mentioned=temps,
        timings_mentioned=timings,
    ), dropped


# ── Public interface ──────────────────────────────────────────────────────────

def parse_recipe(
    html: str,
    recipe_id: str,
    source_url: str,
    variant_label: str,
    gold: bool = False,
) -> tuple[CanonicalRecipe, int]:
    """
    Parse HTML into a (CanonicalRecipe, dropped_count) tuple.
    Tries schema.org JSON-LD first, falls back to heuristic HTML extraction.
    Raises ValueError if junk filtering leaves fewer than 2 steps.
    dropped_count is the number of junk steps removed.
    """
    schema_data = _try_schema_org(html)
    if schema_data:
        return _schema_org_to_canonical(schema_data, recipe_id, source_url, variant_label, gold)
    return _heuristic_extract(html, recipe_id, source_url, variant_label, gold)
