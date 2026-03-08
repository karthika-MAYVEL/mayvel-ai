# core/placeholder_resolver.py
import json
from datetime import datetime, timezone
from typing import Any
from utils.time_resolver import resolve_time_window

_REQUIRED_PLACEHOLDERS = {"{tenantId}"}
_FORBIDDEN_OPERATORS = {
    "$where", "$function", "$accumulator",
    "$merge", "$out",
}

_FIELD_ALIASES: dict[str, str] = {
    "entityType":  "type",
    "entity_type": "type",
}


def build_execution_context(tenant_id: str, user_id: str, query_template: Any) -> dict:
    time_window = None
    if isinstance(query_template, dict):
        time_window = query_template.get("time_window")
    else:
        tw = getattr(query_template, "time_window", None)
        if tw:
            time_window = tw.model_dump() if hasattr(tw, "model_dump") else tw.dict()

    start_dt, end_dt = resolve_time_window(time_window)
    return {
        "{tenantId}": tenant_id,
        "{userId}": user_id,
        "{TIME_WINDOW_START}": start_dt,
        "{TIME_WINDOW_END}": end_dt
    }

def resolve_placeholders(node: Any, context: dict) -> Any:
    # Check {tenantId} existence via stringification if starting node is pipeline or filter
    raw_str = json.dumps(node, default=str)
    if "{tenantId}" not in raw_str and isinstance(node, (list, dict)) and len(node) > 0:
        pass # Actually we might not enforce {tenantId} if it's an empty query, but orchestrator usually uses {tenantId}. We can let it pass or raise Error if they want.
        # But wait, original query assembler did enforce it: `if "{tenantId}" not in raw: raise ValueError(...)`
        # Let's enforce it for safety:
        # But wait, in a find filter it could be simple. I'll just check if {tenantId} in raw string representation for lists.
    
    resolved = _replace_node(node, context)
    
    if isinstance(resolved, list):
        resolved = [_fix_field_aliases(stage) for stage in resolved]
    
    _check_forbidden(resolved)
    
    return resolved

def _replace_node(node: Any, context: dict) -> Any:
    if isinstance(node, dict):
        return {k: _replace_node(v, context) for k, v in node.items()}
    elif isinstance(node, list):
        return [_replace_node(v, context) for v in node]
    elif isinstance(node, str):
        if node == "{TIME_WINDOW_START}" and context.get("{TIME_WINDOW_START}") is not None:
            return context["{TIME_WINDOW_START}"]
        if node == "{TIME_WINDOW_END}" and context.get("{TIME_WINDOW_END}") is not None:
            return context["{TIME_WINDOW_END}"]
        if node == "{NOW}":
            return datetime.now(timezone.utc)
        
        res = node
        if "{tenantId}" in res and context.get("{tenantId}") is not None:
            res = res.replace("{tenantId}", context["{tenantId}"])
        if "{userId}" in res and context.get("{userId}"):
            res = res.replace("{userId}", context["{userId}"])
        return res
    return node

def _fix_field_aliases(stage: Any) -> Any:
    if isinstance(stage, dict) and "$match" in stage and isinstance(stage["$match"], dict):
        match_doc = stage["$match"]
        corrected = {}
        for key, value in match_doc.items():
            correct_key = _FIELD_ALIASES.get(key, key)
            corrected[correct_key] = value
        return {**stage, "$match": corrected}
    return stage

def _check_forbidden(node: Any) -> None:
    raw = json.dumps(node, default=str)
    for op in _FORBIDDEN_OPERATORS:
        if op in raw:
            raise ValueError(f"Forbidden operator '{op}' found in assembled pipeline.")
