"""
FHIR write tools: Create clinical resources in the workspace FHIR server.

All writes require prior clinician approval (enforced at the agent level,
not here — tools execute what they're told, governance lives in the agent
system prompt).

Each tool constructs a valid FHIR resource and POSTs it to the server,
returning the created resource with its server-assigned ID.
"""

import json
import logging
import re
import traceback
from datetime import datetime, timedelta, timezone
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

from medsafe_core.fhir.context import extract_fhir_context, extract_patient_id
from medsafe_core.fhir.client import FhirClient
from medsafe_core.fhir.resource_builders import (
    build_medication_request,
    build_service_request,
    build_task,
    build_communication,
    build_audit_event,
)

logger = logging.getLogger(__name__)


# --- Internal helpers ---

_TIMING_PATTERN = re.compile(
    r"(?:in\s+|at\s+|after\s+)?(\d+)\s*(day|days|week|weeks|month|months|year|years)",
    re.IGNORECASE,
)


def _compute_due_date_from_timing(timing: str | None) -> str | None:
    """
    Parse a natural-language timing string and compute an ISO date relative to now.

    Accepts strings like "6 weeks", "3 months", "in 1 week", "at 6 weeks",
    "2 weeks from now". Returns YYYY-MM-DD or None if unparseable.

    This is deterministic — computed server-side from datetime.now() — so the
    result never depends on the LLM's (often stale) sense of "today".
    """
    if not timing:
        return None
    match = _TIMING_PATTERN.search(timing)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()

    now = datetime.now(tz=timezone.utc)
    if unit.startswith("day"):
        delta = timedelta(days=amount)
    elif unit.startswith("week"):
        delta = timedelta(weeks=amount)
    elif unit.startswith("month"):
        # Approximate a month as 30 days (good enough for follow-up scheduling).
        delta = timedelta(days=amount * 30)
    elif unit.startswith("year"):
        delta = timedelta(days=amount * 365)
    else:
        return None
    return (now + delta).strftime("%Y-%m-%d")


