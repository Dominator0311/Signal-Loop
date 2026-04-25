"""
Shared tools re-registered from medsafe_core.

NormalizeMedication and CheckMedicationSafety are identical to SignalLoop's Phase 2 tools.
Both MCPs register them independently — same underlying logic via medsafe_core.
"""

import json
import logging
import traceback
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

from medsafe_core.rules.engine import evaluate_medication_safety
from medsafe_core.rules.normalizer import normalize_medication as _normalize
from medsafe_core.rules.models import (
    AllergyEntry,
    MedicationEntry,
    PatientRiskProfile,
    RenalFunction,
)

logger = logging.getLogger(__name__)


async def normalize_medication(
    raw_text: Annotated[
        str,
        Field(description="Free-text medication string to normalize (e.g., 'furosemide 40mg BD', 'ramipril 10mg')"),
    ],
    ctx: Context = None,
) -> str:
    """
    Normalize a free-text medication string to a canonical coded identifier.

    Resolves medication descriptions to dm+d codes with pharmacological class information.
    Returns structured result with resolution status.
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
        Field(description="The medication being proposed (e.g., 'spironolactone 25mg OD')"),
    ],
    patient_risk_profile_json: Annotated[
        str,
        Field(description="JSON string of the patient risk profile from BuildEpisodeBrief or BuildPatientRiskProfile"),
    ],
    ctx: Context = None,
) -> str:
    """
    Deterministic medication safety check.

    Evaluates a proposed medication against the patient's risk profile using
    curated safety rules. NO LLM involved — pure deterministic logic.

    Returns: BLOCK (contraindicated), WARN_OVERRIDE_REQUIRED, WARN, INFO, or CLEAN.
    Every flag includes rule_id, severity, evidence_level, and citation.
    """
    try:
        normalized = _normalize(proposed_medication)
        if not normalized.resolved:
            return json.dumps({
                "error": "medication_not_resolved",
                "message": f"Could not resolve '{proposed_medication}' to a known medication code.",
                "candidates": list(normalized.candidates),
            }, indent=2)

        profile = _parse_risk_profile(patient_risk_profile_json)
        verdict = evaluate_medication_safety(
            proposed_drug_classes=list(normalized.drug_classes),
            proposed_drug_name=normalized.canonical_name or proposed_medication,
            proposed_drug_code=normalized.code,
            profile=profile,
        )
        return json.dumps(verdict.model_dump(), indent=2)

    except Exception as e:
        logger.error(f"check_medication_safety failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)


def _parse_risk_profile(profile_json: str) -> PatientRiskProfile:
    try:
        data = json.loads(profile_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid patient risk profile JSON: {e}")

    if isinstance(data, dict) and data.get("error"):
        raise ValueError(f"Risk profile returned an error: {data.get('message', 'unknown')}")

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

    allergies = [
        AllergyEntry(
            substance=a.get("substance", "Unknown"),
            substance_class=a.get("substance_class"),
            reaction=a.get("reaction", ""),
        )
        for a in data.get("allergies", [])
    ]

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
    )
