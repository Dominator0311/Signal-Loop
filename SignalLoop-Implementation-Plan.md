# SignalLoop — Implementation Plan (Platform-Grounded)

*What is actually buildable, what must be stubbed, and what cannot be done on Prompt Opinion in 3.5 weeks — based on verified platform capabilities, not assumptions.*

---

> ## ⚠️ DOCUMENT STATUS: SUPERSEDED IN PARTS
>
> **This document was written before the final architecture and scope were frozen. Parts of it describe earlier thinking that was subsequently revised.**
>
> **For the authoritative, current plan, read `SignalLoop-Final-Operational-Plan.md` instead.**
>
> **What has changed since this document was written:**
>
> 1. **MedSafe architecture.** This document describes MedSafe as a "rules engine with AI explanation on top." The final design is a **three-phase architecture**: Phase 1 (LLM builds patient risk profile) → Phase 2 (rules use the profile to make deterministic verdicts) → Phase 3 (LLM synthesises patient-specific narrative, personalised alternatives, override analysis). This significantly strengthens AI Factor while keeping safety deterministic. See Final Operational Plan Part 3.
>
> 2. **Submission B architecture.** This document describes Submission B as an **external A2A agent built with Google ADK and hosted externally**. The final design makes Submission B a **BYO Patient-scope A2A agent configured inside Prompt Opinion**. This is lower-risk (skips external hosting dependency and A2A card validation) and still enables A2A via skills. See Final Operational Plan Part 2.
>
> 3. **Referral sub-system.** This document treats referral as a minor capability. The final design expands referral into a **first-class differentiator** with four new tools: specialty-specific packet assembly with missing-context flagging, destination ranking, consult-note recommendation extraction, and plan-conflict detection. See Final Operational Plan Part 6.
>
> 4. **Tool count.** This document references roughly 5–8 tools on MedSafe. Final design has ~14 tools organised across three phases plus referral sub-system.
>
> 5. **Time estimate.** This document estimated ~135 hours. Final estimate is ~159–167 hours, reflecting the expanded MedSafe architecture and referral sub-system.
>
> **What is still valid in this document:**
>
> - Part 1 "Platform Reality Check" — the verified platform capabilities, SHARP headers, submission paths, and critical limitations are unchanged
> - Part 3 "Must build / Can stub / Must fake" — the principle stands; specifics evolved
> - Part 5 "Risk Register" — the risks are unchanged and still worth reviewing
>
> **Why keep this document at all?** It's useful historical context. It shows the reasoning that led to the final plan, it documents the platform investigation (which is still accurate), and it's the bridge document between the Master Spec and the Final Operational Plan. When onboarding a teammate or a fresh Claude session, they may find the platform constraints section valuable even though the architecture has moved on.

---

## Part 1: Platform Reality Check

Before we plan what to build, we have to ground in what the platform actually is. This section is based on direct reading of the Prompt Opinion documentation, the SHARP-on-MCP specification, the hackathon quickstart video, and the public sample repositories.

### 1.1 What the platform gives you for free

The platform handles a lot of plumbing, which changes what "hard" means in this hackathon. Hard is no longer infrastructure. Hard is product design.

**FHIR grounding is native.** When you create a workspace in Prompt Opinion, the workspace itself is a FHIR server. You can import synthetic patients, upload FHIR bundles, or manually create patients. You can then upload clinical notes, documents, or other artifacts against those patients. Any MCP server or agent your product uses can call back to that FHIR server using tokens the platform provides.

