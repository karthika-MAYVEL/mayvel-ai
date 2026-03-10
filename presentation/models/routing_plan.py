# presentation/models/routing_plan.py
# T1 LLM response model — validated directly from raw LLM output.
#
# To add a new agent group:
#   1. Add the group name to AgentGroup Literal below
#   2. Add the agent to agent_registry.py
#   3. Add the YAML section under `agents:` in root_agent.yaml
#   Nothing else changes in this file.

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


# Single source of truth for all valid agent group names.
AgentGroup = Literal["INSPECTION"]


class AgentRoute(BaseModel):
    """
    A single routing instruction inside the T1 LLM response.

    @param group:               Domain agent to invoke.
    @param order:               Execution order — 1 = primary, 2+ = secondary.
    @param problem_description: Plain-English restatement of user intent
                                scoped to this specific agent.
    """
    group: AgentGroup
    order: int = Field(..., ge=1)
    problem_description: str


class RoutingPlan(BaseModel):
    """
    Full T1 LLM response — validated directly from raw LLM output.

    @param agents:           Ordered list of agents to invoke (min 1).
    @param execution:        How agents run relative to each other.
    @param query_complexity: LLM-assessed complexity of the query.
    @param coverage_reason:  One-sentence explanation of the routing decision.
    """
    agents: list[AgentRoute] = Field(..., min_length=1)
    execution: Literal["sequential", "parallel"] = "sequential"
    query_complexity: Literal["simple", "complex"] = "simple"
    coverage_reason: str = ""