# Zero-Cost RAG — Design Philosophy

## The Problem with Traditional RAG

Most RAG (Retrieval-Augmented Generation) systems rely on expensive external APIs:

| Component | Traditional Approach | Cost at Our Scale |
|-----------|--------------------|--------------------|
| Embeddings | OpenAI text-embedding-3 | ~$15-30 for 37K contexts |
| Re-ranking | Cohere Rerank | ~$5-10 per 1K queries |
| Extraction | GPT-4 for PDF parsing | ~$500+ for 216 reports |
| Updates | Re-embed on every change | Ongoing cost |

For a startup building a knowledge base that needs frequent updates and re-indexing, these costs compound quickly.

## Our Approach: Zero External API Dependency

GoCarbonTracker's entire RAG pipeline runs locally with zero API cost:

```
┌─────────────────────────────────────────────┐
│              ZERO-COST STACK                 │
│                                              │
│  Extraction:  pdfplumber (free, local)       │
│  Embeddings:  TF-IDF via scikit-learn        │
│  Search:      BM25 via rank-bm25             │
│  Indexing:    NumPy + pickle (local files)    │
│  Storage:     JSON files (no database needed) │
│                                              │
│  Total API Cost: $0.00                       │
│  Total Infrastructure: Local Python runtime   │
└─────────────────────────────────────────────┘
```

## Why TF-IDF Works for ESG

TF-IDF (Term Frequency-Inverse Document Frequency) is often dismissed as "old" compared to neural embeddings. But for domain-specific ESG vocabulary, it has significant advantages:

### 1. Domain Vocabulary Matters More Than Semantics

ESG reports use precise terminology: "Scope 3 Category 1", "SBTi validated", "GHG Protocol". These are exact terms, not fuzzy concepts. TF-IDF excels at exact and near-exact matching.

### 2. No Embedding Drift

Neural embeddings can produce surprising similarities (e.g., "carbon neutral" being similar to "carbon tax"). TF-IDF is deterministic — the same terms always produce the same vectors.

### 3. Instant Re-indexing

Adding a new company to the knowledge base takes seconds with TF-IDF. With neural embeddings, you'd need to re-embed and potentially re-train.

### 4. Interpretable Results

With TF-IDF, you can inspect exactly why two contexts matched (which terms contributed to the score). Neural embeddings are black boxes.

## The Hybrid Advantage: BM25 + TF-IDF

Neither BM25 nor TF-IDF alone is sufficient. Together, they cover different retrieval needs:

| Query Type | BM25 Strength | TF-IDF Strength |
|-----------|--------------|-----------------|
| "BMW Scope 3 emissions" | Exact keyword match | Semantic similarity to related contexts |
| "net zero target 2050" | Finds exact phrases | Finds paraphrased targets |
| Comparative queries | Equal per-company results | Quality-weighted ranking |
| Rare terms | High IDF boost for unique terms | Captures term importance in corpus |

## Trade-offs We Accept

| Trade-off | Impact | Mitigation |
|-----------|--------|------------|
| No cross-lingual search | Can't search German reports with English queries | Reports are pre-processed in English |
| No multi-hop reasoning | Can't answer "which supplier of BMW also supplies Toyota?" in one query | Hyperedges connect related contexts |
| No generative answers | Returns contexts, not synthesized answers | Frontend handles synthesis and display |
| Larger index files | ~460 MB vs ~50 MB for neural embeddings | Acceptable for local storage |

## Results

| Metric | Value |
|--------|-------|
| Knowledge Base Size | 37,877 contexts |
| Query Response Time | <3 seconds |
| Total API Cost | $0.00 |
| Re-index Time | ~30 seconds |
| Index Size | ~460 MB |
| Companies Covered | 216 |

The zero-cost approach enables rapid iteration — we can re-extract, re-index, and re-score the entire knowledge base in minutes, not hours, and at no incremental cost.
