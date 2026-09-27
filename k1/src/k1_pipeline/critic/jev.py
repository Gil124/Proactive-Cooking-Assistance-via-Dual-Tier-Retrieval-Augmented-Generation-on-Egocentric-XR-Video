"""
Jev semantic gate for the L2 critic.

Jev (TypeSafe, via the OpenRouter Decisions API) answers typed questions about
an extraction. It does not write revision text. The critic accepts a node
without calling the generative critic only when every semantic check clears
the configured threshold. Anything else is escalated.
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

from k1_pipeline.config_loader import load_models
from k1_pipeline.models import ExtractedNode

load_dotenv()

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.13"
DEFAULT_THRESHOLD = 0.85

NOUL_KEYS = (
    "node_type_matches",
    "preconditions_supported",
    "postconditions_supported",
    "action_faithful",
    "entities_are_objects",
)


class JevError(RuntimeError):
    """The Decisions API call failed or returned a shape we cannot branch on."""


def jev_settings() -> tuple[str, float]:
    cfg = load_models().get("jev") or {}
    model = str(cfg.get("model") or DEFAULT_MODEL)
    threshold = float(cfg.get("noul_accept_threshold", DEFAULT_THRESHOLD))
    return model, threshold


def semantic_questions() -> dict:
    """Questions asked together. Jev answers them in parallel; none can see the others."""
    return {
        "node_type_matches": {
            "type": "noul",
            "instructions": "The node_type correctly classifies this cooking step.",
            "criteria": {
                "true": (
                    "Process is an action that changes ingredient state. "
                    "Transfer moves an ingredient or item. "
                    "Plate is plating or serving. The chosen node_type matches the step text."
                ),
                "false": "The node_type names a different kind of action than the step text describes.",
            },
        },
        "preconditions_supported": {
            "type": "noul",
            "instructions": (
                "Every pre_condition is a state the step text supports or clearly assumes "
                "before the action."
            ),
            "criteria": {
                "true": (
                    "Each pre_condition is stated in the step or is the state that action "
                    "presupposes, such as eggs being liquid before they are whisked."
                ),
                "false": (
                    "A pre_condition invents an ingredient state, entity, or setup "
                    "the step does not assume."
                ),
            },
        },
        "postconditions_supported": {
            "type": "noul",
            "instructions": (
                "Every post_condition is a state this step actually produces, "
                "not an outcome from a later step."
            ),
            "criteria": {
                "true": "Each post_condition follows from the action described in the step text.",
                "false": "A post_condition states a result the step text does not produce.",
            },
        },
        "entities_are_objects": {
            "type": "noul",
            "instructions": (
                "Every entity_id names a distinct object. A cooked, plated, or prepared "
                "form of a food uses that food's base name, not a new entity_id."
            ),
            "criteria": {
                "true": (
                    "Each entity_id is a separate ingredient or tool. "
                    "Toast is bread, scrambled eggs are egg, and the form is only a physics_state. "
                    "A different food, such as goat cheese or cream, is its own entity."
                ),
                "false": (
                    "An entity_id is only a state or preparation of another food "
                    "(for example entity_id 'toast' instead of 'bread'), "
                    "or a made-up container such as 'plated_dish'."
                ),
            },
        },
        "action_faithful": {
            "type": "noul",
            "instructions": "The action_phrase names only an action the step text states.",
            "criteria": {
                "true": "The action_phrase is a fair short name for an action written in the step.",
                "false": "The action_phrase adds an action, ingredient, or tool the step does not state.",
            },
        },
        "verdict": {
            "type": "choice",
            "instructions": "How should this extraction be treated, judging it on its own?",
            "criteria": {
                "accept": (
                    "node_type, action_phrase, pre_conditions, and post_conditions "
                    "are all faithful to the step text."
                ),
                "revise": "The extraction is partly grounded but has a fixable mistake.",
                "reject": (
                    "The extraction is ungrounded, or the node_type is completely wrong "
                    "and cannot be repaired from this step."
                ),
            },
        },
    }


def extraction_state(
    step_text: str,
    node: ExtractedNode,
    revision_hint: str | None = None,
) -> dict:
    state: dict = {
        "step_text": step_text,
        "extraction": {
            "node_type": node.node_type.value,
            "action_phrase": node.action_phrase,
            "pre_conditions": [c.model_dump(mode="json") for c in node.pre_conditions],
            "post_conditions": [c.model_dump(mode="json") for c in node.post_conditions],
            "ingredients": list(node.ingredients),
            "tools": list(node.tools),
            "source_span": node.source_span,
        },
    }
    if revision_hint:
        state["revision_hint"] = revision_hint
    return state


def call_jev(state: dict, questions: dict, model: str) -> tuple[dict, str]:
    """POST one Decisions API request. Returns (answers, served model id)."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise JevError("OPENROUTER_API_KEY is not set")

    try:
        resp = requests.post(
            DECISIONS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "state": state, "questions": questions},
            timeout=60,
        )
    except requests.RequestException as e:
        raise JevError(f"Jev request failed: {type(e).__name__}") from e

    if resp.status_code >= 400:
        raise JevError(f"Jev decisions API {resp.status_code}: {resp.text[:300]}")

    try:
        body = resp.json()
    except ValueError as e:
        raise JevError("Jev response was not JSON") from e

    answers = body.get("answers")
    if not isinstance(answers, dict):
        raise JevError("Jev response missing answers")
    return answers, str(body.get("model") or model)


