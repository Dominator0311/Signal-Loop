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
from tools.phase1 import (
    build_patient_risk_profile,
    get_renal_trend,
    get_relevant_context,
)
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
from tools.renal_dose import check_renal_dose_adjustment
from tools.stopp_start import check_stopp_start
from tools.beers import check_beers_criteria
from tools.ddi import check_drug_drug_interaction
from tools.suggest_alternative import suggest_alternative
from tools.explain_contra import explain_contraindication
from tools.full_review import run_full_medication_review
from tools.surveillance import surface_patient_attention
from tools.audit_query import query_audit_event


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
        "Create a FHIR Task for follow-up work (e.g., 'Repeat eGFR'). "
        "Use for monitoring tasks, lab rechecks, and appointment reminders. "
        "IMPORTANT: to schedule, pass a `timing` string like '6 weeks' or "
        "'3 months' — the tool computes the real date from today. Do NOT pass "
        "due_date unless you're sure it's a future date."
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

# UK Safe-Prescribing Foundation: deterministic clinical-rule tools (no LLM).
mcp.tool(
    name="CheckRenalDoseAdjustment",
    description=(
        "Look up the BNF-renally-adjusted dose for a drug at the patient's eGFR. "
        "Pure JSON lookup, no LLM. Covers ~25 commonly renally-adjusted UK "
        "medications (metformin, gabapentin, atenolol, digoxin, allopurinol, "
        "ramipril, lisinopril, gentamicin, vancomycin, dabigatran, apixaban, "
        "rivaroxaban, edoxaban, enoxaparin, morphine, tramadol, codeine, "
        "lithium, metoclopramide, ranitidine, ciprofloxacin, trimethoprim, "
        "nitrofurantoin, spironolactone, dapagliflozin, sitagliptin, pregabalin). "
        "Returns the applicable eGFR band, adjustment text, severity and BNF citation."
    ),
)(check_renal_dose_adjustment)

mcp.tool(
    name="CheckSTOPPSTART",
    description=(
        "Apply STOPP/START v2 criteria (O'Mahony et al., Age and Ageing 2015) to "
        "a patient aged 65+. Returns potentially inappropriate prescriptions "
        "(STOPP) and potential prescribing omissions (START) with verbatim "
        "criterion text and citation. Pass the patient risk profile JSON from "
        "BuildPatientRiskProfile."
    ),
)(check_stopp_start)

mcp.tool(
    name="CheckBeersCriteria",
    description=(
        "Screen the patient's active medications against AGS Beers Criteria 2023 "
        "(JAGS 2023;71(7):2052-2081). For adults aged 65+. Returns potentially "
        "inappropriate medications across the top 10 categories (anticholinergics, "
        "benzodiazepines, NSAIDs, antipsychotics, TCAs, sulfonylureas, PPIs, "
        "muscle relaxants, Z-drugs, digoxin) with rationale and recommendation."
    ),
)(check_beers_criteria)

mcp.tool(
    name="CheckDrugDrugInteraction",
    description=(
        "Pairwise drug-drug interaction screen against the curated BNF Appendix 1 "
        "subset (~50 high-clinical-significance interactions). Pass a JSON array "
        "of medication names. Returns interactions with severity (severe/moderate/"
        "mild), mechanism, recommended action and BNF citation. Use to screen a "
        "current med list, or to check a proposed new drug against current meds."
    ),
)(check_drug_drug_interaction)

# Decision-support LLM tools (Phase-3 style: reason FROM verdicts, not against them).
mcp.tool(
    name="SuggestAlternative",
    description=(
        "Given a contraindicated medication and the reason it was flagged unsafe, "
        "suggest 3-5 safer alternatives. LLM-driven structured output: each "
        "alternative includes drug class, rationale specific to this patient, "
        "BNF starting dose, monitoring plan and residual cautions. Use after "
        "CheckMedicationSafety returns BLOCK or WARN_OVERRIDE_REQUIRED."
    ),
)(suggest_alternative)

mcp.tool(
    name="ExplainContraindication",
    description=(
        "Translate a SafetyVerdict into paired clinical + patient-friendly "
        "explanations. LLM-driven. Returns: clinical_explanation (3-5 sentences "
        "for the prescriber), patient_friendly_explanation (plain English, <30s "
        "read), key_risks and next_steps. Never softens or contradicts the "
        "deterministic verdict — only rephrases."
    ),
)(explain_contraindication)

mcp.tool(
    name="RunFullMedicationReview",
    description=(
        "Composite end-to-end medication review for the current patient. "
        "Builds the risk profile, runs deterministic safety checks on every "
        "active medication, screens for drug-drug interactions, and applies "
        "STOPP/START + Beers where age applicable. Returns a compact markdown "
        "report (<5KB) ranked by severity. Use as the entry-point tool for a "
        "comprehensive prescribing review."
    ),
)(run_full_medication_review)

mcp.tool(
    name="SurfacePatientAttention",
    description=(
        "Surface what needs the clinician's attention for the active patient. "
        "Composite tool: runs the patient profile, renal trend, full medication "
        "review, and consult discovery in parallel, returns a deterministically "
        "ranked list of 1-5 attention items with clinical reasoning and citations. "
        "Use when the clinician asks an open-ended question like "
        "'what needs my attention?' or 'brief me on this patient' with no "
        "specific drug or task in scope."
    ),
)(surface_patient_attention)

mcp.tool(
    name="QueryAuditEvent",
    description=(
        "READ-ONLY query of FHIR AuditEvents for the active patient. Returns "
        "chronologically-sorted (newest first) audit events optionally filtered "
        "by date range or medication-name substring. Use to replay clinical "
        "decisions (e.g. 'why did we override the eGFR block on naproxen for "
        "this patient last month?'), compliance review, or handover briefings. "
        "Counterpart to LogOverride which writes audit events."
    ),
)(query_audit_event)
