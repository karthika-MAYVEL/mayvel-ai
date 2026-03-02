# agents/sub_agents/workflow_agent.py
# Workflow sub-agent: generates MongoDB QueryTemplates for workflow entities.

from agents.sub_agents.base_agent import BaseSubAgent


class WorkflowAgent(BaseSubAgent):
    """
    Sub-agent for the 'workflow' entity type.
    Tenant-wide by default; applies optional assignedTo user scope.
    """

    entity_type = "workflow"

    def get_entity_type(self) -> str:
        return self.entity_type
