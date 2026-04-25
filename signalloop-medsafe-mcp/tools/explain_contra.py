"""
ExplainContraindication tool — LLM-driven plain-English explanation of a
SafetyVerdict for both clinician and patient audiences.

Phase-3-style. The verdict is taken as ground truth; the LLM only
rephrases and contextualises.
"""

import json
import logging
import traceback
from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import Field

from medsafe_core.llm.client import get_gemini_client
from medsafe_core.llm.prompts.explain_contra import (
    SYSTEM_INSTRUCTION,
    build_explain_contra_prompt,
)
from medsafe_core.llm.schemas import ContraindicationExplanation

logger = logging.getLogger(__name__)


async def explain_contraindication(
    verdict_json: Annotated[
        str,
        Field(description="JSON string of the SafetyVerdict from CheckMedicationSafety"),
    ],
    patient_risk_profile_json: Annotated[
        str,
        Field(
            description=(
                "Optional JSON string of the patient risk profile. Pass empty "
                "string '' if not available."
            )
        ),
    ] = "",
    ctx: Context = None,
) -> str:
    """
    Produce paired clinician + patient-friendly explanations of a safety verdict.

    LLM-driven. Returns:
      - clinical_explanation (prescriber-facing, 3-5 sentences)
      - patient_friendly_explanation (plain English, <30s read)
      - key_risks (bullet list)
      - next_steps (bullet list)

    Use after CheckMedicationSafety to translate flags into language the
    clinician can paste into the consultation, and that the patient can
    actually understand.
    """
    try:
        try:
            verdict = json.loads(verdict_json)
        except json.JSONDecodeError as e:
            return json.dumps({
                "error": "invalid_verdict_json",
                "message": str(e),
            }, indent=2)

        if isinstance(verdict, dict) and verdict.get("error"):
            return json.dumps({
                "error": "upstream_verdict_error",
                "message": verdict.get("message", "Verdict input contained an error"),
            }, indent=2)

        profile_data: dict[str, Any] | None = None
        if patient_risk_profile_json and patient_risk_profile_json.strip():
            try:
                parsed = json.loads(patient_risk_profile_json)
                if isinstance(parsed, dict) and not parsed.get("error"):
                    profile_data = parsed
            except json.JSONDecodeError:
                logger.warning("explain_contraindication: profile JSON unparseable, ignoring")

        prompt = build_explain_contra_prompt(verdict_data=verdict, profile_data=profile_data)
        gemini = get_gemini_client()
        response = await gemini.generate_structured(
            prompt=prompt,
            output_model=ContraindicationExplanation,
            system_instruction=SYSTEM_INSTRUCTION,
        )

        return json.dumps(response.model_dump(), indent=2)

    except Exception as e:
        logger.error(f"explain_contraindication failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)
