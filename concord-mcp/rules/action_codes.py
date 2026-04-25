"""
Canonical ActionCode vocabulary for Concord.

This enum defines every action code that specialist workers may emit.
ComputeConflictMatrix operates on these codes deterministically.

Extensibility: if a specialist recommendation doesn't map to an existing code,
the worker's system prompt instructs it to use OUT_OF_CATALOG and put nuance
in free_text. ValidateFinalPlan flags OUT_OF_CATALOG as a warning.
"""

from enum import Enum


class ActionCode(str, Enum):
    # Diuresis
    UPTITRATE_LOOP_DIURETIC = "UPTITRATE_LOOP_DIURETIC"
    DOWNTITRATE_LOOP_DIURETIC = "DOWNTITRATE_LOOP_DIURETIC"
    HOLD_LOOP_DIURETIC_TEMPORARILY = "HOLD_LOOP_DIURETIC_TEMPORARILY"

    # RAAS / MRA
    HOLD_ACE_ARB_TEMPORARILY = "HOLD_ACE_ARB_TEMPORARILY"
    REDUCE_ACE_ARB_DOSE = "REDUCE_ACE_ARB_DOSE"
    HOLD_MRA_TEMPORARILY = "HOLD_MRA_TEMPORARILY"
    REVIEW_MRA_FOR_HYPERKALAEMIA = "REVIEW_MRA_FOR_HYPERKALAEMIA"

    # SGLT2 / other HF
    CONTINUE_SGLT2 = "CONTINUE_SGLT2"
    START_SGLT2 = "START_SGLT2"

    # Renal-safety / NSAIDs
    AVOID_NSAIDS = "AVOID_NSAIDS"
    SWITCH_NSAID_TO_PARACETAMOL = "SWITCH_NSAID_TO_PARACETAMOL"

    # Monitoring / re-assessment
    REPEAT_RENAL_PANEL_48H = "REPEAT_RENAL_PANEL_48H"
    REPEAT_RENAL_PANEL_1W = "REPEAT_RENAL_PANEL_1W"
    REPEAT_POTASSIUM_48H = "REPEAT_POTASSIUM_48H"
    DAILY_WEIGHTS = "DAILY_WEIGHTS"
    FLUID_BALANCE_MONITORING = "FLUID_BALANCE_MONITORING"
    REVIEW_IN_CLINIC_2W = "REVIEW_IN_CLINIC_2W"
    REVIEW_IN_CLINIC_4W = "REVIEW_IN_CLINIC_4W"

    # Investigation / deferral
    DEFER_CHANGE_PENDING_VOLUME_ASSESSMENT = "DEFER_CHANGE_PENDING_VOLUME_ASSESSMENT"
    REQUEST_BNP_NTPROBNP = "REQUEST_BNP_NTPROBNP"
    REQUEST_ECHO = "REQUEST_ECHO"

    # Escalation / coordination
    DISCUSS_WITH_HF_SPECIALIST = "DISCUSS_WITH_HF_SPECIALIST"
    DISCUSS_WITH_NEPHROLOGY = "DISCUSS_WITH_NEPHROLOGY"

    # Counselling
    COUNSEL_ON_AKI_RISK = "COUNSEL_ON_AKI_RISK"
    COUNSEL_ON_SICK_DAY_RULES = "COUNSEL_ON_SICK_DAY_RULES"

    # Fallback for out-of-catalog specialist recommendations
    OUT_OF_CATALOG = "OUT_OF_CATALOG"


# Pairs of directly opposing action codes (used by ComputeConflictMatrix)
# If both codes appear for the same drug class in the same episode → direct_conflict
OPPOSING_PAIRS: list[tuple[ActionCode, ActionCode]] = [
    (ActionCode.UPTITRATE_LOOP_DIURETIC, ActionCode.DOWNTITRATE_LOOP_DIURETIC),
    (ActionCode.UPTITRATE_LOOP_DIURETIC, ActionCode.HOLD_LOOP_DIURETIC_TEMPORARILY),
    (ActionCode.HOLD_ACE_ARB_TEMPORARILY, ActionCode.REDUCE_ACE_ARB_DOSE),
    (ActionCode.START_SGLT2, ActionCode.CONTINUE_SGLT2),  # not truly opposing but redundant
]

# Safety-priority codes — these are surfaced first in ranked_next_actions
SAFETY_PRIORITY_CODES: frozenset[ActionCode] = frozenset({
    ActionCode.AVOID_NSAIDS,
    ActionCode.SWITCH_NSAID_TO_PARACETAMOL,
    ActionCode.REVIEW_MRA_FOR_HYPERKALAEMIA,
    ActionCode.REPEAT_POTASSIUM_48H,
    ActionCode.REPEAT_RENAL_PANEL_48H,
    ActionCode.HOLD_ACE_ARB_TEMPORARILY,
    ActionCode.HOLD_MRA_TEMPORARILY,
})
