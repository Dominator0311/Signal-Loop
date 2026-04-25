# SignalLoop Scenarios — Design Doc

> Companion to `system-prompt-signalloop.md` and `signalloop-demo-script.md`.
> Purpose: explain the clinical reasoning behind each scenario, the tool composition, and the Prompt Opinion (PO) platform features each one depends on. This is the spec the demo script and system prompt are built from. If a scenario's PO dependency is broken, the contingency is documented here.
>
> Scope reminder: SignalLoop is **adult renal safety** — CKD, NSAID risk in CKD, RAAS handling, nephrology referral, consult loop closure, Beers/STOPP-START surveillance for ≥65. UK context (NICE, BNF, dm+d). All clinical claims trace to NICE NG203, NICE NG106/CG187, BNF, AGS Beers 2023, or STOPP/START v2.

---

## Why four scenarios, not one

The Apr-21 critical analysis flagged the original SignalLoop demo as "tool execution, not agent reasoning" — a single linear pipeline (`ingest consult → reconcile → draft`) doesn't answer the AI-Factor judging question of "does this generalise?". Four scenarios give four orthogonal demonstrations of agent capability:

| # | Scenario | Capability shown | AI-Factor narrative |
|---|---|---|---|
| 1 | Proactive surveillance | Reasoning across the whole chart with no user-specified target | "The agent decides what matters, not just what was asked." |
| 2 | Multi-turn loop closure | State preservation, in-flight edits, clinical-class reasoning | "Switch-vs-dual-RAAS — a pure-LLM agent gets this wrong." |
| 3 | Novel prescription | Visible chained tool use, override-with-monitoring | "MedSafe MCP and SignalLoop are architecturally linked." |
| 4 | Audit interrogation | Replayability, citation discipline | "Every override is queryable — audit is a clinical artifact." |

Tiebreaker priority is **AI Factor → Impact → Feasibility**. Scenario 1 lifts AI Factor most. Scenario 2 carries Impact (loop closure is the named clinical problem). Scenario 3 carries Feasibility (visible MCP integration). Scenario 4 is bonus credibility — drop it first if timing is tight.

---

## Scenario 1 — Proactive surveillance

### Clinical rationale
A GP opening a complex CKD patient does not ask a single question — they're triaging. eGFR is one signal. The active medication list is another. The unactioned consult document is a third. A real clinician's reasoning is parallel; current EHRs only support sequential search. SignalLoop's value is the parallel surveillance pass.

For Margaret Henderson specifically:
- **Trend** — eGFR 52 → 42 over 5 months is `-2 mL/min/month`. NICE NG203 §1.5.5 defines accelerated decline as `>5 mL/min/year` over a sustained period; Margaret is at `~24 mL/min/year`, far past threshold. This warrants nephrology engagement and medication review, even if no single visit triggers it.
- **Drug-safety** — ibuprofen is on the chart from Nov-2024, when eGFR was higher. The "triple whammy" (NSAID + ACE-I + diuretic) is a named MHRA hazard and is BLOCKED by `INT-001` in the rules engine. Retrospectively re-evaluating active prescriptions against the *current* renal status is the surveillance loop nothing else on the platform performs automatically.
- **Open consult** — Dr Patel's letter returned 2 weeks ago. The DocumentReference exists in FHIR but no MedicationRequest, Task, or AuditEvent was generated against it. The 7 recommendations are sitting unactioned. This is the loop SignalLoop closes in Scenario 2.

### Tool composition

```
SurfacePatientAttention(patientId)
  ├─ BuildPatientRiskProfile        — Phase 1, gives current conditions/meds/allergies
  ├─ GetRenalTrend("62238-1")       — eGFR trajectory + rate
  ├─ RunFullMedicationReview        — re-evaluates EVERY active med against current profile
  └─ ExtractConsultRecommendations  — auto-discovers latest unactioned DocumentReference
```

`SurfacePatientAttention` is a **composite** tool — it does not invent new clinical logic. It calls existing primitives and aggregates their outputs into a prioritised list. See `signalloop-tool-requirements.md` for the spec.

