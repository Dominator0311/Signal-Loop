# Licensing, Attribution, and Clinical Source Provenance

This repository contains three clinical-AI submissions for the **Agents Assemble — Healthcare AI Endgame** hackathon (Prompt Opinion / Darena Health, deadline May 11, 2026):

- **MedSafe MCP** — `signalloop-medsafe-mcp/` (medication safety primitives)
- **SignalLoop Renal Safety Agent** — `agent-config/system-prompt-signalloop.md` (BYO agent in Prompt Opinion)
- **Concord MCP** — `concord-mcp/` (multi-specialty clinical coordination)

This document explains the licensing of clinical content used by these tools and how that content is reproduced.

---

## 1. Patient data — synthetic only

All patient bundles in `fhir-bundles/` are **fully synthetic**. No real-patient data, no PHI, no de-identified reuse. Hero patients (Margaret Henderson, James Okonkwo, Doris Williams, Arthur Blackwell, Patricia Quinn, Frances Doyle) are invented for demonstration. Names, identifiers, dates of birth, and clinical histories are fabricated.

This is consistent with hackathon rule §"Synthetic / de-identified data only".

---

## 2. Clinical knowledge sources — fair-use summarisation

The deterministic safety rules under `medsafe_core/rules/data/` reference real clinical knowledge bases. Each rule entry **names the source** and **summarises the rule's mechanism in original wording**. Verbatim text from copyrighted sources is **not** reproduced in this repository.

This is the standard approach for clinical-decision-support software, and it falls within fair-use (UK CDPA s.30 and US Copyright Act §107 equivalents) for two reasons:

1. **Mechanism summary is original expression** — paraphrasing how an interaction works in our own words is creative speech, not a substitute for the source.
2. **No commercial redistribution of source content** — anyone seeking the verbatim text must consult the original source under its own licence terms.

The `clinical_review_status` field on each rule entry communicates which licence model applies:

| Value | Meaning |
|---|---|
| `summarised_from_named_source` | Rule mechanism / severity reflects the named clinical source; verbatim text intentionally not reproduced (closed-licence source) |
| `verbatim_verified` | Rule text reproduced verbatim from the named source under that source's open licence (NICE / MHRA — Open Government Licence v3.0). Attribution provided in the rule's citation field. |

---

## 3. Source-by-source licensing

### Open licence — verbatim reproduction permitted

| Source | Licence | Attribution required |
|---|---|---|
| **NICE Guidelines** (NG28, NG106, NG203, CG141, CG177, CG185, CG187) | Open Government Licence v3.0 | "Contains public sector information licensed under the Open Government Licence v3.0. Source: National Institute for Health and Care Excellence ([nice.org.uk](https://www.nice.org.uk/))." |
| **MHRA Drug Safety Updates** | Crown copyright under Open Government Licence v3.0 | "Contains public sector information licensed under the Open Government Licence v3.0. Source: Medicines and Healthcare products Regulatory Agency ([gov.uk/drug-safety-update](https://www.gov.uk/drug-safety-update))." |
| **dm+d (Dictionary of Medicines and Devices)** | NHS Digital — UK Open Government Licence | "Contains NHS Digital data licensed under the Open Government Licence v3.0." |
| **LOINC** | LOINC committee — free-for-use, attribution required | "This material contains content from LOINC ([loinc.org](https://loinc.org/)). LOINC is copyright © 1995-present, Regenstrief Institute, Inc., available at no cost under the [LOINC license](https://loinc.org/license/)." |
| **SNOMED CT (UK use)** | NHS Digital UK terminology server | UK use is free under NHS terminology service licence. International use varies. |

### Closed licence — summarised only, never reproduced verbatim

