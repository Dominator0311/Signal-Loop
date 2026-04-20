# SignalLoop — Master Specification (Blue Sky)

*Merged from two iterations. North-star vision. Time and complexity are not constraints in this document — scoping comes later.*

---

## 0. The Product in One Sentence

**SignalLoop is a context-aware clinical signal-to-action platform: it captures patient reality in natural language, interprets new clinical findings in the specific context of that patient, runs a deterministic medication safety gate before any prescribing action, drafts the next verified step for clinician approval, and tracks every resulting loop until it actually closes — with MCP, A2A, and FHIR/SHARP as the backbone throughout.**

### Core Product Promise

**Context in. Verified action out. Loop closed.**

More specifically:
- Turn patient speech, images, and reports into structured clinical context
- Interpret new signals in the context of history, medications, allergies, prior trends, and visit intent
- Convert interpretation into a concrete next-step draft
- Apply a medication safety gate before finalization
- Trigger and track downstream work until a success condition is met

---

## 1. Positioning

### The Last Mile problem it solves
Most healthcare AI stops at insight. SignalLoop goes all the way to *verified action with loop closure*. This is exactly the gap Prompt Opinion explicitly defines as "The Last Mile."

### What makes it non-generic

The differentiator is **not**:
- "we can read FHIR"
- "we use MCP"
- "we use A2A"
- "we summarize reports"

Prompt Opinion already gives builders infrastructure for open standards, FHIR-grounded workflows, reusable tools, and multi-agent coordination. Builders are expected to add the differentiated logic on top.

SignalLoop's differentiated layer is:

**patient-specific relevance selection + next-step drafting + safety gating + loop closure**

Most demos pick one of: patient summarization, report simplification, interaction checking, or referral scheduling. SignalLoop sequences all four into a single workflow where each stage's output is the next stage's input, where the AI does the *contextual* work and rules do the *safety* work, and where every output ends in an auditable clinician-approved action — not just a chatbot answer.

### The 5Ts it delivers
Every stage produces at least three of Consultation, Document, Table, Transaction, Task. The overall product hits all five, multiple times. See §9 for the explicit mapping.

---

## 2. Users and Buyers

### Primary user
The ambulatory clinician making a decision: PCP, outpatient specialist, urgent care clinician, care coordinator.

### Secondary users
- **Patient** — front-end intake, plain-language results
- **Care coordinator** — loop monitoring, escalation
- **Clinical operations lead** — cohort dashboard, loop analytics
- **Medical director / CMIO** — audit, governance view

### Buyer persona
Health system CMIO, multi-specialty clinic operations lead, ACO quality director, or integrated delivery network looking at referral leakage, diagnostic loop closure, and documentation burden as line items they're already paying for.

---

## 3. Trigger Model

SignalLoop is **event-driven**, not chat-driven. Triggers include:

- **Patient initiated** — patient completes intake ahead of visit
- **Result arrival** — new DiagnosticReport or Observation lands
- **Document arrival** — external note, consult letter, or report ingested
- **Chart open** — clinician opens a patient chart, context is assembled
- **Clinician initiated** — clinician types a candidate medication or action
- **Scheduled** — watchdog runs over open loops looking for overdue closures

SignalLoop is never "chat with the record." It is a workflow that fires on real clinical events and produces real clinical artifacts.

---

## 4. System Architecture

### Layered view

```
┌───────────────────────────────────────────────────────────────┐
│  PRESENTATION LAYER                                           │
│  Clinician Workspace · Patient Intake UI · Cohort Tower       │
└───────────────────────────────────────────────────────────────┘
                              ▲
┌───────────────────────────────────────────────────────────────┐
│  ORCHESTRATION LAYER                                          │
│  Orchestrator Agent · Session State · SHARP Context · Audit   │
└───────────────────────────────────────────────────────────────┘
                              ▲
┌───────────────────────────────────────────────────────────────┐
│  STAGE AGENTS (A2A)                                           │
│  Intake · Context · Signal · Trend · MedSafe · Action · Loop  │
└───────────────────────────────────────────────────────────────┘
                              ▲
┌───────────────────────────────────────────────────────────────┐
│  MCP TOOLBOX                                                  │
│  FHIR R/W · Med Normalizer · Interactions · OCR · Scheduling  │
│  Guidelines · Evidence · Notification · Audit Logger          │
└───────────────────────────────────────────────────────────────┘
                              ▲
┌───────────────────────────────────────────────────────────────┐
│  DATA LAYER                                                   │
│  FHIR Server · dm+d / RxNorm · BNF / Stockley's · Guidelines  │
└───────────────────────────────────────────────────────────────┘
```

### Agent vs Tool distinction

**Agents** handle reasoning, adaptation, and coordination. They are A2A-enabled and can call each other.

**Tools** are deterministic MCP servers that do one thing well — normalize a medication, check an interaction, write a FHIR resource, send a notification. They are the plumbing the rest of the Prompt Opinion ecosystem can reuse.

This distinction matters for submission strategy (§12): MedSafe can be extracted as a standalone MCP Superpower submission while the rest of SignalLoop is an A2A Agent submission.

---

## 5. The Seven Stages

### Stage 1 — Intake Capture

**Purpose:** convert messy patient reality into a structured, reviewable clinical draft.

**Inputs:**
- Patient voice or text (adaptive conversation, not a form)
- Medication photos (packaging, blister packs, prescription labels)
- External report uploads (PDF, image)
- Prior history card if returning patient
- EHR demographic and registration data

