# agents/root_agent.py
# Root Agent: classifies a user's natural language query into a ChannelPlan.

import json
from pathlib import Path

from api.models.channel_plan import ChannelPlan, ChainChannel, IndependentChannel, ScopeHints
from api.models.routing_decision import RoutingDecision
from api.models.search_request import SearchRequest
from infrastructure.llm_sdk.gemini import GeminiClient
from utils.logger import get_app_logger

logger = get_app_logger("agent.root")

_PROMPT_PATH = Path(__file__).parent.parent.parent / "knowledge" / "prompts" / "root_agent.yaml"

# ---------------------------------------------------------------------------

_ENTITY_TO_GROUP = {
    "inspection": "INSPECTION",
    "inspectionchecklist": "INSPECTION",
    "inspectionexecution": "INSPECTION",
    "inspectionobservation": "INSPECTION",
    "inspectionstatus": "INSPECTION",
    "inspectionresponse": "INSPECTION",
    "inspectionscore": "INSPECTION",
    "task": "TASK",
    "taskobservation": "TASK",
    "taskcompletion": "TASK",
    "workflow": "WORKFLOW",
    "workflowexecution": "WORKFLOW",
    "workflowtransition": "WORKFLOW",
    "dashboard": "DASHBOARD",
    "activity": "DASHBOARD"
}


class RootAgent:
    """
    Root Agent: parses a user query and returns a typed ChannelPlan.
    Delegates to Gemini for LLM-based classification. Raises an exception
    if the LLM fails or is unavailable.
    """

    def __init__(self):
        import yaml
        self._prompt = yaml.safe_load(_PROMPT_PATH.read_text())
        self._llm = GeminiClient()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def route(self, request: SearchRequest) -> RoutingDecision:
        """
        Classifies the user query into a RoutingDecision (T1).
        """
        plan = await self._classify(request)
        return self._to_routing_decision(plan, request)

    async def _classify(self, request: SearchRequest) -> ChannelPlan:
        if not self._llm.client:
            raise RuntimeError("LLM client is not configured. Cannot classify query.")

        system = self._build_system()
        user_msg = f"USER QUERY: {request.query}"
        try:
            raw = self._llm.generate_json(prompt=user_msg, system_instruction=system, agent="root")
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            channel_plan = ChannelPlan.model_validate(json.loads(raw))
            logger.info(f"RootAgent plan: {len(channel_plan.independent)} independent, {len(channel_plan.chains)} chains")
            return channel_plan
        except Exception as e:
            logger.error(f"RootAgent LLM parse failed: {e}.")
            raise RuntimeError(f"Failed to classify query using LLM: {e}") from e

    def _to_routing_decision(self, plan: ChannelPlan, request: SearchRequest) -> RoutingDecision:
        has_chains = len(plan.chains) > 0
        complexity = 'complex' if has_chains else 'simple'
        
        hints = None
        first_entity = "inspection" # default
        
        if plan.independent:
            first_entity = plan.independent[0].entity_type
            hints = plan.independent[0].scope_hints
        elif plan.chains:
            first_entity = plan.chains[0].root_entity
            hints = plan.chains[0].scope_hints
            
        primary_group = _ENTITY_TO_GROUP.get(first_entity.lower(), 'INSPECTION')
        is_user_scoped = bool(hints and hints.userfield)
        
        return RoutingDecision(
            primary_group=primary_group,
            secondary_groups=[],
            user_scoped=is_user_scoped,
            entity_hint=first_entity,
            status_filter=hints.status_filter if hints else None,
            time_window=hints.time_window if hints else None,
            query_complexity=complexity
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_system(self) -> str:
        sections = self._prompt.get("assembly_order", [])
        parts = [self._prompt[s] for s in sections if s in self._prompt]
        return "\n\n".join(parts)
