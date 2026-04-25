"""Tests for SurfacePatientAttention composite tool.

Focus is on the deterministic ranking and item extraction — the underlying
primitives are mocked so we test what surveillance.py actually does, not
what the primitives do.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from tools.surveillance import (
    AttentionItem,
    AttentionResponse,
    _consult_attention,
    _drug_safety_attentions,
    _rank_and_trim,
    _trend_attention,
    surface_patient_attention,
)


# --- Pure helpers ---


def test_trend_attention_fires_on_steep_decline():
    item = _trend_attention({
        "trajectory": "falling",
        "rate_of_change_per_month": -0.5,  # -6/yr → above threshold
        "latest_value": 42,
    })
    assert item is not None
    assert item.category == "trend"
    assert item.severity == "WARN"
    assert "5 mL/min/year" in item.citation or "NG203" in item.citation


def test_trend_attention_silent_below_threshold():
    item = _trend_attention({
        "trajectory": "falling",
        "rate_of_change_per_month": -0.1,  # -1.2/yr → below threshold
        "latest_value": 60,
    })
    assert item is None


def test_trend_attention_silent_when_stable():
    item = _trend_attention({
        "trajectory": "stable",
        "rate_of_change_per_month": 0.0,
        "latest_value": 60,
    })
    assert item is None


def test_drug_safety_extracts_block_and_warn():
    items = _drug_safety_attentions({
        "medication_findings": [
            {"medication": "ibuprofen", "verdict": "BLOCK",
             "flags": [{"message": "NSAID at eGFR 41 contraindicated", "rule_id": "R1"}]},
            {"medication": "naproxen", "verdict": "WARN",
             "flags": [{"message": "renal caution"}]},
            {"medication": "paracetamol", "verdict": "CLEAN", "flags": []},
        ],
    })
    assert len(items) == 2
    assert items[0].severity == "BLOCK"
    assert items[0].category == "drug_safety"
    assert items[1].severity == "WARN"


def test_drug_safety_handles_empty_or_error():
    assert _drug_safety_attentions(None) == []
    assert _drug_safety_attentions({"error": "boom"}) == []
    assert _drug_safety_attentions({"medication_findings": []}) == []


def test_consult_attention_fires_when_recs_present():
    item = _consult_attention({
        "recommendation_count": 7,
        "specialty": "nephrology",
        "received_at": "2026-04-10",
    })
    assert item is not None
    assert item.category == "open_consult"
    assert "7" in item.headline
    assert item.severity == "WARN"  # >=3 recs


def test_consult_attention_info_severity_for_few_recs():
    item = _consult_attention({
        "recommendation_count": 1,
        "specialty": "cardiology",
    })
    assert item is not None
    assert item.severity == "INFO"


def test_consult_attention_silent_when_zero():
    assert _consult_attention({"recommendation_count": 0}) is None
    assert _consult_attention(None) is None
    assert _consult_attention({"error": "nothing"}) is None


def test_rank_orders_block_before_warn_before_consult():
    items = [
        AttentionItem(category="trend", severity="WARN", headline="t", rationale=""),
        AttentionItem(category="drug_safety", severity="BLOCK", headline="b", rationale=""),
        AttentionItem(category="open_consult", severity="WARN", headline="c", rationale=""),
        AttentionItem(category="drug_safety", severity="WARN", headline="d", rationale=""),
    ]
    ranked = _rank_and_trim(items, max_items=5)
    assert ranked[0].severity == "BLOCK"
    assert ranked[0].category == "drug_safety"
    assert ranked[1].category == "open_consult"
    # WARN drug_safety comes before trend
    assert ranked[2].category == "drug_safety"
    assert ranked[3].category == "trend"


def test_rank_trims_to_max_items():
    items = [
        AttentionItem(category="drug_safety", severity="BLOCK", headline=str(i), rationale="")
        for i in range(10)
    ]
    assert len(_rank_and_trim(items, max_items=3)) == 3


# --- End-to-end tool with mocked primitives ---


def _async(*args, **kwargs):
    """Helper: produce a coroutine that immediately returns the value."""
    val = args[0] if args else kwargs.get("value")
    async def _coro():
        return val
    return _coro()


def test_surface_patient_attention_end_to_end_margaret_like():
    """Margaret-like profile: BLOCK drug, decline trend, 7 unactioned recs → 3 items, BLOCK first."""
    profile_json = json.dumps({"patient_id": "p1", "generated_at": "2026-04-25T10:00:00Z"})
    trend_json = json.dumps({
        "trajectory": "falling",
        "rate_of_change_per_month": -1.0,  # -12/yr
        "latest_value": 42,
    })
    review_json = json.dumps({
        "medication_findings": [
            {"medication": "ibuprofen", "verdict": "BLOCK",
             "flags": [{"message": "NSAID contraindicated at eGFR 41", "rule_id": "R-RENAL-NSAID"}]},
        ],
    })
    consult_json = json.dumps({
        "recommendation_count": 7,
        "specialty": "nephrology",
        "received_at": "2026-04-10",
    })

    async def mocked_profile(ctx=None): return profile_json
    async def mocked_trend(ctx=None): return trend_json
    async def mocked_review(ctx=None): return review_json
    async def mocked_consult(ctx=None): return consult_json

    with (
        patch("tools.surveillance.build_patient_risk_profile", side_effect=mocked_profile),
        patch("tools.surveillance.get_renal_trend", side_effect=mocked_trend),
        patch("tools.surveillance.run_full_medication_review", side_effect=mocked_review),
        patch("tools.surveillance.extract_consult_recommendations", side_effect=mocked_consult),
        patch("tools.surveillance.extract_patient_id", return_value="p1"),
    ):
        result_json = asyncio.run(surface_patient_attention(max_items=5, ctx=None))

    result = json.loads(result_json)
    assert result["patient_id"] == "p1"
    assert len(result["items"]) == 3
    assert result["items"][0]["category"] == "drug_safety"
    assert result["items"][0]["severity"] == "BLOCK"
    assert result["items"][1]["category"] == "open_consult"
    assert result["items"][2]["category"] == "trend"
    assert "3 item(s)" in result["summary_line"]


def test_surface_patient_attention_no_concerns():
    """Healthy patient: no items → friendly summary."""
    async def mocked_profile(ctx=None): return json.dumps({"patient_id": "p2"})
    async def mocked_trend(ctx=None): return json.dumps({"trajectory": "stable", "rate_of_change_per_month": 0})
    async def mocked_review(ctx=None): return json.dumps({"medication_findings": []})
    async def mocked_consult(ctx=None): return json.dumps({"recommendation_count": 0})

    with (
        patch("tools.surveillance.build_patient_risk_profile", side_effect=mocked_profile),
        patch("tools.surveillance.get_renal_trend", side_effect=mocked_trend),
        patch("tools.surveillance.run_full_medication_review", side_effect=mocked_review),
        patch("tools.surveillance.extract_consult_recommendations", side_effect=mocked_consult),
        patch("tools.surveillance.extract_patient_id", return_value="p2"),
    ):
        result_json = asyncio.run(surface_patient_attention(max_items=5, ctx=None))

    result = json.loads(result_json)
    assert result["items"] == []
    assert "No attention items" in result["summary_line"]


def test_surface_patient_attention_tolerates_primitive_failure():
    """If one primitive errors, surface what we got from the others."""
    async def mocked_profile(ctx=None): return json.dumps({"patient_id": "p3"})
    async def mocked_trend(ctx=None): raise RuntimeError("trend boom")
    async def mocked_review(ctx=None):
        return json.dumps({
            "medication_findings": [
                {"medication": "naproxen", "verdict": "WARN",
                 "flags": [{"message": "warn"}]},
            ],
        })
    async def mocked_consult(ctx=None): return json.dumps({"recommendation_count": 0})

    with (
        patch("tools.surveillance.build_patient_risk_profile", side_effect=mocked_profile),
        patch("tools.surveillance.get_renal_trend", side_effect=mocked_trend),
        patch("tools.surveillance.run_full_medication_review", side_effect=mocked_review),
        patch("tools.surveillance.extract_consult_recommendations", side_effect=mocked_consult),
        patch("tools.surveillance.extract_patient_id", return_value="p3"),
    ):
        result_json = asyncio.run(surface_patient_attention(max_items=5, ctx=None))

    result = json.loads(result_json)
    # Did not crash; trend item missing but drug_safety WARN present
    assert "error" not in result
    assert any(it["category"] == "drug_safety" for it in result["items"])
