# presentation/models/query_template.py
#
# QueryTemplate  — validated output from a T2 domain agent (LLM response).
# InspectionQueryTemplate — inspection-specific extension.
#
# DESIGN RULES:
#   - This model represents ONLY what the LLM returns.
#   - Runtime values (database, collection, resolved pipeline) are NEVER here.
#   - Domain-specific fields live in subclasses, not the base model.
#   - Adding a new domain agent = add a subclass. Base model never changes.
#
# SCALING PATTERN:
#   For a new domain agent (e.g. DASHBOARD):
#     class DashboardQueryTemplate(QueryTemplate):
#         breakdown_field: Optional[str] = None
#         aggregation_type: Literal["count", "sum", "avg"] = "count"

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


# ── Time window ───────────────────────────────────────────────────────────────

class TimeWindow(BaseModel):
    """
    Relative time window used in a query.

    @param kind:   Named window type.
    @param amount: Unit count — required for 'lastNDays' and 'lastNYears'.
                   Must be None for all other kinds.
    """
    kind: Literal[
        "lastNDays", "today", "thisWeek", "thisMonth",
        "lastMonth", "thisYear", "lastNYears", "nextNDays",
        "YTD", "overdue",
    ]
    amount: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def amount_required_for_variable_kinds(self) -> TimeWindow:
        variable_kinds = {"lastNDays", "lastNYears", "nextNDays"}
        if self.kind in variable_kinds and self.amount is None:
            raise ValueError(f"'amount' is required when kind='{self.kind}'")
        if self.kind not in variable_kinds and self.amount is not None:
            raise ValueError(f"'amount' must be None when kind='{self.kind}'")
        return self


# ── Base query template ───────────────────────────────────────────────────────

class QueryTemplate(BaseModel):
    """
    LLM output from a T2 domain agent.
    Contains a MongoDB aggregation pipeline with runtime placeholders.

    Placeholders resolved at runtime by placeholder_resolver:
      {tenantId}           — always required
      {userId}             — present when user_scoped=True
      {TIME_WINDOW_START}  — present when time_window is set
      {TIME_WINDOW_END}    — present when time_window is set

    @param entity_type:  SEYO entity type discriminator (e.g. 'inspection').
    @param pipeline:     MongoDB aggregation pipeline with placeholder strings.
    @param filter:       Simple find filter — only valid when query_type='find'.
                         Converted to [{$match: filter}] by the orchestrator.
    @param time_field:   Field the time_window applies to (e.g. 'createdAt').
    @param time_window:  Parsed time window description.
    @param userfield:    Field used for user scoping (e.g. 'assignedTo').
    @param explanation:  One-line LLM reasoning for debugging.
    """

    entity_type: str
    pipeline: List[Dict[str, Any]] = Field(default_factory=list)
    filter: Dict[str, Any] = Field(default_factory=dict)
    time_field: Optional[str] = None
    time_window: Optional[TimeWindow] = None
    userfield: Optional[str] = None
    explanation: str = ""

    @model_validator(mode="after")
    def pipeline_or_filter_required(self) -> QueryTemplate:
        """At least one of pipeline or filter must be non-empty."""
        if not self.pipeline and not self.filter:
            raise ValueError(
                "QueryTemplate must contain either a non-empty 'pipeline' "
                "or a non-empty 'filter'."
            )
        return self


# ── Domain-specific extensions ────────────────────────────────────────────────

class InspectionQueryTemplate(QueryTemplate):
    """
    Inspection-domain extension of QueryTemplate.
    Adds fields specific to inspection scoring and response deduplication.

    @param deduplication_applied: True when dedup stages were added.
    @param scoring_applied:       True when scoring logic was added.
    @param scoring_mode:          How scoring was computed.
    """
    deduplication_applied: bool = False
    scoring_applied: bool = False
    scoring_mode: Optional[Literal["relative", "threshold"]] = None


class WorkflowQueryTemplate(QueryTemplate):
    """
    Workflow-domain extension of QueryTemplate.
    Extend with workflow-specific fields as needed.
    """
    pass