"""
Referral sub-system prompt: Consult Note Recommendation Extraction.

Parses unstructured specialist consult notes and extracts structured
recommendations. This is where generative AI earns substantial value —
turning free-text clinical notes into reconcilable, actionable items
that can be compared against the current care plan.
"""

SYSTEM_INSTRUCTION = """\
You are a clinical AI parsing specialist consultation notes.

Your role is to extract STRUCTURED recommendations from free-text clinical letters.
You must:
- Extract only recommendations explicitly stated in the note
- Never invent or infer recommendations not present in the text
- Classify each recommendation by type (medication_change, monitoring, patient_education, referral_followup)
- Identify urgency level for each recommendation
- Flag any recommendations that require immediate attention
"""


def build_extraction_prompt(note_text: str) -> str:
    """Construct the consult note extraction prompt."""
    return f"""\
## Specialist Consultation Note

{note_text}

## Instructions

Extract ALL recommendations from this consultation note as structured objects.

For each recommendation, provide:
1. **type**: One of: medication_change, medication_start, medication_stop, monitoring, patient_education, lifestyle, referral_followup, investigation
2. **action**: The specific action (start, stop, adjust, recheck, discuss, order)
3. **target**: What the action applies to (drug name, test name, topic)
4. **rationale**: Why the specialist recommends this (from the note)
5. **urgency**: One of: immediate, within_1_week, within_1_month, routine, ongoing
6. **timing**: Specific timing if mentioned (e.g., "6 weeks", "3 months")

Also identify:
- **urgent_flags**: Any recommendations requiring immediate clinician attention
- **specialist_follow_up_needed**: Whether the specialist wants to see the patient again
- **specialist_follow_up_timeline**: When (if mentioned)
"""


CONFLICT_DETECTION_SYSTEM = """\
You are a clinical AI detecting potential conflicts between specialist recommendations
and a patient's current care plan.

A conflict exists when:
- A recommendation to stop/change a medication affects management of another condition
- A recommendation contradicts current plan for a related condition
- Two recommendations from different sources are incompatible

You must explain each conflict clearly and suggest a reconciliation path.
"""


def build_conflict_detection_prompt(
    recommendations: list[dict],
    current_medications: list[dict],
    conditions: list[dict],
    profile_data: dict,
) -> str:
    """Construct the conflict detection prompt."""
    return f"""\
## Specialist Recommendations (just extracted)

{_format_recommendations(recommendations)}

## Current Care Plan

### Active Medications
{_format_current_meds(current_medications)}

### Active Conditions Being Managed
{_format_current_conditions(conditions)}

## Patient Context
Age: {profile_data.get("age", "?")}
Clinical flags: {", ".join(profile_data.get("clinical_context_flags", []))}

## Instructions

1. Identify any CONFLICTS between the specialist recommendations and the current plan
2. For each conflict, explain:
   - What conflicts with what
   - Why it matters clinically
   - Suggested reconciliation (how to harmonise both)
   - Whether clinician action is required

3. Produce a HARMONISED PLAN: the combined set of actions that incorporates the specialist recommendations while maintaining appropriate management of existing conditions

4. Generate TASK RECOMMENDATIONS: specific follow-up tasks with timing for the PCP
"""


def _format_recommendations(recs: list[dict]) -> str:
    lines = []
    for r in recs:
        lines.append(
            f"- [{r.get('type', '?')}] {r.get('action', '?')} {r.get('target', '?')} "
            f"(urgency: {r.get('urgency', '?')}, timing: {r.get('timing', 'not specified')})\n"
            f"  Rationale: {r.get('rationale', 'none given')}"
        )
    return "\n".join(lines) if lines else "No recommendations extracted."


def _format_current_meds(meds: list[dict]) -> str:
    lines = []
    for m in meds:
        name = m.get("medicationCodeableConcept", {}).get("text", "Unknown")
        dose = m.get("dosageInstruction", [{}])
        dose_text = dose[0].get("text", "") if dose else ""
        lines.append(f"- {name} — {dose_text}")
    return "\n".join(lines) if lines else "No active medications."


def _format_current_conditions(conditions: list[dict]) -> str:
    lines = []
    for c in conditions:
        text = c.get("code", {}).get("text", "Unknown condition")
        lines.append(f"- {text}")
    return "\n".join(lines) if lines else "No active conditions."
