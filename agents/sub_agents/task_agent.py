from agents.sub_agents.base_agent import BaseSubAgent

class TaskAgent(BaseSubAgent):
    """
    Placeholder agent for task.
    """
    def generate_query(self, user_query: str, context: dict = None) -> str:
        return "[]"
