# SignalLoop — Project Instructions

## What This Is
Hackathon project for Prompt Opinion platform (deadline: May 11, 2026). Two submissions from one codebase:
- **Submission A (Superpower/MCP):** MedSafe MCP Server — medication safety
- **Submission B (Agent/A2A):** SignalLoop Renal Safety Agent — BYO in-platform agent

## Architecture Principles (Non-Negotiable)

### Three-Phase MedSafe Architecture
- **Phase 1 (LLM):** Build patient risk profile from FHIR record
- **Phase 2 (Rules):** Deterministic safety check — NO LLM, pure Python rules
- **Phase 3 (LLM):** Synthesise patient-specific response with alternatives
- The LLM NEVER makes safety verdicts. Rules make verdicts. LLM contextualises them.

### Separation of Concerns
- `fhir/` — SHARP context extraction + FHIR HTTP client (read/write)
- `rules/` — Deterministic rules engine + data files. No LLM, no I/O beyond loading JSON
- `llm/` — Gemini client + prompts (first-class artifacts in their own modules)
- `tools/` — MCP tool implementations (thin orchestration layer)
- Each module has a single responsibility. Tools don't contain business logic.

### Data Contracts
- Pydantic models define all interfaces between phases
- `PatientRiskProfile` is the shared contract Phase 1 → Phase 2 → Phase 3
- `SafetyVerdict` is Phase 2 output consumed by Phase 3
- All LLM outputs use structured generation (Pydantic → JSON schema → Gemini)

### Rules Engine Design
- Pure functions: input (medication + profile) → output (verdict + flags)
- Testable without network, LLM, or FHIR — just Python + JSON data files
- Every flag traces to a rule_id, citation, and profile_fields_consulted
- Severity matrix maps (severity × evidence_level) → verdict deterministically

### FHIR Context
- SHARP headers: `x-fhir-server-url`, `x-fhir-access-token`, `x-patient-id`
- Patient ID resolved from JWT claims first, then header fallback
- Extension declared as `ai.promptopinion/fhir-context` with SMART scopes
- All FHIR writes require clinician approval (enforced at agent level)

## Tech Stack
- Python 3.14, FastAPI, FastMCP SDK (`mcp>=1.9.0`)
- Gemini via `google-genai` SDK, structured output with Pydantic models
- Streamable HTTP transport, deployed via ngrok reserved domain
- FHIR R4, dm+d coding (UK context)

## Project Structure
```
signalloop-medsafe-mcp/     ← MCP server (Submission A)
├── main.py                  ← FastAPI entry point
├── server.py                ← MCP instance + tool registration
├── config.py                ← Environment config
├── fhir/                    ← FHIR client + SHARP context
├── rules/                   ← Deterministic rules engine
│   └── data/                ← JSON rule files (interaction, renal, Beers)
├── llm/                     ← Gemini client + structured output
│   └── prompts/             ← Prompt modules (one per capability)
├── tools/                   ← MCP tool implementations
└── tests/                   ← Unit tests (rules engine focus)

fhir-bundles/                ← Patient data for upload
medsafe-rules/               ← Source rule data (copied into project)
```

## Demo Patients
- **Margaret Henderson** (72F) — hero demo. CKD 3b, T2DM, HTN, OA. On ACE-I + diuretic. eGFR 42 (declining). Ibuprofen → BLOCK.
- **James Okonkwo** (42M) — safe control. Healthy. Ibuprofen → CLEAN.
- **Doris Williams** (68F) — override scenario. RA on methotrexate. Naproxen → WARN.

## Key Reference Docs
- `PLATFORM-NOTES.md` — platform research findings (MCP patterns, SHARP headers, BYO agent config)
- `SignalLoop-Final-Operational-Plan.md` — frozen execution plan (authoritative)
- `SignalLoop-Master-Spec.md` — blue sky vision (north star, not scope)

## Rules for Codex Sessions
- Always read the Final Operational Plan before starting a new phase
- Reference PLATFORM-NOTES.md for platform-specific patterns
- The rules engine (`rules/engine.py`) must never call an LLM
- Test the rules engine with `pytest tests/test_rules_engine.py` after any change
- When writing new tools, follow the patterns in existing tool files
- FHIR resource builders are pure functions — no I/O, no side effects
