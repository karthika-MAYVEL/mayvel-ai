# models/query_template.py
# Pydantic models for Sub-Agent output — QueryTemplate and nested TimeWindow.

from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional


class TimeWindow(BaseModel):
    """
    Describes a relative time window used in a query.

    @param kind: Named window type
    @param amount: Number of units (only for 'lastNDays')
    """
    kind: Literal[
        "lastNDays", "today", "thisWeek", "thisMonth", "lastMonth", "YTD", 
        "lastNYears", "thisYear", "nextNDays", "overdue"
    ]
    amount: Optional[int] = None


class QueryTemplate(BaseModel):
    """
    Output from a Sub-Agent: a MongoDB query template with placeholder strings.
    Placeholders ({tenantId}, {userId}, {NOW}) are resolved by the assembler at runtime.

    @param query_type: 'find' | 'aggregate'
    @param database: Target database name
    @param collection: Always 'entities' for the unified collection
    @param entity_type: SEYO entity type discriminator
    @param filter: Simple find filter (used when query_type='find')
    @param pipeline: Aggregation pipeline stages (used when query_type='aggregate')
    @param time_field: Which field the time_window applies to
    @param time_window: Parsed time window description
    @param userfield: Which field was used for user scoping
    @param userfield_reason: Why that userfield was chosen
    @param deduplication_applied: True when dedup pipeline stages were added (responseHistory)
    @param scoring_applied: True when scoring logic was added (responseHistory)
    @param scoring_mode: 'relative' | 'threshold' | None
    @param placeholders_used: Which placeholder strings are present in the pipeline
    @param explanation: One-line LLM reasoning
    @param executable_pipeline: Filled by the assembler — real values substituted
    """
    query_type: Literal["find", "aggregate"]
    database: str = "FLATNEW"
    collection: str = "entities"
    entity_type: str
    filter: Dict[str, Any] = Field(default_factory=dict)
    pipeline: List[Dict[str, Any]] = Field(default_factory=list)
    time_field: Optional[str] = None
    time_window: Optional[TimeWindow] = None
    userfield: Optional[str] = None
    userfield_reason: str = ""
    deduplication_applied: bool = False
    scoring_applied: bool = False
    scoring_mode: Optional[Literal["relative", "threshold"]] = None
    placeholders_used: List[str] = Field(default_factory=list)
    explanation: str = ""
    # Runtime — filled by assembler, never by the sub-agent
    executable_pipeline: Optional[List[Dict[str, Any]]] = None
