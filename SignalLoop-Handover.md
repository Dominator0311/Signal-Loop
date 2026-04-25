# SignalLoop — Session Handover Document

> **Purpose:** complete context bootstrap for a new Claude session. Read top-to-bottom before making any changes. This is the single source of truth as of 2026-04-21.
>
> **Related docs (do not duplicate, cross-reference):**
> - `CLAUDE.md` — project instructions (non-negotiable architectural principles)
> - `PLATFORM-NOTES.md` — Prompt Opinion platform research
> - `SignalLoop-Final-Operational-Plan.md` — frozen execution plan (authoritative)
> - `SignalLoop-Master-Spec.md` — blue-sky vision (north-star, not scope)
> - `SignalLoop-Built-System.md` — earlier system documentation
> - `PromptOpinion-Platform-Scope.md` — platform capability scope
> - `fhir-bundles/README.md` — bundle upload + consult architecture
> - Memory index: `~/.claude/projects/-Users-abhinavgupta-Desktop-Med/memory/MEMORY.md`

---

## 0. TL;DR for a fresh session

- **Hackathon:** Prompt Opinion "Agents Assemble", deadline **2026-05-11**.
- **One codebase → two submissions:**
  - **Product A:** MedSafe MCP Server (Superpower/MCP category)
  - **Product B:** SignalLoop Renal Safety Agent (Agent/A2A category)
- **Both products working end-to-end.** All 5 core scenarios pass on clean workspace.
- **Current focus:** demo production + pre-submission hardening.
- **Open strategic questions answered below:** MCP is likely too narrow (proposal to expand to 7 tools); Agent demo is likely too linear (proposal to redesign as multi-turn, multi-scenario). Both changes detailed in §11.
- **Known platform limitations:** Documents tab uses session-cookie auth and is unreachable from MCP; workaround = embed DocumentReference inline in FHIR bundle. Documented.
- **Pending infrastructure:** Fly.io migration before Marketplace publish + judging window (replaces ngrok). See memory note `project_flyio_migration.md`.

---

## 1. Product architecture — what the two products ARE

### Product A — MedSafe MCP Server (Superpower)

**One-liner:** An MCP server exposing a three-phase medication safety engine as callable tools. Any Prompt Opinion agent (or external MCP client) can invoke it against the current patient's FHIR record to get a structured safety verdict.

**Core property:** horizontal capability. Stateless, single-turn, read-only, not workflow-specific.

**Current tool surface (3 tools):**
- `BuildPatientRiskProfile` — Phase 1 LLM pass. Builds a structured `LLMPatientRiskProfile` from the patient's FHIR record.
- `CheckRenalSafety` — Phase 2 deterministic rules engine. No LLM. Returns `SafetyVerdict` (BLOCK / WARN / CLEAN) with flags, `rule_id`, citations, and `profile_fields_consulted`.
- `GetRenalTrend` — pure renal trajectory computation from historical eGFR observations. Overrides LLM-estimated trends with deterministic math.

**Plus supporting FHIR read primitives and Phase 3 narrative synthesis** used internally by the tools.

### Product B — SignalLoop Renal Safety Agent (Agent/A2A)

**One-liner:** A BYO in-platform agent that runs one narrow clinical workflow end-to-end: ingest a returned nephrology consult, extract its recommendations, reconcile against the current record, and draft the prescription + follow-up task changes for clinician approval and FHIR commit.

**Core property:** vertical workflow. Stateful, multi-turn, read + write, approval-gated.

**Workflow (consult loop closure):**
1. **Discovers** the consult DocumentReference in the patient's record (tier-1: LOINC 11488-4 search; tier-2: keyword fallback).
2. **Extracts** recommendations from the consult text (inline base64 text/plain, text/markdown, or PDF via pypdf).
3. **Reconciles** against current medications via `DetectPlanConflicts` (stop+start pairs correctly interpreted as switches, not dual-therapy conflicts).
4. **Drafts** FHIR resources: `MedicationRequest` (new/stop/adjust) and `Task` (follow-up labs, counselling, clinic review) with server-computed `due_date` from `timing` parameter.
5. **Presents** the full plan to the clinician in one pane for approval.
6. **Commits** approved resources to FHIR as a batch with `AuditEvent` trail.

### Non-overlap contract between A and B

| Axis | Product A (MCP) | Product B (Agent) |
|---|---|---|
| Primary artifact | Tools | Workflow |
| Read or write | Read-only | Read + write |
| State | Stateless | Stateful |
| Turns | 1 | Many |
| Demo content | 4 isolated queries | 1 continuous scenario (current plan) |
| Primary verb | "check" | "action" |
| User | Any agent builder | End-user clinician |

**Narrative glue:** the Agent explicitly calls MedSafe MCP under the hood during its conflict check step. Makes the two submissions a deliberate pair, not a split.

---

## 2. Three-phase MedSafe architecture (non-negotiable)

This is the foundational architectural principle in `CLAUDE.md`:

