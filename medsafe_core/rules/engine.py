"""
Deterministic medication safety evaluation engine (MedSafe Phase 2).

This is the safety-critical core. NO LLM calls. Every verdict traces to
a specific rule with a specific evidence source.

The engine receives:
  - A proposed medication (normalized to a drug class)
  - A patient risk profile (built by Phase 1 LLM)

It evaluates all applicable rules and returns a structured verdict with
flags, severity levels, and audit trail showing which profile fields
drove each decision.

Architecture guarantee: this module is a pure function of its inputs.
Given the same medication and profile, it always returns the same verdict.
"""

import json
from pathlib import Path
from functools import lru_cache

from medsafe_core.rules.models import (
    SafetyVerdict,
    SafetyFlag,
    PatientRiskProfile,
    Verdict,
    Severity,
    EvidenceLevel,
)


def evaluate_medication_safety(
    proposed_drug_classes: list[str],
    proposed_drug_name: str,
    proposed_drug_code: str | None,
    profile: PatientRiskProfile,
) -> SafetyVerdict:
    """
    Evaluate medication safety against all applicable rules.

    This is the single entry point for Phase 2. It:
    1. Loads all rule sets (interactions, renal dosing, Beers criteria)
    2. Evaluates each rule against the proposed drug + patient profile
    3. Collects all fired flags
    4. Determines the final verdict (highest severity wins)
    5. Returns structured output with audit trail

    Args:
        proposed_drug_classes: Pharmacological classes of the proposed drug
        proposed_drug_name: Human-readable name
        proposed_drug_code: dm+d or RxNorm code (if resolved)
        profile: Patient risk profile from Phase 1

    Returns:
        SafetyVerdict with verdict, flags, and audit info
    """
    flags: list[SafetyFlag] = []
    all_profile_fields: list[str] = []

    # Evaluate scope guards FIRST — short-circuit if out of scope.
    # These are deterministic blocks that the LLM cannot bypass via prompt drift.
    scope_flags = _evaluate_scope_guards(profile)
    if scope_flags:
        return SafetyVerdict(
            proposed_medication=proposed_drug_name,
            proposed_medication_code=proposed_drug_code,
            proposed_medication_class=proposed_drug_classes[0] if proposed_drug_classes else None,
            verdict=Verdict.BLOCK,
            flags=scope_flags,
            requires_override_reason=True,
            profile_fields_consulted=["demographics.age"],
        )

    # Evaluate interaction rules
    interaction_flags = _evaluate_interaction_rules(proposed_drug_classes, profile)
    flags.extend(interaction_flags)

    # Evaluate renal dosing rules
    renal_flags = _evaluate_renal_rules(proposed_drug_classes, profile)
    flags.extend(renal_flags)

    # Evaluate Beers criteria
    beers_flags = _evaluate_beers_criteria(proposed_drug_classes, profile)
    flags.extend(beers_flags)

    # Collect all profile fields consulted
    for flag in flags:
        all_profile_fields.extend(flag.profile_fields_consulted)

    # Determine final verdict (highest severity wins)
    verdict = _determine_verdict(flags)

    return SafetyVerdict(
        proposed_medication=proposed_drug_name,
        proposed_medication_code=proposed_drug_code,
        proposed_medication_class=proposed_drug_classes[0] if proposed_drug_classes else None,
        verdict=verdict,
        flags=flags,
        requires_override_reason=verdict in (Verdict.BLOCK, Verdict.WARN_OVERRIDE_REQUIRED),
        profile_fields_consulted=list(set(all_profile_fields)),
    )


