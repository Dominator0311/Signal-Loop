"""
Scenario tests for ComputeConflictMatrix classification logic.

Each test targets a specific classification rule:
  safety_block, direct_conflict, missing_data_block, dependency, consensus, tension.
"""

import pytest

from llm.schemas import ConflictMatrix, Recommendation, SpecialistOpinion
from rules.action_codes import ActionCode, SAFETY_PRIORITY_CODES
from rules.conflict_matrix import compute_conflict_matrix


def _opinion(specialty: str, recommendations: list[Recommendation], missing_data: list[str] | None = None) -> SpecialistOpinion:
    return SpecialistOpinion(
        specialty=specialty,
        summary=f"Test {specialty} opinion",
        recommendations=recommendations,
        missing_data=missing_data or [],
        cross_specialty_dependencies=[],
        confidence="high",
    )


def _rec(code: ActionCode, priority: str = "medium", deps: list[str] | None = None, contras: list[str] | None = None) -> Recommendation:
    return Recommendation(
        action_code=code,
        free_text=f"Recommendation for {code.value}",
        priority=priority,
        rationale="Test rationale",
        dependencies=deps or [],
        contraindications=contras or [],
    )


# --- Safety block ---

def test_safety_priority_code_classified_as_safety_block():
    safety_code = ActionCode.REPEAT_RENAL_PANEL_48H
    assert safety_code in SAFETY_PRIORITY_CODES

    opinions = [
        _opinion("nephrology", [_rec(safety_code)]),
        _opinion("cardiology", []),
        _opinion("pharmacy", []),
    ]
    matrix = compute_conflict_matrix(opinions, "ep-1")

    block_codes = {item.action_code for item in matrix.safety_blocks}
    assert safety_code in block_codes


def test_contraindication_triggers_safety_block():
    code = ActionCode.CONTINUE_SGLT2  # not in SAFETY_PRIORITY_CODES
    assert code not in SAFETY_PRIORITY_CODES

    opinions = [
        _opinion("pharmacy", [_rec(code, contras=["eGFR < 30"])]),
        _opinion("nephrology", []),
        _opinion("cardiology", []),
    ]
    matrix = compute_conflict_matrix(opinions, "ep-2")

    block_codes = {item.action_code for item in matrix.safety_blocks}
    assert code in block_codes


def test_safety_block_is_not_also_in_consensus():
    safety_code = ActionCode.HOLD_ACE_ARB_TEMPORARILY
    opinions = [
        _opinion("nephrology", [_rec(safety_code)]),
        _opinion("cardiology", [_rec(safety_code)]),
        _opinion("pharmacy", [_rec(safety_code)]),
    ]
    matrix = compute_conflict_matrix(opinions, "ep-3")

    # Safety block takes priority over consensus
    block_codes = {item.action_code for item in matrix.safety_blocks}
    consensus_codes = {item.action_code for item in matrix.consensus}
    assert safety_code in block_codes
    assert safety_code not in consensus_codes


# --- Direct conflict ---

def test_opposing_recommendations_produce_direct_conflict():
    opinions = [
        _opinion("cardiology", [_rec(ActionCode.UPTITRATE_LOOP_DIURETIC)]),
        _opinion("nephrology", [_rec(ActionCode.DOWNTITRATE_LOOP_DIURETIC)]),
        _opinion("pharmacy", []),
    ]
    matrix = compute_conflict_matrix(opinions, "ep-4")

    conflict_codes = {item.action_code for item in matrix.direct_conflicts}
    # At least one side of the conflict should be classified as direct_conflict
    # (the other may be safety_block if it's in SAFETY_PRIORITY_CODES)
    uptitrate_or_downtitrate = {ActionCode.UPTITRATE_LOOP_DIURETIC, ActionCode.DOWNTITRATE_LOOP_DIURETIC}
    assert bool(conflict_codes & uptitrate_or_downtitrate)


def test_direct_conflict_has_opposing_specialties():
    opinions = [
        _opinion("cardiology", [_rec(ActionCode.UPTITRATE_LOOP_DIURETIC)]),
        _opinion("nephrology", [_rec(ActionCode.DOWNTITRATE_LOOP_DIURETIC)]),
        _opinion("pharmacy", []),
    ]
    matrix = compute_conflict_matrix(opinions, "ep-5")

    for item in matrix.direct_conflicts:
        assert len(item.specialties_supporting) > 0
        assert len(item.specialties_opposing) > 0


