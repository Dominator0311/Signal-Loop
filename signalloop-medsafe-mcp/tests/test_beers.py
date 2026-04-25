"""
Unit tests for CheckBeersCriteria.

Pure rules — no FHIR, no LLM.
"""

import asyncio
import json

import pytest

from tools.beers import check_beers_criteria


def _run(coro):
    return asyncio.run(coro)


def _profile_json(**overrides) -> str:
    base = {
        "patient_id": "test-beers",
        "age": 75,
        "sex": "female",
        "renal_function": {"latest_egfr": 60},
        "active_medications": [],
        "allergies": [],
        "clinical_context_flags": [],
    }
    base.update(overrides)
    return json.dumps(base)


def test_under_65_not_applicable():
    raw = _run(check_beers_criteria(_profile_json(age=50)))
    data = json.loads(raw)
    assert data["applicable"] is False


def test_nsaid_in_elderly_flagged():
    profile = _profile_json(
        active_medications=[{"name": "ibuprofen", "drug_class": "NSAID", "classes": ["NSAID"]}],
    )
    raw = _run(check_beers_criteria(profile))
    data = json.loads(raw)
    ids = [f["id"] for f in data["beers_findings"]]
    assert "BEERS-2023-NSAID" in ids


def test_benzodiazepine_in_elderly_flagged():
    profile = _profile_json(
        active_medications=[
            {"name": "diazepam 5mg", "drug_class": "BENZODIAZEPINE", "classes": ["BENZODIAZEPINE"]},
        ],
    )
    raw = _run(check_beers_criteria(profile))
    data = json.loads(raw)
    ids = [f["id"] for f in data["beers_findings"]]
    assert "BEERS-2023-BENZODIAZEPINE" in ids


def test_clean_med_list_no_findings():
    profile = _profile_json(
        active_medications=[{"name": "paracetamol", "drug_class": "SIMPLE_ANALGESIC", "classes": ["SIMPLE_ANALGESIC"]}],
    )
    raw = _run(check_beers_criteria(profile))
    data = json.loads(raw)
    assert data["beers_findings"] == []


def test_findings_carry_citation():
    profile = _profile_json(
        active_medications=[{"name": "ibuprofen", "drug_class": "NSAID", "classes": ["NSAID"]}],
    )
    raw = _run(check_beers_criteria(profile))
    data = json.loads(raw)
    findings = data["beers_findings"]
    assert findings, "expected at least one finding"
    assert "Beers" in findings[0]["citation"]
    assert findings[0]["clinical_review_status"] in ("summarised_from_named_source", "verbatim_verified")


def test_invalid_profile_returns_error():
    raw = _run(check_beers_criteria("{nope"))
    data = json.loads(raw)
    assert data["error"] == "invalid_profile_json"
