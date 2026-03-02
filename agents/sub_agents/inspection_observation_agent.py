from agents.sub_agents.base_agent import BaseSubAgent

class InspectionObservationAgent(BaseSubAgent):
    """
    Placeholder agent for inspection_observation.
    """
    def generate_query(self, user_query: str, context: dict = None) -> str:
        return "[]"
