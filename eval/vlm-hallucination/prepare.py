"""Download the test report, render the test pages, and build the number gold set.

The Tata Motors BRSR FY25 PDF has a broken font map: most digits in its text
layer come out as Greek/Coptic code points (U+03EC..U+03F5 for 0-9, U+0355 for
',' and U+0358 for '.'). The mapping is one-to-one, so decoding it gives the
exact numbers printed on the page without using any vision model. That decoded
set is the ground truth every model is scored against.
"""
import json
import pathlib
import re
import subprocess
import urllib.request

import pdfplumber
import pymupdf

HERE = pathlib.Path(__file__).parent
WORK = HERE / "work"
PDF_URL = "https://nsearchives.nseindia.com/corporate/TATAMOTORSSJS_24052025005348_NSEBSELETTERBRSR.pdf"
PDF = WORK / "tata_brsr_fy25.pdf"
PAGES = [45, 47, 49, 52]  # energy+water, air+GHG, waste, Scope 3 / other
DPI = 150

CIPHER = {chr(0x3EC + i): str(i) for i in range(10)}
CIPHER.update({"͕": ",", "͘": "."})

NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def decode(text: str) -> str:
    # The broken font also puts a space after its separators: "73, 673", "0. 271".
    # Only cipher separators get joined, so "December 20, 2024" stays two numbers.
    text = re.sub("([Ϭ-ϵ][͕͘]) (?=[Ϭ-ϵ])", r"\1", text)
    return "".join(CIPHER.get(c, c) for c in text)


def numbers(text: str) -> list[str]:
    """Normalised numbers with at least two digits. Commas and trailing dots go,
    so 1,31,407 / 131,407 / 131407 all compare equal."""
    out = []
    for m in NUM_RE.findall(text):
        n = m.replace(",", "").rstrip(".")
        if sum(ch.isdigit() for ch in n) >= 2:
            out.append(n)
    return out


def main():
    WORK.mkdir(exist_ok=True)
    (WORK / "pages").mkdir(exist_ok=True)
    if not PDF.exists():
        req = urllib.request.Request(PDF_URL, headers={"User-Agent": "Mozilla/5.0"})
        PDF.write_bytes(urllib.request.urlopen(req).read())
    doc = pymupdf.open(PDF)
    gold = {}
    for p in PAGES:
        subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p), "-r", str(DPI), "-png",
                        "-singlefile", str(PDF), str(WORK / "pages" / f"p{p}")], check=True)
        raw = doc[p - 1].get_text()
        gold[p] = {
            "cipher_chars": sum(c in CIPHER for c in raw),
            "raw_numbers": numbers(raw),        # what pdfplumber-style extraction sees
            "numbers": numbers(decode(raw)),    # what is printed on the page
        }
        print(p, "gold numbers:", len(gold[p]["numbers"]), "visible to raw text layer:", len(gold[p]["raw_numbers"]))
    (HERE / "gold" / "page_numbers.json").write_text(json.dumps(gold, indent=1))

    # Baseline: the current GCT primary extractor, scored like any model.
    base = WORK / "out" / "pdfplumber-text-layer"
    base.mkdir(parents=True, exist_ok=True)
    with pdfplumber.open(PDF) as pdf:
        for p in PAGES:
            (base / f"p{p}.txt").write_text(pdf.pages[p - 1].extract_text() or "")
            (base / f"p{p}.json").write_text(json.dumps({"model": "pdfplumber", "page": p, "seconds": 0}))


if __name__ == "__main__":
    main()
