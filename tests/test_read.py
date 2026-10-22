import hashlib
import json
import sqlite3

import pytest

from conftest import PDF, grid, make_pdf
from gct.ladder import quality
from gct.stages import read
from gct.workspace import layout, runs, store

TEXT = {"text": [(72, 72, "Scope 1 emissions fell by 12 percent")]}
TABLE = grid(72, 100, [80, 80], [20, 20], [["Metric", "FY24"], ["Scope 1", "1,234"]])
THREE = make_pdf([TEXT, {}, TABLE])


def count(db, table):
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def artifact_files(ws):
    return sorted(p for p in (ws / "artifacts").rglob("*") if p.is_file())


@pytest.fixture
def add(gct, make_file):
    gct("company", "add", "Acme")

    def add(name, content=THREE, company="Acme"):
        r = gct("doc", "add", make_file(name, content), "--company", company, "--json")
        assert r.code == 0
        return r.data["items"][0]["document"]["id"]

    return add


def test_migration_5_applies_to_a_schema_4_workspace(tmp_path, gct):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    conn = store.connect(root / layout.DB_NAME)
    assert store.migrate(conn, up_to=4) == [1, 2, 3, 4]
    conn.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    conn.close()
    assert gct("company", "list", "--workspace", root).code == 0
    conn = store.connect(root / layout.DB_NAME)
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 14
    (run,) = runs.list_runs(conn)
    assert run["command"] == "workspace upgrade"
    assert [e["message"] for e in runs.show_run(conn, run["id"])["events"] if e["kind"] == "note"] == [
        "applied migration 5", "applied migration 6", "applied migration 7", "applied migration 8", "applied migration 9",
        "applied migration 10", "applied migration 11", "applied migration 12", "applied migration 13",
        "applied migration 14"]
    conn.close()


def test_three_page_fixture_reads_correctly(ws, db, gct, add):
    doc = add("r.pdf")
    r = gct("read", "--json")
    assert r.code == 0 and r.data["status"] == "ok"
    (d,) = r.data["documents"]
    assert (d["action"], d["pages"], d["read"], d["cached"], d["flagged"], d["failed"]) == ("read", 3, 3, 0, 1, 0)
    assert d["flags"] == {"no_text": 1}
    rows = db.execute("SELECT * FROM page ORDER BY page_number").fetchall()
    assert [(p["page_number"], p["rung"], p["method"], p["config_version"]) for p in rows] == [
        (n, 1, "pdfplumber", read.read_config()) for n in (1, 2, 3)
    ]
    assert [json.loads(p["flags"]) for p in rows] == [[], ["no_text"], []]
    files = artifact_files(ws)
    assert len(files) == 3
    for f in files:
        assert f.name == hashlib.sha256(f.read_bytes()).hexdigest() + ".json"
    arts = {a["id"]: a for a in db.execute("SELECT * FROM artifact")}
    readings = []
    for p in rows:
        a = arts[p["artifact_id"]]
        path = ws / a["path"]
        assert a["document_id"] == doc and path.name == a["sha256"] + ".json" and path.stat().st_size == a["size_bytes"]
        readings.append(json.loads(path.read_text(encoding="utf-8")))
    for n, reading in enumerate(readings, 1):
        assert set(reading) == {"page", "width", "height", "text", "words", "tables"} and reading["page"] == n
        assert (reading["width"], reading["height"]) == (612, 792)
    word = readings[0]["words"][0]
    assert set(word) == {"text", "x0", "top", "x1", "bottom", "dir", "col"} and word["text"] == "Scope"
    assert abs(word["x0"] - 72) <= 1 and abs(word["top"] - 62.48) <= 1
    assert readings[1]["words"] == [] and readings[1]["text"] == ""
    (table,) = readings[2]["tables"]
    assert table["rows"] == [["Metric", "FY24"], ["Scope 1", "1,234"]]
    x0, top, x1, bottom = table["bbox"]
    assert x0 <= 72 and top <= 100 and x1 >= 232 and bottom >= 140
    assert "1 pages without text" in gct("read", "1").out.splitlines()


def test_second_read_is_cached(ws, db, gct, add):
    add("r.pdf")
    gct("read")
    before = {t: count(db, t) for t in ("page", "artifact", "attempt")}
    files = artifact_files(ws)
    r = gct("read", "--json")
    assert r.code == 0
    (d,) = r.data["documents"]
    assert (d["read"], d["cached"]) == (0, 3)
    assert {t: count(db, t) for t in before} == before and artifact_files(ws) == files


