# Concord MCP — 3-Minute Demo Script

> **Submission:** Concord (Path B / orchestrator-style) — *Agents Assemble: Healthcare AI Endgame*
> **Tool under demo:** `RunCardioRenalConsult` (single MCP tool, server-side multi-specialist orchestration)
> **Server:** `https://concord-mcp.fly.dev`
> **Patients:** Arthur Blackwell (conflict) → Patricia Quinn (consensus) → Frances Doyle (insufficient data)
> **Total runtime:** 3:00 (with 5 s reserve)

The demo proves three things in one continuous pass:
1. **AI Factor:** three specialty Gemini reasoners run in parallel and feed a deterministic conflict-resolution rules engine.
2. **Impact:** cardio-renal coordination that takes a real MDT 7+ days collapses to ~25 s, with full audit trail.
3. **Feasibility:** one MCP tool, one entry point, FHIR-aware, marketplace-publishable, portable to any MCP host (Claude, Cursor, Cline, etc.).

---

## 0:00 – 0:15 — Hook

**Visual cues**
- Title card: *"Cardio-renal coordination — 7 days → 25 seconds."*
- Cut to Prompt Opinion chat with a Concord MCP icon visible in the tool sidebar.

**Voiceover (12 s)**
> "When a patient has heart failure *and* kidney disease, every prescription
> needs sign-off from cardiology, nephrology, and pharmacy. A real MDT can
> take a week. Watch what happens when those three specialists are agents
> running in parallel."

**On-screen overlay:** "1 MCP tool · 3 specialty Gemini reasoners · deterministic rules engine"

---

## 0:15 – 1:30 — Arthur Blackwell (the conflict case)

**State transition:** Arthur's patient record is open in Prompt Opinion. The clinician types the coordination question.

**Clinician message (typed live):**
> "Cardiology wants more diuresis on Arthur, nephrology is worried about
> AKI — what's the unified plan?"

**Visual cues**
- Tool-call chip appears in chat: `RunCardioRenalConsult` firing.
- Status updates fade in/out as the tool emits MCP `notifications/message` events:
  - "Building episode brief from FHIR record..."
  - "Consulting nephrology, cardiology, and pharmacy specialists in parallel..."
  - "Received 3 specialist opinions; classifying conflicts..."
  - "Synthesising patient-safe explanation and rendering panel decision..."

**Voiceover (45 s, over the tool firing)**
> "Concord's tool runs nine phases server-side: it pulls Arthur's FHIR record,
> compresses it into an episode brief, then fans out to three Gemini
> specialists — nephrology, cardiology, pharmacy — *in parallel.* Each one
> emits a structured opinion: action codes, rationale, monitoring
> requirements, contraindications. Those opinions feed a pure-Python
> rules engine that classifies every action into one of six buckets:
> consensus, tension, direct conflict, dependency, safety block, or
> missing-data block. No LLM makes the verdict. The rules engine does.
> The LLM contextualises."

**Visual cue (around 0:55):** Mermaid conflict-matrix diagram renders inline in the chat panel. Highlight one red node (direct conflict on diuretic uptitration) and one grey node (safety caveat on ACE-I hold).

**Voiceover (continues, 30 s)**
> "Here's the matrix. Green is consensus. Amber is one-specialist
> recommendations or items waiting on data. Red is true direct conflict —
> cardiology and nephrology disagreeing on diuretic strategy. Grey is
> safety caveats. Concord doesn't sweep that conflict under the rug —
> it surfaces it as 'unresolved' and refuses to draft a write until the
> clinician arbitrates. Plan validation: pass-with-warnings. Three
> tasks drafted, zero medication writes. Audit event logged."

**Overlay text:** "Total wall clock: ~25 s · Real MDT equivalent: 5–10 days"

---

## 1:30 – 2:15 — Patricia Quinn (the consensus case)

**State transition:** Clinician switches to Patricia Quinn's record. Same chat, same tool.

**Clinician message:**
> "Patricia is in for her 4-monthly review — anything to change?"

**Visual cues**
- Same tool-call chip, same progress notifications.
- Mermaid diagram renders: this time **all green nodes**.
- Three "Agreed actions" lines appear in the markdown panel. Zero pending. Zero unresolved.