- **Phase 1 (LLM):** Build structured patient risk profile from FHIR record → `LLMPatientRiskProfile` via Gemini structured output.
- **Phase 2 (Rules):** Deterministic safety check — **NO LLM**. Pure Python rules engine consuming JSON rule files. Outputs `SafetyVerdict` with flags, rule IDs, citations.
- **Phase 3 (LLM):** Synthesise patient-specific response (alternatives, counselling, explanation) using Phase 1 profile + Phase 2 verdict.

**Core invariant:** the LLM NEVER makes safety verdicts. Rules make verdicts. LLM contextualises them.

**Enforcement:**
- `rules/engine.py` must never call an LLM. Tests verify this.
- Every Phase 2 flag has `rule_id`, `citation` (evidence source), and `profile_fields_consulted` (audit trail).
- Severity × evidence_level matrix maps deterministically to verdict.

---

## 3. Tech stack

- **Runtime:** Python 3.14, FastAPI, FastMCP SDK (`mcp>=1.9.0`)
- **LLM:** Gemini 3.1 Flash Lite Preview (recently migrated from 2.5 Flash Lite) via `google-genai` SDK; structured output with Pydantic schemas.
- **Transport:** Streamable HTTP via ngrok reserved domain (migrating to Fly.io free tier).
- **FHIR:** R4, dm+d coding (UK context).
- **PDF parsing:** `pypdf>=5.0.0` (lazy import in `referral.py`).
- **Auth:** JWT decoded for `x-patient-id` extraction; SHARP headers `x-fhir-server-url`, `x-fhir-access-token`, `x-patient-id`; extension `ai.promptopinion/fhir-context` with SMART scopes.
- **FHIR writes:** require clinician approval, enforced at agent level.

---

## 4. Code structure

```
signalloop-medsafe-mcp/          ← Submission A (also powers Submission B)
├── main.py                      ← FastAPI entry point
├── server.py                    ← MCP instance + tool registration
├── config.py                    ← Environment config (model name, API keys)
├── .env.example
├── requirements.txt             ← includes pypdf>=5.0.0
├── fhir/                        ← FHIR client + SHARP context extraction
│   └── (HTTP client, context resolution, JWT decode)
├── rules/                       ← Deterministic rules engine (NO LLM)
│   ├── engine.py                ← Pure functions, severity matrix
│   │                              Contains `_evaluate_scope_guards`
│   │                              (pediatric BLOCK short-circuits other rules)
│   └── data/                    ← JSON rule files (interaction, renal, Beers)
├── llm/                         ← Gemini client + prompt modules
│   ├── client.py                ← Includes `_call_with_retry` w/ exponential backoff
│   │                              for 503/429/504 errors
│   ├── schemas.py               ← Pydantic schemas for structured output
│   │                              `LLMPatientRiskProfile` has `first_name: str | None`
│   └── prompts/                 ← One module per capability
├── tools/                       ← MCP tool implementations (orchestration only,
│   │                              no business logic)
│   ├── phase1.py                ← Profile building + `_extract_first_name`
│   │                              (deterministic from FHIR Patient.name[0].given[0])
│   ├── referral.py              ← Consult discovery + extraction
│   │                              `_extract_document_text`, `_fetch_attachment_by_url`,
│   │                              `_resolve_relative_url`, `_looks_like_pdf`,
│   │                              `_extract_pdf_text`, CONFLICT_DETECTION_SYSTEM prompt
│   └── writes.py                ← FHIR write drafting + commit
│                                  `timing` param, `_compute_due_date_from_timing`,
│                                  `_coerce_due_date` (rejects past dates)
└── tests/                       ← pytest, rules-engine focused

fhir-bundles/                    ← Patient data for upload
├── README.md                    ← Upload order + architectural notes
├── _convert_to_post.py          ← PUT → POST bundle converter
│                                  Deterministic uuid5 generation via
│                                  SIGNALLOOP_NAMESPACE constant
├── patient-margaret-post.json   ← ACTIVE (includes inline consult DocumentReference)
├── patient-doris-post.json      ← ACTIVE
├── patient-james-post.json      ← ACTIVE
├── patient-documents/           ← PDF versions for human reference only
│   ├── _convert_to_pdf.py       ← Chrome-headless markdown → PDF
│   ├── margaret-nephrology-consult.md   ← source of truth
│   └── margaret-nephrology-consult.pdf  ← 149KB, reference artifact
└── _archive/                    ← superseded files
```

**Non-negotiable structural rules (from CLAUDE.md):**
- `fhir/` — SHARP context + FHIR HTTP client only.
- `rules/` — Deterministic logic + JSON; no LLM, no I/O beyond JSON loading.
- `llm/` — Gemini client + prompts as first-class artifacts.
- `tools/` — Thin orchestration. No business logic.
- Each module has a single responsibility.

**Data contracts:**
- `PatientRiskProfile` — shared contract Phase 1 → Phase 2 → Phase 3.
- `SafetyVerdict` — Phase 2 output consumed by Phase 3.
- All LLM outputs use structured generation (Pydantic → JSON schema → Gemini).

