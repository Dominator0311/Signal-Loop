# SignalLoop — Built System Reference

> Exhaustive reference for what has been built, how it works end-to-end, and what the observed behavior is. Authoritative for the hackathon submission — reflects the system as of 2026-04-20.

---

## 1. Executive Summary

**SignalLoop** is a dual-submission hackathon project for the Prompt Opinion platform (deadline 2026-05-11), targeting two categories from a single codebase:

| Submission | Category | What it is |
|---|---|---|
| **A — MedSafe MCP** | Superpower (MCP) | Reusable medication-safety gate exposed as an MCP server. Any agent on the platform can call it. |
| **B — SignalLoop Agent** | Agent (A2A) | A BYO patient-scope agent inside Prompt Opinion that uses MedSafe + its own orchestration to deliver renal safety, referral, and consult-loop-closure. |

The clinical scope is intentionally narrow: **renal decline (eGFR trending), NSAID safety in CKD, nephrology referral with loop closure.** One clinical thread, fully instrumented end-to-end, with three demo patients.

The system is **live** at the time of writing — MedSafe MCP is deployed via ngrok reserved domain, registered in Prompt Opinion, and the SignalLoop agent is configured with it. **Five core end-to-end clinical scenarios** have been validated in production (see §10.1 for the pass/fail detail).

---

## 2. Hackathon Context

### The ask from the platform

Prompt Opinion offers two hackathon categories:
- **Superpower** — build an MCP server any agent can use (emphasizes reusability)
- **Agent** — build a BYO agent for the platform (emphasizes clinical usefulness)

Both submissions draw from the same codebase. MedSafe is the MCP server (Submission A); the SignalLoop Agent (Submission B) consumes MedSafe's tools and adds orchestration logic the MCP itself doesn't contain.

### Why "renal safety" as the scope

A single clinical thread forces depth over breadth, which is what judges reward. Renal safety is chosen because:

1. **Rich tool surface.** eGFR trending, NSAID/ACE-I/diuretic interactions ("triple whammy"), Beers criteria, specialist referral, consult return — five distinct tool categories in one thread.
2. **Clear black-and-white scenarios.** Margaret on ACE-I + furosemide → NSAID = textbook contraindication. Judges understand this in one sentence.
3. **FHIR-native.** eGFR is an Observation, meds are MedicationRequest, stages are Condition — the full R4 vocabulary is naturally exercised.
4. **Loop closure is unique.** Most clinical AI demos stop at "alert fired." SignalLoop closes the loop by extracting recommendations from a returned consult and materializing them as FHIR resources.

---

## 3. Architecture Overview

### The three-phase MedSafe architecture (non-negotiable)

Every MedSafe interaction follows the same three phases:

```
┌──────────────────────────────────────────────────────────┐
│ PHASE 1 — LLM: FHIR record → Structured Risk Profile     │
│   Input:  FHIR resources (Patient, Condition, MedReq,    │
│           Observation, AllergyIntolerance)               │
│   Output: Pydantic LLMPatientRiskProfile                 │
│   Model:  Gemini 3.1 Flash Lite Preview (structured)     │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│ PHASE 2 — RULES: Profile + Medication → Verdict          │
│   Input:  Profile + proposed medication code             │
│   Output: SafetyVerdict (block / warn / clean) + flags   │
│   Engine: Pure Python. No LLM. No network.               │
│   Rules:  5 JSON files in rules/data/                    │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│ PHASE 3 — LLM: Verdict → Patient-Specific Narrative      │
│   Input:  Verdict + profile + medication                 │
│   Output: Narrative, alternatives, monitoring plan       │
│   Model:  Gemini 3.1 Flash Lite Preview                  │
└──────────────────────────────────────────────────────────┘
```

**Why this split is the point:** the LLM never makes a safety verdict. It translates between unstructured clinical data (Phase 1 in) and unstructured clinical prose (Phase 3 out). The verdict itself is deterministic, auditable, and testable without a network or LLM.

### The two submissions in one stack

