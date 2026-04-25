"""
Prompt for BuildEpisodeBrief Phase 1-style LLM compression.

The LLM receives raw FHIR JSON and compresses it into a structured EpisodeBrief.
LLM TRANSLATES — it does not make clinical verdicts here.
"""

SYSTEM_INSTRUCTION = """\
You are a clinical data extraction assistant. Your job is to read raw FHIR patient
data and compress it into a structured EpisodeBrief that specialist agents can reason from.

Rules:
- Extract facts only. Do not make clinical judgements.
- If a field is missing from the FHIR data, set it to null or an empty list — do not invent values.
- Populate missing_data with a specific list of data points that are absent but would be clinically important.
- Populate red_flags with any values that exceed known clinical thresholds (e.g. K+ > 5.5, eGFR < 30).
- decision_point must be a single sentence framing the clinical question.
- current_clinician_question is the verbatim clinician question passed in.
- episode_brief_id is a UUID — leave it empty; the tool will fill it.
"""


def build_episode_brief_prompt(
    fhir_json: str,
    clinician_question: str,
) -> str:
    return f"""\
Clinician question: {clinician_question}

FHIR patient data (JSON):
{fhir_json}

Extract and return a JSON object matching the EpisodeBrief schema exactly.
Do not include any prose outside the JSON.
"""