**Agents:**
- **Conversation Agent** — drives short, adaptive dialogue. One question at a time. Branches on answers. Recognizes clinical urgency and can break flow.
- **Transcription Agent** — if voice, transcribes with medical-terminology model
- **Image Agent** — OCR on med and report photos, resolves to candidate coded entities
- **Extraction Agent** — parses dialogue into candidate FHIR resources (Condition, MedicationStatement, AllergyIntolerance, Observation, Encounter.reasonCode)
- **Reconciliation Agent** — compares extractions against existing FHIR chart; surfaces conflicts rather than silently overwriting
- **Red-Flag Agent** — deterministic checks for clinical urgency (chest pain, stroke symptoms, suicidal ideation); escalates outside normal flow

**MCP tools used:** `fhir.read_patient_bundle`, `fhir.draft_write`, `med.normalize`, `image.ocr_medication`, `image.ocr_document`

**Output schema — every extracted field carries one of four states:**

- **Confirmed** — patient stated clearly, high extraction confidence, no conflict with chart
- **Needs review** — low-confidence extraction, or OCR ambiguity, or patient phrasing that resolved to multiple candidates
- **Conflict with chart** — contradicts existing chart data (e.g., patient says they stopped a medication that the chart shows as active); never silently overwrites
- **Missing but potentially important** — clinically relevant field the patient didn't mention and the chart doesn't contain, surfaced for the clinician to probe

This taxonomy is the product's statement about itself: the AI is not summarizing, it is *reconciling*. Every piece of patient data has explicit provenance and a confidence state. A summary can be wrong quietly; a reconciliation surfaces its uncertainty.

**Outputs:**
- **Intake Draft Card** (Document) — structured summary with "patient says" quotes; every field tagged with one of the four states above
- **Reconciliation Table** (Table) — explicit conflicts between patient statement and chart
- **Missing-info prompts** (Consultation)
- **Red-flag alerts** (Task) — urgent items requiring immediate attention
- **Candidate chart writes** — staged, never auto-committed

**UX rules:**
- Adaptive conversation, never a giant form
- Median intake: 3–5 minutes
- Nothing commits without clinician review
- Patient can skip any question

---

### Stage 2 — Context Aggregation

**Purpose:** build the minimum relevant context packet for *this specific signal in this specific patient*.

This is the most AI-differentiated stage and should be treated as such. The product's defensibility lives here.

**Inputs:** Intake draft, full FHIR record, triggering signal (if any), reason for visit, recent clinical activity.

**Agents:**
- **Relevance Agent** — the single most important agent in the system. Decides what subset of the chart matters for this signal and this visit. Not summarization — *selection*.
- **Evidence Retrieval Agent** — pulls guideline references and reference-range adjustments for patient context
- **Comorbidity Agent** — identifies active and relevant conditions that should frame interpretation
- **Medication Context Agent** — identifies drugs that might affect interpretation (statins + ALT; ACE inhibitors + creatinine; steroids + glucose)
- **History Synthesis Agent** — produces a short "what matters from the chart" narrative in clinician voice

**Example of what selection looks like:**
- Abdominal pain + abnormal LFTs → prior LFTs, alcohol history, hepatotoxic meds, RUQ imaging, hepatitis status
- Chest symptoms + D-dimer elevation → cardiopulmonary history, anticoagulants, recent immobilization, recent surgery
- Low Hb on CBC → prior Hb trend, iron studies, renal function, anticoagulants, GI history

**MCP tools used:** `fhir.get_conditions`, `fhir.get_longitudinal_observations`, `fhir.get_active_medications`, `fhir.get_procedures`, `fhir.get_documents`, `evidence.lookup`, `guideline.lookup`

**Outputs:**
- **Context Pack** (Document + Table) — selected conditions, meds, prior results, with rationale for what was selected
- **Explanation of selection** — "I pulled these because..." always visible
- **Missing-context alerts** — items that would strengthen interpretation but aren't in the record

---

### Stage 3 — Signal Interpretation

**Purpose:** interpret the new signal in the context built by Stage 2.

**Inputs:** triggering signal, Context Pack, prior interpretations of similar signals for this patient, reason for visit.

**Agents:**
- **Lab Interpreter Agent** — numeric observations; newly abnormal vs chronically abnormal vs meaningful clusters
- **Radiology Interpreter Agent** — imaging reports; extracts findings, impression, and embedded follow-up recommendations (the incidental nodule that needs 6-month CT)
- **Pathology Interpreter Agent** — path reports; key findings and recommended next steps
- **Document Interpreter Agent** — external consult notes and discharge summaries; extracts recommendations and unresolved questions
- **Reasoning Synthesizer** — combines all interpretation output into a structured object with explicit reasoning
- **Dual-Output Agent** — from the same reasoning, generates both a clinician brief and a patient explanation (patient version only surfaces after clinician approval)

**Structured interpretation object (the core data contract):**

```json
{
  "signal_id": "DiagnosticReport/12345",
  "findings": [
    {
      "finding": "eGFR 42 mL/min/1.73m²",
      "raw_flag": "low",
      "contextualized_flag": "concerning_change",
      "why_it_matters_for_this_patient": "Patient has T2DM and hypertension;
        prior eGFR 58 three months ago; currently on lisinopril and 
        ibuprofen PRN. Rate of decline exceeds expected.",
      "evidence_refs": ["NICE NG203 §1.3.2"],
      "proposed_action_candidates": [
        "repeat_renal_function_2_weeks",
        "review_nsaid_use",
        "nephrology_referral_if_sustained"
      ],
      "confidence": 0.82,
      "uncertainty_sources": ["no prior eGFR in last 6 months"]
    }
  ],
  "overall_urgency": "routine_but_important",
  "incidentalomas": [],
  "stable_chronic_findings": [],
  "clinician_brief_required": true,
  "patient_explanation_required": true,
  "trend_analysis_required": true,
  "medication_review_triggered": true,
  "referral_candidate": "nephrology_if_sustained"
}
```

