# agents/sub_agents/base_agent.py
# Abstract base class for all SEYO sub-agents.

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union

import yaml

from models.channel_plan import ChainChannel, IndependentChannel, ScopeHints
from models.query_template import QueryTemplate
from llm_sdk.gemini import GeminiClient
from core.logger import get_app_logger

logger = get_app_logger("agent.base")

_BASE_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "sub_agents" / "base_query_prompt.yaml"
_ENTITY_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts" / "sub_agents"

# Maps camelCase entity_type → snake_case YAML filename (without .yaml)
_ENTITY_YAML_NAMES: dict[str, str] = {
    "responseHistory": "response_history",
    "inspectionObservation": "inspection_observation",
    "taskObservation": "task_observation",
}

# Placeholder strings that must appear in every generated pipeline
_REQUIRED_PLACEHOLDERS = {"{tenantId}"}


class BaseSubAgent(ABC):
    """
    Abstract base for all SEYO sub-agents.

    Subclasses declare `entity_type` as a class attribute and implement
    `get_entity_type()`. The base class handles:
    - Loading base + entity-specific YAML prompts
    - Assembling the system instruction
    - Calling the LLM and validating the QueryTemplate response
    - Fallback template when no API key is available
    """

    entity_type: str  # set by each concrete subclass

    def __init__(self):
        self._base_prompt = yaml.safe_load(_BASE_PROMPT_PATH.read_text())
        yaml_name = _ENTITY_YAML_NAMES.get(self.get_entity_type(), self.get_entity_type())
        entity_yaml_path = _ENTITY_PROMPTS_DIR / f"{yaml_name}.yaml"
        self._entity_prompt = yaml.safe_load(entity_yaml_path.read_text())
        self._llm = GeminiClient()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        channel: Union[IndependentChannel, ChainChannel],
        original_query: str,
    ) -> QueryTemplate:
        """
        Translates a channel + original query into a validated QueryTemplate.

        @param channel: The channel description from the RootAgent ChannelPlan.
        @param original_query: The verbatim user query string.
        @returns: Validated QueryTemplate with placeholder pipeline.
        @throws ValueError: If LLM returns an unparseable / invalid response.
        """
        if not self._llm.client:
            return self._fallback_template(channel.scope_hints)

        system = self._build_system()
        user_msg = self._build_user_message(channel, original_query)
        try:
            raw = self._llm.generate_json(prompt=user_msg, system_instruction=system)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            template = QueryTemplate.model_validate(json.loads(raw))
            logger.info(f"{self.get_entity_type()} agent generated QueryTemplate (type={template.query_type})")
            return template
        except Exception as e:
            logger.error(f"{self.get_entity_type()} agent LLM error: {e}. Returning fallback.")
            return self._fallback_template(channel.scope_hints)

    # ------------------------------------------------------------------
    # Backward-compatibility shim — used by core/orchestrator.py
    # ------------------------------------------------------------------

    def generate_query(self, user_query: str, context: dict = None) -> str:
        """
        Legacy synchronous wrapper kept for orchestrator compatibility.
        Builds a minimal pipeline string without calling the LLM.

        @param user_query: Natural language query string.
        @param context: Optional injected context (e.g. checklistId).
        @returns: JSON string of aggregation pipeline stages.
        """
        import asyncio
        from models.channel_plan import IndependentChannel, ScopeHints
        channel = IndependentChannel(
            entity_type=self.get_entity_type(),
            scope_hints=ScopeHints(),
            reason="compat shim",
        )
        if context:
            channel.scope_hints.keywords = [str(context)]
        try:
            loop = asyncio.get_event_loop()
            template = loop.run_until_complete(self.generate(channel, user_query))
        except RuntimeError:
            template = asyncio.new_event_loop().run_until_complete(self.generate(channel, user_query))
        return json.dumps(template.pipeline)

    # ------------------------------------------------------------------
    # Abstract
    # ------------------------------------------------------------------

    @abstractmethod
    def get_entity_type(self) -> str:
        """Returns the SEYO entity type string for this agent."""
        ...

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_system(self) -> str:
        """Assembles base sections then appends entity-specific rules."""
        order = self._base_prompt.get("assembly_order", [])
        sections = self._base_prompt.get("sections", {})
        parts = [sections[s]["content"] for s in order if s in sections]

        for key in ("additional_rules", "entity_schema", "io_model"):
            value = self._entity_prompt.get(key, "")
            if value:
                parts.append(value)

        return "\n\n".join(parts)

    def _build_user_message(
        self,
        channel: Union[IndependentChannel, ChainChannel],
        original_query: str,
    ) -> str:
        """Formats the LLM user message with entity type, scope_hints, and query."""
        hints = channel.scope_hints
        return (
            f"USER QUERY: {original_query}\n"
            f"ENTITY TYPE: {self.get_entity_type()}\n"
            f"SCOPE HINTS: {hints.model_dump_json()}\n"
            f"REASON FOR SELECTION: {channel.reason}"
        )

    def _fallback_template(self, scope_hints: ScopeHints) -> QueryTemplate:
        """
        Returns a minimal, valid QueryTemplate without calling the LLM.
        Used when no API key is present or the LLM call fails.
        """
        entity = self.get_entity_type()
        userfield = scope_hints.userfield if scope_hints else None
        match_stage: dict = {
            "$match": {"type": entity, "tenantId": "{tenantId}", "isDeleted": False}
        }
        if userfield:
            match_stage["$match"][userfield] = "{userId}"

        project_field = f"{entity}Id"
        pipeline = [
            match_stage,
            {"$project": {"_id": 0, project_field: "$_id", "title": 1, "createdAt": 1}},
        ]
        placeholders = ["tenantId"] + (["userId"] if userfield else [])
        return QueryTemplate(
            query_type="aggregate",
            entity_type=entity,
            pipeline=pipeline,
            userfield=userfield,
            userfield_reason="fallback",
            placeholders_used=placeholders,
            explanation=f"Fallback template for {entity} (no LLM call).",
        )
