"""
Phase 1 MCP tools: Patient Risk Profile Building.

These tools use LLM (Gemini) to read the patient's FHIR record and produce
structured risk profiles for medication safety evaluation.
"""

import json
import logging
import traceback
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

from medsafe_core.fhir.context import extract_fhir_context, extract_patient_id
from medsafe_core.fhir.client import FhirClient
from medsafe_core.llm.cache import patient_profile_cache
from medsafe_core.llm.client import get_gemini_client
from medsafe_core.llm.prompts.profile_builder import SYSTEM_INSTRUCTION, build_profile_prompt
from medsafe_core.llm.schemas import LLMPatientRiskProfile
from medsafe_core.rules.normalizer import normalize_medication as _normalize_med

logger = logging.getLogger(__name__)


def _enrich_profile_with_canonical_classes(profile: LLMPatientRiskProfile) -> None:
    """
    Inject canonical drug class strings into the profile in-place.

    Phase 1 LLM writes medication classes in natural language ("ACE inhibitor",
    "Loop diuretic"). Our deterministic rules engine requires exact enum strings
    ("ACE_INHIBITOR", "LOOP_DIURETIC", "DIURETIC"). This mismatch caused the
    triple-whammy rule to silently miss.

    The fix: after the LLM builds the profile, run each medication through the
    normalizer (which uses drug_classes.json — the same source the rules engine
    uses). Replace the LLM's classes with canonical values. Keep the LLM's
    interaction_relevant_properties and notes for clinical context.

    LLM-provided values are preserved if normalization fails (unknown drug).
    """
    for med in profile.active_medications:
        normalized = _normalize_med(med.name)
        if normalized.resolved and normalized.drug_classes:
            llm_original = list(med.classes)
            med.classes = list(normalized.drug_classes)
            logger.info(
                f"Enriched {med.name}: LLM wrote {llm_original} → canonical {med.classes}"
            )


async def build_patient_risk_profile(
    ctx: Context = None,
) -> str:
    """
    Build a structured patient risk profile for medication safety evaluation.

    Reads the patient's full FHIR record (demographics, conditions, medications,
    allergies, observations, documents) and uses AI to produce a structured
    risk profile focused on factors relevant to prescribing safety.

    The profile is used by check_medication_safety to parameterise deterministic
    safety rules. Call this once per patient session — subsequent calls within
    60 minutes return the cached profile (no LLM cost). Cache is per-patient.

    If patient data has materially changed and you need a fresh profile,
    use RefreshPatientRiskProfile instead.

    On failure, returns structured error JSON (never raises a raw string)
    so downstream tools can detect and report the failure cleanly.
    """
    try:
        fhir_ctx = extract_fhir_context(ctx)
        patient_id = extract_patient_id(ctx)

        # Always check cache first (saves LLM cost + time)
        cached = await patient_profile_cache.get(patient_id)
        if cached is not None:
            logger.info(f"Profile cache HIT for patient {patient_id}")
            return cached
        logger.info(f"Profile cache MISS for patient {patient_id} — building fresh")

        fhir = FhirClient(fhir_ctx)

        # Fetch comprehensive patient data
        patient_data = await _fetch_patient_data(fhir, patient_id)

        # Generate structured profile via LLM
        prompt = build_profile_prompt(patient_data)
        gemini = get_gemini_client()

        profile = await gemini.generate_structured(
            prompt=prompt,
            output_model=LLMPatientRiskProfile,
            system_instruction=SYSTEM_INSTRUCTION,
        )

        # Ensure patient_id is set correctly
        profile.patient_id = patient_id

        # Extract first_name deterministically from the FHIR Patient resource.
        # Agents need this to address the patient by name in rendered responses.
        # We do NOT trust the LLM to extract this — too easy to confuse with
        # names mentioned elsewhere in the record (providers, relatives, etc.).
        profile.first_name = _extract_first_name(patient_data.get("patient"))

        # Enrich medication classes with canonical enum strings so the
        # deterministic rules engine (Phase 2) can match reliably.
        _enrich_profile_with_canonical_classes(profile)

        profile_json = json.dumps(profile.model_dump(), indent=2)

        # Cache for subsequent calls in this session
        await patient_profile_cache.set(patient_id, profile_json)
        logger.info(f"Profile cached for patient {patient_id}")

        return profile_json

    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"build_patient_risk_profile failed: {e}\n{error_trace}")
        return json.dumps({
            "error": "profile_build_failed",
            "error_type": type(e).__name__,
            "message": str(e),
            "hint": "Check the server logs for full traceback. Common causes: Gemini rate limit (429), missing API key, FHIR server unreachable.",
        }, indent=2)


