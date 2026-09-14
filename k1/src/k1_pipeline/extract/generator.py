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

== RULES ==
1. source_span MUST be a verbatim substring of the step text.
2. k2_label MUST be one of: liquid, coagulating, solid, scorched.
3. Do NOT invent temperature values. Only use temperatures from step text or bounds above.
4. Every Process node must have at least one pre_condition and one post_condition.
5. confidence is your self-assessed certainty 0.0–1.0.
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
    if any(w in low for w in ["solid", "set", "firm", "cooked"]):
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
    )

    # Patch in provenance fields that LLM can't set
    node.recipe_id = recipe.recipe_id
    node.step_number = step_number
    node.extractor_model = _GENERATOR_MODEL

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
