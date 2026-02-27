import os
import yaml

from core.logger import get_app_logger
from llm_sdk.gemini import GeminiClient

logger = get_app_logger("agent.inspection")

class InspectionAgent:
    """
    Agent responsible for translating natural language queries about inspections
    into valid MongoDB aggregation pipelines based on authorized schema templates.
    """
    
    def __init__(self):
        """
        Initializes the InspectionAgent, loads instructions from prompts.yaml,
        and setting up the GenAI client using the configured API key.
        """
        # Load prompt from config
        config_path = os.path.join(os.path.dirname(__file__), "..", "knowledge", "prompts", "inspection_prompts.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
            
        # Load schema
        schema_path = os.path.join(os.path.dirname(__file__), "..", "knowledge", "schema", "inspection_schema.md")
        with open(schema_path, "r") as f:
            schema_content = f.read()

        # Build system instruction from template
        template = config.get("templates", {}).get("inspection_query", {})
        section_names = template.get("sections", [])
        
        instruction_parts = []
        for sec_name in section_names:
            content = config.get("sections", {}).get(sec_name, {}).get("content", "")
            if content:
                instruction_parts.append(content)
        
        footer = template.get("footer", "")
        if footer:
            instruction_parts.append(footer)
            
        raw_instruction = "\n\n".join(instruction_parts)
        
        # Inject variables
        db_name = config.get("config", {}).get("database", "seyo-development")
        self.system_instruction = raw_instruction.replace("{SCHEMA}", schema_content).replace("{DB}", db_name)
        
        self.llm = GeminiClient()

    def generate_query(self, user_query: str, context: dict = None) -> str:
        """
        Takes the user query (and optional context like a checklistId) and 
        generates a JSON MongoDB aggregation pipeline for the 'inspections' collection.
        
        Args:
            user_query (str): The natural language string from the user.
            context (dict, optional): Additional context to inject into prompt.
            
        Returns:
            str: A raw JSON string containing the MongoDB aggregation pipeline.
        """
        logger.info(f"Inspection Agent triggered for query. Context present: {bool(context)}")
        prompt = user_query
        if context:
            prompt += f"\n\nAdditional Context from previous steps: {context}"

        if not self.llm.client:
            # Fallback for local testing
            if context and "checklistId" in context:
                return f'[{{"$match": {{"tenantId": "{{tenantId}}", "checklistId": "{context["checklistId"]}"}}}}]'
            return '[{"$match": {"tenantId": "{tenantId}"}}]'

        try:
            response_text = self.llm.generate_json(prompt=prompt, system_instruction=self.system_instruction)
            print("inspection agent response", response_text)
            logger.info("Inspection Agent pipeline generated successfully.")
            return response_text
        except Exception as e:
            logger.error(f"Error generating Inspection query: {e}")
            return f"[]"

if __name__ == "__main__":
    agent = InspectionAgent()
    print("Mock Output:", agent.generate_query("Show me failed inspections"))
