# agents/sub_agents/template_agent.py
# TemplateGroupAgent: T2 domain agent for the TEMPLATE group.
# Entities: checklist, section, question, responseValues

from agents.sub_agents.domain_base_agent import DomainBaseAgent


class TemplateGroupAgent(DomainBaseAgent):
    """
    T2 domain agent for the TEMPLATE group.

    Handles all queries about the content definition layer:
    checklists, sections, questions, responseValues.

    Entity-specific rules and merged schema are loaded from:
    prompts/sub_agents/groups/template.yaml
    """

    group_name = "TEMPLATE"

    def get_group_name(self) -> str:
        return self.group_name
