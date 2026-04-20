"""
Deterministic medication safety rules engine (MedSafe Phase 2).

This module is the safety-critical core. It contains NO LLM calls.
Every verdict traces to a specific rule with a specific evidence source.
The engine is parameterised by the Phase 1 patient risk profile — the same
drug pair may fire differently for different patients based on their profile.

Architecture guarantee: rules are pure functions operating on structured data.
They are testable without network access, LLM calls, or FHIR servers.
"""

from rules.engine import evaluate_medication_safety
from rules.normalizer import normalize_medication
from rules.models import SafetyVerdict, SafetyFlag, PatientRiskProfile

__all__ = [
    "evaluate_medication_safety",
    "normalize_medication",
    "SafetyVerdict",
    "SafetyFlag",
    "PatientRiskProfile",
]
