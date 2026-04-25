"""
Pydantic schemas for all Concord data contracts.

These models define the interfaces between:
  - BuildEpisodeBrief → specialist workers (EpisodeBrief)
  - specialist workers → ComputeConflictMatrix (SpecialistOpinion)
  - ComputeConflictMatrix → ValidateFinalPlan (ConflictMatrix + UnifiedPlan)
  - ValidateFinalPlan → write tools (PlanValidationResult)
  - write tools → audit (TaskDraft, MedicationProposalDraft, etc.)
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from rules.action_codes import ActionCode


# --- EpisodeBrief sub-models ---

class ProblemSummary(BaseModel):
    code: str
    display: str
    status: str
    onset: str | None = None


class MedicationSummary(BaseModel):
    name: str
    dose: str | None = None
    drug_class: str | None = None
    start_date: str | None = None


class LabSummary(BaseModel):
    code: str
    display: str
    value: float | str
    unit: str | None = None
    date: str
    interpretation: str | None = None


class TrendPoint(BaseModel):
    date: str
    value: float
    unit: str | None = None


class TrendSummary(BaseModel):
    egfr: list[TrendPoint] = Field(default_factory=list)
    creatinine: list[TrendPoint] = Field(default_factory=list)
    potassium: list[TrendPoint] = Field(default_factory=list)
    weight: list[TrendPoint] = Field(default_factory=list)
    bnp: list[TrendPoint] = Field(default_factory=list)
    egfr_trajectory: str | None = None
    egfr_rate_of_change_per_month: float | None = None


class EpisodeBrief(BaseModel):
    patient_id: str
    decision_point: str
    active_problems: list[ProblemSummary] = Field(default_factory=list)
    active_medications: list[MedicationSummary] = Field(default_factory=list)
    recent_labs: list[LabSummary] = Field(default_factory=list)
    trend_summary: TrendSummary = Field(default_factory=TrendSummary)
    red_flags: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    current_clinician_question: str
    episode_brief_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


# --- SpecialistOpinion ---

class Recommendation(BaseModel):
    action_code: ActionCode
    free_text: str
    priority: Literal["high", "medium", "low"]
    rationale: str
    risks: list[str] = Field(default_factory=list)
    monitoring: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    contraindications: list[str] = Field(default_factory=list)
    evidence_citation: str | None = None


class SpecialistOpinion(BaseModel):
    specialty: Literal["nephrology", "cardiology", "pharmacy"]
    summary: str
    recommendations: list[Recommendation] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    cross_specialty_dependencies: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]


# --- ConflictMatrix ---

class ConflictItem(BaseModel):
    action_code: ActionCode
    specialties_supporting: list[str] = Field(default_factory=list)
    specialties_opposing: list[str] = Field(default_factory=list)
    resolution: Literal[
        "consensus", "tension", "direct_conflict",
        "dependency", "missing_data_block", "safety_block"
    ]
    severity: Literal["low", "medium", "high"]
    notes: str


class ConflictMatrix(BaseModel):
    consensus: list[ConflictItem] = Field(default_factory=list)
    tensions: list[ConflictItem] = Field(default_factory=list)
    direct_conflicts: list[ConflictItem] = Field(default_factory=list)
    dependencies: list[ConflictItem] = Field(default_factory=list)
    missing_data_blocks: list[ConflictItem] = Field(default_factory=list)
    safety_blocks: list[ConflictItem] = Field(default_factory=list)
    ranked_next_actions: list[ActionCode] = Field(default_factory=list)
    episode_brief_id: str


# --- UnifiedPlan ---

class DraftAction(BaseModel):
    action_code: ActionCode
    resource_type: Literal["Task", "MedicationRequest", "Communication"]
    description: str
    owner_confirmer: str
    monitoring: list[str] = Field(default_factory=list)
    timing: str | None = None


class UnifiedPlan(BaseModel):
    decision_summary: str
    agreed_actions_now: list[DraftAction] = Field(default_factory=list)
    actions_pending_confirmation: list[DraftAction] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    patient_safe_explanation: str
    draft_writes: list[DraftAction] = Field(default_factory=list)
    episode_brief_id: str
    specialist_task_ids: dict[str, str] = Field(default_factory=dict)


# --- PlanValidationResult ---

class PlanValidationResult(BaseModel):
    status: Literal["pass", "pass_with_warnings", "fail"]
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validated_plan: UnifiedPlan | None = None


# --- Draft write output types ---

class TaskDraft(BaseModel):
    status: str = "draft"
    resource_type: str = "Task"
    action_code: str
    description: str
    owner_confirmer: str
    due_date: str | None = None
    timing: str | None = None


class MedicationProposalDraft(BaseModel):
    status: str = "proposal"
    resource_type: str = "MedicationRequest"
    action_code: str
    medication: str
    rationale: str
    owner_confirmer: str
    requires_clinician_approval: bool = True


class CommunicationDraft(BaseModel):
    status: str = "draft"
    resource_type: str = "Communication"
    to_specialty: str
    summary: str
    linked_action_codes: list[str] = Field(default_factory=list)


class AuditEventRef(BaseModel):
    resource_type: str = "AuditEvent"
    episode_brief_id: str
    recorded_at: str
    audit_id: str
    status: str = "created"


# --- LLM output schemas for BuildEpisodeBrief ---
# Kept flat so Gemini can produce them reliably. Mapped to full EpisodeBrief post-call.

class LLMProblemSummary(BaseModel):
    display: str
    status: str = "active"
    onset: str | None = None


class LLMMedicationSummary(BaseModel):
    name: str
    dose: str | None = None
    drug_class: str | None = None


class LLMLabSummary(BaseModel):
    display: str
    value: str  # str to handle both numeric and textual values
    unit: str | None = None
    date: str
    interpretation: str | None = None


class LLMEpisodeBrief(BaseModel):
    """Flat schema for Gemini structured output. Maps to EpisodeBrief after LLM call."""
    decision_point: str = Field(description="One sentence framing of the clinical coordination question")
    active_problems: list[LLMProblemSummary] = Field(default_factory=list)
    active_medications: list[LLMMedicationSummary] = Field(default_factory=list)
    recent_labs: list[LLMLabSummary] = Field(default_factory=list)
    red_flags: list[str] = Field(
        default_factory=list,
        description="Values exceeding clinical thresholds (e.g. 'K+ 5.4 — above normal range')",
    )
    missing_data: list[str] = Field(
        default_factory=list,
        description="Clinically important data absent from the FHIR record",
    )
