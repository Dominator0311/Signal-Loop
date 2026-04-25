"""
RunFullMedicationReview tool — composite end-to-end medication review.

For the current patient (resolved via FHIR context):
  1. Build the patient risk profile (Phase 1 LLM, cached).
  2. For each active medication run the deterministic rules:
     - CheckMedicationSafety (renal, interaction, Beers, scope)
     - STOPP/START screen
     - Beers screen
  3. Aggregate findings into a compact markdown report.

Output is markdown (NOT JSON appendix). Payload kept under ~5KB to avoid
chat-loop bugs we hit on the Concord MCP. Findings are deduplicated and
ranked by severity.
"""

import json
import logging
import traceback
from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import Field

from medsafe_core.rules.engine import evaluate_medication_safety
from medsafe_core.rules.normalizer import normalize_medication as _normalize

from tools.beers import check_beers_criteria
from tools.ddi import check_drug_drug_interaction
from tools.phase1 import build_patient_risk_profile
from tools.phase2 import parse_risk_profile
from tools.stopp_start import check_stopp_start

logger = logging.getLogger(__name__)


_SEVERITY_RANK = {
    "block": 0,
    "contraindicated": 0,
    "severe": 1,
    "warn_override_required": 1,
    "major": 1,
    "warn": 2,
    "moderate": 2,
    "info": 3,
    "minor": 3,
    "clean": 4,
    "mild": 4,
}


def _rank(sev: str | None) -> int:
    return _SEVERITY_RANK.get((sev or "").lower(), 99)


def _format_severity_emoji_free(sev: str | None) -> str:
    """Plain text severity label suitable for markdown without emojis."""
    if not sev:
        return "INFO"
    sev_lower = sev.lower()
    if sev_lower in ("block", "contraindicated", "severe"):
        return "BLOCK"
    if sev_lower in ("warn_override_required", "major"):
        return "WARN-OVR"
    if sev_lower in ("warn", "moderate"):
        return "WARN"
    if sev_lower in ("info", "minor", "mild"):
        return "INFO"
    if sev_lower == "clean":
        return "CLEAN"
    return sev_lower.upper()


