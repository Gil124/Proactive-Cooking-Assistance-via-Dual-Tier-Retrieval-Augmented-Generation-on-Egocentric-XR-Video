"""
Jev semantic gate in front of the generative critic.

The gate accepts on its own only when every Noul and the Choice probability
of "accept" clear the threshold. Deterministic failures never call Jev.
A Jev miss or a Jev outage falls through to the generative critic.
"""
from __future__ import annotations

from k1_pipeline.critic.critic import verify_node
from k1_pipeline.critic.jev import (
    NOUL_KEYS,
    JevError,
    call_jev,
    failed_checks,
    jev_accepts,
    score_map,
)
from k1_pipeline.models import (
    CanonicalRecipe,
    CriticOutput,
    CriticVerdict,
    ExtractedNode,
    K2Label,
    NodeType,
    RecipeStep,
    StateCondition,
)


def _answers(noul: float = 0.95, choice: str = "accept", accept_p: float | None = None) -> dict:
    if accept_p is None:
        accept_p = 0.95 if choice == "accept" else 0.1
    return {
        key: {"type": "noul", "noul": noul}
        for key in NOUL_KEYS
    } | {
        "verdict": {
            "type": "choice",
            "choice": choice,
            "confidence": 0.9,
            "probabilities": {"accept": accept_p, "revise": 0.04, "reject": 0.01},
        }
    }


def _recipe(text: str = "Whisk the eggs until smooth.") -> CanonicalRecipe:
    return CanonicalRecipe(
        recipe_id="r1",
        title="Eggs",
        source_url="https://example.test/eggs",
        variant_label="classic",
        ingredients=["egg"],
        tools=["bowl"],
        steps=[RecipeStep(number=1, text=text)],
    )


def _node(**kwargs) -> ExtractedNode:
    defaults = dict(
        recipe_id="r1",
        step_number=1,
        node_type=NodeType.Process,
        action_phrase="whisk eggs",
        pre_conditions=[
            StateCondition(entity_id="egg", physics_state="raw", k2_label=K2Label.liquid)
        ],
        post_conditions=[
            StateCondition(entity_id="egg", physics_state="homogenized", k2_label=K2Label.liquid)
        ],
        source_span="Whisk the eggs",
        confidence=0.9,
        extractor_model="test",
    )
    defaults.update(kwargs)
    return ExtractedNode(**defaults)


# ── pure decision ─────────────────────────────────────────────────────────────

def test_accepts_when_every_check_clears_threshold():
    assert jev_accepts(_answers(), 0.85) is True


def test_rejects_accept_when_one_noul_is_low():
    answers = _answers()
    answers["action_faithful"]["noul"] = 0.4
    assert jev_accepts(answers, 0.85) is False
    assert "action_faithful=0.40" in failed_checks(answers, 0.85)


def test_rejects_accept_when_choice_is_revise():
    answers = _answers(choice="revise")
    assert jev_accepts(answers, 0.85) is False
    assert "verdict=revise" in failed_checks(answers, 0.85)


def test_rejects_accept_when_accept_probability_is_below_threshold():
    answers = _answers(accept_p=0.5)
    assert jev_accepts(answers, 0.85) is False


def test_threshold_is_inclusive():
    assert jev_accepts(_answers(noul=0.85, accept_p=0.85), 0.85) is True


def test_score_map_records_nouls_and_accept_probability():
    scores = score_map(_answers(noul=0.91, accept_p=0.88))
    assert scores["node_type_matches"] == 0.91
    assert scores["verdict_accept"] == 0.88


# ── Decisions API client ──────────────────────────────────────────────────────

