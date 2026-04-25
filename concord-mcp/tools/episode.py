"""
Episode tools: BuildEpisodeBrief, GetTrendSummary.

BuildEpisodeBrief: Retrieves FHIR resources and uses LLM to compress into
a structured shared case packet for all specialist workers.

GetTrendSummary: Returns longitudinal trajectories for selected metrics
(eGFR, creatinine, potassium, weight, BNP) — no LLM, pure FHIR retrieval.
"""

import asyncio
import json
import logging
import traceback
import uuid
from datetime import datetime
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

from llm.prompts.episode_brief import SYSTEM_INSTRUCTION, build_episode_brief_prompt
from llm.schemas import (
    EpisodeBrief,
    LabSummary,
    LLMEpisodeBrief,
    MedicationSummary,
    ProblemSummary,
    TrendPoint,
    TrendSummary,
)
from medsafe_core.fhir.client import FhirClient
from medsafe_core.fhir.context import extract_fhir_context
from medsafe_core.llm.client import get_gemini_client

logger = logging.getLogger(__name__)

# Metric name → LOINC code
_LOINC_CODES: dict[str, str] = {
    "egfr": "62238-1",
    "creatinine": "2160-0",
    "potassium": "2823-3",
    "weight": "29463-7",
    "bnp": "42637-9",
}

_VALID_METRICS: frozenset[str] = frozenset(_LOINC_CODES.keys())

# Number of historical observations to fetch per metric
_TREND_OBS_COUNT = 12

# Number of recent observations to include in BuildEpisodeBrief context
_BRIEF_OBS_COUNT = 20


def _parse_obs_date(obs: dict) -> datetime | None:
    """Extract effectiveDateTime from a FHIR Observation."""
    raw = obs.get("effectiveDateTime") or obs.get("effectivePeriod", {}).get("start")
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19] if "T" in raw else raw, fmt.split("%z")[0])
        except ValueError:
            continue
    return None


def _parse_obs_value(obs: dict) -> float | None:
    """Extract numeric value from a FHIR Observation valueQuantity."""
    vq = obs.get("valueQuantity")
    if vq and "value" in vq:
        try:
            return float(vq["value"])
        except (TypeError, ValueError):
            pass
    return None


def _parse_obs_value_str(obs: dict) -> str | None:
    """Extract string value from a FHIR Observation (any value[x] type)."""
    if "valueQuantity" in obs:
        vq = obs["valueQuantity"]
        val = vq.get("value")
        unit = vq.get("unit", "")
        if val is not None:
            return f"{val} {unit}".strip()
    if "valueString" in obs:
        return obs["valueString"]
    if "valueCodeableConcept" in obs:
        return obs["valueCodeableConcept"].get("text", "")
    return None


def _compute_trajectory(points: list[TrendPoint]) -> tuple[str | None, float | None]:
    """
    Compute trajectory and rate-of-change from a list of TrendPoints.

    Returns (trajectory, rate_per_month) where trajectory is one of
    'stable', 'rising', 'falling', or None if fewer than 3 points.
    Rate is in the same units as the values, per 30-day month.

    Note: 'rising' / 'falling' are directional labels only — clinical
    significance depends on the metric (rising creatinine = worse;
    rising eGFR = better). The specialist LLMs interpret meaning.
    """
    if len(points) < 3:
        return None, None

    sorted_pts = sorted(points, key=lambda p: p.date)
    dates = [datetime.strptime(p.date[:10], "%Y-%m-%d") for p in sorted_pts]
    values = [p.value for p in sorted_pts]

    # Convert dates to days-since-first-point
    origin = dates[0]
    xs = [(d - origin).days for d in dates]
    n = len(xs)
    x_mean = sum(xs) / n
    y_mean = sum(values) / n

    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        return "stable", 0.0

    slope_per_day = num / den
    rate_per_month = round(slope_per_day * 30, 3)

    if abs(rate_per_month) < 0.5:
        trajectory = "stable"
    elif rate_per_month > 0:
        trajectory = "rising"
    else:
        trajectory = "falling"

    return trajectory, rate_per_month


