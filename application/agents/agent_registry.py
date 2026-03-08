# agents/agent_registry.py
# Registry: maps both entity_type strings and domain group names to their agent classes.

from application.agents.sub_agents.domain_base_agent import DomainBaseAgent
from application.agents.sub_agents.inspection_agent import InspectionGroupAgent
from application.agents.sub_agents.task_agent import TaskGroupAgent
from application.agents.sub_agents.workflow_agent import WorkflowGroupAgent
from application.agents.sub_agents.dashboard_agent import DashboardGroupAgent

# ---------------------------------------------------------------------------
# T2 · Domain Group Registry (new two-call architecture)
# ---------------------------------------------------------------------------
# Current groups:
#   TEMPLATE   — checklist · section · question · responseValues
#   INSPECTION — full inspection lifecycle (v1.1 unified agent, replaces
#                 SCHEDULING + EXECUTION + TASK groups from v1)

_GROUP_REGISTRY: dict[str, type[DomainBaseAgent]] = {
    "INSPECTION": InspectionGroupAgent,
    "TASK": TaskGroupAgent,
    "WORKFLOW": WorkflowGroupAgent,
    "DASHBOARD": DashboardGroupAgent,
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



