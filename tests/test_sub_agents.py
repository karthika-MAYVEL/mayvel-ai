# tests/test_sub_agents.py
# Unit tests for ChecklistAgent and InspectionAgent (Stage 2).
# All LLM calls are mocked — no live API key required.

import json
import pytest
from unittest.mock import MagicMock, patch

from models.channel_plan import IndependentChannel, ScopeHints, ChainChannel
from models.query_template import QueryTemplate

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_independent(entity_type: str, userfield: str = None, keywords: list = None) -> IndependentChannel:
    return IndependentChannel(
        entity_type=entity_type,
        scope_hints=ScopeHints(userfield=userfield, keywords=keywords or []),
        reason="test",
    )


def _mock_llm(response_dict: dict) -> MagicMock:
    mock = MagicMock()
    mock.client = MagicMock()  # non-None → real path taken
    mock.generate_json.return_value = json.dumps(response_dict)
    return mock


def _no_key_llm() -> MagicMock:
    mock = MagicMock()
    mock.client = None  # no API key
    return mock


def _error_llm() -> MagicMock:
    mock = MagicMock()
    mock.client = MagicMock()
    mock.generate_json.side_effect = RuntimeError("LLM timeout")
    return mock


_CHECKLIST_TEMPLATE = {
    "query_type": "aggregate",
    "database": "FLATNEW",
    "collection": "entities",
    "entity_type": "checklist",
    "filter": {},
    "pipeline": [
        {"$match": {"type": "checklist", "tenantId": "{tenantId}", "createdBy": "{userId}", "isDeleted": False}},
        {"$project": {"_id": 0, "checklistId": "$_id", "title": 1, "description": 1, "isLibrary": 1, "createdAt": 1}},
    ],
    "userfield": "createdBy",
    "userfield_reason": "checklist uses createdBy",
    "deduplication_applied": False,
    "scoring_applied": False,
    "placeholders_used": ["tenantId", "userId"],
    "explanation": "My checklists scoped by createdBy",
}

_INSPECTION_TEMPLATE = {
    "query_type": "aggregate",
    "database": "FLATNEW",
    "collection": "entities",
    "entity_type": "inspection",
    "filter": {},
    "pipeline": [
        {"$match": {"type": "inspection", "tenantId": "{tenantId}", "assignedTo": "{userId}", "isDeleted": False}},
        {"$project": {"_id": 0, "inspectionId": "$_id", "title": 1, "status": 1, "createdAt": 1}},
    ],
    "userfield": "assignedTo",
    "userfield_reason": "default inspection userfield",
    "deduplication_applied": False,
    "scoring_applied": False,
    "placeholders_used": ["tenantId", "userId"],
    "explanation": "My inspections",
}


# ===========================================================================
# ChecklistAgent Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_should_return_valid_query_template_for_checklist_query():
    """Happy path: ChecklistAgent returns a valid QueryTemplate for a checklist query."""
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.checklist_agent import ChecklistAgent
        agent = ChecklistAgent()
        agent._llm = _mock_llm(_CHECKLIST_TEMPLATE)

    channel = _make_independent("checklist", userfield="createdBy")
    result = await agent.generate(channel, "Show my checklists")

    assert QueryTemplate.model_validate(result.model_dump())
    assert result.entity_type == "checklist"
    assert result.query_type == "aggregate"


@pytest.mark.asyncio
async def test_should_include_tenant_and_user_placeholders_in_checklist_pipeline():
    """Checklist pipeline must contain {tenantId} and {userId} placeholder strings."""
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.checklist_agent import ChecklistAgent
        agent = ChecklistAgent()
        agent._llm = _mock_llm(_CHECKLIST_TEMPLATE)

    channel = _make_independent("checklist", userfield="createdBy")
    result = await agent.generate(channel, "Show my checklists")

    pipeline_str = json.dumps(result.pipeline)
    assert "{tenantId}" in pipeline_str
    assert "{userId}" in pipeline_str
    assert "tenantId" in result.placeholders_used


@pytest.mark.asyncio
async def test_should_return_fallback_template_for_checklist_when_no_api_key():
    """Checklist agent returns a valid QueryTemplate fallback when no API key configured."""
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.checklist_agent import ChecklistAgent
        agent = ChecklistAgent()
        agent._llm = _no_key_llm()

    channel = _make_independent("checklist", userfield="createdBy")
    result = await agent.generate(channel, "Show my checklists")

    assert QueryTemplate.model_validate(result.model_dump())
    assert result.entity_type == "checklist"
    assert "{tenantId}" in json.dumps(result.pipeline)


# ===========================================================================
# InspectionAgent Tests
# ===========================================================================

@pytest.mark.asyncio
async def test_should_return_valid_query_template_for_inspection_query():
    """Happy path: InspectionAgent returns a valid QueryTemplate for an inspection query."""
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.inspection_agent import InspectionAgent
        agent = InspectionAgent()
        agent._llm = _mock_llm(_INSPECTION_TEMPLATE)

    channel = _make_independent("inspection", userfield="assignedTo")
    result = await agent.generate(channel, "Show my inspections")

    assert QueryTemplate.model_validate(result.model_dump())
    assert result.entity_type == "inspection"
    assert result.userfield == "assignedTo"


@pytest.mark.asyncio
async def test_should_inject_checklist_context_into_inspection_pipeline():
    """When a checklistId context keyword is provided, the pipeline should reference it."""
    checklist_id = "507f1f77bcf86cd799439011"
    template_with_context = {**_INSPECTION_TEMPLATE, "pipeline": [
        {"$match": {"type": "inspection", "tenantId": "{tenantId}", "checklistId": checklist_id, "isDeleted": False}},
        {"$project": {"_id": 0, "inspectionId": "$_id", "title": 1, "createdAt": 1}},
    ]}
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.inspection_agent import InspectionAgent
        agent = InspectionAgent()
        agent._llm = _mock_llm(template_with_context)

    channel = _make_independent("inspection", keywords=[f"checklistId:{checklist_id}"])
    result = await agent.generate(channel, "Inspections for fire safety checklist")

    assert checklist_id in json.dumps(result.pipeline)


@pytest.mark.asyncio
async def test_should_return_fallback_template_for_inspection_when_no_api_key():
    """Inspection agent returns a valid QueryTemplate fallback when no API key configured."""
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.inspection_agent import InspectionAgent
        agent = InspectionAgent()
        agent._llm = _no_key_llm()

    channel = _make_independent("inspection", userfield="assignedTo")
    result = await agent.generate(channel, "Show my inspections")

    assert QueryTemplate.model_validate(result.model_dump())
    assert result.entity_type == "inspection"
    assert "{tenantId}" in json.dumps(result.pipeline)


@pytest.mark.asyncio
async def test_should_return_fallback_template_when_llm_raises_error():
    """When the LLM raises an exception, both agents return a valid fallback (no crash)."""
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.checklist_agent import ChecklistAgent
        from agents.sub_agents.inspection_agent import InspectionAgent
        c_agent = ChecklistAgent()
        i_agent = InspectionAgent()
        c_agent._llm = _error_llm()
        i_agent._llm = _error_llm()

    c_channel = _make_independent("checklist")
    i_channel = _make_independent("inspection")

    c_result = await c_agent.generate(c_channel, "bad query")
    i_result = await i_agent.generate(i_channel, "bad query")

    assert QueryTemplate.model_validate(c_result.model_dump())
    assert QueryTemplate.model_validate(i_result.model_dump())
    assert c_result.entity_type == "checklist"
    assert i_result.entity_type == "inspection"
