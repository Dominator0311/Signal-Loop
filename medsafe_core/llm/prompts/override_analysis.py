"""
Phase 3 prompt: Override Reason Analysis.

When a clinician overrides a MedSafe block, this prompt analyses the
free-text reason and produces structured justification for the audit trail.

This is substantive AI value: a traditional override just captures free text.
This analyses it, classifies it, and suggests mitigating monitoring.
"""

SYSTEM_INSTRUCTION = """\
You are a clinical governance AI analysing a clinician's override of a medication safety alert.

Your role is NOT to second-guess the clinician. It is to:
1. Classify the override reason into a structured category
2. Assess whether it represents valid clinical context
3. Suggest specific monitoring to mitigate remaining risk
4. Structure the justification for permanent audit records

Be respectful of clinical judgment while ensuring accountability.
"""


def build_override_analysis_prompt(
    reason_text: str,
    verdict_data: dict,
    profile_data: dict,
) -> str:
    """Construct the override analysis prompt."""
    return f"""\
## Override Context

The clinician has chosen to override the following safety alert:

Proposed medication: {verdict_data.get("proposed_medication", "unknown")}
Verdict that was overridden: {verdict_data.get("verdict", "unknown")}
Top flag: {verdict_data.get("flags", [{}])[0].get("reason", "unknown") if verdict_data.get("flags") else "unknown"}

Patient: {profile_data.get("patient_id", "unknown")}, Age {profile_data.get("age", "?")}
eGFR: {profile_data.get("renal_function", {}).get("latest_egfr", "?")}

## Clinician's Override Reason (free text)

"{reason_text}"

## Your Task

Produce:
1. **override_classification**: One of: specialist_recommendation, short_course_trial, no_alternative_available, patient_preference, emergency, other
2. **clinical_validity_assessment**: Brief assessment of whether this reason represents valid clinical context (1-2 sentences)
3. **suggested_monitoring**: List of specific monitoring steps to mitigate remaining risk (with timeframes)
4. **structured_audit_justification**: A single sentence suitable for permanent medical records
5. **residual_risk_acknowledged**: true/false — does the reason acknowledge the risk?
"""
