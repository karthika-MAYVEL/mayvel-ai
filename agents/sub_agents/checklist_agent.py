# agents/sub_agents/checklist_agent.py
# Checklist sub-agent: generates MongoDB QueryTemplates for checklist entities.

from agents.sub_agents.base_agent import BaseSubAgent


class ChecklistAgent(BaseSubAgent):
    """
    Sub-agent for the 'checklist' entity type.
    Inherits all LLM orchestration and prompt assembly from BaseSubAgent.
    Entity-specific rules and schema are loaded from prompts/sub_agents/checklist.yaml.
    """

    entity_type = "checklist"

    def get_entity_type(self) -> str:
        return self.entity_type