```
┌─────────────────────────────────────────────────────┐
│  PROMPT OPINION PLATFORM (hosted)                   │
│  ┌────────────────────────────────────────┐         │
│  │  SignalLoop Agent (Submission B)       │         │
│  │  - System prompt with 6-mode orchestr. │         │
│  │  - Patient scope                       │         │
│  │  - Grounded to Content Collection      │         │
│  │  - A2A skill: renal_safety_consult     │         │
│  │  - FHIR context extension enabled      │         │
│  └────────────────────────────────────────┘         │
│                    │                                │
│                    │ MCP tool calls                 │
│                    ▼                                │
└─────────────────────────────────────────────────────┘
                     │
                     │ HTTPS (streamable HTTP)
                     ▼
┌─────────────────────────────────────────────────────┐
│  MedSafe MCP Server (Submission A)                  │
│  Hosted locally, exposed via ngrok reserved domain  │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐    │
│  │  Phase 1    │ │  Phase 2    │ │  Phase 3    │    │
│  │  (LLM)      │ │  (Rules)    │ │  (LLM)      │    │
│  │  3 tools    │ │  2 tools    │ │  2 tools    │    │
│  └─────────────┘ └─────────────┘ └─────────────┘    │
│  ┌─────────────┐ ┌──────────────────────────────┐   │
│  │  Referral   │ │  FHIR Writes                 │   │
│  │  4 tools    │ │  4 tools                     │   │
│  └─────────────┘ └──────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                     │
                     │ SHARP headers (x-fhir-server-url,
                     │                x-fhir-access-token,
                     │                x-patient-id)
                     ▼
┌─────────────────────────────────────────────────────┐
│  Prompt Opinion Workspace FHIR Server               │
│  (HAPI FHIR R4 instance, per-workspace)             │
└─────────────────────────────────────────────────────┘
```

### Data contracts between phases

Interfaces are Pydantic models — the single source of truth for every phase boundary:

- **`LLMPatientRiskProfile`** (Phase 1 → Phase 2): structured patient record with active conditions, active medications (each with drug classes), allergies, labs, and clinical context flags.
- **`SafetyVerdict`** (Phase 2 → Phase 3): `verdict` enum, list of `flags` (each with severity, rule_id, reason, citation), `profile_fields_consulted`.
- **`SynthesisedResponse`** (Phase 3 out): narrative, alternatives list, monitoring items, patient explanation.

Pydantic → JSON Schema → Gemini `response_json_schema` parameter → structured output enforced at decode time.

---

## 4. Component Inventory

```
signalloop-medsafe-mcp/           ← MCP server, runs locally
├── main.py                       ← FastAPI app, mounts MCP at /
├── server.py                     ← FastMCP instance + tool registration
│                                   + FHIR context extension declaration
├── config.py                     ← Environment variables (Gemini key, etc.)
│
├── fhir/                         ← FHIR layer (shared by all tools)
│   ├── context.py                ← SHARP header parsing, JWT decoding
│   ├── client.py                 ← httpx-based FHIR client (GET + POST)
│   └── resource_builders.py      ← Pure functions: dict → FHIR resource
│
├── llm/                          ← LLM layer (Gemini)
│   ├── client.py                 ← async wrapper around google-genai SDK
│   ├── schemas.py                ← Pydantic models for structured output
│   ├── cache.py                  ← 60-min TTL cache, asyncio.Lock
│   └── prompts/                  ← one module per prompt type
│       ├── profile_building.py
│       ├── safety_synthesis.py
│       └── override_analysis.py
│
├── rules/                        ← Deterministic rules engine
│   ├── engine.py                 ← Pure functions, no I/O
│   └── data/                     ← JSON rule data
│       ├── interaction_rules.json    ← drug-drug, drug-condition
│       ├── renal_dosing.json         ← eGFR-based thresholds
│       ├── beers_criteria.json       ← Beers 2023 subset
│       ├── drug_classes.json         ← brand/generic/class lookup
│       └── specialist_directory.json ← ranked specialist destinations
│
├── tools/                        ← MCP tool functions (thin orchestration)
│   ├── phase1.py                 ← BuildPatientRiskProfile, GetRenalTrend,
│   │                               GetRelevantContext
│   ├── phase2.py                 ← NormalizeMedication, CheckMedicationSafety
│   ├── phase3.py                 ← SynthesiseSafetyResponse,
│   │                               AnalyseOverrideReason
│   ├── referral.py               ← AssembleSpecialtyPacket,
│   │                               RankSpecialistDestinations,
│   │                               ExtractConsultRecommendations,
│   │                               DetectPlanConflicts
│   └── writes.py                 ← DraftMedicationRequest, DraftServiceRequest,
│                                   DraftFollowupTask, LogOverride
│
└── tests/                        ← pytest (rules engine focused)

agent-config/                     ← Paste-into-UI configs (not code)
├── system-prompt.md              ← Agent's orchestration brain
├── response-schema.json          ← (DEPRECATED for chat; kept for A2A)
├── response-schema-simplified.json  ← (DEPRECATED for chat)
└── content-collection/           ← 6 clinical reference markdown files

fhir-bundles/                     ← Patient data for workspace upload
├── patient-margaret-post.json
├── patient-james-post.json
├── patient-doris-post.json
├── consult-return-nephrology-post.json
└── _convert_to_post.py           ← Utility: converts PUT bundles to POST
```

