"""Score model outputs against the gold sets and write the hallucination ledger.

Two levels:
  page level   every number (2+ digits) a model writes is checked against the
               numbers printed on that page. Numbers not on the page are
               unsupported: either a misread (one digit edit away from a real
               number) or a fabrication (no close match).
  field level  20 ESG fields x FY25/FY24. The model's row for the field label is
               found and its value compared with the printed value.

Outputs: results/summary.csv, results/fields.csv, results/ledger.jsonl.
Every ledger line is one bookmark a reviewer can open, check against the page,
and mark confirmed or false_alarm.
"""
import csv
import json
import pathlib
import re
from collections import Counter

from prepare import numbers

HERE = pathlib.Path(__file__).parent
OUT = HERE / "work" / "out"
RES = HERE / "results"
GOLD_PAGES = json.loads((HERE / "gold" / "page_numbers.json").read_text())
GOLD_FIELDS = json.loads((HERE / "gold" / "fields.json").read_text())


def clean(text: str) -> str:
    """Strip markup that carries numbers which are not page content:
    DocTags <loc_N> boxes, HTML attributes, grounding coordinates."""
    text = re.sub(r"<loc_\d+>", " ", text)
    text = re.sub(r"\(cid:\d+\)", "�", text)  # pdfplumber glyph ids for unmapped characters
    text = re.sub(r"\[\[[\d,\s]+\]\]", " ", text)
    text = re.sub(r"<(/?)([a-z_]+)[^>]*>", r" <\1\2> ", text)
    text = re.sub(r"<\|[^|]*\|>|<end_of_utterance>|</?s>", " ", text)
    return text


def rows(text: str) -> list[str]:
    text = re.sub(r"<(/tr|nl|br)>", "\n", text)
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r)).lower().strip() for r in text.split("\n")]


def one_edit(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    s, l = sorted((a, b), key=len)
    return any(l[:i] + l[i + 1:] == s for i in range(len(l)))


def looped(text: str) -> bool:
    """A 40-char chunk repeated 4+ times back to back is a decoding loop."""
    return re.search(r"(.{40,}?)\1{3,}", text, re.S) is not None


def context(text: str, needle: str, width: int = 70) -> str:
    i = text.replace(",", "").find(needle)
    flat = text.replace(",", "")
    return re.sub(r"\s+", " ", flat[max(0, i - width): i + len(needle) + width]) if i >= 0 else ""


def main():
    RES.mkdir(exist_ok=True)
    summary, field_rows, ledger = [], [], []
    for model_dir in sorted(p for p in OUT.iterdir() if p.is_dir()):
        model = model_dir.name
        tot = Counter()
        for page_s, gold in GOLD_PAGES.items():
            f = model_dir / f"p{page_s}.txt"
            if not f.exists():
                continue
            page = int(page_s)
            meta = json.loads((model_dir / f"p{page}.json").read_text()) if (model_dir / f"p{page}.json").exists() else {}
            raw = f.read_text()
            text = clean(raw)
            gold_set = set(gold["numbers"])
            out_nums = numbers(text)
            tot["pages"] += 1
            tot["seconds"] += meta.get("seconds", 0)
            tot["out_numbers"] += len(out_nums)
            tot["gold_numbers"] += len(gold_set)
            tot["recalled"] += len(gold_set & set(out_nums))
            if meta.get("hit_token_cap") or looped(raw):
                tot["loops"] += 1
                ledger.append({"model": model, "page": page, "kind": "loop_or_truncation",
                               "detail": f"new_tokens={meta.get('new_tokens')}", "review": "open"})
            for n in out_nums:
                if n in gold_set:
                    continue
                near = next((g for g in gold_set if one_edit(n, g)), None)
                kind = "misread_number" if near else "fabricated_number"
                tot[kind] += 1
                ledger.append({"model": model, "page": page, "kind": kind, "value": n, "nearest_gold": near,
                               "context": context(text, n), "review": "open"})
            # field level
            rws = rows(text)
            for fld in (x for x in GOLD_FIELDS if x["page"] == page):
                cands = [r for r in rws if all(k in r for k in fld["row_has"])
                         and not any(k in r for k in fld.get("row_not", []))]
                for year in ("fy25", "fy24"):
                    want = fld[year]
                    if any(want in numbers(r) for r in cands):
                        status = "correct"
                    elif cands and any(set(numbers(r)) - {fld["fy25"], fld["fy24"]} for r in cands):
                        # the labelled row carries a number that is neither year's printed value
                        status = "wrong_value"
                    elif want in out_nums:
                        status = "value_without_label"
                    else:
                        status = "missing"
                    tot["field_" + status] += 1
                    field_rows.append({"model": model, "field": fld["id"], "year": year, "gold": want,
                                       "status": status, "row": cands[0][:160] if cands else ""})
                    if status == "wrong_value":
                        ledger.append({"model": model, "page": page, "kind": "wrong_field_value",
                                       "field": fld["id"], "year": year, "gold": want,
                                       "row": cands[0][:200], "review": "open"})
        if not tot["pages"]:
            continue
        unsupported = tot["misread_number"] + tot["fabricated_number"]
        fields = sum(v for k, v in tot.items() if k.startswith("field_"))
        summary.append({
            "model": model, "pages": tot["pages"],
            "sec_per_page_cpu": round(tot["seconds"] / tot["pages"]),
            "numbers_written": tot["out_numbers"],
            "unsupported_rate": round(unsupported / max(tot["out_numbers"], 1), 3),
            "misread": tot["misread_number"], "fabricated": tot["fabricated_number"],
            "number_recall": round(tot["recalled"] / tot["gold_numbers"], 3),
            "field_accuracy": round(tot["field_correct"] / max(fields, 1), 3),
            "field_wrong_value": tot["field_wrong_value"],
            "field_value_without_label": tot["field_value_without_label"],
            "field_missing": tot["field_missing"],
            "loop_or_truncation_pages": tot["loops"],
        })
    with open(RES / "summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)
    with open(RES / "fields.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(field_rows[0]))
        w.writeheader()
        w.writerows(field_rows)
    (RES / "ledger.jsonl").write_text("".join(json.dumps(x) + "\n" for x in ledger))
    for s in summary:
        print(s)


if __name__ == "__main__":
    main()