async def get_trend_summary(
    metrics: Annotated[
        str,
        Field(
            description=(
                "JSON array of metric names to retrieve trends for. "
                "Valid values: 'egfr', 'creatinine', 'potassium', 'weight', 'bnp'. "
                "Example: '[\"egfr\", \"potassium\"]'"
            )
        ),
    ],
    ctx: Context = None,
) -> str:
    """
    Get longitudinal trend summaries for selected patient metrics.

    Returns trajectory (stable/improving/declining), rate of change per month,
    and time-series data points for each requested metric.

    No LLM — pure FHIR Observation retrieval and trajectory computation.
    """
    try:
        requested: list[str] = json.loads(metrics) if isinstance(metrics, str) else metrics
        invalid = [m for m in requested if m not in _VALID_METRICS]
        if invalid:
            return json.dumps({
                "error": "invalid_metrics",
                "invalid": invalid,
                "valid_values": sorted(_VALID_METRICS),
            }, indent=2)

        if ctx is None:
            return json.dumps({"error": "no_context", "message": "MCP context required."}, indent=2)

        fhir_ctx = extract_fhir_context(ctx)
        if not fhir_ctx.patient_id:
            return json.dumps({"error": "no_patient_id", "message": "Patient ID not found in context."}, indent=2)

        fhir = FhirClient(fhir_ctx)
        patient_id = fhir_ctx.patient_id

        result: dict = {"patient_id": patient_id, "metrics": {}}

        # Fetch all metric Observation queries in parallel — avoids sequential
        # 30s+ stalls when the FHIR proxy is slow on any single query.
        async def _fetch_one(metric_name: str) -> tuple[str, list[dict] | Exception]:
            try:
                obs = await fhir.get_observations(
                    patient_id, code=_LOINC_CODES[metric_name],
                    sort="-date", count=_TREND_OBS_COUNT,
                )
                return metric_name, obs
            except Exception as fetch_err:
                logger.warning(f"FHIR fetch for metric '{metric_name}' failed: {fetch_err}")
                return metric_name, fetch_err

        fetched = await asyncio.gather(*[_fetch_one(m) for m in requested])

        for metric, observations in fetched:
            if isinstance(observations, Exception):
                # Tolerate per-metric failures — record the gap instead of failing the whole call.
                result["metrics"][metric] = {
                    "data_points": [],
                    "trajectory": None,
                    "rate_of_change_per_month": None,
                    "latest_value": None,
                    "latest_date": None,
                    "unit": None,
                    "error": f"fetch_failed: {type(observations).__name__}",
                }
                continue

            points: list[TrendPoint] = []
            unit_str: str | None = None

            for obs in observations:
                date = _parse_obs_date(obs)
                value = _parse_obs_value(obs)
                if date is None or value is None:
                    continue

                unit_str = obs.get("valueQuantity", {}).get("unit")
                points.append(TrendPoint(
                    date=date.strftime("%Y-%m-%d"),
                    value=value,
                    unit=unit_str,
                ))

            # Sort ascending for trajectory computation and output
            points.sort(key=lambda p: p.date)
            trajectory, rate = _compute_trajectory(points)

            result["metrics"][metric] = {
                "data_points": [p.model_dump() for p in points],
                "trajectory": trajectory,
                "rate_of_change_per_month": rate,
                "latest_value": points[-1].value if points else None,
                "latest_date": points[-1].date if points else None,
                "unit": unit_str,
            }

            # Attach egfr-specific fields to top-level for EpisodeBrief integration
            if metric == "egfr" and trajectory:
                result["egfr_trajectory"] = trajectory
                result["egfr_rate_of_change_per_month"] = rate

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"get_trend_summary failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)


async def build_episode_brief(
    clinician_question: Annotated[
        str,
        Field(
            description=(
                "The clinician's clinical coordination question, e.g. "
                "'Cardiology wants more diuresis, nephrology worried about AKI — what's the unified plan?'"
            )
        ),
    ],
    ctx: Context = None,
) -> str:
    """
    Build a structured shared case packet from the patient's FHIR record.

    Retrieves Patient, Condition, MedicationRequest, and recent Observations,
    then uses LLM compression to produce a structured EpisodeBrief.

    The EpisodeBrief is the single shared input all specialist workers reason from.
    Returns the full EpisodeBrief JSON (including episode_brief_id for audit linkage).

    LLM TRANSLATES FHIR DATA — it does not make clinical verdicts here.
    """
    try:
        if ctx is None:
            return json.dumps({"error": "no_context", "message": "MCP context required."}, indent=2)

        fhir_ctx = extract_fhir_context(ctx)
        if not fhir_ctx.patient_id:
            return json.dumps({"error": "no_patient_id", "message": "Patient ID not found in context."}, indent=2)

        fhir = FhirClient(fhir_ctx)
        patient_id = fhir_ctx.patient_id

        # Fetch FHIR resources in parallel-ish (sequential but batched)
        patient = await fhir.get_patient(patient_id)
        conditions = await fhir.get_conditions(patient_id)
        medications = await fhir.get_medications(patient_id)
        observations = await fhir.get_observations(patient_id, sort="-date", count=_BRIEF_OBS_COUNT)

        fhir_context_json = json.dumps({
            "patient": patient,
            "conditions": conditions,
            "medications": medications,
            "observations": observations,
        }, default=str)

        # LLM compression: FHIR JSON → structured LLMEpisodeBrief
        prompt = build_episode_brief_prompt(fhir_context_json, clinician_question)
        llm = get_gemini_client()
        llm_output: LLMEpisodeBrief = await llm.generate_structured(
            prompt, LLMEpisodeBrief, system_instruction=SYSTEM_INSTRUCTION
        )

        episode_brief_id = str(uuid.uuid4())

        # Map LLMEpisodeBrief → EpisodeBrief (add server-side fields)
        brief = EpisodeBrief(
            patient_id=patient_id,
            decision_point=llm_output.decision_point,
            active_problems=[
                ProblemSummary(
                    code="unknown",
                    display=p.display,
                    status=p.status,
                    onset=p.onset,
                )
                for p in llm_output.active_problems
            ],
            active_medications=[
                MedicationSummary(
                    name=m.name,
                    dose=m.dose,
                    drug_class=m.drug_class,
                )
                for m in llm_output.active_medications
            ],
            recent_labs=[
                LabSummary(
                    code="unknown",
                    display=lab.display,
                    value=lab.value,
                    unit=lab.unit,
                    date=lab.date,
                    interpretation=lab.interpretation,
                )
                for lab in llm_output.recent_labs
            ],
            trend_summary=TrendSummary(),
            red_flags=llm_output.red_flags,
            missing_data=llm_output.missing_data,
            current_clinician_question=clinician_question,
            episode_brief_id=episode_brief_id,
        )

        return brief.model_dump_json(indent=2)

    except Exception as e:
        logger.error(f"build_episode_brief failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)
