"""
FHIR R4 resource builders for write operations.

Each builder constructs a valid FHIR resource dict ready for POST/PUT
to the workspace FHIR server. Resources follow R4 spec structure.

Design: Pure functions that take domain data and return FHIR JSON dicts.
No I/O, no side effects — just data transformation.
"""

from datetime import datetime, timezone


def build_medication_request(
    patient_id: str,
    medication_name: str,
    medication_code: str,
    dose_text: str,
    reason: str,
) -> dict:
    """Build a FHIR MedicationRequest resource."""
    return {
        "resourceType": "MedicationRequest",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "https://dmd.nhs.uk",
                    "code": medication_code,
                    "display": medication_name,
                }
            ],
            "text": medication_name,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "authoredOn": _now_iso(),
        "dosageInstruction": [{"text": dose_text}],
        "note": [{"text": f"Prescribed via SignalLoop MedSafe. Reason: {reason}"}],
    }


def build_service_request(
    patient_id: str,
    specialty: str,
    reason: str,
    urgency: str = "routine",
    note: str = "",
) -> dict:
    """Build a FHIR ServiceRequest for a specialist referral."""
    priority_map = {"urgent": "urgent", "routine": "routine", "asap": "asap"}
    return {
        "resourceType": "ServiceRequest",
        "status": "active",
        "intent": "order",
        "priority": priority_map.get(urgency, "routine"),
        "category": [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "3457005",
                        "display": "Patient referral",
                    }
                ]
            }
        ],
        "code": {
            "text": f"Referral to {specialty}",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "authoredOn": _now_iso(),
        "reasonCode": [{"text": reason}],
        "note": [{"text": note}] if note else [],
    }


def build_task(
    patient_id: str,
    description: str,
    due_date: str | None = None,
    priority: str = "routine",
) -> dict:
    """Build a FHIR Task for follow-up work."""
    task = {
        "resourceType": "Task",
        "status": "requested",
        "intent": "order",
        "priority": priority,
        "description": description,
        "for": {"reference": f"Patient/{patient_id}"},
        "authoredOn": _now_iso(),
    }
    if due_date:
        task["restriction"] = {"period": {"end": due_date}}
    return task


def build_communication(
    patient_id: str,
    message_text: str,
    channel: str = "sms",
) -> dict:
    """Build a FHIR Communication resource for patient outreach (drafted, not sent)."""
    return {
        "resourceType": "Communication",
        "status": "preparation",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/communication-category",
                        "code": "notification",
                        "display": "Notification",
                    }
                ]
            }
        ],
        "medium": [{"text": channel}],
        "subject": {"reference": f"Patient/{patient_id}"},
        "sent": _now_iso(),
        "payload": [{"contentString": message_text}],
        "note": [{"text": "Drafted by SignalLoop. Requires clinician approval before delivery."}],
    }


def build_audit_event(
    patient_id: str,
    action: str,
    description: str,
    outcome: str = "0",
    agent_name: str = "SignalLoop MedSafe",
) -> dict:
    """
    Build a FHIR R4 AuditEvent for governance logging.

    Used for: override events, consequential actions, safety gate decisions.

    Outcome codes: 0=success, 4=minor failure, 8=serious failure, 12=major failure.

    FHIR R4 required fields (enforced by HAPI):
      - type (CodeableConcept)
      - recorded (instant)
      - agent[].requestor (boolean)
      - source.observer (Reference) — REQUIRED, was missing in earlier version
    """
    return {
        "resourceType": "AuditEvent",
        "type": {
            "system": "http://dicom.nema.org/resources/ontology/DCM",
            "code": "110100",
            "display": "Application Activity",
        },
        "action": action,
        "recorded": _now_iso(),
        "outcome": outcome,
        "outcomeDesc": description,
        "agent": [
            {
                "type": {
                    "coding": [
                        {
                            "system": "http://dicom.nema.org/resources/ontology/DCM",
                            "code": "110153",
                            "display": "Source Role ID",
                        }
                    ]
                },
                "who": {"display": agent_name},
                "requestor": False,
            }
        ],
        "source": {
            "observer": {
                "display": agent_name,
            },
            "type": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/security-source-type",
                    "code": "4",
                    "display": "Application Server",
                }
            ],
        },
        "entity": [
            {
                "what": {"reference": f"Patient/{patient_id}"},
                "role": {
                    "system": "http://terminology.hl7.org/CodeSystem/object-role",
                    "code": "1",
                    "display": "Patient",
                },
            }
        ],
    }


def _now_iso() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()
