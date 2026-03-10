# agents/root_agent.py
# Root Agent (T1): classifies a user query into a RoutingDecision.
#
# Flow:
#   route(request)
#     → _classify()        calls LLM, validates against RoutingPlan
#     → _to_routing_decision()   maps RoutingPlan → RoutingDecision
#
# To add a new agent group:
#   1. Add group name to AgentGroup Literal in routing_plan.py
#   2. Add agent to agent_registry.py
#   3. Add YAML section in root_agent.yaml
#   Nothing changes in this file.

from pathlib import Path

from presentation.models.routing_plan import RoutingPlan
from presentation.models.routing_decision import RoutingDecision
from presentation.models.search_request import SearchRequest
from infrastructure.llm_sdk.gemini import GeminiClient
from utils.prompt_loader import load as load_prompt
from utils.llm_response_validator import validate, build_correction_prompt
from utils.logger import get_app_logger

logger = get_app_logger("agent.root")

_PROMPT_PATH = (
    Path(__file__).parent.parent.parent / "knowledge" / "prompts" / "root_agent.yaml"
)


class RootAgent:
    """
    T1 Agent — classifies a user query into a RoutingDecision.

    Validates LLM output against RoutingPlan (which mirrors the YAML
    output schema exactly). Maps the result to a RoutingDecision for
    the orchestrator. Raises explicitly on any failure — no silent fallbacks.
    """

    def __init__(self):
        self._llm = GeminiClient()
        self._system_prompt = load_prompt(_PROMPT_PATH)

    # ── Public ────────────────────────────────────────────────────────────────

    async def route(self, request: SearchRequest) -> RoutingDecision:
        """
        Classifies the user query into a RoutingDecision.

        @param request: Validated SearchRequest from the API layer.
        @returns:       RoutingDecision consumed by the orchestrator.
        @raises RuntimeError: If LLM is unavailable or classification
                              fails after one retry.
        """
        if not self._llm.client:
            raise RuntimeError("LLM client is not configured.")

        plan = await self._classify(request)
        return _to_routing_decision(plan)

    # ── Private ───────────────────────────────────────────────────────────────

    async def _classify(self, request: SearchRequest) -> RoutingPlan:
        """
        Calls the LLM and validates the response against RoutingPlan.
        Retries once with a correction prompt on validation failure.
        """
        raw = self._llm.generate_json(
            prompt=request.query,
            system_instruction=self._system_prompt,
            agent="root",
        )

        try:
            return validate(raw, RoutingPlan, request.query)
        except ValueError as exc:
            logger.warning(f"T1 classification failed (attempt 1): {exc}")

        correction = build_correction_prompt(raw, RoutingPlan, request.query)
        raw_retry = self._llm.generate_json(
            prompt=correction,
            system_instruction=self._system_prompt,
            agent="root",
        )

        try:
            return validate(raw_retry, RoutingPlan, request.query)
        except ValueError as exc:
            logger.error(f"T1 classification failed after retry: {exc}")
            raise RuntimeError(f"Failed to classify query after retry: {exc}") from exc


# ── Pure function — no agent state needed ─────────────────────────────────────

def _to_routing_decision(plan: RoutingPlan) -> RoutingDecision:
    """
    Maps a validated RoutingPlan to a RoutingDecision.

    Primary agent is agents[order=1]. Secondary agents are everything after.
    Group names come directly from the LLM — no mapping table needed.
    """
    # Sort by order so agents[0] is always the primary regardless of LLM list order
    sorted_agents = sorted(plan.agents, key=lambda a: a.order)
    primary = sorted_agents[0]
    secondary = [a.group for a in sorted_agents[1:]]

    return RoutingDecision(
        primary_group=primary.group,
        secondary_groups=secondary,
        problem_description=primary.problem_description,
        query_complexity=plan.query_complexity,
        # user_scoped and filters are resolved by T2 agents
        # from the problem_description — not the T1 agent's job
        user_scoped=False,
        entity_hint=None,
        status_filter=None,
        time_window=None,
    )