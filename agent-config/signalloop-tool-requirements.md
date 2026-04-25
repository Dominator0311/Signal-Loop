# SignalLoop Tool Requirements (for Workstream A)

> **Audience:** Workstream A (MedSafe MCP expansion). Workstream B (SignalLoop redesign) is content-only and cannot implement these tools — this document is the contract.
> **Status:** All but one of these tools are already in Workstream A's planned scope per `IMPROVEMENT-PLAN.md`. The new ask is `SurfacePatientAttention` (composite, Scenario 1) and a small extension to `LogAuditEvent` for Scenario 4.
> **Hard rule:** every rule entry cites its clinical source verbatim. No invented rules. If unsure, mark `verification_required: true` rather than fabricate.

---

## 1. SurfacePatientAttention (NEW — Scenario 1's wow tool)

**Type:** Composite (orchestrates existing primitives, no new clinical logic).
**Owner module:** `signalloop-medsafe-mcp/tools/phase1.py` (alongside `BuildPatientRiskProfile`) OR a new `tools/surveillance.py` if cleaner.
**MCP name:** `SurfacePatientAttention`
**MCP description:**
> "Surface what needs the clinician's attention for a patient — runs trend, full medication review, and consult discovery in parallel and returns a prioritised list of 1–5 attention items with reasoning. Use when the clinician asks an open-ended question like 'what needs my attention' or 'brief me' with no specific drug or task in scope."

### Inputs
```python
async def surface_patient_attention(
    patientId: Annotated[str | None, Field(description="Patient ID; falls back to FHIR context")] = None,
    max_items: Annotated[int, Field(description="Max attention items to return (1-5)", ge=1, le=5)] = 5,
    ctx: Context = None,
) -> str:
    ...
```

### Internal orchestration
```
1. Resolve patientId from FHIR context if not supplied (existing pattern).
2. Call build_patient_risk_profile(patientId, ctx) — produces PatientRiskProfile.
3. Call get_renal_trend(patientId, "62238-1", ctx) — eGFR trajectory + rate of change.
4. Call run_full_medication_review(profile, ctx) — re-evaluates every active medication
   against the current profile. Aggregates per-drug verdicts (BLOCK / WARN / CLEAN).
5. Call extract_consult_recommendations(patientId, ctx) — auto-discovers latest unactioned
   DocumentReference (LOINC 11488-4) within last 90 days; returns count + summary if present.
   Skip if no unactioned consult exists (do not error).
6. Aggregate into AttentionItem list (see schema below); rank; return top max_items.
```

### Output schema (Pydantic)

```python
@dataclass(frozen=True)
class AttentionItem:
    category: Literal["trend", "drug_safety", "open_consult", "overdue_task"]
    severity: Literal["BLOCK", "WARN", "INFO"]
    headline: str               # one-line, e.g. "eGFR 52 → 42 over 5 months"
    rationale: str              # one-sentence clinical reasoning
    citation: str               # NICE/BNF/Beers/STOPP-START reference, verbatim
    profile_fields_consulted: list[str]
    rule_id: str | None         # for drug_safety items, the firing rule_id
    related_resource_ids: list[str]  # FHIR IDs feeding this item

@dataclass(frozen=True)
class AttentionResponse:
    patient_id: str
    items: list[AttentionItem]   # length 0..max_items
    summary_line: str            # e.g. "Margaret Henderson, 72F — 3 items need your attention."
    profile_cache_ts: str        # ISO timestamp of profile cache
```

### Ranking rule (deterministic — no LLM)
1. category=`drug_safety` with severity=`BLOCK` (e.g., "triple whammy" retrospective flag).
2. category=`open_consult` with `unactioned_count > 0` (loop closure is high-value).
3. category=`drug_safety` with severity=`WARN`.
4. category=`trend` with `rate_of_decline > 5 mL/min/year` (NICE NG203 §1.5.5 threshold).
5. category=`overdue_task` with `days_overdue > 0`.
Items below threshold are dropped (no `INFO`-only items unless nothing else fires).

### Acceptance
- For Margaret Henderson, returns at minimum: trend (rate -2 mL/min/month), drug_safety BLOCK on ibuprofen, open_consult with 7 unactioned recs.
- For James Okonkwo (healthy 42M), returns 0 items and `summary_line = "James Okonkwo, 42M — no attention items."`.
- Test fixtures using existing patient bundles in `fhir-bundles/`.

---

## 2. RunFullMedicationReview (already in Workstream A scope — clarification)

The existing `IMPROVEMENT-PLAN.md` lists this as a composite in row 7 of the new tools table. Confirming the Scenario-1 dependency:

- It must accept `profile: PatientRiskProfile` (from `BuildPatientRiskProfile`).
- It must iterate every `active_medication` and call: `CheckRenalDoseAdjustment`, `CheckBeersCriteria`, `CheckSTOPPSTART`, `CheckDrugDrugInteraction` (against every other active med), and the existing `CheckMedicationSafety`.
- It returns a list of per-drug verdicts (`{drug, verdict, flags[]}`).
- `SurfacePatientAttention` consumes its output to populate `category=drug_safety` items.

No new spec required; just calling it out as an upstream dependency.

---

## 3. LogAuditEvent — extend to support read/query (Scenario 4)

The existing tool writes AuditEvents. Scenario 4 needs to **read** them too.

### Option A (preferred — minimal change)
Add a `query` mode to the existing tool:

```python
async def log_audit_event(
    *,
    query: bool = False,
    # existing write params...
    patient_id: str | None = None,
    action: str | None = None,
    drug: str | None = None,
    since: str | None = None,  # ISO date
    ctx: Context = None,
) -> str:
    if query:
        # GET AuditEvent?patient=X&action=Y&date=geZ
        # return list of AuditEvent payloads as JSON string
    else:
        # existing write path
```

