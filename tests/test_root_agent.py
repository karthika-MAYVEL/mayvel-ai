# tests/test_root_agent.py
# Unit tests for the RootAgent.plan() method — spec roadmap Phase 1 test cases.
# All LLM calls are mocked; no live API key required.

import json
import pytest
from unittest.mock import MagicMock, patch

from models.channel_plan import ChannelPlan
from models.search_request import SearchRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(query: str) -> SearchRequest:
    return SearchRequest(query=query, tenantId="t1", userId="u1")


def _mock_llm_response(channel_plan_dict: dict):
    """Returns a mock GeminiClient whose generate_json returns the given dict as JSON."""
    mock = MagicMock()
    mock.client = MagicMock()  # non-None so real path is taken
    mock.generate_json.return_value = json.dumps(channel_plan_dict)
    return mock


async def _plan(query: str, mock_response: dict) -> ChannelPlan:
    from agents.root_agent import RootAgent
    agent = RootAgent()
    agent._llm = _mock_llm_response(mock_response)
    return await agent.plan(_make_request(query))


# ---------------------------------------------------------------------------
# T1 — "Show my tasks this week"
# Expected: independent=[task], userfield=assignedTo, time_window.kind=thisWeek
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_classify_task_query_with_user_scope_and_time_window():
    """Root Agent classifies a user-scoped weekly task query correctly."""
    llm_response = {
        "independent": [{
            "entity_type": "task",
            "scope_hints": {"userfield": "assignedTo", "time_window": {"kind": "thisWeek"}, "status_filter": None, "keywords": []},
            "reason": "task has assignedTo directly; thisWeek maps to createdAt window",
        }],
        "chains": [],
        "coverage_reason": "Single independent entity match",
        "original_query": "Show my tasks this week",
    }
    result = await _plan("Show my tasks this week", llm_response)

    assert ChannelPlan.model_validate(result.model_dump())  # structurally valid
    assert len(result.independent) == 1
    assert result.independent[0].entity_type == "task"
    assert result.independent[0].scope_hints.userfield == "assignedTo"
    assert result.independent[0].scope_hints.time_window == {"kind": "thisWeek"}
    assert result.chains == []


# ---------------------------------------------------------------------------
# T2 — "Show all checklists"
# Expected: independent=[checklist], userfield=null (tenant-wide)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_classify_tenant_wide_checklist_query_with_no_user_scope():
    """Root Agent omits userId scope when no possessive is present."""
    llm_response = {
        "independent": [{
            "entity_type": "checklist",
            "scope_hints": {"userfield": None, "time_window": None, "status_filter": None, "keywords": []},
            "reason": "No possessive detected — tenant-wide checklist query",
        }],
        "chains": [],
        "coverage_reason": "Tenant-wide checklist listing",
        "original_query": "Show all checklists",
    }
    result = await _plan("Show all checklists", llm_response)

    assert ChannelPlan.model_validate(result.model_dump())
    assert len(result.independent) == 1
    assert result.independent[0].entity_type == "checklist"
    assert result.independent[0].scope_hints.userfield is None
    assert result.chains == []


# ---------------------------------------------------------------------------
# T3 — "What is my inspection compliance score for last 30 days?"
# Expected: chains=[responseHistory→execution→inspection], userfield=assignedTo, lastNDays 30
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_classify_scoring_query_as_response_history_chain():
    """Root Agent emits a responseHistory chain for scoring/compliance queries."""
    llm_response = {
        "independent": [],
        "chains": [{
            "root_entity": "responseHistory",
            "chain": ["responseHistory", "execution", "inspection"],
            "scope_hints": {"userfield": "assignedTo", "time_window": {"kind": "lastNDays", "amount": 30}, "status_filter": None, "keywords": ["compliance", "score"]},
            "reason": "Scoring query requires full responseHistory chain",
        }],
        "coverage_reason": "Scoring query requires full responseHistory chain",
        "original_query": "What is my inspection compliance score for last 30 days?",
    }
    result = await _plan("What is my inspection compliance score for last 30 days?", llm_response)

    assert ChannelPlan.model_validate(result.model_dump())
    assert result.independent == []
    assert len(result.chains) == 1
    chain = result.chains[0]
    assert chain.root_entity == "responseHistory"
    assert chain.chain == ["responseHistory", "execution", "inspection"]
    assert chain.scope_hints.userfield == "assignedTo"
    assert chain.scope_hints.time_window == {"kind": "lastNDays", "amount": 30}


# ---------------------------------------------------------------------------
# T4 — "Show inspections for the fire safety checklist"
# Expected: independent=[inspection], checklist treated as a keyword filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_classify_inspection_query_with_checklist_keyword_as_filter():
    """Root Agent routes checklist-filtered inspection queries to inspection channel."""
    llm_response = {
        "independent": [{
            "entity_type": "inspection",
            "scope_hints": {"userfield": None, "time_window": None, "status_filter": None, "keywords": ["fire safety checklist"]},
            "reason": "Query targets inspections; checklist is a filter keyword",
        }],
        "chains": [],
        "coverage_reason": "Inspection query filtered by checklist keyword",
        "original_query": "Show inspections for the fire safety checklist",
    }
    result = await _plan("Show inspections for the fire safety checklist", llm_response)

    assert ChannelPlan.model_validate(result.model_dump())
    assert len(result.independent) == 1
    assert result.independent[0].entity_type == "inspection"
    assert "fire safety checklist" in result.independent[0].scope_hints.keywords


# ---------------------------------------------------------------------------
# Fallback / error-path tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_return_valid_channel_plan_when_llm_returns_invalid_json():
    """When LLM returns garbage, fallback heuristic still returns a valid ChannelPlan."""
    from agents.root_agent import RootAgent
    agent = RootAgent()
    mock_llm = MagicMock()
    mock_llm.client = MagicMock()
    mock_llm.generate_json.return_value = "NOT VALID JSON {{{"
    agent._llm = mock_llm

    result = await agent.plan(_make_request("Show my tasks"))

    assert ChannelPlan.model_validate(result.model_dump())
    # Should still return either a chain or an independent channel
    assert len(result.independent) + len(result.chains) >= 1


@pytest.mark.asyncio
async def test_should_use_fallback_heuristic_when_no_llm_key():
    """When GeminiClient has no client (no API key), fallback plan is returned."""
    from agents.root_agent import RootAgent
    agent = RootAgent()
    mock_llm = MagicMock()
    mock_llm.client = None  # simulates missing API key
    agent._llm = mock_llm

    result = await agent.plan(_make_request("Show my tasks this week"))

    assert ChannelPlan.model_validate(result.model_dump())
    assert result.original_query == "Show my tasks this week"
