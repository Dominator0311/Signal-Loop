# SignalLoop — Final Operational Plan

**Status:** FROZEN. This is the operational contract. The master spec (blue sky) remains the north star; this document is what actually gets built.

**Deadline:** May 11, 2026, 11:00pm EDT
**Available time:** ~24 days from April 18

---

## Part 1: The Product (frozen scope)

### One-sentence positioning

**SignalLoop is a patient-scope clinical agent that detects renal-risk context from new lab results, runs a three-phase context-aware medication safety gate before any prescribing action, proactively identifies when specialist referral is indicated, assembles specialty-specific referral packets with missing-context flagging, and closes the loop by extracting recommendations from returned specialist notes — all built on MCP, A2A, and FHIR inside Prompt Opinion.**

### The narrow clinical scope (locked)

- **Signal family:** renal decline only (eGFR and creatinine trending)
- **Prescribing scenario:** NSAID contraindication in CKD + ACE-I/diuretic context
- **Referral type:** nephrology (specialty-specific packet design applies to others as roadmap)
- **Patient population:** adult, non-pregnant (stated as constraint)
- **Jurisdiction:** UK-first (dm+d coding, NICE NG203 grounding, BNF-flavored severity language)

Everything outside this scope is explicitly roadmap. Not "maybe in MVP." Roadmap.

### What this means commercially

