# tests/test_task_agent.py
# Unit tests for TaskAgent (Stage 3).
# All LLM calls are mocked — no live API key required.

import json
import pytest
from unittest.mock import MagicMock, patch

from models.channel_plan import IndependentChannel, ScopeHints
from models.query_template import QueryTemplate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_channel(userfield: str = "assignedTo", status: str = None) -> IndependentChannel:
    return IndependentChannel(
        entity_type="task",
        scope_hints=ScopeHints(userfield=userfield, status_filter=status),
        reason="test",
    )


def _mock_llm(response_dict: dict) -> MagicMock:
    mock = MagicMock()
    mock.client = MagicMock()
    mock.generate_json.return_value = json.dumps(response_dict)
    return mock


def _no_key_llm() -> MagicMock:
    mock = MagicMock()
    mock.client = None
    return mock


def _error_llm() -> MagicMock:
    mock = MagicMock()
    mock.client = MagicMock()
    mock.generate_json.side_effect = RuntimeError("LLM timeout")
    return mock


_TASK_TEMPLATE = {
    "query_type": "aggregate",
    "database": "FLATNEW",
    "collection": "entities",
    "entity_type": "task",
    "filter": {},
    "pipeline": [
        {"$match": {"type": "task", "tenantId": "{tenantId}", "assignedTo": "{userId}", "isDeleted": False}},
        {"$project": {"_id": 0, "taskId": "$_id", "title": 1, "status": 1, "assignedTo": 1, "createdAt": 1}},
    ],
    "userfield": "assignedTo",
    "userfield_reason": "default task userfield",
    "deduplication_applied": False,
    "scoring_applied": False,
    "placeholders_used": ["tenantId", "userId"],
    "explanation": "My tasks scoped by assignedTo",
}

_TASK_TEMPLATE_STATUS = {
    **_TASK_TEMPLATE,
    "pipeline": [
        {"$match": {"type": "task", "tenantId": "{tenantId}", "assignedTo": "{userId}", "status": "inProgress", "isDeleted": False}},
        {"$project": {"_id": 0, "taskId": "$_id", "title": 1, "status": 1, "assignedTo": 1, "createdAt": 1}},
    ],
    "explanation": "In-progress tasks for user",
}

_TASK_TEMPLATE_CREATED_BY = {
    **_TASK_TEMPLATE,
    "pipeline": [
        {"$match": {"type": "task", "tenantId": "{tenantId}", "createdBy": "{userId}", "isDeleted": False}},
        {"$project": {"_id": 0, "taskId": "$_id", "title": 1, "status": 1, "createdAt": 1}},
    ],
    "userfield": "createdBy",
    "userfield_reason": "explicit creator intent",
    "explanation": "Tasks created by me",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_return_valid_query_template_for_task_query():
    """Happy path: TaskAgent returns a valid QueryTemplate with entity_type='task'."""
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.task_agent import TaskAgent
        agent = TaskAgent()
        agent._llm = _mock_llm(_TASK_TEMPLATE)

    result = await agent.generate(_make_channel(), "Show my tasks")

    assert QueryTemplate.model_validate(result.model_dump())
    assert result.entity_type == "task"
    assert result.query_type == "aggregate"


@pytest.mark.asyncio
async def test_should_include_tenant_and_user_placeholders_in_task_pipeline():
    """Task pipeline must contain {tenantId} and {userId} placeholder strings."""
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.task_agent import TaskAgent
        agent = TaskAgent()
        agent._llm = _mock_llm(_TASK_TEMPLATE)

    result = await agent.generate(_make_channel(), "Show my tasks")

    pipeline_str = json.dumps(result.pipeline)
    assert "{tenantId}" in pipeline_str
    assert "{userId}" in pipeline_str
    assert "tenantId" in result.placeholders_used


@pytest.mark.asyncio
async def test_should_filter_by_status_string_without_lookup():
    """Task status is a string — no $lookup stage should appear for status filtering."""
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.task_agent import TaskAgent
        agent = TaskAgent()
        agent._llm = _mock_llm(_TASK_TEMPLATE_STATUS)

    result = await agent.generate(_make_channel(status="inProgress"), "Show my in-progress tasks")

    pipeline_str = json.dumps(result.pipeline)
    assert "inProgress" in pipeline_str
    # Must NOT have a $lookup stage for status
    assert "$lookup" not in pipeline_str


@pytest.mark.asyncio
async def test_should_use_created_by_when_explicit_creator_intent():
    """TaskAgent switches userfield to 'createdBy' when creator intent is present."""
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.task_agent import TaskAgent
        agent = TaskAgent()
        agent._llm = _mock_llm(_TASK_TEMPLATE_CREATED_BY)

    result = await agent.generate(_make_channel(userfield="createdBy"), "Tasks I created")

    assert result.userfield == "createdBy"
    assert "createdBy" in json.dumps(result.pipeline)


@pytest.mark.asyncio
async def test_should_return_fallback_template_when_no_api_key():
    """TaskAgent returns a valid QueryTemplate fallback when no API key configured."""
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.task_agent import TaskAgent
        agent = TaskAgent()
        agent._llm = _no_key_llm()

    result = await agent.generate(_make_channel(), "Show my tasks")

    assert QueryTemplate.model_validate(result.model_dump())
    assert result.entity_type == "task"
    assert "{tenantId}" in json.dumps(result.pipeline)


@pytest.mark.asyncio
async def test_should_return_fallback_template_when_llm_raises_error():
    """When LLM raises an error, TaskAgent returns a valid fallback (no crash)."""
    with patch("llm_sdk.gemini.GeminiClient"):
        from agents.sub_agents.task_agent import TaskAgent
        agent = TaskAgent()
        agent._llm = _error_llm()

    result = await agent.generate(_make_channel(), "bad query")

    assert QueryTemplate.model_validate(result.model_dump())
    assert result.entity_type == "task"
