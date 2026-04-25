"""
Unit tests for ComputeConflictMatrix (Phase 2 stubs).

Phase 1: tests verify the stub returns valid ConflictMatrix shape.
Phase 2: tests will verify full classification logic with real opinions.
"""

import pytest

from llm.schemas import ConflictMatrix, SpecialistOpinion
from rules.conflict_matrix import compute_conflict_matrix


def _make_empty_opinion(specialty: str) -> SpecialistOpinion:
    return SpecialistOpinion(
        specialty=specialty,
        summary=f"Test {specialty} opinion",
        recommendations=[],
        missing_data=[],
        cross_specialty_dependencies=[],
        confidence="high",
    )


def test_stub_returns_conflict_matrix():
    opinions = [
        _make_empty_opinion("nephrology"),
        _make_empty_opinion("cardiology"),
        _make_empty_opinion("pharmacy"),
    ]
    matrix = compute_conflict_matrix(opinions, episode_brief_id="test-id-1")
    assert isinstance(matrix, ConflictMatrix)
    assert matrix.episode_brief_id == "test-id-1"


def test_stub_has_list_fields():
    opinions = [_make_empty_opinion(s) for s in ("nephrology", "cardiology", "pharmacy")]
    matrix = compute_conflict_matrix(opinions, episode_brief_id="test-id-2")
    assert isinstance(matrix.consensus, list)
    assert isinstance(matrix.tensions, list)
    assert isinstance(matrix.direct_conflicts, list)
    assert isinstance(matrix.dependencies, list)
    assert isinstance(matrix.missing_data_blocks, list)
    assert isinstance(matrix.safety_blocks, list)
    assert isinstance(matrix.ranked_next_actions, list)


def test_stub_with_empty_opinions_produces_empty_matrix():
    opinions = [_make_empty_opinion(s) for s in ("nephrology", "cardiology", "pharmacy")]
    matrix = compute_conflict_matrix(opinions, episode_brief_id="test-id-3")
    # Stub returns all-empty lists — Phase 2 will populate
    total_items = (
        len(matrix.consensus)
        + len(matrix.tensions)
        + len(matrix.direct_conflicts)
        + len(matrix.dependencies)
        + len(matrix.missing_data_blocks)
        + len(matrix.safety_blocks)
    )
    assert total_items == 0  # stub: no classification yet
