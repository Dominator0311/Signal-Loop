# Medication Interaction Reference (BNF-Style Summary)

## Purpose
This document provides a summary of key medication interactions relevant to the SignalLoop MedSafe rules engine. It covers the interactions most likely to be encountered in the demo scenarios and tested by judges.

Source: Based on BNF interaction guidelines (public severity ratings), Stockley's Drug Interactions summaries, and peer-reviewed literature.

## Severity Classification

| Severity | Definition | Action |
|----------|-----------|--------|
| Contraindicated | Must not be given together | Block prescribing |
| Major (Severe) | High risk of serious harm | Warn; require documented override |
| Moderate | Clinically significant but manageable | Warn; inform prescriber |
| Minor | Unlikely to cause problems for most patients | Inform only |

## Key Interactions

### NSAID Interactions

| NSAID + | Severity | Mechanism | Clinical Consequence |
|---------|----------|-----------|---------------------|
| ACE-I/ARB + Diuretic | Major | Triple-whammy: removes all renal compensation | AKI (10-15% of elderly AKI admissions) |
| ACE-I/ARB (without diuretic) | Moderate | Reduces renal perfusion | Reduced eGFR, hyperkalaemia risk |
| Warfarin | Major | Antiplatelet effect + GI mucosal damage | GI and other bleeding |
| Methotrexate | Major | Reduced renal clearance of MTX | Pancytopenia, hepatotoxicity |
| Lithium | Major | Reduced renal clearance of lithium | Lithium toxicity (levels rise 15-30%) |
| SSRIs | Moderate | Both impair platelet function | Increased GI bleeding risk (15x if combined) |
| CKD (eGFR <60) | Contraindicated | Prostaglandin-dependent renal perfusion | Accelerates CKD, precipitates AKI |
| Age ≥65 (chronic) | Moderate | Reduced renal reserve, GI vulnerability | GI bleeding, AKI, CV events (Beers) |
| Heart failure | Major | Fluid retention, prostaglandin inhibition | Acute decompensation |

### ACE-I/ARB Interactions

| ACE-I/ARB + | Severity | Mechanism | Clinical Consequence |
|-------------|----------|-----------|---------------------|
| Potassium supplements | Major | ACE-I reduces K+ excretion | Hyperkalaemia (potentially fatal) |
| Spironolactone | Major | Both retain potassium | Hyperkalaemia (monitor closely) |
| Another ACE-I or ARB | Major | Dual RAAS blockade | AKI, hyperkalaemia (ONTARGET trial) |
| NSAIDs | Moderate-Major | See above | Reduced renal function |
| Trimethoprim | Moderate | Both increase potassium | Hyperkalaemia (especially in CKD) |

### Statin Interactions

| Statin + | Severity | Mechanism | Clinical Consequence |
|----------|----------|-----------|---------------------|
| Clarithromycin/Erythromycin | Major | CYP3A4 inhibition increases statin levels | Rhabdomyolysis risk |
| Grapefruit juice (large amounts) | Moderate | CYP3A4 inhibition | Increased statin levels |
| Fibrates (gemfibrozil) | Major | Pharmacokinetic + pharmacodynamic | Myopathy/rhabdomyolysis |

### Warfarin Interactions

| Warfarin + | Severity | Mechanism | Clinical Consequence |
|-----------|----------|-----------|---------------------|
| Clarithromycin/Erythromycin | Major | CYP inhibition + altered gut flora | INR increase, bleeding |
| Trimethoprim | Major | Inhibits warfarin metabolism | INR rises 40-65%, bleeding |
| NSAIDs | Major | Antiplatelet + GI damage | Bleeding (see above) |
| Metronidazole | Major | CYP2C9 inhibition | INR increase |

## Cross-Reactivity (Allergies)

| Allergy to | Cross-reaction risk with | Risk level |
|-----------|-------------------------|------------|
| Penicillin | Cephalosporins | ~1-2% (higher with 1st-gen cephalosporins) |
| Penicillin | Carbapenems | <1% |
| One NSAID | Other NSAIDs | High (COX-1 mediated, class effect) |
| Sulfonamide antibiotics | Sulfonamide diuretics | Low (different mechanism, but ask) |

## Renal Dosing Quick Reference

| Drug | eGFR threshold | Action |
|------|---------------|--------|
| NSAIDs | <60 | Avoid (contraindicated) |
| Metformin | <45 | Reduce to max 1g/day |
| Metformin | <30 | Stop |
| Gabapentin | <50 | Reduce max dose |
| Lithium | <60 | Reduce dose, monitor levels frequently |
| Dapagliflozin | <25 | Do not initiate (can continue if already on) |
