# agents/root_agent.py
# Root Agent: classifies a user's natural language query into a ChannelPlan.

import json
from pathlib import Path

from models.channel_plan import ChannelPlan, ChainChannel, IndependentChannel, ScopeHints
from models.search_request import SearchRequest
from llm_sdk.gemini import GeminiClient
from core.logger import get_app_logger

logger = get_app_logger("agent.root")

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "root_agent.yaml"

# ---------------------------------------------------------------------------
# Fallback heuristic keyword sets (used when no LLM key is available)
# ---------------------------------------------------------------------------
_SCORING_KEYWORDS = {"score", "compliance", "kpi", "performance", "pass", "fail", "rate", "percentage"}
_USER_KEYWORDS = {"my", "mine", "i ", " me ", "assigned to me", "created by me"}
_CHECKLIST_KEYWORDS = {"checklist", "template", "form"}
_INSPECTION_KEYWORDS = {"inspection", "audit", "survey"}
_TASK_KEYWORDS = {"task", "action item", "corrective"}
_WORKFLOW_KEYWORDS = {"workflow", "process"}
_ACTIVITY_KEYWORDS = {"activity", "schedule"}


class RootAgent:
    """
    Root Agent: parses a user query and returns a typed ChannelPlan.
    Delegates to Gemini for LLM-based classification; falls back to a
    keyword heuristic when no API key is configured.
    """

    def __init__(self):
        import yaml
        self._prompt = yaml.safe_load(_PROMPT_PATH.read_text())
        self._llm = GeminiClient()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def plan(self, request: SearchRequest) -> ChannelPlan:
        """
        Classifies the user query into a ChannelPlan.

        @param request: The incoming SearchRequest.
        @returns: A validated ChannelPlan with independent and/or chain channels.
        @throws ValueError: If LLM returns unparseable JSON.
        """
        if not self._llm.client:
            return self._fallback_plan(request)

        system = self._build_system()
        user_msg = f"USER QUERY: {request.query}"
        try:
            raw = self._llm.generate_json(prompt=user_msg, system_instruction=system, agent="root")
            print("Raw llm response from ROOT AGENT : ", raw)
            # Strip markdown fences if the model wraps output
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            channel_plan = ChannelPlan.model_validate(json.loads(raw))

            print("Channel plan: ", channel_plan)
            
            logger.info(f"RootAgent plan: {len(channel_plan.independent)} independent, {len(channel_plan.chains)} chains")
            return channel_plan
        except Exception as e:
            logger.error(f"RootAgent LLM parse failed: {e}. Falling back to heuristic.")
            return self._fallback_plan(request)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_system(self) -> str:
        sections = self._prompt.get("assembly_order", [])
        parts = [self._prompt[s] for s in sections if s in self._prompt]
        return "\n\n".join(parts)

    def _fallback_plan(self, request: SearchRequest) -> ChannelPlan:
        """
        Keyword heuristic used when Gemini is unavailable (no API key / tests).
        Returns a best-effort ChannelPlan based on token matching.
        """
        q = request.query.lower()
        is_user_scoped = any(kw in q for kw in _USER_KEYWORDS)
        time_window = _detect_time_window(q)
        hints = ScopeHints(
            userfield="assignedTo" if is_user_scoped else None,
            time_window=time_window,
        )

        # Scoring / compliance → responseHistory chain
        if any(kw in q for kw in _SCORING_KEYWORDS):
            return ChannelPlan(
                independent=[],
                chains=[ChainChannel(
                    root_entity="responseHistory",
                    chain=["responseHistory", "execution", "inspection"],
                    scope_hints=hints,
                    reason="Fallback: scoring keywords detected",
                )],
                coverage_reason="Scoring query — responseHistory chain",
                original_query=request.query,
            )

        # Single entity detection
        entity_type = _detect_entity(q)
        return ChannelPlan(
            independent=[IndependentChannel(entity_type=entity_type, scope_hints=hints, reason="Fallback: keyword match")],
            chains=[],
            coverage_reason=f"Single entity fallback: {entity_type}",
            original_query=request.query,
        )


# ---------------------------------------------------------------------------
# Backward-compatibility shim — used by core/orchestrator.py (Stage 1 compat)
# ---------------------------------------------------------------------------

class IntentClassification:
    """
    Thin compat wrapper so the existing orchestrator can still call classify_intent()
    without modification until it is replaced in Stage 3.
    """
    __slots__ = ("intent", "confidence", "reasoning")

    def __init__(self, intent: str, confidence: float, reasoning: str):
        self.intent = intent
        self.confidence = confidence
        self.reasoning = reasoning


def classify_intent(user_query: str) -> IntentClassification:
    """
    Legacy synchronous wrapper kept for orchestrator compatibility.
    Maps the new ChannelPlan back to the old 3-way Checklist/Inspection/Sequential intent.

    @param user_query: Natural language query string.
    @returns: IntentClassification with intent, confidence, and reasoning.
    """
    import asyncio
    from models.search_request import SearchRequest

    agent = RootAgent()
    request = SearchRequest(query=user_query, tenantId="", userId="")
    try:
        plan = asyncio.get_event_loop().run_until_complete(agent.plan(request))
    except RuntimeError:
        # If no event loop is running (e.g. tests), create one
        plan = asyncio.new_event_loop().run_until_complete(agent.plan(request))

    # Map ChannelPlan → legacy intent
    has_chains = bool(plan.chains)
    entity_types = [ch.entity_type for ch in plan.independent]

    if has_chains:
        intent = "Sequential"
    elif "checklist" in entity_types and len(entity_types) == 1:
        intent = "Checklist"
    else:
        intent = "Inspection"

    return IntentClassification(intent=intent, confidence=0.9, reasoning=plan.coverage_reason)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _detect_entity(query: str) -> str:
    if any(kw in query for kw in _CHECKLIST_KEYWORDS):
        return "checklist"
    if any(kw in query for kw in _TASK_KEYWORDS):
        return "task"
    if any(kw in query for kw in _WORKFLOW_KEYWORDS):
        return "workflow"
    if any(kw in query for kw in _ACTIVITY_KEYWORDS):
        return "activity"
    return "inspection"  # default


def _detect_time_window(query: str) -> dict | None:
    if "today" in query:
        return {"kind": "today"}
    if "this week" in query or "thisweek" in query:
        return {"kind": "thisWeek"}
    if "this month" in query or "thismonth" in query:
        return {"kind": "thisMonth"}
    if "last month" in query:
        return {"kind": "lastMonth"}
    if "last 30" in query or "30 day" in query:
        return {"kind": "lastNDays", "amount": 30}
    if "last 7" in query or "7 day" in query:
        return {"kind": "lastNDays", "amount": 7}
    return None
