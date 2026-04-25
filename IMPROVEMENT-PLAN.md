# Hackathon Improvement Plan — Three Workstreams in Parallel

> **Hackathon:** Agents Assemble — The Healthcare AI Endgame (Prompt Opinion / Darena Health)
> **Deadline:** May 11, 2026 11pm ET
> **Rubric:** AI Factor (33%) · Potential Impact (33%) · Feasibility (33%). Tiebreaker order: AI Factor → Impact → Feasibility.
> **Scope of this plan:** code-level improvements to all three submissions (MedSafe MCP, SignalLoop Agent, Concord MCP). Three agents will work in parallel under the file-boundary rules below.

---

## Why these specific improvements

From the Apr-21 critical-analysis notes (`SignalLoop-Handover.md` §11) plus today's strategic analysis:

| Submission | Problem identified | Fix in this plan |
|---|---|---|
| MedSafe MCP | "3 tools along one axis = feature, not platform" — too narrow for first-pass judges | Expand to ~10 tools as a UK Safe-Prescribing Foundation |
| SignalLoop Agent | "Single linear flow = tool execution, not agent reasoning" — fails the 'does this generalise?' test | Redesign as multi-scenario, multi-turn agent (3-4 scenarios) |
| Concord MCP | Lost visual wow when we pivoted from orchestrator-agent route due to PO platform bug po-overview#27 | Restore visual wow via Mermaid conflict diagrams + multi-hero patient demo + streaming (best-effort) |

---

## File ownership boundaries (CRITICAL — to prevent agent conflicts)

To allow safe parallel execution, the three agents have non-overlapping file boundaries:

