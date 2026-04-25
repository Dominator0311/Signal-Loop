"""
SuggestAlternative tool — LLM-driven safer-alternatives recommender.

Phase-3-style: this tool reasons FROM the contraindication context, not
against a rules engine. The deterministic rules have already said the
original drug is unsafe; we use Gemini structured generation to suggest
3-5 safer alternatives with rationale, dosing and monitoring.

This tool NEVER calls the rules engine — separation of concerns.
"""

import json
import logging
import traceback
from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import Field

from medsafe_core.llm.client import get_gemini_client
from medsafe_core.llm.prompts.suggest_alternative import (
    SYSTEM_INSTRUCTION,
    build_suggest_alternative_prompt,
)
from medsafe_core.llm.schemas import AlternativeList

logger = logging.getLogger(__name__)


async def suggest_alternative(
    drug_name: Annotated[
        str,
        Field(description="The contraindicated medication, e.g. 'ibuprofen 400mg'"),
    ],
    contraindication_reason: Annotated[
        str,
        Field(
            description=(
                "Free-text explanation of WHY the drug is contraindicated. "
                "Include patient-specific context where possible, e.g. "
                "'eGFR 41, NICE NG203 §1.3.2 — avoid NSAIDs below eGFR 60'."
            )
        ),
    ],
    patient_risk_profile_json: Annotated[
        str,
        Field(
            description=(
                "Optional JSON string of the patient risk profile from "
                "BuildPatientRiskProfile. Pass empty string '' if not available."
            )
        ),
    ] = "",
    ctx: Context = None,
) -> str:
    """
    Suggest 3-5 safer alternatives to a contraindicated medication.

    LLM-driven (Gemini structured output). Returns ranked alternatives with:
      - drug_class
      - rationale (why it's safer for THIS patient)
      - typical_starting_dose
      - monitoring
      - cautions

    Use after CheckMedicationSafety returns BLOCK or WARN_OVERRIDE_REQUIRED to
    give the clinician an actionable next step.
    """
    try:
        profile_data: dict[str, Any] | None = None
        if patient_risk_profile_json and patient_risk_profile_json.strip():
            try:
                parsed = json.loads(patient_risk_profile_json)
                if isinstance(parsed, dict) and not parsed.get("error"):
                    profile_data = parsed
            except json.JSONDecodeError:
                logger.warning("suggest_alternative: profile JSON unparseable, ignoring")

        prompt = build_suggest_alternative_prompt(
            drug_name=drug_name,
            contraindication_reason=contraindication_reason,
            profile_data=profile_data,
        )

        gemini = get_gemini_client()
        response = await gemini.generate_structured(
            prompt=prompt,
            output_model=AlternativeList,
            system_instruction=SYSTEM_INSTRUCTION,
        )

        # Force the original_drug / contraindication_reason fields to match
        # the inputs even if the LLM tries to summarise them.
        result = response.model_dump()
        result["original_drug"] = drug_name
        result["contraindication_reason"] = contraindication_reason

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"suggest_alternative failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)