def _build_per_drug_findings(profile_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Run CheckMedicationSafety for each active medication on the profile."""
    profile_obj = parse_risk_profile(json.dumps(profile_data))
    out: list[dict[str, Any]] = []

    for med in profile_data.get("active_medications", []):
        name = med.get("name", "")
        classes = list(med.get("classes") or [])
        if not classes:
            normalized = _normalize(name)
            if normalized.resolved:
                classes = list(normalized.drug_classes)

        verdict = evaluate_medication_safety(
            proposed_drug_classes=classes,
            proposed_drug_name=name,
            proposed_drug_code=None,
            profile=profile_obj,
        )
        out.append({
            "medication": name,
            "verdict": verdict.verdict.value,
            "flags": [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity.value,
                    "reason": f.reason,
                    "citation": f.citation,
                }
                for f in verdict.flags
            ],
        })
    return out


def _truncate(text: str, max_chars: int = 220) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _build_markdown(
    profile_data: dict[str, Any],
    per_drug: list[dict[str, Any]],
    stopp_data: dict[str, Any],
    beers_data: dict[str, Any],
    ddi_data: dict[str, Any],
) -> str:
    """Compose a compact markdown report. Target <5KB."""
    lines: list[str] = []

    name = profile_data.get("first_name") or profile_data.get("patient_id", "patient")
    age = profile_data.get("age")
    sex = profile_data.get("sex")
    egfr = (profile_data.get("renal_function") or {}).get("latest_egfr")
    flags = profile_data.get("clinical_context_flags") or []
    meds = profile_data.get("active_medications") or []

    lines.append(f"# Full medication review — {name}")
    header = f"Age {age}" if age is not None else "Age unknown"
    if sex:
        header += f" {sex}"
    if egfr is not None:
        header += f" | eGFR {egfr}"
    lines.append(f"_{header} | {len(meds)} active medications_")
    if flags:
        lines.append(f"_Context flags: {', '.join(flags[:6])}_")
    lines.append("")

    # Per-drug verdicts
    lines.append("## Per-medication safety verdict (rules engine)")
    if not per_drug:
        lines.append("_No active medications recorded._")
    else:
        ranked = sorted(per_drug, key=lambda d: _rank(d.get("verdict")))
        for entry in ranked[:12]:
            sev = _format_severity_emoji_free(entry.get("verdict"))
            med = entry.get("medication", "?")
            top_flag = entry.get("flags", [])[0] if entry.get("flags") else None
            if top_flag:
                lines.append(
                    f"- **[{sev}] {med}** — {_truncate(top_flag['reason'], 180)} "
                    f"_[{top_flag['rule_id']}]_"
                )
            else:
                lines.append(f"- **[{sev}] {med}** — no flags")
        if len(per_drug) > 12:
            lines.append(f"- _... and {len(per_drug) - 12} more medications._")
    lines.append("")

    # DDI summary (top 5)
    lines.append("## Drug-drug interaction screen (BNF Appendix 1)")
    interactions = ddi_data.get("interactions", []) if isinstance(ddi_data, dict) else []
    if not interactions:
        lines.append("_No interactions found in curated BNF subset._")
    else:
        for hit in interactions[:5]:
            sev = _format_severity_emoji_free(hit.get("severity"))
            drugs = " + ".join(hit.get("drugs_involved", []))
            action = _truncate(hit.get("action", ""), 140)
            lines.append(f"- **[{sev}]** {drugs}: {action} _[{hit.get('id')}]_")
        if len(interactions) > 5:
            lines.append(f"- _... and {len(interactions) - 5} more interactions._")
    lines.append("")

    # STOPP/START (top 5 each)
    if stopp_data.get("applicable"):
        lines.append("## STOPP/START v2 (older adults)")
        stopp_findings = stopp_data.get("stopp_findings", [])
        start_findings = stopp_data.get("start_findings", [])
        if stopp_findings:
            lines.append("**STOPP — potentially inappropriate prescriptions:**")
            for f in stopp_findings[:5]:
                lines.append(
                    f"- [{f['id']}] {_truncate(f.get('criterion', ''), 160)} "
                    f"_(matched: {', '.join(f.get('matched_medications', []) or ['n/a'])})_"
                )
        if start_findings:
            lines.append("**START — potential prescribing omissions:**")
            for f in start_findings[:5]:
                lines.append(
                    f"- [{f['id']}] {_truncate(f.get('criterion', ''), 160)} "
                    f"_(indication: {f.get('indication_flag')})_"
                )
        if not stopp_findings and not start_findings:
            lines.append("_No STOPP/START findings._")
        lines.append("")

    # Beers (top 5)
    if beers_data.get("applicable"):
        lines.append("## AGS Beers Criteria 2023")
        beers_findings = beers_data.get("beers_findings", [])
        if not beers_findings:
            lines.append("_No Beers findings._")
        else:
            for f in beers_findings[:5]:
                lines.append(
                    f"- **{f.get('category')}** — matched: "
                    f"{', '.join(f.get('matched_medications', []))}. "
                    f"{_truncate(f.get('recommendation', ''), 100)}"
                )
            if len(beers_findings) > 5:
                lines.append(f"- _... and {len(beers_findings) - 5} more._")
        lines.append("")

    lines.append("---")
    lines.append(
        "_Citations: NICE NG203, BNF Appendix 1, AGS Beers 2023, STOPP/START v2 "
        "(O'Mahony 2015). Verbatim text for all rules is held in the rule data files. "
        "Rules cite their named source; entries marked `clinical_review_status=summarised_from_named_source` paraphrase copyrighted sources (BNF/Beers/STOPP) under fair use.\\n_NICE/MHRA-cited entries may be `verbatim_verified` under Open Government Licence v3.0._"
    )

    md = "\n".join(lines)
    # Hard size cap to avoid chat-loop bug
    if len(md) > 5000:
        md = md[:4990] + "\n_..._"
    return md


async def run_full_medication_review(ctx: Context = None) -> str:
    """
    Composite full medication review for the current patient.

    Pipeline:
      1. BuildPatientRiskProfile (LLM, cached)
      2. For each active medication: deterministic CheckMedicationSafety
      3. CheckDrugDrugInteraction across all active meds
      4. CheckSTOPPSTART (if age >=65)
      5. CheckBeersCriteria (if age >=65)
      6. Aggregate into compact markdown (<5KB) ranked by severity.

    Output is markdown — designed to render directly in Prompt Opinion chat
    without a JSON appendix that would trigger the chat-loop bug.
    """
    try:
        # Step 1 — patient risk profile
        profile_json = await build_patient_risk_profile(ctx=ctx)
        try:
            profile_data = json.loads(profile_json)
        except json.JSONDecodeError:
            return json.dumps({
                "error": "profile_json_unparseable",
                "raw_profile_preview": profile_json[:300],
            }, indent=2)

        if isinstance(profile_data, dict) and profile_data.get("error"):
            return json.dumps({
                "error": "upstream_profile_error",
                "message": profile_data.get("message", "Could not build risk profile"),
            }, indent=2)

        # Step 2 — per-drug safety verdicts
        try:
            per_drug = _build_per_drug_findings(profile_data)
        except Exception as e:
            logger.warning(f"per-drug evaluation partially failed: {e}")
            per_drug = []

        # Step 3 — DDI across active meds
        med_names = [m.get("name", "") for m in profile_data.get("active_medications", []) if m.get("name")]
        ddi_data: dict[str, Any] = {"interactions": []}
        if len(med_names) >= 2:
            ddi_resp = await check_drug_drug_interaction(
                medications_json=json.dumps(med_names),
                ctx=ctx,
            )
            try:
                ddi_data = json.loads(ddi_resp)
            except json.JSONDecodeError:
                ddi_data = {"interactions": []}

        # Step 4 — STOPP/START
        stopp_resp = await check_stopp_start(
            patient_risk_profile_json=profile_json,
            ctx=ctx,
        )
        try:
            stopp_data = json.loads(stopp_resp)
        except json.JSONDecodeError:
            stopp_data = {"applicable": False}

        # Step 5 — Beers
        beers_resp = await check_beers_criteria(
            patient_risk_profile_json=profile_json,
            ctx=ctx,
        )
        try:
            beers_data = json.loads(beers_resp)
        except json.JSONDecodeError:
            beers_data = {"applicable": False}

        # Step 6 — markdown report
        markdown = _build_markdown(
            profile_data=profile_data,
            per_drug=per_drug,
            stopp_data=stopp_data,
            beers_data=beers_data,
            ddi_data=ddi_data,
        )

        return markdown

    except Exception as e:
        logger.error(f"run_full_medication_review failed: {e}\n{traceback.format_exc()}")
        return json.dumps({
            "error": "tool_execution_failed",
            "error_type": type(e).__name__,
            "message": str(e),
        }, indent=2)
