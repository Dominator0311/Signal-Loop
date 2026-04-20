"""
Pydantic models for the rules engine.

These models define the data contracts between Phase 1 (profile building),
Phase 2 (rules evaluation), and Phase 3 (response synthesis). They are the
shared language of the MedSafe pipeline.
"""

from enum import Enum
from pydantic import BaseModel, Field


class Severity(str, Enum):
    """Interaction severity level (from severity matrix)."""
    CONTRAINDICATED = "contraindicated"
    MAJOR = "major"
    MODERATE = "moderate"
    MINOR = "minor"


class EvidenceLevel(str, Enum):
    """Evidence quality for the interaction."""
    ESTABLISHED = "established"
    PROBABLE = "probable"
    SUSPECTED = "suspected"
    THEORETICAL = "theoretical"


class Verdict(str, Enum):
    """Final prescribing verdict from Phase 2."""
    BLOCK = "block"
    WARN_OVERRIDE_REQUIRED = "warn_override_required"
    WARN = "warn"
    INFO = "info"
    CLEAN = "clean"


class SafetyFlag(BaseModel):
    """A single safety flag raised by the rules engine."""
    rule_id: str
    flag_type: str
    severity: Severity
    evidence_level: EvidenceLevel
    reason: str
    citation: str
    profile_fields_consulted: list[str] = Field(default_factory=list)


class SafetyVerdict(BaseModel):
    """Complete Phase 2 output: verdict plus all flags."""
    proposed_medication: str
    proposed_medication_code: str | None = None
    proposed_medication_class: str | None = None
    verdict: Verdict
    flags: list[SafetyFlag] = Field(default_factory=list)
    requires_override_reason: bool = False
    profile_fields_consulted: list[str] = Field(default_factory=list)


class RenalFunction(BaseModel):
    """Renal function data from patient profile."""
    latest_egfr: float | None = None
    trajectory: str | None = None
    rate_of_change_per_month: float | None = None


class MedicationEntry(BaseModel):
    """A single active medication in the patient's profile."""
    name: str
    drug_class: str
    classes: list[str] = Field(default_factory=list)


class AllergyEntry(BaseModel):
    """A single allergy in the patient's profile."""
    substance: str
    substance_class: str | None = None
    reaction: str | None = None


class PatientRiskProfile(BaseModel):
    """
    Structured patient risk profile (Phase 1 output).

    This is the data contract between Phase 1 (LLM builds this)
    and Phase 2 (rules engine consumes this). The profile parameterises
    the deterministic safety checks.
    """
    patient_id: str
    age: int | None = None
    sex: str | None = None
    weight_kg: float | None = None

    renal_function: RenalFunction = Field(default_factory=RenalFunction)

    active_medications: list[MedicationEntry] = Field(default_factory=list)
    allergies: list[AllergyEntry] = Field(default_factory=list)

    clinical_context_flags: list[str] = Field(default_factory=list)
    # e.g., ["frail_elderly", "polypharmacy", "heart_failure", "gi_bleed_history"]

    reasoning_trace: str = ""
