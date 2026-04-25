# Concord — Multi-Specialist Conflict Resolver

## Detailed Implementation Plan

---

## 1. Context

**Concord** is a Prompt Opinion-native clinical AI product designed for one specific job:

> turn fragmented, conflicting specialty advice into one safe, auditable, action-ready care plan.

This is not a generic copilot and not a single-specialty agent.
It is a **patient-scope orchestration agent** that coordinates multiple specialist agents and a shared deterministic MCP layer.

The product is designed to fit Prompt Opinion as it exists today:
- BYO agents inside the platform
- A2A for specialist reasoning
- MCP for reusable deterministic tools
- FHIR-native reads and writes
- marketplace publication
- clinician-in-the-loop workflow

The implementation must respect current platform realities:
- one collection per agent
- no native post-response guardrails
- chat-facing agents should not use Response Format JSON schemas
- sequential A2A is safer than assuming parallel multi-agent execution
- tool latency and end-to-end runtime must stay tight for a hackathon demo

---

## 2. Mission

Build a clinician-facing agent that:
1. reads a patient episode,
2. gathers structured recommendations from multiple specialties,
3. identifies agreement and disagreement,
4. resolves conflict into a unified plan,
5. validates that plan through deterministic checks,
6. and drafts auditable next-step actions in FHIR.

---

## 3. Vision

A clinician should be able to ask a single question such as:

> “Cardiology wants decongestion, nephrology is worried about renal decline, pharmacy is concerned about medication safety — what is the unified plan?”

And receive one response that clearly shows:
- the shared clinical facts,
- what specialists agree on,
- where they disagree,
- how that disagreement was resolved,
- what action should happen now,
- and what still requires clinician confirmation.

The output should not be a vague summary.
It should be a **resolved plan plus concrete actions**.

---

## 4. Product Definition

**Concord** is a **patient-scope A2A orchestrator**.

It is composed of:
- one clinician-facing orchestrator agent,
- three specialist worker agents,
- one shared MCP server,
- one synthetic patient dataset built for multi-specialty tension,
- and a write-back layer for tasks, communications, and audit.

### Core product promise

Concord does not replace specialists.
It does not claim autonomous diagnosis.
It does not prescribe unsafely.

It acts as a **care-plan moderator**.

---

## 5. Narrow V1 Scope

Build only one clinically dense episode type for v1:

## Cardio-Renal-Medication Conflict

Target patient characteristics:
- older adult,
- CKD stage 3b,
- heart failure / congestion concern,
- polypharmacy,
- recent renal decline,
- medication safety implications,
- clinician uncertainty due to competing specialist priorities.

### Why this scope is right

This scope is strong because it:
- naturally creates genuine conflict between specialties,
- is easy for judges to understand,
- reuses existing SignalLoop components,
- stays FHIR-native,
- and ends in concrete next-step actions.

### What not to do in v1

Do **not** attempt:
- broad all-specialty reasoning,
- population health,
- autonomous monitoring,
- external payer integrations,
- background workflows,
- patient-facing mode,
- or five-plus specialist agents.

That would dilute the product and introduce avoidable runtime risk.

---

## 6. How Concord Differs from SignalLoop

### SignalLoop
SignalLoop is a **specialist workflow engine**.
Its core question is:

> “Within this renal-safety workflow, what is the safe next step?”

It is centered on:
- one clinical thread,
- one central deterministic safety path,
- and end-to-end depth within that thread.

### Concord
Concord is a **meta-clinical orchestration engine**.
Its core question is:

> “Given multiple valid specialist perspectives, what unified care plan should the clinician actually follow?”

It is centered on:
- structured disagreement,
- multi-agent reasoning,
- conflict reconciliation,
- and action sequencing across specialties.

### Practical distinction

SignalLoop says:
- detect renal safety issues,
- decide the safe next step,
- close the consult loop.

Concord says:
- gather specialist viewpoints,
- expose agreement and conflict,
- reconcile those views,
- validate the resulting plan,
- and draft actionable outputs.

