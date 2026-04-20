# Agent Configuration Files

These files are used to configure the BYO SignalLoop Renal Safety Agent
in Prompt Opinion. They are NOT code — they are configuration that you
paste into the platform UI.

## Files

### system-prompt.md
The orchestration prompt. Paste the content between the ``` markers into
the "System Prompt" field in Prompt Opinion (Agents → BYO → your agent → System Prompt).

### response-schema.json
The structured output schema. Paste into the "Response Format" tab.
- `response-schema.json` — full version (try this first)
- `response-schema-simplified.json` — fallback if Gemini can't handle nesting

### content-collection/
Upload these 6 markdown files to a single Collection in Prompt Opinion
(Content tab → create collection → upload all 6 files).

| File | Content | Pages |
|------|---------|-------|
| 01-nice-ng203-ckd-management.md | CKD prescribing + referral criteria | ~2 |
| 02-nice-ng226-osteoarthritis.md | OA analgesic ladder | ~1.5 |
| 03-triple-whammy-aki.md | NSAID + ACE-I + diuretic = AKI | ~2 |
| 04-beers-criteria-2023.md | Beers criteria for elderly | ~1.5 |
| 05-nephrology-referral-checklist.md | What nephrologists need | ~2 |
| 06-medication-interaction-reference.md | Key drug interactions | ~2 |

Total: ~11 pages (well under 25-page limit)

## Setup Order (when you have laptop access)

1. Create the agent (Agents → BYO → Add AI Agent)
2. Set scope to "Patient"
3. Paste system prompt
4. Paste response schema (try full version first)
5. Attach MedSafe MCP server as tool
6. Create content collection, upload all 6 files
7. Enable A2A with skill "renal_safety_consult"
8. Enable FHIR context (required)
9. Save and test
