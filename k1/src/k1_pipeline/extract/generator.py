"""
L2 Extract — Generator
Extracts structured K1 nodes from individual recipe steps using a constrained LLM.
All output is grounded via source_span (verbatim quote).
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from rich.console import Console

from k1_pipeline.config_loader import get_k2_compile_map, load_models, load_physics_bounds
from k1_pipeline.extract.llm_client import GENERATOR_MODELS, call_with_fallback
from k1_pipeline.models import CanonicalRecipe, ExtractedNode, K2Label, NodeType, StateCondition
from k1_pipeline.scope import scope_prompt_block

console = Console()

_MODELS_CFG = load_models()
_GENERATOR_MODEL = _MODELS_CFG["extraction"]["generator"]

_PHYSICS_BOUNDS = load_physics_bounds()
_PHYSICS_TEMPS = {
    b["id"]: b["temperature_c"]
    for b in _PHYSICS_BOUNDS
    if b["temperature_c"] is not None
}
_PHYSICS_CONTEXT = "\n".join(
    f"- {b['label']}: {b['temperature_c']} °C — {b['description']}"
    if b["temperature_c"] else f"- {b['label']}: {b['description']}"
    for b in _PHYSICS_BOUNDS
)

_K2_MAP = get_k2_compile_map()

_SYSTEM_PROMPT = f"""\
You are an expert knowledge graph extraction agent for cooking recipes.
Your task is to extract a single K1 graph node from one recipe step.

== ONTOLOGY (frozen — do not invent new types) ==
node_type values:
  - Process : a cooking action that changes ingredient state
  - Transfer: movement of ingredient/item (pour, add, remove from heat)
  - Plate   : plating or serving (always the final step)

k2_label values (compile from physics state):
  - liquid      : raw, whisked, beaten, runny, fluid state
  - coagulating : gel, soft-curd, partial-set, thickening
  - solid       : fully-set, firm, cross-linked, cooked through
  - scorched    : browning, burnt, rubbery, syneresis weeping

== PHYSICS BOUNDS (curated — do not invent temperatures) ==
If you cite a temperature, it must appear verbatim in the step text
OR match one of these known bounds:
{_PHYSICS_CONTEXT}

== SCOPE (closed inventory) ==
{scope_prompt_block()}

== RULES ==
1. source_span MUST be a verbatim substring of the step text.
2. k2_label MUST be one of: liquid, coagulating, solid, scorched.
3. Do NOT invent temperature values. Only use temperatures from step text or bounds above.
4. Every Process node must have at least one pre_condition and one post_condition.
5. confidence is your self-assessed certainty 0.0–1.0.
6. entity_id is the base ingredient or tool, not the name of its current preparation.
   Toast, buttered toast, and toasted bread are entity_id "bread" with physics_state
   "toasted" and k2_label "solid". Scrambled eggs are entity_id "egg".
   A different food the step actually introduces (goat cheese, cream, herbs) is a
   new entity and must be kept under its own name. Do not invent entities such as
   "plated_dish" or "serving".
7. Extract only the part of the step that uses the station inventory. Name
   entities, ingredients, and tools in English with the inventory names above.
   Leave every other item out of action_phrase, pre_conditions, post_conditions,
   ingredients, and tools. "Whisk together the eggs, milk, salt and pepper"
   becomes action_phrase "whisk eggs with salt and pepper". "Lay the toast on a
   plate, spoon the eggs on top, top with the chutney" becomes "spoon eggs onto
   plate". Where you can, choose a source_span that covers only the kept part.
8. If nothing in the step uses the eggs or the station inventory (serving with
   bread, adding a garnish or a sauce), set in_scope to false. Still give
   node_type, a short action_phrase, and source_span; conditions may be empty.
   Otherwise in_scope is true.
