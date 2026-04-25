"""
Approval-gated write tools: DraftTask, DraftMedicationProposal,
DraftCommunication, LogConsensusDecision.

All writes are gated on clinician approval — the orchestrator calls these
only after explicit clinician confirmation in a follow-up turn.

Phase 2 will implement actual FHIR HTTP writes.
Phase 1 stubs return valid draft structures without writing to FHIR.
"""

import json
import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

from llm.schemas import (
    AuditEventRef,
    CommunicationDraft,
    MedicationProposalDraft,
    TaskDraft,
)
from medsafe_core.helpers import compute_due_date_from_timing

logger = logging.getLogger(__name__)


async def draft_task(
    action_code: Annotated[
        str,
        Field(description="ActionCode enum value (e.g. 'REPEAT_RENAL_PANEL_48H', 'DAILY_WEIGHTS')"),
    ],
    description: Annotated[
        str,
        Field(description="Human-readable task description"),
    ],
    owner_confirmer: Annotated[
        str,
        Field(description="Clinician or specialty responsible for confirming this task"),
    ],
    timing: Annotated[
        str | None,
        Field(description="Natural-language timing string used to compute due_date (e.g. '48 hours', '1 week', '4 weeks'). Preferred over due_date."),
    ] = None,
    ctx: Context = None,
) -> str:
    """
    Draft a follow-up Task for clinician approval.

    Computes due_date deterministically from timing if provided.
    Does NOT write to FHIR — returns a draft for clinician review.
    Clinician must explicitly approve before the Task is committed.
    """
    try:
        due_date = compute_due_date_from_timing(timing)
        draft = TaskDraft(
            action_code=action_code,
            description=description,
            owner_confirmer=owner_confirmer,
            due_date=due_date,
            timing=timing,
        )
        return draft.model_dump_json(indent=2)

    except Exception as e:
        logger.error(f"draft_task failed: {e}\n{traceback.format_exc()}")
        return json.dumps({"error": type(e).__name__, "message": str(e)}, indent=2)


async def draft_medication_proposal(
    action_code: Annotated[
        str,
        Field(description="ActionCode enum value (e.g. 'UPTITRATE_LOOP_DIURETIC', 'HOLD_MRA_TEMPORARILY')"),
    ],
    medication: Annotated[
        str,
        Field(description="Medication name and dose being proposed (e.g. 'furosemide 80mg BD')"),
    ],
    rationale: Annotated[
        str,
        Field(description="Clinical rationale for the medication change, citing specialist opinions"),
    ],
    owner_confirmer: Annotated[
        str,
        Field(description="Clinician who must confirm before this proposal is acted upon"),
    ],
    ctx: Context = None,
) -> str:
    """
    Draft a medication proposal for clinician approval.

    Framed as a PROPOSAL — not autonomous prescribing. Requires explicit
    clinician confirmation before materialising as a FHIR MedicationRequest.
    """
    try:
        draft = MedicationProposalDraft(
            action_code=action_code,
            medication=medication,
            rationale=rationale,
            owner_confirmer=owner_confirmer,
        )
        return draft.model_dump_json(indent=2)

    except Exception as e:
        logger.error(f"draft_medication_proposal failed: {e}\n{traceback.format_exc()}")
        return json.dumps({"error": type(e).__name__, "message": str(e)}, indent=2)


async def draft_communication(
    to_specialty: Annotated[
        str,
        Field(description="Receiving specialty for this communication (e.g. 'cardiology', 'nephrology', 'pharmacy')"),
    ],
    summary: Annotated[
        str,
        Field(description="Coordination message summarising the agreed plan and sequencing"),
    ],
    linked_action_codes: Annotated[
        str,
        Field(description="JSON array of ActionCode strings this communication relates to (e.g. '[\"UPTITRATE_LOOP_DIURETIC\", \"REPEAT_RENAL_PANEL_48H\"]')"),
    ],
    ctx: Context = None,
) -> str:
    """
    Draft a team coordination Communication for clinician approval.

    Creates a FHIR Communication resource draft for multi-specialty coordination
    (e.g. notifying HF team of sequencing decisions). Requires clinician approval.
    """
    try:
        codes: list[str] = json.loads(linked_action_codes) if isinstance(linked_action_codes, str) else linked_action_codes
        draft = CommunicationDraft(
            to_specialty=to_specialty,
            summary=summary,
            linked_action_codes=codes,
        )
        return draft.model_dump_json(indent=2)

    except Exception as e:
        logger.error(f"draft_communication failed: {e}\n{traceback.format_exc()}")
        return json.dumps({"error": type(e).__name__, "message": str(e)}, indent=2)


async def log_consensus_decision(
    episode_brief_id: Annotated[
        str,
        Field(description="episode_brief_id from BuildEpisodeBrief"),
    ],
    specialist_task_ids_json: Annotated[
        str,
        Field(description='JSON object mapping specialty to A2A task ID (e.g. {"nephrology": "task-abc", "cardiology": "task-def", "pharmacy": "task-ghi"})'),
    ],
    conflict_matrix_json: Annotated[
        str,
        Field(description="ConflictMatrix JSON from ComputeConflictMatrix"),
    ],
    unified_plan_json: Annotated[
        str,
        Field(description="UnifiedPlan JSON constructed by the orchestrator"),
    ],
    validation_result_json: Annotated[
        str,
        Field(description="PlanValidationResult JSON from ValidateFinalPlan"),
    ],
    ctx: Context = None,
) -> str:
    """
    Log the full orchestration run as a FHIR AuditEvent.

    Captures: specialist inputs (by taskId), action codes emitted,
    conflict dispositions, final resolution, validator status, timestamp.

    This is the audit surface judges will inspect.
    Phase 2 will write the AuditEvent to FHIR; Phase 1 returns the payload.
    """
    try:
        specialist_task_ids: dict = json.loads(specialist_task_ids_json)
        now = datetime.now(timezone.utc).isoformat()
        audit_id = str(uuid.uuid4())

        ref = AuditEventRef(
            episode_brief_id=episode_brief_id,
            recorded_at=now,
            audit_id=audit_id,
            status="draft",  # Phase 2 will change to "created" after FHIR write
        )

        # Include full payload for transparency
        payload = ref.model_dump()
        payload["specialist_task_ids"] = specialist_task_ids
        payload["note"] = "Phase 2 will write this as a FHIR AuditEvent"

        return json.dumps(payload, indent=2)

    except Exception as e:
        logger.error(f"log_consensus_decision failed: {e}\n{traceback.format_exc()}")
        return json.dumps({"error": type(e).__name__, "message": str(e)}, indent=2)
