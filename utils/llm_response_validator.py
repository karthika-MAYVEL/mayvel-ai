# utils/llm_response_validator.py
# Generic LLM response validator.
#
# Usage:
#   from utils.llm_response_validator import validate, build_correction_prompt
#   from presentation.models.routing_decision import RoutingDecision
#
#   # Validate raw LLM string against any Pydantic model
#   result: RoutingDecision = validate(raw, RoutingDecision, query)
#
#   # On ValueError, build a correction prompt for retry
#   correction = build_correction_prompt(raw, RoutingDecision, query)
#
# Works with ANY Pydantic BaseModel — no agent-specific logic here.

import json
from typing import Type, TypeVar

from pydantic import BaseModel
from utils.logger import get_app_logger

logger = get_app_logger("llm_response_validator")

T = TypeVar("T", bound=BaseModel)


def validate(raw: str, model: Type[T], query: str) -> T:
    """
    Validates raw LLM output against a Pydantic model.

    Pipeline:
      1. Strip markdown code fences
      2. Parse JSON — raises ValueError on invalid JSON
      3. Check top-level shape is a dict — raises ValueError if list or other
      4. Validate against the model — raises ValueError on schema mismatch

    @param raw:   Raw string response from the LLM.
    @param model: Pydantic model class to validate against.
    @param query: Original user query (used in error messages for context).
    @returns:     Validated instance of the model.
    @raises ValueError: On any validation failure, with a clear message.
    """
    cleaned = _strip_fences(raw)
    parsed = _parse_json(cleaned, raw)
    _check_shape(parsed, query, model)
    return _validate_model(parsed, model, raw)


def build_correction_prompt(bad_output: str, model: Type[T], query: str) -> str:
    """
    Builds a correction prompt that shows the LLM its bad output and
    the expected schema, so it can self-correct on retry.

    @param bad_output: The raw string the LLM returned incorrectly.
    @param model:      The Pydantic model the LLM should have returned.
    @param query:      Original user query for context.
    @returns:          Correction prompt string to send as the next user message.
    """
    schema = json.dumps(model.model_json_schema(), indent=2)
    return (
        f"Your previous response was WRONG.\n\n"
        f"You returned:\n{bad_output[:500]}\n\n"
        f"The user query was: \"{query}\"\n\n"
        f"You must return a JSON object matching this schema:\n{schema}\n\n"
        f"Return ONLY the JSON object. No markdown. No explanation. No lists."
    )


# ── Private ───────────────────────────────────────────────────────────────────

def _strip_fences(raw: str) -> str:
    """Removes markdown code fences (```json ... ``` or ``` ... ```)."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


def _parse_json(cleaned: str, original_raw: str) -> any:
    """Parses JSON string. Raises ValueError with context on failure."""
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM returned invalid JSON: {exc}\n"
            f"Raw output (first 300 chars): '{original_raw[:300]}'"
        ) from exc


def _check_shape(parsed: any, query: str, model: Type[T]) -> None:
    """
    Validates the top-level JSON shape before hitting Pydantic.
    Catches the case where the LLM answers the query instead of classifying it.
    """
    if isinstance(parsed, list):
        raise ValueError(
            f"LLM returned a list ({len(parsed)} items) instead of a "
            f"{model.__name__} object. "
            f"The LLM answered the query instead of classifying it. "
            f"Query: '{query}'"
        )
    if not isinstance(parsed, dict):
        raise ValueError(
            f"LLM returned type '{type(parsed).__name__}' — "
            f"expected a JSON object matching {model.__name__}."
        )


def _validate_model(parsed: dict, model: Type[T], raw: str) -> T:
    """Runs Pydantic model validation. Raises ValueError with context on failure."""
    try:
        return model.model_validate(parsed)
    except Exception as exc:
        raise ValueError(
            f"LLM output failed {model.__name__} schema validation: {exc}\n"
            f"Parsed dict: {json.dumps(parsed, default=str)[:300]}"
        ) from exc