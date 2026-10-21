"""Story 3.5 stream R: reading in source order (R1), source match on directed readings (R3), the item-13 answer read
in column order (R3), and the reading half of AC 5. Fixtures in pdf_layouts.py."""
import io
import json
from collections import Counter
from pathlib import Path

import pdfplumber

from pdf_layouts import (ACROSS, NO_ANSWER, QUESTION_ONLY, ROTATED, SIDE_A, SIDE_B, TABLES, THREE_COLUMNS, TWO_COLUMNS,
                         _page, pdf)
from test_infer import NAV, acme, label_claims, run_infer  # noqa: F401 (acme is a fixture)
from gct.stages import extract, link, read
from gct.stages.extract import _clean

OLD_CONFIG = "read config 2, kept by the test"


def reading(layout) -> dict:
    with pdfplumber.open(io.BytesIO(pdf([layout]))) as doc:
        return read.read_page(doc.pages[0])


def old_read_page(page) -> dict:
    """Reading config 2 as it was (pdfplumber defaults), to build a reading made before directions were recorded."""
    out = {"page": page.page_number, "width": round(float(page.width), 2), "height": round(float(page.height), 2),
           "text": page.extract_text() or "",
           "words": [{"text": w["text"], **{k: round(float(w[k]), 2) for k in ("x0", "top", "x1", "bottom")}}
                     for w in page.extract_words()],
           "tables": [{"bbox": [round(float(v), 2) for v in t.bbox], "rows": t.extract(),
                       "cells": [[c and [round(float(v), 2) for v in c] for c in row.cells] for row in t.rows]}
                      for t in page.find_tables()]}
    page.close()
    return out


def add(gct, make_file, *layouts) -> int:
    gct("company", "add", "Acme")
    r = gct("doc", "add", make_file("r.pdf", pdf(list(layouts))), "--company", "Acme", "--json")
    return r.data["items"][0]["document"]["id"]


def newest(db) -> dict:
    """{locator: (value_text, metric_text, newest source match status, reason)} for each claim's newest version."""
    return {r[0]: tuple(r[1:]) for r in db.execute(
        "SELECT c.locator, v.value_text, v.metric_text, s.status, s.reason FROM claim c"
        " JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)"
        " JOIN evidence_ref e ON e.claim_version_id = v.id"
        " LEFT JOIN source_match s ON s.id = (SELECT MAX(id) FROM source_match WHERE evidence_ref_id = e.id)")}


# AC 1
def test_rotated_text_reads_in_source_order():
    r = reading(ROTATED)
    words = {w["text"]: w for w in r["words"]}
    for text in ("0.29", "(1.65)", "Reserves", "surplus", "1,234"):
        assert words[text]["dir"] == "btt"
    assert {words[t]["dir"] for t in ("Net", "worth", "4,321")} == {"ttb"}
    assert words["Balance"]["dir"] == "ltr"
    assert "Reserves and surplus 1,234 %" in r["text"].splitlines()
    assert "Net worth 4,321 %" in r["text"].splitlines()
    (table,) = r["tables"]
    assert table["rows"] == [["Debt equity", "0.29", "(1.65)"]]
    # No figure of the fixture reads the same reversed, so a reversal could not pass unseen.
    for text in ("0.29", "(1.65)", "1,234", "4,321", "Reserves and surplus"):
        assert text != text[::-1] and text[::-1] not in r["text"]
    found = {f["locator"]: f for f in extract.rules(r)}
    assert (found["t0r0c1"]["value_text"], found["t0r0c2"]["value_text"]) == ("0.29", "(1.65)")
    reserves = next(f for f in found.values() if f["value_text"] == "1,234")
    assert (reserves["metric_text"], reserves["unit_text"]) == ("Reserves and surplus", "%")
    assert next(f for f in found.values() if f["value_text"] == "4,321")["metric_text"] == "Net worth"


def test_no_text_is_reversed_by_slicing():
    for module in (read, extract):
        assert "[::-1]" not in Path(module.__file__).read_text(encoding="utf-8")


def test_rotated_claims_are_matched_after_read_extract_link(db, gct, make_file):
    add(gct, make_file, ROTATED)
    for stage in ("read", "extract", "link"):
        assert gct(stage).code == 0
    claims = newest(db)
    assert claims["t0r0c1"] == ("0.29", "Debt equity", "matched", None)
    assert claims["t0r0c2"][::2] == ("(1.65)", "matched")
    assert {v[0] for v in claims.values()} == {"0.29", "(1.65)", "1,234", "4,321"}
    assert {v[2] for v in claims.values()} == {"matched"}


