"""Arithmetic gates: the production check that needs no gold data.

BRSR tables print their own totals. If the parts a model extracted do not add
up to the total it extracted, at least one value is wrong or in the wrong row.
This catches row shifts, which page-level hallucination counts cannot see:
every number in a shifted table is a real number from the page.

Run after score.py. Writes results/checks.csv and appends arithmetic_fail
lines to results/ledger.jsonl.
"""
import csv
import json
import pathlib
import re

from score import OUT, RES, clean, rows

# (rule, page, part-row patterns, total-row pattern). Patterns match the
# lower-cased row text. A total pattern of "total" means the first row starting
# with "total" after the last part.
RULES = [
    ("water_withdrawal", 45, [r"surface water", r"groundwater", r"third party water", r"seawater", r"\(v\)\s*others"],
     r"total volume of water withdrawal"),
    ("energy_renewable", 45, [r"electricity consumption \(a\)", r"fuel consumption \(b\)", r"other sources \(c\)"],
     r"total energy consumed from renewable"),
    ("energy_nonrenewable", 45, [r"electricity consumption \(d\)", r"fuel consumption \(e\)", r"other sources \(f\)"],
     r"total energy consumed from non-renewable"),
    ("waste_recovered", 49, [r"recycled", r"re-used", r"other recovery operations"], "total"),
    ("waste_disposed", 49, [r"incineration", r"landfilling", r"other disposal operations"], "total"),
    ("scope3_total", 52, [r"category 1\b", r"category 3\b", r"category 5\b", r"category 6\b", r"category 7\b",
                          r"category 8\b", r"category 11\b", r"category 14\b"], r"^\|?\s*total scope 3 emissions(?!.*rupee)"),
]


def values(row: str) -> list[float]:
    """Numeric cells in reading order, without label digits like 'category 11:' or '(a)'."""
    row = re.sub(r"\$[\^_]\{?\w+\}?\$", " ", row)  # LaTeX super/subscripts: $^{1}$, $_{2}$
    row = re.sub(r"category \d+\s*:?|scope \d|\([a-z+ ]+\)|co2|cfc-11|^\d+\.", " ", row)
    return [float(v.replace(",", "")) for v in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", row)]


def find(rws: list[str], pattern: str, start: int = 0) -> int | None:
    """First row at or after start that matches and carries a value (skips section headers)."""
    for i in range(start, len(rws)):
        if re.search(pattern, rws[i]) and values(rws[i]):
            return i
    return None


def main():
    results, ledger = [], []
    for model_dir in sorted(p for p in OUT.iterdir() if p.is_dir()):
        for rule, page, parts, total in RULES:
            f = model_dir / f"p{page}.txt"
            if not f.exists():
                continue
            rws = [r for r in rows(clean(f.read_text())) if r]
            idx = [find(rws, p) for p in parts]
            t_idx = None
            if None not in idx:
                t_idx = find(rws, r"^\|?\s*total", max(idx) + 1) if total == "total" else find(rws, total)
            for col, year in ((0, "fy25"), (1, "fy24")):
                status, detail = "not_evaluable", "part or total row not found"
                if None not in idx and t_idx is not None:
                    pv = [values(rws[i]) for i in idx]
                    tv = values(rws[t_idx])
                    if all(len(v) > col for v in pv) and len(tv) > col:
                        s, t = sum(v[col] for v in pv), tv[col]
                        # rounding moves a sum by at most half a unit per part (Tata nonrenewable energy: 1 GJ)
                        ok = abs(s - t) <= 0.5 * len(pv) + 1e-9
                        status = "pass" if ok else "fail"
                        detail = f"parts sum {s:,.6g} vs total {t:,.6g}"
                    else:
                        detail = "a row has no value for this year"
                results.append({"model": model_dir.name, "rule": rule, "year": year, "status": status, "detail": detail})
                if status == "fail":
                    ledger.append({"model": model_dir.name, "page": page, "kind": "arithmetic_fail", "rule": rule,
                                   "year": year, "detail": detail, "review": "open"})
    with open(RES / "checks.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)
    with open(RES / "ledger.jsonl", "a") as fh:
        fh.writelines(json.dumps(x) + "\n" for x in ledger)
    for r in results:
        print(r)


if __name__ == "__main__":
    main()
