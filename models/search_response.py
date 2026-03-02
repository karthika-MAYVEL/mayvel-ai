# models/search_response.py
# Pydantic models for the API response returned to end-users.

from pydantic import BaseModel, Field
from typing import Any, Dict, List


class ResultGroup(BaseModel):
    """
    A grouped block of results for a single entity type.

    @param entity_type: SEYO entity type e.g. 'task' | 'inspection'
    @param count: Number of documents in this group
    @param items: The actual result documents
    """
    entity_type: str
    count: int
    items: List[Dict[str, Any]] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """
    Top-level API response for a search query.

    @param summary: Human-readable summary of the results
    @param total_count: Total number of documents across all groups
    @param groups: Result groups, one per entity type queried
    @param metadata: Diagnostic metadata (channels_queried, query_time_ms, etc.)
    """
    summary: str = ""
    total_count: int = 0
    groups: List[ResultGroup] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
