# HyperGraph RAG Engine — Architecture Deep Dive

## Overview

The HyperGraph RAG (Retrieval-Augmented Generation) engine is the core intelligence layer of GoCarbonTracker. It transforms unstructured PDF sustainability reports into a structured, queryable knowledge graph — entirely at zero API cost.

Unlike traditional RAG systems that rely on expensive embedding APIs (OpenAI, Cohere), our engine uses local TF-IDF embeddings and BM25 indexing. The entire knowledge base — 37,877 contexts from 216 companies — was built without a single external API call.

---

## System Design

```
                    ┌─────────────────────────────┐
                    │    PDF Sustainability Reports │
                    │    (Corporate annual reports) │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │      EXTRACTION LAYER        │
                    │                              │
                    │  ┌────────┐  ┌────────────┐ │
                    │  │pdfplumb│  │ AI Vision   │ │
                    │  │  er    │──│ (fallback)  │ │
                    │  └────┬───┘  └──────┬─────┘ │
                    │       │             │        │
                    │  ┌────▼─────────────▼─────┐ │
                    │  │  529+ ESG Regex Patterns │ │
                    │  │  Company ID Enforcement  │ │
                    │  │  Quality Flagging         │ │
                    │  └──────────┬───────────────┘ │
                    └─────────────┼─────────────────┘
                                  │
                    ┌─────────────▼─────────────────┐
                    │       INDEXING LAYER            │
                    │                                │
                    │  Context → TF-IDF Embedding    │
                    │  Context → BM25 Index          │
                    │  Context → Entity Extraction   │
                    │  Context → Fact Triple Mining   │
                    │  Context → Hyperedge Creation   │
                    └─────────────┬──────────────────┘
                                  │
                    ┌─────────────▼─────────────────┐
                    │      KNOWLEDGE BASE            │
                    │                                │
                    │  contexts    — 37,877 entries   │
                    │  embeddings  — TF-IDF vectors   │
                    │  bm25_index  — Full-text search  │
                    │  entities    — Named entities    │
                    │  fact_triples — Structured facts │
                    │  hyperedges  — Semantic links    │
                    └─────────────┬──────────────────┘
                                  │
                    ┌─────────────▼─────────────────┐
                    │      DISCOURSE LAYER           │
                    │                                │
                    │  Claims      — 18,832 mined    │
                    │  Evidence    — 1,638,798 links  │
                    │  Arguments   — 14,714 scored    │
                    │  Contradictions — 1,833 found   │
                    └─────────────┬──────────────────┘
                                  │
                    ┌─────────────▼─────────────────┐
                    │      RETRIEVAL ENGINE          │
                    │                                │
                    │  Hybrid BM25 + TF-IDF Search   │
                    │  Company Stratification         │
                    │  Quality-Gated Fallback         │
                    │  100% Entity Coverage Validation│
                    └────────────────────────────────┘
```

---

## Context Data Model

Each extracted context represents a meaningful unit of information from a sustainability report:

```json
{
  "id": "unique_hash",
  "content": "Extracted text from the report...",
  "metadata": {
    "company_id": "bmw",
    "company": "BMW Group",
    "page": 42,
    "tier": "Tier 0",
    "source": "multimodal_extraction",
    "has_emissions_table": true,
    "data_density_score": 0.85,
    "data_state": "value",
    "confidence": 0.92
  }
}
```

**Key design decisions:**
- Company identity is nested in `metadata.company` (not top-level) — allowing rich metadata without schema bloat
- `data_density_score` enables quality-weighted retrieval — emissions tables score higher than narrative text
- `data_state` flags enable filtering: `value` (has numbers), `zero` (zero emissions), `no_data`, `unknown`

---

## Hypergraph Structure

Unlike simple graphs (node → edge → node), our hypergraph uses **hyperedges** that can connect any number of contexts simultaneously. This is critical for ESG analysis where a single claim may span multiple report sections, companies, and time periods.

```
Hyperedge: "BMW Scope 3 Reduction"
  ├── Context A: "BMW reduced Scope 3 by 20%..." (page 42)
  ├── Context B: "Supply chain emissions target..." (page 67)
  ├── Context C: "Bosch reports downstream reduction..." (different company)
  └── Context D: "Industry average Scope 3 is..." (guidance document)
```

This enables:
- **Cross-company analysis**: One hyperedge connecting BMW's claim to Bosch's corroborating data
- **Cross-page synthesis**: Linking related content scattered across a 200-page report
- **Temporal connections**: Connecting baseline year data to target year commitments

---

## Retrieval Design

### Three-Stage Hybrid Search

```
Query: "BMW net zero target"
  │
  ├── Stage 1: TF-IDF Semantic Search
  │   └── Cosine similarity against 37,877 context embeddings
  │
  ├── Stage 2: BM25 Lexical Search
  │   └── Keyword matching with BM25 scoring
  │
  └── Stage 3: Quality-Gated Fallback
      └── If top results score < 0.03 → agentic exploration
```

### Company Stratification

For comparative queries ("Compare BMW vs Mercedes emissions"), the retrieval engine ensures **equal representation**:
- Divides the result budget (K) equally across queried companies
- Prevents dominant companies from overwhelming results
- Validates 100% entity coverage — every queried company must appear

### Data-Dense Boosting

Contexts with emissions tables receive a **2.5x weight boost**, ensuring quantitative data surfaces above narrative text in results.

---

## Why This Design?

| Decision | Rationale |
|----------|-----------|
| TF-IDF over OpenAI embeddings | Zero cost, no API dependency, sufficient for domain-specific ESG vocabulary |
| BM25 + TF-IDF hybrid | BM25 catches exact terms ("Scope 3"), TF-IDF captures semantic similarity |
| Hyperedges over simple edges | ESG claims inherently span multiple documents and companies |
| Quality-gated fallback | Prevents silent failures when primary retrieval misses relevant contexts |
| Company stratification | Ensures fair comparative analysis — no single company dominates results |
| 4-layer company ID validation | Prevents data corruption in a 216-company knowledge base |

---

## Scale Characteristics

| Metric | Value |
|--------|-------|
| Total Contexts | 37,877 |
| Embedding Dimensions | TF-IDF (variable, corpus-dependent) |
| Index Size | ~460 MB (embeddings + BM25) |
| Query Response | <3 seconds average |
| Companies | 216 (automotive supply chain) |
| Extraction Patterns | 529+ ESG-specific regex |
| API Cost | $0.00 |
