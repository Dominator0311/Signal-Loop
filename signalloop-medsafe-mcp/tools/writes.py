"""
FHIR write tools: Create clinical resources in the workspace FHIR server.

All writes require prior clinician approval (enforced at the agent level,
not here — tools execute what they're told, governance lives in the agent
system prompt).

Each tool constructs a valid FHIR resource and POSTs it to the server,
returning the created resource with its server-assigned ID.
"""

import json
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

from fhir.context import extract_fhir_context, extract_patient_id
from fhir.client import FhirClient
from fhir.resource_builders import (
    build_medication_request,
    build_service_request,
    build_task,
    build_communication,
    build_audit_event,
)


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
    description: Annotated[str, Field(description="Task description (e.g., 'Repeat eGFR in 2 weeks')")],
    due_date: Annotated[str | None, Field(description="Due date in ISO format (e.g., '2026-05-04')")] = None,
    priority: Annotated[str, Field(description="Priority: routine, urgent, asap, stat")] = "routine",
    ctx: Context = None,
) -> str:
    """
    Create a FHIR Task for follow-up work (e.g., repeat labs, monitoring).
    """
    fhir_ctx = extract_fhir_context(ctx)
    patient_id = extract_patient_id(ctx)
    fhir = FhirClient(fhir_ctx)

    resource = build_task(patient_id, description, due_date, priority)
    created = await fhir.create("Task", resource)

    return json.dumps({
        "status": "created",
        "resource_type": "Task",
        "id": created.get("id"),
        "description": description,
        "due_date": due_date,
        "message": f"Task created: '{description}'. Resource ID: {created.get('id')}",
    }, indent=2)


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
    This record is permanent and queryable.
    """
    fhir_ctx = extract_fhir_context(ctx)
    patient_id = extract_patient_id(ctx)
    fhir = FhirClient(fhir_ctx)

    analysis = json.loads(override_analysis_json)
    verdict = json.loads(original_verdict_json)

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
