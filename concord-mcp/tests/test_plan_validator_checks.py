"""
Tests for ValidateFinalPlan V01–V10 checks.

Each test targets a specific check, verifying that blocking issues and warnings
fire correctly with real ConflictMatrix and UnifiedPlan inputs.
"""

import pytest

from llm.schemas import (
    ConflictItem,
    ConflictMatrix,
    DraftAction,
    PlanValidationResult,
    Recommendation,
    SpecialistOpinion,
    UnifiedPlan,
)
from rules.action_codes import ActionCode
from rules.plan_validator import validate_final_plan


def _minimal_matrix(
    safety_blocks: list[ConflictItem] | None = None,
    direct_conflicts: list[ConflictItem] | None = None,
    tensions: list[ConflictItem] | None = None,
    missing_data_blocks: list[ConflictItem] | None = None,
    episode_brief_id: str = "ep-test",
) -> ConflictMatrix:
    return ConflictMatrix(
        consensus=[],
        tensions=tensions or [],
        direct_conflicts=direct_conflicts or [],
        dependencies=[],
        missing_data_blocks=missing_data_blocks or [],
        safety_blocks=safety_blocks or [],
        ranked_next_actions=[],
        episode_brief_id=episode_brief_id,
    )


def _minimal_plan(
    draft_writes: list[DraftAction] | None = None,
    unresolved_questions: list[str] | None = None,
) -> UnifiedPlan:
    return UnifiedPlan(
        decision_summary="Test plan",
        agreed_actions_now=[],
        actions_pending_confirmation=[],
        unresolved_questions=unresolved_questions or [],
        patient_safe_explanation="Test explanation",
        draft_writes=draft_writes or [],
        episode_brief_id="ep-test",
        specialist_task_ids={},
    )


def _draft(code: ActionCode, resource_type: str = "Task", owner: str = "Dr Smith", timing: str | None = None) -> DraftAction:
    return DraftAction(
        action_code=code,
        resource_type=resource_type,
        description=f"Draft for {code.value}",
        owner_confirmer=owner,
        timing=timing,
    )


def _safety_item(code: ActionCode) -> ConflictItem:
    return ConflictItem(
        action_code=code,
        specialties_supporting=["nephrology"],
        specialties_opposing=[],
        resolution="safety_block",
        severity="high",
        notes="Test safety block",
    )


def _conflict_item(code: ActionCode) -> ConflictItem:
    return ConflictItem(
        action_code=code,
        specialties_supporting=["cardiology"],
        specialties_opposing=["nephrology"],
        resolution="direct_conflict",
        severity="high",
        notes="Test conflict",
    )


def _tension_item(code: ActionCode) -> ConflictItem:
    return ConflictItem(
        action_code=code,
        specialties_supporting=["cardiology"],
        specialties_opposing=[],
        resolution="tension",
        severity="low",
        notes="Test tension",
    )


def _missing_data_item(code: ActionCode) -> ConflictItem:
    return ConflictItem(
        action_code=code,
        specialties_supporting=["nephrology"],
        specialties_opposing=[],
        resolution="missing_data_block",
        severity="medium",
        notes="Missing data",
    )


# --- V10 always fires ---

def test_v10_always_warns():
    result = validate_final_plan(_minimal_plan(), _minimal_matrix())
    assert any("V10" in w for w in result.warnings)


# --- Status on clean plan ---

def test_clean_plan_empty_matrix_is_pass_with_warnings():
    result = validate_final_plan(_minimal_plan(), _minimal_matrix())
    assert result.status == "pass_with_warnings"  # V10 always warns


# --- V01: MedicationRequest for safety-critical code ---

def test_v01_medication_request_for_safety_block_is_blocking():
    safety_code = ActionCode.HOLD_ACE_ARB_TEMPORARILY
    matrix = _minimal_matrix(safety_blocks=[_safety_item(safety_code)])
    plan = _minimal_plan(draft_writes=[_draft(safety_code, resource_type="MedicationRequest")])

    result = validate_final_plan(plan, matrix)
    assert result.status == "fail"
    assert any("V01" in issue for issue in result.blocking_issues)


