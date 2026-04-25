"""
Pydantic output schemas for LLM structured generation.

These models define what the LLM must return. They are passed to
Gemini's response_json_schema parameter to enforce structured output.

Design: keep schemas flat where possible (Gemini can struggle with
deeply nested schemas). Use Optional fields generously.
"""

from pydantic import BaseModel, Field


# --- Phase 1: Patient Risk Profile (LLM output) ---

class LLMRenalFunction(BaseModel):
    latest_egfr: float | None = None
    trajectory: str | None = Field(None, description="stable, declining, or improving")
    rate_of_change_per_month: float | None = None
    relevance: str = Field(default="", description="Why this matters for prescribing safety")


class LLMMedicationEntry(BaseModel):
    name: str
    drug_class: str
    classes: list[str] = Field(default_factory=list)
    interaction_relevant_properties: list[str] = Field(default_factory=list)
    notes: str = ""


class LLMAllergyEntry(BaseModel):
    substance: str
    reaction: str = ""
    cross_reactivity_concerns: list[str] = Field(default_factory=list)


class LLMPatientRiskProfile(BaseModel):
    """Schema for Phase 1 LLM output — patient risk profile."""
    patient_id: str
    first_name: str | None = Field(
        default=None,
        description="Patient's first name from FHIR Patient.name[0].given[0]. "
                    "Used by the agent to address the patient in response prose. "
                    "Populated deterministically from FHIR — LLM should not invent this.",
    )
    age: int | None = None
    sex: str | None = None
    weight_kg: float | None = None

    renal_function: LLMRenalFunction = Field(default_factory=LLMRenalFunction)

    active_medications: list[LLMMedicationEntry] = Field(default_factory=list)
    allergies: list[LLMAllergyEntry] = Field(default_factory=list)

    clinical_context_flags: list[str] = Field(default_factory=list)
    reasoning_trace: str = ""


# --- Phase 3: Safety Response Synthesis (LLM output) ---

class LLMAlternative(BaseModel):
    name: str
    suitability_for_this_patient: str
    rationale: str
    trade_offs: str
    monitoring_plan: str = ""


class LLMSafetyResponse(BaseModel):
    """Schema for Phase 3 LLM output — patient-specific safety narrative."""
    patient_specific_narrative: str = Field(
        description="3-5 sentence explanation of why this medication is unsafe for THIS patient"
    )
    personalised_alternatives: list[LLMAlternative] = Field(default_factory=list)
    monitoring_if_override: str = Field(
        default="",
        description="Monitoring protocol if clinician overrides despite warning"
    )


# --- Phase 3: Override Analysis (LLM output) ---

class LLMOverrideAnalysis(BaseModel):
    """Schema for override reason analysis output."""
    override_classification: str = Field(
        description="One of: specialist_recommendation, short_course_trial, "
        "no_alternative_available, patient_preference, emergency, other"
    )
    clinical_validity_assessment: str
    suggested_monitoring: list[str] = Field(default_factory=list)
    structured_audit_justification: str
    residual_risk_acknowledged: bool = False


# --- Referral: Consult Note Extraction (LLM output) ---

class LLMExtractedRecommendation(BaseModel):
    type: str = Field(description="medication_change, monitoring, patient_education, etc.")
    action: str = Field(description="start, stop, adjust, recheck, discuss, order")
    target: str
    rationale: str = ""
    urgency: str = Field(default="routine", description="immediate, within_1_week, within_1_month, routine")
    timing: str = ""


class LLMConsultExtraction(BaseModel):
    """Schema for consult note recommendation extraction."""
    extracted_recommendations: list[LLMExtractedRecommendation] = Field(default_factory=list)
    urgent_flags: list[str] = Field(default_factory=list)
    specialist_follow_up_needed: bool = False
    specialist_follow_up_timeline: str = ""


# --- Referral: Conflict Detection (LLM output) ---

class LLMPlanConflict(BaseModel):
    conflict_type: str
    description: str
    current_plan_item: str
    incoming_recommendation: str
    reconciliation_suggestion: str
    clinician_action_required: bool = True


class LLMTaskRecommendation(BaseModel):
    task_type: str
    timing: str
    description: str = ""


class LLMConflictDetection(BaseModel):
    """Schema for plan conflict detection output."""
    conflicts_detected: list[LLMPlanConflict] = Field(default_factory=list)
    harmonised_plan: list[str] = Field(default_factory=list)
    task_recommendations: list[LLMTaskRecommendation] = Field(default_factory=list)


# --- SuggestAlternative (LLM output) ---

class AlternativeSuggestion(BaseModel):
    """A single safer alternative for a contraindicated medication."""
    name: str = Field(description="Generic drug name of the alternative (UK INN where applicable)")
    drug_class: str = Field(description="Pharmacological class of the alternative")
    rationale: str = Field(
        description="Why this alternative is safer for this specific patient given the contraindication"
    )
    typical_starting_dose: str = Field(
        default="",
        description="Typical UK starting dose (BNF). Empty if dose is highly individualised.",
    )
    monitoring: str = Field(
        default="",
        description="Recommended monitoring after starting this alternative",
    )
    cautions: str = Field(
        default="",
        description="Residual cautions / contraindications the clinician should still consider",
    )


class AlternativeList(BaseModel):
    """Schema for SuggestAlternative LLM output — 3 to 5 alternatives."""
    original_drug: str
    contraindication_reason: str
    alternatives: list[AlternativeSuggestion] = Field(
        default_factory=list,
        description="3-5 safer alternatives ranked by suitability for this patient",
    )
    summary: str = Field(
        default="",
        description="One-sentence summary of the recommendation for the clinician",
    )


# --- ExplainContraindication (LLM output) ---

class ContraindicationExplanation(BaseModel):
    """Schema for ExplainContraindication LLM output — clinical + patient explanations."""
    clinical_explanation: str = Field(
        description=(
            "Concise clinician-facing explanation of why the medication is contraindicated "
            "for this patient. References specific chart facts and cites the rule."
        )
    )
    patient_friendly_explanation: str = Field(
        description=(
            "Plain-English explanation suitable for sharing with the patient. Avoids jargon, "
            "uses analogies where helpful, addresses 'why this drug, why now'."
        )
    )
    key_risks: list[str] = Field(
        default_factory=list,
        description="Bullet list of the specific risks this contraindication addresses",
    )
    next_steps: list[str] = Field(
        default_factory=list,
        description="Suggested next steps for the clinician (e.g. discuss alternative, repeat eGFR)",
    )
