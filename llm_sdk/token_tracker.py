# llm_sdk/token_tracker.py
# Per-request LLM token accumulator using async context variables.
# Each call to add_tokens() accumulates into the current request's counter;
# the orchestrator calls get_totals() at the end and resets for the next request.

from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """Running totals for one request."""
    prompt_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens


_bucket: ContextVar[TokenBucket] = ContextVar("llm_token_bucket")


def reset() -> TokenBucket:
    """
    Creates a fresh TokenBucket for the current async context (call at request start).

    @returns: The new empty bucket.
    """
    bucket = TokenBucket()
    _bucket.set(bucket)
    return bucket


def add_tokens(prompt: int, output: int) -> None:
    """
    Adds token counts from one LLM call to the current request's bucket.

    @param prompt: Input token count for this call.
    @param output: Output token count for this call.
    """
    try:
        b = _bucket.get()
        b.prompt_tokens += prompt
        b.output_tokens += output
        b.calls += 1
    except LookupError:
        pass  # No context set (e.g. called outside a request) — silently skip


def get_totals() -> dict:
    """
    Returns the accumulated token counts for the current request.

    @returns: Dict with prompt_tokens, output_tokens, total_tokens, llm_calls.
    """
    try:
        b = _bucket.get()
        return {
            "prompt_tokens": b.prompt_tokens,
            "output_tokens": b.output_tokens,
            "total_tokens":  b.total_tokens,
            "llm_calls":     b.calls,
        }
    except LookupError:
        return {"prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llm_calls": 0}
