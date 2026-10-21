import hashlib
import json
import sqlite3

import pytest

from conftest import grid, make_pdf
from test_extract import PAGE, count, newest_run
from gct.stages import link
from gct.workspace import layout, published, store


@pytest.fixture
def doc(gct, make_file):
    gct("company", "add", "Acme")
    r = gct("doc", "add", make_file("r.pdf", make_pdf([PAGE])), "--company", "Acme", "--json")
    gct("read")
    gct("extract")
    return r.data["items"][0]["document"]["id"]


def statuses(db):
    """{locator: [(status, reason), ...]} for the refs of each claim's newest version, oldest row first."""
    out = {}
    for r in db.execute("SELECT c.locator, s.status, s.reason FROM claim c JOIN claim_version v ON v.claim_id = c.id"
                        " JOIN evidence_ref e ON e.claim_version_id = v.id JOIN source_match s ON s.evidence_ref_id = e.id"
                        " WHERE v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id) ORDER BY s.id"):
        out.setdefault(r[0], []).append((r[1], r[2]))
    return out


def add_reading(ws, db, doc, change):
    """A later reading of page 1, made by hand from the newest one after change(reading)."""
    old = db.execute("SELECT p.*, a.path FROM page p JOIN artifact a ON a.id = p.artifact_id ORDER BY p.id DESC LIMIT 1").fetchone()
    reading = json.loads((ws / old["path"]).read_text(encoding="utf-8"))
    change(reading)
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


def hand_claim(db, doc, page, locator):
    claim = db.execute("INSERT INTO claim (company_id, document_id, page_number, locator, created_at)"
                       " VALUES (1, ?, ?, ?, 't')", (doc, page, locator)).lastrowid
    version = db.execute("INSERT INTO claim_version (claim_id, run_id, method, config_version, value_text, created_at)"
                         " VALUES (?, 1, 'hand', 'c', '7', 't')", (claim,)).lastrowid
    db.execute("INSERT INTO evidence_ref (claim_version_id, document_id, page_number, boxes, created_at)"
               " VALUES (?, ?, ?, '[[1, 1, 2, 2]]', 't')", (version, doc, page))
    db.commit()


# AC 1
def test_migration_8_applies_to_a_version_7_workspace(tmp_path, gct):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    assert store.migrate(c, up_to=7) == [1, 2, 3, 4, 5, 6, 7]
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.close()
    assert gct("company", "list", "--workspace", root).code == 0
    c = store.connect(root / layout.DB_NAME)
    assert c.execute("SELECT 1 FROM schema_version WHERE version = 8").fetchone()
    c.close()


def test_source_match_rejects_changes_and_bad_status(db, doc):
    for stmt in ("UPDATE source_match SET reason = 'x'", "DELETE FROM source_match"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
            db.execute(stmt)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO source_match (evidence_ref_id, run_id, status, config_version, created_at)"
                   " VALUES (1, 1, 'verified', 'c', 't')")


# AC 2
def test_table_claims_are_matched_and_a_cell_without_a_box_is_cited(ws, db, doc, gct):
    s = statuses(db)
    assert s["t0r1c1"] == s["t0r1c2"] == [("matched", None)]
    add_reading(ws, db, doc, lambda r: r["tables"][0].pop("cells"))
    gct("extract")
    s = statuses(db)
    # A figure that lost its box is not the boxed claim (story 3.5 identity rule): a new claim, the old one not found.
    assert s["t0r1c1~2"] == s["t0r1c2~2"] == [("cited", "no box")]
    assert s["t0r1c1"] == [("matched", None)]
    line = next(x for x in gct("claims", "list", "--doc", doc, "--state", "current").out.splitlines() if "1,234.5" in x)
    assert line.endswith("unknown  cited (no box)")
    current = gct("claims", "list", "--doc", doc, "--state", "current", "--json").data["claims"]
    c = next(c for c in current if c["value_text"] == "1,234.5")
    assert (c["source_match"], c["source_match_reason"], c["boxes"]) == ("cited", "no box", None)


# AC 3b
def test_attached_and_separate_units_are_matched(db, gct, make_file):
    gct("company", "add", "Acme")
    page = grid(72, 100, [160, 80], [20, 20], [["", "FY24"], ["Renewable share", "45%"]])
    page["text"] += [(72, 300, "Energy consumed 4,560 MWh in 2023")]
    gct("doc", "add", make_file("u.pdf", make_pdf([page])), "--company", "Acme")
    gct("read")
    gct("extract")
    rows = db.execute("SELECT v.value_text, v.unit_text, s.status FROM claim_version v JOIN evidence_ref e"
                      " ON e.claim_version_id = v.id JOIN source_match s ON s.evidence_ref_id = e.id ORDER BY v.id").fetchall()
    assert [tuple(r) for r in rows] == [("45", "%", "matched"), ("4,560", "MWh", "matched")]


def test_only_the_stored_unit_counts():
    words = [{"text": "4,560", "x0": 10, "top": 10, "x1": 40, "bottom": 20, "dir": "ltr"},
             {"text": "GWh.", "x0": 42, "top": 10, "x1": 60, "bottom": 20, "dir": "ltr"}]
    ref = {"sheet": None, "boxes": [[10, 10, 60, 20]], "value_text": "4,560", "unit_text": "MWh"}
    assert link.match(ref, {"words": words}) == ("cited", "box does not reproduce the figure")
    assert link.match({**ref, "unit_text": "GWh"}, {"words": words}) == ("matched", None)  # trailing full stop stripped
    assert link.match({**ref, "unit_text": None}, {"words": words}) == ("cited", "box does not reproduce the figure")
    assert link.match({**ref, "boxes": None, "sheet": "Sheet1"}, None) == ("unresolved", "spreadsheet check not built")