### Option B (cleaner — separate tool)
Add a sibling `QueryAuditEvent` tool. Lower coupling, but adds a tool to the count (we want to stay at 10 max — see `IMPROVEMENT-PLAN.md` §11.2).

**Recommendation:** Option A. Avoids tool-count creep.

**Anti-pattern note (from memory feedback file):** the parameter `query: bool = False` is verb-y. LLMs pass `True` to optional bools with verb-y names. Either rename to `mode: Literal["read", "write"]` or split into two tools. If splitting, `QueryAuditEvent` is the cleaner name.

---

## 4. ExplainContraindication (already in Workstream A scope — clarification)

Existing plan row 6: "Given a SafetyVerdict, produce a patient-friendly natural-language explanation."

Scenario 4 needs a slight extension: it must accept an `AuditEvent` payload (which contains the original verdict + the override rationale + the monitoring task IDs) and produce a **clinician-facing replay**, not patient-facing. Two-mode:

```python
async def explain_contraindication(
    verdict: SafetyVerdict | dict,
    audience: Literal["patient", "clinician_audit"] = "patient",
    audit_payload: dict | None = None,
    ctx: Context = None,
) -> str:
    ...
```

When `audience="clinician_audit"`, the prompt template reframes the explanation as a structured replay (original verdict / override rationale / monitoring outcome / citation). The Pydantic structured-output schema captures these four fields.

---

## 5. ReconcileRecommendations vs DetectPlanConflicts (clarification, not new tool)

The existing tool list has `DetectPlanConflicts` (registered in `server.py`). Scenarios 1 and 2 both reference `ReconcileRecommendations` — that's the same tool, possibly renamed. Workstream A: keep one tool, choose the name that better reflects what it does (it produces an agreed/switch/conflict/pending map, so `ReconcileRecommendations` is more accurate than `DetectPlanConflicts`).

If renaming, update `server.py` registration and the system prompt's tool list. The current SignalLoop system prompt references both names so it works either way.

---

## 6. Switch-vs-dual-RAAS detection — already exists, surface it explicitly

Per `SignalLoop-Handover.md` §12 line 551: `tools/referral.py` has `CONFLICT_DETECTION_SYSTEM` (rewritten for switch handling). Scenario 2 depends on this prompt's correct behaviour.

**Ask of Workstream A (NOT a new tool, a verification):**
- Confirm `CONFLICT_DETECTION_SYSTEM` returns a structured field like `classification: "switch" | "dual_blockade" | "agreed" | "conflict"` for each recommendation.
- Confirm the detector cites NICE NG203 §1.6 verbatim when classifying as `switch` or `dual_blockade`.
- If the current implementation only returns free text, add a structured output Pydantic schema so the SignalLoop agent can render the classification deterministically rather than re-parsing prose.

---

## Full list of dependencies the system prompt references

For Workstream A's checklist — every tool the SignalLoop system prompt mentions by name:

**Existing (must remain functional):**
- `BuildPatientRiskProfile`, `RefreshPatientRiskProfile`, `GetRenalTrend`, `GetRelevantContext`
- `NormalizeMedication`, `CheckMedicationSafety`, `CheckRenalSafety` (alias?)
- `SynthesiseSafetyResponse`, `AnalyseOverrideReason`
- `IngestConsultLetter`, `ExtractConsultRecommendations`, `ReconcileRecommendations` / `DetectPlanConflicts`
- `AssembleSpecialtyPacket`, `RankSpecialistDestinations`
- `DraftMedicationRequest`, `DraftServiceRequest`, `DraftFollowupTask`
- `LogAuditEvent`, `LogOverride`

**New (per `IMPROVEMENT-PLAN.md` Workstream A):**
- `CheckRenalDoseAdjustment`
- `CheckSTOPPSTART`
- `CheckBeersCriteria`
- `CheckDrugDrugInteraction`
- `SuggestAlternative`
- `ExplainContraindication` (with `audience` parameter)
- `RunFullMedicationReview`

**New (this document — Workstream B's ask):**
- `SurfacePatientAttention` (composite)

**Modifications:**
- `LogAuditEvent` — add read/query mode (or sibling `QueryAuditEvent`).
- `ExplainContraindication` — add `audience` parameter.
- `ReconcileRecommendations` / `DetectPlanConflicts` — pick one name, structured output for switch classification.

---

## Notes on `CheckRenalSafety` vs `CheckMedicationSafety`

The system prompt and demo script use `CheckRenalSafety` for Scenario 3. The existing tool is `CheckMedicationSafety`. They may be the same tool (renal-focused rule set) or `CheckRenalSafety` may be a thin alias. Workstream A: confirm which name is canonical and update the system prompt's tool list if needed. Either name works — the system prompt should match what's registered in `server.py`.

---

## Sequencing note

`SurfacePatientAttention` depends on `RunFullMedicationReview` and the four new rule tools. Build order in Workstream A:
1. Rule tools (CheckRenalDoseAdjustment, CheckBeersCriteria, CheckSTOPPSTART, CheckDrugDrugInteraction).
2. `RunFullMedicationReview` (composite over the rule tools).
3. `SurfacePatientAttention` (composite over `RunFullMedicationReview` + existing trend/consult tools).
4. LLM tools (`SuggestAlternative`, `ExplainContraindication`).

If Workstream A is bandwidth-constrained, the priority for Scenario 1 to function is: `CheckBeersCriteria` + `CheckDrugDrugInteraction` + `RunFullMedicationReview` + `SurfacePatientAttention`. The renal-dose and STOPP/START tools strengthen Scenarios 1 and 3 but are not strictly blocking.
