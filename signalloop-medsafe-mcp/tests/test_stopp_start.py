"""
Unit tests for CheckSTOPPSTART.

Pure rules — no FHIR, no LLM. Tests use compact patient-profile JSON
strings as input, mirroring the format BuildPatientRiskProfile emits.
"""

import asyncio
import json

import pytest

from tools.stopp_start import check_stopp_start


def _run(coro):
    return asyncio.run(coro)


def _profile_json(**overrides) -> str:
    base = {
        "patient_id": "test-patient",
        "age": 78,
        "sex": "female",
        "renal_function": {"latest_egfr": 45, "trajectory": "stable"},
        "active_medications": [],
        "allergies": [],
        "clinical_context_flags": [],
    }
    base.update(overrides)
    return json.dumps(base)


def test_under_65_not_applicable():
    raw = _run(check_stopp_start(_profile_json(age=40)))
    data = json.loads(raw)
    assert data["applicable"] is False


def test_nsaid_with_low_egfr_fires_e3():
    """STOPP-E3: NSAID + eGFR <50."""
    profile = _profile_json(
        active_medications=[{"name": "ibuprofen 400mg", "drug_class": "NSAID", "classes": ["NSAID"]}],
        renal_function={"latest_egfr": 42},
    )
    raw = _run(check_stopp_start(profile))
    data = json.loads(raw)
    ids = [f["id"] for f in data["stopp_findings"]]
    assert "STOPP-E3" in ids


def test_metformin_with_low_egfr_fires_e5():
    """STOPP-E5: metformin + eGFR <30."""
    profile = _profile_json(
        active_medications=[{"name": "metformin 500mg", "drug_class": "BIGUANIDE", "classes": ["BIGUANIDE"]}],
        renal_function={"latest_egfr": 25},
    )
    raw = _run(check_stopp_start(profile))
    data = json.loads(raw)
    ids = [f["id"] for f in data["stopp_findings"]]
    assert "STOPP-E5" in ids


def test_egfr_threshold_not_breached_does_not_fire():
    """eGFR at or above threshold does not fire the eGFR-gated STOPP."""
    profile = _profile_json(
        active_medications=[{"name": "ibuprofen", "drug_class": "NSAID", "classes": ["NSAID"]}],
        renal_function={"latest_egfr": 60},
    )
    raw = _run(check_stopp_start(profile))
    data = json.loads(raw)
    ids = [f["id"] for f in data["stopp_findings"]]
    assert "STOPP-E3" not in ids


def test_start_atrial_fibrillation_no_anticoag_fires_a1():
    """START-A1: AF without anticoagulant should fire."""
    profile = _profile_json(
        active_medications=[],
        clinical_context_flags=["atrial_fibrillation"],
    )
    raw = _run(check_stopp_start(profile))
    data = json.loads(raw)
    ids = [f["id"] for f in data["start_findings"]]
    assert "START-A1" in ids


def test_start_does_not_fire_when_indication_satisfied():
    """If the patient already has a DOAC, START-A1 should NOT fire."""
    profile = _profile_json(
        active_medications=[{"name": "apixaban 5mg", "drug_class": "DOAC", "classes": ["DOAC"]}],
        clinical_context_flags=["atrial_fibrillation"],
    )
    raw = _run(check_stopp_start(profile))
    data = json.loads(raw)
    ids = [f["id"] for f in data["start_findings"]]
    assert "START-A1" not in ids


def test_invalid_json_returns_error():
    raw = _run(check_stopp_start("not-json"))
    data = json.loads(raw)
    assert data["error"] == "invalid_profile_json"
