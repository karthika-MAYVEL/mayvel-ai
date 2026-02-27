import os
import json

from core.config import settings
from llm_sdk.gemini import GeminiClient
from core.logger import get_app_logger

logger = get_app_logger("service.synthesizer")

class ResponseSynthesizer:
    """
    Synthesizer service that converts technical JSON Database results 
    into a conversational natural language response.
    """
    
    def __init__(self):
        """
        Initializes the Synthesizer with the shared GeminiClient SDK wrapper.
        """
        self.llm = GeminiClient()

    def synthesize_stream(self, original_query: str, db_results: dict):
        """
        Takes the user's original query and the JSON results from the database.
        Streams back a natural language summary.
        
        Args:
            original_query (str): The natural language query from the user.
            db_results (dict): The consolidated JSON payload from the database execution.
            
        Yields:
            str: Chunks of the natural language response stream.
        """
        system_instruction = """
        You are the 'Ask Seyo' Results Synthesizer.
        Your job is to read the raw JSON results returned from the Seyo database
        and provide a concise, helpful natural language response to the user's original query.
        Translate complex data (like "Rejected" statuses or timestamps) into helpful summaries 
        for Site Managers and Safety Leaders.
        """

        prompt = f"Original Query: {original_query}\n\nDatabase Results:\n{json.dumps(db_results, indent=2, default=str)}"

        try:
            logger.info("Streaming natural language response from LLM payload via SDK...")
            # Forward the call to the generic LLM SDK
            for chunk in self.llm.stream_content(prompt=prompt, system_instruction=system_instruction):
                yield chunk
        except Exception as e:
            yield f"Error synthesizing response: {e}"

if __name__ == "__main__":
    synthesizer = ResponseSynthesizer()
    print("Streaming Mock Output:", end=" ")
    for chunk in synthesizer.synthesize_stream("Show me failed inspections", {"results": [{"id": 1, "status": "failed"}]}):
        print(chunk, end="", flush=True)
    print()
