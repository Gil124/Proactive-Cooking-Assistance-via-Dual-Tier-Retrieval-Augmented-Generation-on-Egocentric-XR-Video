"""
L2 Critic -- Grounded verifier
Validates each ExtractedNode against:
  1. source_span is a substring of the step text
  2. k2_labels are valid
  3. No invented temperatures (not in step text AND not in physics_bounds.yaml)
  4. Structural consistency

On 'revise': one revision loop is triggered (generator re-called with critic instructions).
On 'reject': the node is dropped from the pipeline with a warning.
"""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

from k1_pipeline.config_loader import load_models, load_physics_bounds
from k1_pipeline.extract.llm_client import CRITIC_MODELS, call_with_fallback
from k1_pipeline.models import CanonicalRecipe, CriticOutput, CriticVerdict, ExtractedNode, K2Label

console = Console()

_MODELS_CFG = load_models()
_CRITIC_MODEL = _MODELS_CFG["critic"]["model"]
_PHYSICS_BOUNDS = load_physics_bounds()
_KNOWN_TEMPS = {b["temperature_c"] for b in _PHYSICS_BOUNDS if b["temperature_c"] is not None}

_TEMP_RE = re.compile(r"\b(\d{2,3})\b")


def _extract_temp_values(text: str) -> set[float]:
    return {float(m.group(1)) for m in _TEMP_RE.finditer(text)}


_SYSTEM_PROMPT = """\
You are a strict knowledge graph critic for cooking recipes.
You verify that an extracted node is correctly grounded in its source text.

Your verdict must be one of:
  - accept  : the extraction is correct and well-grounded
  - revise  : fixable problems found; provide revision_instructions
  - reject  : unfixable error (invented temperature, completely wrong node_type, no grounding possible)

Rules:
1. source_span must be a verbatim substring of the step text. If not -> revise or reject.
2. k2_label must be one of: liquid, coagulating, solid, scorched. Wrong -> revise.
3. Temperature values in the extraction must appear verbatim in the step text
   OR match a known physics bound (62, 70, 140, 150 C). Invented temps -> reject.
4. A Process node without pre_conditions or post_conditions -> revise.
5. grounding_quote must be a substring of the step text that confirms (or denies) the extraction.
"""


def _build_critic_prompt(recipe: CanonicalRecipe, step_number: int, node: ExtractedNode) -> str:
    step = next(s for s in recipe.steps if s.number == step_number)
    node_json = node.model_dump_json(indent=2)
    return (
        f"Step text: \"{step.text}\"\n\n"
        f"Extracted node:\n{node_json}\n\n"
        "Verify the extraction against the step text. "
        "grounding_quote must be a verbatim substring of the step text above."
    )


def _deterministic_check(node: ExtractedNode, step_text: str) -> list[str]:
    """Deterministic (no-LLM) pre-checks. Returns list of issues found."""
    issues = []

    if node.source_span not in step_text:
        issues.append(f"source_span not found in step text: '{node.source_span[:60]}'")

    valid = {lbl.value for lbl in K2Label}
    for cond in node.pre_conditions + node.post_conditions:
        if cond.k2_label.value not in valid:
            issues.append(f"Invalid k2_label '{cond.k2_label}' on entity '{cond.entity_id}'")

    extracted_temps = _extract_temp_values(node.model_dump_json())
    step_temps = _extract_temp_values(step_text)
    for t in extracted_temps:
        if t not in step_temps and t not in _KNOWN_TEMPS:
            issues.append(f"Invented temperature {t} C (not in step text or physics_bounds)")

    return issues


def verify_node(
    recipe: CanonicalRecipe,
    step_number: int,
    node: ExtractedNode,
    artifact_dir: Path,
) -> CriticOutput:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{recipe.recipe_id}_step{step_number:02d}.critic.json"

    if artifact_path.exists():
        try:
            return CriticOutput.model_validate_json(artifact_path.read_text())
        except Exception:
            pass

    step = next(s for s in recipe.steps if s.number == step_number)
    step_text = step.text

    issues = _deterministic_check(node, step_text)
    if issues:
        verdict = (
            CriticVerdict.reject
            if any("Invented temperature" in i for i in issues)
            else CriticVerdict.revise
        )
        result = CriticOutput(
            node_id=node.node_id,
            verdict=verdict,
            grounding_quote=step_text[:80],
            issues=issues,
            critic_model="deterministic",
            revision_instructions=(
                "Fix the following: " + "; ".join(issues)
            ) if verdict == CriticVerdict.revise else None,
        )
        artifact_path.write_text(result.model_dump_json(indent=2))
        return result

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_critic_prompt(recipe, step_number, node)},
    ]
    result = call_with_fallback(CRITIC_MODELS, CriticOutput, messages, max_tokens=512)
    result.node_id = node.node_id
    result.critic_model = _CRITIC_MODEL

    artifact_path.write_text(result.model_dump_json(indent=2))
    return result


def verify_recipe(
    recipe: CanonicalRecipe,
    nodes: list[ExtractedNode],
    run_dir: Path,
) -> list[tuple[ExtractedNode, CriticOutput]]:
    """
    Verify all extracted nodes. Returns (node, critic) pairs for accepted/revised nodes only.
    Rejected nodes are excluded with a warning.
    """
    from k1_pipeline.extract.generator import extract_node  # lazy to avoid circular

    critic_dir = run_dir / "L2" / "critic"
    gen_dir = run_dir / "L2" / "gen"
    results: list[tuple[ExtractedNode, CriticOutput]] = []

    for node in nodes:
        sn = node.step_number
        console.print(f"  [dim]Critic {recipe.recipe_id} step {sn}[/dim]")
        critic_out = verify_node(recipe, sn, node, critic_dir)

        if critic_out.verdict == CriticVerdict.accept:
            results.append((node, critic_out))
        elif critic_out.verdict == CriticVerdict.revise:
            console.print(f"    [yellow]REVISE step {sn}:[/yellow] {'; '.join(critic_out.issues)}")
            cached = gen_dir / f"{recipe.recipe_id}_step{sn:02d}.gen.json"
            if cached.exists():
                cached.unlink()
            revised_node = extract_node(recipe, sn, gen_dir)
            results.append((revised_node, critic_out))
        else:
            console.print(f"    [red]REJECT step {sn}:[/red] {'; '.join(critic_out.issues)}")

    return results
