"""
Prompt for SuggestAlternative — given a contraindicated drug + the
contraindication reason, suggest 3-5 safer alternatives with structured
rationale, dosing, and monitoring.

Phase-3-style: this LLM reasons FROM the deterministic verdict, not against
it. The rules engine has already decided the original drug is unsafe; this
tool fills in the 'so what should I do instead?' answer.
"""

SYSTEM_INSTRUCTION = """\
You are a UK-trained clinical pharmacist AI suggesting safer prescribing alternatives.

Constraints:
- You receive a contraindicated drug plus the reason it was flagged unsafe.
- You may also receive a patient risk profile (renal function, comorbidities, current meds).
- Suggest exactly 3-5 alternatives. Rank by suitability for THIS patient.
- For each alternative explain:
  1. Why it avoids the specific issue that contraindicated the original
  2. A typical UK starting dose (BNF) where well-defined
  3. Recommended monitoring
  4. Any residual cautions
- Use UK generic names (INN) and BNF dosing conventions.
- Do NOT invent alternatives that share the contraindicated mechanism (e.g. for an NSAID
  contraindicated in CKD, do NOT suggest another systemic NSAID).
- If a drug class is genuinely required and no class-different alternative exists, say so
  explicitly and suggest the safest member of the class with mitigating monitoring.
- Be specific: reference the patient's actual eGFR, age, or condition where relevant.
"""


def build_suggest_alternative_prompt(
    drug_name: str,
    contraindication_reason: str,
    profile_data: dict | None = None,
) -> str:
    """
    Build the SuggestAlternative prompt.

    Args:
        drug_name: The contraindicated medication.
        contraindication_reason: Free-text explanation of why it's unsafe.
        profile_data: Optional patient risk profile dict for personalisation.
    """
    profile_block = ""
    if profile_data:
        renal = profile_data.get("renal_function", {}) or {}
        meds = profile_data.get("active_medications", []) or []
        med_lines = "\n".join(
            f"- {m.get('name', '?')} ({m.get('drug_class', '?')})" for m in meds
        ) or "None recorded."
        profile_block = f"""\

## Patient context

Age: {profile_data.get("age", "unknown")}
Sex: {profile_data.get("sex", "unknown")}
Latest eGFR: {renal.get("latest_egfr", "unknown")} ({renal.get("trajectory", "unknown")} trajectory)
Active medications:
{med_lines}
Clinical context flags: {", ".join(profile_data.get("clinical_context_flags", []) or [])}
"""

    return f"""\
## Contraindicated medication
{drug_name}

## Reason for contraindication (from MedSafe rules engine)
{contraindication_reason}
{profile_block}
## Your task
Suggest 3 to 5 safer alternatives ranked by suitability for THIS patient. For each:
- name (UK generic / INN)
- drug_class
- rationale (why it's safer for this patient given the specific contraindication)
- typical_starting_dose (BNF where well-defined)
- monitoring (specific labs / vitals / timeframes)
- cautions (residual risks the clinician should still consider)

Conclude with a one-sentence `summary` field summarising your top recommendation.
"""
