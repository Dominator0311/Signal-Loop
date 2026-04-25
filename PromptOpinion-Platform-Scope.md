# Prompt Opinion — Platform Scope & Capability Analysis

> A definitive, first-principles reference for what Prompt Opinion is, how its pieces fit together, and — critically — what it is capable of in a blue-sky scenario where technical feasibility is the only constraint. Written from the perspective of someone who has built on top of it and now understands its shape.

---

## 1. What Prompt Opinion Is

Prompt Opinion is a **clinical AI platform** that sits between:
- A **clinician** using a chat UI at the point of care, and
- A **workspace** of clinical data (FHIR server, documents, knowledge bases) and external AI capabilities (LLMs, MCP tools, other agents).

Its thesis is: AI in healthcare needs (a) access to real patient data, (b) access to domain tools, (c) a way to compose those safely, and (d) a human-in-the-loop UI where clinicians drive. Most AI products solve one of these in isolation. Prompt Opinion is an **integration layer** — it doesn't ship the LLM, it doesn't ship the FHIR server, it doesn't ship the tools. It ships the connective tissue that makes them usable together.

### What this means in practice

Prompt Opinion is **not** a monolithic chatbot. It is a configurable agent runtime with:
- **Multiple agent scopes** (Patient, Group, Workspace)
- **Pluggable tool surfaces** (MCP servers — any MCP, not Prompt Opinion's alone)
- **Pluggable knowledge** (content collections grounded per-agent)
- **A permissions model** (SMART scopes, FHIR context extension)
- **A marketplace** for distributing agents and MCP servers
- **An A2A protocol** so agents can call each other
- **A FHIR backbone** so every agent action is data-native and auditable

The platform is bringing concepts from the open AI agent ecosystem (MCP, A2A) into a domain-specific (healthcare) context with domain-specific primitives (FHIR, SMART).

---

## 2. Architecture Overview

### The three surface areas

A builder on Prompt Opinion works with three primary things:

| Surface | What it is | How you build on it |
|---|---|---|
| **MCP Servers** | Callable capability endpoints (tools). Reusable across many agents. | External server speaking the MCP protocol over streamable HTTP. Register by URL. |
| **BYO Agents** | Agent configurations inside the platform. One chat interface, one system prompt, one set of tools. | Configure in UI: scope, system prompt, tools, content, response format, A2A. |
| **A2A Agents** | Agents that expose "skills" callable by other agents. | Flip the A2A switch on a BYO agent and define skill names + FHIR context requirements. |

### Runtime composition

```
┌──────────────────────────────────────────────────────────┐
│  CLINICIAN                                               │
│  │  (selects patient in Launchpad,                       │
│  │   opens an agent, types a question)                   │
└──┼───────────────────────────────────────────────────────┘
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│  BYO AGENT — Patient-scope                               │
│  ┌──────────────────────────────────────────────┐        │
│  │ System Prompt (orchestration brain)          │        │
│  │ Grounded Collection (domain knowledge)       │        │
│  │ Response Format (optional JSON schema)       │        │
│  └──────────────────────────────────────────────┘        │
│                                                          │
│  Composes the LLM call with:                             │
│  - Patient context (FHIR data summary)                   │
│  - System prompt                                         │
│  - Tool definitions (from attached MCP servers)          │
│  - Message history                                       │
│  - Collection search results                             │
│                                                          │
│  Routes:                                                 │
│  - Tool calls → MCP servers (over HTTPS)                 │
│  - Skill calls → other A2A agents                        │
│  - Reads → Workspace FHIR server                         │
│  - Grounding → Content collection / PubMed               │
└──────────────────────────────────────────────────────────┘
   │              │              │              │
   ▼              ▼              ▼              ▼
 MCP         A2A Agent      FHIR Server     Collection
 Server      (another      (HAPI,           (uploaded
 (any        BYO agent)    workspace-       markdown +
 URL)                      scoped)          PDF docs)
```

### What runs where

- **Prompt Opinion-hosted:** the agent runtime, the FHIR server, the Launchpad UI, the Marketplace, A2A routing.
- **External:** your MCP servers (you deploy them), the LLM provider (Gemini, Claude, etc. — routed through platform's model config).
- **Authentication:** platform handles SMART OAuth for FHIR. Your MCP server receives tokens via SHARP headers — doesn't need its own FHIR auth.

---

## 3. MCP Server Integration

### 3.1 What an MCP server is in this context

A plain HTTP service implementing the Model Context Protocol. In our build we used Python FastMCP (`mcp>=1.9.0`) with FastAPI + streamable HTTP transport. The platform sends:
- An MCP **initialize** request when registering the server (capabilities handshake).
- An MCP **list_tools** request to discover available tools.
- An MCP **call_tool** request on every tool invocation.

### 3.2 The FHIR context extension (SHARP-on-MCP)

Prompt Opinion defines a custom MCP capability extension:
```
extensions: {
  "ai.promptopinion/fhir-context": {
    scopes: [
      { name: "patient/Patient.rs", required: true },
      { name: "patient/Condition.rs", required: true },
      ...
    ]
  }
}
```

Declaring this extension does three things:
1. Tells the platform your tools need FHIR context.
2. Causes the platform to **inject three HTTP headers** on every tool call:
   - `x-fhir-server-url` — the workspace FHIR base URL
   - `x-fhir-access-token` — SMART-issued JWT with the declared scopes
   - `x-patient-id` — the active patient (patient-scope only)
3. Shows the user the required scopes during MCP registration; they approve or reject.

This is a genuinely novel idea — it unifies MCP (generic tool protocol) with SMART-on-FHIR (healthcare-specific auth). Your tools can focus on business logic; auth and context injection are handled by the platform.

### 3.3 Tool registration shape

```python
mcp.tool(name="PascalCaseName", description="...")(handler_function)
```

Names must be PascalCase. Descriptions are the LLM's guide for when to call each tool — they should be **operationally prescriptive**, not just descriptive ("Call this BEFORE X" not "Returns X").

### 3.4 What a tool returns

A JSON-encoded string. This becomes the tool result visible to the LLM inside the agent. The structure of this JSON is your contract with your own agent prompt — you design how the agent reads the output.

### 3.5 Observed MCP limits

- **Streamable HTTP** transport only. No SSE, no stdio.
- **Stateless** — tools should not rely on session memory. Any state is in the FHIR server or in your own backing store.
- **No tool versioning** visible to the platform. Updates are live.
- **CORS with `allow_origins=["*"]`** is required. The platform's MCP registration endpoint is a different origin than where your tool runs.

---

## 4. BYO Agent Configuration

### 4.1 Required fields

| Field | Meaning | Constraints |
|---|---|---|
| **Model** | Which LLM the agent uses | Selected from Model Configuration page; admin-configured provider keys |
| **Scope** | Patient / Group / Workspace | Determines where the agent appears in Launchpad |
| **System Prompt** | Orchestration brain | Platform variables injected at runtime: `{{ PatientContextFragment }}`, `{{ PatientDataFragment }}`, `{{ McpAppsFragment }}` |
| **Response Format** | JSON schema (optional) | Provider-specific restrictions; **enforces structured output** |
| **Tools** | Attached MCP servers | Multiple allowed |
| **Content** | Single grounded collection | Max one per agent |
| **A2A** | Skill exposure | Optional; enable to expose the agent to other agents |
| **FHIR Context** | Whether the agent can access patient FHIR | Required for patient scope |

### 4.2 The platform variable fragments

The default system prompt includes these template variables. You should NOT remove them — they are how the platform feeds context:

- **`{{ PatientContextFragment }}`** — narrative summary of the active patient (name, DOB, major conditions).
- **`{{ PatientDataFragment }}`** — structured FHIR data summary.
- **`{{ McpAppsFragment }}`** — dynamic list of available MCP tools the agent can call.

Always "Load Default" before customizing to see the current template — it may evolve.

### 4.3 Response Format — the subtle trap

If you paste a JSON schema in this tab:
- The LLM provider is called with `response_schema` (Gemini) or `response_format: json_object` (OpenAI).
- Output is **constrained at decode time** to match the schema.
- System prompt instructions to "respond in markdown" are silently ignored.

**Intended use:** machine-readable output for A2A consumption, downstream tool wiring, or programmatic consumption.
**Wrong use:** relying on it for UI rendering — Prompt Opinion's chat UI does NOT have a structured-schema render layer that transforms JSON into UI cards (at least not visibly to the builder). Raw JSON shows up in chat.

**Rule of thumb:** leave Response Format blank for chat-facing agents; use it only for A2A skills or when downstream consumers need structured output.

### 4.4 Grounding to a Collection

You upload up to N markdown/PDF files into a collection, then attach exactly one collection per agent. The platform runs retrieval against the collection and injects matching snippets into the LLM call. This is your "knowledge base" — clinical guidelines, protocols, reference material.

Observed limits:
- **One collection per agent.** Can't mix sources.
- **Under 25 pages** is the safe size (we used ~11 pages for SignalLoop).
- **PubMed + public collections** are selectable as alternatives to private collections.

### 4.5 Guardrails

Pre-prompt guardrails only. No post-response moderation yet. This means:
- You can define rules that are injected before the LLM runs ("never recommend X without Y").
- You cannot yet define rules that inspect the LLM's output and block/rewrite it.

Our governance rules in SignalLoop are implemented as pre-prompt guardrails in the system prompt. For production clinical safety this is a known gap — post-response validators (e.g., "did the agent actually cite a guideline?") would add a second defense layer.

---

## 5. Agent-to-Agent (A2A) Protocol

### 5.1 What A2A enables

Any BYO agent can be exposed as a set of callable "skills." Another agent — or a user's scripted workflow — can invoke those skills with structured arguments and receive structured output.

This turns an agent into a **reusable capability** discoverable across the platform, much like an MCP server — but at a higher level of abstraction (an agent has a system prompt, tool orchestration, and its own grounding; an MCP server has only tools).

### 5.2 Configuration

Per-agent A2A config includes:
- **Skill names** (e.g., `renal_safety_consult`)
- **FHIR context requirement** — whether the calling context must include a patient
- **Scope** — patient / group / workspace matches the parent agent's scope

### 5.3 Observed patterns

- A2A is ideal for **specialty agents** — a renal agent, a cardiology agent, an oncology agent, each exposed via skills.
- A "primary care copilot" could call specialty agents as consultants without the user ever leaving the primary-care chat.
- A2A output should be structured (JSON schema in Response Format) so the calling agent can parse it programmatically.

### 5.4 What we don't know yet

- Rate limits on A2A calls.
- Whether A2A calls can recurse (Agent A → Agent B → Agent C).
- Whether A2A transcripts are persisted per-patient (for audit).

---

## 6. FHIR Backbone

### 6.1 Workspace FHIR server

Every workspace has its own HAPI FHIR R4 server. Data uploaded via transaction bundles is accessible to any agent with appropriate SMART scopes. This is the source of truth for patient data within Prompt Opinion.

### 6.2 SMART scopes

Standard SMART-on-FHIR scope format: `patient/Resource.rs`, `patient/Resource.cud`, etc. Declared in your MCP extension capabilities. Users approve/reject scopes at registration.

### 6.3 FHIR writes

POST to `{fhir-base}/{ResourceType}` with Bearer token. Resources returned with server-assigned IDs. No conditional writes demonstrated in our build, but the FHIR spec supports them (If-None-Exist for deduplication, etc.).

### 6.4 FHIR as audit surface

Because every MedSafe action is a FHIR resource (MedicationRequest, ServiceRequest, Task, AuditEvent, Communication), the complete interaction history is queryable via the FHIR server. This is a strong point of the platform: there's no separate audit database — the clinical data IS the audit trail.

---

## 7. Scopes

### 7.1 Patient scope
- Agent appears when a patient is selected in Launchpad.
- Every tool call includes `x-patient-id`.
- Best fit for bedside decision support, MedSafe-style tools, specialty consults.

### 7.2 Group scope
- Agent works across a group of patients (cohort).
- Best fit for panel management, outreach campaigns, quality metrics.

### 7.3 Workspace scope
- Agent has unrestricted access to all workspace FHIR data.
- Best fit for admin tools, cross-patient analytics, population health.

Choice of scope determines both UI placement and which headers the platform sends to MCP tools.

---

## 8. Marketplace

Both MCP servers and BYO Agents can be published to the Marketplace. Other workspaces can discover and install them. This turns SignalLoop-style work into **distributable clinical modules** — the hackathon deliverable is not just a demo, it's a listing other workspaces can adopt.

Observed:
- **MCP listings** show tool descriptions and scope requirements.
- **Agent listings** show skill descriptions and required MCP dependencies.
- Marketplace approval process unclear from our research (may require admin review).

---

## 9. Observed Hard Limitations

### 9.1 Things that genuinely can't be done (as of 2026-04)

- **No post-response guardrails.** Can't inspect LLM output and rewrite/block it.
- **No UI rendering of structured output.** Response Format JSON shows as raw JSON, not UI cards.
- **No tool-result transformation layer.** Tool JSON goes straight to LLM; no programmatic post-processing in the platform.
- **No persistent cross-session agent memory.** Each chat session is independent (MCP servers can implement their own cache — we did).
- **One content collection per agent.** Can't compose knowledge bases.
- **No tool versioning.** MCP changes are live.
- **No streaming from tools.** Tools return after full execution.

### 9.2 Things that are awkward but possible

- **Cross-session state:** implement in your MCP server's backing store.
- **Post-response validation:** run a second agent over the first's output via A2A.
- **Complex workflows:** orchestrate via agent system prompt; no visual workflow builder.
- **Multi-collection knowledge:** split across multiple agents that call each other via A2A.

---

## 10. Blue Sky — Maximum Capability Envelope

Assume the platform works exactly as documented, technical feasibility is unlimited, and all observed limitations can be engineered around or accepted. **What could you actually build on Prompt Opinion?**

### 10.1 Full-spectrum clinical assistant ecosystem

A workspace hosts a constellation of agents, each specialized:

- **Triage agent** (patient scope) — reads incoming consultations, routes to the right specialist agent.
- **Specialist agents** (renal, cardio, onco, endocrine, gastro, …) — each a deep expert, each exposing A2A skills.
- **Medication agent** — wraps a MedSafe-style MCP + prescribing workflow.
- **Documentation agent** — produces clinic letters, discharge summaries, referrals.
- **Prior auth agent** — handles payer interactions (external APIs via MCP).
- **Patient-communication agent** — generates patient-facing explanations for clinician approval.

Each agent can call others. The primary care copilot orchestrates: *"ask renal agent about eGFR decline → ask medication agent to check prescription → ask documentation agent to draft the letter."* Every action becomes a FHIR resource.

### 10.2 Deep MCP capability libraries

MCP servers can expose arbitrarily complex capabilities:
- **Image analysis** — radiology, dermatology, ophthalmology AI models wrapped as MCP tools.
- **Clinical calculators** — CHA2DS2-VASc, Wells score, GFR equations, risk prediction models.
- **Guidelines engines** — structured protocol walkthroughs (e.g., sepsis bundle).
- **External integrations** — wearables, remote monitoring, medical devices.
- **Payer APIs** — eligibility, prior auth, claims status.
- **Pharmacy integrations** — e-prescribing, refill management.
- **Lab integrations** — order entry, result retrieval.

Any clinical API or model can be wrapped as MCP, hosted anywhere, registered once, used by every agent.

### 10.3 Population-health mode

Workspace-scope agents can run autonomously against the entire patient population:
- Identify all diabetics with >9% HbA1c who haven't had a med adjustment in 6 months.
- Propose outreach plans.
- Draft patient communications.
- Create Tasks for the care team.

Prompt Opinion becomes not just a clinical decision support tool but a **population health orchestration layer**.

### 10.4 Multi-agent clinical reasoning

A genuinely novel capability: **adversarial or ensemble agent reasoning.** Run the same clinical question through:
- A conservative agent (defaults to referral / watchful waiting)
- A proactive agent (defaults to intervention)
- A guidelines-strict agent (only cites formal guidelines)
- A patient-centered agent (prioritizes patient preference)

Show the clinician all four opinions, each with its reasoning. This is something impossible in classic EHRs — Prompt Opinion's A2A + multi-agent architecture makes it a natural fit.

### 10.5 Real-time monitoring agents

Workspace-scope agents that watch FHIR subscription feeds and act:
- New Observation with abnormal value → invoke MedSafe → auto-draft reconciliation Task.
- New DocumentReference of type "consult note" → auto-invoke loop closure agent.
- New MedicationRequest → auto-invoke safety check, surface to prescribing clinician inline.

FHIR Subscriptions (R4/R5) + workspace-scope agents = event-driven clinical automation.

### 10.6 Agent-curated patient timelines

An agent that continuously synthesizes the patient's story: every encounter, lab, prescription, consult, note — rolled into a living narrative that updates as data arrives. Pinned to the patient chart. Clinicians open the timeline instead of the raw FHIR resource browser.

### 10.7 Personalized patient-facing agents

A patient-scope agent exposed directly to the patient (not just the clinician), grounded in their own record + guidelines, constrained by safety guardrails. Patient asks "what does my kidney result mean?" — agent responds with their specific data in plain language. Every response is auditable; clinician can review.

### 10.8 Research-grade clinical trials matching

Workspace-scope agent that maintains a matching index between the patient population and available trials. Trials database via MCP. Match scores surfaced per-patient. Enrollment paperwork pre-filled. This is currently a huge manual effort — Prompt Opinion's architecture makes it a 1-agent problem.

### 10.9 Regulatory audit agent

An agent that proactively audits every AI action against SaMD / regulatory frameworks. "Did the agent have appropriate evidence for this claim? Was the clinician in the loop? Was a disclaimer shown?" Runs nightly, produces audit reports, flags violations. Because every action is a FHIR resource, the audit data is already there.

### 10.10 Marketplace as distribution channel

Every capability above becomes shippable:
- **Renal Safety Package** (MedSafe MCP + SignalLoop Agent) — what we built.
- **Diabetes Management Package** (MCP + agents for A1c, insulin, foot checks, eye screening).
- **Oncology Package** (chemo ordering MCP + genomics-guided therapy agent + survivorship agent).
- **Maternal-Fetal Package** (antenatal protocols + fetal monitoring + postnatal follow-up).

Every clinical sub-domain can be a Marketplace listing. Healthcare organizations buy/enable what they need. The platform becomes the **App Store for clinical AI.**

### 10.11 Federation

Workspaces can consume MCPs and Agents hosted by **other workspaces or external vendors**. Your renal agent can call a third party's specialist-network A2A agent. Cross-organization clinical AI networks become possible — with SMART scopes governing data access at every hop.

---

## 11. What Would Need to Change for Each Vision

| Vision | Platform gap | Workaround |
|---|---|---|
| Full ecosystem (§10.1) | A2A rate limits, recursion semantics unclear | Build it, measure, iterate |
| Deep MCP libraries (§10.2) | None — already possible | — |
| Population health (§10.3) | Workspace-scope agents need background execution model | Poll via cron, or external scheduler |
| Multi-agent reasoning (§10.4) | No "parallel A2A" primitive shown | Orchestrate sequentially, combine |
| Real-time monitoring (§10.5) | FHIR Subscriptions support unverified | External event bus + agent webhook |
| Timelines (§10.6) | Needs a way to update persistent UI artifacts | Write as FHIR Composition, render custom |
| Patient-facing agents (§10.7) | Patient UI not demonstrated; platform may be clinician-only | Unknown — check with platform team |
| Trials matching (§10.8) | None — MCP + workspace-scope solves it | — |
| Audit agent (§10.9) | No post-response hook; audit must be async | Run as scheduled workspace agent over FHIR AuditEvent log |
| Marketplace (§10.10) | Already exists | — |
| Federation (§10.11) | External MCP/A2A registration path unclear | Likely works since MCP is just URL registration |

---

## 12. First-Principles Assessment

Prompt Opinion's **core insight** is that three open protocols — FHIR (data), SMART (auth), MCP (tools) — plus one proprietary overlay (A2A) give you enough primitives to compose arbitrary clinical AI systems without shipping a monolithic product.

### Where this wins
- **Composability.** Every capability is a tool; every agent is a capability. Clean interfaces.
- **Auditability.** FHIR backbone means every action is data; every data point is queryable.
- **Extensibility.** Any external service that can be MCP-wrapped is instantly available to every agent.
- **Marketplace distribution.** Shipping clinical AI becomes a matter of publishing a listing, not integrating with every EHR.

### Where this is fragile
- **LLM quality determines clinical quality.** Platform doesn't ship an LLM; you're at Gemini/Claude/GPT's mercy. Variance across runs is real (we observed it).
- **No post-response guardrails yet.** Clinical safety has to be in pre-prompt + tool-level rules + good prompt design. There's no second line of defense.
- **No structured UI rendering.** Response Format enforcement doesn't translate to UI. Chat-first design means markdown is the rendering contract — you are responsible for readability.
- **Governance lives in prompts.** If the prompt drifts or the LLM ignores it, governance is gone. Deterministic guard rails (rules engines, tool-level checks) are essential — this is exactly what we baked into MedSafe.

### Where the ceiling is
Extremely high. The platform is well-architected for the **next 5 years of healthcare AI**:
- Multi-agent systems? Built in (A2A).
- Tool-augmented reasoning? Built in (MCP).
- Domain-specific data? Built in (FHIR).
- Regulatory audit? Built in (FHIR as audit).
- Distribution? Built in (Marketplace).

Very few platforms have all five at once. The limitations are practical (UI rendering, post-response guardrails, observability) rather than architectural.

---

## 13. Implications for Builders

If you are building on Prompt Opinion:

1. **Think in FHIR from day one.** Every action is a FHIR resource. Don't invent parallel data stores.
2. **Separate machine and human rendering.** Tool outputs are JSON for machines; chat outputs are markdown for humans. Don't conflate them via Response Format schemas that suit neither.
3. **Deterministic gates, LLM translation.** The LLM should never make safety calls. It should translate between unstructured data and prose. Rules engines make decisions.
4. **Ship MCPs, not monoliths.** A reusable MCP is worth far more than a one-off agent, both for reuse within your workspace and for Marketplace distribution.
5. **Use A2A for domain separation.** Don't build one mega-agent. Build specialized agents that compose.
6. **Design for governance.** Every action should have an auditable trace (FHIR resource, rule_id citation, reasoning log). Prompt Opinion's architecture rewards this.
7. **Test in fresh chats.** Conversation state is per-chat; fresh chats reveal real agent behavior without prior-turn bias.
8. **Keep MCPs stateless; cache in the MCP layer when needed.** The platform gives you no cross-call state; build it explicitly where useful.

---

## 14. One-Paragraph Summary

Prompt Opinion is a clinical AI integration platform whose power comes from composing four primitives (FHIR, SMART, MCP, A2A) into a single configurable runtime. You build MCP servers to add capabilities, BYO agents to orchestrate them, A2A skills to make agents reusable, and publish to a marketplace to distribute your work. The platform doesn't ship the intelligence — it ships the connective tissue that lets you plug intelligence (LLMs, your tools, external services) into a real, data-native, auditable clinical context. Its blue-sky capability envelope — multi-agent specialist networks, population health automation, real-time monitoring, patient-facing personalization, regulatory audit automation, federated clinical AI — is bounded far more by what builders imagine than by what the platform can do.