def _evaluate_scope_guards(profile: PatientRiskProfile) -> list[SafetyFlag]:
    """
    Deterministic scope-limit guards. Short-circuits evaluation when the
    patient is outside SignalLoop's design scope (adult renal safety).

    These fire a CONTRAINDICATED + ESTABLISHED flag, which maps to a BLOCK
    verdict via the severity matrix. The LLM cannot bypass this — any
    downstream prompt drift will still see BLOCK and the requires_override_reason
    flag set to True.
    """
    flags: list[SafetyFlag] = []

    # Pediatric guard (under 18)
    if profile.age is not None and profile.age < 18:
        flags.append(SafetyFlag(
            rule_id="pediatric-out-of-scope",
            flag_type="scope_limitation",
            severity=Severity.CONTRAINDICATED,
            evidence_level=EvidenceLevel.ESTABLISHED,
            reason=(
                f"Patient is {profile.age} years old. SignalLoop's rule set is "
                f"designed for adult medication safety. Pediatric prescribing "
                f"requires weight-based dosing and age-specific guidelines "
                f"outside this tool's coverage. Please consult a pediatric "
                f"clinical decision support tool."
            ),
            citation="SignalLoop scope declaration — adult-focused rule set",
            profile_fields_consulted=["demographics.age"],
        ))

    return flags


def _evaluate_interaction_rules(
    proposed_classes: list[str],
    profile: PatientRiskProfile,
) -> list[SafetyFlag]:
    """Evaluate drug-drug and drug-condition interaction rules."""
    rules = _load_interaction_rules()
    flags = []

    for rule in rules:
        rule_drug_class = rule["proposed_drug_class"]

        # Check if this rule applies to the proposed drug
        if rule_drug_class not in proposed_classes:
            continue

        # Evaluate the rule's condition against the profile
        condition = rule["condition"]
        fired, fields_consulted, context_values = _evaluate_condition(condition, profile)

        if fired:
            # Build the reason string with actual patient values
            reason = _render_reason(rule, profile, context_values)

            flags.append(SafetyFlag(
                rule_id=rule["rule_id"],
                flag_type=rule.get("description", rule["rule_id"]),
                severity=Severity(rule["severity"]),
                evidence_level=EvidenceLevel(rule["evidence_level"]),
                reason=reason,
                citation=rule["citation"],
                profile_fields_consulted=fields_consulted,
            ))

    return flags


def _evaluate_renal_rules(
    proposed_classes: list[str],
    profile: PatientRiskProfile,
) -> list[SafetyFlag]:
    """Evaluate renal dosing threshold rules."""
    thresholds = _load_renal_dosing()
    flags = []
    egfr = profile.renal_function.latest_egfr

    if egfr is None:
        return flags

    for entry in thresholds:
        entry_class = entry["drug_class"]
        if entry_class not in proposed_classes:
            continue

        for rule in entry["rules"]:
            egfr_below = rule["egfr_below"]
            egfr_above = rule.get("egfr_above", 0)

            if egfr < egfr_below and egfr >= egfr_above:
                flags.append(SafetyFlag(
                    rule_id=f"renal-{entry_class.lower()}-egfr-{egfr_below}",
                    flag_type=f"renal_dosing_{rule['action']}",
                    severity=Severity(rule["severity"]),
                    evidence_level=EvidenceLevel.ESTABLISHED,
                    reason=f"{entry_class}: {rule['action']} at eGFR {egfr} (threshold: <{egfr_below})",
                    citation=rule["citation"],
                    profile_fields_consulted=["renal_function.latest_egfr"],
                ))
                break  # Only fire the most severe applicable threshold

    return flags


def _evaluate_beers_criteria(
    proposed_classes: list[str],
    profile: PatientRiskProfile,
) -> list[SafetyFlag]:
    """Evaluate Beers criteria for older adults."""
    if profile.age is None or profile.age < 65:
        return []

    criteria = _load_beers_criteria()
    flags = []

    for criterion in criteria:
        criterion_class = criterion["drug_class"]
        if criterion_class not in proposed_classes:
            continue

        flags.append(SafetyFlag(
            rule_id=criterion["rule_id"],
            flag_type="beers_criteria",
            severity=Severity(criterion["severity"]),
            evidence_level=EvidenceLevel.ESTABLISHED,
            reason=f"Age {profile.age} — Beers criteria: {criterion['rationale']}",
            citation="AGS Beers Criteria 2023, JAGS 2023;71(7):2052-2077",
            profile_fields_consulted=["demographics.age"],
        ))

    return flags


