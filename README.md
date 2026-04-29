# SignalLoop — Healthcare AI Safety Platform

Three MCP servers that bring deterministic clinical safety rules to AI prescribing workflows on the [Prompt Opinion](https://promptopinion.com) platform.

---

## What's in this repo

| Product | Directory | What it does |
|---|---|---|
| **MedSafe MCP** | `signalloop-medsafe-mcp/` | Prescribing safety MCP. Three-phase architecture: LLM builds patient risk profile from FHIR → deterministic rules engine checks safety → LLM synthesises patient-specific response. |
| **Concord MCP** | `concord-mcp/` | Multi-specialist conflict resolution MCP. Orchestrates cardiology, nephrology, pharmacy, and primary care agents to resolve conflicting treatment plans deterministically. |
| **Shared Core** | `medsafe_core/` | Python library shared by both MCPs: FHIR client, Gemini LLM client, rules engine, Pydantic data models. |

Both MCP servers connect to a HAPI FHIR R4 server via SMART-on-FHIR headers (`x-fhir-server-url`, `x-fhir-access-token`, `x-patient-id`) and expose tools to BYO agents on the Prompt Opinion platform.

---

## Architecture — MedSafe Three-Phase Safety Check

```
FHIR Record
    │
    ▼
Phase 1 (Gemini LLM)
    Build PatientRiskProfile
    (comorbidities, renal function, current meds, allergies)
    │
    ▼
Phase 2 (Pure Python rules — NO LLM)
    Deterministic safety check:
    • Drug–drug interactions (DDI pairs)
    • Renal dose adjustments (eGFR-banded)
    • Beers Criteria 2023 (older adults)
    • STOPP/START v2
    → SafetyVerdict: BLOCK / WARN / CAUTION / CLEAN
    │
    ▼
Phase 3 (Gemini LLM)
    Synthesise patient-specific response
    with clinical rationale and alternatives
```

The LLM **never** makes safety verdicts. The rules engine does. LLM contextualises them.

---

## Repository structure

```
Med/
├── signalloop-medsafe-mcp/     # MedSafe MCP Server
│   ├── main.py                 # FastAPI + uvicorn entry point
│   ├── server.py               # MCP instance and tool registration
│   ├── tools/                  # MCP tool implementations (thin wrappers)
│   ├── tests/                  # 9 pytest test files
│   └── requirements.txt
│
├── concord-mcp/                # Concord MCP Server
│   ├── main.py
│   ├── server.py
│   ├── rules/                  # Conflict matrix, action codes, plan validator
│   ├── llm/                    # Gemini client + episode brief prompts
│   ├── tools/                  # run_consult, arbitration, episode, writes
│   ├── agent-config/           # System prompts for each specialist agent
│   ├── tests/                  # 6 pytest test files
│   └── requirements.txt
│
├── medsafe_core/               # Shared Python library
│   ├── fhir/                   # FHIR HTTP client + SHARP context extraction
│   ├── rules/                  # Deterministic rules engine + JSON data files
│   │   └── data/               # beers_2023, ddi_pairs, renal_dosing, stopp_start_v2, …
│   ├── llm/                    # Gemini client + structured output prompts
│   └── pyproject.toml
│
├── fhir-bundles/               # Synthetic patient FHIR R4 bundles for demo/testing
│   ├── patient-margaret-post.json   # Hero: CKD 3b, T2DM, HTN — BLOCK scenario
│   ├── patient-doris-post.json      # RA on methotrexate — WARN scenario
│   ├── patient-james-post.json      # Healthy adult — CLEAN control
│   ├── concord-patient-*.json       # Multi-specialist conflict scenarios
│   └── README.md
│
├── agent-config/               # SignalLoop BYO agent config for Prompt Opinion
│   ├── system-prompt.md        # Agent system prompt
│   ├── content-collection/     # Clinical reference content (NICE, MHRA, etc.)
│   └── response-schema.json    # Structured response schema
│
├── LICENSE                     # MIT
└── LICENSE-AND-ATTRIBUTION.md  # Clinical content provenance and fair-use analysis
```

---

## Prerequisites

- Python 3.11+
- A Gemini API key from [Google AI Studio](https://aistudio.google.com)
- A running HAPI FHIR R4 server (for live patient data; tests run without one)

---

## Quick start

### 1. Install shared core

```bash
pip install -e ./medsafe_core
```

### 2. MedSafe MCP

```bash
cd signalloop-medsafe-mcp
cp .env.example .env
# Edit .env — set GEMINI_API_KEY
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

MCP endpoint: `http://localhost:8000/mcp`

### 3. Concord MCP

```bash
cd concord-mcp
cp .env.example .env
# Edit .env — set GEMINI_API_KEY
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

MCP endpoint: `http://localhost:8001/mcp`

---

## Running tests

```bash
# MedSafe rules engine (no network, no LLM required)
pytest signalloop-medsafe-mcp/tests/ -v

# Concord conflict resolution
pytest concord-mcp/tests/ -v
```

The rules engine tests are fully offline — they test the deterministic safety logic against known patient profiles.

---

## Demo patients

All patients are **fully synthetic**. See [`fhir-bundles/README.md`](fhir-bundles/README.md) for upload instructions.

| Patient | Scenario | Expected verdict |
|---|---|---|
| Margaret Henderson, 72F | CKD 3b + ACE-I + diuretic. Prescribe ibuprofen. | **BLOCK** — triple whammy AKI risk |
| James Okonkwo, 42M | Healthy adult. Prescribe ibuprofen. | **CLEAN** |
| Doris Williams, 68F | RA on methotrexate. Prescribe naproxen. | **WARN** — DDI + Beers flag |
| Patricia Quinn | Multi-specialist conflict (Concord) | Arbitrated consensus plan |
| Frances Doyle | Data-blocking scenario (Concord) | Conflict detected, escalation path |

---

## Deployment

Both MCPs are containerised for [Fly.io](https://fly.io) free tier:

```bash
# Concord MCP
fly deploy --config fly-concord.toml

# MedSafe MCP (add fly.toml to signalloop-medsafe-mcp/ for production)
```

Set `GEMINI_API_KEY` as a Fly.io secret: `fly secrets set GEMINI_API_KEY=...`

---

## Clinical attribution

This project encodes rules derived from NICE guidelines, MHRA guidance, AGS Beers Criteria, and STOPP/START v2. **Not for clinical use without proper licensing of the underlying content.**

Full provenance, fair-use analysis, and production licensing guidance: [`LICENSE-AND-ATTRIBUTION.md`](LICENSE-AND-ATTRIBUTION.md)

---

## License

MIT — see [`LICENSE`](LICENSE). Clinical content restrictions apply — see above.
