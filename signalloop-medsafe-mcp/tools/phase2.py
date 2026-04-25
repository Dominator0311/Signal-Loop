"""
Phase 2 MCP tools: Deterministic Medication Safety Check.

Pure rules. No LLM. The safety-critical core.
Every verdict traces to a specific rule with a specific evidence source.
"""

import json
import logging
import traceback
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

from medsafe_core.rules.engine import evaluate_medication_safety
from medsafe_core.rules.normalizer import normalize_medication as _normalize
from medsafe_core.rules.models import PatientRiskProfile, MedicationEntry, AllergyEntry, RenalFunction

logger = logging.getLogger(__name__)


async def normalize_medication(
    raw_text: Annotated[
        str,
        Field(description="Free-text medication string to normalize (e.g., 'ibuprofen 400mg tds', 'that white cholesterol pill')")
    ],
    ctx: Context = None,
) -> str:
    """
    Normalize a free-text medication string to a canonical coded identifier.

    Resolves patient-phrased or shorthand medication descriptions to dm+d codes
    with pharmacological class information. Returns structured result with
    resolution status — never silently drops unresolvable medications.
    """
    result = _normalize(raw_text)

    return json.dumps({
        "raw_input": result.raw_input,
        "resolved": result.resolved,
        "canonical_name": result.canonical_name,
        "code": result.code,
        "system": result.system,
        "drug_classes": list(result.drug_classes),
        "candidates": list(result.candidates) if not result.resolved else [],
    }, indent=2)


async def check_medication_safety(
    proposed_medication: Annotated[
        str,
        Field(description="The medication being proposed (e.g., 'ibuprofen 400mg TDS')")
    ],
    patient_risk_profile_json: Annotated[
        str,
        Field(description="JSON string of the patient risk profile from build_patient_risk_profile")
    ],
    ctx: Context = None,
) -> str:
    """
    Deterministic medication safety check (MedSafe Phase 2).

    Evaluates a proposed medication against the patient's risk profile using
    curated safety rules. NO LLM involved — pure deterministic logic.

    Rules evaluate: drug-drug interactions, renal contraindications,
    allergy cross-reactivity, Beers criteria (age ≥65), dose plausibility.

    The verdict matrix determines the response:
    - BLOCK: Contraindicated + Established evidence. Order cannot proceed.
    - WARN_OVERRIDE_REQUIRED: Major + Established. Clinician must provide reason.
    - WARN: Moderate concern. Clinician informed but can proceed.
    - INFO: Minor concern. Logged for awareness.
    - CLEAN: No safety issues identified.

    Every flag includes: rule_id, severity, evidence_level, citation,
    and profile_fields_consulted (for audit trail).
    """
    logger.info(f"check_medication_safety called: proposed={proposed_medication!r}")
    logger.info(f"profile_json length={len(patient_risk_profile_json) if patient_risk_profile_json else 0}")
    logger.info(f"profile_json preview={patient_risk_profile_json[:500] if patient_risk_profile_json else 'EMPTY'}")

    try:
        # Normalize the proposed medication
        normalized = _normalize(proposed_medication)
        logger.info(f"Normalized to: {normalized.canonical_name} (classes={normalized.drug_classes})")

        if not normalized.resolved:
            return json.dumps({
                "error": "medication_not_resolved",
                "message": f"Could not resolve '{proposed_medication}' to a known medication code.",
                "candidates": list(normalized.candidates),
                "action": "Please clarify the medication name or provide a more specific description.",
            }, indent=2)

        # Parse the patient risk profile
        profile = _parse_risk_profile(patient_risk_profile_json)
        logger.info(f"Parsed profile: age={profile.age}, egfr={profile.renal_function.latest_egfr}, "
                    f"meds={len(profile.active_medications)}, allergies={len(profile.allergies)}")

        # Run the deterministic rules engine
        verdict = evaluate_medication_safety(
            proposed_drug_classes=list(normalized.drug_classes),
            proposed_drug_name=normalized.canonical_name or proposed_medication,
            proposed_drug_code=normalized.code,
            profile=profile,
        )
        logger.info(f"Verdict: {verdict.verdict} with {len(verdict.flags)} flags")

        return json.dumps(verdict.model_dump(), indent=2)

    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"check_medication_safety failed: {e}\n{error_trace}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
            "hint": "Check that patient_risk_profile_json is a valid JSON string from BuildPatientRiskProfile.",
        }, indent=2)


def parse_risk_profile(profile_json: str) -> PatientRiskProfile:
    """
    Parse a patient risk profile from JSON string.

    Handles both the LLM-generated profile format and manually constructed profiles.
    Maps the LLM output schema to the rules engine input schema.

    Raises ValueError with clear messages if:
      - Input is not valid JSON
      - Input is an error response from BuildPatientRiskProfile (upstream failure)
    """
    try:
        data = json.loads(profile_json)
    except json.JSONDecodeError as e:
        # Detect if this is an error message from upstream (Phase 1 failure)
        if profile_json and "Error executing tool" in profile_json[:200]:
            raise ValueError(
                "BuildPatientRiskProfile failed upstream — cannot check safety without a valid profile. "
                "Re-run BuildPatientRiskProfile first, or provide a valid profile JSON directly."
            )
        raise ValueError(f"Invalid patient risk profile JSON: {e}")

    # Detect structured error JSON from Phase 1
    if isinstance(data, dict) and data.get("error"):
        raise ValueError(
            f"BuildPatientRiskProfile returned an error: {data.get('message', 'unknown error')}. "
            f"Cannot check medication safety without a valid profile."
        )

    # Map medications
    medications = []
    for med in data.get("active_medications", []):
        classes = med.get("classes", [])
        if not classes and med.get("drug_class"):
            classes = [med["drug_class"]]
        medications.append(MedicationEntry(
            name=med.get("name", "Unknown"),
            drug_class=med.get("drug_class", "UNKNOWN"),
            classes=classes,
        ))

    # Map allergies
    allergies = []
    for allergy in data.get("allergies", []):
        allergies.append(AllergyEntry(
            substance=allergy.get("substance", "Unknown"),
            substance_class=allergy.get("substance_class"),
            reaction=allergy.get("reaction", ""),
        ))

    # Map renal function
    renal_data = data.get("renal_function", {})
    renal = RenalFunction(
        latest_egfr=renal_data.get("latest_egfr"),
        trajectory=renal_data.get("trajectory"),
        rate_of_change_per_month=renal_data.get("rate_of_change_per_month"),
    )

    return PatientRiskProfile(
        patient_id=data.get("patient_id", "unknown"),
        age=data.get("age"),
        sex=data.get("sex"),
        weight_kg=data.get("weight_kg"),
        renal_function=renal,
        active_medications=medications,
        allergies=allergies,
        clinical_context_flags=data.get("clinical_context_flags", []),
        reasoning_trace=data.get("reasoning_trace", ""),
    )
