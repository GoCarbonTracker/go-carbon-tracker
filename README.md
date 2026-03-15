# GoCarbonTracker

## AI-Powered Climate Intelligence Platform

**GoCarbonTracker** is a climate intelligence platform that reads corporate sustainability reports, extracts the claims companies make about their emissions, checks those claims against real evidence, and tells you who's actually delivering — and who's greenwashing.

Over **50,000 companies** worldwide now face mandatory emissions reporting under regulations like CSRD, TCFD, and SEC Climate Rules. Most lack any way to verify what their competitors, suppliers, or even their own subsidiaries are actually claiming. GoCarbonTracker is that verification layer.

[![Companies](https://img.shields.io/badge/Companies%20Analyzed-216-blue)]()
[![Data Points](https://img.shields.io/badge/Data%20Points-37,877-green)]()
[![Claims Verified](https://img.shields.io/badge/Claims%20Verified-18,832-orange)]()
[![Evidence Items](https://img.shields.io/badge/Evidence%20Items-1,638,798-purple)]()
[![API Cost](https://img.shields.io/badge/API%20Cost-$0.00-success)]()
[![License](https://img.shields.io/badge/License-Proprietary-lightgrey)]()

---

## Table of Contents

- [The Problem](#the-problem)
- [What We Do](#what-we-do)
- [Proof of Concept: Automotive Industry](#proof-of-concept-automotive-industry)
- [Architecture Overview](#architecture-overview)
- [HyperGraph RAG Engine](#hypergraph-rag-engine)
- [Docling Enrichment Pipeline](#docling-enrichment-pipeline)
- [Discourse Graph](#discourse-graph)
- [Credibility & Greenwashing Scoring](#credibility--greenwashing-scoring)
- [The Platform](#the-platform)
- [See It In Action](#see-it-in-action)
- [Zero API Cost](#zero-api-cost)
- [Current Progress](#current-progress)
- [Roadmap](#roadmap)
- [Get Involved](#get-involved)

---

## The Problem

Corporate sustainability reports are full of bold claims — net-zero targets, emissions reductions, science-based commitments. But who actually checks them?

- Who verifies if BMW's supply chain emissions claims align with what their suppliers report?
- Who catches it when a company says "carbon neutral" but their own data shows rising emissions?
- Who compares 216 companies across a supply chain to find the weak links?

**Nobody — until now.**

---

## What We Do

GoCarbonTracker reads sustainability reports at scale and turns them into structured, verifiable intelligence:

1. **Extract** — We read corporate sustainability PDFs and pull out structured data: emissions numbers, targets, timelines, and commitments
2. **Enrich** — Our Docling pipeline digs deeper into complex documents, extracting data from tables, charts, and visual elements that basic text extraction misses
3. **Analyze** — Our Discourse Graph mines claims from that data, links each claim to supporting and contradicting evidence, and detects inconsistencies
4. **Score** — Every claim gets a credibility score (9 factors) and a greenwashing risk score (5 factors)
5. **Visualize** — Interactive dashboards let you explore supply chains, compare companies, and spot patterns

The entire system runs at **$0 API cost** — no paid AI services, no per-query fees, no cost barriers to scaling.

---

## Proof of Concept: Automotive Industry

We started with the automotive industry because of its deep, complex supply chain and high-profile sustainability promises.

### What We've Analyzed

| Metric | Value |
|--------|-------|
| Companies Analyzed | 216 (OEMs + suppliers across 9 tiers) |
| Data Points Extracted | 37,877 from sustainability reports |
| Claims Verified | 18,832 structured claims |
| Evidence Items | 1,638,798 linking data to claims |
| Contradictions Found | 1,833 cross-claim conflicts |
| Arguments Scored | 14,714 with credibility analysis |

### Supply Chain Depth

Our knowledge base spans the full automotive supply chain:

```
OEMs (BMW, Toyota, Volkswagen, Mercedes-Benz, ...)
  └── Tier 1 — Major systems (Bosch, Continental, Denso, ...)
       └── Tier 2 — Sub-systems and components
            └── Tier 3 — Specialized parts
                 └── Tiers 4-8 — Raw materials, chemicals, mining
```

This lets us trace how emissions claims flow through the supply chain — and where they break down.

### Extraction Depth

| Level | Companies | What It Means |
|-------|-----------|---------------|
| Full Report | 71 | Deep analysis — 100+ data points per company |
| Partial | 22 | Moderate coverage — 21-99 data points |
| Light | 1 | Basic coverage — 6-20 data points |
| Mentioned | 122 | Referenced in other companies' reports |

---

## Architecture Overview

GoCarbonTracker is built as three interconnected layers:

```
┌─────────────────────────────────────────────────────────────────┐
│                     FRONTEND APPLICATIONS                       │
│                                                                 │
│  ┌────────────────┐  ┌─────────────┐  ┌───────────────────┐   │
│  │   Dashboard    │  │   Admin     │  │   Graph Explorer  │   │
│  │  60+ pages     │  │   Panel     │  │  Interactive viz   │   │
│  │  Emissions UI  │  │  KB mgmt   │  │  Supply chain maps │   │
│  └───────┬────────┘  └──────┬──────┘  └────────┬──────────┘   │
│          │                  │                   │               │
└──────────┼──────────────────┼───────────────────┼───────────────┘
           │                  │                   │
     ┌─────┴──────────────────┴───────────────────┴─────┐
     │                  DATABASE LAYER                    │
     │  PostgreSQL + Auth + Realtime + Row-Level Security │
     │  589 companies | Audit trails | Live sync          │
     └──────────────────────┬────────────────────────────┘
                            │
     ┌──────────────────────┴────────────────────────────┐
     │              INTELLIGENCE ENGINE                    │
     │                                                     │
     │  ┌──────────────┐  ┌──────────────┐               │
     │  │ HyperGraph   │  │  Discourse   │               │
     │  │ RAG Engine   │  │    Graph     │               │
     │  │ 37.8K points │  │ 18.8K claims │               │
     │  │ 216 companies│  │ 1.6M evidence│               │
     │  └──────┬───────┘  └──────┬───────┘               │
     │         │                 │                         │
     │         └────────┬────────┘                         │
     │                  │                                  │
     │  ┌───────────────▼──────────────────┐              │
     │  │      Docling Enrichment          │              │
     │  │  Deep PDF extraction layer       │              │
     │  │  Tables, charts, visual elements │              │
     │  └──────────────────────────────────┘              │
     │                                                     │
     │  PDF Extraction → Knowledge Indexing → Claim Mining │
     │  → Evidence Linking → Credibility Scoring           │
     │  → Greenwashing Detection → Comparative Analysis    │
     └─────────────────────────────────────────────────────┘
```

**Data flows bottom-up**: PDF reports are processed by the HyperGraph RAG engine into structured data points. The Docling pipeline enriches these with deeper context from complex document elements. The Discourse Graph then mines claims, links evidence, and scores credibility. This data syncs to the database for persistence and real-time access. Frontend apps query both layers for interactive analysis.

---

## HyperGraph RAG Engine

The core of GoCarbonTracker. A zero-cost retrieval-augmented generation engine purpose-built for ESG intelligence.

### What It Does

The HyperGraph RAG engine reads corporate sustainability reports and transforms them into a searchable, queryable knowledge base — without relying on any paid AI APIs.

```
Corporate Sustainability Reports (PDFs)
         │
         ▼
┌─────────────────────────┐
│  Extraction Layer       │  Reads text, tables, and visual elements
│                         │  4-layer company identity validation
│                         │  Deduplication and quality scoring
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  Knowledge Base         │  37,877 structured data points
│                         │  Searchable by company, topic, tier
│                         │  Hybrid search (semantic + keyword)
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  Query & Analysis       │  Cross-company benchmarking
│                         │  Supply chain tracing
│                         │  Greenwashing risk detection
└─────────────────────────┘
```

### Key Capabilities

- **Hybrid Search** — Combines meaning-based search with keyword matching for accurate results
- **Company Stratification** — Ensures equal representation per company in comparative queries, so no single company dominates results
- **Data-Dense Boosting** — Emissions tables and quantitative data get higher weight than narrative text
- **100% Entity Coverage** — Comparative analyses are validated to include every relevant company, not just the ones that are easy to find
- **Quality-Gated Fallback** — If primary results aren't strong enough, the engine automatically tries alternative search strategies
- **529+ ESG Patterns** — Industry-specific extraction patterns for Scope 1, 2, and 3 emissions data

### Why "HyperGraph"?

Traditional knowledge graphs connect pairs of things: Company A → emits → X tons. A hypergraph connects *groups* of things simultaneously: a single relationship can link a company, its emissions target, the evidence supporting it, the regulatory framework it aligns with, and the supply chain tier it belongs to — all at once. This makes cross-cutting queries (like "show me all Tier 1 suppliers whose Scope 3 claims contradict their OEM's reports") possible in a single lookup.

---

## Docling Enrichment Pipeline

Standard PDF extraction reads text — but sustainability reports pack critical data into tables, charts, infographics, and formatted layouts that text extraction alone misses.

### What Docling Does

The Docling pipeline is our deep extraction layer that goes beyond basic text:

- **Table Extraction** — Reads complex emissions tables with merged cells, multi-level headers, and footnotes
- **Document Structure Awareness** — Understands sections, headings, and how content is organized within a report
- **Context Enrichment** — Adds richer metadata to existing knowledge base entries by extracting surrounding context that basic extraction missed
- **Merge & Enrich** — New Docling-extracted data is intelligently merged with existing knowledge base entries, enriching rather than duplicating

### Impact

Our Docling enrichment has already added **941 enriched contexts** across companies like Ford Motor (252 enriched contexts) and Porsche (131 enriched contexts), bringing deeper quantitative data and table-based evidence into the knowledge base that text-only extraction couldn't capture.

The pipeline is designed to run incrementally — we can enrich one company at a time without rebuilding the entire knowledge base.

---

## Discourse Graph

The Discourse Graph is where raw data becomes intelligence. It transforms extracted report text into structured arguments with credibility scoring and greenwashing detection.

### How It Works

Every claim a company makes gets structured into a verifiable argument:

```
     ┌─────────────────────┐
     │       Claim         │  "BMW targets net-zero by 2050"
     │                     │  Type: net_zero_claims
     │                     │  Credibility: 0.72
     └──────────┬──────────┘
                │
       ┌────────┴────────┐
       │                 │
  ┌────▼─────┐    ┌──────▼──────┐
  │Supporting │    │Contradicting│
  │ Evidence  │    │  Evidence   │
  │    76     │    │      2      │
  └────┬─────┘    └──────┬──────┘
       │                 │
       └────────┬────────┘
                │
       ┌────────▼────────┐
       │    Argument     │  Strength: 98.7%
       │                 │  Verdict: Strong
       │                 │  Greenwashing Risk: 27%
       └─────────────────┘
```

A claim with 76 pieces of supporting evidence and only 2 contradictions? That's a strong argument with low greenwashing risk. A claim with 3 pieces of vague supporting evidence and 12 contradictions? That's a red flag.

### Scale

| Metric | Count |
|--------|-------|
| Claims Extracted | 18,832 |
| Evidence Items | 1,638,798 |
| Arguments Scored | 14,714 |
| Contradictions Detected | 1,833 |
| Companies with Claims | 216 |

### ESG Theme Coverage

The Discourse Graph covers the full spectrum of ESG topics:

- **Environmental** — Emissions targets, energy initiatives, biodiversity, climate risk
- **Social** — Labor practices, supply chain working conditions, community impact
- **Governance** — Board oversight, integrated reporting, shareholder engagement
- **Supply Chain** — Supplier emissions, responsible sourcing, circular economy
- **Integrated ESG** — Cross-cutting sustainability strategies and frameworks

---

## Credibility & Greenwashing Scoring

### Credibility Score (9 Factors)

Each claim is scored on how trustworthy it is:

| What We Check | Example |
|---------------|---------|
| Specific numbers present? | "Reduced by 15%" vs "significantly reduced" |
| Clear baseline and target? | "From 2019 baseline, targeting 2030" vs vague timelines |
| Third-party verification? | External audit or certification referenced? |
| Methodology explained? | How did they measure it? |
| Concrete timelines? | Specific years, not just "by mid-century" |
| Source credibility? | Annual report vs marketing brochure |
| Externally assured? | Independent assurance statement? |
| CDP disclosure aligned? | Consistent with CDP submissions? |
| Regulatory framework aligned? | CSRD, ISSB, TCFD compliant? |

### Greenwashing Risk Score (5 Factors)

| What We Detect | What It Means |
|----------------|---------------|
| Low credibility | The claim itself scores poorly on the factors above |
| Weak evidence | Big claims with little data to back them up |
| Contradictions | Other evidence directly conflicts with this claim |
| No progress shown | Targets announced but no evidence of actual action |
| Vague language | Buzzwords without measurable commitments |

---

## The Platform

### Dashboard
The main application with 60+ pages covering emissions tracking, company profiles, graph visualization (5 modes), supply chain mapping, and cross-company benchmarking.

### Admin Panel
Knowledge base management, system health monitoring, data imports, and tier classification tools.

### Graph Explorer
Interactive visualization portal with multiple rendering modes for exploring company networks, claim relationships, and supply chain structures.

---

## See It In Action

Explore our interactive visualizations — click any link to open in your browser. All are zoomable, pannable, and clickable.

### Supply Chain Maps

| Visualization | What You'll See |
|--------------|-----------------|
| [Full Supply Chain Network](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/automotive-tiers-relationships.html) | Complete tier mapping — OEM to Tier 8, emission flows, data quality indicators |
| [Companies by Tier & Country](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/vyuh_tier_country_all_companies.html) | 216 companies mapped by supply chain position and headquarters |
| [Company Relationships](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/vyuh_format_with_relationships.html) | How companies connect across the supply chain |
| [Tier Breakdown](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/vyuh_tier_separate_all_companies.html) | Companies organized by supply chain level |
| [Global HQ Distribution](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/vyuh_country_hq_kb_companies.html) | Where these 216 companies are headquartered worldwide |

### Energy & Emissions

| Visualization | What You'll See |
|--------------|-----------------|
| [Energy Initiatives Map](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/hypergraph/energy_initiatives_hypergraph.html) | Full map of energy-related claims, evidence, and connections (large file) |
| [Energy Initiatives (Animated)](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/energy_initiatives_animated.html) | Animated view of renewable energy initiatives across OEMs |
| [Energy Network](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/energy_initiatives_vyuh_network.html) | Energy initiatives as an interactive network |

### OEM Deep Dives

| Visualization | What You'll See |
|--------------|-----------------|
| [BMW Supply Chain](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/supply-chain/bmw-supply-chain-visualization.html) | BMW Group's multi-tier supplier network |
| [Mercedes-Benz Supply Chain](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/supply-chain/mercedes-supply-chain-visualization.html) | Mercedes-Benz supplier structure |
| [Ferrari Supply Chain](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/supply-chain/ferrari-supply-chain-visualization.html) | Ferrari's supplier network |

---

## Zero API Cost

Most platforms that analyze sustainability data rely on paid AI services — charging per query, per document, per embedding. These costs add up fast and create barriers for smaller organizations.

**GoCarbonTracker's entire knowledge base — 37,877 data points, 18,832 claims, 1.6M evidence items across 216 companies — was built and is maintained at $0.00 API cost.**

- No paid AI APIs for reading reports
- No per-query fees for searching the knowledge base
- No cost to re-index when new reports are added
- Full rebuild of the entire knowledge base takes under 30 seconds

This means **adding a new industry costs effectively nothing.** When we expand from automotive to energy, finance, or agriculture, the infrastructure cost is the same: zero.

---

## Current Progress

### Built

- 216-company automotive knowledge base at zero API cost
- HyperGraph RAG engine with hybrid search and quality-gated retrieval
- Discourse Graph with 18,832 claims, credibility scoring, and greenwashing detection
- 1.6M+ evidence items linking data to claims
- Docling enrichment pipeline for deep PDF extraction
- 529+ industry-specific extraction patterns
- Interactive graph visualization with 5 modes
- 60+ page dashboard with emissions tracking
- Secure multi-tenant backend with real-time sync
- 4-layer company identity validation
- Supply chain mapping across 9 tiers

### In Progress

- Advanced ESG theme extraction (governance, biodiversity, supply chain labor)
- Expanding Docling enrichment across more companies
- AI agent integration for automated analysis
- Performance optimization (target <2s response time)

### What's Next

- Expand to new industries (energy, finance, agriculture)
- AI-powered insights and recommendations
- Custom report builder for regulatory frameworks (TCFD, SEC, CSRD, CDP)
- Public API for external integrations
- Predictive emissions modeling
- Team collaboration features

---

## Roadmap

```
Phase 1 ✅  Automotive Knowledge Base (216 companies, 37K+ data points)
Phase 2 ✅  Discourse Graph & Credibility Scoring (18.8K claims)
Phase 3 ✅  Interactive Dashboard (60+ pages, 5 visualization modes)
Phase 4 🔄  Docling Enrichment & Advanced ESG Extraction
Phase 5 📋  Multi-Industry Expansion
Phase 6 📋  Public API & Integrations
Phase 7 📋  Predictive Analytics & AI Insights
```

---

## Get Involved

GoCarbonTracker is actively looking for collaborators, especially people with expertise in:

- **Climate Science** — Validating emissions data against scientific sources
- **Sustainability Reporting** — CSRD, TCFD, GRI, CDP domain knowledge
- **Data Analysis** — Pattern recognition across large datasets
- **Graph Analysis** — Network analysis and relationship mapping
- **Frontend Development** — Interactive data visualization

### Interested?

1. **Explore** the visualizations above to see the platform in action
2. **Open an issue** to discuss ideas or share feedback
3. **Reach out** if you'd like to collaborate

---

## About

GoCarbonTracker is built by [Varun Moka](https://github.com/varunmoka7) — a climate tech developer focused on making corporate sustainability data transparent, verifiable, and actionable.

The platform exists because of a simple belief: **if 50,000+ companies must report their emissions, someone needs to verify what they're saying.**

GoCarbonTracker is that verification layer.

---

**Copyright 2025-2026 GoCarbonTracker. All rights reserved.**