**SHARP context propagation is automatic.** This is the single most important platform capability for you. When the platform invokes an MCP server or an external A2A agent that has declared it needs FHIR context, the platform automatically sends three headers:
- `X-FHIR-Server-URL` — the URL to the workspace's FHIR server (always present)
- `X-FHIR-Access-Token` — the bearer token for that FHIR server (optional — some servers don't need auth)
- `X-Patient-ID` — the active patient's ID, when the agent is running in patient scope

For A2A agents specifically, this same information is passed inside the message metadata under the extension URI `https://app.promptopinion.ai/schemas/a2a/v1/fhir-context`. Prompt Opinion currently uses A2A protocol version 0.3; v1 migration is coming.

**Three distinct submission paths exist.** Confirmed from the video and docs:

*Path 1 — BYO Agent (no-code).* You configure an agent inside the Prompt Opinion workspace. You set the system prompt, attach MCP servers as tools, ground it to a Collection (a folder of documents you upload), set a JSON response format schema if you want structured output, enable A2A with skills if you want other agents to be able to consult it, and enable FHIR context extension if the agent should be able to access patient data.

*Path 2 — MCP Server (Superpower).* You build an external MCP server exposing tools. You host it somewhere publicly reachable (during dev: localhost + ngrok). You declare SHARP-on-MCP's `ai.promptopinion/fhir-context` extension in your initialize response. You add it to the Prompt Opinion workspace as an MCP server. The platform then passes the three SHARP headers on every tool call.

*Path 3 — External A2A Agent.* You build an agent that implements the A2A protocol, exposing an agent card at `/.well-known/agent-card.json`. You declare the FHIR context extension in your agent card. You add it to the workspace via "Add Connection" and paste the agent URL. The platform loads the agent card automatically. FHIR context is passed as metadata inside the A2A message payload.

**Model is free to start.** Google AI Studio gives a free Gemini API key. As of April 2026, the platform recommends Gemini 3.1 Flash-Lite Preview (the current preview model) or Gemini 2.5 Flash-Lite (the stable GA model from July 2025). The platform also supports OpenAI, Claude (direct and via Azure/Vertex), and Gemini on Vertex AI if you bring paid credentials.

**JSON structured output is supported.** On BYO agents you can specify a JSON schema under the Response Format tab. Every provider has different schema restrictions, so your Reasoning Agent's structured interpretation object from the spec needs to be designed with these in mind.

**Grounding to one content collection.** You can upload PDFs or other documents to a Collection and ground an agent's answers to that collection. Critical limitation: each agent can only be grounded to one content source at a time. So if you want guideline grounding plus BNF grounding, you need two agents, or you bundle everything into one collection.

**Consulting other agents is a first-class operation.** In a BYO agent's chat, the clinician picks an external A2A agent from a "Consult with another agent" dropdown. The BYO agent then uses A2A to talk to it. This is Prompt Opinion's answer to agent composition.

**Guardrails exist, but pre-prompt only.** You can attach guardrail agents that run before your main agent sees a prompt. Post-response guardrails are "coming soon," not available now.

### 1.2 Critical limitations that shape the design

These are the hard constraints. Any stage of the SignalLoop spec that fights these loses.

**There is no patient-facing chat interface.** The launchpad is clinician-facing. A patient cannot open Prompt Opinion and talk to an intake agent directly. If you want patient intake, you need an external UI (a simple web form or chat frontend) that calls into the platform's APIs. For a 3.5-week hackathon, this is scope creep you cannot afford.

*Consequence for SignalLoop:* Stage 1 Intake in its original form (patient speaks naturally to the product) is not realistic as a live flow. The honest path is to frame intake as *already complete* — synthetic patients are pre-loaded with clinical notes and intake artifacts, and the demo shows the resulting structured draft with the four-state taxonomy visible. The intake *quality* is showcased; the live capture is faked.

**There is no scheduled trigger or event subscription.** Agents run when a user types in chat. There is no cron, no webhook listener for "new lab result arrived," no way to say "wake up every morning and check open loops." The platform is request-response, not event-driven.

*Consequence for SignalLoop:* Stage 7 Loop Closure's watchdog — the agent that sweeps open loops and fires escalations — cannot run natively. Options: (a) make the loop control tower a view the clinician opens on demand that computes state at that moment; (b) host the watchdog externally as a standalone service that mutates FHIR resources the platform later reads; (c) fake the time-jump in demo. For hackathon: (a) + (c) is the honest answer.

**External A2A agents cannot be the primary chat target.** This is critical for your architecture. Per the docs: *"You cannot start a conversation via the launchpad with an external agent."* External agents are invoked only via the "Consult with another agent" dropdown from an active BYO agent conversation.

*Consequence for SignalLoop:* The "Orchestrator" in the spec cannot be an external A2A agent. It must be a BYO agent. External A2A agents can be specialists the orchestrator consults.

**One content collection per agent.** If you want to ground on both NICE guidelines and BNF content, you either merge them into one collection or you split across multiple agents.

*Consequence for SignalLoop:* Your Signal Interpreter probably wants guideline grounding. Your MedSafe explanation agent wants medication reference grounding. These want to be separate agents, consulted from the orchestrator.

**Medication photo upload is not in the platform.** There's no file upload from the patient side. If you want OCR of medication images, you need to build it into the external infrastructure yourself.

*Consequence for SignalLoop:* Image OCR for medications is an "upload in advance" story in the demo. You can have MCP tools that normalize free-text medication strings to dm+d/RxNorm codes, but the image reading layer needs to be considered scope.

**No native SMS/email/portal notification.** The platform has no notification layer.

*Consequence for SignalLoop:* Patient outreach is "drafted not sent" in the demo. Show the SMS text, don't pretend to deliver it.

**Marketplace publishing is a manual step.** The video is explicit: you must publish your MCP server or agent to the Marketplace Studio before judging. This is not automatic.

*Consequence for SignalLoop:* Reserve the last 2 days for publishing, validation in-platform, and recording the demo. Do not leave this to the last hour.

**Authentication is minimal by default.** MCP servers have no auth by default; the video mentions you can add API key auth but the default Spoke community template doesn't. Don't ship to a real healthcare context, but it's fine for hackathon with synthetic data.

### 1.3 What requires custom work

Everything product-specific. The platform handles standards propagation, agent hosting (for BYO), A2A/MCP wiring, and FHIR access. What it does not handle:

- Any domain intelligence (relevance selection, interpretation, safety logic, etc.)
- Any external knowledge source (BNF, NICE, dm+d content — you bring it)
- Any deterministic rules engine (MedSafe interaction logic)
- Any external UI (patient intake, notifications)
- Any persistence layer beyond FHIR (loop state is up to you)
- Any scheduling, eventing, or long-running workflow orchestration

---

## Part 2: Mapping SignalLoop Stages to Platform Paths

This is the architectural commitment. Every stage lives somewhere specific.

### 2.1 Submission strategy (confirmed)

Two entries, sharing 90% of code:

**Entry A — Superpower (MCP category):** `MedSafe MCP Server`
Standalone MCP server exposing deterministic medication safety tools. Reusable infrastructure that any agent in the marketplace can call. Same code whether consumed by SignalLoop or a third party.

**Entry B — Agent (A2A category):** `SignalLoop Interpretation Agent`
External A2A agent that does context-aware signal interpretation and action composition. Implements the FHIR context extension. Gets consulted by the main BYO orchestrator.

Both submissions work with a third element you build but don't submit: a BYO Orchestrator agent inside your Prompt Opinion workspace that ties everything together for the demo.

### 2.2 The full architecture

```
┌───────────────────────────────────────────────────────────────┐
│  Prompt Opinion Workspace (your env)                          │
│                                                               │
│  ┌──────────────────────────────┐                             │
│  │  BYO Orchestrator Agent      │  ← user chats here          │
│  │  (configured in-platform)    │                             │
│  │                              │                             │
│  │  · Grounded: guidelines+BNF  │                             │
│  │  · Tools: MedSafe MCP        │──────┐                      │
│  │  · Consults: Interpretation  │──────┼──┐                   │
│  │  · FHIR context: enabled     │      │  │                   │
│  └──────────────────────────────┘      │  │                   │
│                                        │  │                   │
│  ┌──────────────────────────────┐      │  │                   │
│  │  Workspace FHIR Server       │      │  │                   │
│  │  · Synthetic patients        │      │  │                   │
│  │  · Clinical notes            │◀─────┼──┼────┐              │
│  │  · Labs, meds, etc.          │      │  │    │              │
│  └──────────────────────────────┘      │  │    │              │
└────────────────────────────────────────┼──┼────┼──────────────┘
                                         │  │    │
              ┌──────────────────────────┘  │    │
              ▼                             │    │
  ┌─────────────────────────┐               │    │ (FHIR reads
  │  SUBMISSION A           │               │    │  via SHARP
  │  MedSafe MCP Server     │               │    │  headers)
  │  (external, you host)   │───────────────┼────┤
  │                         │               │    │
  │  Tools:                 │               │    │
  │  · med.normalize        │               │    │
  │  · interactions.check   │               │    │
  │  · dosing.renal_adjust  │               │    │
  │  · allergy.cross_react  │               │    │
  │  · beers_stopp_start    │               │    │
  │  · explain_flag         │               │    │
  │                         │               │    │
  │  Declares:              │               │    │
  │  ai.promptopinion/      │               │    │
  │  fhir-context           │               │    │
  └─────────────────────────┘               │    │
                                            │    │
              ┌─────────────────────────────┘    │
              ▼                                  │
  ┌─────────────────────────┐                    │
  │  SUBMISSION B           │                    │
  │  SignalLoop             │                    │
  │  Interpretation Agent   │                    │
  │  (external A2A)         │────────────────────┘
  │                         │
  │  Skills:                │
  │  · interpret_signal     │
  │  · compose_action       │
  │  · build_referral_packet│
  │                         │
  │  Extension:             │
  │  FHIR context required  │
  │                         │
  │  Built with: Google ADK │
  └─────────────────────────┘
```

### 2.3 Stage-by-stage mapping

| Spec Stage | Lives Where | Build Path | Reality Check |
|---|---|---|---|
| 1. Intake Capture | Pre-loaded as synthetic data | None (faked) | Not buildable as live patient-facing flow in hackathon |
| 2. Context Aggregation | BYO Orchestrator system prompt + FHIR reads | Path 1 | Native — orchestrator fetches what it needs |
| 3. Signal Interpretation | External A2A Agent (Submission B) | Path 3 | Real. The AI showcase. |
| 4. Trend Analysis | Part of Submission B, or MCP tool | Path 3 or 2 | Real but text-based output |
| 5. MedSafe Gate | Standalone MCP Server (Submission A) | Path 2 | Real. The safety showcase. |
| 6. Action Composition | Part of Submission B (same agent, different skill) | Path 3 | Real — same agent handles this |
| 7. Loop Closure | BYO Orchestrator + FHIR writes + on-demand view | Path 1 | Partially real. Watchdog is faked via time-jump. |

### 2.4 Why this split works

Each submission category has its own strength and this division plays to both:

**MedSafe as MCP** is perfect for the Superpower category because medication safety is genuinely reusable. Any other agent in the Prompt Opinion marketplace — a discharge copilot, a prior auth bot, a chronic care manager — could call MedSafe. It's also the cleanest to build because it's deterministic: no LLM creativity, just rules with structured outputs.

**SignalLoop Interpretation as A2A** is perfect for the Agent category because the interpretation work benefits from being a specialist. The orchestrator handles user conversation and flow; the interpretation agent does the heavy contextual reasoning. When the orchestrator says "I need to make sense of this new eGFR result for Margaret," it consults the specialist. That's the A2A story.

**BYO Orchestrator** is not submitted but makes the demo possible. It's the visible chat interface the user experiences.

---

## Part 3: Scope Reality — Must Build, Can Stub, Must Fake

Every spec has ambition. Every hackathon has 3.5 weeks. This is where we cut.

### 3.1 Must build (real code, no shortcuts)

These are the things that have to work for the submission to be credible and for the demo to hold up to a single judge question.

**MedSafe MCP Server (Submission A).**
- Functional MCP server implementing streamable HTTP transport
- Declares `ai.promptopinion/fhir-context` extension in initialize response
- Returns 403 if FHIR context headers are missing and required
- At least 5 tools: `normalize_medication`, `check_interactions`, `check_renal_dosing`, `check_allergy_conflict`, `explain_flags`
- Deterministic interaction engine seeded with ~150 curated high-signal drug pairs (NSAIDs+ACE, warfarin+antibiotics, statins+macrolides, etc.) — enough to cover common demo scenarios
- At least one renal dosing rule (e.g., NSAID contraindicated at eGFR<60, dose-adjust gabapentin below eGFR 50)
- Allergy cross-reactivity: penicillin↔cephalosporin, sulfa cross-class
- Beers criteria flags for age>65
- Structured JSON output per tool with severity enum

**SignalLoop Interpretation A2A Agent (Submission B).**
- Agent card served at `/.well-known/agent-card.json`
- Declares FHIR context extension required
- Three skills exposed: `interpret_new_signal`, `compose_next_action`, `build_referral_packet`
- Uses Google ADK (Python — use `po-adk-python` as starting point)
- Can read FHIR from the workspace using passed token
- Returns structured JSON interpretation object per the spec
- Generates both clinician brief and patient explanation as distinct artifacts

**BYO Orchestrator (in-platform config).**
- Configured in Prompt Opinion workspace
- System prompt implementing the 4-state reconciliation taxonomy framing
- JSON response schema for structured output
- MedSafe MCP attached as tool
- Interpretation Agent available for consultation
- FHIR context enabled
- Grounded on a small Collection of relevant guidelines

**Synthetic patient data.**
- 1 to 3 carefully crafted patients with full clinical context
- Margaret: 72F, CKD stage 3b, T2DM, HTN, on lisinopril + furosemide + metformin + simvastatin, new eGFR 42 (down from 58), knee pain — this is the hero demo patient
- Secondary patient for backup / testing
- Tertiary for stress-testing edge cases
- All loaded with recent labs, conditions, medications, allergies, encounters, and a few clinical notes

**FHIR writes.**
- Real `MedicationRequest` creation when prescription approved
- Real `ServiceRequest` creation for referrals
- Real `Task` creation for follow-ups
- Real `AuditEvent` logging for every consequential action

### 3.2 Can stub (smart fakes that pass inspection)

These are things where a realistic-looking stub is indistinguishable from the real thing in the demo, and building the real thing is scope creep.

**Intake 4-state taxonomy.** The data is pre-loaded but shown in the UI tagged as if freshly reconciled. One field on the synthetic patient (e.g., "patient reports stopping metformin 3 months ago, chart active") is displayed with the amber CONFLICT state, another is MISSING-BUT-IMPORTANT. The user sees reconciliation; the reconciliation was done by you, by hand, weeks ago.

**Trend visualization.** Don't try to build inline charts in the chat UI. Generate trend descriptions in text ("eGFR: 58 → 52 → 42 over 3 months; declining at 4 points/month"), optionally paired with a simple ASCII sparkline in code blocks. If you want real visualization, generate an image URL via a separate service, but this is optional polish.

**Loop Control Tower.** Instead of a live, always-up-to-date dashboard, implement it as a skill on the orchestrator: "show me overdue loops." The response is a markdown table computed from FHIR Task states at query time. No watchdog. No real-time updates. It looks like a dashboard when the clinician asks for it.

**Medication image OCR.** Pre-load the medication list. Don't attempt real image upload. If you want to show the capability, include a "medications extracted from photo uploaded 4/12" header above the list.

**Specialist matching / directory.** Hardcode three nephrologists in a JSON file. Don't integrate with a real directory API.

**Interaction evidence citations.** For the ~150 curated drug pairs, include fixed citation strings ("BNF 2026 §4.2.3 — severe interaction"). Don't try to build a live evidence lookup system.

### 3.3 Must fake (demo-only, don't build logic)

**Time jumps.** "Six days later" is a hard cut in the recorded video. Don't build a time simulator. Just cut.

**Scheduled watchdog escalation.** The "overdue referral chase" scene shows the escalated state because the FHIR Task resource was manually set to `status: requested, priority: urgent` for demo purposes. Don't build a scheduler.

**Patient SMS outreach.** Show the drafted SMS text in a code block. Don't wire SMS gateways.

**Real specialist acknowledgement.** The "consult note returned" is a pre-prepared `DocumentReference` you insert into the FHIR server mid-demo (or was there all along and gets "discovered"). No real specialist integration.

**Cross-organization federation.** Not in scope. If a judge asks, it's clearly articulated as a roadmap item.

### 3.4 Roadmap (explicit "not in MVP")

State these in the Devpost writeup as acknowledged future work:

- Multi-specialty Context Agents for different specialties
- Probabilistic loop failure prediction
- Adaptive patient outreach cadence
- Cross-organization A2A federation
- Voice-native clinician mode
- Real-time event subscriptions when the platform supports them
- Payer integration for prior auth
- Multimodal image understanding beyond OCR
- Learning from clinician edits
- HEDIS/MIPS emission hooks

Explicitly calling these out makes you look like you understand the problem domain and have thought about production, without committing to ship them.

---

## Part 4: Week-by-Week Build Plan (3.5 weeks, deadline May 11)

Today is April 17. Deadline is May 11. You have approximately 24 days including final publishing and video recording.

### Week 1 (Apr 18 – Apr 24): Infrastructure and Foundation

**Goal:** All three components talk to each other end-to-end on a trivial flow, FHIR reads work, SHARP headers propagate, A2A works, MCP works.

**Days 1–2: Environment setup.**
- Clone `po-community-mcp` (Python branch) as MedSafe starting point
- Clone `po-adk-python` as Interpretation Agent starting point
- Clone `po-overview` for reference
- Prompt Opinion workspace created, Gemini key configured
- Google AI Studio key working
- ngrok account configured with reserved domain (paid $10/mo is worth it vs. rotating URLs)

**Days 3–4: Synthetic patient loading.**
- Design Margaret's full chart: conditions, medications, allergies, 6 months of labs, 2 clinical notes
- Upload via FHIR bundle or platform UI
- Verify BYO default agent can answer basic questions about her
- Build two backup patients for different scenarios

**Days 5–6: MedSafe MCP minimal version.**
- Just two tools: `normalize_medication` (string → code) and `check_interactions` (med list → flags)
- Hardcode 20 interaction pairs to start
- Deploy locally + ngrok
- Register in Prompt Opinion as MCP server
- Verify FHIR headers are received when invoked

**Day 7: Interpretation Agent minimal version.**
- Just the `interpret_new_signal` skill
- Agent card served
- Extension declared
- Can receive FHIR context, fetch patient meds from FHIR, return a basic interpretation
- Registered in workspace as external agent
- BYO agent can consult it

### Week 2 (Apr 25 – May 1): Core Capability Depth

**Goal:** The AI reasoning and deterministic safety logic are genuinely good, not placeholders.

**Days 8–10: MedSafe depth.**
- Grow interaction table to 150 pairs focused on common scenarios
- Add renal dosing rules (eGFR thresholds for common drugs)
- Add allergy cross-reactivity
- Add Beers criteria for age>65
- Severity matrix implemented (Contraindicated / Major / Moderate / Minor × Established / Probable / Suspected / Theoretical)
- `explain_flags` tool uses LLM to explain why each flag matters for this patient (this is the only LLM call in MedSafe)
- Test with Margaret's full profile: ibuprofen should block

**Days 11–13: Signal Interpretation depth.**
- Structured JSON output object per the spec
- Relevance selection: given a new lab and a patient context, decide which prior results and conditions matter
- Trend computation: fetch longitudinal observations, compute rate of change
- Dual-output generation: clinician brief + patient explanation from same reasoning
- Ground the agent on NICE CKD guidelines and a few other relevant guideline PDFs
- Test end-to-end: new eGFR for Margaret returns a rich, contextualized brief

**Day 14: Action Composition.**
- Second skill on the Interpretation Agent: `compose_next_action`
- Takes structured interpretation + context, returns action bundle
- Action types: repeat_lab, repeat_imaging, med_change, referral, escalation, watchful_waiting
- Third skill: `build_referral_packet` — for referral actions, assembles specialty-specific packet

### Week 3 (May 2 – May 8): Integration, Polish, FHIR Writes

**Goal:** The workflow is smooth end-to-end, writes back to FHIR, and the demo story is rehearsed.

**Days 15–16: Orchestrator orchestration.**
- BYO agent system prompt tuned so it knows when to consult Interpretation Agent vs. call MedSafe
- JSON response schema for chat outputs that downstream panels can render
- Action approval flow: clinician says "approve," orchestrator writes `MedicationRequest` / `ServiceRequest` / `Task` to FHIR
- `AuditEvent` writeback for every consequential action

**Days 17–18: Loop tracking.**
- FHIR Task resources created for every follow-up
- "Show me open loops" skill on orchestrator returns formatted table of Task resources
- One pre-loaded scenario where the loop is "6 days later" and a consult note `DocumentReference` has been pre-inserted
- `return_handler` logic that parses a DocumentReference and creates a new Task for the PCP

**Day 19: Marketplace publishing.**
- Publish MedSafe MCP to Marketplace Studio
- Publish Interpretation Agent to Marketplace Studio
- Verify both are discoverable and invokable by a fresh test user
- Write the Devpost descriptions

**Days 20–21: Demo rehearsal.**
- Write the 3-minute script word-for-word
- Pre-stage Margaret's FHIR state so the demo story works in one take
- Rehearse 5 times, fix what breaks
- Record a test version
- Watch it back and cut to <3:00

### Final stretch (May 9 – May 11): Recording and Submission

**Day 22: Final polish.**
- Any last bugs
- Final copy pass on Devpost writeup
- Final copy pass on agent descriptions
- Final copy pass on readme in GitHub repos

**Day 23: Record.**
- Record final video in one clean environment
- Two takes minimum
- Edit to exactly under 3:00
- Upload

**Day 24: Submit.**
- Devpost submission with video link, GitHub links, description
- Verify Marketplace entries are live
- Verify FHIR context works when tested as a fresh user
- Submit before deadline, not at deadline

---

## Part 5: Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| ngrok URL rotates mid-build, breaks registrations | High | Medium | Pay $10 for reserved domain on day 1 |
| Gemini rate limits hit during development | Medium | Low | Start with free, swap to paid Vertex key if needed |
| A2A agent card or extension declaration subtly wrong | Medium | High | Test against working sample from po-adk-python early and often |
| MedSafe interaction coverage inadequate for demo scenarios | Medium | High | Design Margaret's chart first, then build interaction rules to cover it |
| JSON response schema issues (Gemini quirks) | Medium | Medium | Test schema with simple examples before building dependencies on it |
| FHIR writeback fails silently | Low | High | Verify writes show up in Prompt Opinion UI before building on them |
| Demo patient data gets accidentally mutated during rehearsal | Medium | High | Scripted reset — a bash script that deletes and re-uploads Margaret's FHIR bundle |
| 3-minute demo over-runs | High | Medium | Write script word-for-word, time it, cut ruthlessly |
| Platform behaves differently for fresh-user evaluation than for you | Medium | High | Test with a second Prompt Opinion account in the final week |
| Marketplace submission has review delay | Unknown | High | Submit to Marketplace Studio at least 4 days before deadline |

---

## Part 6: Demo Execution Plan (Revised for Platform)

The blue-sky demo in the master spec describes a cinematic 3-minute arc. This is the version that actually happens on Prompt Opinion.

### The flow inside Prompt Opinion

**Open the app** → Launchpad → select "Margaret Henderson" (the pre-loaded patient) → select "SignalLoop Orchestrator" (your BYO agent) → conversation opens.

**Act 1 — Context in (0:00–0:40).** User types: *"It's Margaret's appointment this morning. Anything I should know?"*

The Orchestrator consults the Interpretation Agent. The response streams back in a structured format: recent eGFR decline prominently flagged, relevant history (T2DM, HTN, current ACE + diuretic), reason-for-visit context (knee pain from intake), plus a quiet amber note — *"Chart-patient reconciliation conflict: patient reports stopping metformin 3 months ago; chart shows active."*

The four-state taxonomy is visible in the rendered output. The brief is dense and clinical, as it should be.

**Act 2 — Interpretation (0:40–1:20).** User types: *"Tell me more about the eGFR."*

The Orchestrator pulls the longitudinal observations, asks the Interpretation Agent for deeper analysis. Response includes the trend narrative ("eGFR declining 4 points/month, no recent interventions explain it"), why this matters for this patient specifically ("already on ACE + diuretic — any NSAID would be a third strike"), evidence citation, and proposed action candidates ranked.

**Act 3 — The MedSafe moment (1:20–1:50).** User types: *"Start ibuprofen 400mg TDS for her knee pain."*

The Orchestrator calls MedSafe MCP. Response is blocking:

```
⛔ CONTRAINDICATED
Proposed: ibuprofen 400mg TDS × 7 days

Patient context:
· eGFR 42 (declining) — CKD Stage 3b
· Active: lisinopril 10mg, furosemide 40mg
· Age 72

Flags:
[Contraindicated · Established] NSAID inappropriate in CKD 3b
  (NICE NG203 §1.3.2; BNF severe)
[Major · Established] NSAID + ACE-I + diuretic = triple-whammy AKI
[Moderate · Established] Beers criteria: avoid chronic NSAIDs >65

Safer alternatives:
· Paracetamol 1g QDS — no renal impact
· Topical diclofenac — minimal systemic absorption

This order will not be created without override + reason.
```

User types: *"Use paracetamol 1g QDS instead."*

MedSafe runs again — clean. Orchestrator writes `MedicationRequest` to FHIR. Confirmation message includes the written resource ID.

**Act 4 — Loop opens (1:50–2:20).** User types: *"Refer to nephrology, urgent."*

Orchestrator consults Interpretation Agent with the `build_referral_packet` skill. Response: packet with reason, relevant labs, current meds, specific clinical question. Three candidate nephrologists returned (hardcoded). User picks one. Orchestrator writes `ServiceRequest` and `Appointment` to FHIR. Confirms loop registered.

User types: *"Show me Margaret's open loops."*

Table rendered, all Tasks with status, expected-by date. Margaret's nephrology referral tagged amber because it's recent; a different pre-loaded loop from another patient is tagged red (overdue) to show the escalation state.

**Act 5 — Time jump (2:20–2:50).** Video cut: "Six days later." Pre-insert the consult note DocumentReference. User types: *"Did we get anything back from nephrology?"*

Orchestrator detects the returned DocumentReference, runs the `return_handler` logic, extracts recommendations (hold ACE, recheck in 6 weeks, no NSAIDs ever). Writes a new Task for the PCP. Loop transitions to CLOSED. Audit trail shown.

**Close (2:50–3:00).** Tagline slate: *"Context in. Verified action out. Loop closed."* Logo. GitHub + Marketplace links.

### Why this demo holds up

Every visible capability is backed by real code:
- Orchestrator: real BYO agent in Prompt Opinion
- Interpretation: real external A2A agent receiving real FHIR context
- MedSafe: real MCP server with real deterministic rules
- FHIR writes: real MedicationRequest, ServiceRequest, Task, AuditEvent
- Referral packet: real composition, not a template
- Loop table: real query over Task resources

What's pre-arranged (not faked in logic, just staged in data):
- Margaret's chart is pre-loaded
- The three candidate nephrologists are hardcoded
- The "six days later" consult note is pre-inserted mid-video via script
- The overdue loop for loop-table-drama is a pre-staged Task

That is honest staging, not fraud. Every hackathon demo does this. What matters is that any judge who clicks "test this submission" in Prompt Opinion the next day can reproduce the core interactions — and they will, because the core interactions are really working.

---

## Part 7: What This Plan Explicitly Gets Right vs. The Master Spec

The master spec described a north-star product. This plan describes what's shippable. Differences that matter:

1. **Stage 1 Intake goes from "live patient conversation" to "pre-loaded reconciled draft with visible taxonomy."** The reconciliation capability is still showcased; the live capture is not.

2. **Stage 7 Loop Closure goes from "scheduled watchdog sweeping in the background" to "on-demand queryable view backed by FHIR Task resources."** The loop-tracking capability is still showcased; the background persistence is not.

3. **The Orchestrator is a BYO agent, not an external A2A agent.** This is forced by the platform. It doesn't change the capability; it changes the category.

4. **The demo cinematics are replaced with platform-native interactions.** The hero moment — the MedSafe block — is preserved in full fidelity because that's where the platform's chat interface actually shines.

5. **Multi-specialty, federation, outreach, voice — all explicitly roadmap.** Not "maybe in MVP."

6. **The two submissions share 90% of code.** MedSafe is the same MCP whether standalone or called from the Interpretation Agent. Interpretation Agent is the same A2A whether standalone or consumed by the Orchestrator.

---

## Part 8: The One Sentence for Each Submission

**Submission A — MedSafe MCP Server:**
*MedSafe is a standards-first medication safety MCP server: any healthcare agent in the Prompt Opinion marketplace can invoke its deterministic interaction, contraindication, renal dosing, and allergy cross-reactivity checks to protect patients from unsafe prescribing before an order is written.*

**Submission B — SignalLoop Interpretation Agent:**
*SignalLoop is a context-aware clinical signal-to-action agent: given a new lab, imaging, or pathology result, it decides what matters for this specific patient, produces both a clinician brief and a patient-friendly explanation, composes the next verified action, and builds specialty-ready referral packets when escalation is needed.*

---

*This implementation plan is the operational companion to the master spec. The master spec says what SignalLoop is. This says what will be built, in what order, with what stubs, with what risks. Deviation from this plan should be deliberate and logged.*
