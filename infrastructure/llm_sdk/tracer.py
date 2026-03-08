# llm_sdk/tracer.py
# LlmTracer: writes every LLM call (agent, system prompt, user message, response) to
# a rotating daily JSONL file at logs/llm_trace_YYYY-MM-DD.jsonl

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOG_DIR = Path(__file__).parent.parent / "logs"
_lock = threading.Lock()


def _trace_file() -> Path:
    """Returns today's trace file path, creating the logs/ dir if needed."""
    _LOG_DIR.mkdir(exist_ok=True)
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return _LOG_DIR / f"llm_trace_{date_str}.jsonl"


def write_trace(
    *,
    agent: str,
    system_prompt: str,
    user_message: str,
    response: str,
    model: str = "",
    token_usage: dict | None = None,
    error: str | None = None,
) -> None:
    """
    Appends one JSON record to today's trace file.

    @param agent: Identifier for the agent making the call (e.g. 'checklist', 'root').
    @param system_prompt: Full system instruction sent to the LLM.
    @param user_message: User-turn content sent to the LLM.
    @param response: Raw text response from the LLM.
    @param model: Model name used.
    @param token_usage: Dict with prompt_tokens, output_tokens, total_tokens.
    @param error: Error message if the call failed.
    """
    record = {
        "ts":           datetime.now(tz=timezone.utc).isoformat(),
        "agent":        agent,
        "model":        model,
        "system_prompt": system_prompt,
        "user_message": user_message,
        "response":     response,
        "token_usage":  token_usage or {},
        "error":        error,
    }
    with _lock:
        with _trace_file().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