---

## 5. Demo patients (upload order matters)

| Patient | Age/Sex | Clinical profile | Demo scenarios |
|---|---|---|---|
| **Margaret Henderson** | 72F | CKD 3b, T2DM, HTN, OA. On ACE-I + diuretic. eGFR 42 (declining from 52 over 5 months). | Hero BLOCK (NSAID + triple-whammy), consult loop closure |
| **Doris Williams** | 67F | RA on methotrexate | WARN + Override flow |
| **James Okonkwo** | 42M | Healthy | Safe control (CLEAN) |

**Upload order:** margaret → doris → james. All three bundles upload as FHIR transactions. No separate consult-upload step — the consult lives inline in Margaret's bundle.

**On re-upload:** server-assigned UUIDs differ per workspace. Bundle-local `urn:uuid` cross-references resolve automatically at ingestion. No post-upload patching needed.

**Known content detail:** Margaret's consult uses corrected "5 months" and "~3 points/month" (matches observation dates Nov 2025 → Apr 2026). The archived JSON bundle had inconsistent "3 months" / "~4 points/month" — fixed in current PDF version.

---

## 6. Complete list of problems encountered + fixes applied

### 6.1 Raw JSON in chat output
- **Cause:** Response Format tab had JSON schema pasted; forced every output to JSON.
- **Fix:** clear the Response Format tab in Prompt Opinion.
- **Status:** resolved.

### 6.2 Margaret name hallucinated for other patients
- **Cause:** LLM copied "Margaret" from prompt template verbatim when running on Doris/James.
- **Fix:** added Patient Identity Rule to prompt; changed format specs to `[actual patient first name]` placeholders; added `first_name: str | None` field to `LLMPatientRiskProfile` populated deterministically from `Patient.name[0].given[0]` via `_extract_first_name` in `tools/phase1.py`.
- **Status:** resolved. First name now carries through Phase 3.

### 6.3 Write tool loop on pediatric patient
- **Cause:** Flash Lite Preview couldn't respect "STOP" instruction on empty-record pediatric case; kept trying to draft.
- **Fix:** added deterministic pediatric scope guard in `rules/engine.py::_evaluate_scope_guards`. Fires BLOCK for patients under 18, short-circuits evaluation before other rules.
- **Status:** resolved.

### 6.4 Task `due_date` values in the past (2025)
- **Cause:** LLM passed past dates because training cutoff was older than current date.
- **Fix:** added `timing` parameter to `tools/writes.py` (e.g., "6 weeks", "3 months"); added `_compute_due_date_from_timing` helper using `datetime.now() + timedelta`; added `_coerce_due_date` that rejects past dates from LLM.
  ```python
  _TIMING_PATTERN = re.compile(
      r"(?:in\s+|at\s+|after\s+)?(\d+)\s*(day|days|week|weeks|month|months|year|years)",
      re.IGNORECASE,
  )
  ```
- **Status:** resolved. Verified in test: `2026-06-02`, `2026-04-22`, `2026-07-20` due dates.

### 6.5 `DetectPlanConflicts` false "dual RAAS blockade"
- **Cause:** Tool flagged a stop-ramipril/start-irbesartan pair as dual RAAS blockade conflict.
- **Fix:** rewrote `CONFLICT_DETECTION_SYSTEM` prompt in `tools/referral.py` to explicitly handle stop+start pairs as switches, not conflicts.
- **Status:** resolved. Test showed `conflicts_detected: []`.

### 6.6 Fabricated reconciliations (eGFR/stage pseudo-conflicts)
- **Cause:** LLM inventing conflicts where none existed.
- **Fix:** governance rule in prompt explicitly prohibits treating eGFR values or CKD stage as conflicts.
- **Status:** resolved. Test showed Metformin flagged (real) only.

### 6.7 Documents tab PDF unreachable
- **Cause:** Prompt Opinion's Documents tab stores files on a proprietary `/downloads/` endpoint requiring **browser session-cookie authentication**. MCP servers authenticate with FHIR Bearer tokens and cannot reach that endpoint — server serves an HTML login shell instead of file bytes. Multiple patches attempted (keyword match, URL fetch, scheme resolution, Accept header) all failed.
- **Root cause analysis (forced by user pushback "no patchwork"):** platform-level auth boundary. Documents tab auth context ≠ MCP auth context. Architecturally unreachable, not a code bug.
- **Fix:** moved consult INSIDE Margaret's FHIR bundle as a `DocumentReference` with inline base64 content. Documents tab limitation acknowledged as platform limitation.
- **Status:** resolved. Inline approach is also how real EHRs ingest specialist letters (HL7/FHIR feed from hospital systems) — production-equivalent pattern.

