# utils/placeholder_resolver.py
# Resolves runtime placeholders in a MongoDB aggregation pipeline.
#
# Responsibilities:
#   1. Inject {tenantId}, {userId}, {TIME_WINDOW_START}, {TIME_WINDOW_END}
#   2. Enforce {tenantId} presence — hard failure if missing (tenant isolation)
#   3. Enforce isDeleted: false in every $match stage (soft-delete safety)
#   4. Enforce field aliases (entityType → type) across ALL pipeline stages
#   5. Block forbidden MongoDB operators
#
# executor.py is superseded by this file and must be deleted.

import json
from datetime import datetime, timezone
from typing import Any

from utils.time_resolver import resolve_time_window
from utils.logger import get_app_logger

logger = get_app_logger("placeholder_resolver")

_FORBIDDEN_OPERATORS = {
    "$where", "$function", "$accumulator", "$merge", "$out",
}

# Field name corrections — LLM sometimes uses wrong names.
# Applied to $match, $project, $group, $sort, $addFields across all stages.
_FIELD_ALIASES: dict[str, str] = {
    "entityType":  "type",
    "entity_type": "type",
}


# ── Public API ────────────────────────────────────────────────────────────────

def build_execution_context(
    tenant_id: str,
    user_id: str,
    query_template: Any,
) -> dict:
    """
    Builds the placeholder substitution context from runtime values.

    @param tenant_id:      Tenant UUID from the request.
    @param user_id:        User UUID from the request.
    @param query_template: QueryTemplate — used to extract time_window.
    @returns:              Dict mapping placeholder strings to runtime values.
    """
    time_window = _extract_time_window(query_template)
    start_dt, end_dt = resolve_time_window(time_window)

    return {
        "{tenantId}":          tenant_id,
        "{userId}":            user_id,
        "{TIME_WINDOW_START}": start_dt,
        "{TIME_WINDOW_END}":   end_dt,
    }


def resolve_placeholders(pipeline: list, context: dict) -> list:
    """
    Resolves all placeholders in a pipeline and enforces safety rules.

    Steps (in order):
      1. Enforce {tenantId} is present in the pipeline
      2. Substitute all placeholder values
      3. Enforce isDeleted: false in every $match stage
      4. Fix field aliases across all pipeline stages
      5. Block forbidden operators

    @param pipeline: MongoDB aggregation pipeline with placeholder strings.
    @param context:  Substitution context from build_execution_context().
    @returns:        Resolved, safe, executable pipeline.
    @raises ValueError: If {tenantId} is missing or a forbidden operator is found.
    """
    _enforce_tenant_isolation(pipeline)
    resolved = _replace_node(pipeline, context)
    resolved = [_enforce_is_not_deleted(stage) for stage in resolved]
    resolved = [_fix_field_aliases(stage) for stage in resolved]
    _check_forbidden(resolved)
    return resolved


# ── Private — substitution ────────────────────────────────────────────────────

def _replace_node(node: Any, context: dict) -> Any:
    """Recursively substitutes placeholder strings with runtime values."""
    if isinstance(node, dict):
        return {k: _replace_node(v, context) for k, v in node.items()}

    if isinstance(node, list):
        return [_replace_node(v, context) for v in node]

    if isinstance(node, str):
        # Exact-match placeholders replaced with typed values (datetime, etc.)
        if node in ("{TIME_WINDOW_START}", "{TIME_WINDOW_END}", "{NOW}"):
            if node == "{NOW}":
                return datetime.now(timezone.utc)
            return context.get(node, node)

        # String placeholders replaced inline
        result = node
        if "{tenantId}" in result and context.get("{tenantId}"):
            result = result.replace("{tenantId}", context["{tenantId}"])
        if "{userId}" in result and context.get("{userId}"):
            result = result.replace("{userId}", context["{userId}"])
        return result

    return node


# ── Private — safety enforcement ──────────────────────────────────────────────

def _enforce_tenant_isolation(pipeline: list) -> None:
    """
    Raises if {tenantId} is not present anywhere in the pipeline.
    Every query must be scoped to a tenant — this is non-negotiable.
    """
    raw = json.dumps(pipeline, default=str)
    if "{tenantId}" not in raw:
        raise ValueError(
            "Pipeline is missing {tenantId} placeholder. "
            "All queries must be tenant-scoped. "
            "Check the T2 agent prompt to ensure tenantId is always included."
        )


def _enforce_is_not_deleted(stage: Any) -> Any:
    """
    Injects isDeleted: false into every $match stage.
    Ensures soft-deleted documents never appear in results.
    """
    if isinstance(stage, dict) and "$match" in stage:
        match = stage["$match"]
        if isinstance(match, dict):
            match["isDeleted"] = False
    return stage


def _fix_field_aliases(stage: Any) -> Any:
    """
    Corrects LLM field name mistakes across ALL operator stages.
    e.g. 'entityType' → 'type' in $match, $project, $group, $sort, $addFields.
    """
    if not isinstance(stage, dict):
        return stage

    correctable_operators = {"$match", "$project", "$group", "$sort", "$addFields"}
    result = {}

    for operator, body in stage.items():
        if operator in correctable_operators and isinstance(body, dict):
            result[operator] = {
                _FIELD_ALIASES.get(k, k): v for k, v in body.items()
            }
        else:
            result[operator] = body

    return result


def _check_forbidden(pipeline: list) -> None:
    """
    Blocks forbidden MongoDB operators by inspecting pipeline stage keys.
    Uses structural traversal — not string search — to avoid false positives
    on field values that happen to contain operator-like strings.
    """
    _check_node_forbidden(pipeline)


def _check_node_forbidden(node: Any) -> None:
    if isinstance(node, dict):
        for key in node:
            if key in _FORBIDDEN_OPERATORS:
                raise ValueError(
                    f"Forbidden MongoDB operator '{key}' found in pipeline. "
                    f"This operator is not permitted for security reasons."
                )
        for value in node.values():
            _check_node_forbidden(value)
    elif isinstance(node, list):
        for item in node:
            _check_node_forbidden(item)


# ── Private — helpers ─────────────────────────────────────────────────────────

def _extract_time_window(query_template: Any) -> dict | None:
    """Safely extracts time_window from a QueryTemplate or raw dict."""
    if isinstance(query_template, dict):
        return query_template.get("time_window")
    tw = getattr(query_template, "time_window", None)
    if tw is None:
        return None
    return tw.model_dump() if hasattr(tw, "model_dump") else dict(tw)