# VLM hallucination check on a BRSR report

> Small analysis, run 2026-10-05 on CPU. Every count, rate and timing below is a snapshot from that date, on four pages of one report: a first reading, not a benchmark result. Detected errors are bookmarks for human review, not confirmed findings.

## What this answers

1. When a small vision model reads a sustainability table, how often does it write a number that is not on the page, and what kind of wrong is it?
2. Which checks catch those errors in production, where there is no answer key?

## Test document

Tata Motors, Business Responsibility and Sustainability Report FY2024-25 (NSE filing, 61 pages). Pages 45 (energy, water), 47 (air emissions, Scope 1 and 2), 49 (waste) and 52 (Scope 3 by category).

The PDF is born-digital but its fonts have a broken character map. pdfplumber returns `(cid:NN)` glyph codes for most digits and PyMuPDF returns Greek and Coptic code points (`ϰϯ͕ϳϱϰ` for 43,754). The mapping is one-to-one, so `prepare.py` decodes it into the exact numbers printed on each page without any vision model. That decoded set is the ground truth. Decoded values were checked against the rendered image of page 47.

## Metrics

| Metric | What it counts | Why it matters for GCT |
|---|---|---|
| Unsupported number rate | Numbers a model writes that are not printed on the page, over all numbers it writes | The hallucination rate for emissions data |
| Misread | Unsupported number within two digit edits of a printed one (603,551 read as 603,531) | Plausible, survives sanity checks |
| Fabricated | Unsupported number with no printed number nearby | Invented content or decoding garbage |
| Number recall | Printed numbers that appear in the output | Omission, the silent failure |
| Field accuracy | 22 ESG fields x FY25/FY24 (44 values): is the printed value in the row carrying its label | What the claim layer consumes |
| Wrong value | The labelled row carries a number that is neither year's printed value | Misattribution: real number, wrong row |
| Value without label | The value is present but not in its labelled row | Lost table structure |
| Loop, truncation, empty | Token cap hit, a repeated 40-character chunk, or under 20 characters of output | Degenerate decoding |

Separators are removed before comparing, so 1,31,407, 131,407 and 131407 are one value. Numbers under two digits are ignored on the page-level count (list markers, footnote marks). Coordinate markup (DocTags `<loc_N>`, grounding boxes), HTML attributes, footnote superscripts and the 2 in CO<sub>2</sub> are stripped first.

## Results (2026-10-05, four pages, CPU, greedy decoding)

| Model | Params | Unsupported numbers | Misread | Number recall | Fields correct (of 44) | Wrong value | Gates failed | CPU s/page |
|---|---|---|---|---|---|---|---|---|
| LightOnOCR-2-1B | 1B | 0 of 149 | 0 | 100% | 44 | 0 | 0 of 12 | 332 |
| GLM-OCR | 0.9B | 0 of 131 | 0 | 88% (all misses are page numbers and headers) | 42 | 0 | 0 of 12 | 216 |
| PaddleOCR-VL-1.6 | 0.9B | 0 of 149 | 0 | 100% | 38 | 6 | 2 of 12 | 105 |
| granite-docling-258M | 258M | 4 of 135 (3%) | 4 | 85% | 38 | 1 | 1 failed, 3 not evaluable | 80 |
| pdfplumber (current primary) | n/a | 0 of 55 | 0 | 42% | 1 | 0 | 12 not evaluable | 0 |

Full tables: `results/summary.csv`, `results/fields.csv`, `results/checks.csv`. Every error is a line in `results/ledger.jsonl`.

### What went wrong, by model

granite-docling-258M produced the only true hallucinations, all misreads of real numbers: 603,551 GJ as 603,531; 0.271 MT/vehicle as 0.2171; 0.00008084 kL/$ as 0.0000084; and 0.000005320 tCO2/$ as 0.000050320, a tenfold error in an intensity figure. It also dropped the whole FY24 column from the water-by-source and both waste tables.

PaddleOCR-VL-1.6 wrote every printed number and invented none, yet six field values are wrong. Its water-by-source block shifted up one row: Surface water got Groundwater's values, Groundwater got Third party water's, Third party water got 0. Page-level hallucination counting scores this as perfect, because every number is real. Only row-level checks see it.