def _evaluate_condition(
    condition: dict,
    profile: PatientRiskProfile,
) -> tuple[bool, list[str], dict]:
    """
    Evaluate a rule condition against the patient profile.

    Returns: (fired: bool, fields_consulted: list, context_values: dict)
    """
    fields_consulted = []
    context_values = {}

    profile_field = condition.get("profile_field", "")

    # Numeric threshold conditions (eGFR, age, etc.)
    if "operator" in condition and "threshold" in condition:
        value = _get_profile_value(profile, profile_field)
        fields_consulted.append(profile_field)
        if value is None:
            return False, fields_consulted, context_values

        context_values["value"] = value
        threshold = condition["threshold"]
        op = condition["operator"]

        fired = _compare(value, op, threshold)

        # Check secondary condition if present
        if fired and "secondary_operator" in condition:
            secondary_threshold = condition["secondary_threshold"]
            fired = fired and _compare(value, condition["secondary_operator"], secondary_threshold)

        return fired, fields_consulted, context_values

    # Medication class presence conditions
    if "requires_classes" in condition:
        fields_consulted.append("active_medication_inventory")
        required_class_groups = condition["requires_classes"]
        patient_classes = set()
        for med in profile.active_medications:
            patient_classes.update(med.classes)

        all_satisfied = True
        for class_group in required_class_groups:
            # class_group can be "ACE_INHIBITOR|ARB" meaning either satisfies
            alternatives = class_group.split("|")
            if not any(alt in patient_classes for alt in alternatives):
                all_satisfied = False
                break
            else:
                # Record which specific med matched
                for med in profile.active_medications:
                    if any(alt in med.classes for alt in alternatives):
                        context_values[class_group] = med.name
                        break

        return all_satisfied, fields_consulted, context_values

    # Clinical context flag conditions
    if "contains" in condition:
        fields_consulted.append("clinical_context_flags")
        flag_value = condition["contains"]
        return flag_value in profile.clinical_context_flags, fields_consulted, context_values

    # Allergy conditions
    if "contains_substance" in condition:
        fields_consulted.append("allergy_profile")
        substance = condition["contains_substance"]
        for allergy in profile.allergies:
            if substance.lower() in allergy.substance.lower():
                return True, fields_consulted, context_values
        return False, fields_consulted, context_values

    if "contains_substance_class" in condition:
        fields_consulted.append("allergy_profile")
        substance_class = condition["contains_substance_class"]
        for allergy in profile.allergies:
            if allergy.substance_class and substance_class.lower() in allergy.substance_class.lower():
                return True, fields_consulted, context_values
        return False, fields_consulted, context_values

    return False, fields_consulted, context_values


def _render_reason(rule: dict, profile: PatientRiskProfile, context_values: dict) -> str:
    """Render the reason template with actual patient values."""
    template = rule.get("reason_template", rule.get("description", ""))

    replacements = {
        "egfr": str(profile.renal_function.latest_egfr or "unknown"),
        "age": str(profile.age or "unknown"),
        "ckd_stage": _egfr_to_ckd_stage(profile.renal_function.latest_egfr),
        "rate": str(profile.renal_function.rate_of_change_per_month or "unknown"),
    }

    # Add medication names from context
    for key, value in context_values.items():
        if "|" in key:
            clean_key = key.split("|")[0].lower() + "_name"
            replacements[clean_key] = str(value)
        # Common template variables
        replacements["ace_arb_name"] = context_values.get("ACE_INHIBITOR|ARB", "ACE-I/ARB")
        replacements["diuretic_name"] = context_values.get("DIURETIC", "diuretic")
        replacements["anticoagulant_name"] = context_values.get(
            "ANTICOAGULANT|VITAMIN_K_ANTAGONIST", "anticoagulant"
        )
        replacements["macrolide_name"] = context_values.get("MACROLIDE", "macrolide")
        replacements["statin_name"] = context_values.get("STATIN", "statin")

    # Simple template rendering
    result = template
    for key, value in replacements.items():
        result = result.replace(f"{{{key}}}", value)

    return result


