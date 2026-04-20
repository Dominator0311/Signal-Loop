"""
Phase 3 MCP tools: Response Synthesis and Override Analysis.

LLM-driven tools that turn deterministic verdicts into patient-specific,
clinically-actionable output. This is where AI earns its value over
flat rules engines.
"""

import json
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

from llm.client import get_gemini_client
from llm.prompts.safety_synthesis import SYSTEM_INSTRUCTION as SYNTHESIS_SYSTEM, build_synthesis_prompt
from llm.prompts.override_analysis import SYSTEM_INSTRUCTION as OVERRIDE_SYSTEM, build_override_analysis_prompt
from llm.schemas import LLMSafetyResponse, LLMOverrideAnalysis


async def synthesise_safety_response(
    verdict_json: Annotated[
        str,
        Field(description="JSON string of the safety verdict from check_medication_safety")
    ],
    patient_risk_profile_json: Annotated[
        str,
        Field(description="JSON string of the patient risk profile from build_patient_risk_profile")
    ],
    ctx: Context = None,
) -> str:
    """
    Synthesise a patient-specific safety response (MedSafe Phase 3).

    Takes the deterministic verdict from Phase 2 and the patient risk profile
    from Phase 1, and produces:
    - Patient-specific narrative explaining why the flags matter for THIS patient
    - Personalised alternative recommendations with trade-offs
    - Monitoring protocol if clinician chooses to override

    This is substantive generative AI work: it turns a flat verdict into
    clinically-actionable, patient-specific prose that a rules engine
    fundamentally cannot produce.
    """
    verdict_data = json.loads(verdict_json)
    profile_data = json.loads(patient_risk_profile_json)

    prompt = build_synthesis_prompt(verdict_data, profile_data)
    gemini = get_gemini_client()

    response = await gemini.generate_structured(
        prompt=prompt,
        output_model=LLMSafetyResponse,
        system_instruction=SYNTHESIS_SYSTEM,
    )

    return json.dumps(response.model_dump(), indent=2)


async def analyse_override_reason(
    override_reason: Annotated[
        str,
        Field(description="The clinician's free-text reason for overriding the safety alert")
    ],
    verdict_json: Annotated[
        str,
        Field(description="JSON string of the safety verdict that was overridden")
    ],
    patient_risk_profile_json: Annotated[
        str,
        Field(description="JSON string of the patient risk profile")
    ],
    ctx: Context = None,
) -> str:
    """
    Analyse a clinician's override reason for a MedSafe safety alert.

    When a clinician overrides a safety block, this tool analyses the free-text
    reason and produces:
    - Classification (specialist recommendation, short course, emergency, etc.)
    - Clinical validity assessment
    - Suggested monitoring to mitigate remaining risk
    - Structured justification for permanent audit records

    This is substantive AI value — a traditional override just captures free text.
    This analyses it, classifies it, and suggests mitigating actions.
    """
    verdict_data = json.loads(verdict_json)
    profile_data = json.loads(patient_risk_profile_json)

    prompt = build_override_analysis_prompt(override_reason, verdict_data, profile_data)
    gemini = get_gemini_client()

    response = await gemini.generate_structured(
        prompt=prompt,
        output_model=LLMOverrideAnalysis,
        system_instruction=OVERRIDE_SYSTEM,
    )

    return json.dumps(response.model_dump(), indent=2)
