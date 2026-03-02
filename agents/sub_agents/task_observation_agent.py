from agents.sub_agents.base_agent import BaseSubAgent

class TaskObservationAgent(BaseSubAgent):
    """
    Placeholder agent for task_observation.
    """
    def generate_query(self, user_query: str, context: dict = None) -> str:
        return "[]"
