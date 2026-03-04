# models/routing_decision.py
# RoutingDecision: Pydantic model for T1 classifier output.
# Replaces the entity-level ChannelPlan with a group-level routing contract.

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

# Valid domain group names as specified in the T1/T2 architecture.
VALID_GROUPS = frozenset({"TEMPLATE", "SCHEDULING", "EXECUTION", "TASK"})

# Valid time-window kind values.
VALID_TIME_KINDS = frozenset({
    "today", "thisWeek", "thisMonth", "lastMonth", "lastNDays", "YTD",
})


class TimeWindow(BaseModel):
    """Time constraint extracted from the user query."""

    kind: str = Field(..., description="One of: today|thisWeek|thisMonth|lastMonth|lastNDays|YTD")
    amount: Optional[int] = Field(
        default=None,
        description="Number of days — required only for kind='lastNDays'.",
    )


class RoutingDecision(BaseModel):
    """
    T1 classifier output: routes a user query to a primary domain group
    and zero or more secondary groups, plus extracted query context.

    @param primary_group: Main domain group to handle the query.
    @param secondary_groups: Additional groups needed for cross-group queries.
    @param user_scoped: Whether the query must be filtered to the current user.
    @param query_complexity: 'simple' (find/count) or 'complex' (multi-lookup/aggregate).
    @param time_field: Which date field to apply the time window on, or None.
    @param time_window: Extracted time constraint, or None if no time filter.
    @param status_filter: Status string to filter on, or None.
    @param entity_hint: Specific entity type hint within the primary group, or None.
    """

    primary_group: str = Field(
        ...,
        description="Primary domain group: TEMPLATE|SCHEDULING|EXECUTION|TASK",
    )
    secondary_groups: list[str] = Field(
        default_factory=list,
        description="Additional groups required for cross-group joins.",
    )
    user_scoped: bool = Field(
        default=False,
        description="True when the query targets the current user's data.",
    )
    query_complexity: str = Field(
        default="simple",
        description="'simple' for find/count, 'complex' for multi-stage pipelines.",
    )
    time_field: Optional[str] = Field(
        default=None,
        description="Date field to apply time window on (e.g. scheduleDate, createdAt).",
    )
    time_window: Optional[TimeWindow] = Field(
        default=None,
        description="Extracted time constraint from the user query.",
    )
    status_filter: Optional[str] = Field(
        default=None,
        description="Status value to filter on (e.g. 'inProgress'), or None.",
    )
    entity_hint: Optional[str] = Field(
        default=None,
        description="Specific entity type hint within the primary group.",
    )

    def all_groups(self) -> list[str]:
        """
        Returns primary group plus all secondary groups in order.

        @returns: Ordered list of all groups involved in this routing decision.
        """
        return [self.primary_group, *self.secondary_groups]
