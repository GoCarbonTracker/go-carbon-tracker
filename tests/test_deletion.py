"""Story 4.5: permanent deletion. Destructive, so synthetic workspaces under pytest's temporary folder only; no real
report and no copy of a real workspace is used."""
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from conftest import PDF, make_pdf
from old_code import old_tree, run_old  # noqa: F401 (old_tree is a fixture)
from test_intake import web  # noqa: F401 (a fixture)
from test_match import BOTH, SCOPE_1, WHO, ids, ready, series
from test_messages import internal_names
from test_restate import add, page_of
from gct.stages import deletion
from gct.workspace import intake, layout, published, registry, runs, store
from gct.workspace.layout import REFUSED, GctError

# Canaries, planted in the deleted document only (AC 9).
LOGICAL, METRIC, VALUE, BASIS, QUOTE_CANARY = "zqlogical", "zqmetric", "98,761", "zqbasis", "zqquote"
CORRECTED, CAPACITY, WHY = "98,762", "zqcap", "zqwhy"
FOLDER, FILE = "zqfolder", "zqfile"  # D is added as a folder holding one file, with --name LOGICAL (review HIGH 1)
CANARIES = (LOGICAL, METRIC, VALUE, BASIS, QUOTE_CANARY, CORRECTED, CAPACITY, WHY, FOLDER, FILE)
NOTE = f"The figures for the previous year have been restated {QUOTE_CANARY} due to reclassification."
QUOTE = f"have been restated {QUOTE_CANARY}"
LABEL = f"Total Scope 1 emissions {METRIC}"
# A contributor whose capacity and rationale quote the document (Codex 190: cleared with it).
QUOTING = ("--as", "ana", "--capacity", f"{CAPACITY} reading {METRIC}", "--rationale", f"{WHY}: p1 says {METRIC}")
PURGE = published.purge


def d_bytes() -> bytes:
    return make_pdf([page_of([[LABEL, "tCO2e", VALUE]], periods=BOTH[1:], boundary=None,
                             lines=[(40, 100, f"Reporting boundary: Report {BASIS} is prepared on a standalone basis."),
                                    (40, 150, NOTE)])])


def token(db, doc: int) -> str:
    return db.execute("SELECT sha256 FROM document WHERE id = ?", (doc,)).fetchone()[0][:12]


@pytest.fixture
def world(ws, db, gct, make_file, tmp_path):
    """AC 9's layout: Acme with A (a series shared with D) and D (the canaries), Beta with E (D's file under another
    company, never read), a restatement record with a surviving partner, every review type on D, a gap confirmation
    that looked in D, a page image of D's file, two published versions and an exports/ file."""
    gct("company", "add", "Acme")
    gct("company", "add", "Beta")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")
    a = add(gct, make_file, "a.pdf", [SCOPE_1])
    folder = tmp_path / FOLDER
    folder.mkdir()
    (folder / f"{FILE}.pdf").write_bytes(d_bytes())
    d = gct("doc", "add", folder, "--name", LOGICAL, "--company", "Acme", "--json").data["items"][0]["document"]["id"]
    ready(gct, scoped={a})  # D's boundary statement has no declared pages: its claim is an uncertain item
    claim = ids(gct, d)[(LABEL, "FY 2023-24")]
    (item,) = gct("match", "review", "--json").data["items"]
    assert gct("match", "link", claim, "--series", item["series"], *QUOTING).code == 0
    assert gct("correct", claim, "--value", CORRECTED, *QUOTING).code == 0
    assert gct("infer", "resolve", claim, "--field", "boundary", "--boundary", "standalone", *QUOTING).code == 0
    ready(gct, scoped={a})
    other = ids(gct, a)[(SCOPE_1[0], "FY 2023-24")]
    r = gct("restate", "record", "--original", other, "--restated", claim, "--page", 1, "--quote", QUOTE, *QUOTING)
    assert r.code == 0, r.err
    assert gct("expect", "add", "--company", "Acme", "--metric", "water withdrawal", "--doc", a, d).code == 0
    for doc, who in ((a, WHO), (d, QUOTING)):
        assert gct("pages", "accept", "--doc", doc, "--pages", "1", "--type", "figures", *who).code == 0
    assert gct("gap", "confirm", "1", *QUOTING).code == 0
    # Added last, so it is never read: a reading of it would hold the same text as D's, as Beta's own record.
    e = gct("doc", "add", make_file("e.pdf", d_bytes()), "--company", "Beta", "--json").data["items"][0]["document"]["id"]
    sha =db.execute("SELECT sha256 FROM document WHERE id = ?", (d,)).fetchone()[0]
    render = ws / "artifacts" / "pages" / sha / "1@1.5.png"
    render.parent.mkdir(parents=True)
    render.write_bytes(b"\x89PNG not a real image")
    for _ in range(2):
        assert gct("publish", "build").code == 0
    (ws / "exports" / "shared.csv").write_text(f"{LOGICAL},{VALUE}\n")
    return {"a": a, "d": d, "e": e, "claim": claim, "other": other, "sha": sha, "render": render}


def files(ws) -> list[Path]:
    return sorted(p for p in ws.rglob("*") if p.is_file())


def snapshot(db) -> dict:
    """{table: {rowid: row}} of every table."""
    return {t: {r["_r"]: {k: r[k] for k in r.keys() if k != "_r"} for r in db.execute(f"SELECT rowid AS _r, * FROM {t}")}
            for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}


def scan(ws, skip=(), canaries=CANARIES) -> set:
    """The canaries found in the bytes of every file under the workspace except exports/ (and skip)."""
    found = set()
    for p in files(ws):
        if "exports" in p.relative_to(ws).parts or p in skip:
            continue
        data = p.read_bytes()
        found |= {c for c in canaries if c.encode() in data}
    return found


def delete(gct, db, doc, *extra):
    return gct("doc", "delete", doc, "--confirm", token(db, doc), *WHO, *extra)