def test_a_reading_without_directions_is_never_matched(db, gct, make_file, monkeypatch):
    add(gct, make_file, ROTATED)
    monkeypatch.setattr(read, "read_page", old_read_page)
    monkeypatch.setattr(read, "read_config", lambda: OLD_CONFIG)
    for stage in ("read", "extract", "link"):
        assert gct(stage).code == 0
    claims = newest(db)
    assert claims["t0r0c1"][0] == "92.0"  # what the reading before config 3 printed
    assert {v[2:] for v in claims.values()} == {("cited", link.NO_DIRECTION)}
    assert link.NO_DIRECTION == "reading has no text direction: gct read again"


def test_box_words_of_two_directions_are_not_matched():
    words = [{"text": "4,560", "x0": 10, "top": 10, "x1": 40, "bottom": 20, "dir": "ltr", "col": 0},
             {"text": "MWh", "x0": 42, "top": 10, "x1": 60, "bottom": 20, "dir": "btt", "col": 0}]
    ref = {"sheet": None, "boxes": [[10, 10, 60, 20]], "value_text": "4,560", "unit_text": "MWh"}
    assert link.match(ref, {"words": words})[0] == "cited"
    assert link.match(ref, {"words": [{**w, "dir": "ltr"} for w in words]}) == ("matched", None)


# AC 5, reading half: a config-2 workspace read and extracted again at config 3
def test_reading_again_at_config_3_gives_the_rotated_figure_a_new_version(db, gct, make_file, monkeypatch):
    add(gct, make_file, ROTATED)
    real = read.read_page, read.read_config, extract.extract_config
    monkeypatch.setattr(read, "read_page", old_read_page)
    monkeypatch.setattr(read, "read_config", lambda: OLD_CONFIG)
    monkeypatch.setattr(extract, "extract_config", lambda: "extract config 2, kept by the test")
    gct("read")
    gct("extract")
    for module, name, value in zip((read, read, extract), ("read_page", "read_config", "extract_config"), real):
        monkeypatch.setattr(module, name, value)
    for stage in ("read", "extract", "link"):
        assert gct(stage).code == 0
    assert [r[0] for r in db.execute("SELECT config_version FROM page ORDER BY id")] == [OLD_CONFIG, read.read_config()]
    versions = [tuple(r) for r in db.execute(
        "SELECT v.value_text, v.config_version FROM claim c JOIN claim_version v ON v.claim_id = c.id"
        " WHERE c.locator = 't0r0c1' ORDER BY v.id")]
    assert versions == [("92.0", "extract config 2, kept by the test"), ("0.29", extract.extract_config())]
    assert newest(db)["t0r0c1"] == ("0.29", "Debt equity", "matched", None)
    statuses = [tuple(r) for r in db.execute(
        "SELECT v.value_text, s.status, s.reason FROM claim c JOIN claim_version v ON v.claim_id = c.id JOIN evidence_ref e"
        " ON e.claim_version_id = v.id JOIN source_match s ON s.evidence_ref_id = e.id WHERE c.locator = 't0r0c1'"
        " ORDER BY s.id")]
    # The reversed box no longer confirms itself; both versions keep their rows.
    assert statuses[0] == ("92.0", "cited", link.NO_DIRECTION) and statuses[-1] == ("0.29", "matched", None)


# AC 2
def test_three_columns_read_column_by_column():
    r = reading(THREE_COLUMNS)
    words = {w["text"]: w for w in r["words"] if w["top"] > 90 and w["x0"] < 390}
    assert 7.5 < words["The"]["x0"] - max(w["x1"] for w in r["words"] if w["top"] > 90 and w["x0"] < 180) < 8.5
    assert len({w["col"] for w in r["words"] if w["text"] in ("Are", "Standalone", "c.")}) == 3
    assert "9 Financial Year reported 1 April 2024 to 31 March 2025" in r["text"].splitlines()
    text = _clean(r["text"])
    assert "The disclosures under this report are made on Standalone basis." in text
    assert "taken together). The disclosures under this report are made on Standalone basis. c. A brief" in text


