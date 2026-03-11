# models/search_request.py
# Pydantic model for the incoming API search request.

from pydantic import BaseModel, Field
from typing import Any, Dict, Optional


class SearchRequest(BaseModel):
    """
    Search request payload from the end-user.

    """
    query: str = Field(..., description="Natural language query from the user")
    tenantId: str = Field("", description="Tenant UUID for multi-tenant isolation")
    userId: str = Field("", description="User UUID for scoping")
    # limit: int = Field(default=50, ge=1, le=200)
    # time_zone: str = Field(default="UTC")
    # filters: Dict[str, Any] = Field(default_factory=dict, description="Optional pre-filters")
