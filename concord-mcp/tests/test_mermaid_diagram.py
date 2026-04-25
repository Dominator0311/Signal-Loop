"""
Tests for the Mermaid conflict-matrix diagram generator in tools/run_consult.py.

These exercise the pure function `_build_mermaid_diagram` over:
  - empty matrix → empty string
  - mixed-resolution matrix → all four CSS classes appear
  - oversized matrix → "+N more" overflow node
  - syntactic shape (flowchart TD header, classDef declarations, fenced block)
"""

from __future__ import annotations

import pytest

from llm.schemas import ConflictItem, ConflictMatrix
from rules.action_codes import ActionCode
from tools.run_consult import (
    _MERMAID_MAX_NODES,
    _build_mermaid_diagram,
    _node_label,
)


def _item(
    code: ActionCode,
    resolution: str,
    *,
    severity: str = "low",
    supporting: list[str] | None = None,
) -> ConflictItem:
    return ConflictItem(
        action_code=code,
        specialties_supporting=supporting or ["nephrology"],
        specialties_opposing=[],
        resolution=resolution,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        notes=f"test note for {code.value}",
    )


def _matrix(
    *,
    consensus: list[ConflictItem] | None = None,
    tensions: list[ConflictItem] | None = None,
    direct_conflicts: list[ConflictItem] | None = None,
    dependencies: list[ConflictItem] | None = None,
    missing_data_blocks: list[ConflictItem] | None = None,
    safety_blocks: list[ConflictItem] | None = None,
) -> ConflictMatrix:
    return ConflictMatrix(
        consensus=consensus or [],
        tensions=tensions or [],
        direct_conflicts=direct_conflicts or [],
        dependencies=dependencies or [],
        missing_data_blocks=missing_data_blocks or [],
        safety_blocks=safety_blocks or [],
        ranked_next_actions=[],
        episode_brief_id="ep-test",
    )


# --- Shape / syntactic tests ---


def test_empty_matrix_returns_empty_string():
    diagram = _build_mermaid_diagram(_matrix())
    assert diagram == ""


def test_diagram_starts_with_mermaid_fence_and_flowchart_header():
    matrix = _matrix(
        consensus=[_item(ActionCode.CONTINUE_SGLT2, "consensus", supporting=["nephrology", "cardiology"])],
    )
    diagram = _build_mermaid_diagram(matrix)
    lines = diagram.splitlines()
    assert lines[0] == "```mermaid"
    assert lines[1] == "flowchart TD"
    assert lines[-1] == "```"


def test_diagram_includes_all_classdef_declarations():
    matrix = _matrix(
        consensus=[_item(ActionCode.CONTINUE_SGLT2, "consensus")],
    )
    diagram = _build_mermaid_diagram(matrix)
    # All four classes must always be declared so that future tests rendering
    # any subset of the matrix still produce valid Mermaid.
    assert "classDef agreed" in diagram
    assert "classDef pending" in diagram
    assert "classDef conflict" in diagram
    assert "classDef caveat" in diagram


# --- Bucket → CSS class mapping ---


def test_consensus_item_uses_agreed_class():
    matrix = _matrix(
        consensus=[_item(ActionCode.CONTINUE_SGLT2, "consensus", supporting=["nephrology", "cardiology"])],
    )
    diagram = _build_mermaid_diagram(matrix)
    assert ":::agreed" in diagram


def test_tension_and_dependency_items_use_pending_class():
    matrix = _matrix(
        tensions=[_item(ActionCode.UPTITRATE_LOOP_DIURETIC, "tension")],
        dependencies=[_item(ActionCode.REPEAT_RENAL_PANEL_1W, "dependency")],
    )
    diagram = _build_mermaid_diagram(matrix)
    # both items render with the pending class
    assert diagram.count(":::pending") == 2


def test_direct_conflict_uses_conflict_class():
    matrix = _matrix(
        direct_conflicts=[
            _item(ActionCode.UPTITRATE_LOOP_DIURETIC, "direct_conflict", severity="high"),
        ],
    )
    diagram = _build_mermaid_diagram(matrix)
    assert ":::conflict" in diagram


def test_safety_and_missing_data_use_caveat_class():
    matrix = _matrix(
        safety_blocks=[_item(ActionCode.HOLD_ACE_ARB_TEMPORARILY, "safety_block", severity="high")],
        missing_data_blocks=[_item(ActionCode.REQUEST_BNP_NTPROBNP, "missing_data_block", severity="medium")],
    )
    diagram = _build_mermaid_diagram(matrix)
    assert diagram.count(":::caveat") == 2


def test_mixed_matrix_includes_all_four_classes():
    matrix = _matrix(
        consensus=[_item(ActionCode.CONTINUE_SGLT2, "consensus")],
        tensions=[_item(ActionCode.DAILY_WEIGHTS, "tension")],
        direct_conflicts=[_item(ActionCode.UPTITRATE_LOOP_DIURETIC, "direct_conflict")],
        safety_blocks=[_item(ActionCode.HOLD_ACE_ARB_TEMPORARILY, "safety_block")],
    )
    diagram = _build_mermaid_diagram(matrix)
    assert ":::agreed" in diagram
    assert ":::pending" in diagram
    assert ":::conflict" in diagram
    assert ":::caveat" in diagram


# --- Overflow handling ---


