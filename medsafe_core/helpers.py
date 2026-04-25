"""
Shared deterministic helpers used across MCP tools.

Currently houses:
  - Date/timing parsing (FHIR Task scheduling)
  - Patient-medication class aggregation (used by multiple safety-rule tools)

Deterministic server-side helpers that prevent the common failure mode
where an LLM fabricates a past date because its training cutoff is
older than the current date — and avoid duplicated logic across tool
modules.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_TIMING_PATTERN = re.compile(
    r"(?:in\s+|at\s+|after\s+)?(\d+)\s*(day|days|week|weeks|month|months|year|years)",
    re.IGNORECASE,
)


def compute_due_date_from_timing(timing: str | None) -> str | None:
    """
    Parse a natural-language timing string and compute an ISO date relative to now.

    Accepts strings like "6 weeks", "3 months", "in 1 week", "at 6 weeks",
    "2 weeks from now". Returns YYYY-MM-DD or None if unparseable.

    Computed server-side from datetime.now() — never depends on LLM's sense of "today".
    """
    if not timing:
        return None
    match = _TIMING_PATTERN.search(timing)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()

    now = datetime.now(tz=timezone.utc)
    if unit.startswith("day"):
        delta = timedelta(days=amount)
    elif unit.startswith("week"):
        delta = timedelta(weeks=amount)
    elif unit.startswith("month"):
        delta = timedelta(days=amount * 30)
    elif unit.startswith("year"):
        delta = timedelta(days=amount * 365)
    else:
        return None
    return (now + delta).strftime("%Y-%m-%d")


def coerce_due_date(due_date: str | None, timing: str | None) -> str | None:
    """
    Return a safe due_date for a FHIR Task.

    Priority:
      1. If `timing` is parseable, use it — deterministic, source-of-truth.
      2. Else if `due_date` parses AND is in the future, use it.
      3. Else None.

    Prevents past-date fabrication from LLM training-era date assumptions.
    """
    computed = compute_due_date_from_timing(timing)
    if computed:
        return computed

    if due_date:
        try:
            parsed = datetime.strptime(due_date, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(f"Ignoring malformed due_date: {due_date!r}")
            return None
        today = datetime.now(tz=timezone.utc).date()
        if parsed < today:
            logger.warning(
                f"LLM provided past due_date ({due_date}); coercing to None. "
                f"Agent should pass a `timing` string instead."
            )
            return None
        return due_date

    return None


def collect_patient_classes(profile: dict[str, Any]) -> dict[str, list[str]]:
    """Build a map from drug_class to list of medication names from the profile.

    Falls back to the dm+d normalizer to enrich classes if the profile entry
    didn't include them. Used by every drug-class-gated rule tool (Beers,
    STOPP/START, etc.) — single source of truth so any normalisation-rule
    change propagates uniformly.
    """
    # Local import to avoid a circular import at module load time
    # (medsafe_core.rules.normalizer also imports from helpers indirectly).
    from medsafe_core.rules.normalizer import normalize_medication

    class_to_meds: dict[str, list[str]] = {}
    for med in profile.get("active_medications", []) or []:
        name = med.get("name", "")
        classes = list(med.get("classes") or [])
        if not classes:
            normalized = normalize_medication(name)
            if normalized.resolved:
                classes = list(normalized.drug_classes)
        for cls in classes:
            class_to_meds.setdefault(cls, []).append(name)
    return class_to_meds