# AC 1
def test_migration_16_applies_after_15_and_its_tables_are_append_only(tmp_path, gct, db):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    assert store.migrate(c, up_to=15) == list(range(1, 16))
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.close()
    assert gct("doc", "list", "--workspace", root).code == 0
    c = store.connect(root / layout.DB_NAME)
    assert [r[0] for r in c.execute("SELECT version FROM schema_version ORDER BY version")][-7:] == [15, 16, 17, 18, 19, 20, 21]
    (run,) = runs.list_runs(c)
    assert [e["message"] for e in runs.show_run(c, run["id"])["events"] if e["kind"] == "note"] == [
        "applied migration 16", "applied migration 17", "applied migration 18", "applied migration 19",
        "applied migration 20", "applied migration 21"]
    c.close()
    db.execute("INSERT INTO company (name, created_at) VALUES ('Acme', 't')")
    db.execute("INSERT INTO document (company_id, logical_name, version, sha256, kind, file_type, privacy, size_bytes,"
               " created_at) VALUES (1, 'a.pdf', 1, 'x', 'report', 'pdf', 'private', 1, 't')")
    db.execute("INSERT INTO document_state (document_id, state, at) VALUES (1, 'deleted', 't')")
    db.execute("INSERT INTO document_deletion (document_state_id, plan, created_at) VALUES (1, '{}', 't')")
    db.execute("INSERT INTO document_deletion_step (deletion_id, step, detail, created_at) VALUES (1, 'files', '{}', 't')")
    for table in ("document_deletion", "document_deletion_step"):
        for stmt in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
                db.execute(stmt)
    with pytest.raises(sqlite3.IntegrityError):  # one row per step
        db.execute("INSERT INTO document_deletion_step (deletion_id, step, detail, created_at) VALUES (1, 'files', '{}', 't')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO document_deletion_step (deletion_id, step, detail, created_at) VALUES (1, 'other', '{}', 't')")


