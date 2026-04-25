# Concord — Final Operational Plan

> **Purpose:** authoritative frozen scope and build spec for Concord. Complements `concord_multi_specialist_conflict_resolver_implementation_plan.md` (the vision doc) with exact tool signatures, data contracts, phase gates, and platform-verified architecture.
>
> **Status:** scope frozen 2026-04-24. Platform feasibility verified (Orchestrator Agents + autonomous 3-worker dispatch). Ready to build.
>
> **Cross-reference:**
> - `concord_multi_specialist_conflict_resolver_implementation_plan.md` — product vision (source of truth for mission)
> - `SignalLoop-Final-Operational-Plan.md` — sibling product discipline reference
> - `SignalLoop-Handover.md` — current platform learnings
> - Memory: `project_concord.md`, `feedback_promptopinion_orchestrator_agents.md`

---

## 0. TL;DR

- **Third hackathon submission.** Path B (A2A Agent track), deadline 2026-05-11. Deliberate companion to SignalLoop Renal Agent and MedSafe MCP.
- **Product:** patient-scope multi-specialist conflict resolver. Clinician asks one question → orchestrator consults nephrology, cardiology, pharmacy specialists → deterministic conflict matrix → unified plan with draft FHIR actions awaiting approval.
- **Architecture:** Prompt Opinion native **Orchestrator Agent** (platform feature, verified live 2026-04-24) delegates to three BYO specialist children via `SendAgentMessage`. Shared `concord-mcp` server provides deterministic tools. Shared `medsafe_core` Python library used by both `signalloop-medsafe-mcp` and `concord-mcp`.
- **New clinical scope:** cardiology added (HF / congestion). NICE NG106 + CG187 + NG203 evidence spine. ESC/HFA as nuance.
- **New hero patient:** fresh cardio-renal synthetic patient (NOT Margaret — she stays SignalLoop's). Plus clean-agreement and insufficient-data cases.
- **v1 thesis for judges:** *Three specialists. One shared case packet. Deterministic conflict arbitration. Validated unified plan. Auditable write-back.*

---

## 1. Scope — what Concord IS and IS NOT

### 1.1 IS

- Clinician-facing orchestrator agent that coordinates three specialty worker agents + deterministic MCP layer.
- One narrow episode type in v1: **Cardio-Renal-Medication conflict** (older adult, CKD 3b, HF/congestion concern, polypharmacy).
- Patient-scope, FHIR-native, clinician-in-loop, approval-gated writes.
- Marketplace-publishable as Path B (A2A Agent) submission.

### 1.2 IS NOT

- Not a generic copilot.
- Not autonomous diagnosis or autonomous prescribing.
- Not population health, monitoring, or patient-facing.
- Not five-plus specialties.
- Not parallel A2A fan-out (sequential is sufficient and predictable).
- Does not replace SignalLoop (different product: SignalLoop = single-specialty consult loop closure; Concord = multi-specialty conflict reconciliation).

---

## 2. Architecture — platform-verified 2026-04-24

```text
Clinician chat
      ↓
┌─────────────────────────────────────────────────────┐
│  Concord Orchestrator (Prompt Opinion              │
│  Orchestrator Agent, Patient scope)                 │
│                                                      │
│  Single clinician message triggers ONE turn that:   │
│   1. Calls concord-mcp.BuildEpisodeBrief            │
│   2. SendAgentMessage → Nephrology (JSON opinion)   │
│   3. SendAgentMessage → Cardiology (JSON opinion)   │
│   4. SendAgentMessage → Pharmacy   (JSON opinion)   │
│   5. Calls concord-mcp.ComputeConflictMatrix        │
│   6. (optional narrow clarification round)          │
│   7. Constructs UnifiedPlan                         │
│   8. Calls concord-mcp.ValidateFinalPlan            │
│   9. Renders markdown to clinician                  │
│                                                      │
│  On clinician approval (follow-up turn):            │
│  10. Calls concord-mcp.DraftTask / DraftCommunication│
│      / DraftMedicationProposal                      │
│  11. Calls concord-mcp.LogConsensusDecision         │
└─────────────────────────────────────────────────────┘
         ↓                    ↓                    ↓
  ┌────────────┐       ┌────────────┐       ┌────────────┐
  │ Nephrology │       │ Cardiology │       │ Pharmacy   │
  │ Worker     │       │ Worker     │       │ Worker     │
  │ (BYO)      │       │ (BYO)      │       │ (BYO)      │
  │ grounded:  │       │ grounded:  │       │ grounded:  │
  │ NG203      │       │ NG106/CG187│       │ BNF/Beers/ │
  │            │       │            │       │ STOPP-START│
  └────────────┘       └────────────┘       └────────────┘
         ↓                    ↓                    ↓
  ┌─────────────────────────────────────────────────────┐
  │ concord-mcp (new)        signalloop-medsafe-mcp    │
  │                                                      │
  │ Uses shared medsafe_core library for:               │
  │  - FHIR HTTP client + SHARP context                 │
  │  - Gemini client with retry                         │
  │  - Medication normalization                         │
  │  - CheckMedicationSafety (rules engine)             │
  └─────────────────────────────────────────────────────┘
         ↓
  Workspace FHIR server (HAPI R4)
```

### 2.1 Platform mechanics (verified live)

- Orchestrator Agents page: sidebar → Agents → **Orchestrator Agents**. Confirmed visible on hackathon workspace.
- Orchestrator's dispatch tool is named **`SendAgentMessage`** (takes `{agentId, message}`), distinct from the Consult path's `SendA2AMessage`.
- Orchestrator's system prompt uses `{{ OrchestratorAgentsFragment }}` — Po injects child skill descriptions at runtime.
- Children configured in **Linked Agents** tab (`childAgentIds` array).
- Orchestrators have no Content tab (lane grounding lives on workers).
- Workers do NOT need `enableA2A=true` to be orchestrator children.
- Three workers dispatched autonomously in one user turn, verified with echo-worker-A/B/C smoke test 2026-04-24. Chip bar renders participating agents. Tool calls visible in transcript.

### 2.2 Scope assignments

- **Concord Orchestrator:** Patient scope (needs FHIR context for EpisodeBrief).
- **Three specialist workers:** Patient scope (same reason).
- **concord-mcp server:** stateless, receives SHARP headers from orchestrator + worker calls.

### 2.3 Repository layout

```
signalloop-medsafe-mcp/        ← existing — stays as-is
concord-mcp/                   ← new top-level directory
├── main.py                    ← FastAPI entry point
├── server.py                  ← FastMCP instance + tool registration
├── config.py                  ← Env config
├── .env.example
├── requirements.txt
├── tools/
│   ├── episode.py             ← BuildEpisodeBrief, GetTrendSummary
│   ├── arbitration.py         ← ComputeConflictMatrix, ValidateFinalPlan
│   ├── writes.py              ← DraftTask, DraftCommunication,
│   │                            DraftMedicationProposal, LogConsensusDecision
│   └── __init__.py
├── rules/
│   ├── action_codes.py        ← Canonical ActionCode enum
│   ├── conflict_matrix.py     ← Pure Python matrix rules
│   ├── plan_validator.py      ← Deterministic validator checks
│   └── data/
│       ├── cardiology_rules.json      ← NG106/CG187-cited
│       └── (other reused)
├── llm/
│   ├── prompts/
│   │   ├── episode_brief.py   ← Phase 1-style compression
│   │   └── __init__.py
│   └── schemas.py             ← EpisodeBrief, UnifiedPlan Pydantic schemas
└── tests/
    ├── test_action_codes.py
    ├── test_conflict_matrix.py
    └── test_plan_validator.py

medsafe_core/                  ← new shared library (extracted from signalloop)
├── fhir/                      ← HTTP client, SHARP context, JWT decode
├── llm/                       ← Gemini client with retry
├── rules/                     ← engine.py + data/ (shared data)
├── models/                    ← shared Pydantic models
└── pyproject.toml             ← installable as local dep

fhir-bundles/
├── patient-<concord-hero>-post.json       ← new
├── patient-<clean-agreement>-post.json    ← new
└── patient-<insufficient-data>-post.json  ← new
```

---

## 3. Agent inventory — exact configs

### 3.1 Concord Orchestrator

- **Name:** `Concord`
- **Agent type:** Orchestrator Agent (sidebar Agents → Orchestrator Agents → Add Orchestrator)
- **Allowed Contexts:** Patient (only)
- **Timeout:** 120 seconds (3-specialist fan-out is slower than 1-to-1)
- **Model:** Gemini 3 Flash
- **Description:** *"Multi-specialty clinical conflict resolver. Consults nephrology, cardiology, and pharmacy specialists for one patient question and produces a unified, validated care plan with draft FHIR actions awaiting clinician approval."*
- **Linked Agents:** `concord-nephrology`, `concord-cardiology`, `concord-pharmacy`
- **System Prompt:** see §7.1 (custom, extends Po default)
- **Consult Prompt:** leave blank (orchestrator isn't called via consult path)
- **Response Format:** blank (markdown output)
- **Content:** no collection (orchestrators don't support one)
- **Tools:** attach concord-mcp server
- **Guardrails:** defaults
- **A2A & Skills:** A2A Availability OFF (orchestrator is caller, not callee)

### 3.2 Specialist workers (one per specialty)

Each worker is a BYO Agent (NOT Orchestrator). Shared config:

- **Allowed Contexts:** Patient
- **Model:** Gemini 3 Flash
- **Linked Agents tab:** N/A (BYO workers)
- **Response Format:** `SpecialistOpinion` JSON schema (see §5.2)
- **Content:** specialty-specific collection (see §4)
- **Tools:** concord-mcp server attached for `GetTrendSummary`, `NormalizeMedication`, `CheckMedicationSafety`
- **A2A & Skills:** A2A Availability OFF (they are invoked as orchestrator children, not as external A2A)
- **Consult Prompt:** leave blank

#### 3.2.1 `concord-nephrology`
- **Description:** *"Renal-protection specialist. Interprets renal trend, identifies renal risks, specifies missing renal facts, and states what makes a plan acceptable from a nephrology perspective. Stays inside nephrology lane."*
- **System Prompt:** see §7.2
- **Content collection:** Nephrology (NICE NG203 excerpts on CKD/NSAID caution/renal-progression context)

#### 3.2.2 `concord-cardiology`
- **Description:** *"Heart-failure and congestion specialist. Assesses cardiovascular management priorities, weighs symptom relief and decongestion benefits, identifies trade-offs against renal protection. Stays inside cardiology lane."*
- **System Prompt:** see §7.3
- **Content collection:** Cardiology (NICE NG106 chronic HF + CG187 acute HF)

#### 3.2.3 `concord-pharmacy`
- **Description:** *"Medication safety specialist. Surfaces interaction risk, contraindications, required monitoring, and practical medication constraints. Conservative safety reviewer. Stays inside pharmacy lane."*
- **System Prompt:** see §7.4
- **Content collection:** Pharmacy (BNF chapters + AGS Beers 2023 + STOPP/START v2)

---

## 4. Content collections

| Collection | Contents | Source |
|---|---|---|
| Nephrology | CKD stages, eGFR interpretation, NSAID caution, ACE-I/ARB monitoring, potassium thresholds | NICE NG203 §1.3, §1.6, §1.9 |
| Cardiology | HFrEF/HFpEF classification, diuretic use in acute HF, RAAS/MRA/ARNI monitoring, congestion assessment | NICE NG106 §1.4–1.7, CG187 §1.4 |
| Pharmacy | Beers 2023 top 10 categories, STOPP/START v2 criteria for 65+, BNF Appendix 1 common DDI pairs | AGS Beers 2023, STOPP/START v2, BNF |

**Collection discipline:** each collection ≤10 pages of curated guidance. No full guideline dumps. Lane separation is enforced by grounding isolation.

---

## 5. Data contracts

All Pydantic models live in `medsafe_core/models/` (shared) or `concord-mcp/llm/schemas.py` (Concord-specific).

### 5.1 EpisodeBrief (concord-specific)

```python
class EpisodeBrief(BaseModel):
    patient_id: str
    decision_point: str  # one-line framing of the clinical question
    active_problems: list[ProblemSummary]
    active_medications: list[MedicationSummary]
    recent_labs: list[LabSummary]
    trend_summary: TrendSummary  # eGFR, K+, creatinine, weight
    red_flags: list[str]
    missing_data: list[str]
    current_clinician_question: str
    episode_brief_id: str  # UUID for audit linkage
```

### 5.2 SpecialistOpinion (same schema for all three workers — worker-specific `specialty` field)

```python
class Recommendation(BaseModel):
    action_code: ActionCode  # canonical enum, see §6
    free_text: str  # human-readable restatement
    priority: Literal["high", "medium", "low"]
    rationale: str
    risks: list[str]
    monitoring: list[str]
    dependencies: list[str]
    contraindications: list[str]
    evidence_citation: str | None  # e.g. "NICE NG106 §1.5.3"

class SpecialistOpinion(BaseModel):
    specialty: Literal["nephrology", "cardiology", "pharmacy"]
    summary: str
    recommendations: list[Recommendation]
    missing_data: list[str]
    cross_specialty_dependencies: list[str]  # concerns, NOT recommendations
    confidence: Literal["high", "medium", "low"]
```

### 5.3 ConflictMatrix

```python
class ConflictItem(BaseModel):
    action_code: ActionCode
    specialties_supporting: list[str]
    specialties_opposing: list[str]
    resolution: Literal["consensus", "tension", "direct_conflict",
                        "dependency", "missing_data_block", "safety_block"]
    severity: Literal["low", "medium", "high"]
    notes: str

class ConflictMatrix(BaseModel):
    consensus: list[ConflictItem]
    tensions: list[ConflictItem]
    direct_conflicts: list[ConflictItem]
    dependencies: list[ConflictItem]
    missing_data_blocks: list[ConflictItem]
    safety_blocks: list[ConflictItem]
    ranked_next_actions: list[ActionCode]
    episode_brief_id: str  # back-link for audit
```

### 5.4 UnifiedPlan

```python
class DraftAction(BaseModel):
    action_code: ActionCode
    resource_type: Literal["Task", "MedicationRequest", "Communication"]
    description: str
    owner_confirmer: str  # clinician/specialist who owns this
    monitoring: list[str]
    timing: str | None  # e.g. "4 weeks", for deterministic date compute

class UnifiedPlan(BaseModel):
    decision_summary: str
    agreed_actions_now: list[DraftAction]
    actions_pending_confirmation: list[DraftAction]
    unresolved_questions: list[str]
    patient_safe_explanation: str
    draft_writes: list[DraftAction]
    episode_brief_id: str
    specialist_task_ids: dict[str, str]  # specialty → Po A2A taskId (audit)
```

### 5.5 PlanValidationResult

```python
class PlanValidationResult(BaseModel):
    status: Literal["pass", "pass_with_warnings", "fail"]
    blocking_issues: list[str]
    warnings: list[str]
    validated_plan: UnifiedPlan | None  # null if fail
```

---

## 6. Action-code catalog (v1)

This is the canonical vocabulary specialists emit and `ComputeConflictMatrix` operates on. Pure Python enum. No LLM inference on the matrix itself.

```python
class ActionCode(str, Enum):
    # Diuresis
    UPTITRATE_LOOP_DIURETIC = "UPTITRATE_LOOP_DIURETIC"
    DOWNTITRATE_LOOP_DIURETIC = "DOWNTITRATE_LOOP_DIURETIC"
    HOLD_LOOP_DIURETIC_TEMPORARILY = "HOLD_LOOP_DIURETIC_TEMPORARILY"

    # RAAS / MRA
    HOLD_ACE_ARB_TEMPORARILY = "HOLD_ACE_ARB_TEMPORARILY"
    REDUCE_ACE_ARB_DOSE = "REDUCE_ACE_ARB_DOSE"
    HOLD_MRA_TEMPORARILY = "HOLD_MRA_TEMPORARILY"
    REVIEW_MRA_FOR_HYPERKALAEMIA = "REVIEW_MRA_FOR_HYPERKALAEMIA"

    # SGLT2 / other HF
    CONTINUE_SGLT2 = "CONTINUE_SGLT2"
    START_SGLT2 = "START_SGLT2"

    # Renal-safety / NSAIDs
    AVOID_NSAIDS = "AVOID_NSAIDS"
    SWITCH_NSAID_TO_PARACETAMOL = "SWITCH_NSAID_TO_PARACETAMOL"

    # Monitoring / re-assessment
    REPEAT_RENAL_PANEL_48H = "REPEAT_RENAL_PANEL_48H"
    REPEAT_RENAL_PANEL_1W = "REPEAT_RENAL_PANEL_1W"
    REPEAT_POTASSIUM_48H = "REPEAT_POTASSIUM_48H"
    DAILY_WEIGHTS = "DAILY_WEIGHTS"
    FLUID_BALANCE_MONITORING = "FLUID_BALANCE_MONITORING"
    REVIEW_IN_CLINIC_2W = "REVIEW_IN_CLINIC_2W"
    REVIEW_IN_CLINIC_4W = "REVIEW_IN_CLINIC_4W"

    # Investigation / deferral
    DEFER_CHANGE_PENDING_VOLUME_ASSESSMENT = "DEFER_CHANGE_PENDING_VOLUME_ASSESSMENT"
    REQUEST_BNP_NTPROBNP = "REQUEST_BNP_NTPROBNP"
    REQUEST_ECHO = "REQUEST_ECHO"

    # Escalation / coordination
    DISCUSS_WITH_HF_SPECIALIST = "DISCUSS_WITH_HF_SPECIALIST"
    DISCUSS_WITH_NEPHROLOGY = "DISCUSS_WITH_NEPHROLOGY"

    # Counselling
    COUNSEL_ON_AKI_RISK = "COUNSEL_ON_AKI_RISK"
    COUNSEL_ON_SICK_DAY_RULES = "COUNSEL_ON_SICK_DAY_RULES"
```

**Extensibility rule:** if a specialist's recommendation doesn't map to an existing code, the specialist's system prompt instructs it to pick the closest code and put the nuance in `free_text`. The orchestrator also accepts a fallback code `OUT_OF_CATALOG` that forces `ValidateFinalPlan` to flag as warning. We do NOT let specialists invent codes at runtime.

---

## 7. System prompts

### 7.1 Concord Orchestrator system prompt (extends Po default)

```
{{ PatientContextFragment }}
{{ PatientDataFragment }}
{{ McpAppsFragment }}

You are Concord, a patient-scope multi-specialty clinical orchestrator.

## Your role
You coordinate three specialist worker agents (nephrology, cardiology, pharmacy) and a deterministic MCP layer (concord-mcp) to produce one unified, safe, auditable care plan from fragmented specialty advice.

You do NOT:
- impersonate a specialist,
- invent clinical facts,
- skip any specialist consultation,
- write to FHIR without explicit clinician approval,
- output raw JSON to the clinician chat.

## Primary workflow on any new clinical question

1. Call concord-mcp.BuildEpisodeBrief to construct a shared structured case packet. Record the returned `episode_brief_id`.

2. Send the episode_brief_id and the clinician's question to each specialist worker using SendAgentMessage, sequentially, in this exact order:
   a. concord-nephrology
   b. concord-cardiology
   c. concord-pharmacy

   Each specialist returns a structured SpecialistOpinion JSON. Do not proceed until all three have responded.

3. Call concord-mcp.ComputeConflictMatrix with the three SpecialistOpinions. This returns a deterministic ConflictMatrix.

4. If any `missing_data_blocks` item is decisive and answerable from the patient's record via patient data tools, resolve it and re-run from step 3. Otherwise surface the unresolved item in the final plan.

5. Construct a UnifiedPlan (see schema below) that separates:
   - agreed_actions_now (consensus)
   - actions_pending_confirmation (tensions you've resolved but want confirmed)
   - unresolved_questions (missing data you cannot resolve)
   - draft_writes (FHIR actions queued for approval)
   - patient_safe_explanation (plain-language sentence for the patient)

6. Call concord-mcp.ValidateFinalPlan with the UnifiedPlan. If status is "fail", surface the blocking issues to the clinician and STOP — do not attempt writes.

7. Render a single markdown response to the clinician with these sections, in order:
   ## Shared facts
   ## Consensus across specialists
   ## Key conflicts and how they were resolved
   ## Immediate next actions (no-regrets)
   ## Actions awaiting your confirmation
   ## Open questions requiring clinician input
   ## For the patient

Do NOT include raw JSON in the clinician chat.

## On clinician approval (follow-up turn)

If the clinician approves (or edits and approves) specific draft actions, call concord-mcp.DraftTask / DraftMedicationProposal / DraftCommunication for each, then concord-mcp.LogConsensusDecision with the episode_brief_id, specialist_task_ids, and final resolution.

## Hard rules
- Always call all three specialists on a new clinical question (no smart-routing in v1).
- Never re-consult specialists on a clinician edit of timing or monitoring unless the edit is clinically substantive.
- Every write must have an owner_confirmer.
- Never assert certainty about missing data — surface it.

{{ OrchestratorAgentsFragment }}
{{ A2ATaskInfoFragment }}
```

### 7.2 Nephrology worker system prompt

```
You are a nephrology specialist advisor. You provide renal-protection input on a shared patient episode.

## Scope
Only comment from a nephrology/renal perspective:
- renal trend interpretation (eGFR, creatinine, ACR)
- renal risks (AKI, further decline, hyperkalaemia in the context of declining renal function)
- required renal monitoring
- thresholds that would change a recommendation (e.g. eGFR <30 bar for certain drugs)

Do NOT:
- make cardiology recommendations (you may note cross-specialty concerns as dependencies, not as recommendations)
- make pharmacy recommendations beyond renal-relevant caution
- claim system-wide consensus
- write to FHIR

## Required input
The orchestrator will send you an EpisodeBrief via concord-mcp. Read it before responding.

## Required output
Return ONLY a SpecialistOpinion JSON matching this schema, no prose outside the JSON:
{
  "specialty": "nephrology",
  "summary": "<one paragraph nephrology view>",
  "recommendations": [
    {
      "action_code": "<one of the canonical ActionCode values>",
      "free_text": "<natural-language restatement>",
      "priority": "high|medium|low",
      "rationale": "<why, cited>",
      "risks": [...],
      "monitoring": [...],
      "dependencies": [...],
      "contraindications": [...],
      "evidence_citation": "NICE NG203 §X or null"
    }
  ],
  "missing_data": [...],
  "cross_specialty_dependencies": [
    "<e.g. 'defer to cardiology on decongestion urgency'>"
  ],
  "confidence": "high|medium|low"
}

## Tools available
You may call concord-mcp.GetTrendSummary to confirm eGFR/creatinine/K+ trajectories before responding. You may call concord-mcp.CheckMedicationSafety on specific drug+patient pairs if relevant.

## Action-code discipline
Choose action_code from the canonical catalog. If nothing fits, use "OUT_OF_CATALOG" and describe in free_text.

## Citation discipline
Every substantive recommendation must cite NICE NG203 or NG106 section if applicable. If the recommendation is consensus-standard-of-care, set evidence_citation to null.
```

### 7.3 Cardiology worker system prompt
(Same shape as nephrology; lane = HF/congestion; grounding = NICE NG106 chronic HF + CG187 acute HF; ESC/HFA as secondary.)

### 7.4 Pharmacy worker system prompt
(Same shape as nephrology; lane = medication safety, interactions, Beers/STOPP/START/BNF; framing: RAAS/MRA hyperkalaemia risk in declining renal function, over-diuresis/pre-renal AKI, hypotension, electrolyte disturbance. NOT "loop diuretic causes hyperkalaemia.")

Full text for §7.3 and §7.4 to be drafted during Phase 3 build; structure and rules are locked here.

---

## 8. MCP tool surface — concord-mcp

Nine tools. Every tool has stable JSON in/out, deterministic where safety matters, citation-first where clinical.

### 8.1 Context tools

#### `BuildEpisodeBrief(clinician_question: str) -> EpisodeBrief`
- Deterministic FHIR retrieval (Patient, Condition, MedicationRequest, Observation, DocumentReference).
- LLM structured compression into `EpisodeBrief` schema via Gemini 3 Flash.
- Returns `episode_brief_id` (UUID) used downstream for audit linkage.
- LLM TRANSLATES. LLM DOES NOT DECIDE. No clinical verdicts here.

#### `GetTrendSummary(metrics: list[str]) -> TrendSummary`
- Pure function. Returns trajectory + rate-of-change for requested metrics (eGFR, creatinine, potassium, weight, BNP).
- Extends existing `GetRenalTrend` from signalloop-medsafe-mcp — move to `medsafe_core`, generalize.
- No LLM.

### 8.2 Shared (from medsafe_core)

#### `NormalizeMedication(text: str) -> NormalizedMed`
- Unchanged from SignalLoop. Lives in `medsafe_core`. Both MCPs register it.

#### `CheckMedicationSafety(med: NormalizedMed, profile: PatientRiskProfile) -> SafetyVerdict`
- Unchanged from SignalLoop. Lives in `medsafe_core`. Both MCPs register it.

### 8.3 Arbitration tools

#### `ComputeConflictMatrix(opinions: list[SpecialistOpinion]) -> ConflictMatrix`
- **Pure Python, no LLM.**
- Groups recommendations by `action_code`.
- Classifies each group:
  - **consensus** — all three specialists emit compatible codes (or silence from specialties without lane involvement).
  - **tension** — 2 support, 1 silent; or priority disagreement.
  - **direct_conflict** — ≥1 supports + ≥1 opposes (opposing codes defined in a static map, e.g. UPTITRATE vs DOWNTITRATE of same drug class).
  - **dependency** — specialty declares a `cross_specialty_dependencies` entry that blocks their recommendation on another specialty's answer.
  - **missing_data_block** — specialty lists `missing_data` that blocks any recommendation.
  - **safety_block** — pharmacy (or any) flags a contraindication/high-risk item.
- Ranks next actions by: safety_blocks first, then consensus, then dependencies resolved.
- 100% testable without network or LLM.

#### `ValidateFinalPlan(plan: UnifiedPlan, matrix: ConflictMatrix) -> PlanValidationResult`
- **Deterministic checks, no LLM.** Every check has a name, an expected condition, and a blocking/warning classification:

| Check ID | Blocking? | Condition |
|---|---|---|
| V01 | Yes | Every drafted medication passes `CheckMedicationSafety` — no BLOCK verdict |
| V02 | Yes | No `direct_conflict` item remains in the plan without an explicit resolution field |
| V03 | Yes | Every drafted med/treatment change has an `owner_confirmer` populated |
| V04 | Yes | No write for any action blocked by a decisive `missing_data_block` |
| V05 | Yes | Every specialist recommendation is explicitly dispositioned (accepted / rejected / deferred) — nothing silent |
| V06 | Warn | Every WARN verdict or tension item has a corresponding monitoring Task drafted |
| V07 | Warn | RAAS/MRA/diuretic decisions require renal/electrolyte labs within policy window (default 14 days) — else plan is flagged provisional |
| V08 | Warn | Every drafted Task has a future `due_date` when computed from `timing` |
| V09 | Warn | Missing-data items are either resolved or surfaced in `unresolved_questions` |
| V10 | Warn | Audit artifact will capture specialist inputs + action codes + conflict outcomes + validator status |

Returns `status ∈ {pass, pass_with_warnings, fail}` plus the list of blocking issues and warnings. Only `pass` and `pass_with_warnings` permit write-back.

### 8.4 Action / audit tools (approval-gated)

#### `DraftTask(action_code, description, owner_confirmer, timing) -> TaskDraft`
- Reuse `_compute_due_date_from_timing` from signalloop-medsafe-mcp writes.py. Move to medsafe_core.

#### `DraftMedicationProposal(action_code, med, rationale, owner_confirmer) -> MedicationProposalDraft`
- Framed as **proposal**, not autonomous prescription. Requires explicit clinician confirmation to materialize as FHIR MedicationRequest.

#### `DraftCommunication(to_specialty, summary, linked_action_codes) -> CommunicationDraft`
- FHIR Communication resource for team coordination (e.g. "Message to HF team re: sequencing").

#### `LogConsensusDecision(episode_brief_id, specialist_task_ids, matrix, plan, validation_result) -> AuditEventRef`
- FHIR AuditEvent with structured payload capturing the entire orchestration run. This is the audit surface judges will inspect.
- Required fields: specialist inputs (by taskId), action codes emitted, conflict dispositions, final resolution, validator status, timestamp.

---

## 9. Clinical scope and grounding

### 9.1 Evidence spine
- **Primary (NICE):** NG106 chronic HF, CG187 acute HF, NG203 CKD
- **Secondary (nuance):** ESC 2023 HF focused update, HFA/ESC diuretics position statement
- **Pharmacy:** BNF, AGS Beers 2023, STOPP/START v2

### 9.2 Non-negotiable framings
- **Pharmacy concern in hero scenario:** RAAS/MRA-related hyperkalaemia risk in declining renal function + over-diuresis / pre-renal AKI + hypotension + electrolyte disturbance. **NOT** "loop diuretic causes hyperkalaemia" — that's clinically wrong framing.
- **Nephrology:** renal-protection first, but explicit that over-restriction of decongestion can harm.
- **Cardiology:** congestion kills, but electrolyte-safe sequencing matters.

### 9.3 Citation discipline
Every substantive specialist recommendation must cite a NICE section (or note "standard of care" if no specific citation). Judges will spot-check. Inaccuracy = credibility failure.

---

## 10. Synthetic patients

Three patients. All upload via POST bundles with deterministic uuid5 via a Concord namespace constant (separate from SignalLoop's to avoid collision).

### 10.1 Hero — cardio-renal conflict
- **Profile:** 74M, CKD 3b (eGFR 38, declining from 48 over 6 months), HFrEF (EF 35%, diagnosed 2 years ago), T2DM, hypertension.
- **Active meds:** ramipril 10mg OD, bisoprolol 5mg OD, furosemide 40mg BD, spironolactone 25mg OD, dapagliflozin 10mg OD, metformin 500mg BD, atorvastatin 40mg ON.
- **Recent labs:** eGFR 38, K+ 5.1, Na+ 136, creatinine 165, NT-proBNP 4200 (elevated).
- **Weight trend:** +3kg over 2 weeks.
- **Encounter:** admitted with worsening dyspnoea + ankle oedema 2 days ago. Cardiology wants furosemide up-titration; nephrology worried about further renal decline; pharmacy concerned about MRA-related hyperkalaemia at current K+.
- **Decision point for clinician:** *"Cardiology wants to escalate diuresis, nephrology is worried about renal decline, pharmacy flags hyperkalaemia risk. What's the unified plan?"*

### 10.2 Clean-agreement
- **Profile:** 66F, stable CKD 3a (eGFR 52), HFrEF (EF 40%) on optimal medical therapy, mild ankle swelling.
- **Recent labs:** K+ 4.3, eGFR 52 stable, NT-proBNP modestly elevated but stable.
- **No active NSAIDs, no anticoagulation complications.**
- **Expected:** all three specialists agree on modest loop diuretic adjustment with standard monitoring. Validates Concord doesn't manufacture conflict.

### 10.3 Insufficient-data
- **Profile:** 70F with new-onset dyspnoea and possible congestion signs. No recent BNP, no echo on record, stale electrolyte panel (6 weeks old).
- **Expected:** orchestrator surfaces "cannot safely recommend intensification without recent labs + BNP + echo. Next step: request these before planning."

---

## 11. Build phases

### Phase 0 — Shared library extraction (1.5 days)
- Create `medsafe_core/` with FHIR client, Gemini client, NormalizeMedication, CheckMedicationSafety rules engine, shared Pydantic models.
- Modify `signalloop-medsafe-mcp` to import from `medsafe_core`. Verify SignalLoop tests still pass.
- **Exit:** SignalLoop unchanged behaviourally; `medsafe_core` installable locally.

### Phase 1 — concord-mcp skeleton (1 day)
- New FastMCP server. Register placeholder stubs for all 9 tools. Deploy locally.
- Register concord-mcp URL in Prompt Opinion as MCP app.
- **Exit:** orchestrator can attach concord-mcp and see all 9 tool names in the Tools tab.

### Phase 2 — Concord-specific MCP tool logic (4 days)
- Implement `BuildEpisodeBrief` (hybrid retrieval + LLM compression).
- Implement `GetTrendSummary` (extends existing logic).
- Implement `ComputeConflictMatrix` (pure Python, full unit test coverage).
- Implement `ValidateFinalPlan` (10 deterministic checks, unit tests per check).
- Implement all four draft/audit tools.
- **Exit:** all 9 tools return stable JSON against Margaret/James fixtures; 80%+ unit test coverage on rules-side tools.

### Phase 3 — Specialist workers (2 days)
- Author nephrology/cardiology/pharmacy system prompts in full.
- Create three Patient-scope BYO agents in Po.
- Upload three curated content collections (≤10 pages each).
- Attach concord-mcp to each.
- Smoke-test each worker against the hero EpisodeBrief — confirm each produces a valid, schema-compliant SpecialistOpinion JSON distinct from the others.
- **Exit:** three specialists return three distinct SpecialistOpinions on the same brief, each citing its evidence base.

### Phase 4 — Concord Orchestrator (1 day)
- Create Orchestrator Agent via sidebar.
- Link three specialists.
- Paste authored system prompt (§7.1).
- Attach concord-mcp.
- Run the hero case end-to-end from a fresh chat session.
- **Exit:** one clinician message → EpisodeBrief → 3 specialist calls → ConflictMatrix → UnifiedPlan → ValidateFinalPlan → markdown answer. No raw JSON leaks to the clinician chat.

### Phase 5 — Synthetic patients (1.5 days)
- Author hero patient FHIR bundle (POST format with uuid5).
- Author clean-agreement patient bundle.
- Author insufficient-data patient bundle.
- Upload to hackathon workspace in order.
- **Exit:** all three cases produce coherent outputs that match Concord's thesis.

### Phase 6 — Write-back and audit (1 day)
- Implement draft → approve → commit flow for Tasks, MedicationProposals, Communications.
- Implement LogConsensusDecision AuditEvent with rich payload.
- Test approval-gated commit on hero case.
- **Exit:** after clinician approval, real FHIR resources written with IDs; AuditEvent retrievable.

### Phase 7 — Demo polish and submission (1.5 days)
- Marketplace listing for Concord Orchestrator.
- 3-minute demo script (§12).
- Rehearse hero case from fresh chat ≥3 times.
- Fly.io deploy of concord-mcp alongside signalloop-medsafe-mcp.
- **Exit:** recording matches exactly what judges invoke from the marketplace.

**Total: ~13.5 working days.** Deadline is 2026-05-11, today is 2026-04-24 (17 days). Tight but realistic given most core rules live in medsafe_core and are reused.

---

## 12. Demo script (<3 min)

1. **0:00–0:15** — Set the scene. *"Older patient, admitted with congestion. Cardiology wants more diuresis, nephrology worried about further renal decline, pharmacy flags hyperkalaemia risk. Normally the clinician manually reconciles three specialty opinions. Today we do it in one question."*
2. **0:15–0:40** — Open patient in Prompt Opinion. Select Concord from the agent picker. Paste the clinician's question.
3. **0:40–1:20** — Show orchestrator working: `BuildEpisodeBrief` tool call, three `SendAgentMessage` calls visible in the transcript (nephro / cardio / pharmacy), `ComputeConflictMatrix`, `ValidateFinalPlan`.
4. **1:20–2:10** — Read the rendered markdown. Narrate: consensus on X, tension on Y resolved this way, direct conflict on Z arbitrated by safety block, two draft actions awaiting approval.
5. **2:10–2:30** — Approve two draft actions. Show FHIR resource IDs created + AuditEvent ID.
6. **2:30–2:55** — Close: *"Three specialist opinions. One shared case packet. Deterministic arbitration. Validated unified plan. Auditable write-back. This is multi-agent orchestration that actually respects clinical boundaries."*

**Do NOT:** live-navigate deep tool-call traces, compare against SignalLoop, explain architecture in detail. Keep it clinical.

---

## 13. What we reuse from SignalLoop (via medsafe_core)

- FHIR HTTP client + SHARP context extraction + JWT patient-ID resolution
- Gemini client with `_call_with_retry` exponential backoff
- `NormalizeMedication` logic
- `CheckMedicationSafety` rules engine + renal dosing JSON + Beers JSON + interaction rules JSON
- `_compute_due_date_from_timing` and `_coerce_due_date` helpers
- `GetRenalTrend` (generalised into `GetTrendSummary`)
- Pydantic model patterns for structured Gemini output
- Unit test scaffolding

**Not reused:** single-specialty framing, consult-loop-closure workflow, one-central-verdict narrative — those belong to SignalLoop.

---

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Orchestrator Agent feature is undocumented publicly → may change without notice | Confirmed working as of 2026-04-24. Memory note captures mechanics. Pin Po workspace state; don't upgrade mid-submission window. |
| 3-specialist fan-out latency >30s | Keep specialist prompts tight. Each response schema-constrained. Observed latency during build informs acceptable budget. |
| Worker scope mismatch on save | All agents at Patient scope. Confirmed workable. |
| Action-code catalog gaps | `OUT_OF_CATALOG` fallback code + `ValidateFinalPlan` flags as warning. Catalog is extensible between phases. |
| Judges find a rule citation wrong | Cite-or-omit discipline: every substantive recommendation either cites a specific NICE section or marks "standard of care". Spot-check every rule before submission. |
| Specialist goes out of lane | Enforced 4 ways: (1) system prompt, (2) tool isolation, (3) grounding isolation (one collection per specialty), (4) schema constraint (no `global_plan` field). |
| Margaret's narrative bifurcated | Does not apply — Concord uses a brand-new hero patient, Margaret stays SignalLoop's. |
| LLM timestamp hallucination in worker output | Inject time-sensitive fields deterministically in MCP tools downstream of worker (same pattern as SignalLoop `_compute_due_date_from_timing`). |
| medsafe_core refactor breaks SignalLoop | Phase 0 exit condition requires SignalLoop tests pass unchanged. |

---

## 15. Open questions (resolve during Phase 0)

1. Does `concord-mcp` deploy as a second process on Fly.io, or mount as additional routes under the existing signalloop-medsafe-mcp Fly app? Preference: separate process for isolation.
2. Policy window for V07 (RAAS/MRA labs freshness): default 14 days, confirm against NICE NG106 §1.5.5.
3. `specialist_task_ids` structure in UnifiedPlan — does Po expose taskId to the orchestrator's runtime, or only in transcript? If only transcript, audit capture must happen orchestrator-side via prompt.
4. Concord marketplace listing — separate from SignalLoop? Confirm yes per §1.1.

---

## 16. Frozen commitments

The following do NOT change without a decision recorded in this document:

- **Three specialists**, not four.
- **New hero patient**, not Margaret.
- **Orchestrator Agent type**, not BYO + Consult.
- **Action-code enum**, not free-text conflict arbitration.
- **`ComputeConflictMatrix` and `ValidateFinalPlan` are deterministic**, no LLM.
- **NICE NG106 + CG187 + NG203 evidence spine**, ESC/HFA as nuance only.
- **Patient scope** for all Concord agents.
- **Sequential** fan-out, not parallel.
- **Always-call-all-three** in v1, smart routing deferred.

---

## 17. Definition of done

Concord ships when:

1. All three synthetic patients upload cleanly to the hackathon workspace.
2. Hero case runs end-to-end from fresh chat → markdown unified plan → clinician-approved FHIR writes with AuditEvent in ≤60 seconds.
3. Clean-agreement case returns a plan without manufactured conflict.
4. Insufficient-data case refuses certainty and surfaces decisive missing data.
5. All 10 ValidateFinalPlan checks have passing unit tests.
6. ComputeConflictMatrix has ≥90% branch coverage on its classification rules.
7. Marketplace listing live, agent invokable externally.
8. 3-minute demo recording matches what judges invoke.
9. No raw JSON leaks into clinician chat on any tested path.
10. `medsafe_core` refactor did not break any SignalLoop test.

---

**End of operational plan. Build from Phase 0.**
