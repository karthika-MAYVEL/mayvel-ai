# agents/root_agent.py
# Root Agent (T1): classifies a user query into a RoutingDecision.

from pathlib import Path

from presentation.models.channel_plan import ChannelPlan
from presentation.models.routing_decision import RoutingDecision
from presentation.models.search_request import SearchRequest
from infrastructure.llm_sdk.gemini import GeminiClient
from utils.prompt_loader import load as load_prompt
from utils.llm_response_validator import validate, build_correction_prompt
from utils.logger import get_app_logger

logger = get_app_logger("agent.root")

_PROMPT_PATH = Path(__file__).parent.parent.parent / "knowledge" / "prompts" / "root_agent.yaml"

# Maps granular LLM entity names → coarse domain group names.
# TODO: remove this once ChannelPlan includes primary_group directly.
_ENTITY_TO_GROUP: dict[str, str] = {
    "inspection":            "INSPECTION",
    "inspectionchecklist":   "INSPECTION",
    "inspectionexecution":   "INSPECTION",
    "inspectionobservation": "INSPECTION",
    "inspectionstatus":      "INSPECTION",
    "inspectionresponse":    "INSPECTION",
    "inspectionscore":       "INSPECTION",
    "task":                  "TASK",
    "taskobservation":       "TASK",
    "taskcompletion":        "TASK",
    "workflow":              "WORKFLOW",
    "workflowexecution":     "WORKFLOW",
    "workflowtransition":    "WORKFLOW",
    "dashboard":             "DASHBOARD",
    "activity":              "DASHBOARD",
}


class RootAgent:
    """
    T1 Agent: classifies a user query into a RoutingDecision.
    Raises explicitly on LLM or prompt failure — no silent fallbacks.
    """

    def __init__(self):
        self._llm = GeminiClient()
        self._system_prompt = load_prompt(_PROMPT_PATH)

    # ── Public ────────────────────────────────────────────────────────────────

    async def route(self, request: SearchRequest) -> RoutingDecision:
        """
        Classifies the user query into a RoutingDecision.

        @param request: Validated SearchRequest from the API layer.
        @returns: RoutingDecision with primary group, scope, and complexity.
        @raises RuntimeError: If LLM unavailable, classification fails, or
                              the plan contains no routable entity.
        """
        if not self._llm.client:
            raise RuntimeError("LLM client is not configured.")

        plan = await self._classify(request)
        return self._to_routing_decision(plan)

    # ── Private ───────────────────────────────────────────────────────────────

    async def _classify(self, request: SearchRequest) -> ChannelPlan:
        """
        Calls the LLM and validates the response against ChannelPlan.
        Retries once with a correction prompt on validation failure.
        """
        user_msg = f"USER QUERY: {request.query}"
        raw = self._llm.generate_json(
            prompt=user_msg,
            system_instruction=self._system_prompt,
            agent="root",
        )

        try:
            return validate(raw, ChannelPlan, request.query)
        except ValueError as exc:
            logger.warning(f"RootAgent classification failed (attempt 1): {exc}")

        correction = build_correction_prompt(raw, ChannelPlan, request.query)
        raw_retry = self._llm.generate_json(
            prompt=correction,
            system_instruction=self._system_prompt,
            agent="root",
        )
        try:
            return validate(raw_retry, ChannelPlan, request.query)
        except ValueError as exc:
            logger.error(f"RootAgent classification failed after retry: {exc}")
            raise RuntimeError(f"Failed to classify query after retry: {exc}") from exc

    def _to_routing_decision(self, plan: ChannelPlan) -> RoutingDecision:
        """
        Maps a validated ChannelPlan to a RoutingDecision.
        Raises if the plan contains no routable entity — never silently defaults.
        """
        if not plan.independent and not plan.chains:
            raise RuntimeError(
                "ChannelPlan contains no independent channels or chains. "
                "LLM classification returned an empty plan."
            )

        hints = None

        if plan.independent:
            entity = plan.independent[0].entity_type
            hints = plan.independent[0].scope_hints
        else:
            entity = plan.chains[0].root_entity
            hints = plan.chains[0].scope_hints

        primary_group = _ENTITY_TO_GROUP.get(entity.lower())
        if not primary_group:
            raise RuntimeError(
                f"LLM returned unknown entity type '{entity}'. "
                f"Add it to _ENTITY_TO_GROUP or update the classification prompt."
            )

        return RoutingDecision(
            primary_group=primary_group,
            secondary_groups=[],
            user_scoped=bool(hints and hints.userfield),
            entity_hint=entity,
            status_filter=hints.status_filter if hints else None,
            time_window=hints.time_window if hints else None,
            query_complexity="complex" if plan.chains else "simple",
        )