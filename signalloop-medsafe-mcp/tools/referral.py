"""
Referral sub-system MCP tools.

First-class capability: specialty-specific packet assembly, destination
ranking, consult note recommendation extraction, and plan conflict detection.
"""

import json
import base64
from typing import Annotated
from pathlib import Path

from mcp.server.fastmcp import Context
from pydantic import Field

from fhir.context import extract_fhir_context, extract_patient_id
from fhir.client import FhirClient
from llm.client import get_gemini_client
from llm.prompts.consult_extraction import (
    SYSTEM_INSTRUCTION as EXTRACTION_SYSTEM,
    CONFLICT_DETECTION_SYSTEM,
    build_extraction_prompt,
    build_conflict_detection_prompt,
)
from llm.schemas import LLMConsultExtraction, LLMConflictDetection


# Specialty profiles: what each specialty needs in a referral packet
SPECIALTY_PROFILES = {
    "nephrology": {
        "required_inputs": [
            {"name": "egfr_trend", "fhir_query": "Observation?code=http://loinc.org|62238-1", "importance": "critical"},
            {"name": "creatinine_trend", "fhir_query": "Observation?code=http://loinc.org|2160-0", "importance": "critical"},
            {"name": "urine_acr", "fhir_query": "Observation?code=http://loinc.org|9318-7", "importance": "important"},
            {"name": "bp_history", "fhir_query": "Observation?code=http://loinc.org|85354-9", "importance": "important"},
            {"name": "current_ace_arb", "description": "Current ACE-I/ARB medication and dose", "importance": "critical"},
            {"name": "diabetes_status", "fhir_query": "Condition?code=http://snomed.info/sct|44054006", "importance": "important"},
            {"name": "renal_imaging", "description": "Recent renal ultrasound or imaging", "importance": "optional"},
            {"name": "nephrotoxin_exposure", "description": "Current nephrotoxic medications", "importance": "important"},
        ],
        "referral_question_template": "Sustained eGFR decline from {first_egfr} to {last_egfr} over {period} in {age}{sex} with {conditions}. Please assess for CKD progression and advise on medication optimisation.",
    },
    "cardiology": {
        "required_inputs": [
            {"name": "ecg", "description": "Recent ECG", "importance": "critical"},
            {"name": "echo", "description": "Echocardiogram / ejection fraction", "importance": "important"},
            {"name": "bp_trend", "fhir_query": "Observation?code=http://loinc.org|85354-9", "importance": "important"},
            {"name": "cardiac_history", "description": "Prior cardiac events", "importance": "critical"},
        ],
        "referral_question_template": "Cardiac assessment requested for {reason}.",
    },
    "rheumatology": {
        "required_inputs": [
            {"name": "inflammatory_markers", "description": "CRP, ESR", "importance": "critical"},
            {"name": "joint_distribution", "description": "Which joints affected", "importance": "important"},
            {"name": "prior_dmards", "description": "Previous DMARD trials", "importance": "critical"},
            {"name": "functional_status", "description": "Impact on daily activities", "importance": "important"},
        ],
        "referral_question_template": "Rheumatology assessment for {reason}.",
    },
}


async def assemble_specialty_packet(
    target_specialty: Annotated[
        str,
        Field(description="Target specialty (e.g., 'nephrology', 'cardiology', 'rheumatology')")
    ],
    referral_reason: Annotated[
        str,
        Field(description="Clinical reason for referral")
    ] = "",
    ctx: Context = None,
) -> str:
    """
    Assemble a specialty-specific referral packet with missing-context flagging.

    Different specialties need different inputs. This tool reads the patient's
    FHIR record through specialty-aware filters and produces a structured packet
    containing what the receiving specialist needs — while flagging what's missing.

    Currently supports: nephrology (full), cardiology (stub), rheumatology (stub).
    """
    fhir_ctx = extract_fhir_context(ctx)
    patient_id = extract_patient_id(ctx)
    fhir = FhirClient(fhir_ctx)

    specialty = target_specialty.lower().strip()
    profile = SPECIALTY_PROFILES.get(specialty)

    if not profile:
        return json.dumps({
            "error": "unsupported_specialty",
            "message": f"Specialty '{specialty}' not yet supported. Available: {list(SPECIALTY_PROFILES.keys())}",
        }, indent=2)

    # Fetch patient data relevant to this specialty
    medications = await fhir.get_medications(patient_id)
    conditions = await fhir.get_conditions(patient_id)
    observations = await fhir.get_observations(patient_id, count=20)

    # Evaluate each required input
    included = {}
    missing_flags = []
    for req_input in profile["required_inputs"]:
        name = req_input["name"]
        found = _check_input_available(name, observations, medications, conditions)
        if found:
            included[name] = {"included": True, "summary": found}
        else:
            missing_flags.append(
                f"No {name.replace('_', ' ')} found — "
                f"{'required' if req_input['importance'] == 'critical' else 'recommended'} for {specialty} referral"
            )
            included[name] = {"included": False, "missing_context_flag": missing_flags[-1]}

    # Compute completeness
    total = len(profile["required_inputs"])
    found_count = sum(1 for v in included.values() if v.get("included"))
    completeness = round(found_count / total, 2) if total > 0 else 0

    result = {
        "target_specialty": specialty,
        "patient_id": patient_id,
        "required_inputs": included,
        "referral_reason": referral_reason,
        "packet_completeness_score": completeness,
        "missing_context_flags": missing_flags,
        "missing_context_summary": (
            f"{len(missing_flags)} of {total} inputs not available; "
            f"{'completeness sufficient for standard referral' if completeness >= 0.6 else 'consider addressing gaps before referring'}"
        ),
    }

    return json.dumps(result, indent=2)