# AC 3, 5
def test_a_moved_figure_is_cited_and_the_old_row_kept(ws, db, doc, gct):
    first = gct("link", "--json")
    assert first.code == 0
    rows = count(db, "source_match")

    def move(reading):
        for w in reading["words"]:
            if w["text"] == "1,234.5":
                w["top"] += 200
                w["bottom"] += 200

    add_reading(ws, db, doc, move)
    (d,) = gct("link", "--json").data["documents"]
    assert (d["refs"], d["checked"], d["cached"], d["failed"]) == (4, 4, 0, 0)
    assert statuses(db)["t0r1c1"] == [("matched", None), ("cited", "box does not reproduce the figure")]
    assert statuses(db)["t0r1c2"] == [("matched", None)] * 2  # checked again against the new reading
    assert count(db, "source_match") == rows + 4
    again = count(db, "source_match")
    (d,) = gct("link", "--json").data["documents"]
    assert (d["checked"], d["cached"]) == (0, 4) and count(db, "source_match") == again


def test_a_page_back_on_an_earlier_reading_is_checked_again(ws, db, doc, gct):
    first = db.execute("SELECT * FROM page ORDER BY id DESC LIMIT 1").fetchone()  # reading A
    gct("link")  # an ok link attempt for every ref against reading A

    def move(reading):
        for w in reading["words"]:
            if w["text"] == "1,234.5":
                w["top"] += 200
                w["bottom"] += 200

    add_reading(ws, db, doc, move)  # reading B
    gct("link")
    assert statuses(db)["t0r1c1"][-1] == ("cited", "box does not reproduce the figure")
    # A later page row points back at artifact A (a re-read that gives the same bytes reuses the artifact)
    db.execute("INSERT INTO page (document_id, page_number, rung, method, config_version, width, height, words, tables,"
               " flags, artifact_id, created_at) VALUES (?, 1, 2, 'later', 'c3', ?, ?, ?, ?, '[]', ?, 't')",
               (doc, first["width"], first["height"], first["words"], first["tables"], first["artifact_id"]))
    db.commit()
    (d,) = gct("link", "--json").data["documents"]
    assert (d["checked"], d["cached"], d["matched"], d["cited"]) == (4, 0, 4, 0)
    assert statuses(db)["t0r1c1"][-1] == ("matched", None)
    (d,) = gct("link", "--json").data["documents"]
    assert (d["checked"], d["cached"]) == (0, 4)


# AC 4
def test_a_page_without_a_reading_is_unresolved(db, doc, gct, make_file):
    gct("doc", "add", make_file("unread.pdf", make_pdf([{"text": [(72, 72, "x")]}])), "--company", "Acme")
    hand_claim(db, doc, 999, "h1")
    hand_claim(db, 2, 1, "h2")
    r = gct("link", "--json")
    assert r.code == 0
    assert statuses(db)["h1"] == statuses(db)["h2"] == [("unresolved", "page not read: gct read")]
    assert [d["unresolved"] for d in r.data["documents"]] == [1, 1]


# AC 6
def test_publish_carries_the_newest_status(ws, db, doc, gct):
    v1 = gct("publish", "build", "--json").data
    mark = published.history_mark(db)

    def move(reading):
        for w in reading["words"]:
            if w["text"] == "1,234.5":
                w["text"] = "1,234.6"

    add_reading(ws, db, doc, move)
    gct("link")
    assert published.history_mark(db) != mark
    v = gct("publish", "build", "--json").data
    path = ws / "published" / f"v{v['version']}.db"
    conn = published.open_version(path)
    rows = dict(conn.execute("SELECT c.locator, e.source_match || '|' || COALESCE(e.source_match_reason, '')"
                             " FROM evidence_ref e JOIN claim c ON c.claim_version_id = e.claim_version_id"))
    assert conn.execute("SELECT value FROM meta WHERE key = 'projection_schema'").fetchone()[0] == "7"
    conn.close()
    assert rows["t0r1c1"] == "cited|box does not reproduce the figure" and rows["t0r1c2"] == "matched|"
    assert v1["history_mark"] != v["history_mark"]


def test_retry_only_the_failed_refs_of_a_link_run(db, doc, gct, monkeypatch):
    real = link.match

    def flaky(ref, reading):
        if ref["value_text"] == "1,100":
            raise ValueError("boom")
        return real(ref, reading)

    monkeypatch.setattr(link, "match", flaky)
    r = gct("link", "--json")
    assert r.code == 4 and r.data["status"] == "partial" and r.data["next_action"] == link.RETRY
    n = newest_run(db)
    monkeypatch.setattr(link, "match", real)
    r = gct("run", "retry", n, "--json")
    assert r.code == 0 and (r.data["run_id"], r.data["of_run"]) == (n + 1, n)
    (d,) = r.data["documents"]
    assert (d["refs"], d["checked"], d["failed"]) == (1, 1, 0)
    assert gct("run", "resume", n + 1).code == 4  # it finished


def test_resume_an_interrupted_link(db, doc, gct, monkeypatch):
    real = link.match

    def stop(ref, reading):
        if ref["value_text"] == "1,100":
            raise KeyboardInterrupt
        return real(ref, reading)

    monkeypatch.setattr(link, "match", stop)
    with pytest.raises(KeyboardInterrupt):
        gct("link")
    n = newest_run(db)
    monkeypatch.setattr(link, "match", real)
    r = gct("run", "resume", n)
    assert r.code == 0 and r.out.splitlines()[0] == f"Run {n + 1} resumes run {n}."