This is a genuine product difference.

---

## 7. High-Level Architecture

```text
Clinician
   ↓
Concord Orchestrator (patient-scope BYO A2A agent)
   ├── calls Nephrology Advisor (A2A)
   ├── calls Cardiology Advisor (A2A)
   ├── calls Pharmacy Safety Advisor (A2A)
   └── calls ClinicalCommons MCP tools
           ├── episode brief
           ├── trend extraction
           ├── med normalization
           ├── medication safety checks
           ├── conflict matrix computation
           ├── final plan validation
           ├── FHIR draft writes
           └── audit logging
   ↓
Workspace FHIR server
```

### Design principle

Use:
- **A2A for specialist reasoning**
- **MCP for deterministic reusable capabilities**
- **FHIR as source of truth and audit surface**

---

## 8. Agent Inventory

## 8.1 Concord Orchestrator

**Type:** BYO agent with A2A enabled  
**Scope:** Patient  
**Role:** main clinician-facing product

### Responsibilities
- accept the clinician request,
- build a structured episode brief,
- delegate to specialist worker agents,
- compare specialist outputs,
- request follow-up clarification if needed,
- build a unified plan,
- validate it through MCP,
- present it in readable markdown,
- and only write to FHIR after clinician approval.

### Hard rules
- must never impersonate a specialist,
- must never skip specialist consultation,
- must never draft final write-back without validation,
- must never silently write to FHIR,
- must never output raw JSON to the clinician chat.

---

## 8.2 Nephrology Advisor

**Type:** BYO agent with A2A skill  
**Scope:** Patient  
**Role:** renal-protection specialist

### Responsibilities
- interpret renal trend,
- identify renal risks,
- comment on renal-safe management options,
- state what renal data is missing,
- and explain what would make a plan acceptable or unacceptable from a nephrology perspective.

### Constraints
- stay inside nephrology lane,
- do not claim system-wide consensus,
- do not write to FHIR,
- output only structured JSON.

---

## 8.3 Cardiology Advisor

**Type:** BYO agent with A2A skill  
**Scope:** Patient  
**Role:** congestion / HF-management specialist

### Responsibilities
- assess cardiovascular management priorities,
- weigh symptom relief and congestion management,
- identify trade-offs against renal protection,
- and state what data would change the recommendation.

### Constraints
- stay inside cardiology lane,
- do not claim system-wide consensus,
- do not write to FHIR,
- output only structured JSON.

---

## 8.4 Pharmacy Safety Advisor

**Type:** BYO agent with A2A skill  
**Scope:** Patient  
**Role:** medication safety specialist

### Responsibilities
- interpret drug safety issues,
- surface interaction risk,
- highlight contraindications,
- define required monitoring,
- and identify practical medication constraints.

### Constraints
- stay inside pharmacy / medication-safety lane,
- act as a conservative safety reviewer,
- do not write to FHIR,
- output only structured JSON.

---

## 9. Shared MCP Server

Working name: **ClinicalCommons MCP**

This can be built by extending your existing SignalLoop / MedSafe MCP stack.

### Purpose

Provide the deterministic substrate used by all agents.
This layer should not be broad, magical, or prompt-heavy.
It should be stable, auditable, reusable, and JSON-contract-driven.

---

## 10. Exact MCP Tool List

Keep the MCP tool surface disciplined.
Use around 8–10 tools only.

## 10.1 Context tools

### `BuildEpisodeBrief`
Build one structured shared case packet from FHIR.

**Input:** active patient context  
**Output:** EpisodeBrief JSON

### `GetTrendSummary`
Return longitudinal summaries such as:
- eGFR trend,
- creatinine trend,
- potassium trend,
- or other selected numeric trajectories.

### `NormalizeMedication`
Resolve medication names into canonical drug identities and classes.
Reuse your existing SignalLoop logic.

---

## 10.2 Deterministic arbitration tools

### `CheckMedicationSafety`
Run hard medication safety checks.
Reuse MedSafe where possible.

