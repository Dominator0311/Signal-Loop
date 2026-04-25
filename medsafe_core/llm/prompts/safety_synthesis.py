"""
Phase 3 prompt: Safety Response Synthesis.

Produces patient-specific narrative explaining WHY the safety flags matter
for THIS patient, personalised alternative recommendations with trade-offs,
and monitoring plans.

This is where AI earns its value over a flat rules engine: turning
deterministic output into clinically-actionable, patient-specific prose.
"""

SYSTEM_INSTRUCTION = """\
You are a clinical pharmacist AI producing patient-specific medication safety guidance.

You receive:
1. A deterministic safety verdict with flags (from a rules engine — these are facts, not suggestions)
2. A patient risk profile (structured clinical context)

You must:
- NEVER contradict or override the deterministic verdict
- Explain WHY each flag matters for THIS SPECIFIC patient (cite actual chart facts)
- For each alternative, explain why it fits THIS patient given THEIR other medications and presentation
- Suggest concrete monitoring plans with specific timeframes
- Use clinical professional language (for clinician audience)
- Be specific: "Margaret's eGFR has declined 16 points" not "the patient has renal impairment"
"""


def build_synthesis_prompt(verdict_data: dict, profile_data: dict) -> str:
    """
    Construct the Phase 3 synthesis prompt.

    Args:
        verdict_data: Serialized SafetyVerdict from Phase 2
        profile_data: Serialized PatientRiskProfile from Phase 1
    """
    return f"""\
## Safety Verdict (from deterministic rules engine — these are FACTS)

Proposed medication: {verdict_data.get("proposed_medication", "unknown")}
Overall verdict: {verdict_data.get("verdict", "unknown")}

Flags:
{_format_flags(verdict_data.get("flags", []))}

## Patient Risk Profile

Patient: {profile_data.get("patient_id", "unknown")}
Age: {profile_data.get("age", "unknown")}
Sex: {profile_data.get("sex", "unknown")}

Renal function:
- Latest eGFR: {profile_data.get("renal_function", {}).get("latest_egfr", "unknown")}
- Trajectory: {profile_data.get("renal_function", {}).get("trajectory", "unknown")}
- Rate of change: {profile_data.get("renal_function", {}).get("rate_of_change_per_month", "unknown")} per month

Active medications:
{_format_profile_meds(profile_data.get("active_medications", []))}

Clinical context flags: {", ".join(profile_data.get("clinical_context_flags", []))}

Reasoning trace: {profile_data.get("reasoning_trace", "")}

## Your Task

Produce:
1. **patient_specific_narrative**: A 3-5 sentence explanation of why this medication is unsafe for THIS patient. Reference specific chart facts (eGFR values, specific drug names, specific conditions). Do not use generic language.

2. **personalised_alternatives**: For each safer alternative, explain:
   - Why it's suitable for THIS patient specifically
   - What trade-offs exist given their other medications/conditions
   - What monitoring is needed

3. **monitoring_if_override**: If the clinician insists on proceeding despite the warning, what specific monitoring protocol should be followed? Include timeframes.
"""


def _format_flags(flags: list) -> str:
    if not flags:
        return "No flags (clean)."
    lines = []
    for f in flags:
        lines.append(
            f"- [{f.get('severity', '?')} · {f.get('evidence_level', '?')}] "
            f"{f.get('reason', 'no reason')}\n"
            f"  Citation: {f.get('citation', 'none')}"
        )
    return "\n".join(lines)


def _format_profile_meds(meds: list) -> str:
    if not meds:
        return "None recorded."
    return "\n".join(f"- {m.get('name', '?')} ({m.get('drug_class', '?')})" for m in meds)
