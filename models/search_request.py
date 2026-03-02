from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class SearchRequest(BaseModel):
    """
    Search request payload (Pydantic: query, tenantId, userId, filters)
    """
    query: str = Field(..., description="The natural language query from the user.")
    tenantId: str = Field("", description="The tenant ID of the user's organization.")
    userId: str = Field("", description="The distinct user ID making the request.")
    filters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional filters for the search.")
