"""
Unit tests for ValidateFinalPlan (Phase 2 stubs).

Phase 1: tests verify the stub returns valid PlanValidationResult shape.
Phase 2: tests will verify all V01–V10 checks individually.
"""

import pytest

from llm.schemas import ConflictMatrix, PlanValidationResult, UnifiedPlan
from rules.plan_validator import validate_final_plan


def _make_minimal_plan() -> UnifiedPlan:
    return UnifiedPlan(
        decision_summary="Test plan",
        agreed_actions_now=[],
        actions_pending_confirmation=[],
        unresolved_questions=[],
        patient_safe_explanation="Test patient explanation",
        draft_writes=[],
        episode_brief_id="test-episode-1",
        specialist_task_ids={},
    )


def _make_minimal_matrix() -> ConflictMatrix:
    return ConflictMatrix(
        consensus=[],
        tensions=[],
        direct_conflicts=[],
        dependencies=[],
        missing_data_blocks=[],
        safety_blocks=[],
        ranked_next_actions=[],
        episode_brief_id="test-episode-1",
    )


def test_stub_returns_plan_validation_result():
    plan = _make_minimal_plan()
    matrix = _make_minimal_matrix()
    result = validate_final_plan(plan, matrix)
    assert isinstance(result, PlanValidationResult)


def test_stub_status_is_valid():
    plan = _make_minimal_plan()
    matrix = _make_minimal_matrix()
    result = validate_final_plan(plan, matrix)
    assert result.status in ("pass", "pass_with_warnings", "fail")


def test_stub_has_list_fields():
    plan = _make_minimal_plan()
    matrix = _make_minimal_matrix()
    result = validate_final_plan(plan, matrix)
    assert isinstance(result.blocking_issues, list)
    assert isinstance(result.warnings, list)


def test_stub_preserves_plan():
    plan = _make_minimal_plan()
    matrix = _make_minimal_matrix()
    result = validate_final_plan(plan, matrix)
    # Stub returns pass_with_warnings with original plan
    if result.validated_plan is not None:
        assert result.validated_plan.episode_brief_id == plan.episode_brief_id