### 6.8 Cross-bundle UUID brittleness
- **Cause:** Splitting consult into a separate bundle meant `urn:uuid` cross-refs didn't resolve (they only resolve within one bundle).
- **Fix:** consolidated consult into Margaret's bundle. Single atomic upload. All `urn:uuid` refs resolve at ingestion.
- **Status:** resolved. Verified in test: `discovery_tier: "loinc_coded"` tier-1 hit.

### 6.9 Gemini 503 / 429 / 504 transient errors
- **Fix:** added `_call_with_retry` helper in `llm/client.py` with exponential backoff. Both `generate_structured` and `generate_text` use it.
- **Status:** resolved.

### 6.10 `rate_of_change_per_month` sign inconsistency (OPEN, cosmetic)
- **Observation:** Phase 1 profile sometimes shows `rate_of_change_per_month: 3.2` when eGFR is declining (should be `-3.2`).
- **Impact:** harmless. `GetRenalTrend` overrides with deterministic math. Never surfaces in user-facing output.
- **Potential fix:** add one line to Phase 1 prompt: "For declining values, use negative numbers (e.g. eGFR decline of 3/month = -3.0)." 30s fix.
- **Status:** optional polish, not a blocker.

---

## 7. Platform limitations (MUST be called out or worked around in demo)

### 7.1 Documents tab inaccessibility (RESOLVED via workaround)
- **What judges might ask:** "Why isn't the consult in the Documents tab?"
- **Prepared answer (30 seconds):** "Prompt Opinion's Documents tab uses session-cookie auth; MCP servers use FHIR Bearer tokens — they're different auth contexts by design. Our solution uses inline FHIR `DocumentReference` with base64 content, which is how real EHRs ingest specialist letters in production via HL7/FHIR feeds. UX is identical for clinicians; our MCP can read it via standard FHIR paths."
- **Do not hide this.** Own it.

### 7.2 Prompt Opinion agent UI tool-call visibility (UNKNOWN RISK)
- **Concern:** if UI swallows tool-call traces invisibly, the multi-turn agent demo loses its visible reasoning.
- **Action required BEFORE committing to multi-turn redesign:** verify rendering in actual UI.

### 7.3 Fly.io migration (PENDING)
- **Reason:** ngrok reserved domain is fine for testing but must be replaced before Marketplace publish + judging window.
- **Target:** Fly.io free tier.
- **See memory:** `project_flyio_migration.md`.

### 7.4 Model version dependency
- **Current:** Gemini 3.1 Flash Lite Preview.
- **Risk:** "Preview" model may degrade or be pulled. If it becomes unstable, fall back to 2.5 Flash Lite (verified working previously).
- **Cost implication:** 3.1 is cheaper than 2.5 for similar capability — noted in ongoing model evaluation.

---

## 8. Verified test scenarios (all passing on clean workspace)

Test run reference: Margaret `patient_id: 043250b0-0b5b-4988-95dd-2690249a245c` (new workspace UUID).

### Scenario 1 — Margaret BLOCK
- ✅ Phase 1 profile: `first_name = "Margaret"`, age 72, eGFR 42, CKD 3b.
- ✅ Phase 2 all 3 flags fired: `triple-whammy-aki`, `renal-nsaid-egfr-60`, `beers-nsaid-chronic`.
- ✅ Phase 3 alternatives: Paracetamol, Topical Diclofenac Gel.
- ✅ Reconciliation scope correct: Metformin flagged only (real conflict).
- ✅ "For the patient" line present in plain language.
- ✅ Verdict: `block`, no FHIR writes (Mode governance respected).
- ⚠️ Cosmetic: `rate_of_change_per_month: 3.2` should be `-3.2` (see §6.10).

### Scenario 2 — James CLEAN
- ✅ No flags, CLEAN verdict on ibuprofen query.

### Scenario 3 — Doris WARN
- ✅ WARN verdict on naproxen query with MTX.
- ✅ Override path with captured rationale.

### Scenario 4 — Pediatric SCOPE LIMIT
- ✅ Rules-engine pediatric guard fires BLOCK.
- ✅ No write-tool drafting loop.

### Scenario 5 — Margaret consult loop closure
- ✅ `discovery_tier: "loinc_coded"` (tier-1 LOINC 11488-4 hit).
- ✅ 7 recommendations extracted from inline base64 consult.
- ✅ `DetectPlanConflicts` returned `conflicts_detected: []` (no false dual RAAS).
- ✅ 3 MedicationRequests drafted (irbesartan, furosemide 20mg, dapagliflozin).
- ✅ 3 Tasks with correct 2026 due dates (`2026-06-02`, `2026-04-22`, `2026-07-20`).
- ✅ Headline uses "Margaret" (first_name propagating through Phase 3).
- ✅ Clean markdown output, no JSON leak.

**All 5 scenarios validated on hardened stack. Product ready for submission prep track.**

---

## 9. Current baseline demo plans (pre-enhancement)

> **Important:** this is the CURRENT/BASELINE plan. See §11 for proposed enhancements that likely supersede the agent demo.

### 9.1 Product A demo (MCP) — ~90s

Four isolated medication-safety queries through a generic Prompt Opinion assistant (not SignalLoop agent):

