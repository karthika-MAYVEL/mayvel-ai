# core/query_assembler.py
# Assembler: resolves placeholder strings in a QueryTemplate pipeline
# and returns the executable pipeline with real session values.
# Also sanitises known LLM field-mapping errors before execution.

import json
from datetime import datetime, timezone
from typing import Any


_REQUIRED_PLACEHOLDERS = {"{tenantId}"}
_FORBIDDEN_OPERATORS = {
    "$where", "$function", "$accumulator",
    "$merge", "$out",
}

# Field names the LLM sometimes generates that do not exist in the DB.
# Maps wrong_name → correct_name for automatic replacement in $match stages.
_FIELD_ALIASES: dict[str, str] = {
    "entityType":  "type",   # LLM hallucinates "entityType" — correct field is "type"
    "entity_type": "type",   # snake_case variant of the same mistake
}


def resolve(pipeline: list, *, tenant_id: str, user_id: str) -> list:
    """
    Resolves {tenantId}, {userId}, and {NOW} placeholders, sanitises
    known bad field names, then validates no forbidden operators remain.

    @param pipeline: List of MongoDB pipeline stage dicts.
    @param tenant_id: Real tenant UUID to inject.
    @param user_id: Real user UUID to inject.
    @returns: A new pipeline list with all placeholders resolved and field
              aliases corrected.
    @throws ValueError: If forbidden operators are found or {tenantId} was
                        not present before resolution.
    """
    raw = json.dumps(pipeline)

    if "{tenantId}" not in raw:
        raise ValueError("Pipeline is missing the required '{tenantId}' placeholder.")

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    resolved_str = (
        raw
        .replace("{tenantId}", tenant_id)
        .replace("{userId}", user_id)
        .replace("{NOW}", now_iso)
    )

    result = json.loads(resolved_str)
    result = _fix_field_aliases(result)
    _check_forbidden(result)
    return result


def _fix_field_aliases(pipeline: list) -> list:
    """
    Walks every $match stage in the pipeline and replaces known LLM
    field-name mistakes with the correct DB field name.

    E.g.  { "entityType": "inspection" }  →  { "type": "inspection" }

    Only touches top-level keys inside $match — does not recurse into
    nested operators to avoid false positives.

    @param pipeline: Resolved pipeline list.
    @returns: Pipeline with field aliases corrected in-place (new list).
    """
    fixed = []
    for stage in pipeline:
        if not isinstance(stage, dict):
            fixed.append(stage)
            continue

        if "$match" in stage and isinstance(stage["$match"], dict):
            match_doc = stage["$match"]
            corrected = {}
            for key, value in match_doc.items():
                correct_key = _FIELD_ALIASES.get(key, key)
                corrected[correct_key] = value
            fixed.append({"$match": corrected})
        else:
            fixed.append(stage)

    return fixed


def _check_forbidden(pipeline: list) -> None:
    """
    Recursively scans the pipeline for forbidden operators.

    @param pipeline: Resolved pipeline list.
    @throws ValueError: If a forbidden operator key is found.
    """
    raw = json.dumps(pipeline)
    for op in _FORBIDDEN_OPERATORS:
        if op in raw:
            raise ValueError(f"Forbidden operator '{op}' found in assembled pipeline.")
