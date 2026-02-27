import os
import ast
import json
from pydantic import BaseModel, Field

from core.logger import get_app_logger
from llm_sdk.gemini import GeminiClient

logger = get_app_logger("agent.root")
llm = GeminiClient()

class IntentClassification(BaseModel):
    intent: str = Field(..., description="The classified primary intent, must be 'Checklist', 'Inspection', or 'Sequential'")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score of the classification from 0.0 to 1.0")
    reasoning: str = Field(..., description="Short explanation of why this intent was chosen")

def classify_intent(user_query: str) -> IntentClassification:
    """
    Acts as the Root Agent (Gateway) to classify user intent.
    Routes to 'Inspection', 'Checklist', or 'Sequential' sub-agents.
    
    Args:
        user_query (str): The natural language query from the user.
        
    Returns:
        IntentClassification: The classified intent with confidence and reasoning.
    """
    system_instruction = """
    You are the Root Routing Agent for 'Ask Seyo', a inspection and audit management platform.
    Your job is to read the user's query and classify the primary intent into one of the following domains:
    
    1. 'Checklist': The user is asking about templates, checklist structures, or generic forms (e.g., "Show me fire safety checklists", "What is the daily site template?").
    2. 'Inspection': The user is asking about specific events, filled-out forms, or past occurrences (e.g., "Show me recent failed inspections for fire safety", "Find inspections with rejected statuses").
    3. 'Sequential': The user is asking a complex query that involves finding a checklist first, then finding related inspections (e.g., "Show me all inspections for the fire safety checklist").

    Return a JSON object with:
    - intent: String (must be 'Checklist', 'Inspection', or 'Sequential')
    - confidence: Float (0.0 to 1.0)
    - reasoning: String (Short explanation of why you chose this intent)
    """

    if not llm.client:
        # Fallback for local testing without an API key
        intent = "Checklist"
        if "inspection" in user_query.lower():
            if "checklist" in user_query.lower():
                intent = "Sequential"
            else:
                intent = "Inspection"
        return IntentClassification(intent=intent, confidence=0.9, reasoning="Mock fallback")

    try:
        response_text = llm.generate_json(prompt=user_query, system_instruction=system_instruction)
        print("root agent response", response_text)
        
        if not response_text:
             raise ValueError("Empty response from LLM")
             
        # Parse the JSON string
        result_dict = json.loads(response_text)
        logger.info(f"Root Agent successfully classified intent as '{result_dict.get('intent')}' with confidence {result_dict.get('confidence')}")
        return IntentClassification(**result_dict)
    except Exception as e:
        logger.error(f"Error classifying intent: {e}")
        return IntentClassification(intent="Unknown", confidence=0.0, reasoning=str(e))

if __name__ == "__main__":
    # Test cases
    queries = [
        "Show me all fire safety checklists",
        "Find me all failed inspections related to scaffolding",
        "Show me all inspections for the fire safety checklist"
    ]
    for q in queries:
        res = classify_intent(q)
        print(f"Query: {q}\nIntent: {res.intent} (Confidence: {res.confidence})\nReasoning: {res.reasoning}\n")
