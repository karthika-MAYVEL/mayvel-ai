from agents.sub_agents.base_agent import BaseSubAgent

class ResponseHistoryAgent(BaseSubAgent):
    """
    Placeholder agent for response_history.
    """
    def generate_query(self, user_query: str, context: dict = None) -> str:
        return "[]"
