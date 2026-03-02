from agents.sub_agents.base_agent import BaseSubAgent

class ProjectionAgent(BaseSubAgent):
    """
    Placeholder agent for projection.
    """
    def generate_query(self, user_query: str, context: dict = None) -> str:
        return "[]"
