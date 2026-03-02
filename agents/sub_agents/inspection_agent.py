# agents/sub_agents/inspection_agent.py
# Inspection sub-agent: generates MongoDB QueryTemplates for inspection entities.

from agents.sub_agents.base_agent import BaseSubAgent


class InspectionAgent(BaseSubAgent):
    """
    Sub-agent for the 'inspection' entity type.
    Inherits all LLM orchestration and prompt assembly from BaseSubAgent.
    Entity-specific rules and schema are loaded from prompts/sub_agents/inspection.yaml.
    The inspection.yaml has a full section-based structure (security, role, context, etc.);
    the base class appends additional_rules + entity_schema from that file on top of the
    shared base sections.
    """

    entity_type = "inspection"

    def get_entity_type(self) -> str:
        return self.entity_type
