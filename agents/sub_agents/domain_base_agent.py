# agents/sub_agents/domain_base_agent.py
# DomainBaseAgent: Abstract base for all T2 domain group agents.
# Loads shared_base sections + one or more group schema YAMLs per routing decision.

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import yaml

from models.routing_decision import RoutingDecision
from models.query_template import QueryTemplate
from llm_sdk.gemini import GeminiClient
from core.logger import get_app_logger

logger = get_app_logger("agent.domain_base")

_BASE_PROMPT_PATH = (
    Path(__file__).parent.parent.parent / "prompts" / "sub_agents" / "base_query_prompt.yaml"
)
_GROUPS_DIR = (
    Path(__file__).parent.parent.parent / "prompts" / "sub_agents" / "groups"
)

# Maps group name → YAML filename stem under prompts/sub_agents/groups/
_GROUP_YAML: dict[str, str] = {
    "TEMPLATE":   "template",
    "INSPECTION": "inspection",
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
        self._base_sections = yaml.safe_load(_BASE_PROMPT_PATH.read_text())
        self._group_prompts: dict[str, dict] = {}  # lazily loaded
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
            return self._fallback_template(routing)

        system = self._build_system(routing)
        user_msg = self._build_user_message(routing, user_query)
        try:
            raw = self._llm.generate_json(
                prompt=user_msg,
                system_instruction=system,
                agent=self.group_name,
            )
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            template = QueryTemplate.model_validate(json.loads(raw))
            logger.info(
                f"DomainAgent[{self.group_name}] generated QueryTemplate "
                f"(type={template.query_type}, entity={template.entity_type})"
            )
            return template
        except Exception as exc:
            logger.error(f"DomainAgent[{self.group_name}] LLM error: {exc}. Using fallback.")
            return self._fallback_template(routing)

    @abstractmethod
    def get_group_name(self) -> str:
        """Returns the domain group name for this agent (e.g. 'SCHEDULING')."""
        ...

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_group_prompt(self, group: str) -> dict:
        """Loads and caches the YAML for a domain group."""
        if group not in self._group_prompts:
            yaml_stem = _GROUP_YAML.get(group)
            if not yaml_stem:
                raise ValueError(f"Unknown domain group: '{group}'")
            path = _GROUPS_DIR / f"{yaml_stem}.yaml"
            self._group_prompts[group] = yaml.safe_load(path.read_text())
        return self._group_prompts[group]

    def _build_system(self, routing: RoutingDecision) -> str:
        """Assembles Shared Base sections then appends all relevant group schemas."""
        order = self._base_sections.get("assembly_order", [])
        sections = self._base_sections.get("sections", {})
        parts = [sections[s]["content"] for s in order if s in sections]

        # Keys to pull from each group YAML — includes the new v1.1 INSPECTION keys
        GROUP_YAML_KEYS = (
            "group_rules",
            "entity_schemas",
            "dedup_block",
            "query_patterns",
            "relationships",
            "routing_contract",
            "common_mistakes",
        )

        for group in routing.all_groups():
            group_prompt = self._load_group_prompt(group)
            for key in GROUP_YAML_KEYS:
                value = group_prompt.get(key, "")
                if value:
                    parts.append(value)

        return "\n\n".join(parts)

    def _build_user_message(self, routing: RoutingDecision, user_query: str) -> str:
        """Formats the T2 user message with routing context and query."""
        user_id_line = f"USER ID: {{userId}}" if routing.user_scoped else "USER SCOPE: tenant-wide"
        return (
            f"# USER REQUEST\n"
            f"{user_query}\n\n"
            f"# ROUTING CONTEXT\n"
            f"primary_group: {routing.primary_group}\n"
            f"secondary_groups: {routing.secondary_groups}\n"
            f"user_scoped: {routing.user_scoped}\n"
            f"{user_id_line}\n"
            f"query_complexity: {routing.query_complexity}\n"
            f"time_field: {routing.time_field or 'null'}\n"
            f"time_window: {routing.time_window.model_dump_json() if routing.time_window else 'null'}\n"
            f"status_filter: {routing.status_filter or 'null'}\n"
            f"entity_hint: {routing.entity_hint or 'null'}\n"
        )

    def _fallback_template(self, routing: RoutingDecision) -> QueryTemplate:
        """Minimal valid QueryTemplate returned when no LLM call is possible."""
        entity = routing.entity_hint or routing.primary_group.lower()
        match_stage: dict = {
            "$match": {"type": entity, "tenantId": "{tenantId}", "isDeleted": False}
        }
        if routing.user_scoped:
            match_stage["$match"]["assignedTo"] = "{userId}"

        pipeline = [
            match_stage,
            {"$project": {"_id": 0, f"{entity}Id": "$_id", "title": 1, "createdAt": 1}},
        ]
        placeholders = ["tenantId"] + (["userId"] if routing.user_scoped else [])
        return QueryTemplate(
            query_type="aggregate",
            entity_type=entity,
            pipeline=pipeline,
            userfield="assignedTo" if routing.user_scoped else None,
            userfield_reason="fallback",
            placeholders_used=placeholders,
            explanation=f"Fallback template for group={routing.primary_group} (no LLM call).",
        )
