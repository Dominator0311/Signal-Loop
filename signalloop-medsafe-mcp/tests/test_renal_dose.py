"""
Unit tests for CheckRenalDoseAdjustment.

Verifies the JSON lookup table behaves correctly for happy path + edge cases.
No FHIR, no LLM — pure file I/O + Python.
"""

import asyncio
import json

import pytest

from tools.renal_dose import (
    check_renal_dose_adjustment,
    _load_renal_table,
    _resolve_drug_key,
    _select_band,
)


def _run(coro):
    return asyncio.run(coro)


def test_metformin_normal_renal_function_info():
    """Metformin at eGFR 80 returns the standard 'info' band."""
    raw = _run(check_renal_dose_adjustment(drug_name="metformin", egfr=80))
    data = json.loads(raw)
    assert data["resolved"] is True
    assert data["canonical_drug"] == "metformin"
    assert data["severity"] == "info"
    assert "Standard" in data["adjustment"]


def test_metformin_below_30_contraindicated():
    """Metformin at eGFR 25 must trigger the contraindicated band (lactic acidosis risk)."""
    raw = _run(check_renal_dose_adjustment(drug_name="metformin", egfr=25))
    data = json.loads(raw)
    assert data["severity"] == "contraindicated"
    assert "AVOID" in data["adjustment"].upper() or "discontinue" in data["adjustment"].lower()


def test_gabapentin_band_selection():
    """Gabapentin at eGFR 40 should hit the 30-49 band (max 900mg)."""
    raw = _run(check_renal_dose_adjustment(drug_name="gabapentin", egfr=40))
    data = json.loads(raw)
    assert data["egfr_band"]["egfr_min"] == 30
    assert data["egfr_band"]["egfr_max"] == 49
    assert "900" in data["adjustment"]


def test_apixaban_severe_renal():
    """Apixaban at eGFR 10 should be contraindicated."""
    raw = _run(check_renal_dose_adjustment(drug_name="apixaban", egfr=10))
    data = json.loads(raw)
    assert data["severity"] == "contraindicated"


def test_unknown_drug_returns_unresolved_with_coverage_list():
    """Unknown drug returns resolved=False with the coverage list, not an error."""
    raw = _run(check_renal_dose_adjustment(drug_name="unicornium", egfr=50))
    data = json.loads(raw)
    assert data["resolved"] is False
    assert "covered_drugs" in data and len(data["covered_drugs"]) > 0


def test_negative_egfr_rejected():
    """Negative eGFR is rejected with a structured error."""
    raw = _run(check_renal_dose_adjustment(drug_name="metformin", egfr=-1))
    data = json.loads(raw)
    assert data["error"] == "invalid_egfr"


def test_brand_name_resolution_via_normalizer():
    """Brand name 'glucophage' resolves to metformin via the normalizer."""
    raw = _run(check_renal_dose_adjustment(drug_name="glucophage", egfr=70))
    data = json.loads(raw)
    assert data["resolved"] is True
    assert data["canonical_drug"] == "metformin"


def test_select_band_pure_function():
    """Direct test of _select_band — no I/O, deterministic."""
    bands = [
        {"egfr_min": 60, "egfr_max": None, "severity": "info"},
        {"egfr_min": 30, "egfr_max": 59, "severity": "moderate"},
        {"egfr_min": 0, "egfr_max": 29, "severity": "contraindicated"},
    ]
    assert _select_band(bands, 80)["severity"] == "info"
    assert _select_band(bands, 45)["severity"] == "moderate"
    assert _select_band(bands, 20)["severity"] == "contraindicated"


def test_resolve_drug_key_direct():
    """Direct lookup for a drug already keyed in the table."""
    table = _load_renal_table()
    assert _resolve_drug_key("digoxin", table) == "digoxin"
    assert _resolve_drug_key("DIGOXIN", table) == "digoxin"
    assert _resolve_drug_key("nonexistentium", table) is None


def test_table_has_at_least_25_drugs():
    """We promised ~25 drugs of coverage; verify the table holds at least 25."""
    table = _load_renal_table()
    assert len(table["drugs"]) >= 25
