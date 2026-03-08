# tests/test_routing_decision.py
# Tests for the RoutingDecision model (T1 classifier output contract).

import pytest
from pydantic import ValidationError

from api.models.routing_decision import RoutingDecision, TimeWindow


class TestRoutingDecisionValidation:
    """Happy-path and edge-case validation for RoutingDecision."""

    def should_create_minimal_routing_decision_when_only_primary_group_given(self):
        rd = RoutingDecision(primary_group="SCHEDULING")
        assert rd.primary_group == "SCHEDULING"
        assert rd.secondary_groups == []
        assert rd.user_scoped is False
        assert rd.query_complexity == "simple"
        assert rd.time_field is None
        assert rd.time_window is None
        assert rd.status_filter is None
        assert rd.entity_hint is None

    def should_build_all_groups_list_with_primary_first_when_secondary_groups_present(self):
        rd = RoutingDecision(
            primary_group="TASK",
            secondary_groups=["SCHEDULING", "EXECUTION"],
        )
        assert rd.all_groups() == ["TASK", "SCHEDULING", "EXECUTION"]

    def should_accept_time_window_with_lastndays_and_amount(self):
        rd = RoutingDecision(
            primary_group="SCHEDULING",
            time_window=TimeWindow(kind="lastNDays", amount=30),
        )
        assert rd.time_window.kind == "lastNDays"
        assert rd.time_window.amount == 30

    def should_accept_time_window_without_amount_for_fixed_kinds(self):
        rd = RoutingDecision(
            primary_group="SCHEDULING",
            time_window=TimeWindow(kind="thisWeek"),
        )
        assert rd.time_window.amount is None

    def should_return_primary_only_in_all_groups_when_no_secondary(self):
        rd = RoutingDecision(primary_group="TEMPLATE")
        assert rd.all_groups() == ["TEMPLATE"]

    def should_accept_user_scoped_true_with_status_and_entity_hint(self):
        rd = RoutingDecision(
            primary_group="EXECUTION",
            user_scoped=True,
            status_filter="inProgress",
            entity_hint="responseHistory",
            query_complexity="complex",
        )
        assert rd.user_scoped is True
        assert rd.status_filter == "inProgress"
        assert rd.entity_hint == "responseHistory"
        assert rd.query_complexity == "complex"

    def should_raise_validation_error_when_primary_group_missing(self):
        with pytest.raises(ValidationError):
            RoutingDecision()


class TestTimeWindowValidation:
    """Validates TimeWindow edge cases."""

    def should_allow_all_valid_kind_values(self):
        for kind in ("today", "thisWeek", "thisMonth", "lastMonth", "YTD"):
            tw = TimeWindow(kind=kind)
            assert tw.kind == kind

    def should_allow_amount_to_be_none_by_default(self):
        tw = TimeWindow(kind="today")
        assert tw.amount is None
