# SignalLoop Demo Script — 3 minutes, 4 scenarios

> Submission: SignalLoop Renal Safety BYO Agent (Prompt Opinion).
> Hackathon: Agents Assemble — Healthcare AI Endgame (deadline May 11, 2026).
> Total runtime budget: **3:00** (15s hook + 60s + 75s + 30s + 30s + 15s close = 3:25 raw; trim Scenario 4 if needed to land at 3:00).
>
> **Reading the script:** every dialogue line is camera-ready text. "Clinician:" lines are typed into the PO chat input. "Agent:" lines are the rendered markdown response. "Tool calls" are the banners PO renders before/with the agent's reply — the video editor should hold the camera on those banners for ~1.5s each so judges see the chain.

---

## 0:00–0:15 — Hook (15s)

**Voiceover (camera on PO chat with Margaret's avatar):**
> "Margaret Henderson, 72, on five medications, eGFR declining. Her GP has 7 minutes. SignalLoop is a BYO agent on Prompt Opinion that reasons across her record, surfaces what matters, and closes loops — through Anthropic-style tool use over the MedSafe MCP server."

**On-screen overlay:**
- Title card: `SignalLoop — Renal Safety Agent`
- Subtitle: `Multi-scenario clinical surveillance · Built on MedSafe MCP`

---

## 0:15–1:15 — Scenario 1: Proactive surveillance (60s) — the wow

**Setup (camera on Launchpad):** GP opens Margaret's chart, taps SignalLoop in Launchpad.

### Clinician (typed):
> "What needs my attention for Margaret today?"

### Tool calls visible in PO chat (banners — hold ~1.5s each):
1. `SurfacePatientAttention(patientId=Margaret)`
   - Internally fans out (the banner shows a nested list):
     - `BuildPatientRiskProfile`
     - `GetRenalTrend("62238-1")`
     - `RunFullMedicationReview`
     - `ExtractConsultRecommendations` (auto-discover open consults)

### Agent (rendered markdown):
> **Margaret Henderson, 72F — 3 items need your attention.**
>
> 1. **[Trend]** eGFR 52 → 42 over 5 months (-2 mL/min/month). Trajectory of decline at CKD 3b boundary. *Cite: NICE NG203 §1.5.5.*
> 2. **[Drug-safety]** Active ibuprofen 400 mg PRN (prescribed 2024-Nov, before last eGFR drop) — now retrospectively BLOCKED at eGFR 42 with active ramipril + bendroflumethiazide ("triple whammy"). *Cite: rule INT-001, BNF Appendix 1, NICE NG203.*
> 3. **[Open consult]** Nephrology consult returned 2 weeks ago (Dr Patel, 7 April) — 7 recommendations, 0 actioned.
>
> Which would you like to address?

### Narration overlay:
> "The agent didn't just answer the prompt. It reached across the trend, the active medication list, and the document store — and surfaced three independent safety signals with rule-level citations. This is reasoning, not retrieval."

### Visual cue for editor:
- Pause on the BLOCK flag bullet. Highlight `INT-001` and the NICE citation.
- Pull-quote: "Triple whammy — retrospectively flagged."

---

## 1:15–2:30 — Scenario 2: Multi-turn consult loop closure (75s)

### Clinician (typed):
> "Start with the consult."

### Tool calls visible:
1. `ExtractConsultRecommendations(patientId=Margaret)` — auto-discovers latest DocumentReference.
2. `DetectPlanConflicts(...)` — produces switch/conflict/agreed map.

### Agent (rendered markdown):
> **Closure: nephrology consult, Dr Patel, 7 April 2026.**
>
> **Recommendations extracted:** (7)
> 1. Switch ramipril → irbesartan 150 mg OD.
> 2. Stop ibuprofen 400 mg PRN.
> 3. Add atorvastatin 20 mg ON.
> 4. Repeat U&E + eGFR in 6 weeks.
> 5. Repeat ACR in 3 months.
> 6. BP target <130/80.
> 7. Refer dietitian for low-K+ counselling.
>
> **Reconciliation:**
> - **Switch detected (RAAS):** irbesartan recommended; ramipril 5 mg currently active. Interpreting as a **switch** (stop ramipril, start irbesartan) — NOT dual RAAS blockade (contraindicated in CKD). *Cite: NICE NG203 §1.6.* **Confirm before I draft?**
> - Ibuprofen stop — agreed with current safety BLOCK.
> - Atorvastatin start — no chart conflict.
> - Tasks 4–7 — no chart conflict.

### Narration overlay (on the switch line):
> "This is the moment. A pure-LLM agent would have drafted both ramipril AND irbesartan — dual RAAS blockade is contraindicated in CKD. SignalLoop's rules engine knows the class structure; the agent surfaces it as a confirmation question, not a silent merge."

### Visual cue for editor:
- Hold on the bolded "Switch detected" line for 2s.
- Caption: `Switch ≠ dual blockade · NICE NG203 §1.6`

### Clinician (typed):
> "Confirmed — it's a switch."

### Tool calls visible:
1. `DraftMedicationRequest(stop ramipril)`
2. `DraftMedicationRequest(start irbesartan 150 mg OD)`
3. `DraftMedicationRequest(stop ibuprofen)`
4. `DraftMedicationRequest(start atorvastatin 20 mg ON)`
5. `DraftFollowupTask(timing="6 weeks", note="Repeat U&E + eGFR")`
6. `DraftFollowupTask(timing="3 months", note="Repeat ACR")`
7. `DraftServiceRequest(specialty=dietitian, note="low-K+ counselling")`

### Agent (rendered markdown):
> **Drafted (pending commit):**
> - STOP ramipril 5 mg OD.
> - START irbesartan 150 mg OD.
> - STOP ibuprofen 400 mg PRN.
> - START atorvastatin 20 mg ON.
> - Task: repeat U&E + eGFR in 6 weeks.
> - Task: repeat ACR in 3 months.
> - ServiceRequest: dietitian referral, low-K+ counselling.
>
> Edit anything, or commit?

### Clinician (typed):
> "Change eGFR repeat to 4 weeks not 6."

### Agent (rendered markdown):
> Updated: U&E + eGFR repeat now **4 weeks**. Other drafts unchanged. Commit?

### Clinician (typed):
> "Commit."

### Tool calls visible:
1. (Commits the 7 draft writes — banners show the FHIR resource IDs.)
2. `LogOverride(action="consult_closure_commit", recommendations=7, edits=1)`

### Agent (rendered markdown):
> **Committed.** AuditEvent/4512 logged.
>
> *Writes: MedicationRequest/a1 · MedicationRequest/a2 · MedicationRequest/a3 · MedicationRequest/a4 · Task/b1 · Task/b2 · ServiceRequest/c1 · AuditEvent/4512*
>
> I'll remind you when each task's due date comes around.

### Narration overlay (closing the scenario):
> "Seven recommendations. One in-flight edit. One audit event. Loop closed in under a minute."

---

## 2:30–3:00 — Scenario 3: Novel prescription (30s)

### Setup: switch patient. Camera on Doris Williams' avatar (68F, RA on methotrexate).

### Clinician (typed):
> "I want to prescribe naproxen 250 mg BD for her joint pain."

### Tool calls visible (parallel — banners stack):
1. `NormalizeMedication("naproxen") → dm+d 320365001`
2. `CheckMedicationSafety(naproxen, profile)` → **WARN**
3. `CheckBeersCriteria(naproxen, age=68)` → **flag** (chronic NSAID use, 65+)
4. `CheckDrugDrugInteraction(naproxen, methotrexate)` → **WARN** (NSAID-MTX renal-clearance interaction)
5. `SuggestAlternative(profile, drug=naproxen, verdict=WARN)`

### Agent (rendered markdown):
> **WARN: naproxen requires override for Doris — two independent flags.**
>
> Two rules fired, both clinically real for an RA patient on MTX with eGFR 58.
>
> **Flags:**
> - `BEERS-NSAID-CHRONIC` — Avoid chronic NSAID use in adults ≥65 (AGS Beers 2023, Table 2).
> - `DDI-NSAID-MTX` — NSAIDs reduce methotrexate renal clearance, increased toxicity risk (BNF Appendix 1).
>
> **Alternatives:**
> - Topical diclofenac gel (avoids systemic NSAID exposure, no MTX interaction).
> - Paracetamol 1 g QDS regular + tramadol PRN as step-up.
> - Intra-articular steroid if mono-articular.
>
> Override with rationale, or pick an alternative?

### Clinician (typed):
> "Override — pain control priority, document I've counselled on AKI risk and we'll repeat U&E in 2 weeks."

### Tool calls visible:
1. `AnalyseOverrideReason(...)` → classified as "informed clinical priority, monitoring planned"
2. `LogOverride(override variant)` → AuditEvent/4515
3. `DraftMedicationRequest(naproxen 250 mg BD)`
4. `DraftFollowupTask(timing="2 weeks", note="Repeat U&E + creatinine, document MTX dose")`

### Agent (rendered markdown):
> **Override processed — naproxen 250 mg BD (14 days) drafted for Doris.**
>
> **Risks accepted / Monitoring:** AKI risk counselled; U&E + creatinine in 2 weeks. AuditEvent/4515 logged.
>
> *Writes: MedicationRequest/d1 · Task/e1 · AuditEvent/4515* · *Verdict: `WARN-OVERRIDE`*

### Narration overlay:
> "Visible chained tool use. Two rule sources, three alternatives, override logged with monitoring. The MCP server is doing the rule work; the agent is doing the conversation."

---

## 3:00–3:15 — Scenario 4: Audit interrogation (15–30s, optional, lowest priority — TRIM IF OVER)

### Setup: simulate a future month. Different clinician opens Doris.

### Clinician (typed):
> "Why did we override the eGFR block on naproxen for Doris last month?"

### Tool calls visible:
1. `QueryAuditEvent(patient=Doris, action=override, drug=naproxen)` → returns AuditEvent/4515
2. `ExplainContraindication(audit_payload, original_verdict)`

### Agent (rendered markdown):
> **Audit replay: naproxen override for Doris, 25 March 2026.**
>
> - **Original verdict:** WARN. Two flags: `BEERS-NSAID-CHRONIC` (AGS Beers 2023) and `DDI-NSAID-MTX` (BNF Appendix 1).
> - **Override rationale (logged):** "Pain control priority; counselled on AKI risk; U&E recheck planned at 2 weeks."
> - **Monitoring outcome:** Task/e1 completed 2026-04-08 — U&E normal (creatinine 78, K+ 4.2). MTX dose unchanged.
> - **Citation:** AGS Beers Criteria 2023, Table 2; BNF Appendix 1 (NSAID/MTX).
>
> The decision chain is traceable end-to-end.

### Narration overlay:
> "Every override is queryable — the audit trail isn't a log file, it's a clinical artifact."

---

## 3:15–3:30 — Close (15s — trim from Scenario 4 if needed)

**Voiceover (camera pulls back to PO sidebar):**
> "Four scenarios, one agent, one MCP server. Reasoning across the chart. Rule-level citations. Audit-grade trail. SignalLoop — built for the loop the GP actually has to close."

**On-screen overlay:**
- `SignalLoop · Submission B (Agent / A2A)`
- `Built on MedSafe MCP · Submission A (Superpower / MCP)`

---

## Editor checklist

- [ ] Every tool-call banner is held for ≥1.2s and visible in frame.
- [ ] The "Switch detected" line in Scenario 2 is the visual climax (zoom + 2s hold + caption).
- [ ] The parallel tool-call stack in Scenario 3 is shown as a vertical list, not collapsed.
- [ ] All citations (NICE NG203, AGS Beers 2023, BNF Appendix 1) appear at least once on screen.
- [ ] Total runtime ≤3:00. If Scenario 4 pushes over, trim Scenario 4 to a 10s "audit replay is one tool call away" reference and skip the worked example.
- [ ] No raw JSON visible anywhere in the agent output.
- [ ] Final FHIR resource IDs visible in at least Scenario 2's footer.