def test_v01_task_for_safety_block_does_not_trigger():
    safety_code = ActionCode.HOLD_ACE_ARB_TEMPORARILY
    matrix = _minimal_matrix(safety_blocks=[_safety_item(safety_code)])
    # Task is fine — V05 will check if it's addressed at all
    plan = _minimal_plan(draft_writes=[_draft(safety_code, resource_type="Task")])

    result = validate_final_plan(plan, matrix)
    assert not any("V01" in issue for issue in result.blocking_issues)


# --- V02: Both sides of direct_conflict in draft_writes ---

def test_v02_opposing_pair_both_in_draft_is_blocking():
    plan = _minimal_plan(draft_writes=[
        _draft(ActionCode.UPTITRATE_LOOP_DIURETIC),
        _draft(ActionCode.DOWNTITRATE_LOOP_DIURETIC),
    ])
    result = validate_final_plan(plan, _minimal_matrix())
    assert result.status == "fail"
    assert any("V02" in issue for issue in result.blocking_issues)


def test_v02_only_one_side_of_pair_is_fine():
    plan = _minimal_plan(draft_writes=[_draft(ActionCode.UPTITRATE_LOOP_DIURETIC)])
    result = validate_final_plan(plan, _minimal_matrix())
    assert not any("V02" in issue for issue in result.blocking_issues)


# --- V03: Missing owner_confirmer ---

def test_v03_missing_owner_confirmer_is_blocking():
    plan = _minimal_plan(draft_writes=[_draft(ActionCode.DAILY_WEIGHTS, owner="")])
    result = validate_final_plan(plan, _minimal_matrix())
    assert result.status == "fail"
    assert any("V03" in issue for issue in result.blocking_issues)


def test_v03_whitespace_only_owner_is_blocking():
    plan = _minimal_plan(draft_writes=[_draft(ActionCode.DAILY_WEIGHTS, owner="   ")])
    result = validate_final_plan(plan, _minimal_matrix())
    assert any("V03" in issue for issue in result.blocking_issues)


def test_v03_valid_owner_does_not_trigger():
    plan = _minimal_plan(draft_writes=[_draft(ActionCode.DAILY_WEIGHTS, owner="Dr Jones")])
    result = validate_final_plan(plan, _minimal_matrix())
    assert not any("V03" in issue for issue in result.blocking_issues)


# --- V04: Draft for missing_data_block code ---

def test_v04_draft_for_missing_data_code_is_blocking():
    code = ActionCode.START_SGLT2
    matrix = _minimal_matrix(missing_data_blocks=[_missing_data_item(code)])
    plan = _minimal_plan(draft_writes=[_draft(code)])
    result = validate_final_plan(plan, matrix)
    assert result.status == "fail"
    assert any("V04" in issue for issue in result.blocking_issues)


# --- V05: Safety block not addressed ---

def test_v05_safety_block_absent_from_plan_is_blocking():
    safety_code = ActionCode.REPEAT_RENAL_PANEL_48H
    matrix = _minimal_matrix(safety_blocks=[_safety_item(safety_code)])
    plan = _minimal_plan()  # no draft_writes, no unresolved_questions

    result = validate_final_plan(plan, matrix)
    assert result.status == "fail"
    assert any("V05" in issue for issue in result.blocking_issues)


def test_v05_safety_block_in_draft_writes_is_fine():
    safety_code = ActionCode.REPEAT_RENAL_PANEL_48H
    matrix = _minimal_matrix(safety_blocks=[_safety_item(safety_code)])
    plan = _minimal_plan(draft_writes=[_draft(safety_code)])

    result = validate_final_plan(plan, matrix)
    assert not any("V05" in issue for issue in result.blocking_issues)


def test_v05_safety_block_in_unresolved_questions_is_fine():
    safety_code = ActionCode.REPEAT_RENAL_PANEL_48H
    matrix = _minimal_matrix(safety_blocks=[_safety_item(safety_code)])
    plan = _minimal_plan(unresolved_questions=[f"Should we add {safety_code.value} now?"])

    result = validate_final_plan(plan, matrix)
    assert not any("V05" in issue for issue in result.blocking_issues)


