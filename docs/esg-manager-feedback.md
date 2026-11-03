# ESG Manager Perspective: GoCarbonTracker Evaluation

**Date**: 2024-11-03
**Context**: Feedback on GoCarbonTracker v0.2.1-alpha after testing with HelloFresh SE reports (3 years sustainability + annual reports)
**Metric Coverage**: 43 canonical metrics (reduced from 112 in original specification)

## Executive Summary

GoCarbonTracker has a strong technical foundation with one genuinely differentiated feature: **physical evidence anchoring**. The 43-metric reduction from the original 112-metric spec shows good judgment. However, to transition from research tool to essential ESG software, it needs framework alignment, benchmarking capabilities, and workflow integration.

**Current State**: Valuable for evidence management and audit trails
**Needed**: ESG compliance features, multi-company comparison, export capabilities

---

## What Works Well

### 1. Evidence Anchoring (Killer Feature)
Most ESG tools aggregate numbers but lose provenance. GoCarbonTracker tracks every claim to exact page coordinates `[x0, y0, x1, y1]`. When auditors ask "where did this figure come from?" or stakeholders question a number, you have physical proof with bounding box visualization.

**Real-world value**: Reduces audit preparation time, strengthens data defensibility, enables claim verification.

### 2. Smart Metric Reduction
The 43-metric focus is correct, not limiting. The original 112-metric specification was unrealistic - most companies don't report that granularly. Forcing coverage creates garbage data.

The v3 metric list prioritizes:
- Standardized, comparable metrics across companies
- Reliable extraction over comprehensive coverage
- Quality over quantity

**Impact**: 82% match rate (7,517/9,187 figures matched) on HelloFresh workspace demonstrates practical effectiveness.

### 3. Cross-Report Harmonization
Sustainability teams waste hours reconciling figures between annual reports, sustainability reports, CDP submissions, and investor presentations. Auto-detecting the same metric reported in different formats saves real time.

**Example from testing**: HelloFresh reports emissions data in both sustainability and annual reports. GoCarbonTracker successfully linked 1,670 cited claims across documents.

---

## Critical Gaps for ESG Work

### 1. Framework Mapping is Invisible

**Problem**: No GRI, SASB, TCFD, ESRS, or SEC tags on metrics.

ESG managers live in framework world. We don't think "Scope 1 emissions" - we think "GRI 305-1" or "TCFD Metrics & Targets (a)". Without framework tags, this remains a research tool, not a compliance tool.

**What's needed**:
- Tag each metric with relevant disclosure requirements
  - Example: `scope_1_emissions` → GRI 305-1, SASB various, TCFD Metrics(a), ESRS E1-6