def test_call_jev_posts_decisions_request(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"model": "typesafe/jev-1.13-20260917", "answers": _answers()}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["auth"] = headers["Authorization"]
        return _Resp()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr("k1_pipeline.critic.jev.requests.post", fake_post)

    answers, served = call_jev({"step_text": "whisk"}, {"verdict": {"type": "choice"}}, "typesafe/jev-1.13")

    assert captured["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert captured["json"]["model"] == "typesafe/jev-1.13"
    assert captured["auth"] == "Bearer test-key"
    assert served == "typesafe/jev-1.13-20260917"
    assert answers["verdict"]["choice"] == "accept"


def test_call_jev_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    def fail_post(*_a, **_k):
        raise AssertionError("should not call the API without a key")

    monkeypatch.setattr("k1_pipeline.critic.jev.requests.post", fail_post)
    try:
        call_jev({}, {}, "typesafe/jev-1.13")
    except JevError as e:
        assert "OPENROUTER_API_KEY" in str(e)
    else:
        raise AssertionError("expected JevError")


# ── verify_node cascade ───────────────────────────────────────────────────────

def test_deterministic_failure_skips_jev_and_gemini(tmp_path, monkeypatch):
    def fail(*_a, **_k):
        raise AssertionError("model should not be called")

    monkeypatch.setattr("k1_pipeline.critic.critic.judge_extraction", fail)
    monkeypatch.setattr("k1_pipeline.critic.critic.call_with_fallback", fail)

    result = verify_node(
        _recipe(),
        1,
        _node(source_span="this span is not in the step"),
        tmp_path,
    )
    assert result.verdict == CriticVerdict.revise
    assert result.critic_model == "deterministic"
    assert result.jev_scores == {}


def test_jev_accept_skips_generative_critic(tmp_path, monkeypatch):
    def fake_judge(*_a, **_k):
        return _answers(), "typesafe/jev-1.13-20260917"

    def fail(*_a, **_k):
        raise AssertionError("generative critic should not be called")

    monkeypatch.setattr("k1_pipeline.critic.critic.judge_extraction", fake_judge)
    monkeypatch.setattr("k1_pipeline.critic.critic.call_with_fallback", fail)

    result = verify_node(_recipe(), 1, _node(), tmp_path)
    assert result.verdict == CriticVerdict.accept
    assert result.critic_model == "openrouter/typesafe/jev-1.13-20260917"
    assert result.grounding_quote == "Whisk the eggs"
    assert result.jev_scores["action_faithful"] == 0.95
    saved = (tmp_path / "r1_step01.critic.json").read_text()
    assert "typesafe/jev-1.13-20260917" in saved


def test_jev_miss_escalates_to_generative_critic(tmp_path, monkeypatch):
    answers = _answers()
    answers["postconditions_supported"]["noul"] = 0.2
    captured = {}

    def fake_judge(*_a, **_k):
        return answers, "typesafe/jev-1.13"

    def fake_gemini(_models, _response_model, messages, max_tokens=512):
        captured["messages"] = messages
        return CriticOutput(
            verdict=CriticVerdict.revise,
            grounding_quote="Whisk the eggs",
            issues=["post-condition overreaches"],
            revision_instructions="Drop the invented post-condition.",
        )

    monkeypatch.setattr("k1_pipeline.critic.critic.judge_extraction", fake_judge)
    monkeypatch.setattr("k1_pipeline.critic.critic.call_with_fallback", fake_gemini)

    result = verify_node(_recipe(), 1, _node(), tmp_path)
    assert result.verdict == CriticVerdict.revise
    assert result.critic_model == "openrouter/google/gemini-3.7-flash"
    assert result.revision_instructions == "Drop the invented post-condition."
    assert result.jev_scores["postconditions_supported"] == 0.2
    user = captured["messages"][1]["content"]
    assert "postconditions_supported=0.20" in user


def test_jev_outage_falls_through_to_generative_critic(tmp_path, monkeypatch):
    def fake_judge(*_a, **_k):
        raise JevError("Jev decisions API 503: unavailable")

    def fake_gemini(_models, _response_model, messages, max_tokens=512):
        return CriticOutput(
            verdict=CriticVerdict.accept,
            grounding_quote="Whisk the eggs",
            issues=[],
        )

    monkeypatch.setattr("k1_pipeline.critic.critic.judge_extraction", fake_judge)
    monkeypatch.setattr("k1_pipeline.critic.critic.call_with_fallback", fake_gemini)

    result = verify_node(_recipe(), 1, _node(), tmp_path)
    assert result.verdict == CriticVerdict.accept
    assert result.critic_model == "openrouter/google/gemini-3.7-flash"
    assert result.jev_scores == {}