def _coerce_due_date(due_date: str | None, timing: str | None) -> str | None:
    """
    Return a safe due_date for a Task.

    Priority:
      1. If `timing` is parseable, use it — deterministic, source-of-truth.
      2. Else if `due_date` is provided and parses AND is in the future, use it.
      3. Else fall back to `timing` parse (if any) or None.

    Prevents the common failure mode where the LLM fabricates a past date
    because its training cutoff is older than "today".
    """
    computed = _compute_due_date_from_timing(timing)
    if computed:
        return computed

    if due_date:
        try:
            parsed = datetime.strptime(due_date, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(f"Ignoring malformed due_date: {due_date!r}")
            return None
        today = datetime.now(tz=timezone.utc).date()
        if parsed < today:
            logger.warning(
                f"LLM provided past due_date ({due_date}); coercing to None. "
                f"Agent should pass a `timing` string instead."
            )
            return None
        return due_date

    return None


async def draft_medication_request(
    medication_name: Annotated[str, Field(description="Canonical medication name (e.g., 'paracetamol 1g tablets')")],
    medication_code: Annotated[str, Field(description="dm+d or medication code from normalize_medication")],
    dose_text: Annotated[str, Field(description="Dosage instructions (e.g., 'Take 1g four times daily')")],
    reason: Annotated[str, Field(description="Clinical reason for prescribing")],
    ctx: Context = None,
) -> str:
    """
    Create a FHIR MedicationRequest after clinician approval.

    Only call this AFTER check_medication_safety has returned a clean verdict
    (or after the clinician has explicitly overridden with a documented reason).
    Returns the created resource with server-assigned ID.
    """
    fhir_ctx = extract_fhir_context(ctx)
    patient_id = extract_patient_id(ctx)
    fhir = FhirClient(fhir_ctx)

    resource = build_medication_request(patient_id, medication_name, medication_code, dose_text, reason)
    created = await fhir.create("MedicationRequest", resource)

    return json.dumps({
        "status": "created",
        "resource_type": "MedicationRequest",
        "id": created.get("id"),
        "medication": medication_name,
        "message": f"MedicationRequest created for {medication_name}. Resource ID: {created.get('id')}",
    }, indent=2)


async def draft_service_request(
    specialty: Annotated[str, Field(description="Target specialty (e.g., 'nephrology')")],
    reason: Annotated[str, Field(description="Clinical reason for referral")],
    urgency: Annotated[str, Field(description="Urgency: routine, urgent, asap")] = "routine",
    note: Annotated[str, Field(description="Additional notes for the referral")] = "",
    ctx: Context = None,
) -> str:
    """
    Create a FHIR ServiceRequest for a specialist referral.

    Only call this after the clinician has approved the referral and
    reviewed the specialty-specific packet from assemble_specialty_packet.
    """
    fhir_ctx = extract_fhir_context(ctx)
    patient_id = extract_patient_id(ctx)
    fhir = FhirClient(fhir_ctx)

    resource = build_service_request(patient_id, specialty, reason, urgency, note)
    created = await fhir.create("ServiceRequest", resource)

    return json.dumps({
        "status": "created",
        "resource_type": "ServiceRequest",
        "id": created.get("id"),
        "specialty": specialty,
        "urgency": urgency,
        "message": f"ServiceRequest created for {specialty} referral. Resource ID: {created.get('id')}",
    }, indent=2)


async def draft_followup_task(
    description: Annotated[
        str,
        Field(description="Task description (e.g., 'Repeat eGFR and electrolytes')"),
    ],
    timing: Annotated[
        str | None,
        Field(
            description=(
                "PREFERRED way to schedule the task. Pass a natural-language "
                "interval like '6 weeks', '3 months', '1 week'. The tool computes "
                "the actual due date from today. Use this instead of due_date — "
                "the LLM's sense of 'today' is often wrong."
            )
        ),
    ] = None,
    due_date: Annotated[
        str | None,
        Field(
            description=(
                "FALLBACK only. Explicit due date in ISO format (YYYY-MM-DD). "
                "Prefer `timing` for relative scheduling. Past dates are rejected."
            )
        ),
    ] = None,
    priority: Annotated[
        str, Field(description="Priority: routine, urgent, asap, stat")
    ] = "routine",
    ctx: Context = None,
) -> str:
    """
    Create a FHIR Task for follow-up work (e.g., repeat labs, monitoring).

    Due-date handling is deterministic: pass a `timing` string ('6 weeks',
    '3 months', etc.) and the tool computes the actual date from today. An
    explicit `due_date` is accepted as a fallback but past dates are ignored.
    """
    fhir_ctx = extract_fhir_context(ctx)
    patient_id = extract_patient_id(ctx)
    fhir = FhirClient(fhir_ctx)

    resolved_due_date = _coerce_due_date(due_date, timing)

    resource = build_task(patient_id, description, resolved_due_date, priority)
    created = await fhir.create("Task", resource)

    return json.dumps(
        {
            "status": "created",
            "resource_type": "Task",
            "id": created.get("id"),
            "description": description,
            "due_date": resolved_due_date,
            "timing_input": timing,
            "message": (
                f"Task created: '{description}'. Resource ID: {created.get('id')}"
                + (f" (due {resolved_due_date})" if resolved_due_date else "")
            ),
        },
        indent=2,
    )


async def log_override(
    override_reason: Annotated[str, Field(description="Clinician's reason for overriding the safety alert")],
    override_analysis_json: Annotated[str, Field(description="JSON from analyse_override_reason tool")],
    original_verdict_json: Annotated[str, Field(description="JSON of the original safety verdict that was overridden")],
    ctx: Context = None,
) -> str:
    """
    Log a MedSafe override as a permanent FHIR AuditEvent.

    Creates an audit trail when a clinician overrides a safety alert.
    Incorporates the structured analysis from analyse_override_reason.
    This record is permanent and queryable via AuditEvent.
    """
    try:
        fhir_ctx = extract_fhir_context(ctx)
        patient_id = extract_patient_id(ctx)
        fhir = FhirClient(fhir_ctx)

        # Parse inputs defensively — the agent may occasionally pass malformed JSON
        try:
            analysis = json.loads(override_analysis_json) if override_analysis_json else {}
        except json.JSONDecodeError:
            analysis = {"raw_analysis": override_analysis_json}
        try:
            verdict = json.loads(original_verdict_json) if original_verdict_json else {}
        except json.JSONDecodeError:
            verdict = {"raw_verdict": original_verdict_json}

        description = (
            f"MedSafe override: {verdict.get('proposed_medication', 'unknown medication')}. "
            f"Original verdict: {verdict.get('verdict', 'unknown')}. "
            f"Classification: {analysis.get('override_classification', 'unclassified')}. "
            f"Justification: {analysis.get('structured_audit_justification', override_reason)}. "
            f"Monitoring: {'; '.join(analysis.get('suggested_monitoring', []))}."
        )

        resource = build_audit_event(patient_id, action="E", description=description)
        created = await fhir.create("AuditEvent", resource)

        return json.dumps({
            "status": "created",
            "resource_type": "AuditEvent",
            "id": created.get("id"),
            "override_logged": True,
            "message": f"Override permanently logged as AuditEvent/{created.get('id')}",
        }, indent=2)

    except Exception as e:
        logger.error(f"log_override failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "override_log_failed",
            "error_type": type(e).__name__,
            "message": str(e),
            "hint": "Check server logs for full traceback. Governance record was NOT persisted.",
        }, indent=2)