---

## 5. The MedSafe MCP Server — Tool-by-Tool Reference

**15 tools total, organized by category.** Each returns JSON as its final string (tool-to-agent communication).

### 5.1 Phase 1 tools (LLM — Patient context)

#### `BuildPatientRiskProfile`
- **Purpose:** Fetch the patient's FHIR record (Patient, Conditions, MedicationRequests, Observations, AllergyIntolerances), feed it to Gemini with a structured-output schema, return a `LLMPatientRiskProfile`.
- **Caching:** 60-minute TTL cache, keyed on patient ID. Cache is async-safe (asyncio.Lock). First call builds; subsequent calls within TTL return cached data at near-zero cost.
- **Post-processing:** After Gemini returns the profile, `_enrich_profile_with_canonical_classes()` normalizes drug names via `drug_classes.json` and injects canonical class enum strings into each medication's `classes` field. This is the fix for Phase 2 rules that key on canonical enums (e.g., `ACE_INHIBITOR`) rather than LLM free text ("ACE inhibitor"). Without this enrichment, triple-whammy rules wouldn't fire.
- **Call frequency:** Once per patient session. The agent is explicitly instructed to call it whenever profile data is needed (cache handles cost).

#### `GetRenalTrend`
- **Purpose:** Query workspace FHIR for Observations of a given LOINC code (default: eGFR = `62238-1`), compute trajectory, return structured output with values, dates, rate of change, and a verdict (`stable`, `declining`, `improving`).
- **No LLM.** Pure math over Observation.valueQuantity.
- **Critical for Mode A (patient context)** — the agent uses this to decide whether to surface a proactive nephrology referral.

#### `GetRelevantContext`
- **Purpose:** Narrow tool — given a clinical signal (e.g., "eGFR dropped"), return only the subset of the patient's context relevant to interpreting it.
- **Useful for follow-up questions** where pulling the full profile is wasteful.

### 5.2 Phase 2 tools (Rules — Deterministic gate)

#### `NormalizeMedication`
- **Purpose:** Resolve free-text ("nurofen", "ibuprofen 400mg", "brufen") to a canonical medication name + dm+d code + drug class list.
- **How:** Lookup against `drug_classes.json` (hand-curated brand/generic/synonym → canonical). No LLM.
- **Returns:** `{resolved: bool, canonical_name, code, drug_classes: [...]}`.