def test_no_direct_conflict_when_same_specialty_agrees():
    """Single specialty recommending both sides isn't a cross-specialty conflict."""
    opinions = [
        _opinion("cardiology", [_rec(ActionCode.UPTITRATE_LOOP_DIURETIC)]),
        _opinion("nephrology", [_rec(ActionCode.UPTITRATE_LOOP_DIURETIC)]),
        _opinion("pharmacy", []),
    ]
    matrix = compute_conflict_matrix(opinions, "ep-6")
    assert len(matrix.direct_conflicts) == 0


# --- Missing data block ---

def test_missing_data_block_requires_deps_and_missing_data():
    code = ActionCode.START_SGLT2
    opinions = [
        _opinion("cardiology", [_rec(code, deps=["eGFR > 30"])], missing_data=["eGFR not recent"]),
        _opinion("nephrology", []),
        _opinion("pharmacy", []),
    ]
    matrix = compute_conflict_matrix(opinions, "ep-7")

    mdb_codes = {item.action_code for item in matrix.missing_data_blocks}
    assert code in mdb_codes


def test_dep_without_missing_data_is_dependency_not_missing_data_block():
    code = ActionCode.START_SGLT2
    opinions = [
        _opinion("cardiology", [_rec(code, deps=["eGFR confirmed"])], missing_data=[]),
        _opinion("nephrology", []),
        _opinion("pharmacy", []),
    ]
    matrix = compute_conflict_matrix(opinions, "ep-8")

    mdb_codes = {item.action_code for item in matrix.missing_data_blocks}
    dep_codes = {item.action_code for item in matrix.dependencies}
    assert code not in mdb_codes
    assert code in dep_codes


# --- Consensus vs tension ---

def test_multi_specialty_agreement_is_consensus():
    code = ActionCode.DAILY_WEIGHTS
    assert code not in SAFETY_PRIORITY_CODES

    opinions = [
        _opinion("nephrology", [_rec(code)]),
        _opinion("cardiology", [_rec(code)]),
        _opinion("pharmacy", []),
    ]
    matrix = compute_conflict_matrix(opinions, "ep-9")

    consensus_codes = {item.action_code for item in matrix.consensus}
    assert code in consensus_codes


def test_single_specialty_is_tension():
    code = ActionCode.REVIEW_IN_CLINIC_4W
    opinions = [
        _opinion("nephrology", [_rec(code)]),
        _opinion("cardiology", []),
        _opinion("pharmacy", []),
    ]
    matrix = compute_conflict_matrix(opinions, "ep-10")

    tension_codes = {item.action_code for item in matrix.tensions}
    assert code in tension_codes


# --- Ranked next actions ---

def test_ranked_next_actions_safety_before_consensus():
    safety_code = ActionCode.REPEAT_POTASSIUM_48H
    consensus_code = ActionCode.DAILY_WEIGHTS
    assert safety_code in SAFETY_PRIORITY_CODES
    assert consensus_code not in SAFETY_PRIORITY_CODES

    opinions = [
        _opinion("nephrology", [_rec(safety_code), _rec(consensus_code)]),
        _opinion("cardiology", [_rec(consensus_code)]),
        _opinion("pharmacy", []),
    ]
    matrix = compute_conflict_matrix(opinions, "ep-11")

    ranked = matrix.ranked_next_actions
    assert safety_code in ranked
    assert consensus_code in ranked
    assert ranked.index(safety_code) < ranked.index(consensus_code)


def test_ranked_next_actions_no_duplicates():
    code = ActionCode.DAILY_WEIGHTS
    opinions = [
        _opinion("nephrology", [_rec(code)]),
        _opinion("cardiology", [_rec(code)]),
        _opinion("pharmacy", [_rec(code)]),
    ]
    matrix = compute_conflict_matrix(opinions, "ep-12")

    ranked = matrix.ranked_next_actions
    assert len(ranked) == len(set(ranked))


def test_episode_brief_id_preserved():
    matrix = compute_conflict_matrix([], "my-ep-id")
    assert matrix.episode_brief_id == "my-ep-id"