1. **Margaret BLOCK** — "Can she take ibuprofen?" → BLOCK, 3 flags, rule traceability visible.
2. **James CLEAN** — same question, different patient → CLEAN.
3. **Doris WARN + Override** — "Can she take naproxen?" → WARN, override with rationale.
4. **Pediatric scope guard** — any NSAID query → deterministic BLOCK "outside scope".

**Headline beats:**
- Open: "Medication safety today is either brittle rules or ungrounded LLMs. MedSafe does both — LLM builds profile, rules make verdict, LLM explains it."
- Narrate 3-phase architecture as rules trace renders.
- Close: "Any Prompt Opinion agent builder can drop medication safety into their workflow with one MCP connection."

**Assets to prepare:**
- Pre-staged saved prompts for snappy scenario switching.
- Rule JSON files open in side tab (visual: "rules engine reads this — no magic").
- Clean rules trace rendering.

### 9.2 Product B demo (Agent) — single-scenario baseline (~90s)

One continuous scenario: Margaret consult loop closure.

1. Setup (5s): "Margaret referred to nephrology 4 weeks ago. Dr Patel's letter arrived."
2. Trigger (10s): clinician prompts SignalLoop agent.
3. Discovery (15s): agent finds consult via LOINC, shows 7 recommendations.
4. Conflict check (10s): no false dual RAAS blockade.
5. Drafting (15s): 3 MedicationRequests + 3 Tasks with computed due dates.
6. Approval & commit (10s): AuditEvent trail.
7. Close (5s): "15 min of manual work → <1 min. Clinician-in-loop throughout."

**Cross-reference bumper:** 5s at end: "Built on MedSafe MCP — also submitted as a Superpower."

---

## 10. Key context / operational reminders

### 10.1 Demo patient UUIDs
- Server-assigned per workspace; **do not hardcode**.
- MCP resolves via SHARP `x-patient-id` header at runtime.
- Current test workspace: Margaret = `043250b0-0b5b-4988-95dd-2690249a245c`.

### 10.2 UUID brittleness — answered
- Bundle `urn:uuid` values are deterministic uuid5 via `SIGNALLOOP_NAMESPACE` constant in `_convert_to_post.py`.
- Not hardcoded at runtime. Internal refs resolve at HAPI ingestion.
- Only genuine runtime-hardcoded value is LOINC `11488-4` (clinical identifier, not UUID). Keyword-match fallback exists.
- One cheap hardening: add pre-upload link-integrity validator to converter. Not blocking.

### 10.3 Bundle regeneration
- Source of truth: PUT-style bundles (if kept) + consult `.md` source in `patient-documents/`.
- `_convert_to_post.py` → POST bundles with proper UUIDs.
- `_convert_to_pdf.py` → PDFs from `.md` (Chrome headless, reference only).
- Requires `markdown` package + Chrome at `/Applications/Google Chrome.app`.

### 10.4 Gemini model currently `gemini-3.1-flash-lite-preview`
- Set in `config.py` and `.env.example`.
- Fallback to 2.5 Flash Lite if 3.1 Preview becomes unstable.

### 10.5 Memory system
- Path: `~/.claude/projects/-Users-abhinavgupta-Desktop-Med/memory/`
- Index: `MEMORY.md`
- Key entries as of this handover:
  - `project_signalloop_hackathon.md` — may be stale, verify
  - `user_beginner_collaborative.md` — user profile, discussive partnership preference
  - `feedback_fhir_uuid_spec.md` — `Bundle.entry.fullUrl` must contain real UUIDs
  - `feedback_debug_with_devtools.md` — Network tab first
  - `feedback_llm_boolean_defaults.md` — LLMs ignore optional bool defaults with verb-y names
  - `feedback_fhir_cross_bundle_refs.md` — `urn:uuid` only resolves within one bundle
  - `project_flyio_migration.md` — pending Fly.io migration

### 10.6 Deadline & timing
- **Hackathon deadline:** 2026-05-11.
- **Today:** 2026-04-21. ~20 days remaining.
- **Final week budget:** recording both demo videos. Everything else must close before then.

### 10.7 Hackathon judging criteria (Devpost)
- **AI Factor** — sophistication, novelty.
- **Impact** — real clinical problem, measurable improvement.
- **Feasibility** — actually working, not aspirational.

### 10.8 Judging narrative priorities (from critical analysis)
- Cite every clinical rule source inline (NICE CG182, AGS Beers 2023, STOPP/START v2). Free credibility.
- Before/after metric for Product B: "15–30 min → <1 min" needs a source (RCGP admin-burden papers on consult handling — find citation).
- Narrow + deep beats broad + shallow for clinical judges. Broad appearance still matters for non-clinical judges.

### 10.9 Clinical scope (do not expand without decision)
- Renal decline, NSAID safety in CKD, nephrology referral loop closure.
- UK context (dm+d, NICE, BNF).
- Any expansion (e.g., new clinical axes) is a deliberate choice, not a drift.