This object is auditable, reviewable, and machine-checkable. Malformed responses are rejected by schema.

**MCP tools used:** `fhir.get_longitudinal_observations`, `evidence.lookup`, `guideline.lookup`, `reference_ranges.get_context_adjusted`

**Outputs:**

The Dual-Output Agent generates two distinct documents from the same reasoning core, tuned for completely different audiences. These are not summaries of each other — they are two separate artifacts from a shared interpretation.

**Clinician Brief** (Document + Table — crafted as a distinct artifact, not a JSON dump)

A compact, high-signal document:
- Top findings ranked by relevance *for this patient*
- Why each matters in this specific clinical context
- Prior trend snippet with annotated events
- Action candidates with rationale
- Uncertainty and missing-context flags
- Evidence citations inline

The brief is dense, technical, and assumes clinical vocabulary. It is optimized for a clinician with 90 seconds.

**Patient Explanation** (Document — released only after clinician approval)

A plain-language, reading-level-controlled document:
- What was found, in everyday terms
- What it may mean for the patient
- What happens next
- When to seek urgent help
- Reassurance where warranted — but never false reassurance

The patient version is calm, clear, and never alarming unless alarm is warranted. It is never shown to the patient until the clinician has approved both the interpretation and the release.

**Structured Interpretation Object** — the shared reasoning core, passed downstream to Stages 4–7

The dual-document output directly serves two of Prompt Opinion's 5Ts (Document and Consultation) and makes the product visibly useful to both clinician and patient from the same underlying intelligence.

---

### Stage 4 — Trend Analysis

**Purpose:** answer "is this changing? In what direction? How fast?"

Runs in parallel with Stage 3 when the signal is a repeat of a prior measurement.

**Inputs:** current values, prior measurements, timestamps, event context (medication starts, interventions).

**Agents:**
- **Trajectory Agent** — baseline, delta, rate of change, persistence, oscillation, recovery patterns
- **Annotation Agent** — overlays clinical events on the trend (medication started, procedure performed) so patterns become interpretable
- **Outlier Detection Agent** — flags values outside the patient's own baseline, not just outside population norms

**MCP tools used:** `fhir.get_longitudinal_observations`, `fhir.get_medication_history`, `fhir.get_procedures`

**Outputs:**
- **Trend Panel** (Table + Document) — sparkline or compact graph, annotated with clinical events, with natural-language interpretation ("eGFR declining 4 points/month since lisinopril started; consider medication review")

---

### Stage 5 — MedSafe Gate

**Purpose:** interrupt prescribing and medication-change actions with a context-aware, deterministic safety check *before* anything commits.

This is a **gate**, not a banner. The clinician cannot finalize a MedicationRequest without either passing MedSafe or entering an explicit override with reason (logged to AuditEvent).

**Trigger:** any proposed medication change from Stage 6 or direct clinician input.

**Inputs:** proposed meds (name, dose, route, frequency, duration), current med list (coded), AllergyIntolerance list, active Conditions, relevant labs (eGFR, LFTs, electrolytes), age, weight, pregnancy status, recent Stage 3 results.

#### Three-phase architecture

MedSafe runs as three distinct phases. The middle phase is deterministic; the outer two use AI for what AI genuinely does well. This is the architectural guarantee that makes MedSafe both trustworthy and genuinely AI-enabled.

**Phase 1 — Patient Risk Profile Building (LLM)**

The AI analyses full patient context — demographics, active conditions, current medications, allergies, prior adverse reactions, relevant labs, recent clinical activity, physiological factors (age, weight, renal function, hepatic function, pregnancy status) — and builds a structured patient-risk profile.

This is substantive generative work. The LLM is not just summarising the chart; it is identifying and weighting the factors that matter for medication safety decisions for this specific patient, producing a structured profile with reasoning traces. A rules engine cannot do this — it has no mechanism for deciding which of 400 chart facts are relevant to prescribing safety.

The profile is cached per patient per session; it does not rebuild on every prescription attempt.

Profile output includes:
- Weighted risk factors (e.g., "eGFR 42 with rapid decline — high relevance to renal-risk prescribing")
- Active medication class inventory with interaction-relevant properties
- Allergy and cross-reactivity profile
- Age/weight/organ-function-derived dosing considerations
- Clinical context flags (pregnancy, breastfeeding, frail elderly, polypharmacy)
- Reasoning trace for why each factor was included

**Phase 2 — Deterministic Safety Check (Rules)**

The rules engine receives the proposed medication and the Phase 1 patient-risk profile. It runs a series of deterministic checks:

