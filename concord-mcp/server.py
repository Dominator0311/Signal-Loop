"""
Concord MCP server instance with FHIR context extension and tool registration.

Registers Concord tools:
  Context:      BuildEpisodeBrief, GetTrendSummary
  Shared:       NormalizeMedication, CheckMedicationSafety
  Arbitration:  ComputeConflictMatrix, ValidateFinalPlan
  Writes:       DraftTask, DraftMedicationProposal, DraftCommunication,
                LogConsensusDecision
  All-in-one:   RunCardioRenalConsult  (server-side orchestration of all of the above)
"""

from mcp.server.fastmcp import FastMCP

from tools.episode import build_episode_brief, get_trend_summary
from tools.shared import normalize_medication, check_medication_safety
from tools.arbitration import compute_conflict_matrix, validate_final_plan
from tools.run_consult import run_cardio_renal_consult
from tools.writes import (
    draft_task,
    draft_medication_proposal,
    draft_communication,
    log_consensus_decision,
)


mcp = FastMCP("Concord", stateless_http=True, host="0.0.0.0")


# --- FHIR context extension (same SHARP header pattern as SignalLoop) ---

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

# Context tools
mcp.tool(
    name="BuildEpisodeBrief",
    description=(
        "Build a structured shared case packet from the patient's FHIR record. "
        "Call this FIRST on any new clinical question. All specialist workers "
        "reason from the returned EpisodeBrief. Returns episode_brief_id (UUID) "
        "used for audit linkage throughout the session."
    ),
)(build_episode_brief)

mcp.tool(
    name="GetTrendSummary",
    description=(
        "Get longitudinal trend summaries for selected patient metrics. "
        "Valid metrics: 'egfr', 'creatinine', 'potassium', 'weight', 'bnp'. "
        "Returns trajectory (stable/rising/declining), rate of change, and data points. "
        "Workers may call this to confirm trends before forming their recommendation."
    ),
)(get_trend_summary)

# Shared tools (same logic as SignalLoop MedSafe)
mcp.tool(
    name="NormalizeMedication",
    description=(
        "Normalize a free-text medication string to a canonical dm+d code. "
        "Use before CheckMedicationSafety to resolve drug names to codes."
    ),
)(normalize_medication)

mcp.tool(
    name="CheckMedicationSafety",
    description=(
        "DETERMINISTIC medication safety check. Pure rules, no AI. "
        "Evaluates a proposed medication against the patient risk profile. "
        "Returns: BLOCK (contraindicated), WARN (override required), or CLEAN. "
        "Workers may call this when flagging drug-specific safety concerns."
    ),
)(check_medication_safety)

# Arbitration tools (deterministic, no LLM)
mcp.tool(
    name="ComputeConflictMatrix",
    description=(
        "Classify three specialist opinions into the Concord ConflictMatrix taxonomy. "
        "Pure Python, no LLM. Groups recommendations by action_code and classifies "
        "each as: consensus / tension / direct_conflict / dependency / "
        "missing_data_block / safety_block. "
        "Call AFTER receiving all three specialist opinions."
    ),
)(compute_conflict_matrix)

mcp.tool(
    name="ValidateFinalPlan",
    description=(
        "Run deterministic validation checks (V01–V10) on the proposed unified plan. "
        "No LLM. Status 'fail' means do NOT proceed to writes — surface blocking issues "
        "to the clinician. Only 'pass' or 'pass_with_warnings' permit write-back."
    ),
)(validate_final_plan)

# Write tools (approval-gated)
mcp.tool(
    name="DraftTask",
    description=(
        "Draft a follow-up Task for clinician approval. "
        "Use for monitoring tasks, lab rechecks, and scheduled reviews. "
        "Pass a timing string like '48 hours' or '4 weeks' — tool computes real due_date. "
        "Call ONLY after clinician approval of the unified plan."
    ),
)(draft_task)

mcp.tool(
    name="DraftMedicationProposal",
    description=(
        "Draft a medication change proposal for clinician approval. "
        "Framed as a PROPOSAL — not autonomous prescribing. Requires explicit clinician "
        "confirmation before materialising as a FHIR MedicationRequest. "
        "Call ONLY after clinician approval of the unified plan."
    ),
)(draft_medication_proposal)

mcp.tool(
    name="DraftCommunication",
    description=(
        "Draft a team coordination Communication for clinician approval. "
        "Used to notify a specialty team about sequencing decisions "
        "(e.g. 'Inform HF team: diuretic up-titration deferred 48h for renal monitoring'). "
        "Call ONLY after clinician approval of the unified plan."
    ),
)(draft_communication)

# All-in-one orchestration (server-side, bypasses platform A2A UI bug)
mcp.tool(
    name="RunCardioRenalConsult",
    description=(
        "Run the full Concord cardio-renal consultation in a single tool call. "
        "Server-side orchestration: builds the episode brief, fetches trend data, "
        "consults nephrology / cardiology / pharmacy specialists in parallel, "
        "classifies conflicts via the deterministic rules engine, builds and "
        "validates a unified plan, drafts Task / MedicationRequest / Communication "
        "writes, and logs an AuditEvent. "
        "Returns clinician-facing markdown with per-specialist views, agreed and "
        "pending actions, validation status, and a JSON audit appendix. "
        "Use this as the SINGLE entry point for any cardio-renal coordination question."
    ),
)(run_cardio_renal_consult)


mcp.tool(
    name="LogConsensusDecision",
    description=(
        "Log the full orchestration run as a FHIR AuditEvent. "
        "Captures: specialist inputs, action codes, conflict dispositions, "
        "final resolution, validator status, timestamp. "
        "Call as the LAST step after all approved writes are drafted."
    ),
)(log_consensus_decision)
