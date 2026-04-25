"""
CheckBeersCriteria tool — AGS Beers 2023 PIM screen for adults aged 65+.

DETERMINISTIC. NO LLM. Class-level evaluation against the curated top-10
Beers categories in medsafe_core/rules/data/beers_2023.json.
"""

import json
import logging
import traceback
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import Field

from medsafe_core.rules.normalizer import normalize_medication as _normalize

logger = logging.getLogger(__name__)


_CITATION = (
    "American Geriatrics Society 2023 updated AGS Beers Criteria for Potentially "
    "Inappropriate Medication Use in Older Adults. J Am Geriatr Soc. 2023;71(7):2052-2081."
)


@lru_cache(maxsize=1)
def _load_beers() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "medsafe_core" / "rules" / "data" / "beers_2023.json"
    with open(path) as f:
        return json.load(f)


# Imported lazily — see medsafe_core.helpers.collect_patient_classes — to keep
# the tool's surface tight and ensure beers + stopp_start share one impl.
from medsafe_core.helpers import collect_patient_classes as _collect_patient_classes  # noqa: E402


async def check_beers_criteria(
    patient_risk_profile_json: Annotated[
        str,
        Field(description="JSON string of the patient risk profile from BuildPatientRiskProfile"),
    ],
    ctx: Context = None,
) -> str:
    """
    Screen the patient's active medications against AGS Beers 2023 PIM list.

    DETERMINISTIC. NO LLM. Returns:
      - beers_findings: list of categories triggered, each with rationale,
        recommendation, quality_of_evidence, and citation.
      - For patients under 65 returns 'not_applicable'.
    """
    try:
        try:
            profile = json.loads(patient_risk_profile_json)
        except json.JSONDecodeError as e:
            return json.dumps({
                "error": "invalid_profile_json",
                "message": str(e),
            }, indent=2)

        if isinstance(profile, dict) and profile.get("error"):
            return json.dumps({
                "error": "upstream_profile_error",
                "message": profile.get("message", "BuildPatientRiskProfile returned an error"),
            }, indent=2)

        age = profile.get("age")
        if age is None or age < 65:
            return json.dumps({
                "applicable": False,
                "message": (
                    f"AGS Beers Criteria are validated for adults aged 65+. "
                    f"Patient age={age!r}."
                ),
                "beers_findings": [],
            }, indent=2)

        table = _load_beers()
        patient_classes = _collect_patient_classes(profile)

        findings: list[dict[str, Any]] = []
        for category in table.get("categories", []):
            cat_classes = category.get("drug_classes") or []
            matching_meds: list[str] = []
            for cls in cat_classes:
                for med_name in patient_classes.get(cls, []):
                    if med_name not in matching_meds:
                        matching_meds.append(med_name)
            if not matching_meds:
                continue
            findings.append({
                "id": category["id"],
                "category": category["category"],
                "matched_medications": matching_meds,
                "rationale": category.get("rationale"),
                "recommendation": category.get("recommendation"),
                "quality_of_evidence": category.get("quality_of_evidence"),
                "strength_of_recommendation": category.get("strength_of_recommendation"),
                "citation": _CITATION,
                "clinical_review_status": category.get("clinical_review_status", "summarised_from_named_source"),
            })

        return json.dumps({
            "applicable": True,
            "patient_age": age,
            "beers_findings": findings,
            "summary": {"finding_count": len(findings)},
            "citation": _CITATION,
        }, indent=2)

    except Exception as e:
        logger.error(f"check_beers_criteria failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)
