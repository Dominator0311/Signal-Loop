"""
CheckRenalDoseAdjustment tool — drug-specific renally-adjusted dose lookup.

DETERMINISTIC. NO LLM. Pure JSON lookup keyed by canonical drug name.
For each drug we hold an ordered list of eGFR bands; the tool returns the
band whose [egfr_min, egfr_max] interval contains the patient's eGFR.

This is a thin orchestration layer — the rule data lives in
medsafe_core/rules/data/renal_dose_adjustments.json. The lookup itself is
pure Python and covered by unit tests.
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


@lru_cache(maxsize=1)
def _load_renal_table() -> dict[str, Any]:
    """Load the renal dose adjustment table once per process."""
    path = Path(__file__).resolve().parents[2] / "medsafe_core" / "rules" / "data" / "renal_dose_adjustments.json"
    with open(path) as f:
        return json.load(f)


def _select_band(bands: list[dict[str, Any]], egfr: float) -> dict[str, Any] | None:
    """
    Select the band whose interval contains the eGFR.

    Bands are stored with optional egfr_max (None == open upper bound).
    A band matches when egfr_min <= eGFR <= egfr_max (or egfr_min <= eGFR
    when egfr_max is None).
    """
    for band in bands:
        lower = band.get("egfr_min", 0)
        upper = band.get("egfr_max")
        if egfr < lower:
            continue
        if upper is None or egfr <= upper:
            return band
    return None


def _resolve_drug_key(raw_text: str, table: dict[str, Any]) -> str | None:
    """Find the canonical key in the renal table for the given input."""
    cleaned = raw_text.lower().strip()
    drugs = table["drugs"]

    if cleaned in drugs:
        return cleaned

    # Try the medication normalizer for synonym/brand resolution
    normalized = _normalize(raw_text)
    if normalized.resolved and normalized.canonical_name:
        canonical = normalized.canonical_name.lower().strip()
        if canonical in drugs:
            return canonical

    # Last attempt: substring of any known drug
    for key in drugs:
        if key in cleaned or cleaned in key:
            return key
    return None


async def check_renal_dose_adjustment(
    drug_name: Annotated[
        str,
        Field(description="Drug name to check (free text, e.g. 'metformin', 'gabapentin 300mg', 'apixaban')"),
    ],
    egfr: Annotated[
        float,
        Field(description="Patient eGFR in mL/min/1.73m^2. Must be >= 0."),
    ],
    ctx: Context = None,
) -> str:
    """
    Look up the BNF-renally-adjusted dose for a drug at the given eGFR.

    Pure JSON lookup — no LLM. Returns:
      - canonical_drug, drug_class, default_dose
      - applicable band (egfr_min, egfr_max, adjustment, severity)
      - citation (BNF / NICE source)
      - clinical_review_status field (values: "summarised_from_named_source", "verbatim_verified")

    If the drug is not in the renal-adjustment table the tool returns a
    structured 'unknown_drug' response listing available drugs — never
    silently fabricates a dose.
    """
    try:
        if egfr is None or egfr < 0:
            return json.dumps({
                "error": "invalid_egfr",
                "message": f"eGFR must be a non-negative number, got {egfr!r}.",
            }, indent=2)

        table = _load_renal_table()
        drug_key = _resolve_drug_key(drug_name, table)

        if drug_key is None:
            return json.dumps({
                "drug_input": drug_name,
                "resolved": False,
                "egfr": egfr,
                "message": (
                    "Drug not in MedSafe renal dose adjustment table. The table "
                    "covers 25 commonly renally-adjusted UK medications; for drugs "
                    "outside this set consult BNF Appendix 3 directly."
                ),
                "covered_drugs": sorted(table["drugs"].keys()),
            }, indent=2)

        entry = table["drugs"][drug_key]
        band = _select_band(entry["bands"], egfr)

        result: dict[str, Any] = {
            "drug_input": drug_name,
            "resolved": True,
            "canonical_drug": drug_key,
            "drug_class": entry.get("drug_class"),
            "indication": entry.get("indication"),
            "default_dose_normal_renal_function": entry.get("default_dose"),
            "egfr": egfr,
        }

        if band is None:
            result["adjustment"] = None
            result["message"] = (
                f"No band matched eGFR {egfr} — table coverage gap. Consult BNF directly."
            )
        else:
            result.update({
                "egfr_band": {
                    "egfr_min": band.get("egfr_min"),
                    "egfr_max": band.get("egfr_max"),
                },
                "adjustment": band.get("adjustment"),
                "severity": band.get("severity"),
                "citation": band.get("citation_source"),
                "clinical_review_status": band.get("clinical_review_status", "summarised_from_named_source"),
            })

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"check_renal_dose_adjustment failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)