| Agent | OWNS (read+write) | READ-ONLY (don't modify) |
|---|---|---|
| **A — MedSafe expansion** | `signalloop-medsafe-mcp/tools/` `signalloop-medsafe-mcp/rules/` `signalloop-medsafe-mcp/llm/prompts/` `signalloop-medsafe-mcp/server.py` `signalloop-medsafe-mcp/tests/` `signalloop-medsafe-mcp/llm/schemas.py` `medsafe_core/` (only if absolutely needed) | `concord-mcp/`, `agent-config/`, `fhir-bundles/` |
| **B — SignalLoop redesign** | `agent-config/system-prompt-signalloop.md` (CREATE) `agent-config/signalloop-demo-script.md` (CREATE) `agent-config/signalloop-scenarios.md` (CREATE) | All code directories (Agent B is content/prompts only; if a backing tool is needed, ASK rather than implement) |
| **C — Concord polish** | `concord-mcp/tools/run_consult.py` `concord-mcp/llm/prompts/specialists.py` `concord-mcp/server.py` (read mostly) `fhir-bundles/patient-patricia-*.json` (CREATE) `fhir-bundles/patient-frances-*.json` (CREATE) `agent-config/concord-demo-script.md` (CREATE) | `signalloop-medsafe-mcp/`, `medsafe_core/` |

**Single source of truth for `medsafe_core/`:** Workstream A. B and C must NOT modify it.

---

## Workstream A — MedSafe MCP Expansion

### Goal
Reframe MedSafe from "renal NSAID checker" to **"deterministic UK safe-prescribing primitives."** Expand to 9 tools total (5 existing + 4 new clinical-rule tools + 2 LLM-driven decision-support tools + 1 composite). Net +7 tools.

### New tools to implement

| # | Tool name | Type | Description |
|---|---|---|---|
| 1 | `CheckRenalDoseAdjustment` | Rules | drug + eGFR → BNF-renally-adjusted dose with citation |
| 2 | `CheckSTOPPSTART` | Rules | STOPP/START v2 criteria for 65+ patients |
| 3 | `CheckBeersCriteria` | Rules | Beers 2023 inappropriate-meds list (top 10 categories) |
| 4 | `CheckDrugDrugInteraction` | Rules | Pairwise DDI from BNF Appendix 1 (top 50 pairs) |
| 5 | `SuggestAlternative` | LLM | Given a contraindication, suggest 3-5 safer alternatives with rationale (Phase-3-style structured output) |
| 6 | `ExplainContraindication` | LLM | Given a SafetyVerdict, produce a patient-friendly natural-language explanation |
| 7 | `RunFullMedicationReview` | Composite | For a patient, runs all checks across all active meds and aggregates the verdicts |

### Hard rules

- **Verbatim citations.** Every rule entry must cite its source (NICE NG203, BNF Appendix 1, AGS Beers 2023, STOPP/START v2). Do NOT invent rules. If unsure of a rule's text, mark it `verification_required: true` rather than fabricate.
- **JSON data files** live in `signalloop-medsafe-mcp/rules/data/` (existing pattern).
- **LLM prompts** live in `signalloop-medsafe-mcp/llm/prompts/` (existing pattern).
- **Tools** live in `signalloop-medsafe-mcp/tools/` (existing pattern).
- **Server registration** in `signalloop-medsafe-mcp/server.py` — every new tool registered with a clear `description=` for MCP discovery.
- **Pydantic schemas** for LLM-driven tools in `signalloop-medsafe-mcp/llm/schemas.py`.
- **Tests** in `signalloop-medsafe-mcp/tests/` — at least one happy-path + one edge-case test per new tool. Existing tests must still pass.
- **No FHIR writes** for these new tools (they're read-only safety primitives). Existing draft tools handle writes.
- **No external API dependencies.** All rules data is local JSON.

### What's explicitly out of scope

- Allergy checking (FHIR `AllergyIntolerance` data is unreliable)
- Pregnancy / pediatric dosing (different rule sources, different clinical trust)
- More than 50 DDI pairs (curation cost > marginal value)
- Tool count > 10 total (narrative dilutes)

### Acceptance criteria

- All 7 new tools functional and registered
- Each tool has a complete docstring + MCP description
- Each rule cites its source verbatim
- All existing tests pass
- New tests for each new tool
- `signalloop-medsafe-mcp/AGENTS.md` (or equivalent) updated with the new tool list

---

## Workstream B — SignalLoop Multi-Scenario Redesign

### Goal
Transform SignalLoop from a single linear pipeline ("ingest consult → reconcile → draft") into a multi-scenario clinical-surveillance agent. The deliverable is content (system prompt + demo scripts), NOT code. The agent runs in Prompt Opinion using existing MedSafe MCP tools — so this workstream is about agent design, not MCP development.

### Scenarios to implement (in priority order)

**Scenario 1 — Proactive surveillance (the wow moment)**
- Trigger: clinician opens a patient → asks "what needs my attention?"
- Agent capability: orchestrates calls to GetRenalTrend + safety-audit-on-current-meds + ConsultDiscovery
- Output: prioritised list of attention items with reasoning trace
- **Note for B agent:** This requires a new MedSafe MCP tool (`SurfacePatientAttention`) — Workstream A will add it. B's job is to design the system prompt that drives this scenario and document the tool requirement for A.

**Scenario 2 — Multi-turn consult loop closure**
- Trigger: agent receives a returned consult letter (DocumentReference)
- Agent capability: extracts recommendations → confirms with clinician one-by-one → handles switch-vs-dual-RAAS detection → generates drafts → allows in-flight edits → commits with audit
- Output: multi-turn conversation with editable drafts
- The "switch-vs-dual-RAAS" moment is the clinical-reasoning gotcha that pure-LLM agents miss — must be called out explicitly in the demo

**Scenario 3 — Novel prescription with visible MCP integration**
- Trigger: clinician asks to prescribe a new medication
- Agent capability: visible tool calls to MedSafe MCP (CheckRenalSafety + CheckBeers + CheckDDI as a visible chain)
- Output: warn/block with override flow that logs rationale to AuditEvent
- This demonstrates MedSafe ↔ SignalLoop as architecturally linked, not duplicated

**Scenario 4 (NEW with no time cap) — Educational / audit interrogation**
- Trigger: clinician asks "why did we override the eGFR block on naproxen for Doris last month?"
- Agent capability: replays the reasoning chain with NICE citations
- Output: structured explanation citing the original decision's audit trail
- Only attempt this if Scenarios 1-3 are clean; lowest priority

### Deliverables

1. `agent-config/system-prompt-signalloop.md` — the BYO agent's system prompt covering all scenarios with branching logic (which scenario triggers from which kind of question)
2. `agent-config/signalloop-demo-script.md` — 3-min demo script with timing per scenario, exact dialogue, narration, expected tool-call traces
3. `agent-config/signalloop-scenarios.md` — design doc explaining each scenario's clinical reasoning, tool composition, and PO platform requirements
4. **Tool requirement document** — list of NEW MedSafe MCP tools needed for this redesign (passed to Workstream A as a dependency)

### Hard rules

- The system prompt must reference EXISTING MedSafe MCP tools by name. If a needed tool doesn't exist, document it in the tool-requirement doc rather than inventing it.
- The demo scripts must show TOOL CALLS visible in PO chat — this is critical for AI Factor narration.
- Switch-vs-dual-RAAS detection logic should reference SignalLoop's existing `tools/referral.py` `CONFLICT_DETECTION_SYSTEM` prompt (per `SignalLoop-Handover.md`).
- Every demo dialogue line must be realistic (no narration flourishes the agent wouldn't actually produce).
- **Do NOT modify any code.** This workstream is content-only.

### Acceptance criteria

- All 4 scenarios fully scripted with timing
- System prompt covers scenario routing
- Tool dependencies clearly listed for Workstream A
- Demo scripts achievable in 2:30-3:00 total
- All clinical claims traceable to NICE/BNF citations

---

## Workstream C — Concord Visual Polish

### Goal
Restore demo "wow" lost when Concord pivoted from orchestrator-agent route (due to PO platform bug po-overview#27). Add visual elements that signal multi-specialist reasoning without depending on broken platform features.

### Improvements to implement

1. **Mermaid conflict-matrix diagram in tool output**
   - Add a Mermaid diagram generator to `concord-mcp/tools/run_consult.py`
   - Diagram: action codes as nodes, color-coded by classification:
     - Green = consensus (agreed actions)
     - Yellow = tension (pending decisions)
     - Red = direct conflict
     - Grey = missing-data block / safety caveat
   - Include the Mermaid block in the markdown response (PO renders Mermaid)
   - Keep the diagram tight — max 12 nodes; if more, summarise with "+N more"
   - The diagram should appear AFTER specialist views, BEFORE the agreed-actions list

2. **Streaming specialist views (best-effort)**
   - Investigate whether MCP supports streaming (yields) and whether PO renders streamed tool output
   - If yes: emit specialist results as each Gemini call completes (rather than batched)
   - If no, or if it adds complexity beyond ~2 hours: SKIP — keep current parallel batch
   - DO NOT regress current behaviour

3. **Multi-hero patient demo**
   - Create FHIR bundle for **Patricia Quinn** — clean-consensus case
     - Profile: HFrEF (LVEF 35%) + stable CKD3a (eGFR 52) + mild congestion (BNP 250, weight stable)
     - Expected outcome: all 3 specialists AGREE on plan (continue current GDMT, monitor)
   - Create FHIR bundle for **Frances Doyle** — insufficient-data case
     - Profile: suspected HF (symptoms) + missing BNP / echo / recent labs / weight
     - Expected outcome: specialists honestly say "cannot decide without X" — surfaces missing-data classification
   - Bundle format must match `fhir-bundles/patient-arthur-*.json` pattern (existing Concord patient)
   - Document these patients in a new `fhir-bundles/concord-patients-README.md` or update existing README

4. **Demo script for Concord**
   - `agent-config/concord-demo-script.md`
   - 3-min walkthrough showing all three patients
   - Timing breakdown per second
   - Narration explicitly addressing AI Factor ("three specialty Gemini reasoners in parallel...")
   - Visual cues / overlay suggestions for video editor

### Hard rules

- **Mermaid syntax must be valid.** Test by pasting into a Mermaid live editor before committing.
- **FHIR bundles must be valid R4.** Use existing patient bundle as a template. UUID `fullUrl` per memory feedback file.
- **No regression in tool runtime.** Mermaid generation should add <1s. Streaming, if implemented, must not exceed current 50s cap.
- **Don't modify `medsafe_core/`** — that's Workstream A's territory.
- **Don't modify `signalloop-medsafe-mcp/`** — that's Workstream A's territory.
- **Existing tests must still pass.** Add new tests for Mermaid generation.

### Acceptance criteria

- Mermaid diagram renders in PO chat (verify by deploying and testing)
- Both new FHIR bundles upload to PO without errors
- Demo script achievable in 2:30-3:00 with all three patients
- Concord still completes in <30s end-to-end on Arthur

---

## Cross-workstream rules

- **Each agent must report back what it changed**, in summary form, when finished.
- **Each agent must run existing tests** before signalling "done."
- **No agent deploys to Fly** — deployment is the user's call after review.
- **No agent commits to git** — leave changes uncommitted for user review.
- **No agent modifies `IMPROVEMENT-PLAN.md` or `AGENTS.md` at the repo root** without explicit instruction.

## Sequencing notes

- A, B, C run in parallel.
- B has a dependency on A (the new `SurfacePatientAttention` tool). B documents the requirement; A implements the tool.
- Concord's deployment (when needed) is independent of A and B.

## Out of scope for this round

- Marketplace publication (manual user task)
- Demo video recording (manual user task)
- Real-clinic validation (separate effort)
- MedSafe ↔ Concord cross-pollination (e.g., Concord using MedSafe's CheckBeers internally) — possible future enhancement
- Real-time conflict monitoring for Concord (too speculative)
- Cohort-level surveillance for SignalLoop (extends scenarios beyond what fits the demo budget)
