# GoCarbonTracker

## AI-Powered Climate Intelligence Platform

**GoCarbonTracker** is a climate intelligence platform that extracts, analyzes, and scores sustainability claims from corporate reports at scale. It combines a **HyperGraph RAG engine** with a **Discourse Graph** to detect greenwashing, score credibility, and enable cross-company benchmarking — all at zero API cost.

The platform exists because **50,000+ companies** now face mandatory emissions reporting under CSRD, TCFD, SEC Climate Rule, and other frameworks. Most lack the tools to validate claims, compare against peers, or detect inconsistencies across their supply chain.

GoCarbonTracker solves this by building a knowledge graph that connects raw report data to structured claims, evidence, and credibility scores.

[![Companies](https://img.shields.io/badge/KB%20Companies-216-blue)]()
[![Contexts](https://img.shields.io/badge/Contexts-37,877-green)]()
[![Claims](https://img.shields.io/badge/Discourse%20Claims-18,832-orange)]()
[![Evidence](https://img.shields.io/badge/Evidence-1,638,798-purple)]()
[![API Cost](https://img.shields.io/badge/API%20Cost-$0.00-success)]()
[![License](https://img.shields.io/badge/License-Proprietary-lightgrey)]()

---

## Table of Contents

- [Vision](#vision)
- [Proof of Concept: Automotive Industry](#proof-of-concept-automotive-industry)
- [Architecture Overview](#architecture-overview)
- [HyperGraph RAG Engine](#hypergraph-rag-engine)
- [Discourse Graph System](#discourse-graph-system)
- [Frontend Applications](#frontend-applications)
- [Visualizations](#visualizations)
- [Tech Stack](#tech-stack)
- [Current Progress](#current-progress)
- [Roadmap](#roadmap)
- [Contributing](#contributing)

---

## Vision

GoCarbonTracker aims to become the **leading emissions intelligence platform** for the 50,000+ companies facing mandatory climate reporting worldwide.

**The core insight**: Corporate sustainability reports are full of claims — net-zero targets, emissions reductions, SBTi commitments. But who verifies them? Who checks if BMW's Scope 3 claims align with their suppliers' reports? Who detects when a company's "carbon neutral" claim contradicts their own emissions data?

**Our approach**:
1. **Extract** — Pull structured data from PDF sustainability reports using multimodal extraction (text, tables, images)
2. **Index** — Build a searchable knowledge base with rich metadata and quality scores
3. **Analyze** — Mine claims, link evidence, detect contradictions, score credibility
4. **Visualize** — Interactive dashboards for cross-company benchmarking and greenwashing detection

**The platform is industry-agnostic by design.** The HyperGraph RAG engine and Discourse Graph can be applied to any sector — energy, finance, agriculture, mining. We started with automotive as our proof of concept.

---

## Proof of Concept: Automotive Industry

We chose the automotive industry as our first vertical because of its complex, multi-tier supply chain and high-profile sustainability commitments.

### Current Scale

| Metric | Value |
|--------|-------|
| Companies Analyzed | 216 (OEMs, Tier 1-8 suppliers) |
| Extracted Contexts | 37,877 from sustainability reports |
| Discourse Claims | 18,832 structured claims |
| Evidence Items | 1,638,798 linking contexts to claims |
| Contradictions Detected | 1,833 cross-claim conflicts |
| Arguments Scored | 14,714 with credibility analysis |
| API Cost | $0.00 (zero external API dependency) |

### Extraction Coverage

| Level | Companies | Description |
|-------|-----------|-------------|
| Full Report | 71 | 100+ contexts extracted per company |
| Partial | 22 | 21-99 contexts |
| Light | 1 | 6-20 contexts |
| Mention Only | 122 | 1-5 contexts (referenced in other reports) |

### Supply Chain Tiers

The automotive knowledge base spans the full supply chain hierarchy:

```
Tier 0 — OEMs (BMW, Toyota, Volkswagen, Mercedes-Benz, ...)
  └── Tier 1 — Major systems suppliers (Bosch, Continental, Denso, ...)
       └── Tier 2 — Sub-system and component suppliers
            └── Tier 3 — Specialized component manufacturers
                 └── Tier 4-8 — Raw materials, chemicals, mining
```

Each tier has unique sustainability reporting patterns, allowing cross-tier analysis of how emissions claims flow through the supply chain.

---

## Architecture Overview

GoCarbonTracker is built as three interconnected layers:

```
┌─────────────────────────────────────────────────────────────────┐
│                     FRONTEND APPLICATIONS                       │
│                                                                 │
│  ┌────────────────┐  ┌─────────────┐  ┌───────────────────┐   │
│  │   Dashboard    │  │   Admin     │  │  HyperGraph Viz   │   │
│  │  60+ pages     │  │   Panel     │  │   Graph explorer   │   │
│  │  Graph modes   │  │  DB mgmt    │  │   100+ viz types  │   │
│  │  Emissions UI  │  │  Monitoring │  │   OEM alignment   │   │
│  └───────┬────────┘  └──────┬──────┘  └────────┬──────────┘   │
│          │                  │                   │               │
└──────────┼──────────────────┼───────────────────┼───────────────┘
           │                  │                   │
     ┌─────┴──────────────────┴───────────────────┴─────┐
     │                  SUPABASE LAYER                    │
     │  PostgreSQL + Auth + Realtime + RLS               │
     │  589 companies | Audit trails | WebSocket sync    │
     └──────────────────────┬────────────────────────────┘
                            │
     ┌──────────────────────┴────────────────────────────┐
     │              HYPERGRAPH RAG ENGINE                  │
     │                                                     │
     │  ┌──────────┐  ┌──────────────┐  ┌──────────────┐ │
     │  │ Knowledge │  │  Discourse   │  │  Retrieval   │ │
     │  │   Base    │  │    Graph     │  │   Engine     │ │
     │  │ 37.8K ctx │  │ 18.8K claims │  │ Hybrid BM25  │ │
     │  │ 216 co.   │  │ 1.6M evid.  │  │ + TF-IDF     │ │
     │  └──────────┘  └──────────────┘  └──────────────┘ │
     │                                                     │
     │  PDF Extraction → Context Indexing → Claim Mining   │
     │  → Evidence Linking → Credibility Scoring           │
     │  → Greenwashing Detection → Comparative Analysis    │
     └─────────────────────────────────────────────────────┘
```

**Data flows bottom-up**: PDF reports are processed by the HyperGraph RAG engine into structured contexts, claims, and evidence. This data syncs to Supabase for persistence and real-time access. Frontend apps query both layers for interactive analysis.

---

## HyperGraph RAG Engine

The flagship component. A zero-cost RAG pipeline purpose-built for ESG intelligence.

### How It Works

```
PDF Sustainability Reports
         │
         ▼
┌─────────────────────┐
│  Extraction Layer   │  pdfplumber → multimodal → AI vision → regex
│                     │  Company ID enforcement (4-layer validation)
│                     │  Deduplication and quality flagging
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Knowledge Base     │  37,877 contexts with rich metadata
│                     │  TF-IDF embeddings (zero cost)
│                     │  BM25 full-text index
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Discourse Graph    │  18,832 claims extracted
│                     │  1,638,798 evidence links
│                     │  14,714 arguments scored
│                     │  1,833 contradictions detected
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Query & Analysis   │  Hybrid retrieval (BM25 + TF-IDF)
│                     │  Cross-company benchmarking
│                     │  Greenwashing risk scoring
└─────────────────────┘
```

### Extraction Pipeline

Reports go through a multimodal extraction chain with automatic fallback:

- **Primary**: pdfplumber (text extraction)
- **Fallback**: pdfplumber multimodal (text + tables)
- **Fallback**: AI vision (for complex tables)
- **Legacy**: 529+ ESG-specific regex patterns for Scope 1/2/3 emissions

Each extracted context includes content text, company metadata, page references, tier classification, extraction method, and data density scoring.

### Retrieval System

Three-stage hybrid retrieval with quality gates:

1. **Semantic Search** — TF-IDF vectorizer + cosine similarity
2. **Lexical Search** — BM25 full-text index for keyword matching
3. **Quality-Gated Fallback** — If primary results score below threshold, falls back to agentic exploration

**Key features:**
- Company stratification: equal results per company in comparative queries
- Data-dense context boosting: emissions tables get 2.5x weight
- 100% entity coverage validation for comparative analysis
- Metadata filtering by tier, source, data density, entity level

### Why Zero Cost?

Most RAG systems depend on expensive embedding APIs (OpenAI, Cohere). GoCarbonTracker uses:
- **TF-IDF embeddings** via scikit-learn (free, local)
- **BM25** for keyword search (free, local)
- **pdfplumber** for PDF extraction (free, local)

The entire knowledge base — 37,877 contexts, 18,832 claims, 1.6M evidence items — was built at **$0.00 API cost**.

---

## Discourse Graph System

The discourse graph transforms raw report text into structured arguments with credibility scoring and greenwashing detection.

### Data Model

```
     ┌─────────────┐
     │    Claim     │  "BMW targets net-zero by 2050"
     │              │  Type: net_zero_claims
     │              │  Credibility: 0.72
     └──────┬──────┘
            │
    ┌───────┴───────┐
    │               │
┌───▼───┐     ┌────▼────┐
│Support│     │Contradict│
│Evidence│    │Evidence  │
│  76    │    │   2      │
└───┬───┘     └────┬────┘
    │              │
    └──────┬───────┘
           │
     ┌─────▼─────┐
     │  Argument  │  Strength: 98.7%
     │            │  Verdict: Strong
     │            │  Greenwashing Risk: 27% (Low)
     └────────────┘
```

### Credibility Scoring (9 Factors)

Each claim is scored across nine credibility dimensions:

| Factor | What It Measures |
|--------|-----------------|
| Quantitative Presence | Are there specific numbers and metrics? |
| Baseline Target Clarity | Is the baseline year and target clearly defined? |
| Verification Indicators | Third-party verification or audit evidence? |
| Methodology Disclosure | Is the measurement methodology explained? |
| Temporal Specificity | Are timelines concrete (not vague "by 2050")? |
| Source Authority | Quality of the reporting source? |
| Assured | Has the data been externally assured? |
| CDP Verified | CDP disclosure alignment? |
| CSRD/ISSB | Alignment with regulatory frameworks? |

### Greenwashing Risk Assessment (5 Factors)

| Factor | What It Detects |
|--------|----------------|
| Credibility Risk | Low credibility score on the underlying claim |
| Evidence Ratio Risk | Too little supporting evidence relative to claim strength |
| Contradictions Risk | Other evidence contradicts this claim |
| Progress Risk | Claims without evidence of actual progress |
| Specificity Risk | Vague language without measurable commitments |

### Scale

| Metric | Count |
|--------|-------|
| Claims Extracted | 18,832 |
| Evidence Items | 1,638,798 |
| Arguments Scored | 14,714 |
| Contradictions Detected | 1,833 |
| Companies with Claims | 216 |

---

## Frontend Applications

### Dashboard (60+ Pages)

The primary user-facing application covering emissions tracking, graph visualization, and company analysis.

**Key features:**
- **Emissions Intelligence** — Scope 1/2/3 breakdown and trend analysis
- **Company Profiles** — Individual company deep dives with claim analysis
- **Graph Visualization** — 5 modes: Automotive, Discourse, Supply Chain, Workbench, Presentation
- **Automotive Hub** — Supply chain tier management (OEM through Tier 8)
- **HyperGraph Explorer** — Interactive knowledge base visualization
- **Comparative Analysis** — Cross-company benchmarking with 100% entity coverage

### Graph Visualization Modes

| Mode | Purpose |
|------|---------|
| Automotive | Companies, emissions targets, SBTi validation status |
| Discourse | Argument graphs with claims, evidence, and credibility |
| Supply Chain | Tier-based supplier relationships (OEM → T1 → ... → T8) |
| Workbench | Advanced filtering and power user tools |
| Presentation | Interactive demo scenarios |

### Admin Panel

- Knowledge base context management and query interface
- Tier management (0-8 automotive supply chain tiers)
- System health monitoring and diagnostics
- Data integration and company imports

### HyperGraph Visualization Portal

- Dedicated graph visualization with 100+ visualization types
- 10+ categories with color-coded filtering
- OEM sustainability alignment dashboard
- Multiple rendering engines: AntV G6, Plotly.js 3D, ReactFlow, Cytoscape.js

---

## Visualizations

Click any link below to explore live in your browser — all interactive, zoomable, and filterable.

### Vyuh Network Diagrams — Automotive Supply Chain Mapping

| Visualization | What You'll See |
|--------------|-----------------|
| [Supply Chain Tier Relationships](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/automotive-tiers-relationships.html) | Complete tier mapping — OEM to Tier 8, emission flows, data quality indicators |
| [Tier & Country Network](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/vyuh_tier_country_all_companies.html) | 216 companies mapped by supply chain tier and country of headquarters |
| [Company Relationships](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/vyuh_format_with_relationships.html) | Inter-company relationship network across the supply chain |
| [Tier Breakdown](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/vyuh_tier_separate_all_companies.html) | Companies organized by supply chain tier (OEM → T1 → T2 → ... → T8) |
| [Country HQ Distribution](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/vyuh_country_hq_kb_companies.html) | Geographic distribution of KB companies by headquarters |

### Hypergraph & Energy Visualizations

| Visualization | What You'll See |
|--------------|-----------------|
| [Energy Initiatives Hypergraph](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/hypergraph/energy_initiatives_hypergraph.html) | Full hypergraph of energy-related claims, evidence, and connections (4.6 MB) |
| [Energy Initiatives (Animated)](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/energy_initiatives_animated.html) | Animated network of renewable energy initiatives across OEMs |
| [Energy Network Graph](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/energy_initiatives_vyuh_network.html) | Energy initiatives mapped as an interactive network |

### OEM Supply Chain Deep Dives

| Visualization | What You'll See |
|--------------|-----------------|
| [BMW Supply Chain](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/supply-chain/bmw-supply-chain-visualization.html) | BMW Group's multi-tier supplier network |
| [Mercedes-Benz Supply Chain](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/supply-chain/mercedes-supply-chain-visualization.html) | Mercedes-Benz supplier tier structure |
| [Ferrari Supply Chain](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/supply-chain/ferrari-supply-chain-visualization.html) | Ferrari's supplier network |

> All visualizations are generated from our HyperGraph knowledge base. Zoom, pan, click nodes, and explore.

---

## Tech Stack

### Frontend
| Technology | Purpose |
|-----------|---------|
| React 18 | UI framework (strict mode) |
| TypeScript | Type safety across all apps |
| Vite | Build tool (<3s HMR) |
| Turborepo | Monorepo build orchestration |
| TanStack Query | Data fetching and caching |
| shadcn/ui + Radix | Accessible component primitives |
| Tailwind CSS | Utility-first styling |

### Visualization
| Technology | Purpose |
|-----------|---------|
| Cytoscape.js | 2D interactive graphs (primary) |
| Force-Graph-3D | 3D supply chain visualization |
| D3.js | Data transformations |
| AntV G6 / Graphin | Advanced graph visualization |
| Recharts | Charts (bar, line, pie, area) |
| Plotly.js | 3D particle systems |

### Backend & Data
| Technology | Purpose |
|-----------|---------|
| Supabase | PostgreSQL + Auth + Realtime + Storage |
| Row Level Security | Multi-tenant data isolation |
| Python 3 | HyperGraph RAG engine |
| scikit-learn | TF-IDF embeddings (zero cost) |
| pdfplumber | PDF text and table extraction |
| BM25 (rank-bm25) | Full-text keyword search |

### DevOps
| Technology | Purpose |
|-----------|---------|
| Vercel | Deployment platform |
| GitHub Actions | CI/CD pipelines |
| Sentry | Error tracking |
| Turborepo | Parallel cached builds |

---

## Current Progress

### What's Built

- 216-company automotive knowledge base at zero API cost
- 18,832 discourse claims with credibility scoring and greenwashing detection
- 1.6M+ evidence items linking contexts to claims
- Hybrid retrieval engine (BM25 + TF-IDF) with quality-gated fallback
- Multimodal PDF extraction pipeline (text + tables + AI vision)
- 529+ ESG-specific extraction patterns
- Interactive graph visualization with 5 modes
- 60+ page dashboard with emissions tracking and company profiles
- Multi-tenant Supabase backend with RLS and real-time sync
- 4-layer company ID validation system
- Supply chain mapping across 9 automotive tiers

### In Progress

- Discourse Phase 13-17 extraction (advanced ESG themes: governance, biodiversity, supply chain labor)
- Docling-based enrichment pipeline for deeper PDF context extraction
- MCP server for AI agent integration with HyperGraph RAG
- Performance optimization (target <2s query response)

### What's Next

- Expand beyond automotive to multi-industry coverage
- AI-powered insights with automated recommendations
- Custom report builder for TCFD, SEC, CSRD, CDP templates
- Public API (RESTful + GraphQL) for external integrations
- Predictive emissions modeling and trend analysis
- Collaboration features with team workspaces

---

## Roadmap

```
Phase 1 ✅  Automotive KB (216 companies, 37K+ contexts)
Phase 2 ✅  Discourse Graph (18.8K claims, credibility scoring)
Phase 3 ✅  Frontend Dashboard (60+ pages, 5 graph modes)
Phase 4 🔄  Advanced Extraction (Docling enrichment, Phase 13-17)
Phase 5 📋  Multi-Industry Expansion (energy, finance, agriculture)
Phase 6 📋  Public API & Integrations
Phase 7 📋  Predictive Analytics & AI Insights
```

---

## Contributing

GoCarbonTracker is actively looking for collaborators, especially in:

- **Graph Theory & Data Structures** — Optimizing hypergraph operations and traversal
- **NLP & Information Extraction** — Improving claim extraction accuracy
- **Climate Science** — Validating emissions data against scientific sources
- **Frontend Engineering** — React, TypeScript, graph visualization
- **Data Engineering** — Scaling the extraction pipeline to new industries

### How to Get Involved

1. **Explore** the architecture docs and visualizations in this repo
2. **Open an issue** to discuss ideas or improvements
3. **Reach out** if you're interested in contributing to the platform

### Development Standards

- TypeScript strict mode — no implicit any
- WCAG 2.1 AA accessibility compliance
- Multi-tenant isolation via Row Level Security
- Climate data validated against NOAA, NASA, IPCC sources
- 100% entity coverage required for comparative queries

---

## About

GoCarbonTracker is built by [Varun Moka](https://github.com/varunmoka7) — a climate tech developer focused on making corporate sustainability data transparent, verifiable, and actionable.

The platform is driven by a simple belief: **if 50,000+ companies must report emissions, someone needs to verify what they're saying.** GoCarbonTracker is that verification layer.

---

**Copyright 2025-2026 GoCarbonTracker. All rights reserved.**

*Last Updated: March 2026*
