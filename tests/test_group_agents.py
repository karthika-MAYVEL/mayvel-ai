# tests/test_group_agents.py
# Tests for the 2 T2 domain group agents (v1.1 architecture):
#   TEMPLATE group (TemplateGroupAgent)
#   INSPECTION group (InspectionGroupAgent — unified v2 agent)

import pytest
from unittest.mock import MagicMock

from models.routing_decision import RoutingDecision, TimeWindow
from models.query_template import QueryTemplate
from agents.sub_agents.template_agent import TemplateGroupAgent
from agents.sub_agents.inspection_group_agent import InspectionGroupAgent
from agents.agent_registry import get_group_agent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

INSPECTION_SIMPLE_ROUTING = RoutingDecision(
    primary_group="INSPECTION",
    user_scoped=True,
    entity_hint="inspection",
)

INSPECTION_ISSUE_ROUTING = RoutingDecision(
    primary_group="INSPECTION",
    user_scoped=True,
    entity_hint="task",
    status_filter="yetToStart",
    query_complexity="simple",
)

INSPECTION_OBS_ROUTING = RoutingDecision(
    primary_group="INSPECTION",
    user_scoped=True,
    entity_hint="inspectionObservation",
    time_window=TimeWindow(kind="thisWeek"),
    query_complexity="complex",
)

