"""
Unit tests for ActionCode enum and related constants.

These verify the canonical vocabulary is complete, consistent,
and that the helper sets/pairs are correctly defined.
"""

import pytest

from rules.action_codes import ActionCode, OPPOSING_PAIRS, SAFETY_PRIORITY_CODES


def test_all_action_codes_are_strings():
    for code in ActionCode:
        assert isinstance(code.value, str)
        assert code.value == code.value.upper()


def test_action_codes_roundtrip():
    for code in ActionCode:
        assert ActionCode(code.value) is code


def test_out_of_catalog_exists():
    assert ActionCode.OUT_OF_CATALOG is not None


def test_core_diuresis_codes_present():
    assert ActionCode.UPTITRATE_LOOP_DIURETIC in ActionCode
    assert ActionCode.DOWNTITRATE_LOOP_DIURETIC in ActionCode
    assert ActionCode.HOLD_LOOP_DIURETIC_TEMPORARILY in ActionCode


def test_core_raas_codes_present():
    assert ActionCode.HOLD_ACE_ARB_TEMPORARILY in ActionCode
    assert ActionCode.REDUCE_ACE_ARB_DOSE in ActionCode
    assert ActionCode.HOLD_MRA_TEMPORARILY in ActionCode
    assert ActionCode.REVIEW_MRA_FOR_HYPERKALAEMIA in ActionCode


def test_monitoring_codes_present():
    assert ActionCode.REPEAT_RENAL_PANEL_48H in ActionCode
    assert ActionCode.REPEAT_POTASSIUM_48H in ActionCode
    assert ActionCode.DAILY_WEIGHTS in ActionCode


def test_opposing_pairs_are_valid_codes():
    for a, b in OPPOSING_PAIRS:
        assert isinstance(a, ActionCode)
        assert isinstance(b, ActionCode)
        assert a != b


def test_safety_priority_codes_are_subset_of_action_codes():
    all_codes = set(ActionCode)
    assert SAFETY_PRIORITY_CODES.issubset(all_codes)


def test_safety_priority_not_empty():
    assert len(SAFETY_PRIORITY_CODES) > 0


def test_uptitrate_downtitrate_are_opposing():
    opposing_set = {frozenset(p) for p in OPPOSING_PAIRS}
    pair = frozenset({ActionCode.UPTITRATE_LOOP_DIURETIC, ActionCode.DOWNTITRATE_LOOP_DIURETIC})
    assert pair in opposing_set


def test_safety_priority_includes_renal_codes():
    assert ActionCode.REPEAT_RENAL_PANEL_48H in SAFETY_PRIORITY_CODES
    assert ActionCode.REPEAT_POTASSIUM_48H in SAFETY_PRIORITY_CODES
