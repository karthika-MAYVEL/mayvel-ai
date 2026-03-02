# agents/agent_registry.py
# Registry: maps entity_type strings (lowercase) to their agent classes.

from agents.sub_agents.base_agent import BaseSubAgent
from agents.sub_agents.inspection_agent import InspectionAgent
from agents.sub_agents.checklist_agent import ChecklistAgent
from agents.sub_agents.task_agent import TaskAgent
from agents.sub_agents.response_history_agent import ResponseHistoryAgent
from agents.sub_agents.workflow_agent import WorkflowAgent
from agents.sub_agents.activity_agent import ActivityAgent
from agents.sub_agents.inspection_observation_agent import InspectionObservationAgent
from agents.sub_agents.task_observation_agent import TaskObservationAgent

# Maps entity_type (as returned by RootAgent in ChannelPlan) → agent class.
# Keys intentionally lowercase to match ChannelPlan.independent[n].entity_type.
_REGISTRY: dict[str, type[BaseSubAgent]] = {
    "inspection": InspectionAgent,
    "checklist": ChecklistAgent,
    "task": TaskAgent,
    "responseHistory": ResponseHistoryAgent,
    "workflow": WorkflowAgent,
    "activity": ActivityAgent,
    "inspectionObservation": InspectionObservationAgent,
    "taskObservation": TaskObservationAgent,
}


def get_agent(entity_type: str) -> BaseSubAgent:
    """
    Instantiates and returns the sub-agent for the given entity type.

    @param entity_type: SEYO entity type string (e.g. 'inspection').
    @returns: Instantiated sub-agent.
    @throws ValueError: If no agent is registered for the entity type.
    """
    agent_class = _REGISTRY.get(entity_type)
    if not agent_class:
        raise ValueError(f"No agent registered for entity_type='{entity_type}'")
    return agent_class()
