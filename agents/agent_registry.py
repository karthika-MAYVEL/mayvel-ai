# agents/agent_registry.py
# Registry: maps both entity_type strings and domain group names to their agent classes.

from agents.sub_agents.base_agent import BaseSubAgent
from agents.sub_agents.domain_base_agent import DomainBaseAgent
from agents.sub_agents.inspection_agent import InspectionAgent
from agents.sub_agents.checklist_agent import ChecklistAgent
from agents.sub_agents.task_agent import TaskAgent
from agents.sub_agents.response_history_agent import ResponseHistoryAgent
from agents.sub_agents.workflow_agent import WorkflowAgent
from agents.sub_agents.activity_agent import ActivityAgent
from agents.sub_agents.inspection_observation_agent import InspectionObservationAgent
from agents.sub_agents.task_observation_agent import TaskObservationAgent
from agents.sub_agents.template_agent import TemplateGroupAgent
from agents.sub_agents.inspection_group_agent import InspectionGroupAgent

# ---------------------------------------------------------------------------
# T2 · Domain Group Registry (new two-call architecture)
# ---------------------------------------------------------------------------
# Current groups:
#   TEMPLATE   — checklist · section · question · responseValues
#   INSPECTION — full inspection lifecycle (v1.1 unified agent, replaces
#                 SCHEDULING + EXECUTION + TASK groups from v1)

_GROUP_REGISTRY: dict[str, type[DomainBaseAgent]] = {
    "TEMPLATE":   TemplateGroupAgent,
    "INSPECTION": InspectionGroupAgent,
}


def get_group_agent(group_name: str) -> DomainBaseAgent:
    """
    Instantiates and returns the T2 domain group agent for the given group name.

    @param group_name: Domain group name as returned by the T1 classifier
                       (TEMPLATE | INSPECTION).
    @returns: Instantiated domain group agent.
    @throws ValueError: If no agent is registered for the group name.
    """
    agent_class = _GROUP_REGISTRY.get(group_name)
    if not agent_class:
        raise ValueError(f"No group agent registered for group='{group_name}'")
    return agent_class()


# ---------------------------------------------------------------------------
# Legacy entity registry — kept for backward-compat during Stage B → C migration
# ---------------------------------------------------------------------------

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
    Instantiates and returns the legacy sub-agent for the given entity type.
    DEPRECATED: prefer get_group_agent() for all new routing paths.

    @param entity_type: SEYO entity type string (e.g. 'inspection').
    @returns: Instantiated sub-agent.
    @throws ValueError: If no agent is registered for the entity type.
    """
    agent_class = _REGISTRY.get(entity_type)
    if not agent_class:
        raise ValueError(f"No agent registered for entity_type='{entity_type}'")
    return agent_class()