### Data flow between calls
1. `BuildPatientRiskProfile` produces `PatientRiskProfile` (current eGFR, conditions, active meds list).
2. `GetRenalTrend` reads Observations for LOINC 62238-1 (eGFR), returns trajectory + rate.
3. `RunFullMedicationReview` consumes the profile, iterates over each active med, calls each rule tool, aggregates per-drug verdicts.
4. `ExtractConsultRecommendations` searches DocumentReferences for unactioned consult notes (loinc 11488-4) returned within the last 90 days; returns count + summary.
5. The composite ranks items by severity (BLOCK > WARN > overdue task > trend concern) and returns top 5.

### What the agent surfaces
A single Attention Card with 1–5 ranked items, each tagged by category and accompanied by a rule-level citation. The agent ENDS with "Which would you like to address?" — it does NOT auto-act. Auto-acting on a surveillance pass is contraindicated: a clinician wants the agent to think with them, not for them.

### PO platform requirements
- **Composite tool calls visible in chat** — the user must see the orchestration, even if the agent only directly invokes one tool. Verify the `SurfacePatientAttention` banner shows the nested calls. If PO does not render nested tool calls, fall back to having the agent invoke the four primitives directly in sequence (slower but more visibly orchestrated).
- **Single-shot rendering** — the entire Attention Card must render in one assistant turn, not streamed item-by-item. Verified pattern.

### Contingency if a tool fails
If `SurfacePatientAttention` returns an error, the agent calls the primitives directly in this order: `BuildPatientRiskProfile` → `GetRenalTrend` → `RunFullMedicationReview` → `ExtractConsultRecommendations`, and synthesises the same Attention Card from the four outputs.

---

## Scenario 2 — Multi-turn consult loop closure

### Clinical rationale
The "ingest consult → reconcile → draft" workflow is the core SignalLoop value proposition. RCGP and BMA evidence suggests GP admin time per returned letter is 15–30 minutes; SignalLoop targets <1 minute end-to-end. This scenario is the Impact engine of the submission.

The clinical complexity isn't the extraction — that's parseable text. It's the **reconciliation against current chart state**, where the agent must decide:
- Is this a *new* recommendation, a *change*, a *switch*, or a *conflict*?
- Does the chart contradict the consult?
- Are there contraindications the specialist didn't know about (e.g., the patient just had a fall)?

### The switch-vs-dual-RAAS gotcha (THE critical AI Factor moment)

**Background.** RAAS = renin-angiotensin-aldosterone system. ACE inhibitors (ramipril, lisinopril, enalapril) and ARBs (irbesartan, losartan, candesartan, valsartan) both block this system, at different points. Combined ACE-I + ARB is **dual blockade**.

**Why dual blockade is contraindicated in CKD.** ONTARGET trial (2008) showed dual ACE-I + ARB increased AKI, hyperkalaemia, and mortality with no proteinuria benefit. NICE NG203 §1.6 explicitly recommends against routine dual blockade. It survives only in very narrow MDT-supervised settings (refractory proteinuria with specialist oversight).

**The trap.** A nephrology consult arrives saying "switch to irbesartan 150 mg OD." The patient is on ramipril. A naive LLM agent reads "irbesartan 150 mg OD" as a new prescription and drafts it on top of the existing ramipril. Result: **the agent has just drafted dual RAAS blockade in a CKD patient** — exactly the contraindication NG203 prohibits.

**SignalLoop's mitigation (the AI Factor moment).** The agent does NOT trust the surface text. It applies a class-aware rule:

```
if (consult names a NEW RAAS agent) AND (chart has an ACTIVE different-class RAAS agent):
    if consult text contains "continue", "alongside", "in addition to" → DUAL-RAAS, escalate.
    else → SWITCH (stop chart agent, start consult agent). Confirm with clinician.
```

This logic lives in `tools/referral.py` `CONFLICT_DETECTION_SYSTEM` (already implemented per `SignalLoop-Handover.md` §12). The agent surfaces the classification as a **confirmation question, not a silent decision**:

> "Switch detected: irbesartan recommended, ramipril currently active — interpreting as a switch, NOT dual RAAS blockade. Confirm?"

The clinician confirms, and only then does the agent draft both `STOP ramipril` and `START irbesartan`.

**Citation.** NICE NG203 §1.6 (RAAS blockade in CKD). Cite verbatim in the chat. Physician judges will spot-check this.

