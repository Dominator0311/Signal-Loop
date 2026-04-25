"""
Unit tests for RunFullMedicationReview.

The composite tool depends on FHIR + LLM in production. For tests we stub
build_patient_risk_profile and run_in_background helpers so the markdown
synthesiser is exercised without network.
"""

import asyncio
import json
from unittest.mock import patch

import pytest

from tools import full_review as fr


def _run(coro):
    return asyncio.run(coro)


_PROFILE_MARGARET = {
    "patient_id": "patient-margaret",
    "first_name": "Margaret",
    "age": 72,
    "sex": "female",
    "renal_function": {"latest_egfr": 42, "trajectory": "declining", "rate_of_change_per_month": -4.2},
    "active_medications": [
        {"name": "lisinopril 10mg", "drug_class": "ACE_INHIBITOR", "classes": ["ACE_INHIBITOR"]},
        {"name": "furosemide 40mg", "drug_class": "LOOP_DIURETIC", "classes": ["LOOP_DIURETIC", "DIURETIC"]},
        {"name": "metformin 500mg", "drug_class": "BIGUANIDE", "classes": ["BIGUANIDE"]},
        {"name": "ibuprofen 400mg", "drug_class": "NSAID", "classes": ["NSAID"]},
    ],
    "allergies": [],
    "clinical_context_flags": ["frail_elderly", "polypharmacy"],
}


async def _fake_build_profile(ctx=None):
    return json.dumps(_PROFILE_MARGARET)


def test_run_full_review_renders_markdown_under_5kb():
    with patch.object(fr, "build_patient_risk_profile", _fake_build_profile):
        markdown = _run(fr.run_full_medication_review(ctx=None))
    assert isinstance(markdown, str)
    assert len(markdown) <= 5000
    assert "Full medication review" in markdown
    # Margaret's NSAID + ACE-I + diuretic should surface at least one BLOCK or interaction
    assert "ibuprofen" in markdown.lower() or "NSAID" in markdown


def test_run_full_review_includes_per_drug_section():
    with patch.object(fr, "build_patient_risk_profile", _fake_build_profile):
        markdown = _run(fr.run_full_medication_review(ctx=None))
    assert "Per-medication safety verdict" in markdown
    assert "Drug-drug interaction" in markdown


def test_run_full_review_handles_profile_error():
    async def _err_profile(ctx=None):
        return json.dumps({"error": "profile_build_failed", "message": "test"})

    with patch.object(fr, "build_patient_risk_profile", _err_profile):
        out = _run(fr.run_full_medication_review(ctx=None))
    data = json.loads(out)
    assert data["error"] == "upstream_profile_error"


def test_run_full_review_empty_profile_no_crash():
    async def _empty_profile(ctx=None):
        return json.dumps({
            "patient_id": "p", "age": 30, "active_medications": [],
            "allergies": [], "clinical_context_flags": [],
            "renal_function": {"latest_egfr": 90},
        })

    with patch.object(fr, "build_patient_risk_profile", _empty_profile):
        markdown = _run(fr.run_full_medication_review(ctx=None))
    assert isinstance(markdown, str)
    assert "Full medication review" in markdown