def test_the_item_13_answer_in_column_order_is_a_boundary_statement(ws, db, gct, make_file, acme):
    nav = {"text": [(40, 80 + 20 * i, s) for i, s in enumerate(NAV)]}
    r = gct("doc", "add", make_file("r.pdf", pdf([THREE_COLUMNS, QUESTION_ONLY, NO_ANSWER, nav])), "--company", "Acme",
            "--json")
    doc = r.data["items"][0]["document"]["id"]
    gct("read")
    label_claims(db, doc, ["FY24"])
    run_infer(gct)
    data = run_infer(gct, "bases")
    (b,) = [b for b in data["bases"] if b["kind"] == "reporting_boundary"]
    assert (b["page"], b["kind"], b["boundary"]) == (1, "reporting_boundary", "standalone")
    # The one-line form item keeps its label beside its answer, so its fiscal-year statement is still read.
    assert sorted(b["page"] for b in data["bases"] if b["kind"] == "fiscal_year_end") == [1, 2, 3]
    assert "made on Standalone basis" in b["wording"] and "consolidated" not in b["wording"].lower()
    assert data["headings"] == [{"document": doc, "page": n, "reason": "heading without a readable answer"}
                                for n in (2, 3)]


def test_two_column_text_claims_take_wording_from_their_own_column():
    found = {f["value_text"]: f for f in extract.rules(reading(TWO_COLUMNS))}
    assert {v: f["metric_text"] for v, f in found.items()} == {
        "1,200": "Scope 1 emissions", "3,400": "Water withdrawn", "56": "Waste recycled", "7,800": "Fleet fuel"}
    # Lines are numbered column by column: the left column's three lines first.
    assert [found[v]["locator"] for v in ("1,200", "3,400", "56", "7,800")] == ["l0w3", "l2w2", "l3w2", "l5w2"]
    # A heading printed across both columns does not hide the gutter below it.
    headed = _page(TWO_COLUMNS, {"text": [(40, 80, "A heading printed across both columns of this page", 12)]})
    assert {f["value_text"]: f["metric_text"] for f in extract.rules(reading(headed))} == {
        v: f["metric_text"] for v, f in found.items()}


# AC 3 (table regions)
def test_tables_keep_one_column_and_their_lines():
    with pdfplumber.open(io.BytesIO(pdf([TABLES]))) as doc:
        old = old_read_page(doc.pages[0])["text"]
    r = reading(TABLES)
    assert len(r["tables"]) == len((SIDE_A, SIDE_B, ACROSS))
    assert [len({w["col"] for w in r["words"] if read._centre_in(w, t["bbox"])}) for t in r["tables"]] == [1, 1, 1]
    # Two columns above the tables, then the tables, then two columns below them, each column read through.
    assert r["text"].splitlines() == [
        "Left text one", "Left text two", "Left text three", "Right text one", "Right text two", "Right text three",
        "Metric FY24 Metric FY23", "Scope 1 1,234 Scope 2 5,678", "Energy 4,321 GJ",
        "Left text four", "Left text five", "Left text six", "Right text four", "Right text five", "Right text six"]
    assert len({w["col"] for w in r["words"] if w["text"] in ("Energy", "GJ")}) == 1  # the gutter never splits it
    assert Counter(r["text"].split()) == Counter(old.split())
    olds = old.splitlines()
    assert all(any(line in o for o in olds) for line in r["text"].splitlines())
    assert "Energy 4,321 GJ" in r["text"].splitlines()


def test_a_page_of_one_column_reads_as_before():
    from test_extract import PAGE  # the 3.1 fixture: a table and text lines in one column
    from conftest import make_pdf

    with pdfplumber.open(io.BytesIO(make_pdf([PAGE]))) as doc:
        old = old_read_page(doc.pages[0])
    with pdfplumber.open(io.BytesIO(make_pdf([PAGE]))) as doc:
        new = read.read_page(doc.pages[0])
    assert new["text"] == old["text"] and new["tables"][0]["rows"] == old["tables"][0]["rows"]
    assert [{k: w[k] for k in ("text", "x0", "top", "x1", "bottom")} for w in new["words"]] == old["words"]
    assert {(w["dir"], w["col"]) for w in new["words"]} == {("ltr", 0)}
    assert json.dumps(extract.rules(old), sort_keys=True) == json.dumps(extract.rules(new), sort_keys=True)
