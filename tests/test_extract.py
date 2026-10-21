import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from conftest import grid, make_pdf
from test_lock import holder
from gct.stages import extract
from gct.workspace import layout, runs, store

TABLE = grid(72, 100, [160, 80, 80], [20, 20],
             [["", "FY2023-24", "FY2022-23"], ["Scope 1 emissions (tCO2e)", "1,234.5", "1,100"]])
PAGE = {"text": TABLE["text"] + [(72, 300, "Energy consumed 4,560 MWh in 2023"), (72, 340, "Water 1,23,456 kL"),
                                 (300, 780, "12")],
        "lines": TABLE["lines"]}


def count(db, table):
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.fixture
def doc(gct, make_file):
    gct("company", "add", "Acme")
    r = gct("doc", "add", make_file("r.pdf", make_pdf([PAGE])), "--company", "Acme", "--json")
    return r.data["items"][0]["document"]["id"]


def newest(db):
    return {r["locator"]: r for r in db.execute(
        "SELECT c.locator, v.*, e.boxes FROM claim c JOIN claim_version v ON v.claim_id = c.id"
        " JOIN evidence_ref e ON e.claim_version_id = v.id"
        " WHERE v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)")}


# AC 1
def test_migration_7_applies_to_a_version_6_workspace(tmp_path, gct):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    assert store.migrate(c, up_to=6) == [1, 2, 3, 4, 5, 6]
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.close()
    assert gct("company", "list", "--workspace", root).code == 0
    c = store.connect(root / layout.DB_NAME)
    assert c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 10
    c.close()


def test_checks_reject_bad_rows(db, doc, gct):
    gct("read")
    gct("extract")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO claim_version (claim_id, run_id, method, config_version, metric_text, value_text,"
                   " reporting_boundary, created_at) VALUES (1, 1, 'm', 'c', 'x', '1', 'group', 't')")
    base = "INSERT INTO evidence_ref (claim_version_id, document_id, page_number, boxes, sheet, cell, created_at)" \
           " VALUES (1, 1, ?, ?, ?, ?, 't')"
    for bad in ((1, None, "Sheet1", None), (None, "[]", "Sheet1", "A1"), (None, None, None, None), (1, None, None, "A1")):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(base, bad)
    db.execute(base, (None, None, "Sheet1", "A1"))  # the spreadsheet shape E4 will use


# AC 2, 3, 4 (value)
def test_table_and_text_claims(db, doc, gct):
    gct("read")
    r = gct("extract", "--json")
    assert r.code == 0
    (d,) = r.data["documents"]
    assert (d["pages"], d["extracted"], d["cached"], d["figures"], d["no_box"]) == (1, 1, 0, 4, 0)
    claims = newest(db)
    assert set(claims) == {"t0r1c1", "t0r1c2", "l0w2", "l1w1"}
    words = {w["text"]: w for w in json.loads(_root_read(db))["words"]}
    for loc, printed, value, period in (("t0r1c1", "1,234.5", 1234.5, "FY2023-24"), ("t0r1c2", "1,100", 1100, "FY2022-23")):
        c = claims[loc]
        assert (c["metric_text"], c["unit_text"], c["period_label"], c["value_text"], c["value"]) == (
            "Scope 1 emissions (tCO2e)", "tCO2e", period, printed, value)
        assert (c["method"], c["reporting_boundary"]) == ("rung1-rules", "unknown")
        assert all(c[k] is None for k in ("period_kind", "period_start", "period_end", "metric_key", "boundary_detail"))
        (box,) = json.loads(c["boxes"])
        w = words[printed]
        assert box[0] <= w["x0"] and box[1] <= w["top"] and box[2] >= w["x1"] and box[3] >= w["bottom"]
    energy = claims["l0w2"]
    assert (energy["metric_text"], energy["value_text"], energy["value"], energy["unit_text"], energy["period_label"]) == (
        "Energy consumed", "4,560", 4560, "MWh", "2023")
    assert json.loads(energy["boxes"]) == [[words["4,560"]["x0"], words["4,560"]["top"], words["MWh"]["x1"],
                                            words["MWh"]["bottom"]]]
    indian = claims["l1w1"]
    assert (indian["value_text"], indian["value"], indian["unit_text"]) == ("1,23,456", None, "kL")
    assert not [c for c in claims.values() if c["value_text"] in ("2023", "12")]  # the year, the footer page number


def _root_read(db):
    """The newest reading artifact's JSON text."""
    root = Path(db.execute("PRAGMA database_list").fetchone()["file"]).parent
    return (root / db.execute("SELECT path FROM artifact ORDER BY id DESC LIMIT 1").fetchone()[0]).read_text(encoding="utf-8")


