# agents/sub_agents/inspection_observation_agent.py
# InspectionObservation sub-agent: generates MongoDB QueryTemplates for inspectionObservation entities.

from agents.sub_agents.base_agent import BaseSubAgent


class InspectionObservationAgent(BaseSubAgent):
    """
    Sub-agent for the 'inspectionObservation' entity type.
    Chain-only: chained through execution → inspection.
    """

    entity_type = "inspectionObservation"

    def get_entity_type(self) -> str:
        return self.entity_type
