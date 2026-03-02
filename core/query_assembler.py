# core/query_assembler.py
# Assembler: resolves placeholder strings in a QueryTemplate pipeline
# and returns the executable pipeline with real session values.

import json
from datetime import datetime, timezone
from typing import Any


_REQUIRED_PLACEHOLDERS = {"{tenantId}"}
_FORBIDDEN_OPERATORS = {
    "$where", "$function", "$accumulator",
    "$merge", "$out",
}


def resolve(pipeline: list, *, tenant_id: str, user_id: str) -> list:
    """
    Replaces {tenantId}, {userId}, and {NOW} placeholders in a pipeline
    and validates that no forbidden operators are present.

    @param pipeline: List of MongoDB pipeline stage dicts.
    @param tenant_id: Real tenant UUID to inject.
    @param user_id: Real user UUID to inject.
    @returns: A new pipeline list with all placeholders resolved.
    @throws ValueError: If forbidden operators are found or {tenantId} was not present.
    """
    raw = json.dumps(pipeline)

    if "{tenantId}" not in raw:
        raise ValueError("Pipeline is missing the required '{tenantId}' placeholder.")

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    resolved = (
        raw
        .replace("{tenantId}", tenant_id)
        .replace("{userId}", user_id)
        .replace("{NOW}", now_iso)
    )

    result = json.loads(resolved)
    _check_forbidden(result)
    return result


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
