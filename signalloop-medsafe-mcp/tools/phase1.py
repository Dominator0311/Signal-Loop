"""
Phase 1 MCP tools: Patient Risk Profile Building.

These tools use LLM (Gemini) to read the patient's FHIR record and produce
structured risk profiles for medication safety evaluation.
"""

import json
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

from fhir.context import extract_fhir_context, extract_patient_id
from fhir.client import FhirClient
from llm.client import get_gemini_client
from llm.prompts.profile_builder import SYSTEM_INSTRUCTION, build_profile_prompt
from llm.schemas import LLMPatientRiskProfile


async def build_patient_risk_profile(
    ctx: Context = None,
) -> str:
    """
    Build a structured patient risk profile for medication safety evaluation.

    Reads the patient's full FHIR record (demographics, conditions, medications,
    allergies, observations, documents) and uses AI to produce a structured
    risk profile focused on factors relevant to prescribing safety.

    The profile is used by check_medication_safety to parameterise deterministic
    safety rules. Call this once per patient session.
    """
    fhir_ctx = extract_fhir_context(ctx)
    patient_id = extract_patient_id(ctx)
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

    return json.dumps(profile.model_dump(), indent=2)


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
    fhir_ctx = extract_fhir_context(ctx)
    patient_id = extract_patient_id(ctx)
    fhir = FhirClient(fhir_ctx)

    # Fetch key data
    medications = await fhir.get_medications(patient_id)
    conditions = await fhir.get_conditions(patient_id)
    observations = await fhir.get_observations(patient_id, count=10)

    # Use LLM to select relevant context
    gemini = get_gemini_client()

    prompt = f"""\
Given this new clinical signal for the patient:
"{signal_description}"

And this patient's record:
Conditions: {json.dumps([c.get("code", {}).get("text", "") for c in conditions])}
Medications: {json.dumps([m.get("medicationCodeableConcept", {}).get("text", "") for m in medications])}
Recent labs: {json.dumps([{{
    "name": o.get("code", {{}}).get("text", ""),
    "value": o.get("valueQuantity", {{}}).get("value"),
    "date": o.get("effectiveDateTime", "")
}} for o in observations[:5]])}

Select the items from the record that are RELEVANT to interpreting this signal.
For each selected item, explain WHY it matters for this signal.
Also identify any MISSING context that would strengthen interpretation.
"""

    # Return as structured text (simpler than structured schema here)
    response = await gemini.generate_text(
        prompt=prompt,
        system_instruction="You are a clinical AI selecting relevant context for signal interpretation. Be concise and specific.",
    )

    result = {
        "signal": signal_description,
        "patient_id": patient_id,
        "relevant_context": response,
        "medications_count": len(medications),
        "conditions_count": len(conditions),
    }

    return json.dumps(result, indent=2)


# --- Internal helpers ---

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
