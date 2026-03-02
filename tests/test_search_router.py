# tests/test_search_router.py
# Integration tests for the /api/v1/ai/ask endpoint.

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from models.search_response import SearchResponse, ResultGroup


def _mock_response(**kwargs) -> SearchResponse:
    return SearchResponse(
        summary=kwargs.get("summary", "Found 0 results."),
        total_count=kwargs.get("total_count", 0),
        groups=kwargs.get("groups", []),
        metadata={"channels_queried": [], "query_time_ms": 1},
    )


@pytest.fixture(scope="module")
def client():
    """
    Creates a TestClient with DB + orchestrator mocked out so tests run without
    a live MongoDB instance or API key.
    """
    with patch("db.client.DatabaseConnector.connect", new_callable=AsyncMock), \
         patch("db.client.DatabaseConnector.close",   new_callable=AsyncMock), \
         patch("db.client.DatabaseConnector.get_db",  return_value=MagicMock()):
        from main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

def test_should_return_200_when_valid_query(client):
    """Endpoint returns HTTP 200 for a well-formed request."""
    payload = {"query": "Show me all inspections", "tenantId": "t1", "userId": "u1"}

    with patch("core.orchestrator.SearchOrchestrator.search",
               new_callable=AsyncMock,
               return_value=_mock_response(summary="Found 0 results.")):
        resp = client.post("/api/v1/ai/ask", json=payload)

    assert resp.status_code == 200


def test_should_stream_json_body_when_valid_query(client):
    """Response body contains valid SearchResponse JSON keys."""
    payload = {"query": "Show me all checklists", "tenantId": "t1", "userId": "u1"}
    mock_resp = _mock_response(
        summary="Found 2 results.",
        total_count=2,
        groups=[ResultGroup(entity_type="checklist", count=2, items=[{"title": "A"}, {"title": "B"}])],
    )

    with patch("core.orchestrator.SearchOrchestrator.search",
               new_callable=AsyncMock,
               return_value=mock_resp):
        resp = client.post("/api/v1/ai/ask", json=payload)

    body = json.loads(resp.text.strip())
    assert "summary"     in body
    assert "total_count" in body
    assert "groups"      in body
    assert "metadata"    in body


def test_should_accept_request_without_optional_fields(client):
    """tenantId and userId are optional — default to empty string without error."""
    payload = {"query": "List all tasks"}

    with patch("core.orchestrator.SearchOrchestrator.search",
               new_callable=AsyncMock,
               return_value=_mock_response()):
        resp = client.post("/api/v1/ai/ask", json=payload)

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Validation / error-path tests
# ---------------------------------------------------------------------------

def test_should_return_422_when_query_field_missing(client):
    """FastAPI returns 422 Unprocessable Entity when required `query` field is absent."""
    resp = client.post("/api/v1/ai/ask", json={"tenantId": "t1", "userId": "u1"})
    assert resp.status_code == 422


def test_should_return_403_when_service_raises_value_error(client):
    """Router maps ValueError from the service/orchestrator to HTTP 403."""
    payload = {"query": "bad query", "tenantId": "t1", "userId": "u1"}

    with patch("core.orchestrator.SearchOrchestrator.search",
               new_callable=AsyncMock,
               side_effect=ValueError("Access denied")):
        resp = client.post("/api/v1/ai/ask", json=payload)

    assert resp.status_code == 403
    assert "Access denied" in resp.json()["detail"]


def test_should_return_500_when_service_raises_unexpected_error(client):
    """Router maps unknown exceptions to HTTP 500."""
    payload = {"query": "crash", "tenantId": "t1", "userId": "u1"}

    with patch("core.orchestrator.SearchOrchestrator.search",
               new_callable=AsyncMock,
               side_effect=RuntimeError("Something went wrong")):
        resp = client.post("/api/v1/ai/ask", json=payload)

    assert resp.status_code == 500