@pytest.mark.parametrize("token, expected", [
    ("1,234.5", ("1,234.5", 1234.5)), ("-12", ("-12", -12.0)), ("0.5", ("0.5", 0.5)), ("1,23,456", ("1,23,456", None)),
    ("1.234,5", ("1.234,5", None)), ("(1,234)", ("(1,234)", None)), ("45%", ("45", 45.0)), ("4,560MWh", ("4,560", 4560.0)),
    ("2023", None), ("FY2023-24", None), ("12th", None), ("2023-24", None),
])
def test_figure_detection_and_parsing(token, expected):
    fig = extract._figure(token)
    assert (fig and (fig[0], extract._value(fig[0]))) == expected


def _cells_reading(cells, words):
    return {"height": 792, "width": 612, "words": words, "text": "",
            "tables": [{"bbox": [0, 0, 300, 40], "rows": [["", "2024"], ["Energy (MWh)", "50"]], "cells": cells}]}


# AC 4 (box): no cell box, or cell words that do not reproduce the figure, leave the location unresolved
@pytest.mark.parametrize("cells, words", [
    ([[None, None], [None, None]], [{"text": "50", "x0": 210, "top": 22, "x1": 220, "bottom": 34}]),
    ([[None, None], [[0, 20, 200, 40], [200, 20, 300, 40]]], [{"text": "50*", "x0": 210, "top": 22, "x1": 225, "bottom": 34}]),
    ([[None, None], [[0, 20, 200, 40], [200, 20, 300, 40]]], []),
])
def test_unresolved_table_box(cells, words):
    (c,) = extract.rules(_cells_reading(cells, words))
    assert (c["value_text"], c["unit_text"], c["period_label"], c["boxes"]) == ("50", "MWh", "2024", None)


def test_unit_column_gives_the_unit():
    reading = {"height": 792, "words": [], "tables": [
        {"bbox": [0, 0, 1, 1], "rows": [["Metric", "Unit", "FY24"], ["Water", "kL", "7"]]}]}
    (c,) = extract.rules(reading)
    assert (c["metric_text"], c["unit_text"], c["period_label"], c["boxes"]) == ("Water", "kL", "FY24", None)


def test_the_unit_attached_to_the_figure_comes_before_the_label_suffix():
    reading = {"height": 792, "words": [], "tables": [{"bbox": [0, 0, 1, 1], "rows": [["", "FY24"], ["Share (MWh)", "45%"]]}]}
    (c,) = extract.rules(reading)
    assert (c["metric_text"], c["value_text"], c["unit_text"]) == ("Share (MWh)", "45", "%")


def test_a_table_without_a_label_column(db, gct, make_file):
    gct("company", "add", "Acme")
    page = grid(72, 100, [80, 80], [20, 20], [["10", "1"], ["54", "4"]])
    gct("doc", "add", make_file("n.pdf", make_pdf([page])), "--company", "Acme")
    gct("read")
    assert gct("extract").code == 0
    claims = newest(db)
    assert set(claims) == {"t0r0c0", "t0r0c1", "t0r1c0", "t0r1c1"}
    assert sorted((loc, c["metric_text"], c["value"]) for loc, c in claims.items()) == [
        ("t0r0c0", None, 10), ("t0r0c1", None, 1), ("t0r1c0", None, 54), ("t0r1c1", None, 4)]


# AC 5
def test_unchanged_readings_are_cached_and_a_new_reading_adds_a_version(ws, db, doc, gct):
    gct("read")
    gct("extract")
    before = (count(db, "claim"), count(db, "claim_version"), count(db, "evidence_ref"))
    r = gct("extract", "--json")
    (d,) = r.data["documents"]
    assert (d["extracted"], d["cached"], d["figures"]) == (0, 1, 4)
    assert (count(db, "claim"), count(db, "claim_version"), count(db, "evidence_ref")) == before
    # A later reading of the same page: the figure changed and the reading has no cell boxes.
    old = db.execute("SELECT * FROM page ORDER BY id DESC LIMIT 1").fetchone()
    reading = json.loads(_root_read(db))
    reading["tables"][0]["rows"][1][1] = "1,300"
    del reading["tables"][0]["cells"]
    data = json.dumps(reading).encode()
    sha = hashlib.sha256(data).hexdigest()
    rel = f"artifacts/{sha[:2]}/{sha}.json"
    (ws / rel).parent.mkdir(parents=True, exist_ok=True)
    (ws / rel).write_bytes(data)
    art = db.execute("INSERT INTO artifact (sha256, kind, document_id, path, size_bytes, created_at)"
                     " VALUES (?, 'reading', ?, ?, ?, 't')", (sha, doc, rel, len(data))).lastrowid
    db.execute("INSERT INTO page (document_id, page_number, rung, method, config_version, width, height, words, tables,"
               " flags, artifact_id, created_at) VALUES (?, 1, 2, 'later', 'c2', ?, ?, ?, ?, '[]', ?, 't')",
               (doc, old["width"], old["height"], old["words"], old["tables"], art))
    db.commit()
    (d,) = gct("extract", "--json").data["documents"]
    assert (d["extracted"], d["cached"], d["no_box"]) == (1, 0, 2)
    assert count(db, "claim") == before[0] and count(db, "claim_version") == before[1] * 2
    versions = db.execute("SELECT v.value_text FROM claim_version v JOIN claim c ON c.id = v.claim_id"
                          " WHERE c.locator = 't0r1c1' ORDER BY v.id").fetchall()
    assert [v[0] for v in versions] == ["1,234.5", "1,300"]
    listed = gct("claims", "list", "--doc", doc)
    assert listed.out.count("cited (no box)") == 2 and "1,300" in listed.out and "1,234.5" not in listed.out