### `ComputeConflictMatrix`
Take structured specialist outputs and classify items into:
- consensus,
- tension,
- direct conflict,
- dependency,
- missing data block,
- safety block.

This should be as deterministic as possible.

### `ValidateFinalPlan`
Run the orchestrator’s proposed plan through deterministic checks before any write-back.
This is your substitute for missing platform-level post-response guardrails.

---

## 10.3 Action / audit tools

### `DraftTask`
Create follow-up tasks.

### `DraftMedicationProposal`
Draft a proposed medication change or recommendation artifact.
Do not represent this as autonomous prescribing.

### `DraftCommunication`
Create a team communication or coordination summary.

### `LogConsensusDecision`
Create an audit artifact showing:
- which specialists were consulted,
- what they recommended,
- where conflict existed,
- how the final plan was resolved,
- and what still needs clinician confirmation.

---

## 11. Data Contracts

The interfaces between components must be rigid.
Do not allow free-form prose exchange between workers and orchestrator.

## 11.1 EpisodeBrief

```json
{
  "patient_id": "string",
  "decision_point": "string",
  "active_problems": [],
  "active_medications": [],
  "recent_labs": [],
  "trend_summary": {},
  "red_flags": [],
  "missing_data": [],
  "current_clinician_question": "string"
}
```

## 11.2 SpecialistOpinion

```json
{
  "specialty": "nephrology | cardiology | pharmacy",
  "summary": "string",
  "recommendations": [
    {
      "action": "string",
      "priority": "high | medium | low",
      "rationale": "string",
      "risks": [],
      "monitoring": [],
      "dependencies": [],
      "contraindications": []
    }
  ],
  "missing_data": [],
  "confidence": "high | medium | low"
}
```

## 11.3 ConflictMatrix

```json
{
  "consensus": [],
  "tensions": [],
  "direct_conflicts": [],
  "missing_data_blocks": [],
  "safety_blocks": [],
  "ranked_next_actions": []
}
```

## 11.4 UnifiedPlan

```json
{
  "decision_summary": "string",
  "agreed_actions_now": [],
  "actions_pending_confirmation": [],
  "unresolved_questions": [],
  "draft_writes": [],
  "patient_safe_explanation": "string"
}
```

---

## 12. End-to-End Workflow

This is the exact workflow the product should follow.

## Step 1 — clinician opens Concord on a patient
The clinician asks a real-world coordination question.

Example:

> “Cardiology wants stronger diuresis, nephrology is worried about renal decline, pharmacy is concerned about the current medication combination — what is the unified plan?”

## Step 2 — Concord calls `BuildEpisodeBrief`
This creates one structured shared case packet.
All workers reason from the same brief.

## Step 3 — Concord calls workers sequentially
Call in this order:
1. Nephrology Advisor
2. Cardiology Advisor
3. Pharmacy Safety Advisor

Use sequential orchestration in v1.
Do not assume safe or well-supported parallel fan-out.

## Step 4 — Concord calls `ComputeConflictMatrix`
The system converts specialist outputs into structured disagreement.

## Step 5 — Concord requests narrow follow-up clarification if needed
Only ask second-pass questions if the first round leaves a meaningful unresolved dependency.

Examples:
- “Would this recommendation change if congestion is clinically significant?”
- “What monitoring would make this acceptable?”
- “Is this truly contraindicated or acceptable with caution?”

## Step 6 — Concord generates a unified plan
The clinician-facing markdown must always contain:
1. shared clinical facts,
2. consensus across specialists,
3. key conflicts and how they were resolved,
4. immediate next actions,
5. open items requiring clinician confirmation.

## Step 7 — Concord calls `ValidateFinalPlan`
This is the deterministic final check.

## Step 8 — only after clinician approval, Concord writes to FHIR
Possible outputs:
- one or more Tasks,
- one communication summary,
- one consensus audit artifact,
- optional medication proposal artifact.

---

## 13. Orchestrator Prompt Design

