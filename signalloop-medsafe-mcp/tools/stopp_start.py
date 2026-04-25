"""
CheckSTOPPSTART tool — STOPP/START v2 criteria evaluation for older adults (>=65).

DETERMINISTIC. NO LLM. Evaluates a patient profile + medication list against
the curated subset of STOPP/START v2 criteria stored in
medsafe_core/rules/data/stopp_start_v2.json.

Inputs:
  - patient_risk_profile_json (from BuildPatientRiskProfile)
  - additional medication list optional — if omitted we use the active
    medications already on the profile.

Outputs:
  - List of STOPP findings (potentially inappropriate prescriptions)
  - List of START findings (potential prescribing omissions)
  - Each finding includes severity, criterion text, citation, and
    clinical_review_status field.
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
    "O'Mahony D et al. STOPP/START criteria for potentially inappropriate "
    "prescribing in older people: version 2. Age and Ageing 2015;44(2):213-218."
)


@lru_cache(maxsize=1)
def _load_stopp_start() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "medsafe_core" / "rules" / "data" / "stopp_start_v2.json"
    with open(path) as f:
        return json.load(f)


from medsafe_core.helpers import collect_patient_classes as _collect_patient_classes  # noqa: E402


def _criterion_drug_classes_match(
    criterion_classes: list[str], patient_classes: dict[str, list[str]]
) -> list[str]:
    """Return the patient medications that match any of the criterion classes."""
    matches: list[str] = []
    for cls in criterion_classes:
        for med_name in patient_classes.get(cls, []):
            if med_name not in matches:
                matches.append(med_name)
    return matches


def _evaluate_stopp(
    profile: dict[str, Any], patient_classes: dict[str, list[str]]
) -> list[dict[str, Any]]:
    """Run each STOPP criterion against the profile.

    Logic is intentionally conservative: a criterion fires when the relevant
    drug class is present AND, where applicable, the matching context flag
    is set on the profile. Criteria that depend on data we cannot reliably
    extract (e.g. duration recorded, indication recorded) only fire when an
    explicit clinical_context_flag is present.
    """
    table = _load_stopp_start()
    flags = profile.get("clinical_context_flags", []) or []
    flags_lower = {str(f).lower() for f in flags}
    egfr = (profile.get("renal_function") or {}).get("latest_egfr")

    findings: list[dict[str, Any]] = []
    for crit in table.get("stopp_criteria", []):
        crit_classes = crit.get("drug_classes") or []
        context_flag = crit.get("context_flag")
        egfr_threshold = crit.get("egfr_threshold")
        trigger = crit.get("trigger", "")

        matching_meds = _criterion_drug_classes_match(crit_classes, patient_classes) if crit_classes else []

        # If criterion specifies a class but no matching medications, skip.
        if crit_classes and not matching_meds:
            continue

        # eGFR-gated criteria (E section): only fire if eGFR known and below threshold
        if egfr_threshold is not None:
            if egfr is None or egfr >= egfr_threshold:
                continue

        # Context-flag-gated criteria
        if context_flag is not None:
            if context_flag.lower() not in flags_lower:
                continue

        # Duplicate-class criterion needs >=2 meds in the same class
        if trigger == "duplicate_class":
            duplicates = [
                cls for cls in crit_classes if len(patient_classes.get(cls, [])) >= 2
            ]
            if not duplicates:
                continue
            matching_meds = []
            for cls in duplicates:
                matching_meds.extend(patient_classes.get(cls, []))

        # Criteria with no class and no context flag we cannot evaluate
        # deterministically — skip silently.
        if not crit_classes and not context_flag:
            continue

        # Many STOPP criteria require duration- or indication-context that
        # can't be reliably inferred from structured FHIR data (e.g. STOPP-D5
        # needs ">=4 weeks of benzodiazepine use"). When such context is not
        # explicitly verified via context_flag/egfr_threshold/trigger, flag
        # the finding as advisory (severity 'info') with a caveat so the
        # clinician knows we have not confirmed the firing precondition.
        gating_resolved = bool(context_flag) or egfr_threshold is not None or trigger == "duplicate_class"
        requires_clinical_context = bool(crit.get("requires_duration") or crit.get("requires_indication"))

        finding: dict[str, Any] = {
            "id": crit["id"],
            "section": crit.get("section"),
            "criterion": crit.get("criterion"),
            "matched_medications": matching_meds,
            "severity": crit.get("severity", "moderate"),
            "citation": _CITATION,
            "clinical_review_status": crit.get("clinical_review_status", "summarised_from_named_source"),
        }
        if requires_clinical_context and not gating_resolved:
            finding["severity"] = "info"
            finding["applicable_caveat"] = (
                "Duration- or indication-based gate could not be verified from "
                "structured data. Surfaced as an advisory prompt; clinician must "
                "confirm before treating as a STOPP violation."
            )
        findings.append(finding)

    return findings


def _evaluate_start(
    profile: dict[str, Any], patient_classes: dict[str, list[str]]
) -> list[dict[str, Any]]:
    """
    START criteria fire when an indication flag is present on the profile but
    none of the expected drug classes is in the active medication list.
    """
    table = _load_stopp_start()
    flags = profile.get("clinical_context_flags", []) or []
    flags_lower = {str(f).lower() for f in flags}

    findings: list[dict[str, Any]] = []
    for crit in table.get("start_criteria", []):
        indication = crit.get("indication_flag")
        expected = crit.get("expected_drug_classes") or []

        if indication is None or indication.lower() not in flags_lower:
            continue

        if any(cls in patient_classes for cls in expected):
            continue

        findings.append({
            "id": crit["id"],
            "section": crit.get("section"),
            "criterion": crit.get("criterion"),
            "indication_flag": indication,
            "expected_drug_classes": expected,
            "severity": crit.get("severity", "moderate"),
            "citation": _CITATION,
            "clinical_review_status": crit.get("clinical_review_status", "summarised_from_named_source"),
        })

    return findings


async def check_stopp_start(
    patient_risk_profile_json: Annotated[
        str,
        Field(description="JSON string of the patient risk profile from BuildPatientRiskProfile"),
    ],
    ctx: Context = None,
) -> str:
    """
    Evaluate STOPP/START v2 criteria against a patient (age >=65).

    DETERMINISTIC. NO LLM. Returns two lists:
      - stopp_findings: potentially inappropriate prescriptions
      - start_findings: potential prescribing omissions

    Each finding cites STOPP/START v2 (O'Mahony et al., Age and Ageing 2015).

    For patients under 65 the tool short-circuits with a 'not_applicable'
    response — STOPP/START is validated only for older adults.
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
                    f"STOPP/START v2 criteria are validated only for adults aged 65+. "
                    f"Patient age={age!r}."
                ),
                "stopp_findings": [],
                "start_findings": [],
            }, indent=2)

        patient_classes = _collect_patient_classes(profile)
        stopp = _evaluate_stopp(profile, patient_classes)
        start = _evaluate_start(profile, patient_classes)

        return json.dumps({
            "applicable": True,
            "patient_age": age,
            "stopp_findings": stopp,
            "start_findings": start,
            "summary": {
                "stopp_count": len(stopp),
                "start_count": len(start),
            },
            "citation": _CITATION,
        }, indent=2)

    except Exception as e:
        logger.error(f"check_stopp_start failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)
