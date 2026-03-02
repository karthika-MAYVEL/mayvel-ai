# agents/sub_agents/task_observation_agent.py
# TaskObservation sub-agent: generates MongoDB QueryTemplates for taskObservation entities.

from agents.sub_agents.base_agent import BaseSubAgent


class TaskObservationAgent(BaseSubAgent):
    """
    Sub-agent for the 'taskObservation' entity type.
    Chain-only: chained through task → execution → inspection.
    """

    entity_type = "taskObservation"

    def get_entity_type(self) -> str:
        return self.entity_type
