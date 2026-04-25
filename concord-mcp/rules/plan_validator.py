"""
ValidateFinalPlan — deterministic checks V01–V10, no LLM.

V01–V05: blocking issues → status='fail'
V06–V10: warnings → status='pass_with_warnings'
Only status 'pass' or 'pass_with_warnings' permits write-back.
"""

from medsafe_core.helpers import compute_due_date_from_timing

from llm.schemas import ConflictMatrix, PlanValidationResult, UnifiedPlan
from rules.action_codes import ActionCode, OPPOSING_PAIRS


_RAAS_DIURETIC_CODES: frozenset[ActionCode] = frozenset({
    ActionCode.HOLD_ACE_ARB_TEMPORARILY,
    ActionCode.REDUCE_ACE_ARB_DOSE,
    ActionCode.HOLD_MRA_TEMPORARILY,
    ActionCode.REVIEW_MRA_FOR_HYPERKALAEMIA,
    ActionCode.UPTITRATE_LOOP_DIURETIC,
    ActionCode.DOWNTITRATE_LOOP_DIURETIC,
    ActionCode.HOLD_LOOP_DIURETIC_TEMPORARILY,
})

_MONITORING_CODES: frozenset[ActionCode] = frozenset({
    ActionCode.REPEAT_RENAL_PANEL_48H,
    ActionCode.REPEAT_RENAL_PANEL_1W,
    ActionCode.REPEAT_POTASSIUM_48H,
    ActionCode.DAILY_WEIGHTS,
    ActionCode.FLUID_BALANCE_MONITORING,
})


def validate_final_plan(
    plan: UnifiedPlan,
    matrix: ConflictMatrix,
) -> PlanValidationResult:
    """
    Run V01–V10 deterministic validation checks.

    Returns PlanValidationResult with status 'pass', 'pass_with_warnings', or 'fail'.
    """
    blocking: list[str] = []
    warnings: list[str] = []

    draft_codes: frozenset[ActionCode] = frozenset(a.action_code for a in plan.draft_writes)

    safety_block_codes: frozenset[ActionCode] = frozenset(
        item.action_code for item in matrix.safety_blocks
    )
    missing_data_codes: frozenset[ActionCode] = frozenset(
        item.action_code for item in matrix.missing_data_blocks
    )

    # V01: MedicationRequest draft for a safety-critical action_code
    for action in plan.draft_writes:
        if action.resource_type == "MedicationRequest" and action.action_code in safety_block_codes:
            blocking.append(
                f"V01: MedicationRequest drafted for safety-critical action "
                f"'{action.action_code.value}'. Requires explicit safety review."
            )

    # V02: Both sides of a direct_conflict pair appear in draft_writes
    for a, b in OPPOSING_PAIRS:
        if a in draft_codes and b in draft_codes:
            blocking.append(
                f"V02: Conflicting actions both in draft_writes: "
                f"'{a.value}' and '{b.value}'. Resolve before proceeding."
            )

    # V03: Any DraftAction missing owner_confirmer
    for action in plan.draft_writes:
        if not (action.owner_confirmer and action.owner_confirmer.strip()):
            blocking.append(
                f"V03: Action '{action.action_code.value}' has no owner_confirmer assigned."
            )

    # V04: DraftAction for a missing_data_block code
    for action in plan.draft_writes:
        if action.action_code in missing_data_codes:
            blocking.append(
                f"V04: Action '{action.action_code.value}' depends on missing data. "
                f"Resolve data gaps before drafting."
            )

    # V05: Safety block not addressed in draft_writes or unresolved_questions
    for item in matrix.safety_blocks:
        in_drafts = item.action_code in draft_codes
        in_unresolved = any(
            item.action_code.value in q for q in plan.unresolved_questions
        )
        if not in_drafts and not in_unresolved:
            blocking.append(
                f"V05: Safety-critical action '{item.action_code.value}' is not present in "
                f"draft_writes or unresolved_questions. Every safety block must be explicitly handled."
            )

    # V06: Tensions exist but no monitoring Task in draft_writes
    if matrix.tensions:
        has_monitoring_task = any(
            action.resource_type == "Task" and action.action_code in _MONITORING_CODES
            for action in plan.draft_writes
        )
        if not has_monitoring_task:
            warnings.append(
                "V06: Unresolved tensions present but no monitoring Task in draft_writes. "
                "Add a monitoring action to track outcome."
            )

    # V07: RAAS/diuretic action present but no lab monitoring action
    has_raas_diuretic = any(a.action_code in _RAAS_DIURETIC_CODES for a in plan.draft_writes)
    has_monitoring = any(a.action_code in _MONITORING_CODES for a in plan.draft_writes)
    if has_raas_diuretic and not has_monitoring:
        warnings.append(
            "V07: RAAS, MRA, or diuretic action is planned but no lab monitoring is present. "
            "Add REPEAT_RENAL_PANEL_48H or REPEAT_POTASSIUM_48H."
        )

    # V08: Unparseable timing string
    for action in plan.draft_writes:
        if action.timing and compute_due_date_from_timing(action.timing) is None:
            warnings.append(
                f"V08: Action '{action.action_code.value}' has timing '{action.timing}' "
                f"that cannot be parsed into a due date. Use format like '2 weeks' or '48 hours'."
            )

    # V09: missing_data_blocks exist but unresolved_questions is empty
    if matrix.missing_data_blocks and not plan.unresolved_questions:
        warnings.append(
            "V09: Conflict matrix has missing_data_blocks but unresolved_questions is empty. "
            "Document the data gaps as unresolved questions."
        )

    # V10: Always — reminder to call LogConsensusDecision
    warnings.append(
        "V10: Call LogConsensusDecision to persist the validated plan for audit trail."
    )

    if blocking:
        return PlanValidationResult(
            status="fail",
            blocking_issues=blocking,
            warnings=warnings,
            validated_plan=None,
        )

    return PlanValidationResult(
        status="pass_with_warnings" if warnings else "pass",
        blocking_issues=[],
        warnings=warnings,
        validated_plan=plan,
    )