"""


def _build_prompt(
    recipe: CanonicalRecipe,
    step_number: int,
    revision_hint: str | None = None,
) -> str:
    step = next(s for s in recipe.steps if s.number == step_number)
    ingredient_list = ", ".join(recipe.ingredients[:8]) or "not listed"
    prompt = (
        f"Recipe: {recipe.title}\n"
        f"Variant: {recipe.variant_label}\n"
        f"Ingredients: {ingredient_list}\n\n"
        f"Step {step_number}: \"{step.text}\"\n\n"
        "Extract the K1 node for this step. "
        "source_span must be copied verbatim from the step text above."
    )
    if revision_hint:
        prompt += f"\n\nCritic revision note (fix these issues): {revision_hint}"
    return prompt


# Typographic characters a model tends to rewrite. Each maps to one character,
# so a position in the normalised text is the same position in the original.
_SPAN_NORMALISE = str.maketrans({
    "\u2019": "'", "\u2018": "'", "\u02bc": "'",
    "\u201c": '"', "\u201d": '"',
    "\u00a0": " ", "\u2013": "-", "\u2014": "-",
})


def ground_span(span: str, step_text: str) -> str:
    """
    Return the verbatim substring of `step_text` that `span` stands for.

    A model often writes a straight apostrophe where the source has a curly one,
    which breaks the substring check without changing the quote. When the two
    match after normalising those characters, the original slice is returned.
    Anything else is returned unchanged and left for the critic to flag.
    """
    if span in step_text:
        return span
    start = step_text.translate(_SPAN_NORMALISE).find(span.translate(_SPAN_NORMALISE))
    if start < 0:
        return span
    return step_text[start:start + len(span)]


def compile_k2_label(physics_state: str) -> K2Label:
    """Map a free-text physics state string to a K2Label via the compile map."""
    key = physics_state.lower().strip().replace(" ", "_").replace("-", "_")
    mapped = _K2_MAP.get(key) or _K2_MAP.get(physics_state.lower().strip())
    if mapped:
        return K2Label(mapped)
    # Heuristic fallback
    low = physics_state.lower()
    if any(w in low for w in ["liquid", "raw", "whisk", "beat", "fluid"]):
        return K2Label.liquid
    if any(w in low for w in ["coagulat", "gel", "soft", "creamy", "thicken"]):
        return K2Label.coagulating
    if any(w in low for w in ["solid", "set", "firm", "cooked", "toast", "baked"]):
        return K2Label.solid
    if any(w in low for w in ["scorch", "burn", "brown", "rubber", "dry", "over"]):
        return K2Label.scorched
    return K2Label.liquid  # safest default for eggs


def extract_node(
    recipe: CanonicalRecipe,
    step_number: int,
    artifact_dir: Path,
    revision_hint: str | None = None,
) -> ExtractedNode:
    """
    Run the generator for one step. Returns an ExtractedNode.
    Persists the raw output to artifact_dir.
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{recipe.recipe_id}_step{step_number:02d}.gen.json"

    # Return cached if exists
    if artifact_path.exists():
        try:
            return ExtractedNode.model_validate_json(artifact_path.read_text())
        except Exception:
            pass  # re-extract

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_prompt(recipe, step_number, revision_hint)},
    ]

    node = call_with_fallback(
        GENERATOR_MODELS,
        ExtractedNode,
        messages,
        max_tokens=int(_MODELS_CFG["extraction"].get("max_tokens", 16384)),
    )

    # Patch in provenance fields that LLM can't set
    node.recipe_id = recipe.recipe_id
    node.step_number = step_number
    node.extractor_model = _GENERATOR_MODEL
    step_text = next(s.text for s in recipe.steps if s.number == step_number)
    node.source_span = ground_span(node.source_span, step_text)

    # Re-compile k2_labels via compile map (LLM may have used free text)
    node.pre_conditions = [
        StateCondition(
            entity_id=c.entity_id,
            physics_state=c.physics_state,
            k2_label=compile_k2_label(c.physics_state),
        )
        for c in node.pre_conditions
    ]
    node.post_conditions = [
        StateCondition(
            entity_id=c.entity_id,
            physics_state=c.physics_state,
            k2_label=compile_k2_label(c.physics_state),
        )
        for c in node.post_conditions
    ]

    artifact_path.write_text(node.model_dump_json(indent=2))
    return node


def extract_recipe(
    recipe: CanonicalRecipe,
    run_dir: Path,
) -> list[ExtractedNode]:
    """Extract all steps of a recipe. Returns list of ExtractedNode."""
    artifact_dir = run_dir / "L2" / "gen"
    nodes = []
    for step in recipe.steps:
        console.print(f"  [dim]Extracting {recipe.recipe_id} step {step.number}/{len(recipe.steps)}[/dim]")
        node = extract_node(recipe, step.number, artifact_dir)
        nodes.append(node)
    return nodes