#### `CheckMedicationSafety`
- **Purpose:** The **deterministic verdict gate**. Given the patient profile + a proposed medication, walk all rules and return a verdict.
- **No LLM, no network.** Pure Python over JSON rule files.
- **Rules evaluated** (matched in `rules/engine.py`):
  - Drug-drug interactions (from `interaction_rules.json`) — e.g., NSAID + methotrexate → major.
  - Drug-condition contraindications — e.g., NSAID + CKD 3b.
  - Triple-whammy detector — NSAID + ACE-I/ARB + diuretic in CKD.
  - Renal-dose adjustments (from `renal_dosing.json`) — eGFR thresholds per drug.
  - Beers criteria (from `beers_criteria.json`) — age ≥65.
- **Severity matrix:** (severity × evidence_level) → verdict. `contraindicated × established` → BLOCK. `major × probable` → WARN_OVERRIDE_REQUIRED. `moderate × probable` → WARN. `minor × theoretical` → INFO.
- **Output:** `{verdict, flags: [{severity, rule_id, reason, citation}], profile_fields_consulted: [...]}`.

### 5.3 Phase 3 tools (LLM — Synthesis)

#### `SynthesiseSafetyResponse`
- **Purpose:** Take a verdict (from Phase 2) + profile + medication, generate patient-specific narrative + alternatives + monitoring plan via Gemini structured output.
- **Only called on BLOCK or WARN verdicts.** On CLEAN, the agent drafts the prescription directly.
- **Returns:** `{narrative, alternatives: [...], patient_explanation}`.

#### `AnalyseOverrideReason`
- **Purpose:** When a clinician overrides a safety alert, classify and validate the free-text reason.
- **Classifications:** `specialist_recommendation`, `acute_need`, `risk_accepted`, `patient_preference`, `clinical_judgment`, `unknown`.
- **Returns:** `{override_classification, valid, residual_risk_acknowledged, structured_audit_justification, suggested_monitoring: [...]}`.
- **Drives the audit trail.** The classification feeds into the AuditEvent description.

### 5.4 Referral tools

#### `AssembleSpecialtyPacket`
- **Purpose:** For a given target specialty (e.g., nephrology), assemble the relevant FHIR fields and identify what's missing.
- **Returns:** `{included: [...], missing: [...], completeness_score}`.

#### `RankSpecialistDestinations`
- **Purpose:** Rank available destinations for a specialty from `specialist_directory.json`.
- **Ranking factors:** specialty fit, wait days, distance (if geocoded).

#### `ExtractConsultRecommendations`
- **Purpose:** Given a DocumentReference ID (or auto-discovered consult note), parse the clinical text into structured recommendations via Gemini.
- **Auto-discovery:** If no ID is passed, queries FHIR for DocumentReferences with LOINC `11488-4` (Consult note) and picks the latest. This was added after we found the agent had no way to know the ID upfront.
- **Strict filter:** If no consult notes exist, returns a specific error — does NOT fall back to non-consult documents (this silently produced wrong results earlier).

#### `DetectPlanConflicts`
- **Purpose:** Compare extracted recommendations against the current care plan (from the cached profile) to detect contradictions.

### 5.5 FHIR write tools

#### `DraftMedicationRequest`
- **Purpose:** Create a FHIR MedicationRequest. Called after CLEAN verdict or logged override.

#### `DraftServiceRequest`
- **Purpose:** Create a FHIR ServiceRequest for a specialist referral.

#### `DraftFollowupTask`
- **Purpose:** Create a FHIR Task (e.g., "Repeat eGFR in 2 weeks").

#### `LogOverride`
- **Purpose:** Create a permanent FHIR AuditEvent capturing an override. **Always called BEFORE `DraftMedicationRequest` in an override flow.**
- **Bug fix history:** Initially failed silently because AuditEvent required `source.observer` per FHIR R4 — `resource_builders.py` now always includes it.

---

## 6. The SignalLoop Agent — Orchestration Logic

### 6.1 Configuration in Prompt Opinion