INSPECTION_RHISTORY_ROUTING = RoutingDecision(
    primary_group="INSPECTION",
    user_scoped=False,
    entity_hint="responseHistory",
    time_window=TimeWindow(kind="lastNDays", amount=7),
    query_complexity="complex",
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestGroupAgentRegistry:
    """Validates the group registry maps correctly."""

    def should_return_template_agent_for_template_group(self):
        agent = get_group_agent("TEMPLATE")
        assert isinstance(agent, TemplateGroupAgent)

    def should_return_inspection_agent_for_inspection_group(self):
        agent = get_group_agent("INSPECTION")
        assert isinstance(agent, InspectionGroupAgent)

    def should_raise_value_error_for_old_scheduling_group(self):
        with pytest.raises(ValueError, match="No group agent registered"):
            get_group_agent("SCHEDULING")

    def should_raise_value_error_for_old_execution_group(self):
        with pytest.raises(ValueError, match="No group agent registered"):
            get_group_agent("EXECUTION")

    def should_raise_value_error_for_old_task_group(self):
        with pytest.raises(ValueError, match="No group agent registered"):
            get_group_agent("TASK")

    def should_raise_value_error_for_unknown_group(self):
        with pytest.raises(ValueError):
            get_group_agent("UNKNOWN")

    def should_return_correct_group_name_for_each_registered_agent(self):
        assert get_group_agent("TEMPLATE").get_group_name() == "TEMPLATE"
        assert get_group_agent("INSPECTION").get_group_name() == "INSPECTION"


# ---------------------------------------------------------------------------
# YAML loading — INSPECTION group
# ---------------------------------------------------------------------------

class TestInspectionGroupYamlLoading:
    """Validates the unified INSPECTION YAML structure."""

    def should_load_inspection_yaml_with_all_required_keys(self):
        agent = InspectionGroupAgent()
        prompt = agent._load_group_prompt("INSPECTION")
        for key in ("group", "group_rules", "entity_schemas", "dedup_block",
                    "query_patterns", "relationships", "routing_contract", "common_mistakes"):
            assert key in prompt, f"Missing key: '{key}'"

    def should_register_10_entities_in_inspection_group(self):
        agent = InspectionGroupAgent()
        prompt = agent._load_group_prompt("INSPECTION")
        expected = {
            "inspection", "checklist", "section", "question", "execution",
            "responseHistory", "inspectionObservation", "task", "taskObservation", "report",
        }
        assert set(prompt["entities"]) == expected

    def should_confirm_inspection_is_the_group_name(self):
        agent = InspectionGroupAgent()
        prompt = agent._load_group_prompt("INSPECTION")
        assert prompt["group"] == "INSPECTION"


# ---------------------------------------------------------------------------
# System prompt assembly — INSPECTION group
# ---------------------------------------------------------------------------

class TestInspectionSystemPromptAssembly:
    """Validates _build_system produces the correct system prompt content."""

    def should_include_shared_base_role_section(self):
        agent = InspectionGroupAgent()
        system = agent._build_system(INSPECTION_SIMPLE_ROUTING)
        assert "ROLE & TASK" in system

    def should_include_mandatory_dedup_block(self):
        agent = InspectionGroupAgent()
        system = agent._build_system(INSPECTION_RHISTORY_ROUTING)
        assert "MANDATORY DEDUP" in system

    def should_include_p5a_issue_pattern(self):
        agent = InspectionGroupAgent()
        system = agent._build_system(INSPECTION_ISSUE_ROUTING)
        assert "P5a" in system

    def should_include_p5b_observation_pattern(self):
        agent = InspectionGroupAgent()
        system = agent._build_system(INSPECTION_OBS_ROUTING)
        assert "P5b" in system

    def should_include_report_entity(self):
        agent = InspectionGroupAgent()
        system = agent._build_system(INSPECTION_SIMPLE_ROUTING)
        assert "report" in system

    def should_include_critical_mistake_isresolved_rule(self):
        """isResolved is on taskObservation, NOT inspectionObservation — must be in prompt."""
        agent = InspectionGroupAgent()
        system = agent._build_system(INSPECTION_ISSUE_ROUTING)
        assert "isResolved" in system

    def should_include_scheduling_rule_scheduledate_on_inspection_only(self):
        agent = InspectionGroupAgent()
        system = agent._build_system(INSPECTION_SIMPLE_ROUTING)
        assert "scheduleDate" in system

    def should_include_routing_contract_section(self):
        agent = InspectionGroupAgent()
        system = agent._build_system(INSPECTION_SIMPLE_ROUTING)
        assert "ROUTING CONTRACT" in system


# ---------------------------------------------------------------------------
# Fallback templates — INSPECTION group
# ---------------------------------------------------------------------------

class TestInspectionFallbackTemplate:
    """Edge cases for the no-LLM fallback path."""

    @pytest.mark.parametrize("hint,user_scoped", [
        ("inspection",              True),
        ("task",                    True),
        ("inspectionObservation",   False),
        ("responseHistory",         False),
        ("report",                  False),
        (None,                      False),   # None hint → defaults to group.lower()
    ])
    def should_produce_valid_query_template_for_each_entity_hint(self, hint, user_scoped):
        routing = RoutingDecision(
            primary_group="INSPECTION",
            user_scoped=user_scoped,
            entity_hint=hint,
        )
        agent = InspectionGroupAgent()
        template = agent._fallback_template(routing)

        assert isinstance(template, QueryTemplate)
        assert template.query_type == "aggregate"
        assert "tenantId" in template.placeholders_used
        assert "{tenantId}" in str(template.pipeline)
        if user_scoped:
            assert "userId" in template.placeholders_used

    def should_use_entity_hint_as_fallback_entity_type(self):
        routing = RoutingDecision(primary_group="INSPECTION", entity_hint="task")
        agent = InspectionGroupAgent()
        template = agent._fallback_template(routing)
        assert template.entity_type == "task"

    def should_fall_back_to_group_lowercase_when_entity_hint_is_none(self):
        routing = RoutingDecision(primary_group="INSPECTION")
        agent = InspectionGroupAgent()
        template = agent._fallback_template(routing)
        assert template.entity_type == "inspection"


# ---------------------------------------------------------------------------
# LLM integration (mocked) — INSPECTION group
# ---------------------------------------------------------------------------

class TestInspectionAgentGenerate:
    """Mocked LLM generate() — happy path, error path, no-client path."""

    _VALID_RESPONSE = """{
        "query_type": "aggregate",
        "database": "FLATNEW",
        "collection": "entities",
        "entity_type": "inspection",
        "filter": {},
        "pipeline": [
            {"$match": {"type": "inspection", "tenantId": "{tenantId}",
                         "assignedTo": "{userId}", "isDeleted": false}},
            {"$project": {"_id": 0, "inspectionId": "$_id", "title": 1,
                           "status": 1, "scheduleDate": 1}}
        ],
        "userfield": "assignedTo",
        "userfield_reason": "default for inspection",
        "placeholders_used": ["tenantId", "userId"],
        "explanation": "List inspections assigned to user."
    }"""

    @pytest.mark.asyncio
    async def should_return_query_template_from_valid_llm_json(self):
        agent = InspectionGroupAgent()
        agent._llm = MagicMock()
        agent._llm.client = True
        agent._llm.generate_json = MagicMock(return_value=self._VALID_RESPONSE)

        template = await agent.generate(
            routing=INSPECTION_SIMPLE_ROUTING,
            user_query="Show my inspections",
            tenant_id="t1",
            user_id="u1",
        )

        assert template.query_type == "aggregate"
        assert template.entity_type == "inspection"
        assert template.userfield == "assignedTo"

    @pytest.mark.asyncio
    async def should_return_fallback_template_when_llm_raises_exception(self):
        agent = InspectionGroupAgent()
        agent._llm = MagicMock()
        agent._llm.client = True
        agent._llm.generate_json = MagicMock(side_effect=RuntimeError("LLM offline"))

        template = await agent.generate(
            routing=INSPECTION_ISSUE_ROUTING,
            user_query="Show my open issues",
            tenant_id="t1",
            user_id="u1",
        )

        assert isinstance(template, QueryTemplate)
        assert "{tenantId}" in str(template.pipeline)

    @pytest.mark.asyncio
    async def should_return_fallback_template_when_no_llm_client(self):
        agent = InspectionGroupAgent()
        agent._llm = MagicMock()
        agent._llm.client = None

        template = await agent.generate(
            routing=INSPECTION_OBS_ROUTING,
            user_query="Show observations this week",
            tenant_id="t1",
            user_id=None,
        )

        assert isinstance(template, QueryTemplate)
        assert template.query_type == "aggregate"

    @pytest.mark.asyncio
    async def should_use_entity_hint_in_fallback_for_responsehistory(self):
        agent = InspectionGroupAgent()
        agent._llm = MagicMock()
        agent._llm.client = None

        template = await agent.generate(
            routing=INSPECTION_RHISTORY_ROUTING,
            user_query="Most failed questions last week",
            tenant_id="t1",
            user_id=None,
        )

        assert template.entity_type == "responseHistory"
