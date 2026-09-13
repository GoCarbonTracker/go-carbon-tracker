# Discourse Graph — Architecture Deep Dive

> **Design document, written 2026-03-14.** It describes how the system is designed to work. Any count, size, timing, or cost figure below is a snapshot from that date, not a live number. Detection outputs described here are candidates for human review, not findings; see the [README](../../README.md#one-worked-example-tata-motors) for what review of the Tata Motors output produced.
## Overview

The Discourse Graph is GoCarbonTracker's system for transforming raw sustainability report text into structured, verifiable arguments. It answers the question: **"What does this company claim, what evidence in its own documents supports or conflicts with it, and which apparent conflicts deserve a human look?"**

Every claim extracted from a corporate report is linked to supporting and contradicting evidence, scored for credibility across 9 factors, and assessed for risk across 5 dimensions. The risk score ranks candidates for review; it is not a verdict.

---

## Data Model

```
                ┌─────────────────┐
                │     CLAIM       │
                │                 │
                │ "BMW targets    │
                │  net-zero by    │
                │  2050"          │
                │                 │
                │ Type: net_zero  │
                │ Credibility:    │
                │  0.72 (9 factors)│
                └────────┬────────┘
                         │
              ┌──────────┴──────────┐
              │                     │
     ┌────────▼────────┐  ┌────────▼────────┐
     │   SUPPORTING    │  │  CONTRADICTING  │
     │   EVIDENCE      │  │  EVIDENCE       │
     │                 │  │                 │
     │ 76 contexts     │  │ 2 contexts      │
     │ from reports    │  │ conflicting     │
     │ that back the   │  │ data points     │
     │ claim           │  │                 │
     └────────┬────────┘  └────────┬────────┘
              │                    │
              └────────┬───────────┘
                       │
              ┌────────▼────────┐
              │    ARGUMENT     │
              │                 │
              │ Strength: 98.7% │
              │ Verdict: Strong │
              │                 │
              │ Greenwashing    │
              │ Risk: 27% (Low) │
              │                 │
              │ 5 risk factors  │
              │ analyzed        │
              └─────────────────┘
```

---

## Claim Types

Claims are categorized by the type of sustainability assertion:

| Claim Type | Description | Example |
|-----------|-------------|---------|
| `net_zero_claims` | Net-zero or carbon neutrality targets | "Carbon neutral by 2040" |
| `emissions_reduction` | Scope 1/2/3 reduction commitments | "40% reduction by 2030" |
| `renewable_energy` | Renewable energy adoption targets | "100% renewable electricity by 2025" |
| `sbti_commitment` | Science-Based Targets initiative | "SBTi validated 1.5°C pathway" |
| `supply_chain_engagement` | Supplier decarbonization programs | "80% of suppliers set SBTs" |
| `circular_economy` | Circular economy and waste reduction | "95% recycling rate achieved" |
| `ev_transition` | Electric vehicle transition plans | "50% BEV sales by 2030" |
| `water_stewardship` | Water usage and conservation | "30% water intensity reduction" |
| `biodiversity` | Biodiversity and ecosystem protection | "Zero deforestation commitment" |
| `social_labor` | Social and labor practices | "Living wage across supply chain" |
| `governance` | Corporate governance and oversight | "Board-level climate committee" |

---

## Credibility Scoring

Each claim receives a composite credibility score (0.0 to 1.0) based on 9 independently assessed factors:

```
Credibility Score = Weighted Average of 9 Factors

┌─────────────────────────────┬───────┐
│ Quantitative Presence       │ 0.80  │  Has specific numbers?
├─────────────────────────────┼───────┤
│ Baseline Target Clarity     │ 0.90  │  Clear baseline & target?
├─────────────────────────────┼───────┤
│ Verification Indicators     │ 0.70  │  Third-party verified?
├─────────────────────────────┼───────┤
│ Methodology Disclosure      │ 0.60  │  Explains how measured?
├─────────────────────────────┼───────┤
│ Temporal Specificity        │ 0.80  │  Concrete timelines?
├─────────────────────────────┼───────┤
│ Source Authority             │ 0.70  │  Credible source?
├─────────────────────────────┼───────┤
│ Assured                      │ 0.50  │  Externally assured?
├─────────────────────────────┼───────┤
│ CDP Verified                 │ 0.80  │  CDP aligned?
├─────────────────────────────┼───────┤
│ CSRD/ISSB                    │ 0.50  │  Framework compliant?
├─────────────────────────────┴───────┤
│ COMPOSITE SCORE:              0.72  │
└─────────────────────────────────────┘
```

---

## Greenwashing Risk Assessment

After credibility scoring, each claim-argument pair is given a review-priority risk score (0-100 scale). It ranks candidates for human review; it is not a greenwashing verdict:

| Risk Factor | Weight | What It Detects |
|------------|--------|----------------|
| Credibility Risk | High | Low credibility score → vague or unverifiable claims |
| Evidence Ratio Risk | Medium | Too little evidence supporting a strong claim |
| Contradictions Risk | High | Other evidence directly contradicts this claim |
| Progress Risk | Medium | Claims without evidence of actual implementation |
| Specificity Risk | Low | Vague language without measurable commitments |

### Risk Levels

| Score | Level | Interpretation |
|-------|-------|---------------|
| 0-25 | Low | Well-supported, credible claim |
| 26-50 | Medium | Some concerns, needs deeper review |
| 51-75 | High | Significant credibility gaps |
| 76-100 | Critical | Review first |

---

## Evidence Linking

Evidence items connect knowledge base contexts to discourse claims:

```
Evidence Link:
  claim_id     → Links to a specific claim
  context_id   → Links to a KB context (source text from report)
  type         → "supporting" or "contradicting"
  relevance    → Combined relevance score (0.0 - 1.0)
  keyword_score → BM25 keyword match quality
  semantic_score → TF-IDF semantic similarity
```

**Scale:** 1,638,798 evidence links connecting 18,832 claims to 37,877 contexts.

This means on average, each claim is linked to ~87 pieces of evidence, enabling robust credibility assessment.

---

## Contradiction Detection

Contradictions are automatically detected when:

1. Two claims from the **same company** conflict (e.g., "carbon neutral by 2040" vs "no net-zero target set")
2. A company's claim conflicts with **supplier data** (e.g., OEM claims supply chain decarbonization, but suppliers report increased emissions)
3. **Year-over-year** data shows regression against stated targets

Snapshot 2026-03-14: 1,833 candidate contradictions detected across the automotive knowledge base. These are unreviewed candidates. The only adjudicated sample, Tata Motors on 2026-09-09, went 12 flagged to 0 genuine; every candidate was an extraction artifact.

---

## Architecture Principles

| Principle | Implementation |
|-----------|---------------|
| Separation of concerns | Claims, evidence, and arguments are independent entities linked by IDs |
| Incremental extraction | New claim types can be added without re-processing existing data |
| Evidence-first verdicts | Arguments are derived from evidence ratios, not claim text alone |
| Multi-factor assessment | No single factor determines credibility — 9 factors provide nuance |
| Cross-company linking | Evidence from any company can support/contradict claims from another |
| Reproducibility | All scores are deterministic given the same evidence set |