# AC 7
def test_document_without_a_reading_is_skipped_with_the_note(db, doc, gct):
    r = gct("extract", "--json")
    assert r.code == 0 and r.data["status"] == "ok"
    (d,) = r.data["documents"]
    assert (d["action"], d["next_action"], d["failed"]) == ("skipped", "read it first: gct read", 0)
    assert count(db, "claim") == 0
    assert "read it first: gct read" in gct("extract").out
    notes = [r[0] for r in db.execute("SELECT message FROM run_event WHERE kind = 'note' AND stage = 'extract'")]
    assert notes == ["read it first: gct read"] * 2


TWO = make_pdf([{"text": [(72, 300, "Energy used 10 MWh")]}, {"text": [(72, 300, "Water used 20 kL")]}])


@pytest.fixture
def two(gct, make_file):
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("two.pdf", TWO), "--company", "Acme")
    gct("read")
    return 1


def failing(monkeypatch, word, error=ValueError):
    """Make extraction of the page whose text holds word raise."""
    real = extract.rules

    def flaky(reading):
        if word in reading["text"]:
            raise error("boom")
        return real(reading)

    monkeypatch.setattr(extract, "rules", flaky)
    return real


def newest_run(db):
    return db.execute("SELECT MAX(id) FROM run").fetchone()[0]


def test_extract_records_its_selection(db, gct, two):
    gct("extract", 1, "--company", "Acme")
    assert runs.selection(db, newest_run(db)) == {"ids": [1], "company": "Acme"}


def test_resume_an_interrupted_extract(db, gct, two, monkeypatch):
    real = failing(monkeypatch, "Water", KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        gct("extract")
    n = newest_run(db)
    monkeypatch.setattr(extract, "rules", real)
    r = gct("run", "resume", n, "--json")
    assert r.code == 0 and (r.data["run_id"], r.data["of_run"]) == (n + 1, n)
    (d,) = r.data["documents"]
    assert (d["pages"], d["extracted"], d["cached"], d["failed"], d["figures"]) == (2, 1, 1, 0, 2)
    assert runs.selection(db, n + 1) == runs.selection(db, n)
    assert gct("run", "resume", n + 1).code == 4  # it finished


def test_retry_only_the_failed_page_of_an_extract_run(db, gct, two, monkeypatch):
    real = failing(monkeypatch, "Water")
    assert gct("extract").code == 4
    n = newest_run(db)
    monkeypatch.setattr(extract, "rules", real)
    r = gct("run", "retry", n, "--json")
    assert r.code == 0 and (r.data["run_id"], r.data["of_run"]) == (n + 1, n)
    (d,) = r.data["documents"]
    assert (d["pages"], d["extracted"], d["failed"], d["figures"]) == (1, 1, 0, 1)
    assert [i for (i,) in db.execute("SELECT item FROM attempt WHERE run_id = ?", (n + 1,))] == ["1:2"]
    nothing = gct("run", "retry", n + 1, "--json").data
    assert nothing == {"status": "ok", "run_id": None, "of_run": n + 1, "documents": []}


def test_extract_takes_the_workspace_lock_and_claims_list_does_not(ws, gct, two):
    p = holder(ws)
    try:
        r = gct("extract")
        assert r.code == 4 and r.err.startswith("error: ")
        assert gct("claims", "list", "--doc", 1).code == 0
    finally:
        p.kill()
        p.wait()
    assert gct("extract").code == 0


def test_a_failing_page_is_reported_and_retried(ws, db, doc, gct, monkeypatch):
    gct("read")
    rules = extract.rules
    monkeypatch.setattr(extract, "rules", lambda reading: 1 / 0)
    r = gct("extract", "--json")
    assert r.code == 4 and r.data["status"] == "partial" and r.data["next_action"] == extract.RETRY
    assert count(db, "claim") == 0
    monkeypatch.setattr(extract, "rules", rules)
    (d,) = gct("extract", "--json").data["documents"]
    assert (d["extracted"], d["failed"], d["figures"]) == (1, 0, 4)
