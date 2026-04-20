"""
MCP server instance with FHIR context extension and tool registration.

This module:
1. Creates the FastMCP server instance
2. Declares the ai.promptopinion/fhir-context extension with SMART scopes
3. Registers all MedSafe tools (Phase 1, 2, 3 + referral + writes)

Tool naming follows Prompt Opinion conventions: PascalCase names,
clear descriptions that tell the LLM agent WHEN to call each tool.
"""

from mcp.server.fastmcp import FastMCP

# Import all tool functions
from tools.phase1 import build_patient_risk_profile, get_renal_trend, get_relevant_context
from tools.phase2 import normalize_medication, check_medication_safety
from tools.phase3 import synthesise_safety_response, analyse_override_reason
from tools.referral import (
    assemble_specialty_packet,
    rank_specialist_destinations,
    extract_consult_recommendations,
    detect_plan_conflicts,
)
from tools.writes import (
    draft_medication_request,
    draft_service_request,
    draft_followup_task,
    log_override,
)


# Create MCP server
mcp = FastMCP("SignalLoop MedSafe", stateless_http=True, host="0.0.0.0")


# --- Extension declaration ---
# Declare FHIR context requirement with SMART scopes.
# This tells Prompt Opinion to send SHARP headers on every tool call.

_original_get_capabilities = mcp._mcp_server.get_capabilities


def _patched_get_capabilities(notification_options, experimental_capabilities):
    caps = _original_get_capabilities(notification_options, experimental_capabilities)
    caps.model_extra["extensions"] = {
        "ai.promptopinion/fhir-context": {
            "scopes": [
                {"name": "patient/Patient.rs", "required": True},
                {"name": "patient/Condition.rs", "required": True},
                {"name": "patient/MedicationRequest.rs", "required": True},
                {"name": "patient/Observation.rs", "required": True},
                {"name": "patient/AllergyIntolerance.rs", "required": True},
                {"name": "patient/DocumentReference.rs"},
                {"name": "patient/Encounter.rs"},
                {"name": "patient/ServiceRequest.cud"},
                {"name": "patient/Task.cud"},
                {"name": "patient/Communication.cud"},
                {"name": "patient/AuditEvent.cud"},
                {"name": "patient/MedicationRequest.cud"},
            ],
        }
    }
    return caps


mcp._mcp_server.get_capabilities = _patched_get_capabilities


# --- Tool registration ---
# Phase 1: Patient Risk Profile Building (LLM)
mcp.tool(
    name="BuildPatientRiskProfile",
    description=(
        "Build a structured patient risk profile for medication safety evaluation. "
        "Call this FIRST when a patient session starts. The profile is used by "
        "CheckMedicationSafety to parameterise safety rules."
    ),
)(build_patient_risk_profile)

mcp.tool(
    name="GetRenalTrend",
    description=(
        "Get renal function trend data (eGFR or creatinine) as structured output. "
        "Returns longitudinal values with trajectory and rate of change. "
        "Use to assess whether renal function is stable, declining, or improving."
    ),
)(get_renal_trend)

mcp.tool(
    name="GetRelevantContext",
    description=(
        "Get the subset of patient context relevant to a specific clinical signal. "
        "Use when interpreting a new lab result or clinical finding to understand "
        "which chart facts matter for interpretation."
    ),
)(get_relevant_context)

# Phase 1/2: Medication Normalization
mcp.tool(
    name="NormalizeMedication",
    description=(
        "Normalize a free-text medication string to a canonical dm+d code. "
        "Use before CheckMedicationSafety to resolve drug names to codes."
    ),
)(normalize_medication)

# Phase 2: Deterministic Safety Check (Rules — NO LLM)
mcp.tool(
    name="CheckMedicationSafety",
    description=(
        "DETERMINISTIC medication safety check. Pure rules, no AI. "
        "Evaluates a proposed medication against the patient risk profile. "
        "Call this EVERY TIME a medication is proposed. Pass the patient risk "
        "profile JSON from BuildPatientRiskProfile. "
        "Returns: BLOCK (contraindicated), WARN (override required), or CLEAN."
    ),
)(check_medication_safety)

# Phase 3: Response Synthesis (LLM)
mcp.tool(
    name="SynthesiseSafetyResponse",
    description=(
        "Generate patient-specific safety narrative from a MedSafe verdict. "
        "Call this AFTER CheckMedicationSafety when flags were raised. "
        "Produces personalised alternatives with trade-offs and monitoring plans."
    ),
)(synthesise_safety_response)

mcp.tool(
    name="AnalyseOverrideReason",
    description=(
        "Analyse a clinician's override reason for a safety alert. "
        "Call when the clinician chooses to proceed despite a MedSafe warning. "
        "Classifies the reason, assesses validity, and suggests monitoring."
    ),
)(analyse_override_reason)

# FHIR Write Tools
mcp.tool(
    name="DraftMedicationRequest",
    description=(
        "Create a FHIR MedicationRequest after clinician approval. "
        "Only call AFTER CheckMedicationSafety returns CLEAN or after documented override."
    ),
)(draft_medication_request)

mcp.tool(
    name="DraftServiceRequest",
    description=(
        "Create a FHIR ServiceRequest for a specialist referral. "
        "Call after clinician approves the referral and reviews the packet."
    ),
)(draft_service_request)

mcp.tool(
    name="DraftFollowupTask",
    description=(
        "Create a FHIR Task for follow-up work (e.g., 'Repeat eGFR in 2 weeks'). "
        "Use for monitoring tasks, lab rechecks, and appointment reminders."
    ),
)(draft_followup_task)

mcp.tool(
    name="LogOverride",
    description=(
        "Log a MedSafe override as a permanent FHIR AuditEvent. "
        "Call after AnalyseOverrideReason when a clinician overrides a safety alert. "
        "Creates a permanent, queryable audit record."
    ),
)(log_override)

# Referral Sub-System
mcp.tool(
    name="AssembleSpecialtyPacket",
    description=(
        "Assemble a specialty-specific referral packet with missing-context flags. "
        "Different specialties need different inputs. Call when a referral is being "
        "considered — shows what's available and what's missing before sending."
    ),
)(assemble_specialty_packet)

mcp.tool(
    name="RankSpecialistDestinations",
    description=(
        "Rank specialist destinations for a referral by fit, wait time, distance, "
        "and other factors. Call after the referral packet is assembled."
    ),
)(rank_specialist_destinations)

mcp.tool(
    name="ExtractConsultRecommendations",
    description=(
        "Extract structured recommendations from a returned specialist consult note. "
        "Call when a DocumentReference arrives from a specialist. Parses free text "
        "into actionable recommendation objects."
    ),
)(extract_consult_recommendations)

mcp.tool(
    name="DetectPlanConflicts",
    description=(
        "Detect conflicts between specialist recommendations and current care plan. "
        "Call after ExtractConsultRecommendations. Identifies where incoming "
        "recommendations conflict with ongoing management."
    ),
)(detect_plan_conflicts)
