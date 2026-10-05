# VLM hallucination check on a BRSR report

> Small analysis, run 2026-10-05 on CPU. Four pages of one report, so treat every rate below as a first reading, not a benchmark. Detected errors are bookmarks for human review, not confirmed findings.

## Why this exists

The extraction pipeline escalates hard pages to a vision model. A vision model can return a number that is not on the page, and in an emissions database that is the most expensive error there is: it looks like data, it passes regex, and it can produce a false contradiction or hide a real one. This harness measures how often each candidate model does that, and writes every suspect number to a ledger a reviewer can work through.

## Test document

Tata Motors, Business Responsibility and Sustainability Report FY2024-25 (NSE filing, 61 pages). Pages 45 (energy, water), 47 (air emissions, Scope 1 and 2), 49 (waste) and 52 (Scope 3 by category).

The PDF is born-digital but its fonts have a broken character map. pdfplumber returns `(cid:NN)` glyph codes for most digits, and PyMuPDF returns Greek and Coptic code points (`ϰϯ͕ϳϱϰ` for 43,754). The mapping is one-to-one, so `prepare.py` decodes it. That gives the exact numbers printed on each page without using any vision model, and it is the ground truth everything is scored against. Decoded values were checked against the rendered page for page 47.

## Metrics

| Metric | What it counts | Why it matters for GCT |
|---|---|---|
| Unsupported number rate | Numbers a model writes that are not printed on the page, divided by all numbers it writes | The hallucination rate that matters for emissions data |
| Misread | Unsupported number one digit edit from a real one (43,754 read as 43,154) | Plausible, hard to spot, survives sanity checks |
| Fabricated | Unsupported number with no close real number | Invented content or decoding garbage |
| Number recall | Printed numbers that appear in the output | Omission: the silent failure mode |
| Field accuracy | 20 ESG fields x FY25/FY24: is the printed value in the row with the right label | What the regex and claim layer actually consume |
| Wrong value | The labelled row exists but carries a number that is neither year's printed value | Misattribution: right row, wrong number |
| Value without label | The number appears but not in a row with its label | Table structure lost; the source of the fragmented-row artifacts in the Tata review |
| Loop or truncation | Output hit the token cap or repeated a 40-character chunk 4+ times | Small VLMs loop on dense tables |

Numbers are compared after removing separators, so 1,31,407, 131,407 and 131407 are the same value. Numbers with fewer than two digits are ignored because list markers and footnote numbers dominate them. Markup that carries coordinates (DocTags `<loc_N>`, grounding boxes, HTML attributes) is stripped before counting.

## The ledger

`results/ledger.jsonl` has one line per suspect: model, page, kind, the value, the nearest real number, surrounding text, and `"review": "open"`. A reviewer opens the page, checks the value, and sets `review` to `confirmed` or `false_alarm`. Confirmed rows are the hallucination record over time; false alarms show where the scorer needs work.

## Running it

```
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install "transformers>=5.18" accelerate pdfplumber pymupdf pillow
python prepare.py                         # download, render, build gold, pdfplumber baseline
python run_model.py glm-ocr-0.9b          # one model, all four pages
python score.py                           # results/summary.csv, fields.csv, ledger.jsonl
```

`prepare.py` needs `pdftoppm` (poppler). The PDF and rendered pages go to `work/`, which is not committed.
