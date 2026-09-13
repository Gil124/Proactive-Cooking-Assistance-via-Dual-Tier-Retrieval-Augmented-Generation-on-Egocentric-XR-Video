"""
LLM client — multi-provider fallback with Instructor constrained decoding.
Ported and simplified from Cooking-Advisor/src/llm_client.py.
Temperature is always forced to 0 as per models.yaml.
"""

from __future__ import annotations

import os
import time
import warnings
from typing import Type, TypeVar

warnings.filterwarnings("ignore", category=FutureWarning, module="instructor")
warnings.filterwarnings("ignore", category=FutureWarning, module="google")

import instructor
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from k1_pipeline.config_loader import load_models

load_dotenv()

T = TypeVar("T", bound=BaseModel)

_cfg = load_models()

GENERATOR_MODELS: list[str] = [_cfg["extraction"]["generator"]] + _cfg.get("fallback_generators", [])
CRITIC_MODELS: list[str] = [_cfg["critic"]["model"]] + _cfg.get("fallback_critics", [])

_groq: instructor.Instructor | None = None
_openrouter: instructor.Instructor | None = None
_gemini: instructor.Instructor | None = None


def _get_groq() -> instructor.Instructor:
    global _groq
    if _groq is None:
        _groq = instructor.from_openai(
            OpenAI(api_key=os.environ.get("GROQ_API_KEY", ""), base_url="https://api.groq.com/openai/v1"),
            mode=instructor.Mode.TOOLS,
        )
    return _groq


def _get_openrouter() -> instructor.Instructor:
    global _openrouter
    if _openrouter is None:
        _openrouter = instructor.from_openai(
            OpenAI(api_key=os.environ.get("OPENROUTER_API_KEY", ""), base_url="https://openrouter.ai/api/v1"),
            mode=instructor.Mode.TOOLS,
        )
    return _openrouter


def _get_gemini() -> instructor.Instructor:
    global _gemini
    if _gemini is None:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))
        _gemini = instructor.from_gemini(
            client=genai.GenerativeModel(model_name="gemini-2.0-flash-lite"),
            mode=instructor.Mode.GEMINI_JSON,
        )
    return _gemini


def _resolve(full_model: str) -> tuple[instructor.Instructor, str | None]:
    if full_model.startswith("groq/"):
        return _get_groq(), full_model[len("groq/"):]
    if full_model.startswith("openrouter/"):
        return _get_openrouter(), full_model[len("openrouter/"):]
    if full_model.startswith("gemini/"):
        return _get_gemini(), None
    # litellm fallback
    import litellm
    return instructor.from_litellm(litellm.completion), full_model


_RETRYABLE = (
    "RateLimitError", "ServiceUnavailableError", "Timeout",
    "APIConnectionError", "InternalServerError", "OverloadedError",
    "NotFoundError", "InstructorRetryException",
)
_RETRYABLE_PHRASES = (
    "rate limit", "ratelimit", "too many requests", "resource_exhausted",
    "server error", "service unavailable", "overloaded", "timeout", "connection",
    "502", "503", "529", "not a valid model", "model not found",
)


def _classify(e: Exception) -> tuple[bool, float]:
    err_type = type(e).__name__
    err_msg = str(e).lower()
    if any(r in err_type for r in _RETRYABLE):
        extra = 8.0 if "InstructorRetry" in err_type else 0.0
        return True, extra
    if any(p in err_msg for p in _RETRYABLE_PHRASES):
        return True, 0.0
    return False, 0.0


def call_with_fallback(
    models: list[str],
    response_model: Type[T],
    messages: list[dict],
    max_tokens: int = 2048,
    base_delay: float = 2.0,
) -> T:
    last_error: Exception | None = None
    for i, full_model in enumerate(models):
        client, model_name = _resolve(full_model)
        is_gemini = full_model.startswith("gemini/")
        kwargs: dict = dict(
            response_model=response_model,
            messages=messages,
            max_retries=2,
        )
        if model_name is not None:
            kwargs["model"] = model_name
        if not is_gemini:
            kwargs["max_tokens"] = max_tokens

        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            retryable, extra = _classify(e)
            if retryable:
                wait = base_delay * (i + 1) + extra
                print(f"  [{full_model}] {type(e).__name__} — waiting {wait:.0f}s…")
                last_error = e
                time.sleep(wait)
            else:
                raise

    raise RuntimeError(
        f"All {len(models)} models failed. Last error: {last_error}"
    )
