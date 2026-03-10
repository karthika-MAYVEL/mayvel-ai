# agents/agent_registry.py
# Registry: maps domain group names to their T2 agent instances.
#
# Agents are singletons — instantiated ONCE at module load time.
# This means prompt loading and GeminiClient init happen at startup,
# not on every request.
#
# To add a new domain agent:
#   1. Create the agent subclass
#   2. Import it here
#   3. Add one line to _GROUP_REGISTRY
#   Nothing else changes.

from application.agents.sub_agents.domain_base_agent import DomainBaseAgent
from application.agents.sub_agents.inspection_agent import InspectionGroupAgent
from utils.logger import get_app_logger

logger = get_app_logger("agent_registry")

# Agents instantiated once at startup — prompts loaded, LLM client ready.
_GROUP_REGISTRY: dict[str, DomainBaseAgent] = {
    "INSPECTION": InspectionGroupAgent(),
}


def get_group_agent(group_name: str) -> DomainBaseAgent:
    """
    Returns the pre-instantiated T2 agent for the given group name.

    @param group_name: Domain group as returned by T1 RootAgent.
    @returns:          Ready-to-use DomainBaseAgent instance.
    @raises ValueError: If no agent is registered for the group name.
    """
    agent = _GROUP_REGISTRY.get(group_name)
    if not agent:
        registered = list(_GROUP_REGISTRY.keys())
        raise ValueError(
            f"No agent registered for group='{group_name}'. "
            f"Registered groups: {registered}"
        )
    return agent