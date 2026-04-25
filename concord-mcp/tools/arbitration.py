"""
Arbitration tools: ComputeConflictMatrix, ValidateFinalPlan.

Both tools are deterministic — no LLM.
Phase 2 will implement full classification and validation logic.
"""

import json
import logging
import traceback
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

from llm.schemas import ConflictMatrix, PlanValidationResult, SpecialistOpinion, UnifiedPlan
from rules.conflict_matrix import compute_conflict_matrix as _compute
from rules.plan_validator import validate_final_plan as _validate

logger = logging.getLogger(__name__)


async def compute_conflict_matrix(
    nephrology_opinion_json: Annotated[
        str,
        Field(description="SpecialistOpinion JSON returned by concord-nephrology worker"),
    ],
    cardiology_opinion_json: Annotated[
        str,
        Field(description="SpecialistOpinion JSON returned by concord-cardiology worker"),
    ],
    pharmacy_opinion_json: Annotated[
        str,
        Field(description="SpecialistOpinion JSON returned by concord-pharmacy worker"),
    ],
    episode_brief_id: Annotated[
        str,
        Field(description="episode_brief_id from BuildEpisodeBrief — used for audit linkage"),
    ],
    ctx: Context = None,
) -> str:
    """
    Classify three specialist opinions into the Concord ConflictMatrix taxonomy.

    Pure Python, no LLM. Groups recommendations by action_code, then classifies
    each group as: consensus / tension / direct_conflict / dependency /
    missing_data_block / safety_block.

    Returns a ConflictMatrix with ranked_next_actions (safety_blocks first,
    then consensus, then resolved tensions).
    """
    try:
        opinions: list[SpecialistOpinion] = []
        for label, raw in [
            ("nephrology", nephrology_opinion_json),
            ("cardiology", cardiology_opinion_json),
            ("pharmacy", pharmacy_opinion_json),
        ]:
            try:
                opinions.append(SpecialistOpinion.model_validate_json(raw))
            except Exception as e:
                return json.dumps({
                    "error": "invalid_specialist_opinion",
                    "specialty": label,
                    "message": f"Could not parse {label} opinion: {e}",
                    "hint": "Ensure the worker returned a valid SpecialistOpinion JSON.",
                }, indent=2)

        matrix = _compute(opinions, episode_brief_id)
        return matrix.model_dump_json(indent=2)

    except Exception as e:
        logger.error(f"compute_conflict_matrix failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)


async def validate_final_plan(
    unified_plan_json: Annotated[
        str,
        Field(description="UnifiedPlan JSON constructed by the orchestrator after ComputeConflictMatrix"),
    ],
    conflict_matrix_json: Annotated[
        str,
        Field(description="ConflictMatrix JSON returned by ComputeConflictMatrix"),
    ],
    ctx: Context = None,
) -> str:
    """
    Run deterministic validation checks (V01–V10) on the proposed unified plan.

    No LLM. Every check has a name, condition, and blocking/warning classification.
    Only status 'pass' or 'pass_with_warnings' permits write-back.
    Status 'fail' must be surfaced to the clinician — do not attempt writes.
    """
    try:
        plan = UnifiedPlan.model_validate_json(unified_plan_json)
        matrix = ConflictMatrix.model_validate_json(conflict_matrix_json)
        result = _validate(plan, matrix)
        return result.model_dump_json(indent=2)

    except Exception as e:
        logger.error(f"validate_final_plan failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)
