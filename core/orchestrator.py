import json
import asyncio

from agents.root_agent import classify_intent
from agents.checklist_agent import ChecklistAgent
from agents.inspection_agent import InspectionAgent
from core.logger import get_app_logger

logger = get_app_logger("orchestrator")

class SearchOrchestrator:
    """
    The main Orchestrator entry point for the Search system.
    Receives the request, moves it to the Root Agent for planning (intent classification),
    and then manages the execution handovers to the specialized Sub-Agents.
    """
    def __init__(self):
        self.checklist_agent = ChecklistAgent()
        self.inspection_agent = InspectionAgent()

    async def execute_search(self, user_query: str, db=None, executor=None) -> dict:
        """
        Orchestrates the resolution of a user query.
        1. Planning: Passes query to Root Agent.
        2. Execution: Delegates to the appropriate Sub-Agent (or handles Sequential flow).
        
        Args:
            user_query (str): The natural language query from the user.
            db: Current MongoDB database instance.
            executor: QueryExecutor instance for security sanitization.
            
        Returns:
            dict: The orchestration result containing the final database pipelines.
        """
        logger.info(f"Orchestrator handling query handover: '{user_query}'")
        
        # Planning Phase: Root Agent decides the intent
        classification = classify_intent(user_query)
        intent = classification.intent
        logger.info(f"Root Agent Plan: Classified intent as '{intent}' (Confidence: {classification.confidence})")

        response_data = {
            "intent": intent,
            "queries": [],
            "messages": []
        }

        # Execution Phase
        if intent == "Checklist":
            # Delegate to Checklist Agent
            logger.info("Delegating execution to Checklist Sub-Agent.")
            query_str = self.checklist_agent.generate_query(user_query)
            try:
                parsed_query = json.loads(query_str)
                pipe = parsed_query.get("pipeline", parsed_query) if isinstance(parsed_query, dict) else parsed_query
                if isinstance(pipe, dict): pipe = [pipe]
                response_data["queries"].append({"collection": "checklists", "pipeline": pipe})
            except json.JSONDecodeError:
                response_data["messages"].append("Failed to parse Checklist Agent query.")
                response_data["queries"].append({"collection": "checklists", "pipeline": query_str})

        elif intent == "Inspection":
            # Delegate to Inspection Agent
            logger.info("Delegating execution to Inspection Sub-Agent.")
            query_str = self.inspection_agent.generate_query(user_query)
            try:
                parsed_query = json.loads(query_str)
                pipe = parsed_query.get("pipeline", parsed_query) if isinstance(parsed_query, dict) else parsed_query
                if isinstance(pipe, dict): pipe = [pipe]
                response_data["queries"].append({"collection": "inspections", "pipeline": pipe})
            except json.JSONDecodeError:
                response_data["messages"].append("Failed to parse Inspection Agent query.")
                response_data["queries"].append({"collection": "inspections", "pipeline": query_str})

        elif intent == "Sequential":
            # Sequential Execution
            logger.info("Orchestrator starting Sequential Intent execution: Dispatching to Checklist Agent first.")
            checklist_query_str = self.checklist_agent.generate_query(user_query)
            
            try:
                parsed_checklist_query = json.loads(checklist_query_str)
                c_pipe = parsed_checklist_query.get("pipeline", parsed_checklist_query) if isinstance(parsed_checklist_query, dict) else parsed_checklist_query
                if isinstance(c_pipe, dict): c_pipe = [c_pipe]
                response_data["queries"].append({"collection": "checklists", "pipeline": c_pipe})
                
                context = {}
                if db is not None and executor is not None:
                    safe_pipe = executor.prepare_query(c_pipe)
                    cursor = db["checklists"].aggregate(safe_pipe)
                    checklists = await cursor.to_list(length=1)
                    if checklists:
                        found_id = str(checklists[0].get("_id", ""))
                        context = {"checklistId": found_id}
                        response_data["messages"].append(f"Executed checklist query. Found checklistId: {found_id}")
                    else:
                        response_data["messages"].append("Executed checklist query. No checklist found.")
                else:
                    mock_checklist_id = "mock_checklist_id_123"
                    context = {"checklistId": mock_checklist_id}
                    response_data["messages"].append(f"Mock executed checklist query. Found checklistId: {mock_checklist_id}")
                
                logger.info(f"Orchestrator Handover to Inspection Agent with context: {context}")
                inspection_query_str = self.inspection_agent.generate_query(user_query, context=context)
                
                parsed_inspection_query = json.loads(inspection_query_str)
                i_pipe = parsed_inspection_query.get("pipeline", parsed_inspection_query) if isinstance(parsed_inspection_query, dict) else parsed_inspection_query
                if isinstance(i_pipe, dict): i_pipe = [i_pipe]
                response_data["queries"].append({"collection": "inspections", "pipeline": i_pipe})
                
            except json.JSONDecodeError:
                response_data["messages"].append("Failed to parse sequential queries.")
            except Exception as e:
                response_data["messages"].append(f"Execution failed during sequential router step: {e}")

        else:
            response_data["messages"].append("Unknown intent. Cannot route.")

        return response_data

if __name__ == "__main__":
    async def test():
        orchestrator = SearchOrchestrator()
        result = await orchestrator.execute_search("Show me all inspections for the fire safety checklist")
        print(json.dumps(result, indent=2))
        
    asyncio.run(test())
