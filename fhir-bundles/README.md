# FHIR Bundles & Patient Documents — SignalLoop

Upload-ready content for the three demo patients plus their clinical documents.

## Structure

```
fhir-bundles/
├── README.md                       ← this file
├── _convert_to_post.py             ← util: convert PUT bundle → POST bundle
├── patient-margaret-post.json      ← ACTIVE bundle
├── patient-doris-post.json         ← ACTIVE bundle
├── patient-james-post.json         ← ACTIVE bundle
├── patient-documents/              ← PDFs for Documents tab uploads
│   ├── _convert_to_pdf.py          ← util: markdown → PDF via Chrome headless
│   ├── margaret-nephrology-consult.md   ← source (editable)
│   └── margaret-nephrology-consult.pdf  ← ACTIVE (upload to Margaret's Documents tab)
└── _archive/                       ← superseded files, reference only
```

## Upload order (fresh workspace)

Upload all three patient bundles as FHIR transactions. That's it — no separate consult upload step.

1. `patient-margaret-post.json` — includes Progress Note (GP visit) AND Nephrology Consult note (Dr Patel) as DocumentReferences inside the bundle
2. `patient-doris-post.json`
3. `patient-james-post.json`

After upload, server-assigned UUIDs will differ per workspace. The bundle's internal `urn:uuid` cross-references resolve automatically during ingestion — no post-upload patching needed.

## Why consult note lives INSIDE Margaret's bundle (not Documents tab)

**Architectural decision documented here for future reference.**

Prompt Opinion's Documents tab is a UI feature that stores uploaded files on a proprietary endpoint requiring browser session-cookie authentication. MCP servers (like ours) authenticate with FHIR Bearer tokens and cannot reach that endpoint programmatically — the server serves an HTML login shell instead of the file bytes. This is a platform limitation, not a code bug.

Bundle-embedded DocumentReferences with inline base64 content:
- Appear in the Documents tab UI exactly the same as UI-uploaded docs (clinician UX unchanged)
- Are readable by our MCP via FHIR-standard paths (works programmatically)
- Resolve bundle-internal `urn:uuid` references at ingestion (no UUID patching)
- Are how real EHRs ingest specialist letters in production (HL7/FHIR feed from hospital systems)

The patient-documents/ folder contains markdown + PDF versions of the consult note as HUMAN-viewable artifacts (for reference, Marketplace listing samples, etc.) — but the runtime data path is the bundle.

## Patient overview

| Patient | Age/Sex | Conditions | Demo purpose |
|---|---|---|---|
| Margaret Henderson | 72F | CKD 3b, T2DM, HTN, OA | Hero BLOCK (NSAID + triple-whammy); consult loop closure |
| Doris Williams | 67F | RA on methotrexate | WARN + Override flow |
| James Okonkwo | 42M | None | Safe control (CLEAN) |

## Regenerating the consult PDF

If you edit `patient-documents/margaret-nephrology-consult.md`:

```bash
cd fhir-bundles/patient-documents
python _convert_to_pdf.py
```

Requires: `markdown` Python package + Chrome at `/Applications/Google Chrome.app`. Uses the signalloop-medsafe-mcp venv if you don't have markdown globally.

## Creating a new patient bundle

1. Write the PUT-based bundle (standard FHIR format)
2. Run `_convert_to_post.py` to produce a POST-based bundle with `urn:uuid` cross-references
3. Upload the `-post.json` version (HAPI FHIR rejects PUT with unregistered IDs)

## Archived files

In `_archive/`:

- Pre-conversion PUT bundles (kept for reference; use `*-post.json` instead)
- `consult-return-nephrology-post.json` — old FHIR bundle path for the consult note, superseded by the PDF-via-Documents-tab approach above
- `test-minimal-patient.json` — early scaffolding, unused

## Known content details

- Consult note uses corrected dates: "5 months" and "~3 points/month" (matches the observation dates in Margaret's bundle: Nov 2025 → Apr 2026)
- The archived JSON bundle had "3 months" / "~4 points/month" — contradicted the dates. Fixed in the PDF version.
