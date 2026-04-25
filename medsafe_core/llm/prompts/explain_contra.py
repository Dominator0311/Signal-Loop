"""
Prompt for ExplainContraindication — given a SafetyVerdict, produce a
patient-friendly natural-language explanation alongside the clinical one.

Phase-3-style: the rules engine has already decided. The LLM is here to
turn flags into prose a clinician (and a patient) can understand.
"""

SYSTEM_INSTRUCTION = """\
You are a clinical pharmacist AI explaining medication safety verdicts.

You produce TWO complementary explanations of the same verdict:

1. clinical_explanation: For the prescriber. Concise (3-5 sentences). References
   chart facts (specific eGFR, drug names, conditions). Names the rule fired
   and its citation. No fluff.

2. patient_friendly_explanation: For the patient. Plain English at a
   secondary-school reading level. Use simple analogies sparingly where they
   genuinely help (e.g. "kidneys filter waste like a coffee filter"). NEVER
   add reassurance that contradicts the verdict — the drug really is unsafe
   for them.

Also produce:

3. key_risks: bullet list of the specific risks this contraindication
   addresses (e.g. "Acute kidney injury", "GI bleeding").

4. next_steps: bullet list of suggested next steps for the clinician.

Hard rules:
- NEVER soften or contradict the deterministic verdict.
- NEVER invent chart facts; reason only from what's in the verdict / profile.
- Keep both explanations short. The patient version must be readable in <30 seconds.
"""


def build_explain_contra_prompt(verdict_data: dict, profile_data: dict | None = None) -> str:
    """
    Build the ExplainContraindication prompt.

    Args:
        verdict_data: Serialized SafetyVerdict dict.
        profile_data: Optional patient risk profile dict.
    """
    flags = verdict_data.get("flags", []) or []
    flag_lines = []
    for f in flags:
        flag_lines.append(
            f"- [{f.get('severity', '?')} / {f.get('evidence_level', '?')}] "
            f"{f.get('reason', '')}\n  citation: {f.get('citation', '')}"
        )
    flags_block = "\n".join(flag_lines) if flag_lines else "(no flags)"

    profile_block = ""
    if profile_data:
        renal = profile_data.get("renal_function", {}) or {}
        profile_block = f"""\

## Patient context

Patient: {profile_data.get("patient_id", "unknown")} ({profile_data.get("age", "?")}{profile_data.get("sex", "?")[:1].upper() if profile_data.get("sex") else ""})
Latest eGFR: {renal.get("latest_egfr", "unknown")} ({renal.get("trajectory", "unknown")})
Clinical context flags: {", ".join(profile_data.get("clinical_context_flags", []) or [])}
"""

    return f"""\
## Safety verdict (from deterministic rules engine — these are FACTS)

Proposed medication: {verdict_data.get("proposed_medication", "unknown")}
Verdict: {verdict_data.get("verdict", "unknown")}

Flags:
{flags_block}
{profile_block}
## Your task

Produce the four output fields:
1. clinical_explanation — 3-5 sentences, prescriber-facing.
2. patient_friendly_explanation — plain English, <30s read, no jargon.
3. key_risks — bullets.
4. next_steps — bullets.
"""
