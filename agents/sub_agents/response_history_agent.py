# agents/sub_agents/response_history_agent.py
# ResponseHistory sub-agent: generates MongoDB QueryTemplates for responseHistory entities.

from agents.sub_agents.base_agent import BaseSubAgent


class ResponseHistoryAgent(BaseSubAgent):
    """
    Sub-agent for the 'responseHistory' entity type.
    Chain-only: root of the responseHistory → execution → inspection chain.
    Mandatory deduplication and optional scoring pipeline stages.
    """

    entity_type = "responseHistory"

    def get_entity_type(self) -> str:
        return self.entity_type