# --- V06: Tensions without monitoring task ---

def test_v06_tension_without_monitoring_warns():
    matrix = _minimal_matrix(tensions=[_tension_item(ActionCode.REVIEW_IN_CLINIC_2W)])
    plan = _minimal_plan()  # no monitoring task

    result = validate_final_plan(plan, matrix)
    assert any("V06" in w for w in result.warnings)


def test_v06_tension_with_monitoring_task_no_warn():
    matrix = _minimal_matrix(tensions=[_tension_item(ActionCode.REVIEW_IN_CLINIC_2W)])
    plan = _minimal_plan(draft_writes=[_draft(ActionCode.DAILY_WEIGHTS, resource_type="Task")])

    result = validate_final_plan(plan, matrix)
    assert not any("V06" in w for w in result.warnings)


# --- V07: RAAS/diuretic without monitoring ---

def test_v07_raas_without_monitoring_warns():
    plan = _minimal_plan(draft_writes=[_draft(ActionCode.HOLD_ACE_ARB_TEMPORARILY)])
    # HOLD_ACE_ARB_TEMPORARILY is also a safety block code — need to address V05 too
    matrix = _minimal_matrix(safety_blocks=[_safety_item(ActionCode.HOLD_ACE_ARB_TEMPORARILY)])

    # Plan addresses V05 via draft_writes, so only V07 fires
    result = validate_final_plan(plan, matrix)
    assert any("V07" in w for w in result.warnings)


def test_v07_diuretic_with_monitoring_no_warn():
    plan = _minimal_plan(draft_writes=[
        _draft(ActionCode.UPTITRATE_LOOP_DIURETIC),
        _draft(ActionCode.REPEAT_RENAL_PANEL_48H),
    ])
    result = validate_final_plan(plan, _minimal_matrix())
    assert not any("V07" in w for w in result.warnings)


# --- V08: Unparseable timing ---

def test_v08_bad_timing_warns():
    plan = _minimal_plan(draft_writes=[_draft(ActionCode.DAILY_WEIGHTS, timing="ASAP")])
    result = validate_final_plan(plan, _minimal_matrix())
    assert any("V08" in w for w in result.warnings)


def test_v08_valid_timing_no_warn():
    plan = _minimal_plan(draft_writes=[_draft(ActionCode.DAILY_WEIGHTS, timing="2 weeks")])
    result = validate_final_plan(plan, _minimal_matrix())
    assert not any("V08" in w for w in result.warnings)


# --- V09: missing_data_blocks without unresolved_questions ---

def test_v09_missing_data_without_unresolved_warns():
    code = ActionCode.REQUEST_ECHO
    matrix = _minimal_matrix(missing_data_blocks=[_missing_data_item(code)])
    plan = _minimal_plan()  # no unresolved_questions
    # V04 would fire if we draft the code, so we don't draft it here
    result = validate_final_plan(plan, matrix)
    assert any("V09" in w for w in result.warnings)


def test_v09_missing_data_with_unresolved_no_warn():
    code = ActionCode.REQUEST_ECHO
    matrix = _minimal_matrix(missing_data_blocks=[_missing_data_item(code)])
    plan = _minimal_plan(unresolved_questions=["Echo not yet available — defer decision"])
    result = validate_final_plan(plan, matrix)
    assert not any("V09" in w for w in result.warnings)


# --- validated_plan only returned on pass/pass_with_warnings ---

def test_validated_plan_none_on_fail():
    plan = _minimal_plan(draft_writes=[_draft(ActionCode.DAILY_WEIGHTS, owner="")])
    result = validate_final_plan(plan, _minimal_matrix())
    assert result.status == "fail"
    assert result.validated_plan is None


def test_validated_plan_returned_on_pass_with_warnings():
    plan = _minimal_plan()
    result = validate_final_plan(plan, _minimal_matrix())
    assert result.status == "pass_with_warnings"
    assert result.validated_plan is not None
    assert result.validated_plan.episode_brief_id == "ep-test"
