# Concord MCP Demo Patients

Three FHIR R4 transaction bundles purpose-built for the Concord cardio-renal
consult tool (`RunCardioRenalConsult`). Each patient surfaces a different
axis of multi-specialist reasoning so the 3-minute demo can show consensus,
direct conflict, and clinical honesty under uncertainty in one continuous
walk-through.

## Upload

Upload each bundle to the demo workspace as a FHIR `Bundle` POST. All
`fullUrl` values are real UUIDs (per project memory: HAPI 502s on
non-UUID `urn:uuid:` values), and intra-bundle references resolve at
ingestion — server-assigned IDs differ per workspace and do not need
post-upload patching.

```
concord-patient-arthur-post.json     ← conflict case (existing hero patient)
concord-patient-patricia-post.json   ← consensus case
concord-patient-frances-post.json    ← insufficient-data case
```

## Patients

| Patient | Age / Sex | Key clinical picture | Concord expected outcome |
|---|---|---|---|
| **Arthur Reynolds** | 78 M | Decompensated HFrEF + worsening CKD3b. Cardiology wants more diuresis, nephrology worried about AKI. | Direct conflict on diuretic strategy → `direct_conflicts` populated; pharmacy adds K+ monitoring caveat. |
| **Patricia Quinn** | 68 F | Stable HFrEF (LVEF 35%) + stable CKD3a (eGFR 52, K+ 4.4). On full quadruple GDMT. NT-proBNP 250 stable. Weight stable. | All three specialties agree → `consensus` populated, `direct_conflicts` empty. Plan: continue GDMT, review at 4w. |
| **Frances Doyle** | 75 F | Suspected HF (NYHA II symptoms documented at GP encounter) + ?CKD. **Missing:** BNP, echo, recent eGFR/creatinine, weight history. Amlodipine monotherapy. | Most candidate actions fall into `missing_data_blocks` — specialists honestly state "cannot decide diuretic / GDMT until BNP, echo, eGFR available." |

### Patricia Quinn — design notes

Active medications (all on file):
- bisoprolol 5 mg OD
- ramipril 5 mg OD
- eplerenone 25 mg OD
- empagliflozin 10 mg OD
- furosemide 40 mg OD
- metformin 1 g BD

Recent labs (last 6 months):
- eGFR: 53 → 51 → 52 mL/min/1.73m² (stable)
- creatinine 110 µmol/L
- K+ 4.4 mmol/L
- NT-proBNP 540 pg/mL (elevated but stable; appropriate for compensated HFrEF on quadruple GDMT in CKD3a — both impaired LVEF and reduced eGFR contribute to chronic NT-proBNP elevation)
- HbA1c 56 mmol/mol
- LVEF 35 % (TTE Dec-2025, no change vs Mar-2023 baseline)
- weight 72.4 → 72.6 kg (stable)

Why this should produce consensus: every specialist sees a patient with
optimised guideline-directed therapy, no decompensation signals, no
data gaps, and no drug-level safety conflicts. The right answer is
"continue and monitor," and all three specialties should arrive at it
independently. This demonstrates that Concord handles the boring-but-
important "no change needed" case as cleanly as the high-drama conflict
case — a real MDT mostly produces consensus, and Concord shouldn't
hallucinate disagreement to look interesting.

### Frances Doyle — design notes

Sparse record by design:
- HTN (long-standing, on amlodipine 10 mg OD)
- Suspected HF (verificationStatus = `provisional`) recorded after a
  GP encounter Mar-2026 with breathlessness on exertion and ankle
  swelling
- OA (PRN paracetamol)
- BP 142/84 at last GP visit
- **No BNP, no echo, no recent eGFR or creatinine, no weight log, no
  potassium**

Why this should produce missing-data blocks: NICE NG106 requires
BNP/NT-proBNP and echo before initiating HF-specific GDMT. Without those
plus an eGFR baseline, a responsible specialist cannot recommend
starting a loop diuretic, ACE-I, MRA, or SGLT2i. The conflict matrix
should fill `missing_data_blocks` and the unified plan should fall
through to "request BNP, request echo, repeat U&E within 1 week" rather
than committing to drug changes. This demonstrates clinical honesty
under uncertainty — a real specialty MDT does not invent confidence
where the evidence base does not support it, and the demo proves
Concord refuses to either.

## How these patients map to the demo script

The 3-minute demo script (`agent-config/concord-demo-script.md`) walks
through Arthur → Patricia → Frances in that order so the judge sees:
1. Full Concord wow-moment on the conflict case (Arthur)
2. Same tool, different patient → consensus (Patricia)
3. Same tool, missing data → honest deferral (Frances)

That sequence proves the system handles the three real archetypes a
panel encounters — disagreement, agreement, and indeterminacy — using
exactly one tool entry point.

## Bundle clinical-coding notes

- **Patricia's empagliflozin** is coded with dm+d concept `30789011000001100`
  (system `https://dmd.nhs.uk`). The NHS dm+d / SNOMED browsers are JS-rendered
  so the code's canonical status was not verified server-side. The FHIR
  `medicationCodeableConcept` includes a `text` fallback ("Empagliflozin 10mg
  tablets") so HAPI accepts the bundle regardless. If HAPI is configured for
  strict terminology validation and rejects the `coding[]` entry, the safe
  fallback is to drop `coding[]` and rely on `text` only.
- **Other dm+d codes** in Patricia's and Frances's bundles follow the same
  belt-and-braces pattern (coding + text). Frances's bundle is intentionally
  minimal — the design-intent is to demonstrate `missing_data_block`
  classification when key labs are absent.
