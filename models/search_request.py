# models/search_request.py
# Pydantic model for the incoming API search request.

from pydantic import BaseModel, Field
from typing import Any, Dict, Optional


class SearchRequest(BaseModel):
    """
    Search request payload from the end-user.

    @param query: Natural language query
    @param tenantId: Tenant UUID for multi-tenant isolation
    @param userId: User UUID for user-scoped queries
    # @param limit: Maximum number of results (1–200)
    # @param time_zone: IANA time zone string, used to interpret relative time expressions
    # @param filters: Optional pre-filters applied before the LLM pipeline
    """
    query: str = Field(..., description="Natural language query from the user")
    tenantId: str = Field("", description="Tenant UUID for multi-tenant isolation")
    userId: str = Field("", description="User UUID for scoping")
    # limit: int = Field(default=50, ge=1, le=200)
    # time_zone: str = Field(default="UTC")
    # filters: Dict[str, Any] = Field(default_factory=dict, description="Optional pre-filters")