- Framework coverage reports (which requirements are satisfied?)
- Gap analysis per framework (what's missing from TCFD compliance?)

**User story**: "As an ESG manager preparing our GRI content index, I need to see which metrics satisfy which GRI indicators, so I can verify disclosure completeness."

### 2. No Benchmarking

**Problem**: Single-company analysis only.

The value of emissions data isn't the absolute number - it's comparison to peers, industry averages, and historical performance. Right now GoCarbonTracker extracts HelloFresh's data but can't show how it compares to Delivery Hero or Blue Apron.

**What's needed**:
- Multi-company workspaces or federated querying
- Peer comparison tables (HelloFresh vs. food delivery sector)
- Trend analysis across years (is intensity improving?)
- Industry percentile rankings

**User story**: "As an investor, I need to compare HelloFresh's carbon intensity to peer companies in the meal kit sector, so I can assess relative ESG performance."

### 3. Missing Assurance Metadata

**Problem**: No tracking of data quality, verification status, or scope boundaries.

Real ESG work requires distinguishing:
- Third-party verified vs. unverified
- Limited vs. reasonable assurance
- Estimated vs. measured values
- Scope/boundary definitions (operational control vs. equity share)

**What's needed**:
- Assurance status field per claim
- Confidence scoring (rule-based extraction vs. semantic match)
- Methodology tracking (how was this calculated?)
- Boundary/scope metadata

**User story**: "As an auditor, I need to see which emissions figures are third-party verified with reasonable assurance, so I can prioritize verification efforts."

### 4. No Gap Analysis

**Problem**: Tool shows what's present, not what's absent.

ESG managers need to identify:
- What metrics do peers report that we don't?
- What's missing from our TCFD coverage?
- Which frameworks have disclosure gaps?

**What's needed**:
- Expected vs. actual metric coverage by framework
- Peer comparison showing reporting gaps
- Materiality-weighted gap prioritization

**User story**: "As a sustainability director, I need to see which SASB metrics our competitors report that we don't, so I can improve disclosure quality."

### 5. Export Formats

**Problem**: No clear path to get data into ESG workflows.

Can I export to:
- Excel for board decks?
- XBRL for regulatory filing?
- JSON/API for ESG platform integration?
- PDF for GRI content index generation?

If not, data stays locked in the viewer.

**What's needed**:
- CSV/Excel export with full metadata
- Structured JSON API
- Template-based report generation (GRI index, TCFD report)
- Integration hooks for Bloomberg, Sustainalytics, etc.

**User story**: "As an ESG analyst, I need to export matched metrics to Excel with source citations, so I can build investor presentations."

### 6. Sector-Specific Blindness

**Problem**: Generic extraction misses industry context.

Food industry metrics (packaging waste, food waste, supply chain emissions, animal welfare) need different treatment than tech (e-waste, data center energy) or manufacturing (industrial emissions, water usage).

**What's needed**:
- Sector-specific metric libraries (SASB already provides this structure)
- Industry-specific extraction rules
- Contextual validation (does this number make sense for this sector?)

**User story**: "As a food industry ESG manager, I need to track packaging material metrics that are material to my sector but not to tech companies."

---

## Improvement Roadmap

### Phase 1: Make It Useful for ESG Work (3-6 months)

**P0 (Must-Have)**:
1. **Framework tags on metrics**
   - Add GRI, SASB, TCFD, ESRS mappings to metric definitions
   - Generate framework coverage reports

2. **Multi-year comparison**
   - Trend charts for key metrics across years
   - YoY change detection and flagging

3. **Export to CSV/Excel**
   - Include all metadata (source doc, page, bounding box, framework tags)
   - Preserve data lineage

4. **Search functionality**
   - "Show me all Scope 1 emissions across documents"
   - "Find all GRI 305 disclosures"
   - Filter by metric, framework, year, assurance status

**P1 (Should-Have)**:
5. **Assurance status tracking**
   - Manual tagging UI for verified claims
   - Confidence scoring for extracted data

6. **Gap analysis - single company**
   - Expected vs. actual coverage per framework
   - Missing metric identification

### Phase 2: Make It Competitive (6-12 months)

**P0**:
1. **Multi-company workspaces**
   - Peer comparison tables
   - Sector benchmarking
   - Percentile rankings

2. **Sector-specific metric libraries**
   - SASB-aligned industry templates
   - Material metrics by sector

3. **Regulatory compliance checks**
   - CSRD adequacy assessment
   - SEC climate rule coverage
   - Framework-specific validators

**P1**:
4. **Auto-generate compliance artifacts**
   - GRI content index from extracted data
   - TCFD disclosure report
   - SASB/sustainability accounting table

5. **Data lineage visualization**
   - Track how numbers change between reports
   - Flag inconsistencies and restatements
   - Show calculation chains

6. **API for platform integration**
   - Webhook for new extractions
   - REST API for programmatic access
   - Integration templates for major ESG platforms

### Phase 3: Make It Essential (12-24 months)

**P0**:
1. **Multi-stakeholder views**
   - Investor lens (financial materiality)
   - Regulator lens (compliance focus)
   - NGO lens (impact verification)

2. **Greenwashing detection**
   - Claim strength analysis (qualitative vs. quantitative backing)
   - Consistency checking across time
   - Peer comparison for outlier detection

3. **AI-assisted narrative analysis**
   - Are qualitative claims backed by quantitative evidence?
   - Sentiment vs. performance correlation
   - Risk disclosure completeness

**P1**:
4. **Automated materiality assessment**
   - Based on actual reporting patterns
   - Industry benchmarking
   - Stakeholder input integration

5. **Integration with data feeds**
   - CDP, Bloomberg ESG, Sustainalytics
   - Real-time data updates
   - Cross-validation against third-party sources

---

## Testing Insights: HelloFresh Workspace

**Setup**:
- 6 documents (3 sustainability reports + 3 annual reports, 2021-2023)
- 503 pages total
- 9,187 figures extracted

**Results**:
- 7,517 figures matched to bounding boxes (82%)
- 1,670 cited claims across documents (18%)
- 477 figures mapped to 43 canonical metrics
- Match quality high for standardized tables, lower for narrative text

**Observations**:
1. **Extraction quality is strong** for structured disclosures (GRI tables, performance dashboards)
2. **Cross-document linking works** - found same metrics across sustainability and annual reports
3. **Bounding box anchoring is reliable** - UI allows verification of every claim
4. **Semantic filter unavailable** (no torch) but rule-based extraction still effective
5. **Missing context**: No way to know which extracted figures are third-party verified

---

## Recommended Next Steps

### For the Developer

1. **Talk to 3-5 ESG managers** at different company sizes and watch them work for a day. The workflow gaps will become obvious.

2. **Pick one framework to nail** (suggest GRI as it's most universal). Full GRI compliance would make this immediately valuable to hundreds of companies.

3. **Build the comparison feature**. Single-company analysis is table stakes. Multi-company benchmarking is the moat.

4. **Export everything**. ESG data needs to flow into Excel, PowerPoint, XBRL, and ESG platforms. Make integration frictionless.

### For Potential Users

1. **Use it for audit preparation**. The evidence anchoring feature is valuable today, even without framework tags.

2. **Provide feedback on metric coverage**. The 43-metric list should evolve based on real reporting patterns.

3. **Test with your own reports**. See how well it handles your specific disclosure style and sector.

---

## Bottom Line

**Current state**: Strong foundation for ESG evidence management, built by someone who understands data infrastructure better than ESG workflow.

**Key strength**: Evidence anchoring with bounding boxes - genuinely differentiated and valuable.

**Key decision**: 43-metric focus is correct. Quality over quantity wins in data extraction.

**To reach product-market fit**: Add framework alignment, benchmarking, and export capabilities. The technical foundation is solid. The ESG features need to catch up.

**Recommendation**: Partner with an ESG professional to map features to actual compliance workflows. The infrastructure is 80% there. The last 20% is understanding how ESG teams actually work.

---

## Appendix: Technical Details

### Extraction Pipeline Performance
```
read:    503 pages, 14 flagged (4 no_text, 10 sparse_tables)
extract: 9,187 figures total, 54 without bounding box
link:    7,517 matched (82%), 1,670 cited (18%)
infer:   periods and boundaries auto-detected
match:   477 figures → 43 canonical metrics
publish: Version 2 built successfully
```

### Metric Categories (v3 Metric List)
- Emissions (Scope 1, 2, 3)
- Energy (renewable %, total consumption)
- Water (withdrawal, consumption, discharge)
- Waste (generated, recycled, hazardous)
- Social (employees, gender diversity, safety)
- Governance (board composition, ethics training)

### Evidence Anchoring Format
Each claim stored with:
- Source document ID
- Page number
- Bounding box coordinates `[x0, y0, x1, y1]`
- Extracted text
- Matched metric (if applicable)
- Citation links to other mentions

This enables full audit trail from metric → claim → page → physical location in PDF.
