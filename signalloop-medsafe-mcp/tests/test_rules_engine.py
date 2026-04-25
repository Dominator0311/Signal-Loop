"""
Unit tests for the deterministic rules engine (Phase 2).

These tests verify the safety-critical core WITHOUT any LLM or FHIR dependency.
The rules engine is a pure function: given a medication + profile, it returns a verdict.

Test cases cover the three demo patients:
  - Margaret (should BLOCK ibuprofen)
  - James (should CLEAN ibuprofen)
  - Doris (should WARN for naproxen)
"""

from medsafe_core.rules.engine import evaluate_medication_safety
from medsafe_core.rules.normalizer import normalize_medication
from medsafe_core.rules.models import (
    PatientRiskProfile,
    RenalFunction,
    MedicationEntry,
    AllergyEntry,
    Verdict,
    Severity,
)


# --- Test profiles (mirror the FHIR bundle patients) ---

MARGARET_PROFILE = PatientRiskProfile(
    patient_id="patient-margaret",
    age=72,
    sex="female",
    renal_function=RenalFunction(
        latest_egfr=42,
        trajectory="declining",
        rate_of_change_per_month=-4.2,
    ),
    active_medications=[
        MedicationEntry(name="lisinopril 10mg", drug_class="ACE_INHIBITOR", classes=["ACE_INHIBITOR"]),
        MedicationEntry(name="furosemide 40mg", drug_class="LOOP_DIURETIC", classes=["LOOP_DIURETIC", "DIURETIC"]),
        MedicationEntry(name="metformin 500mg", drug_class="BIGUANIDE", classes=["BIGUANIDE"]),
        MedicationEntry(name="simvastatin 20mg", drug_class="STATIN", classes=["STATIN"]),
    ],
    allergies=[
        AllergyEntry(substance="penicillin", reaction="rash"),
    ],
    clinical_context_flags=["frail_elderly", "polypharmacy", "cardio_renal_high_risk", "ckd_stage_3b_near_4"],
)

JAMES_PROFILE = PatientRiskProfile(
    patient_id="patient-james",
    age=42,
    sex="male",
    renal_function=RenalFunction(
        latest_egfr=95,
        trajectory="stable",
    ),
    active_medications=[],
    allergies=[],
    clinical_context_flags=[],
)

DORIS_PROFILE = PatientRiskProfile(
    patient_id="patient-doris",
    age=68,
    sex="female",
    renal_function=RenalFunction(
        latest_egfr=65,
        trajectory="stable",
    ),
    active_medications=[
        MedicationEntry(name="methotrexate 15mg", drug_class="DMARD", classes=["DMARD", "IMMUNOSUPPRESSANT"]),
        MedicationEntry(name="folic acid 5mg", drug_class="VITAMIN", classes=["VITAMIN"]),
        MedicationEntry(name="alendronic acid 70mg", drug_class="BISPHOSPHONATE", classes=["BISPHOSPHONATE"]),
    ],
    allergies=[],
    clinical_context_flags=[],
)


# --- Normalization tests ---

def test_normalize_ibuprofen():
    result = normalize_medication("ibuprofen 400mg tds")
    assert result.resolved is True
    assert result.canonical_name == "ibuprofen"
    assert "NSAID" in result.drug_classes


def test_normalize_paracetamol():
    result = normalize_medication("paracetamol 1g qds")
    assert result.resolved is True
    assert "SIMPLE_ANALGESIC" in result.drug_classes


def test_normalize_unknown():
    result = normalize_medication("unicorn pills 500mg")
    assert result.resolved is False


# --- Margaret: ibuprofen should BLOCK ---

def test_margaret_ibuprofen_blocks():
    """Margaret + ibuprofen = BLOCK (triple whammy: NSAID + ACE-I + diuretic + CKD)"""
    verdict = evaluate_medication_safety(
        proposed_drug_classes=["NSAID"],
        proposed_drug_name="ibuprofen 400mg",
        proposed_drug_code="demo-dmd-376445002",
        profile=MARGARET_PROFILE,
    )
    assert verdict.verdict == Verdict.BLOCK
    assert verdict.requires_override_reason is True
    assert len(verdict.flags) >= 2  # At minimum: renal contraindication + triple whammy


def test_margaret_ibuprofen_has_renal_flag():
    """Margaret should trigger renal-nsaid-egfr-under-60 rule."""
    verdict = evaluate_medication_safety(
        proposed_drug_classes=["NSAID"],
        proposed_drug_name="ibuprofen",
        proposed_drug_code=None,
        profile=MARGARET_PROFILE,
    )
    renal_flags = [f for f in verdict.flags if "renal" in f.rule_id]
    assert len(renal_flags) >= 1
    assert renal_flags[0].severity == Severity.CONTRAINDICATED


