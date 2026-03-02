from typing import Type
from agents.sub_agents.base_agent import BaseSubAgent
from agents.sub_agents.inspection_agent import InspectionAgent
from agents.sub_agents.checklist_agent import ChecklistAgent
from agents.sub_agents.task_agent import TaskAgent
from agents.sub_agents.response_history_agent import ResponseHistoryAgent
from agents.sub_agents.workflow_agent import WorkflowAgent
from agents.sub_agents.activity_agent import ActivityAgent
from agents.sub_agents.inspection_observation_agent import InspectionObservationAgent
from agents.sub_agents.task_observation_agent import TaskObservationAgent
from agents.sub_agents.projection_agent import ProjectionAgent

class AgentRegistry:
    """
    Registry for mapping entity types to their respective agent classes.
    """
    _registry = {
        "Inspection": InspectionAgent,
        "Checklist": ChecklistAgent,
        "Task": TaskAgent,
        "ResponseHistory": ResponseHistoryAgent,
        "Workflow": WorkflowAgent,
        "Activity": ActivityAgent,
        "InspectionObservation": InspectionObservationAgent,
        "TaskObservation": TaskObservationAgent,
        "Projection": ProjectionAgent,
    }

    @classmethod
    def get_agent(cls, entity_type: str) -> Type[BaseSubAgent]:
        agent_class = cls._registry.get(entity_type)
        if not agent_class:
            raise ValueError(f"No agent registered for entity type: {entity_type}")
        return agent_class
