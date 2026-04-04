# GoCarbonTracker

## Climate Intelligence Platform

**GoCarbonTracker** is a climate intelligence platform that reads corporate sustainability reports, extracts the claims companies make about their emissions, checks those claims against real evidence, and identifies who's actually delivering — and who's greenwashing.

Over **50,000 companies** worldwide now face mandatory emissions reporting under regulations like CSRD, TCFD, and SEC Climate Rules. Most lack any way to verify what their competitors, suppliers, or even their own subsidiaries are actually claiming. GoCarbonTracker is building that verification layer.

---

## Table of Contents

- [The Problem](#the-problem)
- [What We Do](#what-we-do)
- [What You Can Query](#what-you-can-query)
- [Proof of Concept: Automotive Industry](#proof-of-concept-automotive-industry)
- [Architecture](#architecture)
- [HyperGraph RAG Engine](#hypergraph-rag-engine)
- [Discourse Graph](#discourse-graph)
- [Credibility & Greenwashing Scoring](#credibility--greenwashing-scoring)
- [Compliance Mapping](#compliance-mapping)
- [See It In Action](#see-it-in-action)
- [Roadmap](#roadmap)
- [Get Involved](#get-involved)

---

## The Problem

Corporate sustainability reports are full of bold claims — net-zero targets, emissions reductions, science-based commitments. But who actually checks them?

- Who verifies if a company's supply chain emissions claims align with what their suppliers report?
- Who catches it when a company says "carbon neutral" but their own data shows rising emissions?
- Who compares hundreds of companies across a supply chain to find the weak links?

These are the questions GoCarbonTracker is designed to answer.

---

## What We Do

GoCarbonTracker reads sustainability reports at scale and turns them into structured, verifiable intelligence:

1. **Extract** — Read corporate sustainability PDFs and pull out structured data: emissions numbers, targets, timelines, and commitments
2. **Structure** — Organize extracted data into a hypergraph knowledge base where companies, claims, evidence, regulatory frameworks, and supply chain tiers are connected through rich n-ary relationships
3. **Analyze** — Mine claims, link each to supporting and contradicting evidence, detect inconsistencies across companies and time periods
4. **Score** — Credibility scoring (9 factors) and greenwashing risk detection. A contrastive retrieval model learns which signals best predict claim plausibility
5. **Visualize** — Interactive hypergraph visualizations, supply chain maps, and dashboards to explore companies, compare claims, and spot patterns

---

## What You Can Query

Because the knowledge base is structured as a hypergraph — where each relationship connects multiple dimensions simultaneously — you can ask questions that would be impossible with flat document search or traditional knowledge graphs:

**Supply Chain Intelligence**
- *"Which Tier 1 suppliers claim Scope 3 reductions but have upstream suppliers with increasing emissions?"*
- *"Which suppliers appear in 5+ OEM supply chains and have weak credibility scores?"*
- *"Trace the emissions claims from raw materials through Tier 3 → Tier 1 → OEM for a specific component"*

**Cross-Company Benchmarking**
- *"How does Tata's emissions trajectory compare to BMW's, with supporting evidence from both supply chains?"*
- *"Which companies in the automotive sector have the highest ratio of contradicting evidence to claims?"*
- *"Rank all OEMs by the percentage of their claims that are backed by third-party verification"*

**Greenwashing Detection**
- *"Company A says they source 100% renewable energy — does their supplier's report agree?"*
- *"Find all net-zero commitments that lack a baseline year, methodology, or interim targets"*
- *"Which companies increased their emissions while simultaneously announcing carbon neutrality?"*

**Regulatory Gap Analysis**
- *"Which CSRD E1 datapoints have zero coverage across these 50 companies?"*
- *"Map all Tata claims to their corresponding ESRS disclosure requirements — where are the gaps?"*
- *"Which companies meet TCFD recommendations for climate risk disclosure, and which only partially comply?"*

These queries work because of two things no LLM or general-purpose AI can replicate:

1. **A curated knowledge base built from scratch** — every data point extracted, validated, and structured from hundreds of sustainability reports. LLMs can summarize a single report, but they can't cross-reference a company's Scope 3 claims against what their suppliers actually report — because they don't have the structured relationships between them.

2. **Hypergraph structure** — a single hyperedge connects company + topic + evidence + regulatory framework + supply chain context simultaneously. You don't search documents — you traverse relationships across the entire supply chain.

---

## Proof of Concept: Automotive Industry

We started with the automotive industry because of its deep, complex supply chain and high-profile sustainability promises.

The knowledge base spans the full automotive supply chain — from OEMs through multiple tiers of suppliers down to raw materials:

```
OEMs (BMW, Toyota, Volkswagen, Mercedes-Benz, ...)
  └── Tier 1 — Major systems (Bosch, Continental, Denso, ...)
       └── Tier 2 — Sub-systems and components
            └── Tier 3 — Specialized parts
                 └── Tiers 4-8 — Raw materials, chemicals, mining
```

This lets us trace how emissions claims flow through the supply chain — and where they break down.

---

## Architecture

GoCarbonTracker is built as three interconnected layers:

```
┌─────────────────────────────────────────────────────┐
│                 FRONTEND APPLICATIONS                │
│  Dashboard  |  Admin Panel  |  Graph Explorer        │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│                   DATABASE LAYER                     │
│  PostgreSQL + Auth + Realtime + Row-Level Security   │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│                INTELLIGENCE ENGINE                   │
│                                                      │
│  Extraction Pipeline (Docling + pdfplumber + LLM)    │
│         │                                            │
│         ▼                                            │
│  HyperGraph Knowledge Base (hypergraph-structured)   │
│         │                                            │
│         ├──► Discourse Graph (claims + evidence)     │
│         │         │                                  │
│         │         ▼                                  │
│         │    Credibility & Greenwashing Scoring       │
│         │                                            │
│         └──► Contrastive Retrieval (learned scoring)  │
│                                                      │
│  Compliance Mapping (ESRS/CSRD datapoint ontology)   │
└──────────────────────────────────────────────────────┘
```

**Data flows bottom-up**: PDF reports are processed by the extraction pipeline into structured data points. The HyperGraph knowledge base organizes these into queryable relationships. The Discourse Graph mines claims, links evidence, and scores credibility. The contrastive retrieval model learns which signals best predict claim plausibility. Compliance mapping connects claims to regulatory requirements.

---

## HyperGraph RAG Engine

The core of GoCarbonTracker. A retrieval-augmented generation engine purpose-built for ESG intelligence.

Traditional knowledge graphs connect two nodes per edge — Company A → emits → X tons. But a sustainability claim simultaneously involves a company, a target year, a baseline, a regulatory framework, supporting evidence, and a supply chain context. Splitting this into separate pairwise edges loses the inherent structure.

GoCarbonTracker uses a **domain-specific hypergraph** — where a single hyperedge connects any number of nodes simultaneously. One relationship captures the full context of a claim, instead of fragmenting it across five or six edges. The foundational research behind this approach is detailed in [Luo et al., "HyperGraphRAG" (NeurIPS 2025)](https://arxiv.org/abs/2503.21322).

This structure enables:

- **Smart search** — combines meaning-based and keyword search so you find the right data even when companies use different terminology
- **Fair comparison** — ensures every company gets equal representation in comparative queries, so large companies don't drown out smaller ones
- **Numbers over narrative** — emissions tables and quantitative data are prioritized over marketing language
- **Learned scoring** — a model trained on the knowledge base learns which claims are plausible and which are suspicious, using the structure of the graph itself

---

## Discourse Graph

The Discourse Graph turns structured data into intelligence. It transforms extracted report text into structured arguments with credibility scoring and greenwashing detection.

[Discourse graphs](https://discoursegraphs.com/) are an information model for collaborative knowledge synthesis ([Chan et al., arXiv:2407.20666](https://arxiv.org/abs/2407.20666v2)). The core idea: separate *claims* (what someone asserts) from *evidence* (what supports or contradicts it). Each element can be independently examined, connected, and updated.

We apply this to corporate sustainability. Every claim a company makes — every net-zero target, every emissions reduction assertion — gets extracted as an atomic element. Each claim is linked to supporting and contradicting evidence from across the knowledge base. The ratio between supporting and contradicting evidence, combined with credibility scoring, produces an argument strength assessment and a greenwashing risk score.

```
  ┌──────────────────────────────────────────────────────┐
  │  Claim: "Tata Motors targets net-zero by 2040"       │
  │  Credibility: 0.28  |  Greenwashing Risk: 52%        │
  └──────────────────┬───────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
   ┌────▼──────┐          ┌───────▼───────┐
   │ Supporting │          │ Contradicting │
   │  Evidence  │          │   Evidence    │
   │            │          │               │
   │ • Annual   │          │ • Subsidiary  │
   │   report   │          │   targets     │
   │   2023     │          │   2039, 2045  │
   └────────────┘          └───────────────┘

  Why high risk? Three different net-zero dates
  across Tata parent and divisions — 2039, 2040, 2045.
  The discourse graph catches this automatically.
```

### ESG Theme Coverage

- **Environmental** — Emissions targets, energy initiatives, biodiversity, climate risk
- **Social** — Labor practices, supply chain working conditions, community impact
- **Governance** — Board oversight, integrated reporting, shareholder engagement
- **Supply Chain** — Supplier emissions, responsible sourcing, circular economy

---


## Credibility & Greenwashing Scoring

### Credibility Score (9 Factors)

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

### Greenwashing Risk Detection

| What We Detect | What It Means |
|----------------|---------------|
| Low credibility | The claim scores poorly on the factors above |
| Weak evidence | Big claims with little data to back them up |
| Contradictions | Other evidence directly conflicts with this claim |
| No progress shown | Targets announced but no evidence of actual action |
| Vague language | Buzzwords without measurable commitments |

---

## Compliance Mapping

Sustainability claims don't exist in a vacuum — they correspond to specific regulatory disclosure requirements under frameworks like CSRD, TCFD, GRI, and CDP.

GoCarbonTracker automatically maps extracted claims against these regulatory requirements, surfacing:

- **Disclosure gaps** — which required datapoints a company hasn't addressed
- **Framework coverage** — how completely a company's reporting meets each framework's requirements
- **Cross-framework alignment** — where a single claim satisfies multiple frameworks, and where frameworks conflict

This turns the knowledge base into a compliance intelligence layer — not just "what did the company say?" but "what were they supposed to say, and did they?"

---

## See It In Action

Explore our interactive visualizations — click any link to open in your browser.

### Supply Chain Maps

| Visualization | What You'll See |
|--------------|-----------------|
| [Full Supply Chain Network](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/automotive-tiers-relationships.html) | Complete tier mapping — OEM to Tier 8 |
| [Companies by Tier & Country](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/vyuh_tier_country_all_companies.html) | Companies mapped by supply chain position and headquarters |
| [Company Relationships](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/vyuh/vyuh_format_with_relationships.html) | How companies connect across the supply chain |

### OEM Deep Dives

Tata Motors is our deepest case study — with the most extensive extraction and enrichment coverage. BMW, Mercedes-Benz, and Ferrari demonstrate breadth across different OEMs with lighter coverage.

| Visualization | Coverage | What You'll See |
|--------------|----------|-----------------|
| [Tata Motors Hypergraph](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/supply-chain/tata-supply-chain-visualization.html) | Deep | Supply chain + hypergraph claims view with interactive hull regions |
| [BMW Supply Chain](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/supply-chain/bmw-supply-chain-visualization.html) | Standard | BMW Group's multi-tier supplier network |
| [Mercedes-Benz Supply Chain](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/supply-chain/mercedes-supply-chain-visualization.html) | Standard | Mercedes-Benz supplier structure |
| [Ferrari Supply Chain](https://gocarbontracker.github.io/go-carbon-tracker/visualizations/supply-chain/ferrari-supply-chain-visualization.html) | Standard | Ferrari's supplier network |

---

## Roadmap

```
Phase 1 ✅  Automotive Knowledge Base
Phase 2 ✅  Discourse Graph & Credibility Scoring
Phase 3 ✅  Interactive Dashboard & Visualizations
Phase 4 🔄  Deep Extraction Pipeline (Docling + table-aware + LLM fallback)
Phase 5 🔄  ESRS Compliance Intelligence (regulatory datapoint mapping)
Phase 6 📋  Multi-Industry Expansion
Phase 7 📋  Public API & Integrations
```

---


## Get Involved

GoCarbonTracker is looking for collaborators with expertise in:

- **Sustainability Reporting** — CSRD, TCFD, GRI, CDP domain knowledge
- **Climate Science** — Validating emissions data against scientific sources
- **Graph/Network Analysis** — Relationship mapping and community detection
- **Data Visualization** — Interactive visualization of complex datasets

**Interested?** [Open an issue](https://github.com/GoCarbonTracker/go-carbon-tracker/issues) or reach out directly.

---

Built by [Varun](https://github.com/varunmoka7)

**Copyright 2025-2026 GoCarbonTracker. All rights reserved.**