# AC 3
def test_every_table_and_column_is_classified(ws, db, gct, make_file):
    cls = deletion.classification()
    for t, (_, values) in deletion.CLEAR.items():
        assert not set(values) & set(deletion.KEPT[t].split()), t
    tables = [t for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    assert set(tables) == set(cls)
    for t in tables:
        assert {r[1] for r in db.execute(f"PRAGMA table_info({t})")} == set(cls[t]), t
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme")
    assert gct("publish", "build").code == 0
    v = published.open_version(ws / "published" / "v1.db")
    try:
        built = {t: {r[1] for r in v.execute(f"PRAGMA table_info({t})")}
                 for (t,) in v.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    finally:
        v.close()
    assert built == {t: set(roles) for t, roles in deletion.PROJECTION.items()}
    doc = (Path(__file__).resolve().parent.parent / "docs" / "deletion.md").read_text(encoding="utf-8")
    for t in [*cls, *deletion.PROJECTION]:
        assert f"`{t}`" in doc, t


# AC 2
def test_the_plan_writes_nothing_and_shows_what_goes_and_stays(ws, db, gct, world):
    d = world["d"]
    before, listing = snapshot(db), files(ws)
    r = gct("doc", "delete", d)
    assert r.code == 4 and "error: Nothing was deleted" in r.err
    assert f"next: Delete it with: gct doc delete {d} --confirm {token(db, d)} --as KEY" in r.err
    for words in ("takes it out of every active output", "claims", "claim version:", "review record",
                  "Kept: the company, contributors, expectations", f"cleared with document {d}",
                  "none of the original (another document has the same file)",
                  "reading files", "none of its page images", "Published versions it is removed from: 1, 2",
                  "Copies already exported or shared, including files in exports/, cannot be recalled by GCT.",
                  "do not quote the document", f"Confirmation token: {token(db, d)}"):
        assert words in r.out, words
    assert [n for n in internal_names(ws) if n in r.out + r.err] == []
    j = gct("doc", "delete", d, "--json")
    assert j.code == 4 and j.data["status"] == "plan" and j.data["token"] == token(db, d)
    assert j.data["files"] == {"files": {"remove": 0, "keep": 1}, "artifacts": {"remove": 1, "keep": 0},
                               "renders": {"remove": 0, "keep": 1}}  # E has the same file
    assert j.data["versions"] == [1, 2] and j.data["clears"]["claim_version"] == 2
    wrong = gct("doc", "delete", d, "--confirm", "000000000000", *WHO)
    assert wrong.code == 4 and "not the confirmation token" in wrong.err and f"gct doc delete {d}" in wrong.err
    flags = gct("doc", "delete", d, "--confirm", token(db, d), "--as", "ana")
    assert flags.code == 2 and "Deleting needs --capacity, --rationale." in flags.err
    assert snapshot(db) == before and files(ws) == listing
    assert delete(gct, db, d).code == 0
    again = gct("doc", "delete", d)
    assert again.code == 4 and f"Document {d} was deleted on" in again.err and "cannot be undone" in again.err
    assert delete(gct, db, d).code == 4


# AC 4
def test_the_database_step_clears_content_and_keeps_rows_keys_and_triggers(ws, db, gct, world):
    d = world["d"]
    conn = store.connect(ws / "workspace.db")
    params = deletion._params(conn, registry.get_document(conn, d), deletion.NOT_YET)
    conn.close()
    attached = {t: {r[0] for r in db.execute(f"SELECT rowid FROM {t} WHERE {where}", params)}
                for t, (where, _) in deletion.CLEAR.items()}
    triggers = dict(db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'").fetchall())
    before = snapshot(db)
    r = delete(gct, db, d, "--json")
    assert r.code == 0, r.out
    after = snapshot(db)
    added = {t: len(after[t]) - len(before[t]) for t in after if len(after[t]) != len(before[t])}
    assert set(added) <= {"document_state", "document_state_change", "document_deletion", "document_deletion_step",
                          "published_purge"} and added["document_state"] == added["document_state_change"] == 1
    assert [s for (s,) in db.execute("SELECT step FROM document_deletion_step ORDER BY id")] == list(deletion.STEPS)
    (sid, state, _), = db.execute("SELECT s.id, s.state, s.document_id FROM document_state s JOIN document_deletion x"
                                  " ON x.document_state_id = s.id").fetchall()
    assert state == "deleted"
    own = db.execute("SELECT capacity, rationale FROM document_state_change WHERE document_state_id = ?", (sid,)).fetchone()
    assert tuple(own) == ("analyst", "checked on the page")  # the deleting contributor's own text is kept
    marker = f"cleared with document {d}"
    cls = deletion.classification()
    for t, rows in before.items():
        for rowid, old in rows.items():
            new = after[t][rowid]
            for col, value in old.items():
                if cls[t][col] == "kept" or rowid not in attached.get(t, ()):
                    assert new[col] == value, (t, rowid, col)
                elif t not in ("run_event", "attempt"):
                    assert new[col] in (None, "", "unknown") or new[col].startswith(marker), (t, col, new[col])
    assert attached["claim_version"] and attached["inference_review"] and attached["match_review"]
    assert attached["restatement"] and attached["page_acceptance"] and attached["gap_confirmation"]
    assert attached["run_event"]  # the doc add lines naming its file
    assert dict(db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'").fetchall()) == triggers
    with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
        db.execute("UPDATE claim_version SET value_text = 'x'")


def test_a_failure_after_the_first_clear_leaves_the_database_as_before(ws, db, gct, world, monkeypatch):
    d = world["d"]
    dump = list(db.iterdump())
    real, calls = deletion._clear, []

    def failing(conn, table, params):
        calls.append(table)
        if len(calls) == 2:
            raise sqlite3.OperationalError("injected")
        real(conn, table, params)

    monkeypatch.setattr(deletion, "_clear", failing)
    assert delete(gct, db, d).code == 1  # an unexpected error, logged
    assert len(calls) == 2 and list(db.iterdump()) == dump
    assert gct("doc", "show", d, "--json").data["document"]["state"] == "registered"


# AC 5
def test_files_go_unless_a_document_not_deleted_uses_them(ws, db, gct, make_file):
    gct("company", "add", "Acme")
    gct("company", "add", "Beta")
    gct("contributor", "add", "ana", "--name", "Ana")
    pdf = make_pdf([page_of([SCOPE_1])])
    d = gct("doc", "add", make_file("d.pdf", pdf), "--company", "Acme", "--json").data["items"][0]["document"]["id"]
    e = gct("doc", "add", make_file("e.pdf", pdf), "--company", "Beta", "--json").data["items"][0]["document"]["id"]
    f = gct("doc", "add", make_file("f.pdf", make_pdf([page_of([SCOPE_1], boundary="consolidated")])), "--company",
            "Acme", "--json").data["items"][0]["document"]["id"]
    assert gct("read", d, f).code == 0
    sha, fsha = (db.execute("SELECT sha256 FROM document WHERE id = ?", (i,)).fetchone()[0] for i in (d, f))
    for s in (sha, fsha):
        (ws / "artifacts" / "pages" / s).mkdir(parents=True)
        (ws / "artifacts" / "pages" / s / "1@1.5.png").write_bytes(b"png")
    reading = ws / db.execute("SELECT path FROM artifact WHERE document_id = ?", (d,)).fetchone()[0]
    assert delete(gct, db, d).code == 0
    # E (Beta) has the same file: the original and its page images stay; D's reading was its own and goes.
    assert registry.stored_path(ws, sha).is_file() and (ws / "artifacts" / "pages" / sha).is_dir()
    assert not reading.exists()
    assert gct("read", e).code == 0  # E reads the same pages into the same content-addressed reading file
    assert reading.is_file()
    freading = ws / db.execute("SELECT path FROM artifact WHERE document_id = ?", (f,)).fetchone()[0]
    assert delete(gct, db, e).code == 0 and delete(gct, db, f).code == 0
    assert not registry.stored_path(ws, sha).exists() and not (ws / "artifacts" / "pages" / sha).exists()
    assert not reading.exists() and not freading.exists() and not registry.stored_path(ws, fsha).exists()
    assert not (ws / "artifacts" / "pages" / fsha).exists()


def test_a_reading_shared_with_a_document_not_deleted_stays(ws, db, gct, make_file):
    gct("company", "add", "Acme")
    gct("company", "add", "Beta")
    gct("contributor", "add", "ana", "--name", "Ana")
    pdf = make_pdf([page_of([SCOPE_1])])
    d = gct("doc", "add", make_file("d.pdf", pdf), "--company", "Acme", "--json").data["items"][0]["document"]["id"]
    gct("doc", "add", make_file("e.pdf", pdf), "--company", "Beta")
    assert gct("read").code == 0
    reading = ws / db.execute("SELECT path FROM artifact WHERE document_id = ?", (d,)).fetchone()[0]
    r = delete(gct, db, d, "--json")
    assert r.code == 0 and reading.is_file()
    assert json.loads(db.execute("SELECT detail FROM document_deletion_step WHERE step = 'artifacts'").fetchone()[0]) == {
        "removed": 0, "kept": 1}


# AC 6, AC 14
def test_retained_versions_lose_the_document_and_restore_cannot_bring_it_back(ws, db, gct, world):
    d, claim = world["d"], world["claim"]
    versions = [v for (v,) in db.execute("SELECT v.id FROM claim_version v JOIN claim c ON c.id = v.claim_id"
                                         " WHERE c.document_id = ?", (d,))]

    def naming(v: int) -> list:
        conn = published.open_version(ws / "published" / f"v{v}.db")
        try:
            return [t for t, roles in deletion.PROJECTION.items() for col, role in roles.items()
                    if role in ("document", "claim", "version") and conn.execute(
                        f"SELECT COUNT(*) FROM {t} WHERE {col} IN (SELECT value FROM json_each(?))",
                        (json.dumps({"document": [d], "claim": [claim], "version": versions}[role]),)).fetchone()[0]]
        finally:
            conn.close()

    assert {"document", "claim", "comparison", "restatement", "series_point"} <= set(naming(2))
    assert gct("publish", "status", "--json").data["documents"] == 3
    assert delete(gct, db, d).code == 0
    assert naming(1) == naming(2) == []
    assert sorted(map(tuple, db.execute("SELECT version, reason FROM published_purge"))) == [(1, "deletion"), (2, "deletion")]
    # A purged version reports what its file holds now (review LOW 1).
    assert gct("publish", "status", "--json").data["documents"] == 2
    assert "2 companies, 2 documents" in gct("publish", "status").out
    r = gct("publish", "restore", "--json")
    assert r.code == 0 and r.data["version"] == 1 and (r.data["companies"], r.data["documents"]) == (2, 2)
    conn = published.open_version(ws / "published" / "v1.db")
    try:
        assert {x for (x,) in conn.execute("SELECT id FROM document")} == {world["a"], world["e"]}
        (gap,) = conn.execute("SELECT capacity, rationale FROM gap_confirmation").fetchall()
        assert tuple(gap) == (f"cleared with document {d}",) * 2
    finally:
        conn.close()
    # Retention still removes an older version file after a deletion purge (Q5).
    for _ in range(2):
        assert gct("publish", "build").code == 0
    assert sorted(p.name for p in (ws / "published").iterdir()) == ["v3.db", "v4.db"]
    v4 = published.open_version(ws / "published" / "v4.db")
    try:
        meta = dict(v4.execute("SELECT key, value FROM meta").fetchall())
        assert meta["projection_schema"] == "16" and meta["deleted_documents"] == "1"
        assert [tuple(r) for r in v4.execute("SELECT * FROM deleted_document")] == [
            (d, db.execute("SELECT at FROM document_state WHERE state = 'deleted'").fetchone()[0])]
        assert {"hidden_by_archive", "comparison", "restatement", "series", "page_acceptance"} <= {
            t for (t,) in v4.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        v4.close()


def held(ws, v: int, d: int) -> tuple[dict, str]:
    """({page, expected_item_document: rows of document d}, expectation 1's accepted column) of version v."""
    conn = published.open_version(ws / "published" / f"v{v}.db")
    try:
        tables = {t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        rows = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} WHERE document_id = ?", (d,))]
                for t in ("page", "expected_item_document") if t in tables}
        return rows, conn.execute("SELECT accepted FROM expected_item WHERE id = 1").fetchone()[0]
    finally:
        conn.close()


def entry(db, doc: int) -> dict:
    (i,) = db.execute("SELECT id FROM page_acceptance WHERE document_id = ?", (doc,)).fetchone()
    return {"type": "figures", "acceptance_id": i, "count": 1}


# Story 7.1 part B, B6 (and B4: a deleted declared document has no link)
def test_purge_removes_the_documents_page_rows_links_and_accepted_entries(ws, db, gct, world):
    a, d = world["a"], world["d"]
    rows, accepted = held(ws, 2, d)
    assert rows["page"] and rows["expected_item_document"] == [(1, d, "registered")]
    assert json.loads(accepted) == [entry(db, a), entry(db, d)]
    assert delete(gct, db, d).code == 0
    for v in (1, 2):
        rows, after = held(ws, v, d)
        assert rows == {"page": [], "expected_item_document": []}
        assert after == json.dumps([entry(db, a)]) and json.dumps(entry(db, a)) in accepted  # a's entry byte for byte
    assert gct("publish", "build").code == 0
    rows, accepted = held(ws, 3, d)
    assert rows == {"page": [], "expected_item_document": []} and json.loads(accepted) == [entry(db, a)]
    assert held(ws, 3, a)[0]["expected_item_document"] == [(1, a, "registered")]


# Story 7.1 part B, B8: a projection-14 file built by the code before 15, retained as the previous version
def test_a_projection_14_file_of_the_older_code_is_purged_and_restored(ws, db, gct, world, old_tree):
    a, d = world["a"], world["d"]
    (r,) = run_old(old_tree, ws, ("publish", "build", "--json"), newer=True)  # the workspace is at schema 21
    assert r["code"] == 0 and json.loads(r["out"])["version"] == 3
    assert gct("publish", "build").code == 0
    assert sorted(p.name for p in (ws / "published").iterdir()) == ["v3.db", "v4.db"]
    old = published.open_version(ws / "published" / "v3.db")
    try:
        assert dict(old.execute("SELECT key, value FROM meta").fetchall())["projection_schema"] == "14"
        assert "page" not in {t for (t,) in old.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        old.close()
    rows, accepted = held(ws, 3, d)
    assert rows == {"expected_item_document": [(1, d)]} and json.loads(accepted) == [
        {"type": "figures", "accepted": "accepted by Ana (analyst)", "count": 1},
        {"type": "figures", "accepted": f"accepted by Ana ({CAPACITY} reading {METRIC})", "count": 1}]
    assert held(ws, 4, a)[0]["page"]  # the first build after the older code fills the page table from the readings
    assert delete(gct, db, d).code == 0
    rows, accepted = held(ws, 3, d)
    assert rows == {"expected_item_document": []} and json.loads(accepted) == [
        {"type": "figures", "accepted": f"cleared with document {d}", "count": 1}] * 2
    assert CAPACITY.encode() not in (ws / "published" / "v3.db").read_bytes()
    assert held(ws, 4, d)[1] == json.dumps([entry(db, a)])
    r = gct("publish", "restore", "--json")
    assert r.code == 0 and r.data["version"] == 3


# AC 7, AC 8
def test_retained_reviews_carry_the_marker_and_shared_records_stay(ws, db, gct, world, make_file):
    a, d, claim, other = world["a"], world["d"], world["claim"], world["other"]
    (s,) = series(gct, "ghg_scope_1")
    assert {p["document_id"] for p in gct("series", "show", s["id"], "--all", "--json").data["series"]["points"]} == {a, d}
    a_claims = gct("claims", "list", "--doc", a, "--json").data["claims"]
    assert delete(gct, db, d).code == 0
    marker, when = f"cleared with document {d}", db.execute("SELECT at FROM document_state WHERE state = 'deleted'").fetchone()[0]
    mark = f"evidence deleted (document {d}, {when[:10]})"
    h = gct("claims", "history", claim, "--json").data
    assert h["claim"]["evidence_deleted"] == {"document": d, "at": when} and h["claim"]["document_state"] == "deleted"
    (review,) = [r for v in h["versions"] for r in v["reviews"] if r["field"] == "boundary"]
    (fix,) = [v["correction"] for v in h["versions"] if v["correction"]]
    for rec in (review, fix):
        assert (rec["contributor"], rec["capacity"], rec["rationale"]) == ("Ana", marker, marker) and rec["created_at"]
    assert review["decision"] == "resolved" and review["boundary"] is None
    text = gct("claims", "history", claim).out
    assert f"boundary review #{review['id']}: resolved by Ana ({marker}): {marker}  made " in text and mark in text
    assert f"correction #{fix['id']}" in text
    shown = gct("restate", "show", other, "--json").data  # from the survivor's side
    (rec,) = [x for v in shown["versions"] if v["claim"] == claim for x in v["reviews"]["restatements"]]
    assert (rec["decision"], rec["quote"], rec["capacity"], rec["rationale"], rec["contributor"]) == (
        "recorded", "", marker, marker, "Ana")
    assert all(v["evidence_deleted"] == {"document": d, "at": when} for v in shown["versions"] if v["claim"] == claim)
    # Listed under the survivor's own version too, the record carries the marker of its deleted side (review LOW 2).
    (mine,) = [x for v in shown["versions"] if v["claim"] == other for x in v["reviews"]["restatements"]]
    assert mine["id"] == rec["id"] and mine["evidence_deleted"] == {"document": d, "at": when}
    survivor = gct("restate", "show", other).out.split(f"claim {other} version ")[1].split("\n  claim ")[0]
    assert f"restatement #{rec['id']}" in survivor and mark in survivor
    assert shown["pairs"] == [] and gct("restate", "list", "--json").data["pairs"] == []
    assert mark in gct("restate", "show", other).out
    mine = gct("restate", "show", claim, "--json").data
    (m,) = [x for v in mine["versions"] for x in v["reviews"]["match_reviews"]]
    assert (m["decision"], m["series"], m["rationale"]) == ("linked", None, marker)
    assert f"Document {d} was deleted." in gct("restate", "show", claim).out
    page = [r for r in gct("doc", "show", d, "--json").data["deletion"]["records"] if r["kind"] == "page acceptance"]
    assert [(r["what"], r["contributor"], r["capacity"], r["evidence_deleted"]["document"]) for r in page] == [
        ("p1 figures", "Ana", marker, d)]
    assert mark in gct("doc", "show", d).out
    (x,) = gct("expect", "list", "--json").data["expectations"]
    c = x["confirmation"]
    assert x["documents"] == [a] and c["evidence_deleted"]["document"] == d and c["rationale"] == marker
    assert not c["current"] and any("was made on older readings" in r["reason"] for r in x["reasons"])
    assert mark in gct("expect", "list").out
    # Shared records: A's claims and the series, less D's point.
    assert gct("claims", "list", "--doc", a, "--json").data["claims"] == a_claims
    (s2,) = series(gct, "ghg_scope_1")
    assert s2["id"] == s["id"] and {p["document_id"] for p in gct("series", "show", s["id"], "--all", "--json").data[
        "series"]["points"]} == {a}
    assert [c["name"] for c in gct("company", "list", "--json").data["companies"]] == ["Acme", "Beta"]
    # Writes on it are refused; restore too.
    for argv in (["doc", "restore", d, *WHO], ["correct", claim, "--value", "1", *WHO], ["doc", "archive", d, *WHO]):
        r = gct(*argv)
        assert r.code == 4 and f"Document {d} " in r.err, argv
    # Adding the same file again registers a new document with nothing of the old one.
    r = gct("doc", "add", make_file(f"{LOGICAL}.pdf", d_bytes()), "--company", "Acme", "--json").data["items"][0]
    assert r["action"] == "registered" and r["document"]["id"] not in (a, d, world["e"])
    assert gct("claims", "list", "--doc", r["document"]["id"], "--json").data["claims"] == []
    lst = gct("doc", "list").out
    assert f"{d}  Acme  {marker}  v1  private  unknown  deleted {when[:10]}" in lst
    act = gct("doc", "list", "--active", "--json").data
    assert d not in {x["id"] for x in act["documents"]} and act["hidden_deleted"] == 1


# AC 9: the Deletion gate's acceptance method
def test_no_canary_survives_anywhere_in_the_workspace(ws, db, gct, world):
    d, e = world["d"], world["e"]
    kept = registry.stored_path(ws, world["sha"])  # E's original, the same bytes as D's: kept by design (AC 5)
    assert scan(ws, skip=[kept]) == set(CANARIES)  # the scan can fail: before deletion it finds every canary
    plan = gct("doc", "delete", d).out
    assert "exports/" in plan
    export = (ws / "exports" / "shared.csv").read_bytes()
    assert delete(gct, db, d).code == 0
    db.close()
    left = {str(p.relative_to(ws)): c for p in files(ws) if p != kept and "exports" not in p.parts
            for c in CANARIES if c.encode() in p.read_bytes()}
    assert left == {}
    assert hashlib.sha256(kept.read_bytes()).hexdigest() == world["sha"]
    assert gct("doc", "show", e, "--json").data["document"]["state"] == "registered"
    assert (ws / "exports" / "shared.csv").read_bytes() == export
    assert not (ws / "workspace.db-wal").exists() or (ws / "workspace.db-wal").stat().st_size == 0


# AC 10
def test_a_failed_step_stays_pending_until_a_second_confirm(ws, db, gct, world, monkeypatch):
    d = world["d"]

    def locked(*args):
        raise OSError("the file is held open")

    monkeypatch.setattr(published, "purge", locked)
    r = delete(gct, db, d)
    assert r.code == 4 and "these steps did not finish: published" in r.err
    assert f"gct doc delete {d} --confirm {token(db, d)}" in r.err
    shown = gct("doc", "show", d, "--json").data
    assert shown["document"]["state"] == "deleted" and shown["deletion"]["pending"] == ["published"]
    assert "Pending: published" in gct("doc", "show", d).out
    refused = gct("publish", "restore")
    assert refused.code == 4 and "still contains a document that has since been deleted" in refused.err
    monkeypatch.setattr(published, "purge", PURGE)  # the file can be written again
    r = gct("doc", "delete", d, "--confirm", token(db, d))
    assert r.code == 0, r.err
    assert gct("doc", "show", d, "--json").data["deletion"]["pending"] == []
    assert db.execute("SELECT COUNT(*) FROM document_deletion_step WHERE step = 'published'").fetchone()[0] == 1
    assert gct("publish", "restore").code == 0


# Review HIGH 1: the file path of a document added under another name
def test_older_add_lines_are_found_by_the_file_they_still_hold(ws, db, gct, tmp_path):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    kept, moved = tmp_path / "zqkept.pdf", tmp_path / "zqmoved.pdf"
    kept.write_bytes(PDF)
    d = gct("doc", "add", kept, "--name", "plain", "--company", "Acme", "--json").data["items"][0]["document"]["id"]
    (run,) = db.execute("SELECT MAX(id) FROM run").fetchone()
    # Register lines as gct wrote them before they recorded the document id: one whose path still holds the file,
    # one whose file was moved away since (it cannot be found, docs/deletion.md says so).
    old = [db.execute("INSERT INTO run_event (run_id, at, kind, stage, item, outcome) VALUES (?, 't', 'item', 'register',"
                      " ?, 'ok')", (run, str(p))).lastrowid for p in (kept, moved)]
    db.commit()
    assert delete(gct, db, d).code == 0
    items = dict(db.execute("SELECT id, item FROM run_event WHERE id IN (?, ?)", old).fetchall())
    assert items == {old[0]: f"cleared with document {d}", old[1]: str(moved)}
    assert not db.execute("SELECT 1 FROM run_event WHERE instr(item, 'zqkept') OR instr(message, 'zqkept')").fetchone()


# Review MEDIUM 1: other documents' attempts are machine state
def test_a_short_name_leaves_other_documents_attempts_alone(ws, db, gct, make_file):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    a = add(gct, make_file, "a.pdf", [SCOPE_1])
    d = gct("doc", "add", make_file("d.pdf", make_pdf([page_of([SCOPE_1], boundary="consolidated")])), "--name", "1",
            "--company", "Acme", "--json").data["items"][0]["document"]["id"]
    for step in ("read", "extract", "infer", "match"):
        assert gct(step).code == 0
    before = [tuple(r) for r in db.execute("SELECT id, item, output FROM attempt ORDER BY id")]
    assert any("1" in (x or "") for _, i, o in before for x in (i, o))  # the name is a substring of attempt text
    assert delete(gct, db, d).code == 0
    assert [tuple(r) for r in db.execute("SELECT id, item, output FROM attempt ORDER BY id")] == before
    for step in ("read", "extract", "infer", "match"):
        r = gct(step, "--json")
        assert r.code == 0, (step, r.err)
    assert db.execute("SELECT COUNT(*) FROM attempt").fetchone()[0] == len(before)  # A's results are reused
    assert gct("claims", "list", "--doc", a, "--json").data["claims"]


# Integration with story 4.3 (f): a 4.1 workspace takes migrations 13, 14, 15 and 16 in order
def test_migrations_13_to_16_apply_in_order_to_a_4_1_workspace(tmp_path, gct):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    assert store.migrate(c, up_to=12) == list(range(1, 13))
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.close()
    assert gct("doc", "list", "--workspace", root).code == 0
    c = store.connect(root / layout.DB_NAME)
    (run,) = runs.list_runs(c)
    assert [e["message"] for e in runs.show_run(c, run["id"])["events"] if e["kind"] == "note"] == [
        f"applied migration {n}" for n in (13, 14, 15, 16, 17, 18, 19, 20, 21)]
    assert {"restatement", "document_state_change", "sheet_mapping", "claim_note", "document_deletion"} <= {
        t for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    c.close()


# Integration with story 4.3 (b) to (e): spreadsheet evidence
SHEET_CANARIES = {"sheet name (CSV file)": "zqcsv", "sheet name (XLSX)": "zqxsheet", "header": "zqhead",
                  "metric cell": "zqline", "note cell": "zqnote", "mapping capacity": "zqmapcap",
                  "mapping rationale": "zqmapwhy", "value": "77,123"}
SHEET_ROWS = [["zqhead Metric", "Value", "Unit", "Note"], ["zqline Scope 1", "77,123", "tCO2e", "zqnote"]]
MAPPED = ("--metric", "zqhead Metric", "--value", "Value", "--unit", "Unit", "--note", "Note")
SHEET_WHO = ("--as", "ana", "--capacity", "zqmapcap analyst", "--rationale", "zqmapwhy headers")


def test_spreadsheet_canaries_leave_with_their_documents(ws, db, gct, make_file):
    from test_sheet import HEADER, MAP, ROWS, WHO as SHEET_PLAIN, csv_bytes, xlsx

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")

    def add_sheet(name, data) -> int:
        r = gct("doc", "add", make_file(name, data), "--company", "Acme", "--kind", "evidence", "--json")
        return r.data["items"][0]["document"]["id"]

    c = add_sheet("zqcsv.csv", csv_bytes(SHEET_ROWS))
    x = add_sheet("x.xlsx", xlsx({"zqxsheet": SHEET_ROWS}))
    keep = add_sheet("k.csv", csv_bytes([HEADER, ["zqkeep Scope 1", *ROWS[1][1:]]]))
    for doc, name, who in ((c, "zqcsv", SHEET_WHO), (x, "zqxsheet", SHEET_WHO), (keep, "k", SHEET_PLAIN)):
        sheet_name = gct("sheet", "show", doc, "--json").data["sheets"][0]["name"]
        assert name in sheet_name
        assert gct("sheet", "map", doc, "--sheet", sheet_name, *(MAP if doc == keep else MAPPED), *who).code == 0
    assert gct("extract").code == 0 and gct("link").code == 0
    # A new mapping that reads the metric column as the value: the check quotes the metric cell (zqline).
    csv_sheet = gct("sheet", "show", c, "--json").data["sheets"][0]["name"]
    assert gct("sheet", "map", c, "--sheet", csv_sheet, "--metric", "zqhead Metric", "--value", "zqhead Metric",
               *SHEET_WHO).code == 0
    assert gct("link", c).code == 0
    assert db.execute("SELECT COUNT(*) FROM source_match WHERE instr(reason, 'zqline')").fetchone()[0]
    assert gct("doc", "archive", x, *SHEET_PLAIN).code == 0  # its mappings are counted in hidden_by_archive
    for _ in range(2):
        assert gct("publish", "build").code == 0
    keep_attempts = [tuple(r) for r in db.execute(
        "SELECT id, item, output, error FROM attempt WHERE stage = 'sheet' AND item LIKE ? ORDER BY id", (f"{keep}:%",))]
    assert keep_attempts
    found = {k for k, v in SHEET_CANARIES.items() for p in files(ws) if v.encode() in p.read_bytes()}
    assert found == set(SHEET_CANARIES)  # the scan can fail
    for doc in (c, x):
        assert gct("doc", "delete", doc, "--confirm", token(db, doc), *SHEET_PLAIN).code == 0
    db.close()
    left = {str(p.relative_to(ws)): k for p in files(ws) if "exports" not in p.parts
            for k, v in SHEET_CANARIES.items() if v.encode() in p.read_bytes()}
    assert left == {}
    for p in [ws / "workspace.db", *(ws / "published").glob("v*.db")]:
        assert b"zqkeep" in p.read_bytes(), p  # the other spreadsheet's canary survives
    conn = sqlite3.connect(ws / "workspace.db")
    conn.row_factory = sqlite3.Row
    try:
        marker = f"cleared with document {c}"
        rows = conn.execute("SELECT * FROM sheet_mapping WHERE document_id = ? ORDER BY id", (c,)).fetchall()
        assert len(rows) == 2 and all(
            (r["sheet"], r["value_col"], r["metric_col"], r["note_col"], r["capacity"], r["rationale"])
            == ("", "", None, None, marker, marker) and r["contributor_version_id"] and r["created_at"] for r in rows)
        assert {r["text"] for r in conn.execute(
            "SELECT n.text FROM claim_note n JOIN claim_version v ON v.id = n.claim_version_id JOIN claim k"
            " ON k.id = v.claim_id WHERE k.document_id IN (?, ?)", (c, x))} == {""}
        # (c) the sheet attempts of the deleted documents are cleared by their key; the other one's are unchanged
        assert [tuple(r) for r in conn.execute(
            "SELECT id, item, output, error FROM attempt WHERE stage = 'sheet' AND item LIKE ? ORDER BY id",
            (f"{keep}:%",))] == keep_attempts
        outs = [json.loads(o) for (o,) in conn.execute(
            "SELECT output FROM attempt WHERE stage = 'sheet' AND item LIKE ? AND output IS NOT NULL", (f"{c}:%",))]
        assert outs and all(o["sheet"] == marker and o["claims"] for o in outs)
    finally:
        conn.close()
    shown = gct("doc", "show", c, "--json").data["deletion"]["records"]
    assert [(r["kind"], r["what"], r["contributor"], r["capacity"], r["evidence_deleted"]["document"])
            for r in shown if r["kind"] == "sheet mapping"] == [("sheet mapping", "sheet 1", "Ana", marker, c)] * 2
    assert "evidence deleted" in gct("doc", "show", c).out
    refused = gct("sheet", "show", c)
    assert refused.code == 4 and f"Document {c} was deleted." in refused.err
    (first,) = [k["id"] for k in gct("claims", "list", "--doc", c, "--json").data["claims"]][:1]
    history = gct("claims", "history", first).out  # a cleared sheet reference (fix round 2, LOW 3)
    assert "sheet and cell cleared" in history and "pNone" not in history
    assert gct("sheet", "map", c, "--sheet", "x", "--metric", "x", "--value", "x", *SHEET_PLAIN).code == 4
    # (d) retained versions: no mapping or sheet row of the deleted documents, the other's stay, counts consistent
    for v in (1, 2):
        ver = published.open_version(ws / "published" / f"v{v}.db")
        try:
            assert {d for (d,) in ver.execute("SELECT document_id FROM sheet_mapping")} == {keep}
            assert {d for (d,) in ver.execute("SELECT document_id FROM claim")} == {keep}
            assert not ver.execute("SELECT 1 FROM evidence_ref WHERE document_id IN (?, ?)", (c, x)).fetchone()
            hidden = json.loads(dict(ver.execute("SELECT key, value FROM meta").fetchall())["hidden_by_archive"])
            assert hidden == {"documents": 0, "claims": 0, "evidence_refs": 0, "review_records": 0}
            assert not ver.execute("SELECT 1 FROM hidden_by_archive").fetchone()
        finally:
            ver.close()
    assert gct("extract").code == 0 and gct("claims", "list", "--doc", keep, "--json").data["claims"]


# Fix round 2, MEDIUM 1: run lines another document's runs read back stay
def test_a_short_name_leaves_another_runs_retry_alone(ws, db, gct, make_file, monkeypatch):
    import pdfplumber

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    b = add(gct, make_file, "b.pdf", [SCOPE_1])
    real = pdfplumber.open

    def unopenable(*args, **kw):
        raise OSError("held by another program")

    monkeypatch.setattr(pdfplumber, "open", unopenable)
    assert gct("read").code == 4  # B could not be opened: a failure line with item "1"
    monkeypatch.setattr(pdfplumber, "open", real)
    (run,) = db.execute("SELECT MAX(id) FROM run").fetchone()
    assert db.execute("SELECT item FROM run_event WHERE run_id = ? AND kind = 'failure'", (run,)).fetchone()[0] == str(b)
    d = gct("doc", "add", make_file("d.pdf", make_pdf([page_of([SCOPE_1], boundary="consolidated")])), "--name",
            str(b), "--company", "Acme", "--json").data["items"][0]["document"]["id"]
    assert delete(gct, db, d).code == 0
    r = gct("run", "retry", run, "--json")
    assert r.code == 0, r.err
    assert [(x["id"], x["action"]) for x in r.data["documents"]] == [(b, "read")]


def test_a_document_named_like_another_file_leaves_its_add_lines_alone(ws, db, gct, tmp_path):
    gct("company", "add", "Acme")
    gct("company", "add", "Beta")
    gct("contributor", "add", "ana", "--name", "Ana")
    one, two = tmp_path / "one", tmp_path / "two"
    for folder, data in ((one, PDF), (two, PDF + b"other")):
        folder.mkdir()
        (folder / "b.pdf").write_bytes(data)
    assert gct("doc", "add", one / "b.pdf", "--company", "Acme").code == 0
    run_b = db.execute("SELECT MAX(id) FROM run").fetchone()[0]
    before = [tuple(r) for r in db.execute("SELECT id, item, message FROM run_event WHERE run_id = ?", (run_b,))]
    assert any(str(one / "b.pdf") in (m or "") for _, _, m in before)  # B's selection note holds its path
    d = gct("doc", "add", two / "b.pdf", "--company", "Beta", "--json").data["items"][0]["document"]["id"]
    assert delete(gct, db, d).code == 0
    assert [tuple(r) for r in db.execute("SELECT id, item, message FROM run_event WHERE run_id = ?", (run_b,))] == before
    assert not db.execute("SELECT 1 FROM run_event WHERE instr(item, ?) OR instr(message, ?)",
                          (str(two), str(two))).fetchone()  # D's own add lines are cleared
    assert runs.selection(db, run_b)["sources"] == [str(one / "b.pdf")]  # B's run can still be replayed


# Fix round 2, LOW 2: an id-less line of another company's document with the same file stays
def test_an_old_add_line_of_another_company_with_the_same_file_stays(ws, db, gct, tmp_path):
    gct("company", "add", "Acme")
    gct("company", "add", "Beta")
    gct("contributor", "add", "ana", "--name", "Ana")
    mine, theirs = tmp_path / "zqmine.pdf", tmp_path / "zqtheirs.pdf"
    mine.write_bytes(PDF)
    theirs.write_bytes(PDF)
    d = gct("doc", "add", mine, "--company", "Acme", "--json").data["items"][0]["document"]["id"]
    run_d = db.execute("SELECT MAX(id) FROM run").fetchone()[0]
    assert gct("doc", "add", theirs, "--company", "Beta").code == 0
    run_c = db.execute("SELECT MAX(id) FROM run").fetchone()[0]
    # Register lines as gct wrote them before they recorded the document id, one in each company's run.
    old = [db.execute("INSERT INTO run_event (run_id, at, kind, stage, item, outcome) VALUES (?, 't', 'item', 'register',"
                      " ?, 'ok')", (r, str(p))).lastrowid for r, p in ((run_d, mine), (run_c, theirs))]
    db.commit()
    assert delete(gct, db, d).code == 0
    assert dict(db.execute("SELECT id, item FROM run_event WHERE id IN (?, ?)", old).fetchall()) == {
        old[0]: f"cleared with document {d}", old[1]: str(theirs)}


# Fix round 3, MEDIUM A: the document's own add runs, whether or not they registered it
def test_a_refused_add_before_the_successful_one_leaves_no_canary_and_nothing_to_retry(ws, db, gct, tmp_path):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    canaries = ("zqfaildir", "zqfailfile", "Zqfailname", "zqfailsrc")
    (tmp_path / canaries[0]).mkdir()
    path = tmp_path / canaries[0] / f"{canaries[1]}.pdf"
    path.write_bytes(b"not a PDF yet")
    named = ("--company", "Acme", "--name", canaries[2], "--source", f"https://e.org/{canaries[3]}")
    assert gct("doc", "add", path, *named).code != 0
    (refused,) = db.execute("SELECT MAX(id) FROM run").fetchone()
    path.write_bytes(PDF)
    d = gct("doc", "add", path, *named, "--json").data["items"][0]["document"]["id"]
    assert scan(ws, canaries=canaries) == set(canaries)
    assert delete(gct, db, d).code == 0
    assert scan(ws, canaries=canaries) == set()
    r = gct("run", "retry", refused, "--json")
    assert (r.code, r.data["items"]) == (0, [])
    assert db.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 1


def test_a_failed_fetch_before_the_successful_one_leaves_no_address(ws, db, gct, web, monkeypatch):  # noqa: F811
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    u, real = web.url("/r.pdf"), intake._download

    def missing(root, url):
        raise GctError(REFUSED, "The address answered with HTTP error 404.", intake.RETRY)

    monkeypatch.setattr(intake, "_download", missing)
    assert gct("doc", "add", u, "--company", "Acme").code != 0
    (failed,) = db.execute("SELECT MAX(id) FROM run").fetchone()
    monkeypatch.setattr(intake, "_download", real)
    d = gct("doc", "add", u, "--company", "Acme", "--json").data["items"][0]["document"]["id"]
    assert runs.selection(db, failed)["sources"] == [u]
    assert delete(gct, db, d).code == 0
    assert not db.execute("SELECT 1 FROM run_event WHERE instr(item, ?) OR instr(message, ?)", (u, u)).fetchone()
    r = gct("run", "retry", failed, "--json")
    assert (r.code, r.data["items"]) == (0, [])


def test_an_old_add_run_of_a_file_moved_since_loses_the_name(ws, db, gct, tmp_path):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    path = tmp_path / "zqold.pdf"
    path.write_bytes(PDF)
    # Added as gct did before register lines recorded the document id, then the file was moved away.
    c = store.connect(ws / layout.DB_NAME)
    run = runs.start(c, "doc add")
    runs.record(c, run, {"sources": [str(path)], "company": "Acme", "kind": "report", "privacy": "private",
                         "name": "Zqoldname", "source": None})
    runs.event(c, run, "item", stage="register", item=str(path), outcome="ok")
    _, doc = registry.add_document(c, ws, path, "Acme", name="Zqoldname")
    c.close()
    path.rename(tmp_path / "moved.pdf")
    assert delete(gct, db, doc["id"]).code == 0
    assert runs.selection(db, run) is None
    assert not db.execute("SELECT 1 FROM run_event WHERE instr(message, 'Zqoldname')").fetchone()


# Fix round 3, LOW B: another company's fetch of the same address stays
def test_another_companys_fetch_of_the_same_address_stays(ws, db, gct, web):  # noqa: F811
    gct("company", "add", "Acme")
    gct("company", "add", "Beta")
    gct("contributor", "add", "ana", "--name", "Ana")
    u = web.url("/r.pdf")
    assert gct("doc", "add", u, "--company", "Acme").code == 0  # first, so its run holds the fetch line
    (run_b,) = db.execute("SELECT MAX(id) FROM run").fetchone()
    before = [tuple(r) for r in db.execute("SELECT id, item, message FROM run_event WHERE run_id = ?", (run_b,))]
    assert any(i == u for _, i, _ in before)
    c = gct("doc", "add", u, "--company", "Beta", "--json").data["items"][0]["document"]["id"]
    assert delete(gct, db, c).code == 0
    assert [tuple(r) for r in db.execute("SELECT id, item, message FROM run_event WHERE run_id = ?", (run_b,))] == before


def run_lines(db, run: int) -> list[tuple]:
    return [tuple(r) for r in db.execute("SELECT id, kind, item, message FROM run_event WHERE run_id = ?", (run,))]


# Fix round 4, H1: a refused folder add before the successful one
def test_a_refused_folder_add_before_the_successful_one_leaves_no_canary(ws, db, gct, tmp_path):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    canaries = ("zqh1folder", "zqh1file", "Zqh1name", "zqh1src")
    folder = tmp_path / canaries[0]
    folder.mkdir()
    named = ("--company", "Acme", "--name", canaries[2], "--source", f"https://e.org/{canaries[3]}")
    assert gct("doc", "add", folder, *named).code != 0  # the folder holds no PDF yet
    (refused,) = db.execute("SELECT MAX(id) FROM run").fetchone()
    assert [i for _, k, i, _ in run_lines(db, refused) if k == "failure"] == [str(folder.resolve())]
    (folder / f"{canaries[1]}.pdf").write_bytes(PDF)
    d = gct("doc", "add", folder, *named, "--json").data["items"][0]["document"]["id"]
    assert scan(ws, canaries=canaries) == set(canaries)
    assert delete(gct, db, d).code == 0
    assert scan(ws, canaries=canaries) == set()
    r = gct("run", "retry", refused, "--json")
    assert (r.code, r.data["items"]) == (0, [])
    assert db.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 1


# Fix round 4, LOW 1: the document's failure line in a run that registered another document
def test_a_run_that_registered_another_file_loses_the_documents_failure_line(ws, db, gct, make_file):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    keep, a = make_file("keepc.pdf", PDF + b"c"), make_file("zqmixa.pdf", b"not a PDF yet")
    assert gct("doc", "add", keep, a, "--company", "Acme").code != 0  # registers C, refuses A's file
    (run,) = db.execute("SELECT MAX(id) FROM run").fetchone()
    lines = run_lines(db, run)
    (failure,) = [x for x in lines if x[1] == "failure"]
    assert failure[2] == str(a.resolve())
    a.write_bytes(PDF)
    d = gct("doc", "add", a, "--company", "Acme", "--name", "Zqmixname", "--json").data["items"][0]["document"]["id"]
    assert delete(gct, db, d).code == 0
    marker = f"cleared with document {d}"
    assert run_lines(db, run) == [(*x[:2], marker, marker) if x == failure else x for x in lines]  # C's lines stay
    r = gct("run", "retry", run, "--json")
    assert (r.code, r.data["items"]) == (0, [])
    assert db.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 2


# Fix round 4, LOW 2: a refused run of several files is not the document's own run
def test_a_refused_run_of_several_files_keeps_the_other_files_retry(ws, db, gct, make_file):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    a, keep = make_file("zqmultia.pdf", b"not a PDF yet"), make_file("keepc.pdf", b"not a PDF either")
    assert gct("doc", "add", a, keep, "--company", "Acme").code != 0  # refuses both
    (run,) = db.execute("SELECT MAX(id) FROM run").fetchone()
    a.write_bytes(PDF)
    d = gct("doc", "add", a, "--company", "Acme", "--json").data["items"][0]["document"]["id"]
    assert delete(gct, db, d).code == 0
    keep.write_bytes(PDF + b"c")
    r = gct("run", "retry", run, "--json")
    assert r.code == 0, r.err
    assert [(i["source"], i["action"]) for i in r.data["items"]] == [(str(keep.resolve()), "registered")]
    assert db.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 2