def _determine_verdict(flags: list[SafetyFlag]) -> Verdict:
    """Determine overall verdict from collected flags using severity matrix."""
    if not flags:
        return Verdict.CLEAN

    # Map severity + evidence to verdict
    verdict_priority = {
        Verdict.BLOCK: 4,
        Verdict.WARN_OVERRIDE_REQUIRED: 3,
        Verdict.WARN: 2,
        Verdict.INFO: 1,
        Verdict.CLEAN: 0,
    }

    highest = Verdict.CLEAN
    for flag in flags:
        flag_verdict = _severity_to_verdict(flag.severity, flag.evidence_level)
        if verdict_priority[flag_verdict] > verdict_priority[highest]:
            highest = flag_verdict

    return highest


def _severity_to_verdict(severity: Severity, evidence: EvidenceLevel) -> Verdict:
    """Apply the severity matrix to determine verdict for a single flag."""
    matrix = {
        (Severity.CONTRAINDICATED, EvidenceLevel.ESTABLISHED): Verdict.BLOCK,
        (Severity.CONTRAINDICATED, EvidenceLevel.PROBABLE): Verdict.WARN_OVERRIDE_REQUIRED,
        (Severity.CONTRAINDICATED, EvidenceLevel.SUSPECTED): Verdict.WARN,
        (Severity.CONTRAINDICATED, EvidenceLevel.THEORETICAL): Verdict.INFO,
        (Severity.MAJOR, EvidenceLevel.ESTABLISHED): Verdict.WARN_OVERRIDE_REQUIRED,
        (Severity.MAJOR, EvidenceLevel.PROBABLE): Verdict.WARN,
        (Severity.MAJOR, EvidenceLevel.SUSPECTED): Verdict.INFO,
        (Severity.MAJOR, EvidenceLevel.THEORETICAL): Verdict.INFO,
        (Severity.MODERATE, EvidenceLevel.ESTABLISHED): Verdict.WARN,
        (Severity.MODERATE, EvidenceLevel.PROBABLE): Verdict.INFO,
        (Severity.MODERATE, EvidenceLevel.SUSPECTED): Verdict.INFO,
        (Severity.MODERATE, EvidenceLevel.THEORETICAL): Verdict.CLEAN,
        (Severity.MINOR, EvidenceLevel.ESTABLISHED): Verdict.INFO,
        (Severity.MINOR, EvidenceLevel.PROBABLE): Verdict.INFO,
        (Severity.MINOR, EvidenceLevel.SUSPECTED): Verdict.CLEAN,
        (Severity.MINOR, EvidenceLevel.THEORETICAL): Verdict.CLEAN,
    }
    return matrix.get((severity, evidence), Verdict.INFO)


def _get_profile_value(profile: PatientRiskProfile, field_path: str):
    """Navigate dotted field path on the profile model."""
    parts = field_path.split(".")
    obj = profile
    for part in parts:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            return None
    return obj


def _compare(value, operator: str, threshold) -> bool:
    """Compare a value against a threshold with the given operator."""
    if value is None:
        return False
    ops = {
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "==": lambda a, b: a == b,
    }
    return ops.get(operator, lambda a, b: False)(value, threshold)


def _egfr_to_ckd_stage(egfr: float | None) -> str:
    """Convert eGFR to CKD stage string."""
    if egfr is None:
        return "unknown"
    if egfr >= 90:
        return "1"
    if egfr >= 60:
        return "2"
    if egfr >= 45:
        return "3a"
    if egfr >= 30:
        return "3b"
    if egfr >= 15:
        return "4"
    return "5"


# --- Data loading (cached) ---

@lru_cache(maxsize=1)
def _load_interaction_rules() -> list[dict]:
    path = Path(__file__).parent / "data" / "interaction_rules.json"
    with open(path) as f:
        data = json.load(f)
    return data["rules"]


@lru_cache(maxsize=1)
def _load_renal_dosing() -> list[dict]:
    path = Path(__file__).parent / "data" / "renal_dosing.json"
    with open(path) as f:
        data = json.load(f)
    return data["thresholds"]


@lru_cache(maxsize=1)
def _load_beers_criteria() -> list[dict]:
    path = Path(__file__).parent / "data" / "beers_criteria.json"
    with open(path) as f:
        data = json.load(f)
    return data["criteria"]