Framed honestly: a *narrow deterministic prototype for one high-value prescribing safety workflow with deep referral loop closure*, with an architecture designed to plug into licensed drug knowledge bases (BNF, Stockley's) and real specialist directories for production use. Do not oversell as a general-purpose DDI engine or real-time scheduling system.

### Why it is non-generic

Two architectural commitments make this product different from the crowd of hackathon submissions:

**MedSafe runs as three phases, not as "AI wrapping rules."** Phase 1 (LLM): build structured patient risk profile from the chart. Phase 2 (rules): deterministic safety check parameterised by the profile. Phase 3 (LLM): synthesise patient-specific narrative, personalised alternatives with trade-offs, monitoring plans, override-reason analysis. This mirrors how expert clinical pharmacists think, and it earns AI Factor credit while keeping Feasibility because safety verdicts remain deterministic and auditable.

**Loop closure is treated as first-class capability, not an afterthought.** Proactive referral identification during interpretation. Specialty-specific packet assembly with missing-context flagging. Destination ranking. Patient message drafting. Return-handler that extracts structured recommendations from free-text consult notes *and detects conflicts with the current care plan*. Most hackathon submissions stop at insight or single-action. Showing an actually-closed loop is a rare and strong differentiator.

---

## Part 2: Architecture (frozen)

### Two submissions, shared codebase

**Submission A — MedSafe MCP Server (Superpower category)**
- Standalone MCP server, externally hosted
- Declares `ai.promptopinion/fhir-context` extension
- Exposes ~14 tools organised across three phases (patient profile building, deterministic safety check, response synthesis) plus a referral sub-system
- Reusable: any agent in the Prompt Opinion marketplace can call it
- Built from `po-community-mcp` Python branch

**Submission B — SignalLoop Renal Safety Agent (Agent category)**
- BYO Patient-scope A2A agent configured *inside Prompt Opinion*
- Not external. Not ADK. In-platform.
- A2A enabled with skills so other agents can consult it
- MedSafe MCP attached as tool
- Grounded on a small, curated content collection
- JSON response schema for structured outputs
- FHIR context enabled

**Not submitted but present:** the user experiences Submission B directly via the Launchpad. No separate Orchestrator needed — the BYO A2A agent *is* the orchestrator.

### Architecture diagram

```
┌─────────────────────────────────────────────────────────────┐
│  Prompt Opinion Workspace                                   │
│                                                             │
│  ┌─────────────────────────────────────────────┐            │
│  │  SignalLoop Renal Safety Agent              │            │
│  │  (BYO Patient-scope A2A, in-platform)       │            │
│  │                                             │            │
│  │  · Scope: Patient                           │            │
│  │  · A2A: enabled, 1 skill                    │            │
│  │  · FHIR context: enabled                    │            │
│  │  · Tools: MedSafe MCP                       │            │
│  │  · Content: 1 curated collection            │            │
│  │  · Response format: JSON schema             │            │
│  └─────────────────────────────────────────────┘            │
│         │                                  ▲                │
│         │ MCP tool calls                   │ FHIR reads     │
│         │ (SHARP headers auto)             │ (writes too)   │
│         ▼                                  │                │
│  ┌─────────────────────────────────────────┴──┐             │
│  │  Workspace FHIR Server (built-in)          │             │
│  │  · Patient A — positive alert (Margaret)   │             │
│  │  · Patient B — safe control                │             │
│  │  · Patient C — override/stress test        │             │
│  │  · Curated synthetic data each             │             │
│  └────────────────────────────────────────────┘             │
│                                             ▲               │
└─────────────────────────────────────────────┼───────────────┘
                                              │
                                              │ FHIR reads via
                                              │ SHARP headers
                                              │ (X-FHIR-Server-URL,
                                              │  X-FHIR-Access-Token,
                                              │  X-Patient-ID)
                                              │
  ┌───────────────────────────────────────────┴──┐
  │  MedSafe MCP Server (external, ngrok)        │
  │  (Submission A — Python, from po-community)  │
  │                                              │
  │  Tools:                                      │
  │                                              │
  │  Phase 1 (LLM — patient profile):            │
  │  · build_patient_risk_profile                │
  │  · get_relevant_context                      │
  │  · get_renal_trend                           │
  │                                              │
  │  Phase 1/2 helper:                           │
  │  · normalize_medication                      │
  │                                              │
  │  Phase 2 (rules — deterministic):            │
  │  · check_medication_safety                   │
  │                                              │
  │  Phase 3 (LLM — response synthesis):         │
  │  · synthesise_safety_response                │
  │  · analyse_override_reason                   │
  │                                              │
  │  FHIR writes:                                │
  │  · draft_medication_request                  │
  │  · draft_followup_task                       │
  │  · draft_service_request                     │
  │  · log_override                              │
  │                                              │
  │  Referral sub-system (see Part 6):           │
  │  · assemble_specialty_packet                 │
  │  · rank_specialist_destinations              │
  │  · extract_consult_recommendations           │
  │  · detect_plan_conflicts                     │
  │                                              │
  │  Declares:                                   │
  │  ai.promptopinion/fhir-context extension     │
  └──────────────────────────────────────────────┘
```

### SHARP headers (correction locked in)

The platform passes exactly three headers when FHIR context is enabled:

- `X-FHIR-Server-URL` (always)
- `X-FHIR-Access-Token` (optional, often present)
- `X-Patient-ID` (present in patient-scope calls)

Encounter, loop, and session identifiers are **not** platform fields. If SignalLoop needs them, treat them as internal app state — not as propagated context.

---

## Part 3: The MedSafe MCP tool surface (frozen)

Ten tools organised around a three-phase architecture. All tools receive FHIR context via SHARP headers; none require patient data in the request body.

### The three-phase architecture (locked)

MedSafe's core innovation is that it runs as three distinct phases — LLM reasoning bookends a deterministic safety core:

**Phase 1 — Patient Risk Profile Building (LLM)**
The AI reads the full patient chart and constructs a structured risk profile. This is substantive generative work: identifying which of many chart facts matter for prescribing safety, weighting their relevance, and producing reasoning traces. A rules engine cannot do this.

**Phase 2 — Deterministic Safety Check (Rules)**
The rules engine receives the proposed medication plus the Phase 1 profile and applies deterministic safety rules. The profile *parameterises* the rules — a single drug pair might fire differently for different patients — but the decision logic itself stays deterministic and auditable. No LLM involved.

**Phase 3 — Response Synthesis (LLM)**
The AI synthesises Phase 2 verdicts and Phase 1 profile into clinically-actionable output: patient-specific risk narrative, personalised alternatives with trade-offs, monitoring plans, override-reason analysis.

This design earns AI Factor (LLM does real generative work on both ends) while keeping Feasibility (safety verdicts are deterministic). It mirrors how expert clinical pharmacists actually think.

### Tool contracts

### Phase 1 Tools

#### `build_patient_risk_profile(patient_id)` *(patient_id sourced from header)*

Flagship Phase 1 tool. LLM reads the patient's FHIR record and produces a structured risk profile with reasoning.

```json
{
  "patient_id": "patient-margaret",
  "generated_at": "2026-04-20T09:15:00Z",
  "demographics": {
    "age": 72,
    "sex": "female",
    "weight_kg": 68,
    "height_cm": 162
  },
  "physiological_factors": {
    "renal_function": {
      "latest_egfr": 42,
      "trajectory": "declining",
      "rate_of_change_per_month": -4.2,
      "relevance": "high — any renal-risk medication requires scrutiny",
      "reasoning": "eGFR has declined 16 points over 3 months with no intervention explaining the drop; classic pre-CKD stage 4 trajectory"
    },
    "hepatic_function": {"relevance": "low", "reasoning": "no LFT abnormalities on record"},
    "pregnancy_status": "not applicable (postmenopausal)"
  },
  "active_medication_inventory": [
    {
      "name": "lisinopril 10mg",
      "class": "ACE inhibitor",
      "interaction_relevant_properties": ["renal_risk_component", "hyperkalemia_risk"],
      "notes": "forms first leg of triple-whammy with diuretic + NSAID"
    },
    {
      "name": "furosemide 40mg",
      "class": "Loop diuretic",
      "interaction_relevant_properties": ["renal_risk_component", "electrolyte_disturbance"],
      "notes": "forms second leg of triple-whammy"
    },
    {"name": "metformin 500mg BD", "class": "Biguanide", "interaction_relevant_properties": ["renal_dose_adjust"]},
    {"name": "simvastatin 20mg", "class": "HMG-CoA reductase inhibitor", "interaction_relevant_properties": ["myopathy_risk"]}
  ],
  "allergy_profile": [
    {"substance": "penicillin", "reaction": "rash", "cross_reactivity_concerns": ["cephalosporins"]}
  ],
  "clinical_context_flags": [
    "frail_elderly",
    "polypharmacy",
    "cardio_renal_high_risk",
    "ckd_stage_3b_near_4"
  ],
  "weighted_risk_factors": [
    {"factor": "sustained eGFR decline on ACE + diuretic", "weight": "critical",
     "reasoning": "any NSAID or nephrotoxic drug creates triple-whammy AKI risk"},
    {"factor": "age 72 with polypharmacy", "weight": "high",
     "reasoning": "Beers criteria considerations, increased drug-drug interaction risk"},
    {"factor": "diabetes with CKD", "weight": "high",
     "reasoning": "compounds renal risk for any new nephrotoxic exposure"}
  ],
  "reasoning_trace": "Primary risk is renal — all prescribing decisions should be evaluated against the triple-whammy pattern. Secondary risk is polypharmacy in elderly. Hepatic function, pregnancy, pediatric considerations are not material for this patient."
}
```

The profile is cached per patient per session. It does not rebuild on every prescription attempt but refreshes when new relevant data arrives (new eGFR, new medication, new condition).

#### `get_relevant_context(signal_id)`

Focused subset of the profile relevant to a specific new signal. Used by the Signal Interpretation agent during Stage 2 Context Aggregation.

```json
{
  "signal": {
    "resource_type": "Observation",
    "id": "obs-egfr-latest",
    "label": "eGFR 42 (declining)"
  },
  "selected_context": [
    {"resource_ref": "MedicationRequest/lisinopril",
     "why_selected": "ACE inhibitor — renal risk component in triple-whammy pattern"},
    {"resource_ref": "MedicationRequest/furosemide",
     "why_selected": "Diuretic — second leg of triple-whammy"},
    {"resource_ref": "Condition/diabetes",
     "why_selected": "Compounds renal risk for any new nephrotoxic exposure"}
  ],
  "missing_context": ["No recent urine ACR found — would strengthen CKD staging"],
  "uncertainties": [],
  "evidence_refs": ["NICE NG203 §1.3.2"]
}
```

#### `get_renal_trend(lab_code, lookback_days)`

Returns eGFR or creatinine history as structured trend. Used by the profile builder and by the signal interpreter.

```json
{
  "code": "LOINC:62238-1",
  "label": "eGFR",
  "values": [
    {"date": "2025-11-14", "value": 58, "unit": "mL/min/1.73m²"},
    {"date": "2026-01-20", "value": 52, "unit": "mL/min/1.73m²"},
    {"date": "2026-04-12", "value": 42, "unit": "mL/min/1.73m²"}
  ],
  "trajectory": "declining",
  "rate_of_change_per_month": -4.2,
  "interpretation": "Sustained decline; no interventions recorded that explain it"
}
```

### Phase 1 & 2 Helper

#### `normalize_medication(raw_text)`

Free-text or patient-phrased medication string → canonical identifier.

```json
{
  "raw": "ibuprofen 400mg tds",
  "resolved": true,
  "system": "dm+d",
  "code": "demo-dmd-376445002",
  "canonical_name": "ibuprofen 400mg tablets",
  "dose": {"value": 400, "unit": "mg", "frequency": "TDS"},
  "drug_class": "NSAID"
}
```

When unresolvable, returns `"resolved": false` with candidate matches. Never silently drops.

### Phase 2 Tool

#### `check_medication_safety(proposed_med_code, patient_risk_profile)`

The deterministic core. Pure rules. No LLM. Patient_risk_profile is passed in (from Phase 1) — the rules use its structured fields to parameterise verdicts.

```json
{
  "proposed_medication": {"code": "demo-dmd-376445002",
                          "canonical_name": "ibuprofen 400mg tablets",
                          "class": "NSAID"},
  "verdict": "block",
  "flags": [
    {"type": "renal-contraindication",
     "severity": "contraindicated", "evidence_level": "established",
     "reason": "NSAID inappropriate in CKD stage 3b (eGFR 42)",
     "rule_id": "renal-nsaid-egfr-under-60",
     "citation": "NICE NG203 §1.3.2"},
    {"type": "triple-whammy-aki",
     "severity": "major", "evidence_level": "established",
     "reason": "NSAID + ACE-I (lisinopril) + diuretic (furosemide) = AKI risk",
     "rule_id": "triple-whammy-aki",
     "citation": "BNF interaction severity: severe"},
    {"type": "beers-criteria",
     "severity": "moderate", "evidence_level": "established",
     "reason": "Age 72 — Beers criteria: avoid chronic NSAIDs >65",
     "rule_id": "beers-nsaid-over-65",
     "citation": "Beers 2023"}
  ],
  "requires_override_reason": true,
  "profile_fields_consulted": [
    "physiological_factors.renal_function.latest_egfr",
    "active_medication_inventory[ACE inhibitor, Loop diuretic]",
    "demographics.age"
  ]
}
```

The `profile_fields_consulted` field is important for audit: it shows exactly which parts of the Phase 1 profile influenced the deterministic verdict.

### Phase 3 Tools

#### `synthesise_safety_response(verdict, patient_risk_profile)`

Flagship Phase 3 tool. Takes deterministic verdict + rich patient profile and produces patient-specific narrative, personalised alternatives with trade-offs, and monitoring plans.

```json
{
  "patient_specific_narrative": "Margaret's kidney function has declined 16 points over 3 months with no intervention explaining the drop. She is already on the two medications — lisinopril and furosemide — that form two legs of the triple-whammy pattern. Adding an NSAID is the specific combination that causes 10-15% of AKI admissions in this demographic. Her age and diabetes compound the risk. The decline trajectory itself suggests she may be approaching CKD stage 4; an NSAID could accelerate that conversion.",
  "personalised_alternatives": [
    {
      "name": "paracetamol 1g QDS",
      "suitability_for_this_patient": "best first-line option",
      "rationale": "Effective for osteoarthritis per NICE CG177, no renal impact, no interaction with her current regimen",
      "trade_offs": "Caution: she is on simvastatin; high-dose paracetamol long-term can affect liver enzymes. Suggest LFT monitoring at 3 months",
      "monitoring_plan": "Check LFTs if continuing beyond 3 months at 1g QDS"
    },
    {
      "name": "topical diclofenac",
      "suitability_for_this_patient": "reasonable second-line for localised pain",
      "rationale": "Minimal systemic absorption sidesteps the triple-whammy",
      "trade_offs": "Adherence is lower in patients with bilateral involvement. Margaret's note mentioned bilateral knee pain, so practical adherence may be limited",
      "monitoring_plan": "Monitor topical site reactions; no systemic monitoring required"
    }
  ],
  "monitoring_if_override": "If proceeding with NSAID despite warnings: repeat eGFR in 5-7 days; hold ACE inhibitor during NSAID course; monitor for AKI symptoms (oliguria, rising creatinine). Strongly discouraged."
}
```

#### `analyse_override_reason(override_reason_text, verdict, patient_risk_profile)`

When a clinician overrides a MedSafe block, this tool analyses the free-text reason and:
- Classifies it (specialist recommendation, short-course trial, no alternative available, patient preference, emergency)
- Determines whether it represents valid clinical context
- Suggests mitigating monitoring plan
- Structures the justification for audit

```json
{
  "override_classification": "specialist_recommendation",
  "clinical_validity_assessment": "Valid context — rheumatology specialist has recommended short-course NSAID for flare. Short-course prescribing with monitoring is defensible even with renal risk.",
  "suggested_monitoring": [
    "Repeat eGFR within 7 days of starting",
    "Hold lisinopril during NSAID course if possible",
    "Limit to 7-day supply maximum",
    "Patient education on dehydration avoidance"
  ],
  "structured_audit_justification": "Rheumatology-directed short-course NSAID for arthritis flare; monitoring plan in place",
  "residual_risk_acknowledged": true
}
```

This is substantive AI value — a traditional override just captures free text and moves on. This analyses it.

### Phase 3 Drafting & Write Tools

#### `draft_medication_request(action_payload)`

Converts approved action into a FHIR MedicationRequest. Returns resource ID after write.

#### `draft_followup_task(action_payload)`

Creates a FHIR Task for follow-up work. For example, "Repeat eGFR in 2 weeks" or "Check LFTs at 3 months."

#### `draft_service_request(action_payload)`

Creates a FHIR ServiceRequest for referrals. Used for the nephrology referral in the demo.

#### `log_override(reason_payload)`

Creates a FHIR AuditEvent when a clinician overrides a MedSafe block. Incorporates the structured analysis from `analyse_override_reason`. Permanent record.

---

## Part 4: The SignalLoop agent configuration (frozen)

### System prompt strategy

The agent is a *renal safety specialist with deep referral loop management*. It follows this exact orchestration:

1. **On patient open:** proactively calls `build_patient_risk_profile` (Phase 1) and caches the result for the session
2. **Check for new renal signals:** uses `get_renal_trend` and `get_relevant_context`
3. **Produce structured interpretation:** via JSON schema, leveraging the cached risk profile
4. **If interpretation indicates specialist referral may be appropriate:** proactively surface the recommendation with reasoning — *"Given the pattern, nephrology review is indicated under NICE NG203 §1.4. Shall I draft the packet?"*
5. **When user proposes a medication:** always call `check_medication_safety` (Phase 2, deterministic) passing the cached patient risk profile
6. **If MedSafe flags fire:** always call `synthesise_safety_response` (Phase 3, LLM) to produce patient-specific narrative and personalised alternatives
7. **Never generate safety verdicts itself** — defers to the MedSafe MCP tool chain
8. **If user approves an NSAID despite block (override):** call `analyse_override_reason` and `log_override`
9. **If user approves a referral:** call `assemble_specialty_packet` for the target specialty, then `rank_specialist_destinations`, then `draft_service_request` with the packet
10. **Writes to FHIR only after user approval** (text confirmation counts)
11. **When a returned consult note appears:** call `extract_consult_recommendations` and `detect_plan_conflicts`, then `draft_followup_task` with the reconciled next steps

### JSON response schema (expanded)

```json
{
  "clinician_brief": {
    "what_changed": "string",
    "why_it_matters_for_this_patient": ["string"],
    "trend_summary": "string",
    "uncertainties": ["string"]
  },
  "patient_explanation": {
    "text": "string",
    "reading_level": "6th_grade",
    "requires_clinician_approval": true
  },
  "medsafe": {
    "triggered": "boolean",
    "phase_1_profile_summary": "string",
    "phase_2_verdict": "none|warn|block|overridden",
    "phase_3_narrative": "string",
    "top_flags": ["string"],
    "personalised_alternatives": [
      {"name": "string",
       "suitability": "string",
       "trade_offs": "string",
       "monitoring_plan": "string"}
    ]
  },
  "proactive_referral": {
    "indicated": "boolean",
    "specialty": "string|null",
    "reasoning": "string",
    "guideline_citation": "string"
  },
  "referral_packet": {
    "target_specialty": "string|null",
    "included_resources": ["string"],
    "missing_context_flags": ["string"],
    "candidate_destinations": [
      {"name": "string",
       "rank_factors": {"specialty_fit": "number",
                        "wait_time_days": "number",
                        "distance_miles": "number",
                        "language_match": "boolean"}}
    ]
  },
  "recommended_actions": [
    {"type": "string", "label": "string", "rationale": "string",
     "requires_approval": true}
  ],
  "writeback_candidates": [
    {"resource_type": "string", "action": "string", "draft_ref": "string"}
  ],
  "returned_consult_handling": {
    "source_document_ref": "string|null",
    "extracted_recommendations": ["string"],
    "plan_conflicts_detected": ["string"],
    "reconciled_next_steps": ["string"]
  },
  "reconciliation_notes": [
    {"field": "string",
     "state": "confirmed|needs_review|conflict|missing_important"}
  ]
}
```

The `reconciliation_notes` field is how the 4-state intake taxonomy surfaces without building a live intake UI. The new `proactive_referral`, `referral_packet`, and `returned_consult_handling` fields are how the expanded referral capability surfaces.

### Content collection (one only)

Curated, small, focused:
- NICE NG203 (CKD assessment and management) — key sections including §1.4 on referral indications
- NICE CG177 (osteoarthritis care)
- BNF-style interaction severity reference (public summary, not full BNF)
- Beers criteria 2023 summary
- AKI "triple whammy" reference paper/summary
- Nephrology referral packet checklist (what nephrologists need)

Keep under 25 pages total. A tight collection grounds better than a sprawling one.

### A2A configuration

- A2A: enabled
- Skills: one skill named `renal_safety_consult`, described as "Consult SignalLoop for renal-risk interpretation, context-aware prescribing safety, proactive referral recommendation, specialty-specific packet assembly, and loop closure"
- FHIR context: required (not just enabled — required, so clients must pass it)

### Scope

Patient scope. Appears in Launchpad when a patient is selected.

---

## Part 5: The three-patient demo set (frozen)

### Patient A — Margaret Henderson (positive alert, hero demo)

- 72F, retired teacher
- Active conditions: T2DM (10 years), hypertension (15 years), CKD stage 3b, osteoarthritis (bilateral knees)
- Active meds: lisinopril 10mg OD, furosemide 40mg OD, metformin 500mg BD, simvastatin 20mg nocte
- Allergies: penicillin (rash)
- Renal observations: eGFR 58 → 52 → 42 over 3 months; creatinine rising in parallel
- Recent note: primary care visit 2 weeks ago, knee pain worsening
- Reason for visit today: follow up on knee pain

This is the demo. Her chart is designed so that attempting to prescribe ibuprofen fires MedSafe with all three flag types (contraindication, triple-whammy, Beers).

### Patient B — James Okonkwo (safe control)

- 42M, healthy
- Active conditions: seasonal allergies only
- Active meds: none
- eGFR 95 (normal)
- Reason for visit: ankle sprain

Proves the system doesn't over-block. Prescribing ibuprofen 400mg for him passes MedSafe cleanly. This is the stress-test judges will attempt.

### Patient C — Doris Williams (override scenario)

- 68F
- Active conditions: rheumatoid arthritis (severe), osteoporosis
- Active meds: methotrexate, folic acid, alendronic acid
- eGFR 65 (mildly reduced)
- Clinical context: rheumatology specialist has recommended short-course NSAID for flare

This patient is for the override path. When a clinician prescribes naproxen, MedSafe fires a *major* warning (not a block). Clinician can proceed with documented reason. AuditEvent is logged. This shows the system respects clinical judgment, not just hard rules.

---

## Part 6: The referral sub-system (frozen)

Referral loop closure is treated as first-class capability because it meaningfully differentiates SignalLoop from the crowd and because documented referral loop-closure rates of 35-65% in ambulatory care represent a real, measurable patient safety and revenue-leakage problem.

### Four new MCP tools

#### `assemble_specialty_packet(target_specialty, patient_id)` *(patient_id from header)*

Given a target specialty, assembles a packet containing what *that specialty* needs. Different specialties need different inputs. The tool reads the patient's FHIR record through specialty-aware filters and flags what's missing.

Output for `target_specialty: "nephrology"`:

```json
{
  "target_specialty": "nephrology",
  "patient_id": "patient-margaret",
  "required_inputs": {
    "egfr_trend": {"included": true, "resource_refs": ["Observation/..."]},
    "creatinine_trend": {"included": true, "resource_refs": ["Observation/..."]},
    "urine_acr": {"included": false,
                  "missing_context_flag": "No urine ACR in last 12 months — consider ordering before referral"},
    "bp_history": {"included": true, "resource_refs": ["Observation/..."]},
    "current_ace_arb_dose": {"included": true, "resource_refs": ["MedicationRequest/lisinopril"]},
    "diabetes_status": {"included": true, "resource_refs": ["Condition/diabetes"]},
    "recent_imaging": {"included": false,
                       "missing_context_flag": "No renal imaging on record — not required but may be requested by nephrologist"},
    "active_nephrotoxin_exposure": {"included": true,
                                    "flagged_items": ["furosemide (loop diuretic)", "lisinopril (ACE-I)"]}
  },
  "referral_question": "Sustained eGFR decline from 58 to 42 over 3 months in 72F with T2DM, HTN, on ACE-I + loop diuretic. Please assess for CKD progression and advise on medication optimisation.",
  "urgency_rationale": "Rapid progression trajectory; preventing progression to stage 4",
  "packet_completeness_score": 0.75,
  "missing_context_summary": "2 of 8 optional inputs not available; completeness is sufficient for standard referral but ordering ACR before sending would strengthen."
}
```

For hackathon, the specialty profiles are hardcoded for nephrology (full detail) with stub profiles for cardiology and rheumatology (for demonstrating extensibility without building depth). All other specialties are explicit roadmap.

#### `rank_specialist_destinations(specialty, patient_id)` *(patient_id from header)*

Returns candidate destinations ranked across multiple factors. For hackathon: queries a hardcoded directory of three realistic candidates; in production this queries a live directory service.

```json
{
  "specialty": "nephrology",
  "ranked_candidates": [
    {
      "name": "Dr Anita Patel",
      "site": "Royal Free Nephrology Clinic",
      "rank_score": 0.89,
      "rank_factors": {
        "specialty_subfit": 0.9,
        "earliest_slot_days": 8,
        "distance_miles": 4.2,
        "language_match": true,
        "network_status": "in-network",
        "clinical_focus": "CKD progression, medication optimisation"
      },
      "rationale": "Closest clinic, strong match on CKD focus, 8-day wait is acceptable for subacute decline"
    },
    {
      "name": "Dr Marcus Williams",
      "site": "UCH Renal Services",
      "rank_score": 0.81,
      "rank_factors": {
        "specialty_subfit": 0.8,
        "earliest_slot_days": 3,
        "distance_miles": 7.1,
        "language_match": true,
        "network_status": "in-network",
        "clinical_focus": "general nephrology"
      },
      "rationale": "Fastest availability; further distance but broader nephrology coverage"
    },
    {
      "name": "Dr Fatima Okonkwo",
      "site": "North Thames Kidney Centre",
      "rank_score": 0.72,
      "rank_factors": {
        "specialty_subfit": 0.85,
        "earliest_slot_days": 14,
        "distance_miles": 12.0,
        "language_match": true,
        "network_status": "in-network",
        "clinical_focus": "CKD + diabetes"
      },
      "rationale": "Strong diabetes-CKD subfocus matches patient profile; longest wait"
    }
  ]
}
```

Honest framing: the directory is seeded. The *ranking logic* is real. In the Devpost writeup, state clearly that production integration would query a real directory API.

#### `extract_consult_recommendations(document_reference_id)`

When a specialist consult note returns as a `DocumentReference`, this tool parses the note and extracts structured recommendations.

```json
{
  "source_document_ref": "DocumentReference/nephrology-consult-20260426",
  "specialist": "Dr Anita Patel, Nephrology",
  "consult_date": "2026-04-26",
  "extracted_recommendations": [
    {"type": "medication_change",
     "action": "stop",
     "target": "lisinopril",
     "rationale": "Further ACE inhibition may accelerate decline given current eGFR and trajectory",
     "urgency": "within_1_week"},
    {"type": "medication_start",
     "action": "start",
     "target": "irbesartan 150mg OD",
     "rationale": "ARB preferred over ACE-I in this context; consider titration",
     "urgency": "concurrent_with_ace_stop"},
    {"type": "monitoring",
     "action": "recheck",
     "target": "eGFR and electrolytes",
     "timing": "6_weeks",
     "rationale": "Confirm stabilisation after medication optimisation"},
    {"type": "patient_education",
     "action": "discuss",
     "target": "NSAID avoidance permanently",
     "rationale": "Lifelong avoidance given CKD stage"}
  ],
  "urgent_flags": [],
  "specialist_follow_up_needed": true,
  "specialist_follow_up_timeline": "3_months"
}
```

This is substantive generative AI work — turning unstructured clinical free text into structured, actionable recommendations that can be reconciled against the current plan.

#### `detect_plan_conflicts(extracted_recommendations, current_plan, patient_risk_profile)`

Takes the extracted recommendations and compares them against the current care plan, flagging conflicts for clinician attention.

```json
{
  "conflicts_detected": [
    {
      "conflict_type": "medication_change_affects_other_condition",
      "description": "Stopping lisinopril may affect BP control",
      "current_plan_item": "Hypertension management via ACE-I",
      "incoming_recommendation": "Stop lisinopril",
      "reconciliation_suggestion": "Replace with ARB (irbesartan) as specialist recommended; monitor BP at 2 weeks and 6 weeks",
      "clinician_action_required": true
    }
  ],
  "harmonised_plan": [
    "Stop lisinopril today",
    "Start irbesartan 150mg OD today",
    "Check BP at 2 weeks",
    "Repeat eGFR and electrolytes at 6 weeks",
    "Patient education: NSAID avoidance permanent",
    "Nephrology follow-up at 3 months"
  ],
  "task_recommendations": [
    {"task_type": "medication_reconciliation", "timing": "today"},
    {"task_type": "bp_check", "timing": "2_weeks"},
    {"task_type": "repeat_labs", "timing": "6_weeks"},
    {"task_type": "nephrology_followup", "timing": "3_months"}
  ]
}
```

This is the "loop closure" deliverable: reconciled, actionable PCP next-step list, not "review this note." A rules engine cannot reconcile free-text clinical recommendations against a care plan. This is real AI value.

### What the referral sub-system deliberately does NOT do

Maintain honest framing by explicitly naming what's out of scope:

- **Real specialist directory integration** — seeded with three candidates; production would query NHS Spine or commercial directory
- **Real appointment booking** — we write a `ServiceRequest` resource representing a referral request; we do not update a specialist's calendar
- **Real patient message delivery** — we draft SMS/email content and write a `Communication` resource; we do not transmit
- **Multi-specialty depth** — nephrology is built out; cardiology and rheumatology are stubbed for demonstrating extensibility; other specialties are roadmap
- **Active watchdog monitoring** — loop status is queried on demand; no scheduled sweep

State these clearly in the Devpost writeup and in the demo if asked. Honest positioning beats over-promising every time.

---

## Part 7: FHIR writes (frozen)

### Write targets

| Trigger | Resource | Purpose |
|---|---|---|
| Medication approved after MedSafe clean | `MedicationRequest` | The prescribing action |
| Follow-up needed | `Task` | "Repeat eGFR in 2 weeks," etc. |
| Referral approved | `ServiceRequest` | Nephrology referral |
| Patient message drafted + approved | `Communication` | The SMS/email draft |
| Override used on MedSafe | `AuditEvent` | Permanent record with reason |

### What we're NOT writing

- `Appointment` — we don't actually book slots. Using Appointment without a real booking is standards abuse.
- `CarePlan` — adds complexity without demo value
- `DocumentReference` for return consult — we pre-insert for the demo time-jump; don't try to build a generator

### Clinician-in-the-loop invariants

1. No `MedicationRequest` without passing MedSafe (or documented override)
2. No `ServiceRequest` without explicit user approval
3. No `Communication` without approval
4. Every override creates an `AuditEvent`

---

## Part 8: What's faked in the demo

Label these clearly in the Devpost writeup as "demo staging":

- **Margaret's chart is pre-loaded.** Her clinical reality is hand-designed.
- **The "6 days later" consult note** is pre-inserted as a `DocumentReference` mid-demo via a staging script.
- **The three candidate nephrologists** (for referral matching) are hardcoded.
- **Intake** is pre-loaded as clinical notes and structured FHIR resources, not live-captured.
- **Patient SMS outreach** is drafted and shown in the chat; not sent.

This is honest staging, not fraud. Any hackathon demo stages. What matters is that the core capabilities — context selection, MedSafe logic, FHIR writes, referral packet assembly — are all real.

---

## Part 9: Explicit roadmap (not in MVP)

State these in the Devpost writeup so judges know you understand the full problem:

- Live patient intake conversation
- Medication photo OCR
- Broad radiology/pathology interpretation
- Multi-signal (cardiac, hepatic, hematologic)
- Comprehensive DDI coverage (requires BNF/Stockley's licensing)
- Scheduled watchdog for loop closure (requires platform event support)
- Multi-specialty referral routing with real directory APIs
- Real SMS/email/portal delivery
- Cross-organization A2A federation
- Multilingual patient outputs
- Voice-native clinician mode
- Predictive loop failure models
- HEDIS/MIPS emission hooks
- Adaptive learning from clinician edits

---

## Part 10: Execution Plan — How You Actually Build This

This is the step-by-step. Treat it as the shipping plan.

### Phase 0: Preflight (Day 0 — April 18, ~4 hours)

**Goal:** account, keys, tooling ready before any code.

1. Create Prompt Opinion account at app.promptopinion.ai (10 min)
2. Create Google AI Studio account; generate API key; save to `~/.signalloop-env` (10 min)
3. In Prompt Opinion: Configuration → Models → add Gemini key, load models, pick `gemini-2.5-flash-lite` as default; name it "SignalLoop Default" (15 min)
4. Sign up for ngrok, pay $10 for reserved domain (avoids URL rotation pain later); save domain like `signalloop.ngrok.app` (15 min)
5. Install Python 3.11+, Node 20+ (for TypeScript option), Docker Desktop (30 min)
6. Create two GitHub repos: `signalloop-medsafe-mcp` (Submission A), `signalloop-docs` (for Devpost content) (15 min)
7. Clone starting repos locally:
   ```
   git clone https://github.com/prompt-opinion/po-community-mcp
   git clone https://github.com/prompt-opinion/po-overview
   ```
   (10 min)
8. In Prompt Opinion, verify default general chat agent works by clicking "Configure an agent" and enabling it. Test one message in Launchpad (15 min)

**Difficulty:** trivial. Just admin.
**Risk:** low. Only risk is Google AI Studio quota; start with free, upgrade if needed.

### Phase 1: Synthetic Patient Reality (Days 1-2, ~8 hours)

**Goal:** Margaret, James, and Doris are in the FHIR server with the exact clinical reality the demo needs.

1. In Prompt Opinion, go to Patients → create or import Margaret
   - Use "Individually select patient" if sample patients exist
   - If not: manually add patient, then upload FHIR bundle
2. Build Margaret's full FHIR bundle in JSON:
   - `Patient` resource (age 72, F, etc.)
   - 4 `Condition` resources (T2DM, HTN, CKD3b, OA)
   - 4 `MedicationRequest` resources (lisinopril, furosemide, metformin, simvastatin)
   - 1 `AllergyIntolerance` (penicillin)
   - 3 `Observation` resources (eGFR trend: 58, 52, 42)
   - 3 `Observation` resources (creatinine trend matching)
   - 1 `DocumentReference` (clinical note about knee pain)
   - 1 `Encounter` resource (current visit, reason: knee pain followup)
3. Upload bundle to workspace via platform UI or API
4. Verify in Prompt Opinion: select Margaret in Launchpad, chat with default general agent, ask "Summarize this patient" — she should come back with her full clinical picture
5. Repeat abbreviated version for James (simple: age, no meds, normal eGFR, ankle sprain)
6. Repeat for Doris (RA, MTX, mild renal impairment, complex case)
7. **Write a reset script:** a bash script that deletes and re-uploads all three patients' bundles in one command. You'll need this during rehearsal when the demo state drifts.

**Difficulty:** medium. Requires FHIR knowledge. If you're new to FHIR, use a tool like Synthea (`https://synthetichealth.github.io/synthea/`) to generate a baseline bundle and modify it.
**Time:** 8 hours if FHIR-familiar; 12-16 hours if learning FHIR as you go.
**Risk:** medium. Getting the FHIR resources correctly linked (MedicationRequest.subject pointing to Patient, etc.) is fiddly. Test every upload.

### Phase 2: MedSafe MCP — Minimal Version (Days 3-5, ~20 hours)

**Goal:** MCP server running, registered in Prompt Opinion, two tools working end-to-end with real FHIR reads.

1. Copy `po-community-mcp/python` to your `signalloop-medsafe-mcp` repo as the starting point
2. Read the README carefully. Understand how the server handles initialize and how FHIR context is received
3. Implement initialize handler:
   - Return `capabilities.experimental.fhir_context_required.value = true`
   - Return `ai.promptopinion/fhir-context: {}` in extensions
   - Return 403 if the three headers aren't present on subsequent tool calls
4. Implement `normalize_medication` as the simplest possible tool:
   - Hardcoded dictionary of ~30 medications mapping raw text to dm+d codes
   - Include all of Margaret's meds plus ibuprofen, paracetamol, diclofenac, naproxen
   - Return structured JSON per the contract in Part 3
5. Implement `get_renal_trend`:
   - Parse SHARP headers to get FHIR server URL and patient ID
   - Call the FHIR server with a search on `Observation?patient={id}&code=LOINC:62238-1&_sort=-date`
   - Return structured JSON
6. Run locally (e.g., `uvicorn main:app --port 8080`)
7. Run `ngrok http 8080 --domain=signalloop.ngrok.app`
8. In Prompt Opinion: Configuration → MCP Servers → Add new
   - URL: `https://signalloop.ngrok.app/mcp`
   - Transport: streamable HTTP
   - Check FHIR context box when the option appears
   - Click test, verify tools list appears
9. Save, then attach MedSafe to your test BYO agent, and verify a chat like "What is Margaret's eGFR trend?" triggers the tool

**Difficulty:** medium-hard. First real integration work. Debugging headers between ngrok and local process can be painful.
**Time:** 20 hours (3 days). First tool might take 12 hours; second tool 8 hours as you understand the patterns.
**Risk:** high if you've never built an MCP server. Budget extra time.

**Pitfall to watch:** Gemini's JSON schema support has provider-specific quirks. When your tool returns JSON, test that Gemini parses it correctly. If it fails, simplify the schema.

### Phase 3: MedSafe Three-Phase Logic (Days 6-9, ~32 hours)

**Goal:** the full three-phase MedSafe architecture is working — Phase 1 builds patient profiles, Phase 2 runs deterministic rules parameterised by those profiles, Phase 3 synthesises patient-specific responses.

This is the heart of Submission A's AI Factor argument. Do not rush it.

**Phase 1 — Patient Risk Profile Building (~10 hours)**

1. Implement `build_patient_risk_profile(patient_id)`:
   - Reads full patient FHIR record (Patient, Conditions, MedicationRequest, AllergyIntolerance, recent Observations, Encounters)
   - Uses Gemini via a carefully-designed prompt to produce the structured profile JSON per the contract in Part 3
   - Prompt emphasises: weight factors by *relevance to medication safety*, produce reasoning traces, identify clinical context flags (frail elderly, polypharmacy, cardio-renal high risk, etc.)
   - Prompt constrains: never invent data not in the record, cite specific resources in reasoning traces
   - Caches the profile for the session (patient_id + timestamp key); rebuilds only on explicit refresh signal
2. Implement `get_relevant_context(signal_id)`:
   - Reads the profile from cache; if not present, builds it
   - Takes a signal and returns the subset of the profile relevant to that signal
   - LLM-assisted narrowing; rules-based filtering as fallback
3. Implement `get_renal_trend(lab_code, lookback_days)`:
   - Standard FHIR query on longitudinal Observations
   - Returns structured trend with trajectory and rate-of-change computed numerically
   - No LLM needed here — just math and structured output

**Phase 2 — Deterministic Rules (~10 hours)**

4. Implement `check_medication_safety(proposed_med_code, patient_risk_profile)`:
   - Pure Python. No LLM calls.
   - Receives the proposed medication code AND the patient risk profile as input parameters
   - Classifies proposed med into drug classes (NSAID, ACE-I, Diuretic, Statin, Biguanide, etc.)
   - Encodes these specific rules:
     - **Rule 1:** NSAID + eGFR < 60 (from profile) = CONTRAINDICATED · Established
     - **Rule 2:** NSAID + ACE-I + Diuretic (all present in profile's med inventory) = MAJOR · Established (triple whammy)
     - **Rule 3:** NSAID + age ≥ 65 (from profile) + chronic course = MODERATE · Established (Beers)
     - **Rule 4:** NSAID + allergy to NSAIDs (from profile) = CONTRAINDICATED · Established
     - **Rule 5:** Ibuprofen/naproxen dose > max daily = MAJOR
   - Uses the profile's `weighted_risk_factors` to calibrate severity (e.g., "critical" risk factor raises a MAJOR to CONTRAINDICATED)
   - Returns verdict, flags with citations, and — critically — a `profile_fields_consulted` list showing which parts of the profile drove the verdict (for audit)

**Phase 3 — Response Synthesis (~10 hours)**

5. Implement `synthesise_safety_response(verdict, patient_risk_profile)`:
   - LLM call. Takes deterministic verdict + rich profile.
   - Prompt emphasises: produce *patient-specific* narrative that cites actual chart facts, not generic warnings
   - Prompt emphasises: for each alternative, explain why it fits *this patient* given *their other medications* and *their specific clinical presentation*
   - Prompt emphasises: suggest concrete monitoring plans with timeframes
   - Output per contract: narrative, personalised alternatives with trade-offs, monitoring plans
6. Implement `analyse_override_reason(reason_text, verdict, profile)`:
   - LLM call. Takes free-text clinician override reason.
   - Classifies into enum (specialist_recommendation, short_course_trial, no_alternative, patient_preference, emergency)
   - Assesses clinical validity
   - Suggests mitigating monitoring plan
   - Structures the justification for AuditEvent storage

**Testing (~2 hours)**

7. Test against all three patients:
   - **Margaret + ibuprofen:** Phase 1 builds profile flagging sustained renal decline + triple-whammy meds; Phase 2 fires 3 flags (contraindication + triple-whammy + Beers) → BLOCK; Phase 3 produces Margaret-specific narrative referencing her decline rate and drug regimen
   - **James + ibuprofen:** Phase 1 profile shows healthy 42M; Phase 2 clean → PROCEED; Phase 3 returns minimal guidance
   - **Doris + naproxen:** Phase 1 profile shows rheumatology context, mild renal impairment; Phase 2 fires Major (not Contraindicated) → WARN; Phase 3 suggests short-course with monitoring; override path tested by user entering "rheumatology recommendation for flare" → `analyse_override_reason` produces structured justification

**Difficulty:** medium-hard. The rules engine is straightforward. The LLM prompt engineering for Phase 1 (producing a consistent, well-structured profile) and Phase 3 (staying grounded in profile facts without hallucinating) is where most time goes.
**Time:** 32 hours across 3-4 days.
**Risk:** medium. Biggest risks: (a) Phase 1 LLM inconsistency — the same patient producing different profiles on different runs; (b) Phase 3 LLM over-riding or second-guessing the deterministic verdict; (c) schema drift between phases. Mitigate by locking prompts early and writing golden-output tests.

### Phase 4: Referral Sub-System + Remaining Write Tools (Days 10-12, ~25 hours)

**Goal:** the referral sub-system's four tools work, plus all FHIR write drafting tools.

**Referral sub-system (~15 hours)**

1. Implement `assemble_specialty_packet(target_specialty, patient_id)`:
   - Define the nephrology profile in full detail: which FHIR resources matter, which are optional, what the referral question template looks like
   - Build specialty-aware filters that walk the patient record and extract matching resources
   - Implement missing-context detection: for each "required_input" in the profile, check if it's present and flag if not
   - Compute packet completeness score (weighted average of included required inputs)
   - Stub cardiology and rheumatology profiles at shallow depth (demonstrate extensibility without building)
2. Implement `rank_specialist_destinations(specialty, patient_id)`:
   - Hardcode three nephrologists in a JSON file with realistic attributes (name, site, distance, wait time, language, clinical focus)
   - Implement ranking logic: weighted sum across specialty subfit, wait time vs urgency, distance, language match, network status, clinical focus match
   - Return ranked list with rationale for each rank
   - The *ranking logic* is real; the directory data is seeded — state this clearly in the Devpost writeup
3. Implement `extract_consult_recommendations(document_reference_id)`:
   - Reads the `DocumentReference` content from FHIR
   - LLM call with a tightly-scoped prompt that extracts structured recommendation objects from free-text clinical notes
   - Output per contract: list of `{type, action, target, rationale, urgency}` objects
   - Flags urgent items separately
4. Implement `detect_plan_conflicts(extracted_recommendations, current_plan, patient_risk_profile)`:
   - LLM call combining the three inputs
   - Identifies conflicts: recommendation that contradicts current plan, recommendation that interacts with other active plan items
   - Produces a reconciled harmonised plan
   - Generates structured Task recommendations

**Remaining write tools (~10 hours)**

5. `draft_medication_request(action_payload)`:
   - Constructs FHIR MedicationRequest resource
   - POSTs to workspace FHIR server
   - Returns resource ID
6. `draft_followup_task(action_payload)`:
   - Constructs FHIR Task with due date, priority, and description
7. `draft_service_request(action_payload)`:
   - Constructs FHIR ServiceRequest with referral details, target specialty, and attached packet
8. `log_override(reason_payload)`:
   - Incorporates `analyse_override_reason` output into FHIR AuditEvent
   - Permanent record with structured justification

**Difficulty:** medium. Specialty packet logic requires careful data modelling. The LLM-driven consult extraction and conflict detection are prompt engineering problems, but the output contracts are strict so testing is straightforward.
**Time:** 25 hours across 3 days.
**Risk:** medium. Main risks: (a) the consult note extraction hallucinating recommendations not in the note; (b) conflict detection over-firing on non-conflicts. Mitigate with structured output schemas and golden-input tests.

### Phase 5: The Agent Configuration (Days 13-15, ~20 hours)

**Goal:** Submission B — the SignalLoop Renal Safety Agent — works end-to-end with all three-phase MedSafe calls and the referral sub-system.

1. In Prompt Opinion: Agents → BYO Agents → Add AI Agent
2. Configure:
   - **Name:** "SignalLoop Renal Safety Consult"
   - **Scope:** Patient
   - **Model:** Gemini 2.5 Flash-Lite (default)
3. **System prompt:** write a detailed prompt (500-700 words) implementing the 11-step orchestration from Part 4:
   - On patient open: proactively call `build_patient_risk_profile` and cache
   - Check for new renal signals via `get_renal_trend` and `get_relevant_context`
   - Produce interpretation per JSON schema
   - If referral indicated: proactively surface recommendation
   - When medication proposed: call `check_medication_safety` passing cached profile
   - If flags fire: call `synthesise_safety_response`
   - If override: call `analyse_override_reason` and `log_override`
   - If referral approved: call `assemble_specialty_packet`, `rank_specialist_destinations`, `draft_service_request`
   - If consult note returns: call `extract_consult_recommendations`, `detect_plan_conflicts`, `draft_followup_task`
   - Never generate safety verdicts itself; always defer to MedSafe MCP chain
   - Writes to FHIR only after user approval
   - Include `reconciliation_notes` field flagging chart/context mismatches
4. **Content collection:** create one collection per Part 4, attach to agent
5. **Response Format:** paste the expanded JSON schema from Part 4 into Response Format tab
6. **Tools:** attach MedSafe MCP server (all 14 tools exposed)
7. **A2A:** enable with one skill `renal_safety_consult`
8. **FHIR context:** enable, set to required
9. Save. Return to Launchpad. Select Margaret. Chat with SignalLoop agent.
10. Test the end-to-end flow per the demo script in Part 11:
    - "What should I know about Margaret today?" → profile built, brief produced, proactive nephrology recommendation surfaced
    - "Prescribe ibuprofen 400mg TDS" → three-phase MedSafe fires: check_medication_safety → synthesise_safety_response → BLOCK with patient-specific narrative and personalised alternatives
    - "Use paracetamol 1g QDS instead" → check_medication_safety clean, draft_medication_request writes
    - "Draft the nephrology referral" → assemble_specialty_packet, rank_specialist_destinations, draft_service_request
    - [pre-insert consult note] "Did nephrology respond?" → extract_consult_recommendations, detect_plan_conflicts, draft_followup_task

**Difficulty:** hard. The expanded orchestration with 14 tools is more complex to prompt than the minimal version. Gemini must call tools in the right order with the right arguments.
**Time:** 20 hours. Expect 3-4 major prompt revisions.
**Risk:** high. This is where hackathon agents most often fall apart. Specific failure modes: (a) agent skips `build_patient_risk_profile` and calls `check_medication_safety` without a profile; (b) agent generates its own safety verdict instead of deferring; (c) JSON schema validation failures; (d) agent invents specialist directory data instead of calling `rank_specialist_destinations`. Mitigate with explicit prompt constraints and fallback error handling.

**Key trick:** Gemini 2.5 Flash-Lite with JSON mode can be rigid. If outputs break schema repeatedly, consider upgrading to regular 2.5 Flash (more capable, still cheap) for the agent's LLM. The cost difference at hackathon scale is trivial.

### Phase 6: FHIR Writes End-to-End (Days 16-17, ~12 hours)

**Goal:** approved actions produce real FHIR writes visible in Prompt Opinion.

1. Test the full demo flow manually, watching FHIR server state change after each action
2. For each write target:
   - Verify the resource appears in Prompt Opinion's patient view
   - Verify IDs link correctly (MedicationRequest.subject → Patient)
   - Verify AuditEvent captures overrides
3. Create a view query or skill that shows "active loops" for the patient:
   - The agent can query `Task` resources and summarize them as a markdown table
   - This replaces the "Loop Control Tower" from blue-sky with an on-demand query
4. Pre-stage the "consult note returned" scenario:
   - Create a `DocumentReference` for Margaret's nephrology consult
   - Keep it as a separate JSON file
   - Write a bash script that POSTs it to the FHIR server during demo

**Difficulty:** easy-medium.
**Time:** 12 hours.
**Risk:** low if Phase 4 went well.

### Phase 7: Demo Rehearsal (Days 18-20, ~18 hours)

**Goal:** you can record a clean 3-minute demo in one take.

1. Write the demo script word-for-word. Target: 2:45-2:55 (under 3:00 with buffer). See Part 11 for the script outline.
2. Run through the demo cold. Time it.
3. Identify where the agent misbehaves. Fix the system prompt.
4. Run the patient-reset script. Retest.
5. Repeat until you can do the full demo in one clean take 3 times in a row.
6. Record a trial video. Watch it back. Edit mental notes.
7. Prepare the "6 days later" transition: the DocumentReference insertion script needs to run cleanly.

**Difficulty:** medium. The hidden work here is making the system prompt robust enough that the demo works on the 10th run, not just the first.
**Time:** 18 hours.
**Risk:** medium-high. Demos break. Allocate time.

### Phase 8: Marketplace Publishing (Days 21, ~8 hours)

**Goal:** both submissions are live in the Prompt Opinion Marketplace and validated by a fresh user.

1. In Prompt Opinion: Marketplace Studio → Publish MCP Server (MedSafe)
   - Title: "SignalLoop MedSafe — Renal Prescribing Safety"
   - Description: (use the positioning from Part 1)
   - Category: Superpower / MCP
2. Publish Agent (SignalLoop Renal Safety Consult)
   - Title: "SignalLoop — Renal Signal Safety Consult"
   - Description: (use the positioning from Part 1)
   - Category: Agent / A2A
3. Create a second Prompt Opinion account for testing
4. From the fresh account, search Marketplace for both submissions
5. Install them, select Margaret, and run the demo flow from the fresh account
6. Fix anything that breaks when a user who isn't you runs it
7. Verify from the fresh account's perspective that:
   - MedSafe can be attached as a tool to any agent
   - SignalLoop can be consulted from any BYO agent

**Difficulty:** easy, but tedious.
**Time:** 8 hours.
**Risk:** medium. Publishing processes sometimes have review delays or validation errors. Do this 4+ days before deadline.

### Phase 9: Final Video + Devpost Submission (Days 22-23, ~12 hours)

**Goal:** polished submission live on Devpost before deadline.

1. Record final video (2:45-2:55), at least 2 takes
2. Edit for any rough spots, keep under 3:00
3. Write Devpost submission:
   - Inspiration (the referral/safety loop problem, personal angle if applicable)
   - What it does (product positioning from Part 1)
   - How we built it (architecture diagram, tech stack, standards compliance, three-phase MedSafe, referral sub-system)
   - Challenges we ran into (show you understand the hard parts)
   - What we learned (e.g., narrow scope, rules-vs-LLM split, three-phase pattern)
   - What's next (the roadmap from Part 9)
   - Built with: Python, Gemini, MCP, A2A, FHIR, dm+d, Prompt Opinion
4. Links: GitHub repo (MedSafe), Marketplace URLs for both submissions, video
5. Submit 24+ hours before deadline. Not 1 hour before.

**Difficulty:** easy.
**Time:** 12 hours.
**Risk:** low if pacing was right.

### Phase 10: Buffer (Day 24 — May 10)

**Goal:** fix one unexpected thing.

Everything you budgeted for Day 24. Something will break at the last minute. That's what this day is for.

---

## Part 11: The Demo Script Outline (3 minutes)

| Time | Act | User action | System response |
|---|---|---|---|
| 0:00-0:15 | Open | Select Margaret in Launchpad, open SignalLoop agent | Agent auto-loads, builds patient risk profile (Phase 1) in background |
| 0:15-0:45 | Context | "What should I know about Margaret today?" | Brief with reconciliation note, eGFR trend, why it matters *for this patient specifically* (patient risk profile surfaces) |
| 0:45-1:10 | Proactive referral surfaced | — | Agent proactively: "Given sustained decline under NICE NG203 §1.4, nephrology review is indicated. Flag for later?" User: "Yes, flag it." |
| 1:10-1:50 | **MedSafe moment** | "Prescribe ibuprofen 400mg TDS for knee pain" | Three-phase MedSafe fires: Phase 2 BLOCK with 3 flags; Phase 3 delivers patient-specific narrative + personalised alternatives with trade-offs |
| 1:50-2:05 | Recover | "Use paracetamol 1g QDS instead" | Clean MedSafe; MedicationRequest written; follow-up Task queued (check LFTs at 3 months per Phase 3 monitoring suggestion) |
| 2:05-2:30 | Loop open | "Now draft that nephrology referral" | Specialty-specific packet assembled (eGFR trend, BP history, current ACE-I dose, medication list); **missing-context flag:** "No urine ACR in 12 months — consider ordering"; three ranked specialists shown; user selects Dr Patel; ServiceRequest + Communication written |
| 2:30-2:45 | Time jump + return | *[cut] "6 days later"* — pre-insert consult note as DocumentReference. User: "Did nephrology respond?" | `extract_consult_recommendations` parses note; `detect_plan_conflicts` flags ACE-I stop affects BP plan; reconciled next steps produced; Tasks created |
| 2:45-2:55 | Close | — | Tagline slate: "Context in. Verified action out. Loop closed." |

This script demonstrates all three differentiators in sequence: the three-phase MedSafe (the hero moment at 1:10), the proactive referral identification (0:45), the specialty-specific packet with missing-context flag (2:05), and the rich return-handler with conflict detection (2:30). Each is a distinct, credible capability shown for ~20 seconds.

---

## Part 12: Difficulty and Time Summary

Hours have been updated to reflect the MedSafe three-phase architecture (added ~8 hours in Phase 3) and the referral sub-system expansion (added ~13 hours in Phase 4):

| Phase | Days | Hours | Difficulty | Risk |
|---|---|---|---|---|
| 0: Preflight | 1 | 4 | Trivial | Low |
| 1: Patients | 2 | 8-16 | Medium | Medium |
| 2: MCP minimal | 3 | 20 | Medium-hard | High |
| 3: MedSafe three-phase logic | 3-4 | 32 | Medium-hard | Medium |
| 4: Referral sub-system + remaining write tools | 3 | 25 | Medium | Medium |
| 5: Agent config | 3 | 20 | Hard | High |
| 6: FHIR writes end-to-end | 2 | 12 | Easy-medium | Low |
| 7: Rehearsal | 3 | 18 | Medium | Medium-high |
| 8: Publishing | 2 | 8 | Easy | Medium |
| 9: Video + submit | 3 | 12 | Easy | Low |
| 10: Buffer | 1 | — | — | — |
| **Total** | **24** | **159-167** | — | — |

The expanded scope adds ~25 hours compared to the original estimate. This is significant. Three implications:

**Solo full-time builder:** achievable with disciplined 7-hour days. Budget conservatively.
**Solo part-time (3-4 hours/day):** the original plan was already tight; the expanded version requires aggressive feature deferral. Cut Patient C from the demo set and defer override-reason analysis (`analyse_override_reason`) to post-hackathon if time slips.
**Two-person team:** still comfortable. Person 1 owns MCP (Phases 2-4), person 2 owns Agent + rehearsal (Phases 5, 7, 9). Converge on Phase 6 writes together.

### The hardest parts (pay attention)

1. **Phase 2 — MCP server initialize handler with FHIR context headers.** If you've never built MCP, the first day will feel impossible. Power through.
2. **Phase 3 — The three-phase MedSafe orchestration.** Phase 1 profile building is substantive prompt engineering. Phase 3 synthesis needs careful prompting so it doesn't override the deterministic verdict. The three phases must chain cleanly without the LLM second-guessing the rules engine. Budget serious iteration time.
3. **Phase 5 — Getting Gemini to reliably call tools in the right sequence and produce schema-valid JSON.** The expanded schema (with `proactive_referral`, `referral_packet`, `returned_consult_handling`) is more complex than the minimal version. Start with a trimmed schema and grow it.
4. **Phase 7 — Demo reliability under reset.** The 10th rehearsal run must work as well as the 1st. With more capabilities shown in the demo, the surface area that can break increases.

### The easiest parts

1. **Phase 0 — Preflight.** Just admin.
2. **Phase 6 — FHIR writes end-to-end.** Once MCP and Agent work, these are just CRUD operations against the workspace FHIR server.
3. **Phase 9 — Video + submit.** By then you know the demo cold.

### Scope cut priorities if time slips

If you hit Day 15 and realise you won't make it:

1. **First cut:** `analyse_override_reason` tool and Patient C's override demo scene. Saves ~6 hours.
2. **Second cut:** `detect_plan_conflicts` tool; replace with simple "extracted recommendations → Tasks" flow. Saves ~4 hours.
3. **Third cut:** Specialist ranking; show a single recommended destination. Saves ~3 hours.
4. **Do not cut:** the three-phase MedSafe architecture itself. That's the AI Factor differentiator.
5. **Do not cut:** proactive referral identification. That's what makes SignalLoop different from a reactive assistant.

If you're ahead of schedule at Day 18, **do not add scope.** Invest extra time in rehearsal and in judge-facing polish (Devpost writeup, agent descriptions, README clarity).

---

## Part 13: Required External References (read these during build)

These three documents describe **what** to build but not line-by-line **how**. During each phase, you (or a fresh Claude Code / Codex session) must read the following external sources to translate specs into working code.

**Always read these before writing code:**

1. **`po-community-mcp` README and sample code** — `https://github.com/prompt-opinion/po-community-mcp`
   - Python branch is the starting point for MedSafe MCP (Submission A)
   - Shows how initialize is handled, how SHARP headers are received, transport setup
   - Read this before Phase 2; reread when adding each new tool

2. **Prompt Opinion docs** — `https://docs.promptopinion.ai/`
   - `fhir-context/mcp-fhir-context` — extension declaration format, exact header names
   - `fhir-context/a2a-fhir-context` — A2A payload shape
   - `agents/byo-agents` — system prompt variables, JSON response format, A2A skills, tool attachment
   - `agents/agent-scopes` — Patient vs Workspace vs Group
   - `agents/external-agents` — only relevant if you change architecture
   - Read before Phase 2 and Phase 5 especially

3. **SHARP-on-MCP specification** — `https://www.sharponmcp.com/key-components.html`
   - Canonical source for header schema and extension declaration
   - Clarifies auth models

4. **FHIR R4 specification** — `https://hl7.org/fhir/R4/`
   - `MedicationRequest` — `hl7.org/fhir/R4/medicationrequest.html`
   - `Task` — `hl7.org/fhir/R4/task.html`
   - `ServiceRequest` — `hl7.org/fhir/R4/servicerequest.html`
   - `Communication` — `hl7.org/fhir/R4/communication.html`
   - `AuditEvent` — `hl7.org/fhir/R4/auditevent.html`
   - `Observation` — `hl7.org/fhir/R4/observation.html`
   - Read the specific resource spec before writing code that creates or reads it

5. **A2A protocol v0.3 docs** — `https://a2a-protocol.org/`
   - Only needed if you debug agent card or extension mechanics
   - Prompt Opinion currently uses v0.3 (not v1)

**How to use these when starting a new session:**

When you drop these three project docs into a fresh Claude Code / Codex / chat session, include this instruction in the opening message:

> *"I am building SignalLoop per the attached Master Spec, Implementation Plan, and Final Operational Plan. We are currently on Phase [X]. Before writing code, please read the relevant external references listed in Part 13 of the Final Operational Plan — particularly the po-community-mcp README, the Prompt Opinion docs for the specific feature I'm working on, and the FHIR R4 spec for any resource I'm reading or writing. Guide me through Phase [X] step by step, writing code where appropriate."*

This instruction tells the new session to ground in primary sources rather than hallucinate API shapes.

**Platform quirks log (build it as you go):**

After Phase 2, start a `QUIRKS.md` file in your repo. Every time you hit platform behavior not documented anywhere — a specific error code, a Gemini JSON schema limitation, an ngrok + Prompt Opinion interaction — write it down. Paste this file into future sessions alongside the three project docs. The quirks file compounds rapidly in value.

---

## Part 14: What You Do Tomorrow (Day 0)

Four hours of focused work:

1. Create Prompt Opinion account (10 min)
2. Create Google AI Studio key (10 min)
3. Configure Gemini 2.5 Flash-Lite in Prompt Opinion (15 min)
4. Pay for ngrok reserved domain (15 min)
5. Install Python 3.11+ and verify (15 min)
6. Create `signalloop-medsafe-mcp` GitHub repo (10 min)
7. Clone `po-community-mcp` locally (10 min)
8. Open `po-community-mcp/python/README.md` and read it end-to-end (30 min)
9. Run the default sample MCP server locally (30 min)
10. Register it in Prompt Opinion via ngrok and verify the default tools appear (30 min)
11. Chat with a test BYO agent, verify a tool call fires (30 min)
12. Save everything to GitHub with a clean first commit (15 min)

End of Day 0: you have a working, registered, empty MCP server that the platform can talk to. From there, every phase is incremental capability.

---

*This is the frozen operational plan. The master spec remains the north star. Deviation from this plan should be deliberate, logged, and pushed to the roadmap document.*

*Ship.*