**Why this beats a pure-LLM agent.** A pure LLM might or might not get this right depending on prompt phrasing and luck. SignalLoop's approach makes it deterministic at the rule layer, then asks the LLM to phrase the confirmation question. The clinical reasoning is in the rule; the agent is the conversation.

### Tool composition (multi-turn)

| Turn | Tool calls | Purpose |
|---|---|---|
| 1 | `ExtractConsultRecommendations` | Parse the DocumentReference into structured recs. |
| 1 | `DetectPlanConflicts` (or `DetectPlanConflicts`) | Map each rec to agreed/switch/conflict/pending. |
| 1 | (CONFLICT_DETECTION_SYSTEM applied internally to flag SWITCH vs DUAL-RAAS) | Class-aware safety check. |
| 2 (after clinician confirms switch) | `DraftMedicationRequest` × N | One per stop, one per start. |
| 2 | `DraftFollowupTask` × N (with `timing="6 weeks"` etc.) | Tasks computed from natural-language timing. |
| 2 | `DraftServiceRequest` (if rec involves a sub-referral, e.g., dietitian) | Outbound referral. |
| 3 (after clinician edit "4 weeks not 6") | Re-emit changed drafts only | Edit handling. |
| 4 (after "commit") | `LogOverride` | Permanent audit record. |