- Drug-drug interactions (from licensed content: BNF / Stockley's in UK, First Databank or equivalent in US)
- Allergy and cross-reactivity conflicts (penicillin ↔ cephalosporin, sulfa cross-class, etc.)
- Renal dosing (eGFR-adjusted)
- Hepatic dosing (Child-Pugh-adjusted)
- Age-specific cautions (Beers criteria for elderly, STOPP/START)
- Pregnancy/lactation categories
- Duplicate therapy
- Dose-range plausibility
- Drug-disease contraindications

Critically, because the rules engine is *parameterised by the Phase 1 patient-risk profile*, the checks are patient-specific without being AI-dependent. The same drug pair might fire a Major warning for one patient and a Minor flag for another, based on Phase 1's profile, while the *decision logic* stays deterministic and auditable.

No LLM is involved in Phase 2. Every verdict traces to a specific rule with a specific evidence source.

**Phase 3 — Response Synthesis (LLM)**

The AI takes the Phase 2 verdict and the Phase 1 profile and synthesises the clinical-grade response:

- **Patient-specific risk narrative** — not "CONTRAINDICATED. NSAID + eGFR 42" but "Margaret's kidney function has declined 16 points over 3 months with no intervention explaining the drop. She's already on the two medications that form two legs of the triple-whammy — adding an NSAID is the specific combination that causes 10-15% of AKI admissions in this demographic..."
- **Personalised alternatives with trade-offs** — not just a list, but reasoning about which alternative fits *this* patient given *their* other medications and *their* clinical presentation
- **Monitoring plans** if proceeding — LFTs at 3 months if paracetamol long-term, etc.
- **Override-reason analysis** — when a clinician overrides, the AI analyses the reason, determines whether it represents valid clinical context, and suggests mitigating monitoring

Phase 3 is where AI earns its AI-Factor credit: it turns deterministic output into clinically-actionable, patient-specific prose that a rules engine fundamentally cannot produce.

#### Why this architecture is stronger than "AI wraps rules"

A traditional "AI explains rules" design has the LLM downstream of the rules, adding a narrative layer on top of a flat drug-pair lookup. The three-phase design puts the LLM on both sides: *before* rules (understanding the patient), *after* rules (explaining in patient-specific terms). The deterministic core is still the source of truth for safety verdicts, but the whole pipeline is context-aware in a way flat rules cannot be.

This mirrors how expert clinical pharmacists actually think:
1. Build mental model of the patient
2. Look up the specific interaction/rule
3. Contextualise the answer and propose alternatives

#### Severity matrix (locked)

|                    | Established | Probable          | Suspected | Theoretical |
|--------------------|-------------|-------------------|-----------|-------------|
| **Contraindicated** | Blocks order | Warning + override | Warning  | Info        |
| **Major**          | Warning + override | Warning     | Info      | Info        |
| **Moderate**       | Warning     | Info              | Info      | Silent      |
| **Minor**          | Info        | Info              | Silent    | Silent      |

Only Contraindicated + Established blocks outright. Calibration is what makes this gate actually get used rather than banner-blinded.

**Agents:**
- **Profile Builder Agent** (Phase 1, LLM) — constructs structured patient-risk profile
- **Normalization Agent** (thin wrapper over Med Normalizer tool)
- **Interaction Engine** (Phase 2, deterministic — not an agent, a rules engine behind an MCP tool)
- **Response Synthesiser Agent** (Phase 3, LLM) — produces patient-specific narrative, alternatives, monitoring
- **Override Analyser Agent** (Phase 3, LLM) — when override used, analyses reason and suggests mitigation

**MCP tools used:** `build_patient_risk_profile`, `normalize_medication`, `check_medication_safety`, `synthesise_safety_response`, `analyse_override_reason`, `dosing.check_renal`, `dosing.check_hepatic`, `allergy.cross_reactivity`, `guideline.age_specific`, `pregnancy.category_lookup`

**Outputs:**
- **MedSafe Review Card** (Document + Table) — flags ranked by severity with patient-specific narrative, personalised alternatives with trade-offs, monitoring suggestions
- **Patient Risk Profile** (Document) — the Phase 1 artifact, itself valuable as a reusable context object other tools can query
- **Override record** if clinician proceeds — AI-analysed reason permanently logged with mitigation suggestions (Consultation + Task)
- **MedicationRequest write** if clean or overridden (Transaction)

---

### Stage 6 — Action Composition

**Purpose:** convert interpretation into a concrete proposed action for clinician verification.

**Inputs:** Clinician Brief, Trend Panel, MedSafe outputs (if medication involved), urgency, local workflow pathways, formulary, patient preferences if captured.

**Agents:**
- **Action Composer Agent** — generates candidate action plan from interpretation
- **Prerequisite Checker Agent** — identifies missing inputs (e.g., TSH before thyroid med change)
- **Formulary Agent** — checks if proposed meds are on the org's formulary
- **Patient Message Agent** — drafts patient-facing communication
- **Care Pathway Agent** — aligns proposed actions with local care pathways

**Candidate action types:**
- Repeat labs
- Repeat imaging
- Follow-up appointment
- Medication start / change / stop
- Specialist referral
- Urgent escalation
- Watchful waiting + patient education
- Care coordinator task

**Output bundle (all five 5Ts):**
- **Proposed plan** (Document)
- **Ranked alternatives** (Table)
- **Patient message draft** (Document)
- **Missing prerequisites** (Task)
- **Order/referral/task drafts** (Transaction candidates — not yet written)
- **Rationale snippet** — why these options, in order

**Clinician decision points:** approve as-is, approve with edits, reject with reason, defer, escalate.

No autonomous execution of consequential actions. Ever.

---

### Stage 7 — Loop Closure

**Purpose:** ensure actions that require downstream completion actually complete.

This is what makes the product operationally real rather than just analytically clever. Referral loop closure specifically is treated as a first-class capability because (a) documented loop-closure rates of 35–65% in ambulatory primary care represent a major patient-safety gap, (b) referral leakage has measurable financial impact on health systems, and (c) most hackathon submissions will stop at "insight or single action" — showing an actually-closed loop is a rare and strong differentiator.

**Triggered when:** any approved Stage 6 action implies a downstream artifact (specialist note, repeat test, patient response, outside record). Additionally, the system proactively identifies referral need during Stage 3 interpretation when clinical context warrants it.

**Loop types:**
- Referral → consult note return
- Order → result return + interpretation recorded
- Medication start → follow-up check (e.g., TFTs after levothyroxine)
- Imaging recommendation → follow-up imaging completed
- Patient outreach → response received
- Abnormal finding → resolution action recorded

#### Proactive referral identification

The referral sub-system is not passive. When Stage 3 interpretation produces a structured finding with `referral_candidate` populated and `overall_urgency` above threshold, the Loop Closure stage proactively surfaces the referral recommendation with reasoning. Example: *"Given Margaret's 4-points-per-month eGFR decline with sustained ACE inhibitor exposure, nephrology review is indicated under NICE NG203 §1.4. Shall I draft the packet?"*

This turns the clinician's role from "decide whether to refer" into "approve or modify a drafted referral," which dramatically lowers friction for a workflow that's too often skipped under time pressure.

#### Specialty-specific packet assembly with missing-context flagging

Different specialties need different inputs. A nephrologist needs eGFR trend, urine ACR, BP history, current ACE-I dose, recent imaging. A rheumatologist needs joint distribution, inflammatory markers, prior DMARD trials, functional status. A cardiologist needs ECG, ejection fraction, prior events, BP/HR trend.

The Packet Agent is specialty-aware: given the target specialty, it assembles the right inputs from the patient's FHIR record and produces a structured referral packet. Equally important, it flags what's missing — "No urine ACR in the last 12 months; consider ordering before referral" — giving the clinician a chance to close gaps before sending rather than having the specialist request them back.

#### Destination matching and ranking

Specialist directory is treated as a lookup service. Candidate destinations are ranked by:
- Specialty fit (subspecialty match where relevant)
- Urgency vs earliest available slot
- Distance from patient address
- Language match with patient preferences
- Network status (in-network, preferred, out-of-network)
- Receiving clinician's clinical focus (e.g., transplant nephrologist vs general)

In production, this queries a live directory API. In hackathon-scale implementations, this queries a seeded directory of realistic candidates.

#### Patient outreach (drafted, not sent)

Approved referrals generate drafted patient-facing messages — SMS, email, portal — in plain language at controlled reading level. The draft includes the appointment details, preparation instructions, and what the patient should expect. Delivery happens via integrated notification channels in production; in hackathon-scale implementations, the draft is shown and marked approved, and a FHIR `Communication` resource is written without actual transmission.

#### Return handling with recommendation extraction and conflict detection

The most valuable part of loop closure is what happens when the artifact returns. The Return Handler Agent:

- Parses the returned specialist note (DocumentReference) or result
- Extracts structured recommendations (hold medication X, start medication Y, recheck in N weeks, repeat imaging)
- **Detects conflicts with the current plan** — e.g., nephrologist recommends stopping lisinopril; agent notes that this requires BP monitoring adjustment and may conflict with the current hypertension management strategy
- Creates PCP-facing tasks with structured next steps, not just "review this note"
- Flags urgent recommendations for immediate attention
- Updates the loop state to CLOSED only after the PCP has reviewed and acted

This is where generative AI earns substantial value — a returned specialist note is unstructured free text, and turning it into reconciled, actionable PCP tasks is exactly the kind of work rules engines cannot do.

**Agents:**
- **Loop Registration Agent** — on approval, creates a tracked loop with expected-by date, success criteria, escalation policy
- **Proactive Referral Agent** — during Stage 3, identifies referral candidates and surfaces them with reasoning
- **Packet Agent** — assembles specialty-specific packet with missing-context flagging
- **Matching Agent** — ranks specialist destinations across the criteria above
- **Outreach Agent** — drafts multi-channel patient messages at controlled reading level
- **Specialist-Side Intake Agent** — in federation mode, represents receiving side, validates packet, acknowledges readiness
- **Watchdog Agent** — scheduled sweep of open loops, fires escalations at SLA breach
- **Return Handler Agent** — extracts recommendations from returned artifacts, detects conflicts, converts into PCP tasks
- **Escalation Agent** — routes overdue loops to appropriate human owners

**Loop state machine:**

```
DRAFTED ──→ CLINICIAN_APPROVED ──→ SENT ──→ ACKNOWLEDGED
                                    │            │
                                    ▼            ▼
                                STALLED      SCHEDULED
                                    │            │
                                    └────────────┼──→ COMPLETED
                                                 │         │
                                                 ▼         ▼
                                            OVERDUE   NOTE_RETURNED
                                                 │         │
                                                 ▼         ▼
                                           ESCALATED  ACTION_REVIEWED
                                                           │
                                                           ▼
                                                        CLOSED
```

**Each loop carries:** loop_id, triggered_by (action ID), expected_by, success_criteria, current_state, state_history, escalation_policy, owning_clinician, specialty (for referrals), destination (for referrals).

**MCP tools used:** `fhir.create_service_request`, `fhir.create_appointment`, `fhir.create_task`, `fhir.create_communication`, `fhir.subscribe_event`, `directory.specialist_search`, `scheduling.check_availability`, `notify.sms`, `notify.email`, `notify.portal`, `referral.assemble_packet`, `consult_note.extract_recommendations`, `plan.detect_conflicts`

**Outputs (all five 5Ts):**
- Transactions to FHIR (ServiceRequest, Appointment, Communication)
- Tasks for clinician review when artifacts return
- **Loop Control Tower** — cohort-level table of all open loops, ranked by drop-off risk
- **Specialty-specific referral packet** (Document) with missing-context flags
- **Reconciled recommendations brief** (Document) when specialist note returns
- Consultations to clinician when loops escalate or conflicts detected

---

## 6. The Orchestrator (Cross-Cutting)

The Orchestrator is the single visible agent. Everything else runs behind it.

**Responsibilities:**
- Session state across stages
- **SHARP context propagation** on every A2A call: `X-FHIR-Server-URL`, `X-FHIR-Access-Token`, `X-Patient-ID`, `X-Encounter-ID`, `X-Loop-ID`, `X-Session-ID`
- Capability negotiation via MCP initialize (declaring `fhir_context_required`, `supported_resources`, 5Ts produced)
- Governance enforcement (invariants in §10)
- Audit event emission (every agent call, tool call, clinician decision)
- Fallback routing — when any agent's confidence drops below threshold, route to clinician consultation

---

## 7. AI vs Rules (Explicit)

This separation is the product's trust story. State it this clearly in the submission.

### The core principle

AI does contextual reasoning that rules cannot. Rules do deterministic verdicts that AI should not. The MedSafe three-phase architecture embodies this: Phase 1 (AI builds patient profile) → Phase 2 (rules make safety verdict) → Phase 3 (AI synthesises patient-specific response).

### What AI does
- Natural-language intake conversation
- Extraction from free text and images
- Reconciliation reasoning
- **Context relevance selection** (the core differentiator)
- **Patient risk profile building** (MedSafe Phase 1)
- Report interpretation (labs, imaging, pathology, documents)
- Trend narrative generation
- **Patient-specific risk narrative** (MedSafe Phase 3)
- **Personalised alternative reasoning with trade-offs** (MedSafe Phase 3)
- **Override-reason analysis and mitigation suggestions** (MedSafe Phase 3)
- **Proactive referral identification from interpretation**
- **Specialty-specific packet assembly with missing-context flagging**
- **Consult note recommendation extraction and conflict detection**
- Alternative proposal phrasing
- Patient-facing explanation generation
- Missing-information reasoning

### What AI does NOT do
- **Medication interaction verdicts** (MedSafe Phase 2 — rules)
- **Severity ranking** (MedSafe Phase 2 — rules)
- **Contraindication evaluation** (MedSafe Phase 2 — rules)
- **Duplicate-therapy detection** (MedSafe Phase 2 — rules)
- Red-flag safety rules (intake urgency detection)
- Code normalization final truth
- Loop state transitions
- Permissions and audit determination
- Override approval
- Terminal action execution

### Why this design wins on both AI Factor and Feasibility

AI Factor is earned by having the LLM do substantive generative work: building patient profiles, reasoning about context, synthesising patient-specific narratives, extracting structured information from unstructured clinical text, detecting conflicts across care plans. These are all things traditional rule-based software cannot do.

Feasibility is earned by keeping the deterministic core deterministic: safety verdicts are auditable, verdicts trace to specific rules and specific evidence sources, the LLM never decides whether an interaction exists. A clinician judge can trust this design because it matches how expert clinical pharmacists actually work.

This split is what makes the product feasible *and* safe. Rules engines are deterministic, licensable, and auditable. LLMs are not. Putting the LLM inside the rules engine's decision loop destroys both.

---

## 8. FHIR + SHARP Standards Stack

### FHIR resources — reads
Patient, Encounter, Condition, AllergyIntolerance, MedicationRequest, MedicationStatement, Observation, DiagnosticReport, DocumentReference, Procedure, CarePlan, ServiceRequest, Appointment, Task, Communication

### FHIR resources — writes
Condition (proposed), MedicationStatement (proposed), AllergyIntolerance (proposed), MedicationRequest (after MedSafe), ServiceRequest, Appointment, Task, Communication, AuditEvent, CarePlan updates

### Medication coding
- Primary: dm+d (UK) or RxNorm (US)
- Secondary: SNOMED CT concept IDs
- Unresolved items always surfaced, never silently dropped

### SHARP context propagation
Every inter-agent A2A call carries: `X-FHIR-Server-URL`, `X-FHIR-Access-Token`, `X-Patient-ID`, `X-Encounter-ID`, `X-Loop-ID`, `X-Session-ID`

### MCP initialize capability declaration

```json
{
  "fhir_context_required": true,
  "supported_resources": [...],
  "produces_5ts": ["document", "table", "task", "transaction", "consultation"],
  "requires_clinician_approval": true,
  "audit_events_emitted": true
}
```

---

## 9. The 5Ts Mapping (Explicit)

| Stage | Consultation | Document | Table | Transaction | Task |
|---|---|---|---|---|---|
| Intake | Clarifying Qs | Intake draft card | Conflicts table | Draft chart writeback | Review-intake task |
| Context | Missing-data prompts | Context pack narrative | Selection table | — | Chart-review task |
| Signal | Ambiguous findings | Clinician brief + patient letter | Findings table | — | Review-result task |
| Trend | — | Trend narrative | Annotated trend panel | — | — |
| MedSafe | Override reason capture | MedSafe review card | Flags table | MedicationRequest | Monitoring task |
| Action | Reject-with-reason | Proposed plan + patient message | Alternatives table | Order/referral drafts | Prerequisites task |
| Loop | Escalations | Referral packet + status report | Loop Control Tower | ServiceRequest, Appointment | Follow-up tasks |

The product produces all five Ts multiple times across the workflow.

---

## 10. Governance, Safety, Audit

### Clinician-in-the-loop invariants (never violated)
1. No chart writeback without clinician review
2. No MedicationRequest without passing MedSafe (or documented override)
3. No referral sent without clinician approval of packet and destination
4. No patient-facing communication sent without clinician approval
5. Every override creates a permanent AuditEvent record
6. Every agent reasoning step with confidence < threshold routes to consultation

### Failure modes and responses

| Failure | Response |
|---|---|
| LLM hallucination in interpretation | Structured output schema rejects malformed; `evidence_refs` must resolve |
| Medication not resolvable to code | Surfaced as "needs review," never absent |
| Low confidence on reasoning | Auto-escalate to consultation |
| MCP tool failure | Retry once, then surface; never silently skip safety check |
| Watchdog misses an artifact | Manual "mark closed" path, logged |
| Patient intake urgency | Break flow, escalate immediately, log |
| Clinician overrides MedSafe | Full AuditEvent with reason, patient record annotated |
| Signal arrives for unknown patient | Quarantine, require manual matching |

### PHI boundary
- Patient-facing Conversation Agent operates on sanitized context
- Clinician-facing agents operate on full FHIR context
- Patient never sees raw interpretation output; only clinician-approved patient explanation
- Audit trail preserves who saw what, when

### Audit granularity
Every: agent call, tool call, reasoning step, clinician decision, override, patient interaction, loop transition, writeback. Stored as FHIR AuditEvent. Queryable by case, patient, clinician, agent.

---

## 11. UI Blueprint

### The 5-Panel Clinician Workspace

```
┌─────────────────┬─────────────────┬─────────────────┐
│                 │                 │                 │
│   PANEL 1       │   PANEL 3       │   PANEL 4       │
│   Intake        │   Clinician     │   MedSafe       │
│   Draft         │   Brief         │   Review        │
│                 │                 │                 │
├─────────────────┤                 │                 │
│                 │                 │                 │
│   PANEL 2       │                 │                 │
│   Signal        ├─────────────────┤                 │
│   Review        │                 │                 │
│                 │   PANEL 5       │                 │
│                 │   Action +      │                 │
│                 │   Closure       │                 │
│                 │                 │                 │
└─────────────────┴─────────────────┴─────────────────┘
```

**Panel 1 — Intake:** patient conversation summary, meds/allergies draft, uploaded documents, confidence flags, reconciliation conflicts.

**Panel 2 — Signal Review:** new result/report, extracted findings, relevance rationale, trend sparkline.

**Panel 3 — Clinician Brief:** what matters now, what changed, what needs action, uncertainty flags, evidence refs.

**Panel 4 — MedSafe:** active/proposed meds, conflicts by severity, alternatives, override button.

**Panel 5 — Action + Closure:** approve/edit/reject plan, create order/referral/task, patient message preview, active loop status.

### The Cohort Loop Control Tower

A separate view showing the clinician's entire panel:
- All open loops, ranked by drop-off risk
- Color coding: green (on track), amber (approaching SLA), red (overdue)
- Predictive failure column — loops most likely to break based on past patterns
- One-click escalation, rescheduling, or manual close
- Filtering by loop type, urgency, specialty, age

### Patient Intake UI

- Voice or text option
- Medication photo upload
- External report upload
- Plain language throughout
- Multilingual (blue-sky extension: live translation)
- Reading-level controlled to ~6th grade
- "Skip" available on every question
- Clinical urgency detection with clear escalation path

---

## 12. Submission Strategy

Two submissions, two categories — same codebase, double the shots.

### Submission A — Agent (A2A category)
**SignalLoop Orchestrator + full stage pipeline**
- Uses all seven stages
- Full A2A collaboration visible in demo
- Calls MedSafe as an MCP tool (not embedded)
- The "full product" submission

### Submission B — Superpower (MCP category)
**MedSafe Gate as standalone MCP server**
- The 3-layer normalization + knowledge + patient-context engine
- Exposed as reusable MCP tools
- Any agent in the marketplace can call it
- The "infrastructure" submission

Why both: entry fees are zero, categories are separate, and MedSafe is genuinely reusable infrastructure. A good MCP tool can win Superpower even if Agent doesn't place. The MedSafe code is the same in both.

---

## 13. Demo Execution Plan

Hackathons are won or lost on the demo. The spec describes a system; this section describes the story. The 3-minute video must feel like narrative, not a feature tour.

### 13.1 The 3-Minute Hero Flow (full demo arc)

**Act 1 — Patient reality (0:00–0:45)**

Margaret, 72, with knee pain, opens SignalLoop on a tablet in the waiting room. She speaks naturally: *"I'm here because my knees are really bothering me. I'm taking lisinopril, water tablets, and that little white pill for cholesterol."* She uploads a photo of her pill bottles. The intake panel fills in real-time. One field flashes amber:

> **⚠ Conflict with chart** — patient says she stopped metformin three months ago; chart shows active prescription.

The four-state taxonomy is visible in the UI: Confirmed fields in green, Needs Review in yellow, Conflict in amber, Missing-But-Important in grey.

**Act 2 — Overnight, a signal lands (0:45–1:30)**

Dr. Patel opens Margaret's chart for morning review. A new eGFR result arrived overnight: **42, down from 58 three months ago**. The Signal pane shows the Trend Agent's annotated sparkline: *"eGFR declining 4 points/month; no corresponding interventions recorded."* The Clinician Brief explains, in three bullets, why this matters *for this patient specifically* — she's on an ACE inhibitor and a diuretic, and any NSAID would be a dangerous third layer. She's also diabetic, which compounds the picture. Evidence citation: NICE NG203 §1.3.2.

**Act 3 — The MedSafe interrupt (1:30–2:00)**

Dr. Patel, reaching for the obvious treatment, types "ibuprofen 400mg TDS" for the knee pain and clicks prescribe. The screen freezes for a half-second. Then the red gate slides in:

> **⛔ CONTRAINDICATED**
> eGFR 42 (new, down from 58) — NSAID inappropriate in CKD Stage 3b
> *Currently on lisinopril + diuretic — triple-whammy AKI risk*
> *Age 72 — Beers criteria: avoid chronic NSAIDs >65*
>
> **Paracetamol 1g QDS** — cleaner option, no renal risk
> **Topical diclofenac** — minimal systemic absorption

Dr. Patel clicks "use paracetamol instead." The MedicationRequest writes. A plain-language patient message auto-drafts. A follow-up task queues for two weeks to repeat renal function.

**Act 4 — The loop opens (2:00–2:30)**

Dr. Patel decides Margaret needs a nephrology referral. The Packet Agent assembles the specialist packet on-screen, pulling exactly what nephrology needs — eGFR trend, current medications, diabetes status, relevant imaging — and leaving out the knee-pain primary care churn that's irrelevant. The Matching Agent shows three specialists ranked by urgency, earliest slot, and language match. Dr. Patel approves. ServiceRequest and Appointment write to FHIR. The Loop Control Tower shows 47 open loops across the panel; Margaret's new one tagged green.

**Act 5 — Time jump, loop closes (2:30–2:50)**

*"Six days later."* The nephrology consult note returns. The Return Handler extracts the recommendation — adjust ACE inhibitor, recheck in 6 weeks, no NSAIDs ever — and converts it into a task for Dr. Patel. The loop transitions to CLOSED. The audit trail is visible: every agent call, every tool call, every clinician decision, logged as AuditEvent.

**Closing frame (2:50–3:00)**

*"Context in. Verified action out. Loop closed."*

### 13.2 The 10-Second Shareable Moment

Inside the arc, one 10-second clip is the one a judge will remember and share. It is the MedSafe interrupt in Act 3 — the moment the red gate slides in over Dr. Patel's prescription, showing:

- **Context-specific reasoning** (eGFR trend + ACE inhibitor + diuretic + age interacting)
- **A deterministic verdict** (rules engine, not LLM guessing)
- **Safer alternatives** with clear rationale
- **The clinician recovering gracefully** in one click

AI reasoning, rules verdict, workflow execution, and trust calibration in a single frame. That is the clip. Every other demo moment builds toward it or reinforces it.

### 13.3 Why this demo structure wins

- **Act 1** proves the AI is reconciling, not summarizing (the four-state taxonomy is visible)
- **Act 2** proves context-aware interpretation (the same eGFR means different things for different patients)
- **Act 3** delivers the hero moment — the clip that spreads
- **Act 4** proves the workflow is operationally real (FHIR writes, not mockups)
- **Act 5** proves loop closure — the thing almost no other hackathon entry will show

Each of the three judging criteria lights up at least twice across the five acts: AI Factor in Acts 1, 2, 3; Potential Impact in Acts 3, 4, 5; Feasibility in Acts 1, 4, 5.

---

## 14. Blue-Sky Extensions

North-star vision beyond first ship:

- **Multi-specialty support** — separate specialist-side Context Agents for cardiology, nephrology, rheumatology, each knowing what their specialty cares about
- **Multi-signal fusion** — interpret three results arriving in the same week as one coherent clinical picture
- **Probabilistic loop failure prediction** — train on past loop outcomes to predict which new loops will break
- **Cohort-level abnormality dashboard** — every unresolved abnormal result across a clinician's panel in one view
- **Adaptive outreach cadence** — patient messaging frequency learned per-patient from response patterns
- **Cross-organization federation** — specialist-side agent represents the receiving organization via A2A rather than fax
- **Clinician-edit learning** — capture deltas when clinicians edit generated briefs; improve prompts with privacy safeguards
- **Policy-aware local pathways** — per-organization customization of care pathways, formularies, referral directories
- **Payer integration** — prior-auth branching inside Stage 6 when an action requires authorization
- **Multimodal image interpretation** — beyond OCR into actual image understanding for dermatologic photos, wound progression
- **Voice-native clinician mode** — clinician dictates response to a brief rather than clicks
- **Longitudinal CarePlan mode** — multi-month CarePlan resources rather than single-event loops
- **Quality reporting hook** — emit data in HEDIS/MIPS-compatible formats as a byproduct of loop closure
- **Comparative patient explanation** — "patients with similar profiles typically..." grounded in de-identified cohort data
- **Temporal causality reasoning** — distinguish "the medication caused the lab change" from "the lab change triggered the medication"

---

## 15. Final Product Positioning

**SignalLoop is the clinical copilot for the last mile. From the moment a patient describes their symptoms in their own words to the moment a consult note returns and a task lands in the PCP's inbox, SignalLoop tracks every signal, every decision, and every downstream step — with AI doing the contextual reasoning, rules doing the safety verdicts, and the clinician always in command.**

---

*End of master specification. Next document: ruthless 3.5-week hackathon build scope built on top of this spec.*
