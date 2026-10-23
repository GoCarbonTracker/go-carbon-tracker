"""Story 4.3: internal-evidence spreadsheets. CSV and XLSX fixtures are written here (XLSX with zipfile only)."""
import sqlite3
import zipfile
from io import BytesIO

import pytest

from test_match import report
from gct.stages import sheet
from gct.workspace import layout, published, store

WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "the metering export headers")
HEADER = ["Metric", "Value", "Unit", "Period", "Boundary", "Company", "Note"]
ROWS = [
    HEADER,
    ["Total Scope 1 emissions", "1100", "tCO2e", "FY 2023-24", "Standalone", "Acme", "meter log p3"],
    ["Total energy consumed", "5000", "GJ", "FY 2023-24", "Standalone", "Acme", ""],
    ["Water withdrawal", "", "kL", "FY 2023-24", "Standalone", "Acme", ""],
    ["Total Scope 1 emissions", "99", "tCO2e", "FY 2023-24", "Standalone", "Beta Ltd", ""],
]
MAP = ("--metric", "Metric", "--value", "Value", "--unit", "Unit", "--period", "Period", "--boundary", "Boundary",
       "--company", "Company", "--note", "Note")
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def csv_bytes(rows, sep=",") -> bytes:
    return "\n".join(sep.join(r) for r in rows).encode("utf-8")


