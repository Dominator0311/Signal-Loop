# AGS Beers Criteria 2023 — Summary for SignalLoop

Source: American Geriatrics Society 2023 Updated AGS Beers Criteria for Potentially Inappropriate Medication Use in Older Adults. J Am Geriatr Soc. 2023;71(7):2052-2077.
URL: https://agsjournals.onlinelibrary.wiley.com/doi/10.1111/jgs.18372

## Purpose

The Beers Criteria identify medications that are potentially inappropriate for adults aged 65 and older. "Potentially inappropriate" means the risks generally outweigh benefits for most older adults — it does NOT mean absolutely contraindicated in all cases.

## Medications Relevant to SignalLoop Demo Scenarios

### NSAIDs (Oral) — AVOID

**Recommendation:** Avoid chronic use of oral NSAIDs.

**Rationale:** Increases risk of:
- GI bleeding / peptic ulcer disease
- Acute kidney injury (especially with concurrent ACE-I, ARB, or diuretics)
- Cardiovascular events (MI, stroke)
- Fluid retention / worsening heart failure
- Hypertension exacerbation

**Quality of Evidence:** Moderate
**Strength of Recommendation:** Strong

**Exception:** Short-term use (<1 week) may be acceptable with gastroprotection if no renal impairment, no concurrent nephrotoxic drugs, and no history of GI bleeding.

### Proton Pump Inhibitors (PPIs) — Avoid beyond 8 weeks without clear indication

**Rationale:** Long-term use associated with C. difficile infection, bone loss, fractures, hypomagnesaemia.

### Benzodiazepines — AVOID

**Rationale:** Increased sensitivity in older adults. Risk of cognitive impairment, delirium, falls, fractures.

### First-Generation Antihistamines (diphenhydramine, chlorphenamine) — AVOID

**Rationale:** Highly anticholinergic. Risk of confusion, dry mouth, constipation, urinary retention, falls.

### Tricyclic Antidepressants — AVOID

**Rationale:** Anticholinergic, sedating, orthostatic hypotension. Risk of falls, cardiac conduction abnormalities.

### Long-Acting Sulfonylureas (glibenclamide/glyburide) — AVOID

**Rationale:** Higher risk of severe prolonged hypoglycaemia due to long half-life and active metabolites.

### Skeletal Muscle Relaxants — AVOID

**Rationale:** Poorly tolerated due to anticholinergic effects, sedation, and fall risk. Effectiveness questionable at tolerable doses.

## How Beers Criteria Apply in SignalLoop

The Beers Criteria are used in the MedSafe Phase 2 rules engine as a MODERATE severity flag when:
- Patient age ≥65 AND
- Proposed medication matches a Beers-listed drug class

This does NOT block prescribing (severity is moderate, not contraindicated). It raises awareness that the prescriber should consider age-related risk.

In Margaret's case (age 72), Beers adds a THIRD reason to avoid ibuprofen on top of the renal contraindication and triple-whammy risk. The combination of all three makes the case overwhelming.

## Important Nuance

Beers criteria are NOT absolute prohibitions. They are:
- A prompt for risk-benefit discussion
- Stronger when compounding with other risk factors (as in Margaret)
- Weaker in isolation for short-term use in otherwise healthy elderly

The MedSafe architecture handles this correctly by rating Beers flags as MODERATE severity / ESTABLISHED evidence, which translates to a WARN (not a BLOCK) in the verdict matrix.