The orchestrator prompt is where most implementations will fail.

### Required behavior
- always include the default Prompt Opinion fragments,
- always act as coordinator rather than specialist,
- always build the episode brief first,
- always gather specialist recommendations before resolving conflict,
- always run deterministic validation before final action,
- never produce raw JSON in the clinician chat,
- never write to FHIR without explicit approval,
- always separate consensus from conflict,
- always state unresolved dependencies.

### Output format
The orchestrator’s chat output must be markdown only.
Leave Response Format blank for the chat-facing orchestrator.

---

## 14. Specialist Prompt Design

Each specialist must be tightly lane-disciplined.

## 14.1 Nephrology prompt behavior
- interpret renal trend and renal protection priorities,
- emphasize kidney-related risks and thresholds,
- specify missing renal facts,
- state what would make a plan acceptable.

## 14.2 Cardiology prompt behavior
- interpret congestion / heart-failure priorities,
- weigh symptom control and decongestion benefits,
- identify what data would change the plan.

## 14.3 Pharmacy prompt behavior
- review interaction risk,
- assess monitoring burden,
- block unsafe medication proposals,
- express constraints in medication-operational terms.

### Output format for workers
Each worker should use structured JSON suitable for A2A consumption.
Workers should not be designed as human-facing chat products.

---

## 15. Knowledge Design

Because Prompt Opinion supports only one collection per agent, split grounding by specialty.

### Recommended collections
- **Nephrology Advisor collection** — short renal guidance bundle
- **Cardiology Advisor collection** — short HF / congestion bundle
- **Pharmacy Advisor collection** — short medication safety bundle
- **Concord Orchestrator collection** — optional minimal coordination guidance only, or none

### Rule
Do not create one bloated mixed-specialty collection.
The platform structure actually favors specialist separation.

---

## 16. Synthetic Patient Dataset

Build exactly three synthetic patients.

## 16.1 Hero patient
This is the primary demo case.
It must contain:
- real multi-specialty tension,
- at least one consensus item,
- at least one direct or meaningful conflict,
- at least one missing-data dependency,
- and at least one write-back action.

## 16.2 Clean-agreement patient
All specialists mostly agree.
This proves Concord is not manufacturing conflict.

## 16.3 Insufficient-data patient
The system should refuse false certainty and instead surface decisive missing data.
This proves safety and feasibility.

---

## 17. Recommended Hero Scenario

Use one cardio-renal-medication tension case.

### Example shape
- older patient,
- CKD 3b,
- heart failure / edema concern,
- worsening renal trend,
- multiple active meds,
- one current management dilemma,
- clinician seeks one executable plan.

### What the demo must visibly show
- nephrology and cardiology are not identical,
- pharmacy adds safety structure,
- Concord shows both agreement and disagreement,
- the final plan is more than a summary,
- at least one FHIR action is drafted after approval,
- the final plan is clearly auditable.

---

## 18. Reuse Strategy from SignalLoop

Do not start from zero.

### Reuse directly
- FHIR client / SHARP context handling
- MCP server scaffolding
- medication normalization
- medication safety checks
- trend extraction
- FHIR write helpers
- audit logging patterns
- synthetic FHIR bundle tooling
- testing discipline

### Do not reuse as-is
- single-thread product framing
- one-specialty system prompt
- one central deterministic verdict as the whole product story

### Correct reuse mindset
SignalLoop becomes a **subsystem** inside Concord, not the final product itself.

---

## 19. Platform Constraints to Design Around

These are non-negotiable practical constraints.

## 19.1 One collection per agent
So split knowledge by specialty.

## 19.2 No native post-response guardrails
So build deterministic validation into the MCP layer.

## 19.3 Response Format trap
So use structured output only for specialist A2A workers.
Do not use Response Format for the clinician-facing orchestrator chat.

## 19.4 MCP is stateless
So keep durable state in FHIR or controlled MCP-side storage.
Do not rely on tool session memory.