GLM-OCR invented nothing and placed every content number correctly. It wrote the page-49 intensity rows (a table continued from the previous page without a header) as plain lines, so two values sit under their label instead of in a table row. It also left out the KPMG assurance sentence on page 47, which matters because assurance status is a claim GCT checks.

LightOnOCR-2-1B was clean on all 44 fields and all gates. It is the slowest here on CPU.

pdfplumber invents nothing but recovers 42% of numbers and 1 of 44 fields on these pages, because of the broken font map. The failure is silent: regex finds nothing and nothing flags it.

### Published hallucination figures, for context

Model makers rarely publish a hallucination rate for document models. The closest published signals: olmOCR-Bench's baseline tests (repeated n-grams, garbage characters), where olmOCR 2 scores 99.7; LightOnOCR's own report of repetition loops falling from 1.14% to 0.50% of generations after RL training; and a 2026 risk-control paper reporting GLM-OCR catastrophic errors (CER of 2 or more) at 1.8 to 3.7 per thousand on scene-text sets. None of these measures misattribution to the wrong row, which was the most common error in this sample.

## The ledger (bookmarks)

`results/ledger.jsonl` has one line per problem: model, page, kind, the value, the nearest printed number or the expected value, the row or surrounding text, and `"review": "open"`. Kinds: `misread_number`, `fabricated_number`, `wrong_field_value`, `unlabelled_value`, `missing_field`, `arithmetic_fail`, `loop_or_truncation`, `empty_output`. On 2026-10-05 it holds 2 GLM-OCR lines, 11 granite-docling, 8 PaddleOCR-VL, 0 LightOnOCR and 43 pdfplumber. A reviewer opens the page, checks the line and sets `review` to `confirmed` or `false_alarm`.

## Proposed extraction process

The sample is small, so this is a process to validate, not a verdict on models.

1. Text-layer health check per page. Count `(cid:NN)` codes and out-of-range code points. A page whose numbers do not decode goes to vision. Known one-to-one ciphers like this one can be decoded directly and used as a free cross-check.
2. Two independent page readers on every numeric table page: GLM-OCR and LightOnOCR-2-1B. On this sample, no field was wrong in both (0 of 44), and GLM-OCR with PaddleOCR-VL also had no shared error.
3. Accept a value only when both readers put the same number in the same labelled row. Disagreements go to the ledger. On this sample, GLM-OCR plus LightOnOCR would have accepted 42 values, all correct, and sent 2 to review.
4. Arithmetic gates (`checks.py`). BRSR tables print their own totals; parts must add up to the printed total within rounding (half a unit per part). This needs no answer key and caught the PaddleOCR-VL row shift and the granite 603,531 misread. A missing part makes the gate "not evaluable", which is itself a flag.
5. Ratio gates, not built yet: an intensity value should equal its numerator over its denominator (Scope 1+2 over revenue, over vehicles produced). That would catch the granite 0.000050320 error, which no sum covers.
6. Human review of the ledger. A reviewer sets `review` to `confirmed` or `false_alarm`. Confirmed lines become the per-model hallucination record across reports.

What to track over time: unsupported number rate where a ground truth exists, gate failure rate, reader disagreement rate, and reviewer-confirmed error rate per model.

## Limits of this run

- One report, four pages, one table style. Charts, scanned pages and multi-column narrative were not tested.
- GLM-OCR and PaddleOCR-VL were run on whole pages. Both are designed to read regions cut out by a separate layout model, which may change their behaviour.
- DeepSeek-OCR 2 and Granite Vision 4.1 4B were not run. DeepSeek-OCR 2's released code needs a GPU; Granite Vision was not attempted on this CPU-only machine. Chart extraction, its main use for GCT, needs a separate test set.
- CPU timings (4 threads, float32) are for comparison only.
- Two harness bugs were found and fixed during the run: granite-docling ships `use_cache=false` (CPU decoding 20x slower), and LightOnOCR loaded through the Auto classes ignores the image. Both are noted in `run_model.py`.

## Running it

```
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install "transformers>=5.18" accelerate pdfplumber pymupdf pillow
python prepare.py                         # download, render, build gold, pdfplumber baseline
python run_model.py glm-ocr-0.9b          # one model, all four pages
python score.py && python checks.py       # results/*.csv and results/ledger.jsonl
```

`prepare.py` needs `pdftoppm` (poppler). The PDF, page images and raw model outputs stay in `work/`, which is not committed.
