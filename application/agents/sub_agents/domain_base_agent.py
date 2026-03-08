# agents/sub_agents/domain_base_agent.py
# DomainBaseAgent: Abstract base for all T2 domain group agents.
# Loads shared_base sections + one or more group schema YAMLs per routing decision.

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from utils.json_parser import safe_parse_json

from api.models.routing_decision import RoutingDecision
from api.models.query_template import QueryTemplate
from infrastructure.llm_sdk.gemini import GeminiClient
from utils.logger import get_app_logger

logger = get_app_logger("agent.domain_base")

_KNOWLEDGE_DIR = (
    Path(__file__).parent.parent.parent.parent / "knowledge" / "prompts" / "sub_agents"
)

# Maps group name → YAML filename stem under knowledge/groups/
_GROUP_YAML: dict[str, str] = {
    "INSPECTION": "inspection",
    "TASK":       "task",
    "WORKFLOW":   "workflow",
    "DASHBOARD":  "dashboard",
}


class DomainBaseAgent(ABC):
    """
    Abstract base for all T2 domain group agents.

    Each subclass declares `group_name` (e.g. 'SCHEDULING') and the base class:
    - Assembles Shared Base (SB-1…SB-10) from base_query_prompt.yaml
    - Appends group_rules + entity_schemas for the primary group
    - Appends secondary group schemas when cross-group routing occurs
    - Calls the LLM once and validates the QueryTemplate response
    """

    group_name: str  # set by each concrete subclass

    def __init__(self) -> None:
        self._prompt_cache: dict[str, str] = {}
        self._llm = GeminiClient()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        routing: RoutingDecision,
        user_query: str,
        tenant_id: str,
        user_id: Optional[str],
    ) -> QueryTemplate:
        """
        Generates a QueryTemplate for the given routing decision.

        @param routing: T1 routing decision (primary + secondary groups).
        @param user_query: Original natural language query from the user.
        @param tenant_id: Tenant UUID (injected at runtime).
        @param user_id: User UUID, or None for tenant-wide queries.
        @returns: Validated QueryTemplate with placeholder pipeline.
        @throws ValueError: If LLM returns an unparseable response.
        """
        if not self._llm.client:
            raise RuntimeError(f"LLM client is not configured for DomainAgent[{self.group_name}].")

        system = self._load_prompt(self.group_name)
        user_msg = self._build_user_message(routing, user_query)
        try:
            raw = self._llm.generate_json(
                prompt=user_msg,
                system_instruction=system,
                agent=self.group_name,
            )
            parsed = safe_parse_json(raw)
            template = QueryTemplate.model_validate(parsed)
            logger.info(
                f"DomainAgent[{self.group_name}] generated QueryTemplate "
                f"(type={template.entity_type})"
            )
            return template
        except Exception as exc:
            logger.error(f"DomainAgent[{self.group_name}] LLM error: {exc}.")
            raise RuntimeError(f"Failed to generate template in DomainAgent[{self.group_name}]: {exc}") from exc

    @abstractmethod
    def get_group_name(self) -> str:
        """Returns the domain group name for this agent (e.g. 'SCHEDULING')."""
        ...

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_prompt(self, group: str) -> str:
        """Loads and caches the YAML for a domain group."""
        if group not in self._prompt_cache:
            yaml_stem = _GROUP_YAML.get(group)
            if not yaml_stem:
                raise ValueError(f"Unknown domain group: '{group}'")
            path = _KNOWLEDGE_DIR / f"{yaml_stem}.yaml"
            if not path.exists():
                raise FileNotFoundError(f"System prompt missing: {path}")
            self._prompt_cache[group] = path.read_text(encoding="utf-8")
        return self._prompt_cache[group]

    def _build_user_message(self, routing: RoutingDecision, user_query: str) -> str:
        """Formats the T2 user message with routing context and query."""
        user_id_line = "yes" if routing.user_scoped else "no"
        return (
            f"USER QUERY: {user_query}\n"
            f"ENTITY HINT: {routing.entity_hint or 'none'}\n"
            f"STATUS FILTER: {routing.status_filter or 'none'}\n"
            f"TIME WINDOW: {routing.time_window.model_dump() if routing.time_window else 'none'}\n"
            f"USER SCOPED: {user_id_line}\n"
        )
