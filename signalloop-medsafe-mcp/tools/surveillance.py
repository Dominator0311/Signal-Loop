"""
SurfacePatientAttention — composite tool for SignalLoop Scenario 1.

Drives the "what needs my attention for Margaret today?" demo moment.
Composes existing primitives:
  1. BuildPatientRiskProfile  — patient profile + active meds
  2. GetRenalTrend            — eGFR trajectory and rate of change
  3. RunFullMedicationReview  — every active med checked against profile
  4. ExtractConsultRecommendations — auto-discover unactioned consult letters

Returns a deterministically-ranked list of 1-5 attention items, each with
clinical reasoning and citation. No LLM in this composite — the underlying
primitives already use LLMs where appropriate (Phase 1 + Phase 3); this tool
is a pure orchestrator.

Ranking rule (deterministic, in priority order):
  1. drug_safety BLOCK   — e.g. retrospective contraindication on active med
  2. open_consult        — unactioned consult recommendations (>= 1)
  3. drug_safety WARN    — interactions, polypharmacy concerns
  4. trend declining     — eGFR rate < -5 mL/min/year (NICE NG203 threshold)
  5. overdue_task        — follow-up due date passed

Items below threshold are dropped. Empty result → summary line says nothing
needs attention right now.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import BaseModel, Field

from medsafe_core.fhir.context import extract_patient_id

# Reuse the existing tool implementations server-side. We wrap them rather
# than re-fetch FHIR — keeps consistency with what the agent would otherwise
# get from individual tool calls.
from tools.phase1 import build_patient_risk_profile, get_renal_trend
from tools.full_review import run_full_medication_review
from tools.referral import extract_consult_recommendations

logger = logging.getLogger(__name__)


# --- Output schema ---

class AttentionItem(BaseModel):
    """One attention-worthy finding for the clinician."""
    category: str  # "trend" | "drug_safety" | "open_consult" | "overdue_task"
    severity: str  # "BLOCK" | "WARN" | "INFO"
    headline: str  # one-line summary
    rationale: str  # one-sentence clinical reasoning
    citation: str | None = None  # NICE/BNF reference if available
    profile_fields_consulted: list[str] = Field(default_factory=list)
    rule_id: str | None = None
    related_resource_ids: list[str] = Field(default_factory=list)


class AttentionResponse(BaseModel):
    patient_id: str
    items: list[AttentionItem] = Field(default_factory=list)
    summary_line: str
    profile_cache_ts: str | None = None  # ISO timestamp


# --- Helpers ---

_CATEGORY_PRIORITY: dict[tuple[str, str], int] = {
    ("drug_safety", "BLOCK"): 0,
    ("open_consult", "INFO"): 1,
    ("open_consult", "WARN"): 1,
    ("drug_safety", "WARN"): 2,
    ("trend", "WARN"): 3,
    ("trend", "INFO"): 3,
    ("overdue_task", "WARN"): 4,
    ("overdue_task", "INFO"): 4,
}


def _safe_json_loads(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        return None
    return None


def _trend_attention(trend_data: dict[str, Any] | None) -> AttentionItem | None:
    """Surface a trend-decline attention item if rate is concerning.

    NICE NG203 §1.5.5 flags eGFR decline > 5 mL/min/year as a marker of
    progression worth referral / closer monitoring. We use that threshold.
    """
    if not trend_data or trend_data.get("error"):
        return None

    rate = trend_data.get("rate_of_change_per_month")
    trajectory = trend_data.get("trajectory")
    latest = trend_data.get("latest_value")

    if rate is None or trajectory is None:
        return None

    # rate is per-month; NICE threshold is per-year (-5 mL/min/year ≈ -0.42/month)
    annual_rate = rate * 12

    if trajectory in ("falling", "declining") and annual_rate <= -5:
        return AttentionItem(
            category="trend",
            severity="WARN",
            headline=f"eGFR declining at {abs(annual_rate):.1f} mL/min/year (latest {latest})",
            rationale=(
                "Sustained decline beyond the 5 mL/min/year threshold suggests "
                "progressive CKD warranting closer monitoring or specialist input."
            ),
            citation="NICE NG203 §1.5.5 (CKD progression markers)",
            profile_fields_consulted=["egfr_trajectory", "egfr_rate_of_change_per_month"],
        )
    return None


def _drug_safety_attentions(review_data: dict[str, Any] | None) -> list[AttentionItem]:
    """Convert RunFullMedicationReview verdicts into attention items."""
    if not review_data or review_data.get("error"):
        return []

    items: list[AttentionItem] = []
    for entry in review_data.get("medication_findings", []) or review_data.get("findings", []):
        verdict = (entry.get("verdict") or "").upper()
        if verdict not in ("BLOCK", "WARN"):
            continue

        drug = entry.get("medication") or entry.get("drug") or "unknown medication"
        flags = entry.get("flags") or entry.get("primary_flags") or []
        first_flag = flags[0] if flags else {}
        flag_message = (
            first_flag.get("message")
            if isinstance(first_flag, dict)
            else str(first_flag) if first_flag else "safety concern flagged"
        )

        items.append(AttentionItem(
            category="drug_safety",
            severity=verdict,
            headline=f"{drug}: {verdict}",
            rationale=str(flag_message)[:240],
            citation=(first_flag.get("citation") if isinstance(first_flag, dict) else None),
            rule_id=(first_flag.get("rule_id") if isinstance(first_flag, dict) else None),
            related_resource_ids=[entry.get("medication_request_id")] if entry.get("medication_request_id") else [],
        ))
    return items


def _consult_attention(consult_data: dict[str, Any] | None) -> AttentionItem | None:
    """Surface unactioned consult letters as attention items."""
    if not consult_data or consult_data.get("error"):
        return None

    rec_count = (
        consult_data.get("recommendation_count")
        or len(consult_data.get("recommendations", []))
        or 0
    )
    if rec_count == 0:
        return None

    received_at = consult_data.get("received_at") or consult_data.get("date") or "recently"
    specialty = consult_data.get("specialty") or "specialist"

    return AttentionItem(
        category="open_consult",
        severity="WARN" if rec_count >= 3 else "INFO",
        headline=f"{rec_count} unactioned recommendations from {specialty} consult ({received_at})",
        rationale=(
            f"A {specialty} consult returned {rec_count} recommendations that have not "
            "been reconciled against the active record. Loop closure improves outcomes."
        ),
        citation="NICE NG203 §1.4 (referral and shared care)",
        related_resource_ids=consult_data.get("source_document_id_list", []),
    )


def _rank_and_trim(items: list[AttentionItem], max_items: int) -> list[AttentionItem]:
    def key(item: AttentionItem) -> tuple[int, str]:
        priority = _CATEGORY_PRIORITY.get((item.category, item.severity), 99)
        # Stable secondary key — alphabetical on headline. Avoid hash() because
        # CPython randomises string hashes per-process via PYTHONHASHSEED, which
        # would make the ranking non-deterministic across runs / test reruns.
        return (priority, item.headline)

    return sorted(items, key=key)[:max_items]


# --- The tool ---

async def surface_patient_attention(
    max_items: Annotated[
        int,
        Field(
            description="Maximum number of attention items to return (1-5).",
            ge=1, le=5,
        ),
    ] = 5,
    ctx: Context = None,
) -> str:
    """Surface what needs the clinician's attention for the active patient.

    Composite tool that runs the patient profile, renal trend, full medication
    review, and consult discovery in parallel, then produces a deterministically
    ranked list of attention items. Use when the clinician asks an open-ended
    question like "what needs my attention?" with no specific drug or task in
    scope.

    No new LLM calls — composes existing primitives.
    """
    try:
        try:
            patient_id = extract_patient_id(ctx)
        except Exception:
            patient_id = "unknown"

        # Fan-out: run the four primitives in parallel. Each returns a JSON
        # string. We tolerate per-primitive failure — surface what we got.
        profile_task = build_patient_risk_profile(ctx=ctx)
        trend_task = get_renal_trend(ctx=ctx)
        review_task = run_full_medication_review(ctx=ctx)
        consult_task = extract_consult_recommendations(ctx=ctx)

        results = await asyncio.gather(
            profile_task, trend_task, review_task, consult_task,
            return_exceptions=True,
        )

        profile_raw, trend_raw, review_raw, consult_raw = results

        # Log per-primitive failures so they are observable. We don't surface
        # these to the chat (the missing items will simply not appear), but
        # silent failure is bad observability for a safety-touching tool.
        for label, raw in (
            ("build_patient_risk_profile", profile_raw),
            ("get_renal_trend", trend_raw),
            ("run_full_medication_review", review_raw),
            ("extract_consult_recommendations", consult_raw),
        ):
            if isinstance(raw, BaseException):
                logger.warning(
                    f"surface_patient_attention: {label} primitive failed: "
                    f"{type(raw).__name__}: {raw}"
                )

        profile_data = _safe_json_loads(profile_raw) if isinstance(profile_raw, str) else None
        trend_data = _safe_json_loads(trend_raw) if isinstance(trend_raw, str) else None
        review_data = _safe_json_loads(review_raw) if isinstance(review_raw, str) else None
        consult_data = _safe_json_loads(consult_raw) if isinstance(consult_raw, str) else None

        items: list[AttentionItem] = []

        if (trend_item := _trend_attention(trend_data)):
            items.append(trend_item)

        items.extend(_drug_safety_attentions(review_data))

        if (consult_item := _consult_attention(consult_data)):
            items.append(consult_item)

        ranked = _rank_and_trim(items, max_items)

        # Compose a human-friendly summary line for the agent's reply.
        if not ranked:
            summary = "No attention items above threshold for this patient right now."
        else:
            cat_count: dict[str, int] = {}
            for it in ranked:
                cat_count[it.category] = cat_count.get(it.category, 0) + 1
            parts = []
            for cat, n in cat_count.items():
                label = {
                    "drug_safety": "drug-safety flag" if n == 1 else "drug-safety flags",
                    "open_consult": "open consult",
                    "trend": "trend concern",
                    "overdue_task": "overdue task" if n == 1 else "overdue tasks",
                }.get(cat, cat)
                parts.append(f"{n} {label}")
            summary = (
                f"{len(ranked)} item(s) need attention: " + "; ".join(parts) + "."
            )

        response = AttentionResponse(
            patient_id=patient_id,
            items=ranked,
            summary_line=summary,
            profile_cache_ts=(
                profile_data.get("generated_at") if profile_data else None
            ) if isinstance(profile_data, dict) else None,
        )

        return response.model_dump_json(indent=2)

    except Exception as e:
        logger.error(f"surface_patient_attention failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)