---

## 11. Proposed enhancements (strategic — review before execution)

> **Source:** critical analysis session 2026-04-21. User explicitly asked for hole-finding, not validation. These are recommendations, not committed scope.

### 11.1 Context — why enhancements are being proposed

Honest assessment after critical analysis:

- **Product A is likely too narrow.** Three tools along one clinical axis (renal + NSAIDs) may read to judges as "a feature, not a platform." Competing MCP submissions may have broader surfaces. Our depth-first story is architecturally sound but may lose at first-pass skim.
- **Product B is likely too linear.** A single-prompt → single-response agent demo is not an agent demo — it's a tool-execution demo. Single-scenario coverage doesn't answer the "does this generalize?" question that kills agent submissions.

**Priority ranking for enhancements:** agent demo redesign > MCP expansion. If only one can be done, do the agent redesign — higher judging impact per unit work.

**Biggest risk to all proposals:** Prompt Opinion's agent UI rendering of multi-turn + visible tool calls. MUST be verified before committing to the redesign.

---

### 11.2 Product A — MCP expansion

**Goal:** expand from "renal NSAID checker" to "UK safe-prescribing foundation." Target 6-8 tools total, not 30.

**Hard requirement:** every new rule must cite its clinical source verbatim (NICE, BNF, AGS Beers, STOPP/START). No inventing rules.

**Proposed additions (ranked by value-to-cost):**

| Tool | Description | Build cost | Value | Priority |
|---|---|---|---|---|
| `CheckRenalDoseAdjustment` | Given drug + eGFR, return renally-adjusted dose (BNF rules) | Low (wraps existing renal profile + JSON table) | High — real clinical problem, published guidance | 1 |
| `CheckBeersCriteria` | Full Beers 2023 for elderly (not just NSAIDs, top 10 categories) | Medium (~10 categories of JSON) | High — AGS Beers is canonical | 2 |
| `CheckSTOPPSTART` | STOPP/START v2 criteria for 65+ patients | Medium (similar to Beers) | Very high — UK-native (Beers is US) | 3 |
| `CheckDrugDrugInteraction` | Pairwise DDI beyond the NSAID/ACE case | Medium (DDI JSON seeded from BNF Appendix 1 common pairs) | High — universally recognised | 4 |

**Recommended pick:** all 4. Gets to 7 total tools along one coherent axis ("UK safe-prescribing primitives").

**Explicit DO-NOT adds:**
- Allergy checking (FHIR `AllergyIntolerance` data is notoriously incomplete; high false-negative risk embarrasses on demo)
- External API dependencies (BNF, NICE Evidence — network + licensing risk)
- General "ask the guidelines" LLM wrappers (violates 3-phase principle)
- Anything past 10 total tools (tool-selection quality degrades, narrative dilutes)

**Reframe requirement:** if expanded, pitch changes from "medication safety for CKD" to **"deterministic UK safe-prescribing primitives."** Otherwise reads as bolted-on features.

**Cost estimate:** ~10 days of work (JSON authoring, tool integration, testing against Phase 1 pipeline).

**Testing requirement:** Phase 1 prompt must be tested against all new tools. Context bloat and tool-selection errors are real risks.

**Critical pushback noted:** this plan assumes the competition is strong. If a check of past Prompt Opinion hackathon winners shows weaker bars, this is over-investment. Research task: find past winners, 30 min budget.

---

### 11.3 Product B — Agent demo redesign

**Goal:** transform from scripted linear pipeline to conversational multi-turn agent with clinician in the loop. Total demo length 2:30–3:00 min (longer justified by agent complexity).

**Structure: three scenarios, not one.** Each shows a different agent capability.

#### Scenario 1 (60s) — Proactive surveillance (the "wow moment")

**Purpose:** open with the thing nothing else on the platform does. Reasoning across the whole patient record, not executing one task.

Turn 1 — Clinician: "What needs my attention for Margaret today?"
Turn 2 — Agent (tool calls visible in UI):
> "Three things:
> 1. eGFR has dropped 52 → 42 over 5 months — trajectory of decline.
> 2. She's on ibuprofen which is contraindicated at this eGFR — 2024-Nov prescription, BLOCK flagged retrospectively.
> 3. Nephrology consult returned 2 weeks ago with 7 unactioned recommendations.
>
> Which would you like to address?"

Turn 3 — Clinician: "Start with the consult."
Turn 4 — Agent: [proceeds to scenario 2]

**Implementation cost:** NEW capability. Requires orchestrated call to GetRenalTrend + safety-audit-on-current-meds + ConsultDiscovery. Estimated 1-2 days. **This is the one scenario that adds scope.** If bandwidth-limited, cut it.

#### Scenario 2 (75s) — Consult loop closure as multi-turn conversation

**Purpose:** show approval-gating, editability, state retention. Same core workflow as current baseline, presented as conversation rather than pipeline.

