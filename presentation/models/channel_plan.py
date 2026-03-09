# models/channel_plan.py
# Pydantic models for Root Agent output — ChannelPlan and its components.

from pydantic import BaseModel, Field
from typing import List, Optional


class ScopeHints(BaseModel):
    """
    Scope hints extracted by the Root Agent to help sub-agents build correct queries.

    @param userfield: 'assignedTo' | 'createdBy' | None (None = tenant-wide, no user scope)
    @param time_window: e.g. { kind: 'lastNDays', amount: 7 }
    @param status_filter: e.g. 'inProgress' | 'completed' | None
    @param keywords: Any domain keywords extracted from the query
    """
    userfield: Optional[str] = None
    time_window: Optional[dict] = None
    status_filter: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)


class IndependentChannel(BaseModel):
    """
    A single-entity channel that can be executed independently against MongoDB.

    @param entity_type: SEYO entity type e.g. 'inspection' | 'task' | 'checklist'
    @param scope_hints: Scope constraints for the sub-agent query
    @param reason: Why this entity was selected
    """
    entity_type: str
    scope_hints: ScopeHints = Field(default_factory=ScopeHints)
    reason: str


class ChainChannel(BaseModel):
    """
    A multi-hop channel where entities are queried in sequence to resolve the request.

    @param root_entity: Entry point of the chain (the agent that generates the first query)
    @param chain: Full hop sequence e.g. ['responseHistory', 'execution', 'inspection']
    @param scope_hints: Scope constraints applied to the root of the chain
    @param reason: Why this chain was selected
    """
    root_entity: str
    chain: List[str]
    scope_hints: ScopeHints = Field(default_factory=ScopeHints)
    reason: str


class ChannelPlan(BaseModel):
    """
    Complete Root Agent output: a structured plan of which channels to query.

    @param independent: List of single-entity channels
    @param chains: List of multi-hop chain channels
    @param coverage_reason: Explanation of the overall channel selection
    @param original_query: The verbatim user query
    """
    independent: List[IndependentChannel] = Field(default_factory=list)
    chains: List[ChainChannel] = Field(default_factory=list)
    coverage_reason: str = ""
    original_query: str = ""