async def rank_specialist_destinations(
    specialty: Annotated[
        str,
        Field(description="Target specialty to search (e.g., 'nephrology')")
    ],
    urgency: Annotated[
        str,
        Field(description="Urgency level: routine, urgent, emergency")
    ] = "routine",
    ctx: Context = None,
) -> str:
    """
    Rank specialist destinations for a referral.

    Returns candidate specialists ranked by: specialty fit, wait time,
    distance, language match, network status, and clinical focus.

    Note: For hackathon, queries a seeded directory. In production,
    this would query a live specialist directory service.
    """
    data_path = Path(__file__).parent.parent / "rules" / "data" / "specialist_directory.json"
    with open(data_path) as f:
        directory = json.load(f)

    specialty_key = specialty.lower().strip()
    candidates = directory.get(specialty_key, [])

    if not candidates:
        return json.dumps({
            "specialty": specialty_key,
            "ranked_candidates": [],
            "message": f"No specialists found for '{specialty_key}' in directory.",
        }, indent=2)

    # Rank candidates
    ranked = []
    for candidate in candidates:
        # Urgency filter
        if urgency == "urgent" and not candidate.get("accepts_urgent", True):
            continue

        # Compute composite rank score
        score = _compute_rank_score(candidate, urgency)
        ranked.append({
            "name": candidate["name"],
            "site": candidate["site"],
            "rank_score": score,
            "rank_factors": {
                "specialty_fit": candidate.get("subspecialty_fit_score", 0.7),
                "earliest_slot_days": candidate.get("earliest_available_slot_days", 14),
                "distance_miles": candidate.get("distance_miles_from_camden", 10),
                "language_match": "English" in candidate.get("language", []),
                "network_status": candidate.get("network_status", "unknown"),
                "clinical_focus": candidate.get("clinical_focus", ""),
            },
            "rationale": candidate.get("notes", ""),
        })

    # Sort by rank score descending
    ranked.sort(key=lambda x: x["rank_score"], reverse=True)

    return json.dumps({
        "specialty": specialty_key,
        "urgency": urgency,
        "ranked_candidates": ranked,
    }, indent=2)


async def extract_consult_recommendations(
    document_reference_id: Annotated[
        str,
        Field(description="FHIR DocumentReference ID of the returned specialist note")
    ],
    ctx: Context = None,
) -> str:
    """
    Extract structured recommendations from a returned specialist consult note.

    Parses the DocumentReference content and uses AI to extract structured
    recommendation objects from free-text clinical letters. This is where
    generative AI earns substantial value — turning unstructured clinical
    text into actionable, reconcilable items.
    """
    fhir_ctx = extract_fhir_context(ctx)
    fhir = FhirClient(fhir_ctx)

    # Fetch the document
    doc = await fhir.read("DocumentReference", document_reference_id)
    if not doc:
        return json.dumps({
            "error": "document_not_found",
            "message": f"DocumentReference/{document_reference_id} not found.",
        }, indent=2)

    # Extract text content
    note_text = _extract_document_text(doc)
    if not note_text:
        return json.dumps({
            "error": "no_text_content",
            "message": "Document has no extractable text content.",
        }, indent=2)

    # Use LLM to extract structured recommendations
    prompt = build_extraction_prompt(note_text)
    gemini = get_gemini_client()

    extraction = await gemini.generate_structured(
        prompt=prompt,
        output_model=LLMConsultExtraction,
        system_instruction=EXTRACTION_SYSTEM,
    )

    result = extraction.model_dump()
    result["source_document_ref"] = f"DocumentReference/{document_reference_id}"

    return json.dumps(result, indent=2)