Turn 1 — Agent: "Dr Patel (nephrology) returned this plan on 7 April. Summary: [7 bullets]. Shall I check it against Margaret's current record?"
Turn 2 — Clinician: "Yes."
Turn 3 — Agent: "I ran conflict detection. One note: Dr Patel recommends irbesartan. Margaret is on ramipril. This is a **switch** (stop ramipril, start irbesartan), not dual RAAS blockade — I won't flag it as a conflict. Confirm?"
Turn 4 — Clinician: "Confirmed."
Turn 5 — Agent: "Drafted: 3 prescriptions (1 stop, 2 start), 3 follow-up tasks. Review: [structured plan]."
Turn 6 — Clinician (edits): "Change the eGFR repeat to 4 weeks not 6."
Turn 7 — Agent: "Updated. Ready to commit?"
Turn 8 — Clinician: "Commit."
Turn 9 — Agent: "Committed. AuditEvent 4512 logged. I'll remind you at each task's due date."

**Explicit call-outs in demo narration:**
- Switch-vs-dual-RAAS moment — the clinical reasoning a pure-LLM agent would miss.
- Clinician-edited task due date — shows editability, state preservation.
- AuditEvent — shows compliance/audit story.

**Implementation cost:** mostly recording production. Small code changes to support in-flight edits if not already supported.

#### Scenario 3 (30s) — Novel prescription check, demonstrating MCP integration

**Purpose:** show Product A and Product B are architecturally linked, not duplicated.

Turn 1 — Clinician (different patient — Doris): "I want to prescribe naproxen for her joint pain."
Turn 2 — Agent: "Running safety check via MedSafe. [visible MCP tool calls: CheckRenalSafety → WARN; CheckBeersCriteria → flag; CheckDrugDrugInteraction with MTX → WARN]. Verdict: WARN, two independent flags. Alternatives, or override with rationale?"
Turn 3 — Clinician: "Override — pain control takes priority; document I've counseled on AKI risk."
Turn 4 — Agent: "Drafted with rationale logged to AuditEvent. Commit?"

**Value:** explicit MCP integration visible in tool-call trace. Override flow covered.

#### One-shot mode handling

Mention at close, do NOT demo:
> "Clinicians can also trigger the full workflow in one prompt: 'run Margaret's consult workflow end-to-end.' We show the multi-turn version because it reflects how clinicians actually think, but the agent supports both."

**Reason:** demoing one-shot after multi-turn makes the multi-turn version look padded. Mention and move on.

---

### 11.4 Holes and risks in the proposed enhancements

1. **UI rendering risk (CRITICAL):** Prompt Opinion may not render multi-turn + tool-call visibility cleanly. If tool calls are invisible, the "agent reasoning" story collapses to narrated text. **Verify in UI before committing.**
2. **Context bloat on 7 MCP tools:** Phase 1 prompt has to know about all of them. Tool-selection degradation is real. Budget time to test each new tool in pipeline.
3. **Proactive surveillance scenario requires tool-selection without a specific prompt.** Real agent failure mode. Prompt-engineering pass required. Fallbacks for when agent doesn't call the right tool.
4. **Clinical source-of-truth:** STOPP/START and Beers rules MUST be verbatim with citations. Physician judges will spot-check random rules. Inaccuracy = fail credibility hard.
5. **One recording attempt per video realistically.** Budget: don't try to do MCP expansion + agent redesign + recording in final week. If tight, drop MCP expansion (Priority 2) and keep agent redesign (Priority 1).
6. **Unknown competitive field.** All expansion arguments rest on assumed strength of competition. 30-min research task: find past Prompt Opinion hackathon winners if publicly available.

---

### 11.5 Priority plan (as of 2026-04-21)

| Priority | Task | Budget | Unlocks |
|---|---|---|---|
| 1 (TODAY) | Verify Prompt Opinion agent UI multi-turn + tool-call rendering. Research past hackathon winners if findable. | 4 hours | Green-lights the redesign |
| 2 (Week 1) | Agent demo redesign to multi-turn, 2-scenario (drop Scenario 1 if constrained). Highest judging impact per unit work. | ~5 days | Product B submission strength |
| 3 (Weeks 1-2) | MCP expansion: add 3 tools (CheckRenalDoseAdjustment, CheckBeersCriteria, CheckSTOPPSTART). Do NOT attempt 4. | ~10 days | Product A narrative broadened |
| 4 (Week 3) | Record both demos. MCP 90s covering 4 tools. Agent 2:30–3:00 with multi-turn redesign. | 3 days | Submission complete |
| 5 (Throughout) | Cite every rule's clinical source inline. Fly.io migration before Marketplace publish. Cosmetic fix for `rate_of_change_per_month` sign. | Rolling | Credibility + infra ready |

---

### 11.6 Single strongest recommendation

**Agent demo redesign > MCP expansion if forced to choose.** Going from scripted pipeline to conversational agent with edit/approval transforms perception of the submission. MCP expansion is nice-to-have; agent redesign is existential to Product B's Agent-category submission.

---

