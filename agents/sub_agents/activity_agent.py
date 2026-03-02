from agents.sub_agents.base_agent import BaseSubAgent

class ActivityAgent(BaseSubAgent):
    """
    Placeholder agent for activity.
    """
    def generate_query(self, user_query: str, context: dict = None) -> str:
        return "[]"