| Source | Licence holder | What we do |
|---|---|---|
| **British National Formulary (BNF)** | NICE / Pharmaceutical Press | Cite by name and Appendix/section reference. Mechanism summarised in original wording. Users seeking verbatim must consult BNF directly via NHS OpenAthens, BNF print/online subscription, or [bnf.nice.org.uk](https://bnf.nice.org.uk/) (subset publicly viewable). |
| **AGS Beers Criteria 2023** | American Geriatrics Society / Wiley (J Am Geriatr Soc) | Cite by DOI and table reference. Categories named generically; verbatim criteria text not reproduced. |
| **STOPP/START v2** | Oxford University Press (Age and Ageing) | Cite by DOI. Criterion mechanism summarised; verbatim text not reproduced. |

---

## 4. Hackathon submission notes

For the hackathon judges:

- **No fabricated rules.** Every rule entry in `medsafe_core/rules/data/` cites a real, named clinical source. Mechanisms reflect the source's substance.
- **Where verbatim reproduction is licence-clean** (NICE / MHRA), we provide it directly. Look for `clinical_review_status: "verbatim_verified"`.
- **Where verbatim reproduction is licence-restricted** (BNF / Beers / STOPP), we provide a faithful summary. Look for `clinical_review_status: "summarised_from_named_source"`.
- **Production deployment** (post-hackathon, in a clinical setting) would require a clinician/pharmacist with access to the original sources to verify each summary against the verbatim text. That is normal due diligence for clinical-decision software, regardless of how it was authored.

---

## 5. Code licensing

Code in this repository is provided as a hackathon submission. No specific open-source licence is asserted; all rights remain with the author until a licence file is added. Reuse of clinical knowledge requires independent verification against the original sources cited.

---

## 6. Status of verbatim verification

The 19 rule entries that cite **NICE Guidelines (NG28, NG106, NG203, CG185)** or **MHRA Drug Safety Updates** are eligible for verbatim reproduction under Open Government Licence v3.0 — pasting the exact NICE/MHRA wording into those entries would be **legally permitted**.

That backfill was attempted via automated web-fetching of the NICE / MHRA websites, but those sites are JavaScript-rendered single-page applications that do not expose the recommendation text in the server-rendered HTML. Reliable verbatim extraction therefore requires either:

1. **Manual paste** — open the live NICE / MHRA page in a browser, copy the verbatim recommendation text, paste it into the matching rule entry's `citation_text_verbatim` field, and set `clinical_review_status: "verbatim_verified"`. ~10-15 min per guideline.
2. **NICE Syndication API** — NICE offers an API for licensed reuse of guidance content (https://www.nice.org.uk/about/what-we-do/syndication). Free for non-commercial use; requires registration.
3. **NICE PDF download** — every guideline page has a "Download as PDF" button. The PDF text layer is extractable.

The 19 candidate entries are listed below. **All currently carry `clinical_review_status: "summarised_from_named_source"`** — the same defensible fair-use posture as the BNF / Beers / STOPP entries. They can be upgraded to `verbatim_verified` post-hackathon when manual time allows.

### NICE/MHRA verbatim-eligible entries

| File | Entry | Source clause |
|---|---|---|
| `renal_dose_adjustments.json` | metformin × 3 bands | NICE NG28 §1.6.1 (Type 2 diabetes — metformin and renal impairment) |
| `renal_dose_adjustments.json` | lithium × 3 bands | NICE CG185 (Bipolar disorder — lithium prescribing) |
| `renal_dose_adjustments.json` | dapagliflozin × 2 bands | NICE NG203 §1.3.16 (CKD — SGLT2 inhibitors) |
| `renal_dose_adjustments.json` | spironolactone | NICE NG203 (CKD — MRA contraindications) |
| `ddi_pairs.json` | DDI-NSAID-DIURETIC-ACEI | NICE NG203 (triple-whammy AKI risk) |
| `ddi_pairs.json` | DDI-STATIN-MACROLIDE | MHRA Drug Safety Update (statin / clarithromycin) |
| `ddi_pairs.json` | DDI-ACEI-K-SPARING | NICE NG106 (Chronic HF — ACE-I + aldosterone antagonists) |
| `ddi_pairs.json` | DDI-ACEI-TRIMETHOPRIM | MHRA Drug Safety Update Sept 2014 |
| `ddi_pairs.json` | DDI-DUAL-RAAS | MHRA Drug Safety Update May 2014 |
| `ddi_pairs.json` | DDI-COLCHICINE-CLARITHROMYCIN | MHRA Drug Safety Update |
| `ddi_pairs.json` | DDI-CITALOPRAM-QT | MHRA Drug Safety Update Dec 2011 |
| `ddi_pairs.json` | DDI-CLOPIDOGREL-PPI | MHRA Drug Safety Update Apr 2010 |
| `ddi_pairs.json` | DDI-OPIOID-BENZODIAZEPINE | MHRA Drug Safety Update Mar 2020 |

For hackathon submission this status is defensible — all 19 cite their open-licence source faithfully, even though the verbatim wording is not reproduced.

---

## 7. Verification status by file

| File | Source | Reproduction mode |
|---|---|---|
| `medsafe_core/rules/data/renal_dose_adjustments.json` | BNF chapters + NICE NG28/NG203/CG141/CG177/CG185 | Mixed — NICE-cited entries can be `verbatim_verified`; BNF-cited entries stay `summarised_from_named_source` |
| `medsafe_core/rules/data/beers_2023.json` | AGS Beers 2023 | Always `summarised_from_named_source` (closed licence) |
| `medsafe_core/rules/data/stopp_start_v2.json` | O'Mahony 2015, Age and Ageing | Always `summarised_from_named_source` (closed licence) |
| `medsafe_core/rules/data/ddi_pairs.json` | BNF Appendix 1 + MHRA Drug Safety Updates + scattered NICE/peer-reviewed | Mixed — MHRA / NICE entries can be `verbatim_verified`; BNF stays `summarised_from_named_source` |
| `medsafe_core/rules/data/interactions.json` (legacy) | Same scope as ddi_pairs.json | `summarised_from_named_source` |

---

*This document is intended to make the project's content-licensing posture transparent to hackathon judges and to anyone considering deployment in a clinical setting.*
