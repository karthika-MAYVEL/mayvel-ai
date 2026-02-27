from google import genai
from google.genai import types

from core.config import settings
from core.logger import get_app_logger

logger = get_app_logger("llm_sdk.gemini")

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

    def generate_json(self, prompt: str, system_instruction: str = "") -> str:
        """
        Generates structured JSON output from a given prompt.
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
            
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage = response.usage_metadata
                logger.info(f"[LLM Token Usage (JSON)] Input: {usage.prompt_token_count} | Output: {usage.candidates_token_count} | Total: {usage.total_token_count}")
            
            logger.info(f"LLM Response (JSON): {response.text}")
            return response.text
        except Exception as e:
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