| Field | Value |
|---|---|
| Scope | Patient |
| Model | Gemini 3.1 Flash Lite Preview (via Prompt Opinion's model config) — $0.25/M input, $1.50/M output |
| System Prompt | See `agent-config/system-prompt.md` (mode-switching template) |
| Response Format | **Leave blank** (schemas deprecated for chat) |
| Tools | MedSafe MCP server (all 15 tools) |
| Content | Collection `signalloop-clinical-references` (6 markdown files) |
| A2A | Skill `renal_safety_consult` (patient-scope) |
| FHIR Extension | Enabled with all required scopes |

### 6.2 Six operational modes

The system prompt routes every clinician intent to one of six modes:

| Mode | Trigger | Tool sequence |
|---|---|---|
| **A — Patient Context** | "What should I know about this patient?" | BuildPatientRiskProfile → GetRenalTrend |
| **B — Medication Safety** | "Can I prescribe X?" | NormalizeMedication → CheckMedicationSafety → [SynthesiseSafetyResponse if flagged] |
| **C — Override** | "Override, reason: X" | AnalyseOverrideReason → LogOverride → DraftMedicationRequest → DraftFollowupTask |
| **D — Clean Prescribe** | After approved alternative or CLEAN verdict | CheckMedicationSafety → DraftMedicationRequest → DraftFollowupTask |
| **E — Referral** | "Refer to X" | AssembleSpecialtyPacket → RankSpecialistDestinations → DraftServiceRequest |
| **F — Consult Return** | "Did nephrology respond?" | ExtractConsultRecommendations → DetectPlanConflicts → DraftMedicationRequest/DraftFollowupTask per recommendation |

### 6.3 Governance rules

These are hard constraints the agent must never violate:
- Never generate safety verdicts from its own knowledge. Always defer to `CheckMedicationSafety`.
- Never draft a MedicationRequest without a CLEAN verdict OR a logged override.
- Never send a referral without clinician approval of the packet.
- Always call `LogOverride` BEFORE `DraftMedicationRequest` in an override flow.
- Always surface chart-patient conflicts visibly.
- Always cite the rule/guideline behind a flag.

### 6.4 Cache protection

- `BuildPatientRiskProfile` is cached server-side (60-min TTL per patient).
- `RefreshPatientRiskProfile` is **not exposed as an MCP tool** — the LLM would call it on any optional boolean named with a verb-y name. Removing it entirely is the fix.
- The system prompt tells the agent: "If you need the profile, just call BuildPatientRiskProfile — it returns cached data if available."

---

## 7. Data Flow — End-to-End Example

**Scenario:** Clinician asks "Can I prescribe naproxen for Margaret's knee pain?"

```
Clinician types in Prompt Opinion chat
  │
  ▼
SignalLoop Agent receives prompt
  │
  │ 1. Recognizes Mode B (medication safety)
  │
  ├─→ MCP call: NormalizeMedication("naproxen 500mg BD")
  │      │
  │      ├─→ Rules data lookup (drug_classes.json)
  │      │
  │      └─← {canonical: "naproxen", code: "...", classes: ["NSAID"]}
  │
  ├─→ MCP call: BuildPatientRiskProfile
  │      │ (cache hit — returns in ~50ms, no Gemini call)
  │      │
  │      └─← LLMPatientRiskProfile {
  │           active_conditions: [CKD_3b, T2DM, HTN, OA],
  │           active_medications: [lisinopril (ACE_INHIBITOR),
  │                                furosemide (LOOP_DIURETIC),
  │                                paracetamol, ...],
  │           labs: [eGFR=42, trending_down],
  │           ...
  │         }
  │
  ├─→ MCP call: CheckMedicationSafety(profile, naproxen_code)
  │      │
  │      ├─→ Rules engine evaluation (pure Python):
  │      │     • triple-whammy-aki:   fires (NSAID + ACE-I + diuretic)
  │      │     • renal-nsaid-ckd:     fires (CKD 3b + NSAID)
  │      │     • beers-nsaid-chronic: fires (age ≥65)
  │      │
  │      └─← SafetyVerdict {
  │           verdict: "block",
  │           flags: [3 flags with rule_id + citation each],
  │           profile_fields_consulted: [active_medications,
  │                                      renal_function,
  │                                      chronic_conditions, age]
  │         }
  │
  ├─→ MCP call: SynthesiseSafetyResponse(verdict, profile, naproxen)
  │      │
  │      ├─→ Gemini 3.1 Flash Lite Preview with Pydantic schema
  │      │
  │      └─← {
  │           narrative: "...triple whammy risk...",
  │           alternatives: [paracetamol 1g QDS, topical diclofenac, physio],
  │           patient_explanation: "Naproxen would strain your kidneys..."
  │         }
  │
  └─→ Agent renders response (markdown)
         │
         ▼
    Clinician sees in chat:
    "**BLOCK: Naproxen contraindicated for Margaret.**
     Triple-whammy AKI risk — NSAID + lisinopril + furosemide...
     **Flags:** triple-whammy-aki, renal-nsaid-ckd-3b, beers-nsaid-chronic
     **Alternatives:** [...]
     **For the patient:** [...]"
```

**Zero FHIR writes this turn** — BLOCK means no prescription is drafted. Clinician makes the next move (accept alternative / override / abandon).

---

## 8. FHIR Integration

### 8.1 SHARP headers

Every MCP tool call from Prompt Opinion arrives with three HTTP headers:

| Header | Contents |
|---|---|
| `x-fhir-server-url` | Workspace-scoped HAPI FHIR base URL |
| `x-fhir-access-token` | JWT bearer token with SMART scopes |
| `x-patient-id` | Active patient ID (fallback — primary source is the JWT `patient` claim) |

Our `fhir/context.py` extracts these, decodes the JWT, and constructs a `FhirContext` object. The `FhirClient` in `fhir/client.py` uses this for every GET/POST.

### 8.2 FHIR extension declaration

`server.py` monkey-patches `mcp._mcp_server.get_capabilities()` to inject the `ai.promptopinion/fhir-context` extension into the MCP server's capabilities announcement. The platform reads this on registration and shows the SMART scopes to the user for approval.

Required scopes declared: Patient, Condition, MedicationRequest, Observation, AllergyIntolerance (reads). Optional: DocumentReference, Encounter (reads). Writes: ServiceRequest, Task, Communication, AuditEvent, MedicationRequest.

### 8.3 FHIR bundle uploads (workspace data setup)

Patient data is loaded into the workspace FHIR server via transaction bundles — one per patient, plus one for the returned consult note.

**Cross-bundle reference gotcha (resolved):** `urn:uuid:X` references only resolve *within* one bundle. The consult-note bundle references Margaret's Patient resource, which was created in a prior bundle. We resolved this by hardcoding Margaret's server-assigned UUID (`7540845c-2212-4170-bc1c-a520014ea96f`) in `consult-return-nephrology-post.json`. Production solution (documented as follow-up): use conditional references via a business identifier.

### 8.4 FHIR writes

Every write tool follows the same pattern:
```
resource = build_X(patient_id, ...)      # pure function
created = await fhir.create("X", resource)
return json.dumps({status: "created", id: created["id"], ...})
```

Resources returned include their server-assigned ID. The agent surfaces these IDs to the clinician for audit visibility.

---

## 9. Demo Patients & Scenarios

### 9.1 Margaret Henderson (72F) — Hero demo

- **Conditions:** CKD 3b, T2DM (10y), HTN (15y), OA
- **Meds:** lisinopril 10mg OD, furosemide 40mg OD, simvastatin 20mg nocte
- **Reconciliation flag:** Metformin listed but patient reports stopped 3mo ago (GI intolerance)
- **eGFR trajectory:** 58 (Nov 2025) → 52 (Jan 2026) → 42 (Apr 2026). **−3.3 pts/month — rapid decline.**
- **ACR:** 12.3 mg/mmol (moderately increased)

**Hero scenario:** "Naproxen for knee pain?"
- Verdict: **BLOCK**
- Flags: triple-whammy-aki, renal-nsaid-ckd-3b, beers-nsaid-chronic
- Alternatives: paracetamol, topical diclofenac, physio

**Loop-closure scenario:** "Did nephrology respond?"
- Nephrology consult returns with 6 recommendations (stop lisinopril → irbesartan, reduce furosemide, SGLT2i consideration, 3-mo review, lifelong NSAID avoidance, 6-week recheck)
- Agent extracts, detects conflicts, drafts MedicationRequests and Tasks for each

### 9.2 James Okonkwo (42M) — Safe control

- **Conditions:** none notable
- **Meds:** none chronic
- **Renal:** normal, stable
- **Scenario:** "Naproxen 500mg BD for shoulder strain?"
  - Verdict: **CLEAN**
  - Result: MedicationRequest drafted immediately, no flags

### 9.3 Doris Williams (68F) — Override scenario

- **Conditions:** RA, on methotrexate
- **Renal:** borderline (eGFR ~65)
- **Scenario:** "Naproxen for OA flare?"
  - Verdict: **WARN_OVERRIDE_REQUIRED**
  - Flags: nsaid-methotrexate-toxicity, renal-nsaid-egfr-90, beers-nsaid-chronic
- **Override flow:** "Override — rheumatology aware, short course, patient counselled."
  - AnalyseOverrideReason → `specialist_recommendation`, valid, residual risk acknowledged
  - LogOverride → AuditEvent created
  - DraftMedicationRequest → naproxen 500mg BD × 7 days
  - DraftFollowupTask → FBC/LFTs/eGFR in 1 week

---

## 10. Observed Test Results

All tests below have been run end-to-end in production (against live Prompt Opinion workspace + live MedSafe MCP via ngrok).

### 10.1 Core clinical scenarios

| Test | Verdict | FHIR writes | Pass |
|---|---|---|---|
| Margaret + naproxen | `block` | none | ✅ |
| James + naproxen | `clean` | MedicationRequest | ✅ |
| Doris + naproxen | `warn_override_required` | none | ✅ |
| Doris override flow | — | AuditEvent + MedicationRequest + Task | ✅ |
| Margaret consult return | — | Multiple MedicationRequests + Tasks | ✅ |

### 10.2 Infrastructure / integration

| Check | Result |
|---|---|
| Profile cache (2nd call within 60min) | Returns cached data, no Gemini call, ~50ms latency |
| `_enrich_profile_with_canonical_classes` | Verified in logs: "Enriched lisinopril: ['ACE inhibitor'] → ['ACE_INHIBITOR']" |
| Triple-whammy rule fires | Verified: 3 flags on Margaret with correct rule IDs and citations |
| AuditEvent persists | Verified after adding `source.observer` field |
| Consult auto-discovery (no ID) | Verified via LOINC 11488-4 lookup |
| Cross-bundle reference resolution | Verified after hardcoding Margaret's server UUID |
| Billing quotas (500 RPD, 60 RPM, 200K TPM on Tier 1) | Not hit in testing |
| Cost per full demo run | ~$0.10 |

### 10.3 Known LLM variance

- **Doris Phase 1 profile:** `gi_bleed_history` flag appeared in one run but not a subsequent run. Rules engine handles the presence/absence gracefully, but the flag count varies.
- **Hallucination risk in reconciliation:** the model occasionally surfaces a "conflict" between eGFR value and CKD stage code that may or may not be real — need to verify by reading the FHIR Condition resources before accepting.

### 10.4 Currently known output issue (rendering layer)

The agent currently returns **raw JSON** in the chat UI, not the intended markdown. Root cause identified: `response-schema-simplified.json` is pasted in Prompt Opinion's "Response Format" tab, forcing Gemini's `response_schema` parameter to constrain output to the JSON schema. **Fix:** clear the Response Format tab; keep system prompt with markdown template; schema files remain as A2A artifacts.

---

## 11. Outputs & Formats

### 11.1 MCP tool outputs (machine-to-agent)

All 15 tools return JSON strings. Example from `CheckMedicationSafety`:
```json
{
  "verdict": "block",
  "proposed_medication": "naproxen",
  "flags": [
    {
      "severity": "contraindicated",
      "rule_id": "triple-whammy-aki",
      "reason": "NSAID with ACE-I (lisinopril) and loop diuretic (furosemide) in CKD 3b",
      "citation": "NICE NG203 §1.4.3, KDIGO 2021"
    },
    ...
  ],
  "profile_fields_consulted": ["active_medications", "renal_function", "chronic_conditions", "age"]
}
```

This is correct — it's the machine interchange format between MCP and agent.

### 11.2 Agent chat output (agent-to-clinician)

**Intended:** markdown following the template in `system-prompt.md`.

Example after fix:
```markdown
**BLOCK: Naproxen contraindicated for Margaret.**

Triple-whammy AKI risk — NSAID + lisinopril (ACE-I) + furosemide (loop diuretic).
Her eGFR has declined 58 → 42 over 5 months (~3.3 pts/month), CKD 3b.

**Flags:** triple-whammy-aki, renal-nsaid-ckd-3b, beers-nsaid-chronic
— NICE NG203 §1.4.3, Beers 2023

**Alternatives:**
- Paracetamol 1g QDS — safest systemic option; already on chart
- Topical diclofenac gel — minimal systemic absorption, fine in CKD
- Physiotherapy referral — first-line non-pharmacological

**⚠️ Reconcile:** Metformin 500mg BD active in chart but patient reports
stopping 3 months ago.

**For the patient:** Naproxen would put too much strain on your kidneys.
Paracetamol or a rub-on gel will be safer — I'll talk you through them.

**Next steps:**
1. Do not prescribe naproxen.
2. Confirm metformin status, update MedicationRequest.
3. Consider nephrology referral — rapid eGFR decline.

---
*Writes: none this turn* · *Verdict: block*
```

**Currently (bug):** returns the JSON schema shape instead. Fix is to clear Response Format tab.

### 11.3 A2A skill output

The `renal_safety_consult` A2A skill, when called by another agent, can use the structured `response-schema.json` (full version). This gives machine-readable output for agent-to-agent invocations while chat output stays markdown. **Separation of concerns** — one format per audience.

---

## 12. Known Issues & Limitations

1. **Rendering layer bug** (in-progress): JSON schema enforcement overrides system prompt markdown instructions. Fix is a UI change in Prompt Opinion — clear the Response Format tab.
2. **Phase 1 LLM variance:** clinical_context_flags vary run-to-run. Acceptable for hackathon; production fix would derive flags from structured fields instead of LLM free text.
3. **Hardcoded Margaret UUID** in consult bundle for cross-bundle reference resolution. Production fix: conditional references via business identifier.
4. **Reconciliation hallucination risk:** Phase 1 may invent conflicts that aren't in the FHIR record. Unverified whether Doris's eGFR/CKD-stage conflict is real or fabricated. **Action required:** read Doris's Condition resources before demo.
5. **ngrok as deployment:** MedSafe runs locally, exposed via ngrok reserved domain. Production would use a real cloud deployment.
6. **No retry / idempotency on FHIR writes:** if a write request is retried, you get duplicate resources. Production would use conditional creates with business identifiers.
7. **No versioning on the MCP server:** the platform registers the URL; any change is a live update. Not an issue for hackathon.

---

## 13. What's Left (Submission Track)

Not yet started per user direction:

1. **Demo script** — word-for-word clinician narration for the video.
2. **Demo rehearsals** — 2–3 cold runs of the full scenario sequence.
3. **Video recording** — using the demo script, one take per scenario.
4. **Marketplace Studio publishing** — MedSafe MCP + SignalLoop Agent as two listings.
5. **Devpost writeup** — architecture diagram, demo video, text submission.
6. **Production-readiness notes** — for each "known issue" above, document the production fix so judges know we're aware of the gap.

**Pre-demo critical path:**
1. Clear Response Format tab in Prompt Opinion → verify markdown output.
2. Verify Doris's Condition resources to confirm the reconciliation conflict is real.
3. Re-run all 5 clinical scenarios in fresh chats to confirm demo flow.
4. Then begin submission track.