def _require_shape(answers: dict) -> None:
    for key in NOUL_KEYS:
        answer = answers.get(key)
        if not isinstance(answer, dict) or "noul" not in answer:
            raise JevError(f"Jev answer '{key}' is missing noul")
        float(answer["noul"])
    verdict = answers.get("verdict")
    if not isinstance(verdict, dict) or verdict.get("choice") not in {"accept", "revise", "reject"}:
        raise JevError("Jev verdict choice is missing or not accept|revise|reject")


def judge_extraction(
    step_text: str,
    node: ExtractedNode,
    revision_hint: str | None = None,
) -> tuple[dict, str]:
    """Ask Jev about one extraction. Returns (answers, served model id)."""
    model, _threshold = jev_settings()
    answers, served = call_jev(
        extraction_state(step_text, node, revision_hint),
        semantic_questions(),
        model,
    )
    _require_shape(answers)
    return answers, served


def score_map(answers: dict) -> dict[str, float]:
    """Flat probabilities stored on the critic artifact."""
    scores = {key: float(answers[key]["noul"]) for key in NOUL_KEYS}
    probs = (answers.get("verdict") or {}).get("probabilities") or {}
    if "accept" in probs:
        scores["verdict_accept"] = float(probs["accept"])
    elif answers["verdict"]["choice"] == "accept":
        scores["verdict_accept"] = 1.0
    else:
        scores["verdict_accept"] = 0.0
    return scores


def jev_accepts(answers: dict, threshold: float) -> bool:
    """
    Accept only when every semantic Noul clears the threshold and the Choice
    both selects accept and puts at least `threshold` probability on it.

    Questions are answered independently, so agreement between the Nouls and
    the Choice is checked here rather than inside the request.
    """
    if any(float(answers[key]["noul"]) < threshold for key in NOUL_KEYS):
        return False
    verdict = answers["verdict"]
    if verdict.get("choice") != "accept":
        return False
    probs = verdict.get("probabilities") or {}
    if "accept" in probs and float(probs["accept"]) < threshold:
        return False
    return True


def failed_checks(answers: dict, threshold: float) -> list[str]:
    """Human-readable flags passed to the generative critic on escalation."""
    flags = [
        f"{key}={float(answers[key]['noul']):.2f}"
        for key in NOUL_KEYS
        if float(answers[key]["noul"]) < threshold
    ]
    choice = answers["verdict"].get("choice")
    if choice != "accept":
        flags.append(f"verdict={choice}")
    return flags
