"""
Phase 1 prompt: Patient Risk Profile Builder.

This prompt instructs the LLM to read a patient's full FHIR record
and produce a structured risk profile focused on medication safety.
The profile parameterises the Phase 2 deterministic rules engine.

Key prompt design principles:
  - Be explicit about what TO produce (structured profile with reasoning)
  - Be explicit about what NOT to do (never invent data not in the record)
  - Constrain the output tightly to the Pydantic schema
  - Emphasise clinical reasoning traces (why each factor matters)
"""

SYSTEM_INSTRUCTION = """\
You are a clinical pharmacist AI assistant specialising in medication safety assessment.
Your role is to analyse a patient's clinical record and produce a structured risk profile
that will be used by a deterministic rules engine to evaluate prescribing safety.

You must:
- Only use information present in the provided patient data
- Never invent, assume, or infer data not explicitly in the record
- Provide reasoning traces explaining WHY each factor is relevant to medication safety
- Identify ALL active medications with their pharmacological classes
- Assess renal function trajectory (not just latest value)
- Flag clinical context that affects prescribing decisions

Your output will directly parameterise safety rules. Accuracy is critical.
"""


def build_profile_prompt(patient_data: dict) -> str:
    """
    Construct the Phase 1 profile-building prompt from patient FHIR data.

    Args:
        patient_data: Dict containing patient demographics, conditions,
                     medications, allergies, observations, and documents.
    """
    return f"""\
Analyse the following patient record and produce a medication safety risk profile.

## Patient Record

### Demographics
{_format_demographics(patient_data.get("patient", {}))}

### Active Conditions
{_format_conditions(patient_data.get("conditions", []))}

### Active Medications
{_format_medications(patient_data.get("medications", []))}

### Allergies
{_format_allergies(patient_data.get("allergies", []))}

### Recent Observations (Labs & Vitals)
{_format_observations(patient_data.get("observations", []))}

### Clinical Notes
{_format_documents(patient_data.get("documents", []))}

## Instructions

Produce a structured risk profile with:
1. **Demographics**: age, sex, weight if available
2. **Renal function**: latest eGFR, trajectory (stable/declining/improving), rate of change per month if multiple values available
3. **Active medication inventory**: each medication with its pharmacological class(es) and interaction-relevant properties
4. **Allergy profile**: each allergy with cross-reactivity concerns
5. **Clinical context flags**: relevant flags from this set: frail_elderly, polypharmacy, heart_failure, gi_bleed_history, cardio_renal_high_risk, ckd_stage_3b_near_4, pregnancy, liver_disease
6. **Reasoning trace**: a brief explanation of the primary prescribing safety concerns for this patient

Focus exclusively on factors relevant to MEDICATION SAFETY decisions.
Do not summarise the entire chart — select only what matters for prescribing.
"""


def _format_demographics(patient: dict) -> str:
    if not patient:
        return "No patient demographics available."
    name = patient.get("name", [{}])[0]
    given = " ".join(name.get("given", []))
    family = name.get("family", "")
    birth_date = patient.get("birthDate", "unknown")
    gender = patient.get("gender", "unknown")
    return f"Name: {given} {family}\nDOB: {birth_date}\nGender: {gender}"


def _format_conditions(conditions: list) -> str:
    if not conditions:
        return "No active conditions recorded."
    lines = []
    for c in conditions:
        code = c.get("code", {})
        text = code.get("text", code.get("coding", [{}])[0].get("display", "Unknown"))
        onset = c.get("onsetDateTime", "unknown onset")
        notes = c.get("note", [])
        note_text = notes[0].get("text", "") if notes else ""
        line = f"- {text} (onset: {onset})"
        if note_text:
            line += f"\n  Note: {note_text}"
        lines.append(line)
    return "\n".join(lines)


def _format_medications(medications: list) -> str:
    if not medications:
        return "No active medications."
    lines = []
    for m in medications:
        med_concept = m.get("medicationCodeableConcept", {})
        name = med_concept.get("text", "Unknown medication")
        dosage = m.get("dosageInstruction", [{}])
        dose_text = dosage[0].get("text", "") if dosage else ""
        notes = m.get("note", [])
        note_text = notes[0].get("text", "") if notes else ""
        line = f"- {name}"
        if dose_text:
            line += f" — {dose_text}"
        if note_text:
            line += f"\n  Note: {note_text}"
        lines.append(line)
    return "\n".join(lines)


def _format_allergies(allergies: list) -> str:
    if not allergies:
        return "No known allergies."
    lines = []
    for a in allergies:
        code = a.get("code", {})
        substance = code.get("text", code.get("coding", [{}])[0].get("display", "Unknown"))
        reactions = a.get("reaction", [])
        reaction_text = ""
        if reactions:
            manifestations = reactions[0].get("manifestation", [])
            if manifestations:
                reaction_text = manifestations[0].get("text", "")
        severity = reactions[0].get("severity", "") if reactions else ""
        line = f"- {substance}"
        if reaction_text:
            line += f" (reaction: {reaction_text}, severity: {severity})"
        lines.append(line)
    return "\n".join(lines)


def _format_observations(observations: list) -> str:
    if not observations:
        return "No recent observations."
    lines = []
    for o in observations:
        code = o.get("code", {})
        name = code.get("text", code.get("coding", [{}])[0].get("display", "Unknown"))
        date = o.get("effectiveDateTime", "unknown date")
        value_qty = o.get("valueQuantity")
        if value_qty:
            value = f"{value_qty.get('value')} {value_qty.get('unit', '')}"
        else:
            # Handle component-based observations (e.g., BP)
            components = o.get("component", [])
            if components:
                parts = []
                for comp in components:
                    comp_name = comp.get("code", {}).get("coding", [{}])[0].get("display", "")
                    comp_val = comp.get("valueQuantity", {})
                    parts.append(f"{comp_name}: {comp_val.get('value', '?')}")
                value = "; ".join(parts)
            else:
                value = "no value"
        lines.append(f"- {name}: {value} ({date})")
    return "\n".join(lines)


def _format_documents(documents: list) -> str:
    if not documents:
        return "No clinical documents."
    lines = []
    for d in documents:
        desc = d.get("description", "Untitled document")
        date = d.get("date", "unknown date")
        content = d.get("content", [])
        content_preview = ""
        if content:
            attachment = content[0].get("attachment", {})
            if attachment.get("contentType") == "text/plain" and attachment.get("data"):
                import base64
                try:
                    decoded = base64.b64decode(attachment["data"]).decode("utf-8")
                    content_preview = decoded[:500]
                except Exception:
                    content_preview = "[content not decodable]"
        line = f"- {desc} ({date})"
        if content_preview:
            line += f"\n  Content: {content_preview}"
        lines.append(line)
    return "\n".join(lines)