**Voiceover (40 s)**
> "Same tool, different patient. Patricia has stable heart failure on full
> guideline-directed therapy, stable kidneys, normal potassium, mildly
> elevated but stable BNP, weight steady. All three specialty Gemini
> reasoners independently land on the same plan: continue current GDMT,
> review at four weeks, repeat U&E in a week. Concord shows three green
> consensus nodes, zero conflicts, zero pending decisions. This matters
> because a real panel mostly *agrees* — the system has to handle the
> quiet case as cleanly as the dramatic one. A naive LLM would
> hallucinate disagreement to look interesting. The deterministic
> rules engine doesn't."

**Overlay text:** "3 / 3 specialists agree · 0 conflicts · plan validated"

---

## 2:15 – 2:45 — Frances Doyle (the insufficient-data case)

**State transition:** Clinician switches to Frances Doyle's record.

**Clinician message:**
> "Frances has been getting more breathless — should we start her on
> heart-failure treatment?"

**Visual cues**
- Same tool-call chip, same progress notifications.
- Mermaid diagram renders with mostly **grey nodes** (missing-data blocks) plus one or two amber nodes for "Request BNP / NT-proBNP" and "Request echo".
- Markdown panel shows under "Unresolved / data gaps":
  - `[DATA_DEPENDENCY on START_SGLT2] supporting specialty reports missing clinical data`
  - `(cardiology) Missing: NT-proBNP, echocardiogram`
  - `(nephrology) Missing: recent eGFR, creatinine, potassium`

**Voiceover (28 s)**
> "Frances has breathlessness on exertion, but no BNP, no echo, no recent
> kidney function on file. NICE guidance is unambiguous — you don't start
> heart-failure GDMT without those. Look what Concord does. Three grey
> nodes: missing-data blocks. The specialists explicitly say *we cannot
> decide on diuretic, GDMT, or SGLT2 without these tests*. Concord drafts
> two tasks: request the BNP, request the echo. Zero medication writes.
> Clinical honesty under uncertainty — the system refuses to bluff. That
> is the difference between a tool you'd let near a real patient and a
> tool you wouldn't."

**Overlay text:** "Concord refuses to recommend GDMT without evidence base"

---

## 2:45 – 3:00 — Tag

**Visual cues**
- Cut to a clean wide shot showing the Concord MCP server entry in the Marketplace listing.
- Title card: *"11 MCP tools · FHIR-aware · marketplace-published · portable to any MCP host."*

**Voiceover (12 s)**
> "Concord. Eleven MCP tools. One single-call orchestrator. FHIR-aware.
> Deterministic conflict resolution. Marketplace-published, and it runs
> in any MCP host — Claude, Cursor, Cline, the Prompt Opinion chat
> you've just seen. Three specialists, one plan, full audit trail."

---

## Production checklist (for the editor)

- [ ] Patricia, Frances, and Arthur bundles uploaded to demo workspace before recording.
- [ ] Concord MCP server reachable at `https://concord-mcp.fly.dev` and listed in the BYO MCP server list.
- [ ] Pre-warm Gemini connection by running one consult against a throwaway patient ~30 min before recording (cold-start latency on Fly is the #1 demo risk).
- [ ] Capture the chat at 1080p; the Mermaid diagram is a critical visual — verify it renders before takes.
- [ ] If the tool-call chip flashes too fast in PO's UI, slow the segment in post by 1.25× — the audience needs to see the progress notifications.
- [ ] Subtitle every voiceover line — judges may watch muted.

## Failure-mode contingencies

| Failure | Detection | Fallback |
|---|---|---|
| Specialist Gemini call timeout (>35 s) | Tool returns `### Concord — Insufficient specialist responses` markdown | Skip ahead to next patient; mention in voiceover only if visible |
| Mermaid not rendering in PO chat | No diagram block in panel | Cut directly to the "Agreed actions" / "Unresolved" sections; the markdown alone still tells the story |
| Fly cold start exceeding 50 s | Loading spinner persists | Pre-warm 30 min before recording (see checklist) |

## Why this script wins on the rubric

- **AI Factor (33 %):** three parallel specialty Gemini reasoners + structured-output Pydantic schemas + deterministic Python rules engine + visible Mermaid output. The voiceover names every component.
- **Impact (33 %):** real cardio-renal MDTs cost ~£200/hour and take a week. Three patients in three minutes makes the time-compression visceral.
- **Feasibility (33 %):** one MCP tool, one entry point, FHIR R4, deployed on Fly free tier. Judges can run the same query themselves the moment the demo ends.