async def refresh_patient_risk_profile(
    ctx: Context = None,
) -> str:
    """
    Invalidate the cached patient risk profile and rebuild it from scratch.

    Use ONLY when patient data has materially changed during the session:
      - New lab result arrived (e.g., updated eGFR)
      - New medication added or stopped
      - New condition diagnosed
      - New allergy recorded

    This forces a Gemini LLM call. Do not invoke casually — normal tool
    orchestration should use BuildPatientRiskProfile (which caches).
    """
    try:
        patient_id = extract_patient_id(ctx)
        await patient_profile_cache.invalidate(patient_id)
        logger.info(f"Profile cache invalidated for patient {patient_id}")
        # Delegate to the main builder — will now miss cache and rebuild
        return await build_patient_risk_profile(ctx=ctx)
    except Exception as e:
        logger.error(f"refresh_patient_risk_profile failed: {e}")
        return json.dumps({
            "error": "refresh_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)


async def get_renal_trend(
    lab_code: Annotated[
        str,
        Field(description="LOINC code for the lab (e.g., '62238-1' for eGFR, '2160-0' for creatinine)")
    ] = "62238-1",
    lookback_days: Annotated[
        int,
        Field(description="Number of days to look back for trend data")
    ] = 365,
    ctx: Context = None,
) -> str:
    """
    Get renal function trend data (eGFR or creatinine) as structured output.

    Returns longitudinal lab values with trajectory analysis and rate of change.
    No LLM involved — pure data retrieval and computation.
    """
    fhir_ctx = extract_fhir_context(ctx)
    patient_id = extract_patient_id(ctx)
    fhir = FhirClient(fhir_ctx)

    observations = await fhir.get_observations(
        patient_id=patient_id,
        code=lab_code,
        count=20,
    )

    if not observations:
        return json.dumps({
            "code": lab_code,
            "values": [],
            "trajectory": "unknown",
            "interpretation": "No observations found for this lab code.",
        })

    # Extract values and dates
    values = []
    for obs in observations:
        value_qty = obs.get("valueQuantity", {})
        value = value_qty.get("value")
        unit = value_qty.get("unit", "")
        date = obs.get("effectiveDateTime", "")
        if value is not None:
            values.append({"date": date, "value": value, "unit": unit})

    # Sort chronologically (oldest first)
    values.sort(key=lambda v: v["date"])

    # Compute trajectory
    trajectory = "unknown"
    rate_per_month = None

    if len(values) >= 2:
        first_val = values[0]["value"]
        last_val = values[-1]["value"]
        delta = last_val - first_val

        # Estimate months between first and last
        first_date = values[0]["date"][:10]
        last_date = values[-1]["date"][:10]
        months = _estimate_months_between(first_date, last_date)

        if months > 0:
            rate_per_month = round(delta / months, 1)

        if delta < -2:
            trajectory = "declining"
        elif delta > 2:
            trajectory = "improving"
        else:
            trajectory = "stable"

    # Build interpretation
    interpretation = _build_trend_interpretation(values, trajectory, rate_per_month, lab_code)

    result = {
        "code": f"LOINC:{lab_code}",
        "label": "eGFR" if lab_code == "62238-1" else "Creatinine",
        "values": values,
        "trajectory": trajectory,
        "rate_of_change_per_month": rate_per_month,
        "interpretation": interpretation,
    }

    return json.dumps(result, indent=2)


async def get_relevant_context(
    signal_description: Annotated[
        str,
        Field(description="Description of the clinical signal to contextualise (e.g., 'new eGFR 42, declining from 58')")
    ],
    ctx: Context = None,
) -> str:
    """
    Get the subset of patient context relevant to a specific clinical signal.

    Uses the patient risk profile to select which chart facts matter for
    interpreting a new signal. Returns selected context with reasoning
    for why each item was included.
    """
    try:
        fhir_ctx = extract_fhir_context(ctx)
        patient_id = extract_patient_id(ctx)
        fhir = FhirClient(fhir_ctx)

        # Fetch key data
        medications = await fhir.get_medications(patient_id)
        conditions = await fhir.get_conditions(patient_id)
        observations = await fhir.get_observations(patient_id, count=10)

        # Build serialisable summaries outside the f-string to avoid brace-escape issues
        condition_summaries = [c.get("code", {}).get("text", "") for c in conditions]
        medication_summaries = [
            m.get("medicationCodeableConcept", {}).get("text", "") for m in medications
        ]
        recent_labs = [
            {
                "name": o.get("code", {}).get("text", ""),
                "value": o.get("valueQuantity", {}).get("value"),
                "date": o.get("effectiveDateTime", ""),
            }
            for o in observations[:5]
        ]

        conditions_json = json.dumps(condition_summaries)
        medications_json = json.dumps(medication_summaries)
        labs_json = json.dumps(recent_labs)

        prompt = (
            f"Given this new clinical signal for the patient:\n"
            f'"{signal_description}"\n\n'
            f"And this patient's record:\n"
            f"Conditions: {conditions_json}\n"
            f"Medications: {medications_json}\n"
            f"Recent labs: {labs_json}\n\n"
            "Select the items from the record that are RELEVANT to interpreting this signal.\n"
            "For each selected item, explain WHY it matters for this signal.\n"
            "Also identify any MISSING context that would strengthen interpretation.\n"
        )

        gemini = get_gemini_client()
        response = await gemini.generate_text(
            prompt=prompt,
            system_instruction=(
                "You are a clinical AI selecting relevant context for signal interpretation. "
                "Be concise and specific."
            ),
        )

        result = {
            "signal": signal_description,
            "patient_id": patient_id,
            "relevant_context": response,
            "medications_count": len(medications),
            "conditions_count": len(conditions),
        }
        return json.dumps(result, indent=2)

    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"get_relevant_context failed: {e}\n{error_trace}")
        return json.dumps({
            "error": "context_retrieval_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)


# --- Internal helpers ---

def _extract_first_name(patient_resource: dict | None) -> str | None:
    """
    Deterministically extract the patient's first name from a FHIR Patient resource.

    FHIR R4 Patient.name is an array of HumanName, each with a `given` array
    (first + middle names). We take the first entry's first given name. Prefers
    entries with use='official' when present.

    Returns None if the resource is missing, malformed, or has no given name.
    """
    if not patient_resource:
        return None
    names = patient_resource.get("name") or []
    if not names:
        return None
    # Prefer official name if available
    official = next((n for n in names if n.get("use") == "official"), None)
    name_entry = official or names[0]
    given = name_entry.get("given") or []
    if not given:
        return None
    first = given[0]
    if not isinstance(first, str) or not first.strip():
        return None
    # Strip trailing digits some synthetic datasets add (e.g., "Margaret123")
    return first.rstrip("0123456789").strip() or first.strip()


async def _fetch_patient_data(fhir: FhirClient, patient_id: str) -> dict:
    """Fetch comprehensive patient data from FHIR for profile building."""
    patient = await fhir.get_patient(patient_id)
    conditions = await fhir.get_conditions(patient_id)
    medications = await fhir.get_medications(patient_id)
    allergies = await fhir.get_allergies(patient_id)
    observations = await fhir.get_observations(patient_id, count=20)
    documents = await fhir.get_documents(patient_id)

    return {
        "patient": patient or {},
        "conditions": conditions,
        "medications": medications,
        "allergies": allergies,
        "observations": observations,
        "documents": documents,
    }


def _estimate_months_between(date1: str, date2: str) -> float:
    """Rough month estimate between two ISO date strings."""
    from datetime import date as dt_date
    try:
        d1 = dt_date.fromisoformat(date1)
        d2 = dt_date.fromisoformat(date2)
        days = (d2 - d1).days
        return max(days / 30.44, 0.1)  # Avoid division by zero
    except (ValueError, TypeError):
        return 1.0


def _build_trend_interpretation(
    values: list[dict],
    trajectory: str,
    rate_per_month: float | None,
    lab_code: str,
) -> str:
    """Build a human-readable trend interpretation."""
    if not values:
        return "No data available for trend analysis."

    if len(values) == 1:
        return f"Single value only ({values[0]['value']} on {values[0]['date'][:10]}). No trend computable."

    lab_name = "eGFR" if lab_code == "62238-1" else "Creatinine"
    first = values[0]
    last = values[-1]

    parts = [
        f"{lab_name}: {first['value']} ({first['date'][:10]}) → {last['value']} ({last['date'][:10]})",
        f"Trajectory: {trajectory}",
    ]

    if rate_per_month is not None:
        parts.append(f"Rate of change: {rate_per_month} per month")

    if trajectory == "declining" and lab_code == "62238-1" and rate_per_month and rate_per_month < -3:
        parts.append("ALERT: Rapid decline exceeding 3 points/month — warrants urgent review")

    return "; ".join(parts)