### State preserved across turns
- The list of extracted recommendations.
- The reconciliation result (which are agreed, which are switches, which are conflicts).
- The set of pending drafts (what's been drafted, what's been edited, what's been committed).
- The clinician's confirmations (switch confirmed, edits applied).

### PO platform requirements (RISK REGISTER)

| Risk | Severity | Mitigation |
|---|---|---|
| **Multi-turn state preservation across the conversation** | CRITICAL | Verified via PO docs: BYO agents in PO retain full conversation history within a session. If a session ends, state is lost — that's acceptable for the demo. |
| **Tool-call visibility for nested/parallel calls** | HIGH | Each `mcp.tool` call renders a banner. Nested calls (composites) may or may not render — verify in UI. Fallback: agent calls primitives directly. |
| **In-flight edit handling** | HIGH | The agent must understand "change X to Y" maps to a re-draft of one line item, not the whole plan. Prompt-engineering responsibility. |
| **FHIR write commit timing** | MEDIUM | The `Draft*` tools currently produce drafts at call time. The "commit" semantic is enforced at the agent layer (don't call `Draft*` until clinician confirms). Acceptable. |
| **AuditEvent ID retrieval** | LOW | `LogOverride` returns the FHIR ID; agent surfaces it in the footer. |

### Contingency
If multi-turn rendering is broken in PO, fall back to a "review-and-approve-all" single-turn pattern: agent emits all 7 drafts in one card, clinician types "commit all" or "commit but change task 4 to 4 weeks". The switch detection still works; the in-flight edit demonstration is reduced.

---

## Scenario 3 — Novel prescription with visible MCP integration

### Clinical rationale
For Doris Williams (68F, RA, on methotrexate, eGFR 58):
- **NSAID + age 65+** → AGS Beers 2023 flags chronic NSAID use as inappropriate (Table 2: "Avoid chronic use unless other alternatives are not effective").
- **NSAID + methotrexate** → BNF Appendix 1: NSAIDs reduce MTX renal clearance, increase MTX toxicity. WARN.
- **eGFR 58** → not a hard BLOCK at this level (BLOCK threshold is typically eGFR <30 or "triple whammy" combinations); WARN for renal vigilance.

Three independent rule sources fire. The Action Card surfaces all three. The agent does NOT collapse them into one — flag count is informative to the clinician's risk assessment.

### Tool composition

```
NormalizeMedication("naproxen") → dm+d 320365001
[ parallel: ]
  CheckMedicationSafety(naproxen, profile)              → WARN
  CheckBeersCriteria(naproxen, age=68)             → flag
  CheckDrugDrugInteraction(naproxen, methotrexate) → WARN
SuggestAlternative(profile, drug=naproxen, verdict=WARN)
```

Why three checks instead of one composite? **Visibility.** Each banner is an AI Factor moment. Hiding them inside a `RunFullMedicationReview` collapses the visual story. For Scenario 3, the chained checks ARE the demo.

### Override flow
1. Clinician overrides with a rationale.
2. `AnalyseOverrideReason` classifies the rationale (informed-clinical-priority, monitoring-planned, etc.).
3. `LogOverride` (override variant) — MUST precede the draft.
4. `DraftMedicationRequest` for the prescribed drug.
5. `DraftFollowupTask` for the monitoring (e.g., "Repeat U&E in 2 weeks").

This order matters: audit before draft. If the draft fails, the audit still records that the clinician chose to override.

### PO platform requirements
- **Parallel tool calls render as a stack of banners** — verify in UI; if not, sequential rendering still works but is slightly less impressive on video.
- **Override verb-y boolean trap (per memory feedback file):** AnalyseOverrideReason should not have an optional `auto_draft: bool = False` parameter — LLMs pass `True` when verb-y. The current implementation uses separate tools (`AnalyseOverrideReason` then `DraftMedicationRequest`). Keep that pattern.

---

## Scenario 4 — Audit interrogation (optional, lowest priority)

### Clinical rationale
Audit-and-replay is the regulatory story. UK CQC inspections, GMC investigations, and clinical-negligence reviews all need queryable decision records. SignalLoop's AuditEvent stream is structured to answer "why did this happen?" in one call, with citations.

The scenario is short by design. The clinical content was already established in Scenario 3 (the override). Scenario 4 demonstrates that the audit is queryable, not just stored.

### Tool composition
```
QueryAuditEvent(patient=Doris, action=override, drug=naproxen)
  → returns the AuditEvent payload
ExplainContraindication(audit_payload, original_verdict)
  → produces the natural-language replay
```

### What the agent surfaces
The Audit Card replays the original verdict, the override rationale (verbatim from the AuditEvent), the monitoring outcome (from the linked Task's completion status), and the citation. End-to-end traceability in one chat turn.

### PO platform requirements
- `LogOverride` needs to also support read/query (current implementation only writes — see tool requirements doc; minor extension or add a sibling `QueryAuditEvent` tool).
- If timing is tight, **drop the worked example** and replace with a 5s narration: "Every override is one query away from a full replay. We've logged six in this demo. Audit is not paperwork — it's a clinical artifact."

### Contingency
If `LogOverride` cannot read, skip Scenario 4 entirely. Demo lands at 3:00.

---

## Cross-scenario design decisions

### Why the agent never auto-commits writes
A clinical agent that drafts and commits in one turn is a liability agent. Every Draft* tool produces a *pending* resource until the clinician explicitly says "commit". This pattern is enforced at the agent layer (system prompt) AND would ideally be enforced at the platform layer (FHIR writes gated by approval). For the hackathon, the agent-layer enforcement is sufficient and demonstrable.

### Why we cite verbatim, not paraphrased
Physician judges spot-check rule sources. A paraphrased citation that subtly misstates NICE NG203 §1.6 fails credibility immediately. Every rule tool returns its citation verbatim. The agent renders it without modification.

### Why we use four scenarios, not three
Scenario 4 is "if there's time" insurance — its presence in the script signals depth of audit thinking, even if the video editor cuts it. Worst case: Scenario 4 lives in the demo write-up, not the video.

### Why we don't demo one-shot mode
Per Apr-21 critical analysis: "demoing one-shot after multi-turn makes the multi-turn version look padded." Mention at close, do NOT demo.

---

## Open clinical questions

These are explicitly open and should be resolved before hackathon submission if possible:

1. **CheckBeersCriteria threshold for chronic vs acute NSAID use.** AGS Beers Criteria 2023 is more permissive of acute NSAID use (≤7 days) than chronic. The rules data must capture the duration field; if it doesn't, the agent will conservatively flag any NSAID prescription for ≥65 patients as Beers — acceptable for the demo, may be over-flagging in production.
2. **DDI severity levels for naproxen + methotrexate.** Some sources (BNF) list the interaction as "monitor"; others (Stockley's) list it as "avoid combination if MTX dose >15 mg/week". The rules data should capture the dose threshold. If it doesn't, the agent flags WARN regardless of dose — defensible but could be over-flagging at low MTX doses.
3. **Switch-vs-dual-RAAS detection robustness.** The current detector relies on text-pattern matching for "continue", "alongside", "in addition to". A specialist who phrases dual blockade unusually ("retain ramipril, add irbesartan") could slip through. Document this as a known false-negative risk in the demo voiceover, or strengthen the detector with an LLM-based class-co-presence check.