def test_same_bytes_for_another_company_share_files(ws, db, gct, add):
    add("r.pdf")
    gct("read")
    files = artifact_files(ws)
    gct("company", "add", "Beta")
    other = add("r.pdf", company="Beta")
    r = gct("read", other, "--json")
    assert r.code == 0 and r.data["documents"][0]["read"] == 3
    assert artifact_files(ws) == files
    assert count(db, "artifact") == 6
    assert count(db, "artifact WHERE document_id = ?".replace("?", str(other))) == 3


def test_changed_threshold_reads_again(ws, db, gct, add, monkeypatch):
    doc = add("r.pdf")
    gct("read")
    old = read.read_config()
    monkeypatch.setattr(quality, "FRAGMENT_MIN_TOKENS", 1)
    monkeypatch.setattr(quality, "FRAGMENT_MAX_LEN", 20)
    assert read.read_config() != old
    r = gct("read", "--json")
    assert r.code == 0 and r.data["documents"][0]["read"] == 3
    configs = [p[0] for p in db.execute("SELECT config_version FROM page ORDER BY id")]
    assert configs == [old] * 3 + [read.read_config()] * 3
    newest = gct("doc", "pages", doc, "--json").data["pages"]
    assert [p["flags"] for p in newest] == [["fragmented_text"], ["no_text"], ["fragmented_text"]]
    assert count(db, "artifact") == 3  # same bytes, same document: rows reused


def test_damaged_document_fails_and_the_good_one_is_read(ws, db, gct, add):
    bad = add("bad.pdf", PDF)
    good = add("good.pdf")
    for argv in (("read",), ("read", "--json")):
        r = gct(*argv)
        assert r.code == 4
        assert "Error" not in r.out + r.err and "Traceback" not in r.out + r.err
    by_id = {d["id"]: d for d in r.data["documents"]}
    assert by_id[bad]["action"] == "failed" and by_id[bad]["cause"] == read.NOT_OPENED
    assert by_id[good]["action"] == "read" and by_id[good]["cached"] == 3
    failures = db.execute("SELECT item, message FROM run_event WHERE kind = 'failure' AND stage = 'read'").fetchall()
    assert [tuple(f) for f in failures] == [(str(bad), read.NOT_OPENED)] * 2
    assert f"failed {bad}: bad.pdf: {read.NOT_OPENED}" in gct("read").out


def test_page_failure_then_retry(ws, db, gct, add, monkeypatch):
    add("r.pdf")
    real = read.read_page

    def flaky(page):
        if page.page_number == 2:
            raise ValueError("boom")
        return real(page)

    monkeypatch.setattr(read, "read_page", flaky)
    r = gct("read", "--json")
    assert r.code == 4 and r.data["status"] == "partial" and r.data["next_action"] == read.RETRY
    (d,) = r.data["documents"]
    assert (d["read"], d["failed"]) == (2, 1)
    assert db.execute("SELECT outcome FROM attempt WHERE item = '1:2'").fetchone()[0] == "failed"
    assert db.execute("SELECT COUNT(*) FROM run_event WHERE kind = 'failure' AND item = '1:2'").fetchone()[0] == 1
    monkeypatch.setattr(read, "read_page", real)
    r = gct("read", "--json")
    assert r.code == 0
    (d,) = r.data["documents"]
    assert (d["read"], d["cached"]) == (1, 2)
    assert db.execute("SELECT COUNT(*) FROM run_event WHERE kind = 'retry' AND item = '1:2'").fetchone()[0] == 1


def test_interrupted_read_keeps_committed_pages(ws, db, gct, add, monkeypatch):
    add("r.pdf")
    real = read.read_page

    def interrupt(page):
        if page.page_number == 2:
            raise KeyboardInterrupt
        return real(page)

    monkeypatch.setattr(read, "read_page", interrupt)
    with pytest.raises(KeyboardInterrupt):
        gct("read")
    assert [p["page_number"] for p in db.execute("SELECT page_number FROM page")] == [1]
    assert db.execute("SELECT outcome FROM attempt WHERE item = '1:1'").fetchone()[0] == "ok"
    assert runs.list_runs(store.connect(ws / "workspace.db"))[0]["outcome"] == "interrupted"
    monkeypatch.setattr(read, "read_page", real)
    r = gct("read", "--json")
    assert r.code == 0 and (r.data["documents"][0]["read"], r.data["documents"][0]["cached"]) == (2, 1)
    assert [p[0] for p in db.execute("SELECT page_number FROM page ORDER BY page_number")] == [1, 2, 3]