## 19.5 Sequential A2A is the safe default
Assume sequential orchestration for v1.

## 19.6 Keep the demo tight
Do not depend on background workflows, long multi-agent chains, or external A2A fragility.

---

## 20. Build Phases

## Phase 1 — Freeze the product

### Deliverables
- final product name,
- final hero use case,
- final worker agent list,
- final MCP tool list,
- final schemas.

### Exit condition
You can explain the product in one sentence without drifting into “general clinical AI.”

---

## Phase 2 — Build the shared MCP layer

### Deliverables
- `BuildEpisodeBrief`
- `GetTrendSummary`
- `NormalizeMedication`
- `CheckMedicationSafety`
- `ComputeConflictMatrix`
- `ValidateFinalPlan`
- write and logging tools

### Exit condition
All tools return stable JSON and work correctly against the active patient context.

---

## Phase 3 — Build the specialist worker agents

### Deliverables
- Nephrology Advisor
- Cardiology Advisor
- Pharmacy Safety Advisor
- one collection per worker
- structured JSON outputs

### Exit condition
The same EpisodeBrief reliably produces three distinct and schema-valid specialist opinions.

---

## Phase 4 — Build the Concord Orchestrator

### Deliverables
- clinician-facing markdown output
- sequential worker orchestration
- follow-up clarification pathway
- approval gating before writes

### Exit condition
A fresh chat produces a coherent unified plan without raw JSON leaking into the clinician-facing output.

---

## Phase 5 — Build FHIR write-back

### Deliverables
- task drafting
- communication drafting
- consensus audit artifact
- optional medication proposal artifact

### Exit condition
After clinician approval, the plan produces auditable FHIR resources with IDs.

---

## Phase 6 — Demo polish and submission

### Deliverables
- final hero case
- clean-agreement case
- insufficient-data case
- marketplace listing(s)
- under-3-minute demo script
- repeated fresh-chat dry runs

### Exit condition
The recorded demo matches exactly what the judges can invoke in the marketplace.

---

## 21. Demo Structure

The full demo should stay under three minutes.

### Demo flow
1. open patient in Prompt Opinion,
2. ask Concord for the unified plan,
3. show three specialist consultations happening,
4. show the structured conflict resolution,
5. show the unified markdown plan,
6. approve the plan,
7. show FHIR draft actions and audit artifact.

### What to avoid in the demo
- long explanations,
- too many agent calls,
- unstructured specialist prose,
- hidden logic,
- UI clutter,
- raw schema output.

---

## 22. Why This Idea Scores Well

## AI Factor
This is not a simple rules workflow.
The key AI step is multi-specialty reasoning plus conflict reconciliation across structured specialist opinions.

## Potential Impact
This solves a real coordination problem:
contradictory or fragmented specialist guidance that a frontline clinician must reconcile manually.

## Feasibility
This is:
- clinician-in-the-loop,
- FHIR-native,
- auditable,
- deterministic where it matters,
- and constrained enough to be demoable and believable.

---

## 23. What Not to Build

Do **not** build:
- five or more specialties,
- parallel orchestration,
- generic “all medicine” reasoning,
- autonomous prescribing,
- patient-facing mode,
- background monitoring,
- population analytics,
- UI-card fantasies based on raw structured output,
- or a single mega-agent pretending to do everything.

Those choices increase complexity faster than they increase judging value.

---

## 24. Final Recommendation

Build this exact product:

> **Concord = patient-scope multi-specialty conflict resolver**

with:
- **three worker agents**: nephrology, cardiology, pharmacy
- **one shared deterministic MCP layer**
- **one hero cardio-renal conflict case**
- **one clean case**
- **one insufficient-data case**
- **markdown for the clinician**
- **JSON for the worker-agent contracts**
- **FHIR write-back only after approval**

This gives you:
- a strong Prompt Opinion-native architecture,
- a product clearly different from SignalLoop,
- a higher AI-factor story than a single-thread workflow,
- and enough reuse from your current system to be realistic to build.