def xlsx(sheets: dict) -> bytes:
    """An XLSX: a str cell is a shared string, ("inline", s) an inline string, ("rich", parts) a shared string in
    rich-text runs, an int or float a number, None or "" no cell."""
    shared = []

    def cell(ref, v):
        if isinstance(v, tuple) and v[0] == "inline":
            return f'<c r="{ref}" t="inlineStr"><is><t>{v[1]}</t></is></c>'
        if isinstance(v, (str, tuple)):
            si = v if isinstance(v, str) else "".join(f"<r><t xml:space=\"preserve\">{p}</t></r>" for p in v[1])
            si = f"<t>{si}</t>" if isinstance(v, str) else si
            shared.append(si)
            return f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>'
        return f'<c r="{ref}"><v>{v}</v></c>'

    parts, book, rels = {}, [], []
    for i, (name, rows) in enumerate(sheets.items(), 1):
        data = "".join(f'<row r="{r}">' + "".join(cell(f"{sheet.column(c)}{r}", v) for c, v in enumerate(row)
                                                  if v not in (None, "")) + "</row>" for r, row in enumerate(rows, 1))
        parts[f"xl/worksheets/sheet{i}.xml"] = f'<worksheet xmlns="{NS}"><sheetData>{data}</sheetData></worksheet>'
        book.append(f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>')
        rels.append(f'<Relationship Id="rId{i}" Type="{R_NS}/worksheet" Target="worksheets/sheet{i}.xml"/>')
    rels.append(f'<Relationship Id="rIdS" Type="{R_NS}/sharedStrings" Target="sharedStrings.xml"/>')
    parts["xl/sharedStrings.xml"] = f'<sst xmlns="{NS}">' + "".join(f"<si>{s}</si>" for s in shared) + "</sst>"
    parts["xl/workbook.xml"] = f'<workbook xmlns="{NS}" xmlns:r="{R_NS}"><sheets>{"".join(book)}</sheets></workbook>'
    parts["xl/_rels/workbook.xml.rels"] = f'<Relationships xmlns="{PKG}">{"".join(rels)}</Relationships>'
    parts["[Content_Types].xml"] = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, text in parts.items():
            z.writestr(name, text)
    return out.getvalue()


# The XLSX twin of ROWS: numbers stored as numbers, one inline string, one rich-text string, empty cells absent.
ENERGY = [
    HEADER,
    ["Total Scope 1 emissions", 1100, "tCO2e", "FY 2023-24", "Standalone", ("inline", "Acme"), "meter log p3"],
    [("rich", ["Total ", "energy consumed"]), 5000, "GJ", "FY 2023-24", "Standalone", "Acme", None],
    ["Water withdrawal", None, "kL", "FY 2023-24", "Standalone", "Acme", None],
    ["Total Scope 1 emissions", 99, "tCO2e", "FY 2023-24", "Standalone", "Beta Ltd", None],
]
FUEL = [["Fuel", "Litres"], ["Diesel", 120]]


@pytest.fixture
def acme(ws, gct):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")


def add(gct, make_file, name, content, *extra) -> int:
    r = gct("doc", "add", make_file(name, content), "--company", "Acme", "--kind", "evidence", *extra, "--json")
    return r.data["items"][0]["document"]["id"]


def claims(gct, doc) -> dict:
    return {c["locator"]: c for c in gct("claims", "list", "--doc", doc, "--json").data["claims"]}


def count(db, table) -> int:
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# AC 1
def test_migration_15_applies_to_a_version_12_workspace(tmp_path, gct):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    assert store.migrate(c, up_to=12) == list(range(1, 13))
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.close()
    assert gct("contributor", "list", "--workspace", root).code == 0
    c = store.connect(root / layout.DB_NAME)
    assert [r[0] for r in c.execute("SELECT version FROM schema_version ORDER BY version")] == [*range(1, 20)]
    c.close()


def test_spreadsheet_tables_are_append_only_and_check_their_values(db):
    insert = ("INSERT INTO sheet_mapping (document_id, sheet, position, value_col, year_end, boundary_is,"
              " contributor_version_id, capacity, rationale, created_at) VALUES (1, 's', 1, 'Value', ?, ?, 1, 'c', 'r', 't')")
    db.execute(insert, ("03-31", "standalone"))
    db.execute(insert, (None, None))
    db.execute("INSERT INTO claim_note (claim_version_id, text, created_at) VALUES (1, 'n', 't')")
    for table in ("sheet_mapping", "claim_note"):
        for stmt in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
                db.execute(stmt)
    for bad in (("3-31", None), ("13-01", None), ("03-32", None), ("0331", None), (None, "group"), (None, "unknown")):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            db.execute(insert, bad)


# AC 2
def test_csv_and_xlsx_are_read_to_the_same_rows(tmp_path):
    comma, semi, book = tmp_path / "m.csv", tmp_path / "s.csv", tmp_path / "b.xlsx"
    comma.write_bytes(b"\xef\xbb\xbf" + csv_bytes(ROWS))  # with a byte order mark
    semi.write_bytes(csv_bytes(ROWS, ";"))
    book.write_bytes(xlsx({"Energy": ENERGY, "Fuel": FUEL}))
    assert sheet.read_book(str(comma), "csv", "m.csv") == (("m", ROWS),)
    assert sheet.read_book(str(semi), "csv", "s.csv") == (("s", ROWS),)
    assert sheet.read_book(str(book), "xlsx", "b.xlsx") == (("Energy", ROWS), ("Fuel", [["Fuel", "Litres"], ["Diesel", "120"]]))
    assert [sheet.column(i) for i in (0, 25, 26, 27, 701, 702)] == ["A", "Z", "AA", "AB", "ZZ", "AAA"]


def test_a_styled_empty_cell_far_out_allocates_nothing(tmp_path):
    src = zipfile.ZipFile(BytesIO(xlsx({"Fuel": FUEL})))
    far = '<row r="1048576"><c r="XFD1048576" s="1"/></row></sheetData>'
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name in src.namelist():
            text = src.read(name).decode()
            z.writestr(name, text.replace("</sheetData>", far) if name == "xl/worksheets/sheet1.xml" else text)
    path = tmp_path / "far.xlsx"
    path.write_bytes(out.getvalue())
    assert sheet.read_book(str(path), "xlsx", "far.xlsx") == (("Fuel", [["Fuel", "Litres"], ["Diesel", "120"]]),)


def test_the_docs_name_everything_extraction_writes():
    from pathlib import Path

    text = " ".join((Path(__file__).resolve().parent.parent / "docs" / "spreadsheets.md").read_text().split())
    assert "(`claim_note`)" in text and "(`source_match`," in text and "`row without a company`" in text
    assert "never `same table row`" in text and "`unresolved conflict`" in text
    assert "`gct restate record` cannot name it as the restated figure" in text


def test_sheet_show_prints_header_and_first_rows_per_sheet(acme, gct, make_file):
    doc = add(gct, make_file, "b.xlsx", xlsx({"Energy": ENERGY, "Fuel": FUEL}))
    r = gct("sheet", "show", doc)
    assert r.code == 0
    lines = r.out.splitlines()
    assert lines[0] == "sheet 1 Energy: no confirmed mapping"
    assert lines[1] == "  row 1: " + " | ".join(HEADER)
    assert lines[2].startswith("  row 2: Total Scope 1 emissions | 1100 | tCO2e")
    assert "sheet 2 Fuel: no confirmed mapping" in lines and "  row 2: Diesel | 120" in lines
    data = gct("sheet", "show", doc, "--json").data["sheets"]
    assert [(s["name"], s["position"], s["mapping"]) for s in data] == [("Energy", 1, None), ("Fuel", 2, None)]
    assert data[0]["rows"][0] == {"row": 2, "cells": ROWS[1]} and len(data[0]["rows"]) == 4


# AC 3
def test_map_stores_the_mapping_with_its_contributor_and_supersedes(acme, gct, db, make_file):
    doc = add(gct, make_file, "m.csv", csv_bytes(ROWS))
    r = gct("sheet", "map", doc, "--sheet", "m", *MAP, *WHO, "--json")
    assert r.code == 0
    m = r.data["mapping"]
    assert (m["sheet"], m["position"], m["metric"], m["value"], m["note"], m["contributor"], m["organisation"]) == (
        "m", 1, "Metric", "Value", "Note", "Ana", "Acme audit")
    row = db.execute("SELECT * FROM sheet_mapping").fetchone()
    assert (row["value_col"], row["contributor_version_id"], row["capacity"]) == ("Value", 1, "analyst")
    second = gct("sheet", "map", doc, "--sheet", "m", "--metric", "Metric", "--value", "Unit", *WHO, "--json").data["mapping"]
    assert second["id"] == 2 and second["value"] == "Unit" and second["unit"] is None
    assert gct("sheet", "show", doc, "--json").data["sheets"][0]["mapping"]["id"] == 2
    assert count(db, "sheet_mapping") == 2


def test_map_refusals(acme, gct, db, make_file):
    doc = add(gct, make_file, "m.csv", csv_bytes([HEADER + ["Value"], *(r + [""] for r in ROWS[1:])]))
    pdf = add(gct, make_file, "r.pdf", report([["Total Scope 1 emissions", "tCO2e", "1", "2"]]))
    base = ("sheet", "map", doc, "--sheet", "m", "--metric", "Metric")
    cases = [
        ((*base[:4], "Nope", "--metric", "Metric", "--value", "Unit", *WHO), 3, "has no sheet named Nope"),
        ((*base, "--value", "Kilolitres", *WHO), 4, "Kilolitres is not a header in row 1 of sheet m."),
        ((*base, "--value", "Value", *WHO), 4, "Value is printed 2 times in row 1 of sheet m"),
        ((*base, *WHO), 2, "The value column is missing."),
        ((*base, "--value", "Unit", "--year-end", "3/31", *WHO), 2, "3/31 is not a year end like 03-31."),
        ((*base, "--value", "Unit", "--year-end", "02-30", *WHO), 2, "02-30 is not a year end"),
        ((*base, "--value", "Unit", "--boundary-detail", "two plants", *WHO), 2, "A boundary detail needs"),
        (("sheet", "map", pdf, "--sheet", "x", "--metric", "M", "--value", "V", *WHO), 4, "Only CSV and XLSX documents"),
        ((*base, "--value", "Unit", "--as", "bob", "--capacity", "c", "--rationale", "r"), 3, "no contributor with key bob"),
    ]
    for argv, code, cause in cases:
        r = gct(*argv, "--json")
        assert r.code == code and cause in r.data["cause"] and r.data["next_action"], (argv, r.data)
    for i in (0, 2, 4):  # --as, --capacity or --rationale left out: required, as on every attributed command
        assert gct(*base, "--value", "Unit", *WHO[:i], *WHO[i + 2:]).code == 2
    assert count(db, "sheet_mapping") == 0


# AC 4
def test_extraction_makes_one_claim_per_row_with_a_value(acme, gct, db, make_file):
    doc = add(gct, make_file, "b.xlsx", xlsx({"Energy": ENERGY, "Fuel": FUEL}))
    first = gct("extract", doc, "--json").data["documents"][0]
    assert (first["action"], first["cause"]) == ("skipped", "sheet Energy: no confirmed mapping; sheet Fuel: no confirmed mapping")
    gct("sheet", "map", doc, "--sheet", "Energy", *MAP, *WHO)
    r = gct("extract", doc)
    assert r.code == 0
    assert r.out.splitlines()[0] == (f"extracted {doc}: b.xlsx: 1 pages, 1 extracted, 0 cached, 0 failed, 2 figures, 0 without a box;"
                                     " sheet Fuel: no confirmed mapping; sheet Energy: 1 skipped (row for another company)")
    cs = claims(gct, doc)
    assert set(cs) == {"s1r2", "s1r3"}
    c = cs["s1r2"]
    assert (c["page_number"], c["sheet"], c["cell"], c["boxes"], c["claim_state"]) == (1, "Energy", "B2", None, "current")
    assert (c["metric_text"], c["value_text"], c["value"], c["unit_text"], c["period_label"], c["boundary_label"]) == (
        "Total Scope 1 emissions", "1100", 1100.0, "tCO2e", "FY 2023-24", "Standalone")
    assert cs["s1r3"]["metric_text"] == "Total energy consumed"
    ref = db.execute("SELECT * FROM evidence_ref WHERE claim_version_id = 1").fetchone()
    assert (ref["page_number"], ref["boxes"], ref["sheet"], ref["cell"]) == (None, None, "Energy", "B2")
    assert [tuple(r) for r in db.execute("SELECT claim_version_id, text FROM claim_note")] == [(1, "meter log p3")]
    assert f"{c['id']}  sheet Energy cell B2  current  1100  tCO2e" in gct("claims", "list", "--doc", doc).out
    assert "  location sheet Energy cell B2: matched" in gct("claims", "history", c["id"]).out

    again = gct("extract", doc, "--json").data["documents"][0]
    assert (again["extracted"], again["cached"], again["figures"]) == (0, 1, 2)
    assert count(db, "claim_version") == 2

    # A new mapping re-extracts; only the rows whose fields changed get a new version.
    gct("sheet", "map", doc, "--sheet", "Energy", *MAP[:-2], *WHO)  # the note column left out
    assert claims(gct, doc)["s1r2"]["claim_state"] == "page read again, not yet extracted"
    redo = gct("extract", doc, "--json").data["documents"][0]
    assert (redo["extracted"], redo["cached"]) == (1, 0)
    assert count(db, "claim_version") == 3 and count(db, "claim") == 2
    assert [r[0] for r in db.execute("SELECT claim_id FROM claim_version WHERE id = 3")] == [c["id"]]
    assert claims(gct, doc)["s1r2"]["claim_state"] == "current"


def test_an_empty_company_cell_is_skipped_under_its_own_reason(acme, gct, make_file):
    rows = [*ROWS, ["Total Scope 2 emissions", "40", "tCO2e", "FY 2023-24", "Standalone", "", ""]]
    doc = add(gct, make_file, "m.csv", csv_bytes(rows))
    gct("sheet", "map", doc, "--sheet", "m", *MAP, *WHO)
    d = gct("extract", doc, "--json").data["documents"][0]
    assert d["cause"] == "sheet m: 1 skipped (row for another company); sheet m: 1 skipped (row without a company)"
    assert set(claims(gct, doc)) == {"s1r2", "s1r3"}


def test_a_row_gone_from_the_new_mapping_is_not_found(acme, gct, make_file):
    doc = add(gct, make_file, "m.csv", csv_bytes(ROWS))
    gct("sheet", "map", doc, "--sheet", "m", "--metric", "Metric", "--value", "Value", *WHO)
    gct("extract", doc)
    assert set(claims(gct, doc)) == {"s1r2", "s1r3", "s1r5"}  # no company column: Beta's row is not checked
    gct("sheet", "map", doc, "--sheet", "m", *MAP, *WHO)
    gct("extract", doc)
    assert claims(gct, doc)["s1r5"]["claim_state"] == "not found in the newest reading"
    assert gct("claims", "list", "--doc", doc, "--state", "current", "--json").data["claims"][0]["locator"] == "s1r2"


def test_a_mixed_selection_makes_two_runs_and_resume_and_retry_take_sheet_runs(acme, gct, make_file, monkeypatch):
    pdf = add(gct, make_file, "r.pdf", report([["Total Scope 1 emissions", "tCO2e", "1,234", "1,100"]]))
    doc = add(gct, make_file, "m.csv", csv_bytes(ROWS))
    gct("sheet", "map", doc, "--sheet", "m", *MAP, *WHO)
    gct("read")
    out = gct("extract", "--json").data["documents"]
    assert [d["id"] for d in out] == [pdf, doc]
    commands = [r["command"] for r in gct("run", "list", "--json").data["runs"][:2]]
    assert commands == ["sheet", "extract"]
    n = gct("run", "list", "--json").data["runs"][0]["id"]
    assert gct("run", "resume", n).code == 4  # it finished
    assert gct("run", "retry", n, "--json").data["documents"] == []

    def boom(*a, **k):
        raise ValueError("boom")

    real = sheet.figures
    monkeypatch.setattr(sheet, "figures", boom)
    gct("sheet", "map", doc, "--sheet", "m", "--metric", "Metric", "--value", "Value", *WHO)
    failed = gct("extract", doc, "--json")
    assert failed.code == 4 and failed.data["documents"][0]["failed"] == 1
    assert failed.data["next_action"] == sheet.RETRY  # only a spreadsheet failed: its own retry wording
    assert f"next: {sheet.RETRY}" in gct("extract", doc).err
    monkeypatch.setattr(sheet, "figures", real)  # not undo(): that drops the workspace too
    n = gct("run", "list", "--json").data["runs"][0]["id"]
    retried = gct("run", "retry", n, "--json").data
    assert retried["of_run"] == n and retried["documents"][0]["extracted"] == 1
    assert gct("run", "show", retried["run_id"], "--json").data["command"] == "sheet"


# AC 5, AC 6
def test_the_upload_confirms_nothing_and_declarations_are_proposals(acme, gct, db, make_file):
    doc = add(gct, make_file, "m.csv", csv_bytes(ROWS))
    gct("sheet", "map", doc, "--sheet", "m", *MAP, *WHO)
    gct("extract", doc)
    gct("infer")
    eff = gct("claims", "list", "--doc", doc, "--json").data["claims"][0]
    assert eff["period"]["state"] == "unresolved" and eff["period"]["reason"] == "no fiscal year statement in this document"
    assert eff["boundary"]["state"] == "unresolved"
    gct("sheet", "map", doc, "--sheet", "m", *MAP, "--year-end", "03-31", "--boundary-is", "standalone", *WHO)
    gct("extract", doc)
    gct("infer")
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table in ("inference_review", "match_review", "correction", "gap_confirmation", "page_acceptance", "restatement"):
        assert table not in tables or count(db, table) == 0, table
    for c in gct("claims", "list", "--doc", doc, "--json").data["claims"]:
        assert c["period"]["state"] in ("proposed", "unresolved") and c["boundary"]["state"] in ("proposed", "unresolved")
    c = claims(gct, doc)["s1r2"]
    p, b = c["period"], c["boundary"]
    assert (p["state"], p["kind"], p["start"], p["end"]) == ("proposed", "fiscal_year", "2023-04-01", "2024-03-31")
    assert p["basis"]["wording"] == "declared in sheet mapping #2 by Ana" and p["basis"]["page"] == 1
    assert (b["state"], b["boundary"], b["basis"]["wording"]) == ("proposed", "standalone", "declared in sheet mapping #2 by Ana")
    scope = gct("infer", "bases", "--doc", doc, "--json").data["bases"][1]["scope"]
    assert (scope["first"], scope["last"], scope["contributor"], scope["capacity"]) == (1, 1, "Ana", "analyst")
    assert gct("infer", "--json").data["documents"][0]["cached"] == 1  # nothing changed: not inferred twice


def test_accepted_sheet_claims_join_a_series_with_the_report(acme, gct, make_file):
    from test_match import ready  # reads, extracts, infers, declares the report's boundary page, accepts, matches

    add(gct, make_file, "r.pdf", report([["Total Scope 1 emissions", "tCO2e", "1,234", "1,100"]]))
    doc = add(gct, make_file, "m.csv", csv_bytes(ROWS))
    gct("sheet", "map", doc, "--sheet", "m", *MAP, "--year-end", "03-31", "--boundary-is", "standalone", *WHO)
    ready(gct)
    (s,) = gct("series", "list", "--metric", "ghg_scope_1", "--json").data["series"]
    shown = gct("series", "show", s["id"], "--all", "--json").data["series"]["points"]
    assert {(x["document_id"], x["value_text"], x["sheet"], x["cell"]) for x in shown} == {
        (1, "1,234", None, None), (1, "1,100", None, None), (doc, "1100", "m", "B2")}
    text = gct("series", "show", s["id"], "--all").out
    assert f"document {doc} sheet m cell B2  claim" in text and "document 1 p1  claim" in text


def test_a_sheet_claim_in_a_pair_prints_its_cell_and_cannot_be_the_restated_side(acme, gct, make_file):
    from test_match import ready
    from gct.stages import restate

    add(gct, make_file, "r.pdf", report([["Total Scope 1 emissions", "tCO2e", "1,234", "1,100"]]))
    rows = [HEADER, ["Total Scope 1 emissions", "1150", "tCO2e", "FY 2023-24", "Standalone", "Acme", ""]]
    doc = add(gct, make_file, "m.csv", csv_bytes(rows))
    gct("sheet", "map", doc, "--sheet", "m", *MAP, "--year-end", "03-31", "--boundary-is", "standalone", *WHO)
    ready(gct)
    (p,) = gct("restate", "list", "--json").data["pairs"]
    assert p["state"] == restate.UNRESOLVED and "sheet" not in p["a"]  # never same table row; JSON keys unchanged
    mine = next(x["claim_id"] for x in (p["a"], p["b"]) if x["document_id"] == doc)
    other = next(x["claim_id"] for x in (p["a"], p["b"]) if x["document_id"] != doc)
    listed = gct("restate", "list").out
    assert f"(document {doc} sheet m cell B2, claim {mine})" in listed and "(document 1 p1, claim" in listed
    shown = gct("restate", "show", mine).out
    assert shown.startswith(f"claim {mine}  document {doc} sheet m cell B2  version")
    assert "    location sheet m cell B2: matched" in shown and " p1 " not in shown.splitlines()[0] and "pNone" not in shown
    refused = gct("restate", "record", "--original", other, "--restated", mine, "--page", "1", "--quote", "q", *WHO)
    assert refused.code == layout.REFUSED and "(not a PDF)" in refused.err  # 4.2's refusal: no page reading to quote


def test_archive_and_restore_of_a_spreadsheet(acme, gct, ws, make_file):
    doc = add(gct, make_file, "m.csv", csv_bytes(ROWS))
    gct("sheet", "map", doc, "--sheet", "m", *MAP, *WHO)
    gct("extract", doc)

    def outputs():
        v = gct("publish", "build", "--json").data["version"]
        conn = published.open_version(published.version_path(ws, v))
        try:
            return (claims(gct, doc), [dict(r) for r in conn.execute("SELECT * FROM sheet_mapping")],
                    [dict(r) for r in conn.execute("SELECT * FROM claim WHERE document_id = ?", (doc,))],
                    [dict(r) for r in conn.execute("SELECT * FROM hidden_by_archive")])
        finally:
            conn.close()

    before = outputs()
    assert len(before[1]) == 1 and len(before[2]) == 2 and before[3] == []
    plan = gct("doc", "archive", doc, "--plan", "--json").data["impact"]
    assert plan["review_records"]["sheet_mapping"] == 1
    assert ", 1 sheet mappings" in gct("doc", "archive", doc, "--plan").out
    assert gct("doc", "archive", doc, *WHO).code == 0
    (d,) = gct("extract", doc, "--json").data["documents"]
    assert (d["action"], d["cause"]) == ("skipped", "the document is no longer active")
    m = gct("sheet", "map", doc, "--sheet", "m", *MAP, *WHO)
    assert m.code == layout.REFUSED and f"Document {doc} is archived." in m.err and "gct doc restore" in m.err
    _, mappings, rows, hidden = outputs()
    assert mappings == [] and rows == [] and [(h["document_id"], h["claims"], h["review_records"]) for h in hidden] == [(doc, 2, 1)]
    assert gct("doc", "restore", doc, *WHO).code == 0
    assert outputs() == before


# AC 7
def test_link_reads_the_cell_under_the_current_mapping(acme, gct, db, make_file):
    doc = add(gct, make_file, "m.csv", csv_bytes(ROWS))
    gct("sheet", "map", doc, "--sheet", "m", *MAP, *WHO)
    gct("extract", doc)
    r = gct("link", doc, "--json").data["documents"][0]
    assert (r["refs"], r["matched"], r["cached"]) == (2, 2, 0)
    assert gct("link", doc, "--json").data["documents"][0]["cached"] == 2
    gct("sheet", "map", doc, "--sheet", "m", "--metric", "Metric", "--value", "Period", *WHO)
    r = gct("link", doc, "--json").data["documents"][0]
    assert (r["checked"], r["cited"]) == (2, 2)
    c = claims(gct, doc)["s1r2"]
    assert (c["source_match"], c["source_match_reason"]) == (
        "cited", "cell D2 under mapping #2 reads FY 2023-24, not the claim's value")


# AC 8, AC 9
def test_privacy_and_the_published_version(acme, gct, db, ws, make_file):
    doc = add(gct, make_file, "m.csv", csv_bytes(ROWS))
    assert gct("doc", "show", doc, "--json").data["document"]["privacy"] == "private"
    gct("sheet", "map", doc, "--sheet", "m", *MAP, *WHO)
    gct("extract", doc)
    built = gct("publish", "build", "--json").data
    path = published.version_path(ws, built["version"])
    conn = published.open_version(path)
    try:
        assert conn.execute("SELECT value FROM meta WHERE key = 'projection_schema'").fetchone()[0] == "15"
        assert conn.execute("SELECT privacy FROM document WHERE id = ?", (doc,)).fetchone()[0] == "private"
        assert dict(conn.execute("SELECT locator, note FROM claim")) == {"s1r2": "meter log p3", "s1r3": None}
        assert [tuple(r) for r in conn.execute("SELECT sheet, cell FROM evidence_ref ORDER BY id")] == [("m", "B2"), ("m", "B3")]
        m = conn.execute("SELECT * FROM sheet_mapping").fetchone()
        assert (m["value_col"], m["contributor_name"], m["contributor_organisation"]) == ("Value", "Ana", "Acme audit")
        assert "contributor_version_id" not in m.keys()
    finally:
        conn.close()
    mark = built["history_mark"]
    gct("sheet", "map", doc, "--sheet", "m", "--metric", "Metric", "--value", "Value", *WHO)
    assert gct("publish", "status", "--json").data["stale"] is True
    rebuilt = gct("publish", "build", "--json").data
    assert rebuilt["history_mark"] != mark
    assert gct("publish", "restore", "--json").code == 0
    assert gct("publish", "build").code == 0