def test_page_row_without_attempt_is_reused(ws, db, gct, add, monkeypatch):
    """A crash after the page row commits and before its attempt: the retry inserts no second row."""
    add("r.pdf")
    from gct import stages

    real = stages._attempt

    def crash(conn, run_id, key, outcome, *a):
        if key[1] == "1:1" and outcome == "ok":
            raise KeyboardInterrupt
        return real(conn, run_id, key, outcome, *a)

    monkeypatch.setattr(stages, "_attempt", crash)
    with pytest.raises(KeyboardInterrupt):
        gct("read")
    assert count(db, "page") == 1 and count(db, "attempt") == 0
    monkeypatch.setattr(stages, "_attempt", real)
    assert gct("read").code == 0
    assert [p[0] for p in db.execute("SELECT page_number FROM page ORDER BY id")] == [1, 2, 3]


def test_quality_flags(ws, db, gct, add):
    fragmented = {"text": [(40 + 15 * i, 100, "x") for i in range(30)]}
    sparse = grid(72, 100, [60, 60, 60], [20, 20, 20], [["only", "", ""], ["", "", ""], ["", "", ""]])
    doc = add("q.pdf", make_pdf([fragmented, sparse, TEXT, {}, {}]))
    r = gct("read", "--json")
    assert r.data["documents"][0]["flags"] == {"fragmented_text": 1, "no_text": 2, "sparse_tables": 1}
    assert [p["flags"] for p in read.pages(store.connect(ws / "workspace.db"), doc)] == [
        ["fragmented_text"], ["sparse_tables"], [], ["no_text"], ["no_text"]
    ]
    text = gct("read").out.splitlines()
    assert "2 pages without text" in text and "Flagged pages: fragmented_text 1, no_text 2, sparse_tables 1" in text
    out = gct("doc", "pages", doc).out.splitlines()
    assert out[0] == "p1  rung 1  pdfplumber  words 30  tables 0  flags fragmented_text"
    assert "Flagged pages: fragmented_text 1, no_text 2, sparse_tables 1" in out and "2 pages without text" in out


def test_selection(ws, db, gct, add):
    a = add("a.pdf")
    gct("company", "add", "Beta")
    b = add("b.pdf", make_pdf([TEXT]), company="Beta")
    csv = add("e.csv", b"a,b\n1,2\n")
    r = gct("read", "--company", "Beta", "--json")
    assert r.code == 0 and [d["id"] for d in r.data["documents"]] == [b]
    r = gct("read", "--json")
    assert r.code == 0 and [(d["id"], d["action"]) for d in r.data["documents"]] == [
        (a, "read"), (b, "read"), (csv, "skipped")
    ]
    assert r.data["documents"][2]["cause"] == "not a PDF"
    assert f"skipped {csv}: e.csv: not a PDF" in gct("read").out
    runs_before = count(db, "run")
    assert gct("read", 99).code == 3 and gct("read", "--company", "Nobody").code == 3
    assert count(db, "run") == runs_before
    assert gct("read", "x").code == 2


def test_nothing_to_read(ws, gct):
    r = gct("read")
    assert r.code == 0 and r.out.strip() == "Nothing to read."


def test_doc_pages(ws, db, gct, add):
    doc = add("r.pdf")
    r = gct("doc", "pages", doc)
    assert r.code == 0 and r.out.strip() == f"No pages read yet. Run: gct read {doc}"
    assert gct("doc", "pages", 99).code == 3
    gct("read")
    r = gct("doc", "pages", doc, "--json")
    assert r.data["document"] == doc
    assert [(p["page_number"], p["rung"], p["method"], p["tables"], p["flags"]) for p in r.data["pages"]] == [
        (1, 1, "pdfplumber", 0, []), (2, 1, "pdfplumber", 0, ["no_text"]), (3, 1, "pdfplumber", 1, [])
    ]
    shas = {a[0] for a in db.execute("SELECT sha256 FROM artifact")}
    assert {p["artifact"] for p in r.data["pages"]} == shas
    assert gct("doc", "pages", doc).out.splitlines()[1] == "p2  rung 1  pdfplumber  words 0  tables 0  flags no_text"


def test_run_show_lists_every_page(ws, gct, add):
    add("r.pdf")
    gct("read")
    r = gct("run", "show", 2, "--json").data
    assert r["command"] == "read" and r["methods"] == ["pdfplumber"]
    assert [e["item"] for e in r["events"] if e["kind"] == "item"] == ["1:1", "1:2", "1:3"]


def test_page_and_artifact_are_append_only(ws, db, gct, add):
    add("r.pdf")
    gct("read")
    for table in ("page", "artifact"):
        for stmt in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
                db.execute(stmt)
