from google import genai
from google.genai import types

from config.settings import settings
from core.logger import get_app_logger
from llm_sdk.tracer import write_trace
import llm_sdk.token_tracker as token_tracker

logger = get_app_logger("llm_sdk.gemini")

# Truncation limit for inline log display
_INLINE_CHARS = 120


def _log_agent_call(
    agent: str,
    prompt: str,
    response_text: str,
    usage: dict | None,
) -> None:
    """
    Emits a single compact log line per LLM agent call showing:
    agent name, truncated input, truncated output, and token counters.

    @param agent: Agent identifier (e.g. 'root', 'inspection').
    @param prompt: User-turn string sent to the LLM.
    @param response_text: Raw LLM response string.
    @param usage: Token usage dict or None.
    """
    short_in  = (prompt[:_INLINE_CHARS] + "…") if len(prompt) > _INLINE_CHARS else prompt
    short_out = (response_text[:_INLINE_CHARS] + "…") if len(response_text) > _INLINE_CHARS else response_text
    token_str = (
        f"in={usage['prompt_tokens']} out={usage['output_tokens']} total={usage['total_tokens']}"
        if usage else "tokens=n/a"
    )
    logger.info(
        f"[AGENT:{agent.upper()}] "
        f"INPUT: {short_in!r} | "
        f"OUTPUT: {short_out!r} | "
        f"TOKENS: {token_str}"
    )

class GeminiClient:
    """
    SDK wrapper for the Google GenAI (Gemini) API.
    Handles initializing the client and exposing universal generation commands
    to keep agents agnostic of the underlying HTTP mechanics.
    """
    def __init__(self):
        self.api_key = settings.LLM_API_KEY
        
        if self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
                logger.info("Successfully initialized Gemini SDK Client.")
            except Exception as e:
                self.client = None
                logger.error(f"Failed to initialize Gemini SDK Client: {e}")
        else:
            self.client = None
            logger.warning("No valid LLM_API_KEY provided. Gemini SDK Client running in mock mode.")

    def generate_json(self, prompt: str, system_instruction: str = "", agent: str = "unknown") -> str:
        """
        Generates structured JSON output from a given prompt.

        @param prompt: User-turn content.
        @param system_instruction: System prompt sent to the LLM.
        @param agent: Caller identifier written to the trace file.
        """
        if not self.client:
            logger.warning("Mocking generate_json call due to missing API key")
            return "[]"

        try:
            response = self.client.models.generate_content(
                model=settings.LLM_MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                )
            )
            
            logger.info(f"{agent}response: {response.text}")

            usage = None
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                u = response.usage_metadata
                usage = {
                    "prompt_tokens":  u.prompt_token_count,
                    "output_tokens":  u.candidates_token_count,
                    "total_tokens":   u.total_token_count,
                }
            if usage:
                token_tracker.add_tokens(usage["prompt_tokens"], usage["output_tokens"])
            _log_agent_call(agent, prompt, response.text, usage)

            write_trace(
                agent=agent,
                model=settings.LLM_MODEL_NAME,
                system_prompt=system_instruction,
                user_message=prompt,
                response=response.text,
                token_usage=usage,
            )
            return response.text
        except Exception as e:
            write_trace(
                agent=agent,
                model=settings.LLM_MODEL_NAME,
                system_prompt=system_instruction,
                user_message=prompt,
                response="",
                error=str(e),
            )
            logger.error(f"Gemini API Error (generate_json): {e}")
            raise e
            
    def generate_text(self, prompt: str, system_instruction: str = "") -> str:
        """
        Generates standard text output from a given prompt.
        """
        if not self.client:
            return "Mock Text Response"

        try:
            response = self.client.models.generate_content(
                model=settings.LLM_MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction
                )
            )
            
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage = response.usage_metadata
                logger.info(f"[LLM Token Usage (Text)] Input: {usage.prompt_token_count} | Output: {usage.candidates_token_count} | Total: {usage.total_token_count}")
            
            logger.info(f"LLM Response (Text): {response.text}")
            return response.text
        except Exception as e:
            logger.error(f"Gemini API Error (generate_text): {e}")
            raise e

    def stream_content(self, prompt: str, system_instruction: str = ""):
        """
        Yields text chunks progressively as they stream back from the LLM.
        """
        if not self.client:
            # Fallback for local testing and mocking
            mock_words = f"Based on your query, here is a mock streamed response.".split()
            for chunk in mock_words:
                yield chunk + " "
            return

        try:
            response = self.client.models.generate_content_stream(
                model=settings.LLM_MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction
                )
            )
            
            full_response = ""
            for chunk in response:
                if chunk.text:
                    full_response += chunk.text
                    yield chunk.text
                if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                    usage = chunk.usage_metadata
                    logger.info(f"[LLM Token Usage (Stream)] Input: {usage.prompt_token_count} | Output: {usage.candidates_token_count} | Total: {usage.total_token_count}")
            
            logger.info(f"LLM Response (Stream): {full_response}")
        except Exception as e:
            logger.error(f"Gemini API Error (stream_content): {e}")
            yield f"Error synthesizing response from upstream AI provider: {e}"
