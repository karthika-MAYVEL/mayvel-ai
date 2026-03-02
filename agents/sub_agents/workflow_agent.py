from agents.sub_agents.base_agent import BaseSubAgent

class WorkflowAgent(BaseSubAgent):
    """
    Placeholder agent for workflow.
    """
    def generate_query(self, user_query: str, context: dict = None) -> str:
        return "[]"
