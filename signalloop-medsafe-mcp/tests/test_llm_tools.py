"""
Unit tests for the LLM-driven tools (SuggestAlternative, ExplainContraindication).

We stub the Gemini client at module-import time so these tests do not hit the
real API and do not require GEMINI_API_KEY. We assert the input wiring + the
output JSON shape.
"""

import asyncio
import json
from unittest.mock import patch

import pytest

from medsafe_core.llm.schemas import (
    AlternativeList,
    AlternativeSuggestion,
    ContraindicationExplanation,
)


def _run(coro):
    return asyncio.run(coro)


# --- SuggestAlternative ---

class _FakeGeminiAlternatives:
    """Stub Gemini client that returns a canned AlternativeList."""

    async def generate_structured(self, prompt, output_model, system_instruction=None):
        assert output_model is AlternativeList
        # Sanity: the prompt should mention the contraindicated drug and reason
        assert "ibuprofen" in prompt
        assert "eGFR" in prompt or "renal" in prompt.lower() or "kidney" in prompt.lower()
        return AlternativeList(
            original_drug="ibuprofen 400mg",
            contraindication_reason="eGFR 41 — NICE NG203 §1.3.2",
            alternatives=[
                AlternativeSuggestion(
                    name="paracetamol",
                    drug_class="SIMPLE_ANALGESIC",
                    rationale="No nephrotoxicity; safe at eGFR 41.",
                    typical_starting_dose="500mg-1g QDS, max 4g/day",
                    monitoring="LFTs if chronic alcohol use",
                    cautions="Hepatic impairment",
                ),
                AlternativeSuggestion(
                    name="topical diclofenac",
                    drug_class="NSAID_TOPICAL",
                    rationale="Minimal systemic absorption",
                    typical_starting_dose="2-4g TDS-QDS",
                    monitoring="Skin reactions",
                    cautions="Avoid broken skin",
                ),
                AlternativeSuggestion(
                    name="codeine",
                    drug_class="OPIOID",
                    rationale="No renal contraindication at this eGFR",
                    typical_starting_dose="30-60mg q4-6h",
                    monitoring="Bowel habit, sedation",
                    cautions="Constipation; falls risk",
                ),
            ],
            summary="Paracetamol first-line; topical diclofenac if localised pain.",
        )


def test_suggest_alternative_happy_path():
    from tools import suggest_alternative as sa_module

    fake = _FakeGeminiAlternatives()
    with patch.object(sa_module, "get_gemini_client", return_value=fake):
        raw = _run(sa_module.suggest_alternative(
            drug_name="ibuprofen 400mg",
            contraindication_reason="eGFR 41 — NICE NG203 §1.3.2 NSAID avoidance below eGFR 60",
            patient_risk_profile_json="",
        ))
    data = json.loads(raw)
    assert data["original_drug"] == "ibuprofen 400mg"
    assert "alternatives" in data
    assert len(data["alternatives"]) >= 3
    assert data["alternatives"][0]["name"] == "paracetamol"


def test_suggest_alternative_handles_invalid_profile_gracefully():
    from tools import suggest_alternative as sa_module

    fake = _FakeGeminiAlternatives()
    with patch.object(sa_module, "get_gemini_client", return_value=fake):
        raw = _run(sa_module.suggest_alternative(
            drug_name="ibuprofen 400mg",
            contraindication_reason="eGFR 41 — kidney function low",
            patient_risk_profile_json="not-valid-json",
        ))
    data = json.loads(raw)
    # Should still succeed — invalid profile JSON is logged + ignored.
    assert "alternatives" in data


# --- ExplainContraindication ---

class _FakeGeminiExplain:
    async def generate_structured(self, prompt, output_model, system_instruction=None):
        assert output_model is ContraindicationExplanation
        return ContraindicationExplanation(
            clinical_explanation=(
                "NSAID contraindicated at eGFR 41 (NICE NG203 §1.3.2). "
                "Patient also on ACE-I + diuretic — triple whammy AKI risk. "
                "Suggest paracetamol or topical NSAID."
            ),
            patient_friendly_explanation=(
                "Your kidneys are working at about 41% of normal. Anti-inflammatory "
                "tablets like ibuprofen would put extra strain on them and could "
                "cause sudden kidney damage, especially with the blood-pressure "
                "tablet you already take. We will use paracetamol instead."
            ),
            key_risks=["Acute kidney injury", "Hyperkalaemia", "Hospital admission"],
            next_steps=["Switch to paracetamol", "Recheck eGFR in 2 weeks"],
        )


def test_explain_contraindication_happy_path():
    from tools import explain_contra as ec_module

    fake_verdict = {
        "proposed_medication": "ibuprofen 400mg",
        "verdict": "block",
        "flags": [
            {
                "severity": "contraindicated",
                "evidence_level": "established",
                "reason": "NSAID at eGFR 41 below NICE 60 threshold",
                "citation": "NICE NG203 §1.3.2",
            }
        ],
    }
    fake = _FakeGeminiExplain()
    with patch.object(ec_module, "get_gemini_client", return_value=fake):
        raw = _run(ec_module.explain_contraindication(
            verdict_json=json.dumps(fake_verdict),
            patient_risk_profile_json="",
        ))
    data = json.loads(raw)
    assert "clinical_explanation" in data
    assert "patient_friendly_explanation" in data
    assert isinstance(data["key_risks"], list)
    assert isinstance(data["next_steps"], list)


def test_explain_contraindication_invalid_verdict():
    from tools import explain_contra as ec_module

    raw = _run(ec_module.explain_contraindication(verdict_json="{not-json"))
    data = json.loads(raw)
    assert data["error"] == "invalid_verdict_json"
