# Extraction Pipeline — Architecture Deep Dive

## Overview

The extraction pipeline transforms raw PDF sustainability reports into structured, queryable contexts. It uses a multimodal approach with automatic fallback — starting with lightweight text extraction and escalating to AI vision only when necessary.

---

## Pipeline Stages

```
┌─────────────────────────────────────────┐
│          PDF SUSTAINABILITY REPORT       │
│          (50-300 pages typical)          │
└────────────────────┬────────────────────┘
                     │
        ┌────────────▼────────────┐
        │    1. TEXT EXTRACTION    │
        │    pdfplumber            │
        │    (Primary — free)     │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │    2. TABLE DETECTION   │
        │    pdfplumber tables     │
        │    (Multimodal pass)    │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │    3. AI VISION         │
        │    Gemini/OpenAI        │
        │    (Fallback — complex  │
        │     tables only)        │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │    4. PATTERN MATCHING  │
        │    529+ ESG-specific    │
        │    regex patterns       │
        │    (Scope 1/2/3, SBTi,  │
        │     targets, etc.)      │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │    5. COMPANY ID        │
        │    ENFORCEMENT          │
        │    4-layer validation   │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │    6. QUALITY SCORING   │
        │    Data density, state, │
        │    confidence flags     │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │    7. DEDUPLICATION     │
        │    Content hashing +    │
        │    semantic similarity  │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │    8. CONTEXT CREATION  │
        │    → Knowledge Base     │
        └─────────────────────────┘
```

---

## ESG Pattern Library

The extraction engine includes **529+ regex patterns** specifically designed for ESG data extraction:

### Scope Emissions Patterns

| Category | Pattern Count | Examples |
|----------|--------------|---------|
| Scope 1 Direct | 45+ | CO2 direct emissions, fuel combustion, process emissions |
| Scope 2 Indirect | 40+ | Purchased electricity, market-based, location-based |
| Scope 3 Categories | 90+ | All 15 GHG Protocol categories (purchased goods, transport, investments, etc.) |
| Combined/Total | 30+ | Total GHG, carbon footprint, net emissions |

### Target & Commitment Patterns

| Category | Pattern Count | Examples |
|----------|--------------|---------|
| Net-Zero | 35+ | Carbon neutral, climate neutral, net-zero by [year] |
| SBTi | 25+ | Science-based targets, 1.5°C pathway, SBTi validated |
| Reduction Targets | 50+ | X% reduction by [year], absolute/intensity targets |
| Renewable Energy | 30+ | RE100, 100% renewable, PPA, green certificates |

### Financial & Governance Patterns

| Category | Pattern Count | Examples |
|----------|--------------|---------|
| Carbon Pricing | 20+ | Internal carbon price, shadow price, carbon tax |
| Green Finance | 25+ | Green bonds, sustainability-linked loans, ESG ratings |
| Board Oversight | 15+ | Climate committee, board-level ESG, TCFD governance |

---

## Company ID Enforcement

A 4-layer validation system prevents data corruption across 216 companies:

```
Layer 1: Automatic Fixing
  └── fix_company_id_mismatches.py
      Standardizes variations → canonical underscore format

Layer 2: CI/CD Validation
  └── validate_company_ids.py --strict
      Blocks merges with invalid company IDs

Layer 3: Extraction Pipeline
  └── company_id_enforcer.py
      Real-time enforcement during extraction

Layer 4: Pre-Commit Hook
  └── Validates before code enters repository
```

**Company Registry**: 216 entries in `lowercase_underscore` format. All display names resolved through `get_display_name()` — never `.upper()` on the ID.

---

## Quality Scoring

Each extracted context receives quality metadata:

| Field | Values | Purpose |
|-------|--------|---------|
| `data_density_score` | 0.0 - 1.0 | How information-dense is this context? |
| `data_state` | `value`, `zero`, `no_data`, `unknown` | Does it contain quantitative data? |
| `confidence` | 0.0 - 1.0 | Extraction confidence level |
| `has_emissions_table` | boolean | Contains structured emissions data? |
| `source` | `text`, `multimodal`, `ai_vision`, `regex` | Which extraction method produced this? |

Contexts with `has_emissions_table: true` receive a **2.5x boost** in retrieval scoring, ensuring quantitative data surfaces above narrative text.

---

## Design Principles

| Principle | Rationale |
|-----------|-----------|
| Cheapest first | Start with free pdfplumber, escalate to paid AI vision only when needed |
| Never trust a single method | Multiple extraction passes catch what individual methods miss |
| Quality over quantity | Better to extract 100 high-quality contexts than 1,000 noisy ones |
| Company identity is sacred | 4-layer validation because one wrong company ID corrupts analysis |
| Metadata enables retrieval | Rich metadata (tier, density, state) powers intelligent search |