## 12. Specific files and code locations worth knowing for a new session

### Files modified during recent work (context for "why does this look like that")

- `/Users/abhinavgupta/Desktop/Med/fhir-bundles/patient-margaret-post.json` — consult DocumentReference inline, LOINC 11488-4, base64 text/plain, patient ref `urn:uuid:29540f77-...`, fullUrl `urn:uuid:451b045e-...`.
- `/Users/abhinavgupta/Desktop/Med/signalloop-medsafe-mcp/tools/referral.py` — tier-1/tier-2 discovery, `_extract_document_text`, `_fetch_attachment_by_url`, `_resolve_relative_url`, `_looks_like_pdf`, `_extract_pdf_text`, `CONFLICT_DETECTION_SYSTEM` prompt (rewritten for switch handling), UI-upload-detection branch returning `ui_uploaded_document_not_accessible`.
- `/Users/abhinavgupta/Desktop/Med/signalloop-medsafe-mcp/tools/writes.py` — `timing` param, `_compute_due_date_from_timing`, `_coerce_due_date`, `_TIMING_PATTERN` regex.
- `/Users/abhinavgupta/Desktop/Med/signalloop-medsafe-mcp/llm/schemas.py` — `first_name: str | None = None` on `LLMPatientRiskProfile`.
- `/Users/abhinavgupta/Desktop/Med/signalloop-medsafe-mcp/tools/phase1.py` — `_extract_first_name` deterministic helper.
- `/Users/abhinavgupta/Desktop/Med/signalloop-medsafe-mcp/rules/engine.py` — `_evaluate_scope_guards` pediatric short-circuit.
- `/Users/abhinavgupta/Desktop/Med/signalloop-medsafe-mcp/llm/client.py` — `_call_with_retry` with exponential backoff.
- `/Users/abhinavgupta/Desktop/Med/signalloop-medsafe-mcp/config.py` + `.env.example` — `gemini-3.1-flash-lite-preview`.
- `/Users/abhinavgupta/Desktop/Med/signalloop-medsafe-mcp/requirements.txt` — `pypdf>=5.0.0`.
- `/Users/abhinavgupta/Desktop/Med/fhir-bundles/README.md` — architectural decision documented.
- `/Users/abhinavgupta/Desktop/Med/fhir-bundles/patient-documents/` — `_convert_to_pdf.py`, `margaret-nephrology-consult.md`, `.pdf`.

### Constants worth knowing

- `SIGNALLOOP_NAMESPACE = uuid.UUID("6a4f4f74-7369-67e5-6c6c-6f6f7000b7fe")` in `_convert_to_post.py`.
- LOINC `11488-4` — consult note code, hardcoded in `referral.py` discovery.
- Chrome path: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` in `_convert_to_pdf.py`.

---

## 13. What a new session should NOT do without explicit permission

- Do not expand clinical scope (e.g., cardiology, endocrinology) — current narrowing is deliberate.
- Do not call an LLM from `rules/engine.py` (violates 3-phase principle, tests will fail).
- Do not add tools past 10 total on the MCP — tool-selection quality degrades.
- Do not invent rule content — cite NICE / BNF / AGS / STOPP-START verbatim.
- Do not `git reset --hard` or other destructive git operations without `git status` + stash first (see `~/.claude/CLAUDE.md`).
- Do not commit without explicit user request.
- Do not switch clinical sources without clinician-reviewable change.
- Do not hardcode any server-assigned UUIDs — runtime lookup only.
- Do not remove the Documents-tab platform-limitation workaround (inline DocumentReference) — it's load-bearing.

---

## 14. Open questions / decisions needed from the user

1. **Go/no-go on MCP expansion (§11.2).** Default recommendation: yes, add 3 tools. Alternative: keep lean, lean harder on narrative.
2. **Go/no-go on agent demo redesign (§11.3).** Default recommendation: yes, redesign to multi-turn. Blocker if UI rendering fails verification.
3. **Scenario 1 ("proactive surveillance") include or drop?** Default: include if UI verification passes and bandwidth allows; drop if not.
4. **Fly.io migration timing.** Before or after demo recording? Recommendation: before.
5. **Research past Prompt Opinion hackathon winners?** 30-min budget. Informs competitive assumptions.

---

## 15. Contact points / pointers

- Project root: `/Users/abhinavgupta/Desktop/Med/`
- MCP server: `/Users/abhinavgupta/Desktop/Med/signalloop-medsafe-mcp/`
- FHIR bundles: `/Users/abhinavgupta/Desktop/Med/fhir-bundles/`
- Rules data: `/Users/abhinavgupta/Desktop/Med/signalloop-medsafe-mcp/rules/data/` (and source in `/Users/abhinavgupta/Desktop/Med/medsafe-rules/`)
- Project memory: `/Users/abhinavgupta/.claude/projects/-Users-abhinavgupta-Desktop-Med/memory/`

---

**End of handover. A new session should be able to pick up directly from any of the priorities in §11.5 with this document as sole context.**