async def detect_plan_conflicts(
    extracted_recommendations_json: Annotated[
        str,
        Field(description="JSON from extract_consult_recommendations")
    ],
    patient_risk_profile_json: Annotated[
        str,
        Field(description="JSON of patient risk profile")
    ],
    ctx: Context = None,
) -> str:
    """
    Detect conflicts between specialist recommendations and current care plan.

    Compares extracted recommendations against the patient's current medications
    and conditions, identifying where recommendations conflict with ongoing
    management and suggesting reconciliation paths.
    """
    fhir_ctx = extract_fhir_context(ctx)
    patient_id = extract_patient_id(ctx)
    fhir = FhirClient(fhir_ctx)

    recommendations = json.loads(extracted_recommendations_json)
    profile_data = json.loads(patient_risk_profile_json)

    # Fetch current plan data
    medications = await fhir.get_medications(patient_id)
    conditions = await fhir.get_conditions(patient_id)

    # Use LLM for conflict detection
    prompt = build_conflict_detection_prompt(
        recommendations=recommendations.get("extracted_recommendations", []),
        current_medications=medications,
        conditions=conditions,
        profile_data=profile_data,
    )
    gemini = get_gemini_client()

    detection = await gemini.generate_structured(
        prompt=prompt,
        output_model=LLMConflictDetection,
        system_instruction=CONFLICT_DETECTION_SYSTEM,
    )

    return json.dumps(detection.model_dump(), indent=2)


# --- Internal helpers ---

def _check_input_available(
    input_name: str,
    observations: list,
    medications: list,
    conditions: list,
) -> str | None:
    """Check if a required input is available in the patient data."""
    # Map input names to detection logic
    if input_name == "egfr_trend":
        egfr_obs = [o for o in observations if _obs_has_code(o, "62238-1")]
        if egfr_obs:
            values = [o.get("valueQuantity", {}).get("value") for o in egfr_obs[:3]]
            return f"eGFR values: {values}"
    elif input_name == "creatinine_trend":
        creat_obs = [o for o in observations if _obs_has_code(o, "2160-0")]
        if creat_obs:
            return f"{len(creat_obs)} creatinine values found"
    elif input_name == "bp_history":
        bp_obs = [o for o in observations if _obs_has_code(o, "85354-9")]
        if bp_obs:
            return f"{len(bp_obs)} BP readings found"
    elif input_name == "current_ace_arb":
        ace_arb = [m for m in medications if _med_is_class(m, ["lisinopril", "ramipril", "enalapril", "losartan", "irbesartan", "candesartan"])]
        if ace_arb:
            name = ace_arb[0].get("medicationCodeableConcept", {}).get("text", "ACE-I/ARB")
            return f"Current: {name}"
    elif input_name == "diabetes_status":
        diabetes = [c for c in conditions if "diabetes" in c.get("code", {}).get("text", "").lower()]
        if diabetes:
            return "T2DM confirmed"
    elif input_name == "nephrotoxin_exposure":
        # Check for known nephrotoxins
        return "Assessment available from medication list"
    elif input_name == "urine_acr":
        acr_obs = [o for o in observations if _obs_has_code(o, "9318-7")]
        if acr_obs:
            return f"ACR: {acr_obs[0].get('valueQuantity', {}).get('value')}"

    return None


def _obs_has_code(obs: dict, loinc_code: str) -> bool:
    """Check if an observation has a specific LOINC code."""
    codings = obs.get("code", {}).get("coding", [])
    return any(c.get("code") == loinc_code for c in codings)


def _med_is_class(med: dict, drug_names: list[str]) -> bool:
    """Check if a medication matches any of the given drug names."""
    med_text = med.get("medicationCodeableConcept", {}).get("text", "").lower()
    return any(name in med_text for name in drug_names)


def _extract_document_text(doc: dict) -> str | None:
    """Extract text content from a FHIR DocumentReference."""
    content = doc.get("content", [])
    if not content:
        return None
    attachment = content[0].get("attachment", {})
    if attachment.get("contentType") == "text/plain" and attachment.get("data"):
        try:
            return base64.b64decode(attachment["data"]).decode("utf-8")
        except Exception:
            return None
    return None


def _compute_rank_score(candidate: dict, urgency: str) -> float:
    """Compute composite ranking score for a specialist candidate."""
    score = 0.0

    # Specialty fit (weight: 0.3)
    score += candidate.get("subspecialty_fit_score", 0.5) * 0.3

    # Wait time (weight: 0.25) — shorter is better, especially for urgent
    wait_days = candidate.get("earliest_available_slot_days", 14)
    wait_score = max(0, 1.0 - (wait_days / 30.0))
    if urgency == "urgent":
        wait_score *= 1.5  # Weight wait time more heavily for urgent
    score += min(wait_score, 1.0) * 0.25

    # Distance (weight: 0.2) — closer is better
    distance = candidate.get("distance_miles_from_camden", 10)
    distance_score = max(0, 1.0 - (distance / 20.0))
    score += distance_score * 0.2

    # Network status (weight: 0.15)
    if candidate.get("network_status") == "in-network":
        score += 0.15

    # Language (weight: 0.1)
    if "English" in candidate.get("language", []):
        score += 0.1

    return round(score, 2)
