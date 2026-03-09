# tests/test_search_router.py
# Integration tests for the /api/v1/ai/ask endpoint.

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from presentation.models.search_response import SearchResponse, ResultGroup
from application.services.search_service import SearchService
from infrastructure.database.database import get_db

def _mock_response(**kwargs) -> dict:
    return {
        "success": True,
        "data": kwargs.get("data", []),
        "meta": kwargs.get("meta", {"query_time_ms": 1}),
        "error": None
    }


@pytest.fixture(scope="module")
def client():
    """
    Creates a TestClient with DB + orchestrator mocked out so tests run without
    a live MongoDB instance or API key.
    """
    from main import app
    
    async def override_get_db():
        yield MagicMock()
        
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
        
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

def test_should_return_200_when_valid_query(client):
    """Endpoint returns HTTP 200 for a well-formed request."""
    payload = {"query": "Show me all inspections", "tenantId": "t1", "userId": "u1"}

    with patch("application.services.search_service.SearchService.search",
               new_callable=AsyncMock,
               return_value=_mock_response(data=[])):
        resp = client.post("/api/v1/ai/ask", json=payload)

    assert resp.status_code == 200


def test_should_stream_json_body_when_valid_query(client):
    """Response body contains valid SearchResponse JSON keys."""
    payload = {"query": "Show me all checklists", "tenantId": "t1", "userId": "u1"}
    mock_resp = _mock_response(
        data=[{"title": "A"}, {"title": "B"}]
    )

    with patch("application.services.search_service.SearchService.search",
               new_callable=AsyncMock,
               return_value=mock_resp):
        resp = client.post("/api/v1/ai/ask", json=payload)

    body = json.loads(resp.text.strip())
    assert "success" in body
    assert "data"    in body
    assert "meta"    in body
    assert "error"   in body


def test_should_accept_request_without_optional_fields(client):
    """tenantId and userId are optional — default to empty string without error."""
    payload = {"query": "List all tasks"}

    with patch("application.services.search_service.SearchService.search",
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


def test_should_return_500_when_service_raises_unexpected_error(client):
    """Router maps unknown exceptions to HTTP 500."""
    payload = {"query": "crash", "tenantId": "t1", "userId": "u1"}

    with patch("application.services.search_service.SearchService.search",
               new_callable=AsyncMock,
               side_effect=RuntimeError("Something went wrong")):
        resp = client.post("/api/v1/ai/ask", json=payload)

    assert resp.status_code == 500
