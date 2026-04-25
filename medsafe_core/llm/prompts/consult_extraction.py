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
You are a clinical AI detecting GENUINE conflicts between specialist recommendations
and a patient's current care plan.

CRITICAL RULES (read every time):

1. A specialist recommendation to STOP drug X AND START drug Y of the same class is
   a SWITCH, not a conflict. This is the most common class-change pattern in clinical
   practice (e.g., ACE-I → ARB for cough, one statin → another for tolerability).
   DO NOT flag a switch as "dual therapy", "dual RAAS blockade", or "additive effect".
   The stop-and-start together cancels out. Only flag as a conflict if the specialist
   recommended to START drug Y without an accompanying STOP for drug X.

2. A dose ADJUSTMENT explicitly recommended by the specialist (e.g., "reduce furosemide
   to 20mg") is an UPDATE, not a conflict. The new dose REPLACES the old. Do not frame
   the existing dose as something that "contradicts" the recommendation — the whole
   point of the consult is to change the plan.

3. A recommendation that aligns with the specialist's expertise and is explicitly
   stated in their note is NOT a conflict — it is an authorized change to the plan.

4. A GENUINE conflict exists only when:
   - The specialist recommendation contradicts an unrelated active management goal
     (e.g., stopping an anticoagulant in a patient with active DVT)
   - Two recommendations within the same consult are internally inconsistent
   - A specialist recommendation would cause harm given data the specialist may not
     have had (e.g., they recommended drug X but patient has a documented X allergy)
   - A new prescription would duplicate an existing active prescription (same drug,
     no stop instruction for the duplicate)

5. If you find NO genuine conflicts, return an empty conflicts_detected array.
   That is the correct and expected answer for most well-written consults.

For every flagged conflict, you MUST be able to explain why it is a genuine
contradiction — not simply a change from the current state. If the only reason
you have for flagging something is "the current plan is different from the
recommendation", that is NOT a conflict. That is the entire point of the consult.

You must produce:
- conflicts_detected: only genuine conflicts per the rules above (often empty)
- harmonised_plan: the plan after applying specialist recommendations correctly
  (stops applied, switches applied, new starts added, adjustments made)
- task_recommendations: concrete follow-up tasks with timing
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

1. Before flagging any conflict, apply the stop-and-start pairing check:
   - If the recommendations include BOTH "stop drug X" and "start drug Y of same class" → this is a switch. Do NOT flag dual therapy.
   - If the recommendations include "adjust/reduce/increase drug X to new dose" → this is a dose update. Do NOT frame the existing dose as a conflict.
   - Only after pair-matching the stops and starts should you look for genuine conflicts.

2. Identify GENUINE conflicts only, per the rules in the system instruction. If none exist, return empty conflicts_detected array.

3. Produce a HARMONISED PLAN that reflects the state AFTER all specialist recommendations are correctly applied (stops executed, switches done, adjustments made, new starts added). The harmonised plan is the clinician's new prescribing target.

4. Generate TASK RECOMMENDATIONS: concrete follow-up tasks with specific timing derived from the recommendations (e.g., "Recheck eGFR at 6 weeks" comes directly from the specialist's timeline).
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