def test_overflow_summarises_excess_nodes():
    # Build 14 distinct consensus items (above the 12-node cap) using real
    # action codes from the enum.
    distinct_codes = list(ActionCode)[:14]
    consensus_items = [_item(c, "consensus") for c in distinct_codes]
    matrix = _matrix(consensus=consensus_items)

    diagram = _build_mermaid_diagram(matrix)

    # Exactly _MERMAID_MAX_NODES action-code nodes plus one "+2 more" overflow.
    explicit_node_count = diagram.count(':::agreed')
    # 12 explicit + 1 overflow = 13 total agreed-class nodes.
    assert explicit_node_count == _MERMAID_MAX_NODES + 1
    overflow_count = len(distinct_codes) - _MERMAID_MAX_NODES
    assert f"+{overflow_count} more" in diagram


def test_no_overflow_node_when_under_cap():
    matrix = _matrix(
        consensus=[_item(c, "consensus") for c in list(ActionCode)[:5]],
    )
    diagram = _build_mermaid_diagram(matrix)
    assert "more" not in diagram


# --- Label / safety ---


def test_node_label_truncates_long_codes():
    # _node_label should never produce a label longer than ~28 chars.
    for code in ActionCode:
        label = _node_label(code)
        assert len(label) <= 28, f"label too long: {label!r}"


def test_action_code_value_does_not_appear_raw_in_diagram():
    # Labels are titlecased, so the SHOUTY value should not appear unmodified
    # (which would suggest the label helper was bypassed).
    matrix = _matrix(
        consensus=[_item(ActionCode.UPTITRATE_LOOP_DIURETIC, "consensus")],
    )
    diagram = _build_mermaid_diagram(matrix)
    assert "UPTITRATE_LOOP_DIURETIC" not in diagram
    assert "Uptitrate Loop Diuretic" in diagram


# --- Determinism ---


def test_diagram_is_deterministic_for_same_matrix():
    matrix = _matrix(
        consensus=[_item(ActionCode.CONTINUE_SGLT2, "consensus")],
        tensions=[_item(ActionCode.DAILY_WEIGHTS, "tension")],
    )
    a = _build_mermaid_diagram(matrix)
    b = _build_mermaid_diagram(matrix)
    assert a == b


def test_duplicate_action_code_across_buckets_appears_once():
    # If upstream classification accidentally placed the same code in two
    # buckets, the diagram should still emit only one node for it.
    code = ActionCode.UPTITRATE_LOOP_DIURETIC
    matrix = _matrix(
        consensus=[_item(code, "consensus")],
        tensions=[_item(code, "tension")],
    )
    diagram = _build_mermaid_diagram(matrix)
    label = _node_label(code)
    # The label appears in exactly one node line.
    assert diagram.count(f'"{label}"') == 1


def test_mermaid_output_has_valid_basic_structure():
    """Structural sanity check on the Mermaid block: opens with 'flowchart TD',
    closes cleanly, every node id appears in classDef-mapped class, and there
    are no obviously malformed lines.

    This is not a full Mermaid parser, but it catches the most common failures
    a string-contains test would miss: wrong header, dangling lines, misnamed
    classes, unbalanced fences.
    """
    from tools.run_consult import _build_mermaid_diagram
    from llm.schemas import ConflictItem, ConflictMatrix
    from rules.action_codes import ActionCode

    matrix = ConflictMatrix(
        consensus=[
            ConflictItem(action_code=ActionCode.CONTINUE_SGLT2,
                         specialties_supporting=["nephrology", "cardiology"],
                         specialties_opposing=[], resolution="consensus",
                         severity="medium", notes="agreed"),
        ],
        tensions=[
            ConflictItem(action_code=ActionCode.UPTITRATE_LOOP_DIURETIC,
                         specialties_supporting=["cardiology"],
                         specialties_opposing=[], resolution="tension",
                         severity="high", notes="cardio wants this"),
        ],
        direct_conflicts=[],
        dependencies=[],
        missing_data_blocks=[],
        safety_blocks=[
            ConflictItem(action_code=ActionCode.REVIEW_MRA_FOR_HYPERKALAEMIA,
                         specialties_supporting=["pharmacy"],
                         specialties_opposing=[], resolution="safety_block",
                         severity="high", notes="K+ borderline"),
        ],
        ranked_next_actions=[],
        episode_brief_id="test-eb",
    )

    diagram = _build_mermaid_diagram(matrix)
    assert diagram, "non-empty matrix should produce a non-empty diagram"

    lines = [ln for ln in diagram.splitlines() if ln.strip()]
    # First content line must declare flowchart direction.
    assert lines[0].startswith("```mermaid"), f"missing opening fence: {lines[0]!r}"
    assert lines[-1].strip() == "```", f"missing closing fence: {lines[-1]!r}"

    body = lines[1:-1]
    assert any(ln.startswith("flowchart TD") for ln in body), \
        f"diagram body missing 'flowchart TD' header: {body[0]!r}"

    # Every classDef line must reference one of the four declared classes.
    declared_classes = {"agreed", "pending", "conflict", "caveat"}
    classdef_lines = [ln for ln in body if ln.lstrip().startswith("classDef ")]
    for ln in classdef_lines:
        # classDef <name> fill:#X,stroke:#Y
        parts = ln.lstrip().split()
        assert len(parts) >= 2, f"malformed classDef: {ln!r}"
        cls_name = parts[1]
        assert cls_name in declared_classes, \
            f"unexpected class name in classDef: {cls_name!r}"

    # Node ::: assignments must reference a declared class.
    node_lines = [ln for ln in body if ":::" in ln]
    for ln in node_lines:
        # Format like: NODE_ID["Label"]:::class
        cls_part = ln.split(":::")[-1].strip()
        assert cls_part in declared_classes, \
            f"node references undeclared class: {ln!r}"

    # No stray characters from previous bug patterns.
    forbidden = ("```mermaid", "```")
    for ln in body:
        for bad in forbidden:
            assert bad not in ln, f"fence leaked into body: {ln!r}"
