"""
CheckDrugDrugInteraction tool — pairwise DDI lookup against the curated BNF
Appendix 1 subset stored in medsafe_core/rules/data/ddi_pairs.json.

DETERMINISTIC. NO LLM. Two calling modes:

  1) Two-drug check: pass medications=["drug A", "drug B"] — returns the
     interaction (if any) for that exact pair.
  2) Bulk screen: pass medications=[...] with 2+ entries — returns every
     pair-wise interaction found across the list.
  3) New-drug-vs-current-meds: pass `proposed_drug` plus `current_medications`
     — convenience for the CheckMedicationSafety pipeline.

Each interaction returns severity, mechanism, action, and citation.
"""

import json
import logging
import traceback
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import Field

from medsafe_core.rules.normalizer import normalize_medication as _normalize

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_ddi_table() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "medsafe_core" / "rules" / "data" / "ddi_pairs.json"
    with open(path) as f:
        return json.load(f)


def _resolve_drug(raw: str) -> dict[str, Any]:
    """Return {raw, canonical, classes} for a drug name, even if unresolved."""
    normalized = _normalize(raw)
    return {
        "raw": raw,
        "canonical": normalized.canonical_name if normalized.resolved else None,
        "classes": list(normalized.drug_classes) if normalized.resolved else [],
        "resolved": normalized.resolved,
    }


def _matches_side(side: dict[str, Any], drug: dict[str, Any]) -> bool:
    """Check if a drug matches one side of a DDI pair definition.

    Side can specify either 'class' (must be in drug.classes) or
    'specific' (must equal canonical name).
    """
    specific = side.get("specific")
    if specific:
        canonical = (drug.get("canonical") or "").lower()
        raw = (drug.get("raw") or "").lower()
        if specific.lower() == canonical or specific.lower() in raw:
            return True
    klass = side.get("class")
    if klass and klass in drug.get("classes", []):
        # If the side restricts to specific drugs in that class, enforce it.
        restrict = side.get("specific_drugs_in_a") or side.get("specific_drugs_in_b")
        if restrict:
            canonical = (drug.get("canonical") or "").lower()
            raw = (drug.get("raw") or "").lower()
            if not any(s.lower() == canonical or s.lower() in raw for s in restrict):
                return False
        return True
    return False


def _all_classes_present(required: list[str], all_drug_classes: set[str]) -> bool:
    """Check that EVERY required class (or class-alternative) appears in the drug list.

    A required entry like 'ACE_INHIBITOR|ARB' means ANY of those classes counts.
    A required entry like 'NSAID' means exactly that class must be present.
    """
    for req in required:
        alternatives = req.split("|")
        if not any(alt in all_drug_classes for alt in alternatives):
            return False
    return True


def _find_interaction(
    drug_x: dict[str, Any],
    drug_y: dict[str, Any],
    all_drug_classes: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return all interactions where {x,y} matches a pair definition.

    If a pair has `requires_all_classes`, the rule only fires when every named
    class is present in the FULL active medication list (passed as
    `all_drug_classes`). This is how the triple-whammy rule (NSAID + diuretic +
    ACE-I/ARB) avoids firing on just NSAID + diuretic.
    """
    table = _load_ddi_table()
    hits: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for pair in table.get("pairs", []):
        a = pair.get("drug_a", {})
        b = pair.get("drug_b", {})
        pair_match = (
            (_matches_side(a, drug_x) and _matches_side(b, drug_y))
            or (_matches_side(a, drug_y) and _matches_side(b, drug_x))
        )
        if not pair_match or pair["id"] in seen_ids:
            continue

        # Honour requires_all_classes — pair fires only when EVERY required class
        # (or class-alternative group) is on the full active list.
        required = pair.get("requires_all_classes")
        if required:
            if all_drug_classes is None or not _all_classes_present(required, all_drug_classes):
                continue

        seen_ids.add(pair["id"])
        hits.append({
            "id": pair["id"],
            "drugs_involved": [drug_x.get("canonical") or drug_x["raw"], drug_y.get("canonical") or drug_y["raw"]],
            "severity": pair.get("severity"),
            "mechanism": pair.get("mechanism"),
            "action": pair.get("action"),
            "citation": pair.get("citation"),
            "clinical_review_status": pair.get("clinical_review_status", "summarised_from_named_source"),
        })
    return hits


async def check_drug_drug_interaction(
    medications_json: Annotated[
        str,
        Field(
            description=(
                "JSON array of medication name strings to screen for interactions, "
                "e.g. '[\"warfarin\", \"clarithromycin\"]'. Pass 2 to check a "
                "specific pair, or N>=2 to screen every pair in the list."
            )
        ),
    ],
    ctx: Context = None,
) -> str:
    """
    Pairwise drug-drug interaction screen against the curated BNF Appendix 1
    subset (~50 high-clinical-significance pairs).

    DETERMINISTIC. NO LLM. Returns a list of interactions found, each with
    severity (severe/moderate/mild), mechanism, recommended action, and
    BNF citation.
    """
    try:
        try:
            meds = json.loads(medications_json)
        except json.JSONDecodeError as e:
            return json.dumps({
                "error": "invalid_medications_json",
                "message": (
                    f"medications_json must be a JSON array of strings. {e}"
                ),
            }, indent=2)

        if not isinstance(meds, list) or len(meds) < 2:
            return json.dumps({
                "error": "need_at_least_two_drugs",
                "message": "Provide at least two medications to screen for interactions.",
            }, indent=2)

        resolved = [_resolve_drug(str(m)) for m in meds]
        unresolved = [r["raw"] for r in resolved if not r["resolved"]]

        # Aggregate every drug class on the active list — needed for rules
        # tagged `requires_all_classes` (e.g. triple-whammy NSAID+diuretic+ACEI).
        all_drug_classes: set[str] = set()
        for r in resolved:
            all_drug_classes.update(r.get("classes", []) or [])

        interactions: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for x, y in combinations(resolved, 2):
            for hit in _find_interaction(x, y, all_drug_classes=all_drug_classes):
                if hit["id"] not in seen_ids:
                    seen_ids.add(hit["id"])
                    interactions.append(hit)

        # Sort by severity for downstream usability
        order = {"severe": 0, "moderate": 1, "mild": 2}
        interactions.sort(key=lambda i: order.get(i.get("severity"), 99))

        return json.dumps({
            "input_medications": [r["raw"] for r in resolved],
            "resolved_canonicals": [r.get("canonical") for r in resolved],
            "unresolved_inputs": unresolved,
            "interactions": interactions,
            "summary": {
                "interaction_count": len(interactions),
                "severe_count": sum(1 for i in interactions if i.get("severity") == "severe"),
                "moderate_count": sum(1 for i in interactions if i.get("severity") == "moderate"),
            },
        }, indent=2)

    except Exception as e:
        logger.error(f"check_drug_drug_interaction failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)
