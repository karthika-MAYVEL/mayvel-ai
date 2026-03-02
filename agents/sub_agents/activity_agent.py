# agents/sub_agents/activity_agent.py
# Activity sub-agent: generates MongoDB QueryTemplates for activity entities.

from agents.sub_agents.base_agent import BaseSubAgent


class ActivityAgent(BaseSubAgent):
    """
    Sub-agent for the 'activity' entity type.
    Default userfield: assignedTo; scheduleDate available for time filtering.
    """

    entity_type = "activity"

    def get_entity_type(self) -> str:
        return self.entity_type