def test_margaret_ibuprofen_has_triple_whammy_flag():
    """Margaret should trigger triple-whammy-aki rule."""
    verdict = evaluate_medication_safety(
        proposed_drug_classes=["NSAID"],
        proposed_drug_name="ibuprofen",
        proposed_drug_code=None,
        profile=MARGARET_PROFILE,
    )
    whammy_flags = [f for f in verdict.flags if "triple-whammy" in f.rule_id]
    assert len(whammy_flags) == 1
    assert whammy_flags[0].severity == Severity.MAJOR


def test_margaret_ibuprofen_has_beers_flag():
    """Margaret (age 72) should trigger Beers criteria for NSAIDs."""
    verdict = evaluate_medication_safety(
        proposed_drug_classes=["NSAID"],
        proposed_drug_name="ibuprofen",
        proposed_drug_code=None,
        profile=MARGARET_PROFILE,
    )
    beers_flags = [f for f in verdict.flags if "beers" in f.rule_id]
    assert len(beers_flags) == 1


def test_margaret_paracetamol_clean():
    """Margaret + paracetamol = CLEAN (no renal risk, no interactions)."""
    verdict = evaluate_medication_safety(
        proposed_drug_classes=["SIMPLE_ANALGESIC"],
        proposed_drug_name="paracetamol 1g",
        proposed_drug_code="demo-dmd-322236009",
        profile=MARGARET_PROFILE,
    )
    assert verdict.verdict == Verdict.CLEAN
    assert len(verdict.flags) == 0


# --- James: ibuprofen should be CLEAN ---

def test_james_ibuprofen_clean():
    """James (healthy 42M) + ibuprofen = CLEAN."""
    verdict = evaluate_medication_safety(
        proposed_drug_classes=["NSAID"],
        proposed_drug_name="ibuprofen 400mg",
        proposed_drug_code="demo-dmd-376445002",
        profile=JAMES_PROFILE,
    )
    assert verdict.verdict == Verdict.CLEAN
    assert len(verdict.flags) == 0
    assert verdict.requires_override_reason is False


# --- Doris: naproxen should WARN (not block) ---

def test_doris_naproxen_warns():
    """Doris + naproxen = WARN_OVERRIDE_REQUIRED (methotrexate interaction, Beers)."""
    verdict = evaluate_medication_safety(
        proposed_drug_classes=["NSAID"],
        proposed_drug_name="naproxen 500mg",
        proposed_drug_code="demo-dmd-375093004",
        profile=DORIS_PROFILE,
    )
    # Should NOT block (eGFR 65 is above 60 threshold)
    assert verdict.verdict != Verdict.BLOCK
    # Should warn due to methotrexate interaction
    assert verdict.verdict in (Verdict.WARN_OVERRIDE_REQUIRED, Verdict.WARN)
    # Should have methotrexate flag
    mtx_flags = [f for f in verdict.flags if "methotrexate" in f.rule_id]
    assert len(mtx_flags) >= 1


def test_doris_naproxen_has_beers():
    """Doris (age 68) should trigger Beers criteria."""
    verdict = evaluate_medication_safety(
        proposed_drug_classes=["NSAID"],
        proposed_drug_name="naproxen",
        proposed_drug_code=None,
        profile=DORIS_PROFILE,
    )
    beers_flags = [f for f in verdict.flags if "beers" in f.rule_id]
    assert len(beers_flags) == 1


# --- Edge cases ---

def test_empty_profile_clean():
    """Empty profile + any drug = CLEAN (no rules fire without context)."""
    empty = PatientRiskProfile(patient_id="empty")
    verdict = evaluate_medication_safety(
        proposed_drug_classes=["NSAID"],
        proposed_drug_name="ibuprofen",
        proposed_drug_code=None,
        profile=empty,
    )
    # No eGFR means renal rules don't fire, no meds means no interactions
    assert verdict.verdict == Verdict.CLEAN


def test_profile_fields_consulted_populated():
    """Verify audit trail: profile_fields_consulted is populated."""
    verdict = evaluate_medication_safety(
        proposed_drug_classes=["NSAID"],
        proposed_drug_name="ibuprofen",
        proposed_drug_code=None,
        profile=MARGARET_PROFILE,
    )
    assert len(verdict.profile_fields_consulted) > 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
