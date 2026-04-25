"""
QueryAuditEvent tool — read-mode counterpart to LogOverride.

Used by SignalLoop Scenario 4 (audit interrogation): the clinician asks
"why did we override X for patient Y last month?" and the agent surfaces
the original AuditEvent payload with verdict, override rationale, and
citation context.

This is a SEPARATE tool from LogOverride (which writes) to avoid the
"verb-y boolean default" anti-pattern flagged in the user's memory feedback
file (LLMs pass True on optional bools with verb-y names).
"""

from __future__ import annotations

import json
import logging
import traceback
from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import Field

from medsafe_core.fhir.client import FhirClient
from medsafe_core.fhir.context import extract_fhir_context, extract_patient_id

logger = logging.getLogger(__name__)


def _summarise_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    """Pull the most salient fields out of a FHIR AuditEvent into a flat dict
    the agent can render in chat.

    Description-resolution order matches what `LogOverride` actually writes
    (via `medsafe_core.fhir.resource_builders.build_audit_event`):
      1. `outcomeDesc` (canonical primary path — this is what LogOverride writes)
      2. Any `extension[].valueString` whose `url` ends with "description"
         (kept as forward-compat for future writers that use extensions)
      3. Empty string.
    """
    description = event.get("outcomeDesc") or ""
    if not description:
        for ext in event.get("extension", []):
            if ext.get("url", "").endswith("description"):
                description = ext.get("valueString", "")
                break

    when = (
        event.get("recorded")
        or event.get("period", {}).get("start")
        or "unknown"
    )

    action = event.get("action", "")  # E = execute, R = read, etc.

    agent_names: list[str] = []
    for agent in event.get("agent", []):
        nm = agent.get("name") or agent.get("who", {}).get("display")
        if nm:
            agent_names.append(nm)

    return {
        "id": event.get("id"),
        "recorded_at": when,
        "action": action,
        "agents": agent_names,
        "description": description,
        "outcome": event.get("outcome"),
        # Note: full FHIR payload deliberately NOT inlined to keep responses
        # compact for the chat UI. Agent can re-fetch by id if needed.
    }


async def query_audit_event(
    since: Annotated[
        str,
        Field(
            description=(
                "ISO-8601 date or datetime — only events recorded on or after "
                "this point are returned. Empty string = no lower bound."
            )
        ),
    ] = "",
    drug_filter: Annotated[
        str,
        Field(
            description=(
                "Case-insensitive substring to filter by medication name (matched "
                "against the audit description). Empty string = no filter."
            )
        ),
    ] = "",
    limit: Annotated[
        int,
        Field(
            description="Maximum number of audit events to return (1-50).",
            ge=1, le=50,
        ),
    ] = 10,
    ctx: Context = None,
) -> str:
    """
    Query FHIR AuditEvents for the active patient.

    Returns a chronologically-sorted (newest first) list of summarised audit
    events. Use to replay clinical decisions for compliance review, override
    interrogation ("why did we approve X for this patient last month?"), or
    handover briefings.

    READ-ONLY. Does not modify any FHIR resources.
    """
    try:
        fhir_ctx = extract_fhir_context(ctx)
        patient_id = extract_patient_id(ctx)
        fhir = FhirClient(fhir_ctx)

        params: dict[str, str] = {
            "patient": patient_id,
            "_sort": "-date",
            "_count": str(limit),
        }
        if since.strip():
            # FHIR supports 'date=ge2024-01-01'
            params["date"] = f"ge{since.strip()}"

        events = await fhir.search("AuditEvent", params)

        # Optional client-side filter on description text — FHIR's text search
        # is uneven across servers, so do this after retrieval.
        filter_term = drug_filter.strip().lower()
        if filter_term:
            filtered: list[dict[str, Any]] = []
            for ev in events:
                summary = _summarise_audit_event(ev)
                if filter_term in (summary.get("description") or "").lower():
                    filtered.append(ev)
            events = filtered

        summaries = [_summarise_audit_event(ev) for ev in events[:limit]]

        return json.dumps({
            "patient_id": patient_id,
            "since": since or None,
            "drug_filter": drug_filter or None,
            "count": len(summaries),
            "events": summaries,
        }, indent=2, default=str)

    except Exception as e:
        logger.error(f"query_audit_event failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
            "hint": "Confirm FHIR context is bound and AuditEvent search is supported by the server.",
        }, indent=2)
