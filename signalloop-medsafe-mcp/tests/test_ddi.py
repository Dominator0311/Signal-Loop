"""
Unit tests for CheckDrugDrugInteraction.

Pure rules — no FHIR, no LLM.
"""

import asyncio
import json

import pytest

from tools.ddi import check_drug_drug_interaction


def _run(coro):
    return asyncio.run(coro)


def test_warfarin_clarithromycin_severe():
    raw = _run(check_drug_drug_interaction(json.dumps(["warfarin", "clarithromycin"])))
    data = json.loads(raw)
    assert data["summary"]["interaction_count"] >= 1
    severities = {i["severity"] for i in data["interactions"]}
    assert "severe" in severities


def test_simvastatin_clarithromycin_severe():
    raw = _run(check_drug_drug_interaction(json.dumps(["simvastatin", "clarithromycin"])))
    data = json.loads(raw)
    ids = [i["id"] for i in data["interactions"]]
    assert "DDI-STATIN-MACROLIDE" in ids


def test_ibuprofen_methotrexate_flagged():
    raw = _run(check_drug_drug_interaction(json.dumps(["ibuprofen", "methotrexate"])))
    data = json.loads(raw)
    ids = [i["id"] for i in data["interactions"]]
    # Either NSAID-MTX class match or specific MTX-NSAID rule should fire.
    assert any("METHOTREXATE" in mid or "NSAID" in mid for mid in ids)


def test_clean_pair_no_interactions():
    """Paracetamol + amoxicillin: no curated interactions."""
    raw = _run(check_drug_drug_interaction(json.dumps(["paracetamol", "amoxicillin"])))
    data = json.loads(raw)
    assert data["summary"]["interaction_count"] == 0


def test_only_one_drug_returns_error():
    raw = _run(check_drug_drug_interaction(json.dumps(["warfarin"])))
    data = json.loads(raw)
    assert data["error"] == "need_at_least_two_drugs"


def test_invalid_json_returns_error():
    raw = _run(check_drug_drug_interaction("not json"))
    data = json.loads(raw)
    assert data["error"] == "invalid_medications_json"


def test_unresolved_inputs_listed_but_pair_check_continues():
    """Unknown drug + warfarin: unknown listed, no interaction with warfarin from curated set."""
    raw = _run(check_drug_drug_interaction(json.dumps(["warfarin", "totallymadeupium"])))
    data = json.loads(raw)
    assert "totallymadeupium" in data["unresolved_inputs"]


def test_triple_whammy_requires_all_three_drugs():
    """Triple-whammy (NSAID+diuretic+ACE-I/ARB) must NOT fire on just NSAID+diuretic.

    Regression test: previously DDI-NSAID-DIURETIC-ACEI fired as 'severe' on any
    NSAID + diuretic pair because the evaluator ignored the `with_class` field.
    Now uses requires_all_classes — only fires when an ACE-I/ARB is also present.
    """
    raw = _run(check_drug_drug_interaction(json.dumps(["ibuprofen", "furosemide"])))
    data = json.loads(raw)
    ids = [i["id"] for i in data["interactions"]]
    # The two-drug rule fires (moderate); the three-drug rule must NOT.
    assert "DDI-NSAID-DIURETIC" in ids
    assert "DDI-NSAID-DIURETIC-ACEI" not in ids


def test_triple_whammy_fires_when_aceI_also_present():
    """When NSAID + diuretic + ACE-I are ALL on the list, the severe rule fires."""
    raw = _run(check_drug_drug_interaction(json.dumps(["ibuprofen", "furosemide", "ramipril"])))
    data = json.loads(raw)
    ids = [i["id"] for i in data["interactions"]]
    assert "DDI-NSAID-DIURETIC-ACEI" in ids
    severe = [i for i in data["interactions"] if i["id"] == "DDI-NSAID-DIURETIC-ACEI"]
    assert severe[0]["severity"] == "severe"


def test_no_duplicate_warfarin_nsaid_rule():
    """Regression: the duplicate DDI-WARFARIN-NSAID was removed; only DDI-NSAID-WARFARIN remains."""
    raw = _run(check_drug_drug_interaction(json.dumps(["warfarin", "ibuprofen"])))
    data = json.loads(raw)
    ids = [i["id"] for i in data["interactions"]]
    # The rule fires once (under either name) — no double-counting.
    assert ids.count("DDI-NSAID-WARFARIN") <= 1
    assert "DDI-WARFARIN-NSAID" not in ids
    # Severe interaction is still surfaced.
    assert any(i["severity"] == "severe" for i in data["interactions"])
