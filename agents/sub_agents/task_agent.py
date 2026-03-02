# agents/sub_agents/task_agent.py
# Task sub-agent: generates MongoDB QueryTemplates for task entities.

from agents.sub_agents.base_agent import BaseSubAgent


class TaskAgent(BaseSubAgent):
    """
    Sub-agent for the 'task' entity type.
    Inherits all LLM orchestration and prompt assembly from BaseSubAgent.
    Entity-specific rules and schema are loaded from prompts/sub_agents/task.yaml.

    Key constraints (from spec):
    - Default userfield: 'assignedTo'; switch to 'createdBy' on explicit creator intent
    - Status is a plain String field — no $lookup required
    - No scheduleDate field — never filter by due date
    """

    entity_type = "task"

    def get_entity_type(self) -> str:
        return self.entity_type
