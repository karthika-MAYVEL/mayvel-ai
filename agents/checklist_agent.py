import os
import yaml

from core.logger import get_app_logger
from llm_sdk.gemini import GeminiClient

logger = get_app_logger("agent.checklist")

class ChecklistAgent:
    """
    Agent responsible for translating natural language queries about checklists
    into valid MongoDB aggregation pipelines based on authorized schema templates.
    """
    
    def __init__(self):
        """
        Initializes the ChecklistAgent, loads instructions from prompts.yaml,
        and setting up the GenAI client using the configured API key.
        """
        # Load prompt from config
        config_path = os.path.join(os.path.dirname(__file__), "..", "knowledge", "prompts", "prompts.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        self.system_instruction = config.get("system", {}).get("checklist_agent", "")
        self.llm = GeminiClient()

    def generate_query(self, user_query: str) -> str:
        """
        Generates a MongoDB query string from natural language.
        
        Args:
            user_query (str): The natural language string from the user.
            
        Returns:
            str: A raw JSON string containing the MongoDB aggregation pipeline.
        """
        logger.info(f"Checklist Agent triggered for query: '{user_query}'")
        if not self.llm.client:
            # Fallback for local testing
            return '[{"$match": {"tenantId": "{tenantId}"}}]'

        try:
            response_text = self.llm.generate_json(prompt=user_query, system_instruction=self.system_instruction)
            print("checklist agent response", response_text)
            logger.info("Checklist Agent pipeline generated successfully.")
            return response_text
        except Exception as e:
            logger.error(f"Error in ChecklistAgent: {e}")
            return "[]"

if __name__ == "__main__":
    agent = ChecklistAgent()
    print("Mock Output:", agent.generate_query("Show me fire safety checklists"))
