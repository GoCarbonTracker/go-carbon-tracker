"""Story 5.4: highlights, the third separate record of FR36 (a correction and a company confirmation are the other two).
Labelled test entries on synthetic workspaces only; no real report and no copy of a real workspace is used."""
import sqlite3

import pytest

from test_deletion import WHO as DELETE_WHO, scan, token, world  # noqa: F401 (world is a fixture)
from old_code import labels_table
from test_match import SCOPE_1
from test_restate import acme, add  # noqa: F401 (acme is a fixture)
from test_review import NOTE, SELF, counts, first_claim, newest, one, projected, rec, rows  # noqa: F401 (one is a fixture)
from gct.stages import extract
from gct.workspace import published, store


def hl(gct, claim, version, note="check against the 2023 report", who="ana", capacity="analyst", *extra):
    return gct("highlight", "add", claim, "--version", version, "--note", note, "--as", who, "--capacity", capacity,
               *extra)


def versions(gct, claim) -> dict:
    """{version id: version record} of gct highlight list."""
    return {v["id"]: v for v in gct("highlight", "list", claim, "--json").data["versions"]}


# AC 1, matrix row "workspace upgraded from 0018 (and from 0016)"
@pytest.mark.parametrize("old", [16, 18])
def test_migration_19_applies_in_order_and_the_table_is_append_only(tmp_path, gct, make_file, monkeypatch, old):
    real = store.migrate
    monkeypatch.setattr(store, "migrate", lambda conn, up_to=None: real(conn, old))
    root = tmp_path / "old"
    assert gct("workspace", "init", root).code == 0
    labels_table(root)  # story 7.1 part A (Q1): the current doc add writes it
    monkeypatch.setenv("GCT_WORKSPACE", str(root))
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    add(gct, make_file, "a.pdf", [SCOPE_1])
    assert gct("read").code == 0 and gct("extract").code == 0
    db = sqlite3.connect(root / "workspace.db")
    claim = db.execute("SELECT claim_id FROM claim_version WHERE period_label = 'FY 2024-25'").fetchone()[0]
    assert db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == old
    db.execute("DROP TABLE document_label")  # the upgrade below creates it (Q1)
    monkeypatch.setattr(store, "migrate", real)
    r = gct("highlight", "list", claim)
    assert r.code == 0 and "no highlights" in r.out, r.out
    assert [v for (v,) in db.execute("SELECT version FROM schema_version ORDER BY version")][old - 1:] == list(
        range(old, 22))
    notes = [m for (m,) in db.execute("SELECT message FROM run_event WHERE kind = 'note' ORDER BY id DESC LIMIT 3")]
    assert notes == ["applied migration 21", "applied migration 20", "applied migration 19"]
    assert db.execute("SELECT COUNT(*) FROM highlight").fetchone()[0] == 0
    db.execute("INSERT INTO highlight (claim_version_id, contributor_version_id, capacity, note, created_at)"
               " VALUES (1, 1, 'c', 'n', 't')")
    db.commit()
    for stmt in ("UPDATE highlight SET note = 'x'", "DELETE FROM highlight"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
            db.execute(stmt)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO highlight (claim_version_id, contributor_version_id, capacity, created_at)"
                   " VALUES (1, 1, 'c', 't')")


# AC 2
def test_add_writes_one_row_kept_as_typed_and_list_shows_it(ws, db, gct, one):
    doc, claim, version = one
    note = "  We have verified   this figure?  "
    r = hl(gct, claim, version, note, "ana", "head of sustainability", "--json")
    assert r.code == 0, r.err
    (row,) = rows(db, "highlight")
    assert {k: row[k] for k in row if k not in ("id", "created_at")} == {
        "claim_version_id": version, "contributor_version_id": 1, "capacity": "head of sustainability", "note": note}
    assert r.data["claim"] == {"id": claim, "document": doc, "company": "Acme", "version": version}
    e = r.data["entry"]
    assert (e["contributor"], e["organisation"], e["note"], e["latest"], e["binds"], e["self_declared"]) == (
        "Ana", "Acme audit", note, True, True, True)
    text = hl(gct, claim, version, note).out
    assert f'by Ana (Acme audit) (self-declared), capacity "analyst": "{note}"' in text and text.count(SELF) == 1
    listed = gct("highlight", "list", claim)
    assert listed.code == 0 and listed.out.count("highlight #") == 2 and listed.out.count(SELF) == 1
    assert [len(v["highlights"]) for v in versions(gct, claim).values()] == [2]


def refusals(gct, db, make_file, one) -> list[tuple]:
    """(argv, exit code) for every refusal of AC 2, on a workspace prepared for them."""
    doc, claim, version = one
    archived = add(gct, make_file, "b.pdf", [SCOPE_1[:3]])
    gone = add(gct, make_file, "c.pdf", [["Total Scope 2 emissions", "tCO2e", "77", "70"]])
    assert gct("read").code == 0 and gct("extract").code == 0
    archived_claim = gct("claims", "list", "--doc", archived, "--json").data["claims"][0]["id"]
    gone_claim = gct("claims", "list", "--doc", gone, "--json").data["claims"][0]["id"]
    who = ("--as", "ana", "--capacity", "c", "--rationale", "r")
    assert gct("doc", "archive", archived, *who).code == 0
    assert gct("doc", "delete", gone, "--confirm", token(db, gone), *who).code == 0

    def h(c=claim, v=version, note="n", who="ana", capacity="c"):
        return ["highlight", "add", c, "--version", v, "--note", note, "--as", who, "--capacity", capacity]

    return [(h(c=99), 3), (h(who="nobody"), 3), (h(c=archived_claim, v=newest(gct, archived_claim)), 4),
            (h(c=gone_claim, v=newest(gct, gone_claim)), 4), (h(v=99), 4), (h(note=" "), 2), (h(capacity=""), 2)]


def test_every_refusal_writes_nothing_and_gives_a_next_step(ws, db, gct, make_file, one, monkeypatch):
    doc, claim, version = one
    cases = refusals(gct, db, make_file, one)
    before = counts(db)
    for argv, code in cases:
        out = gct(*argv)
        assert out.code == code, (argv, out.err)
        assert out.err.startswith("error: ") and "\nnext: " in out.err, (argv, out.err)
        assert counts(db) == before, argv
    with monkeypatch.context() as m:  # the page read again with other rules: the claim is not current
        m.setattr(extract, "extract_config", lambda: "extract-other")
        out = hl(gct, claim, version)
        assert out.code == 4 and "so it cannot be highlighted" in out.err and f"gct extract {doc}" in out.err
    assert counts(db) == before
    assert hl(gct, claim, version).code == 0
    assert counts(db) == {**before, "highlight": 1}


# AC 3 (FR36): three records in three tables; none changes the others' output, states or counts
def test_highlight_correction_and_confirmation_are_three_separate_records(ws, db, gct, one):
    doc, claim, version = one
    assert rec(gct, "company", claim, version).code == 0
    seen = {"history": gct("claims", "history", claim, "--json").data, "list": gct("claims", "list", "--doc", doc,
            "--json").data, "review": gct("review", "list", claim, "--json").data,
            "pending": gct("review", "pending", "--json").data, "plan": gct("doc", "archive", doc, "--plan", "--json").data}
    assert hl(gct, claim, version).code == 0
    plan = gct("doc", "archive", doc, "--plan", "--json").data
    assert plan["impact"]["review_records"] == {**seen["plan"]["impact"]["review_records"], "highlight": 1}
    assert {"history": gct("claims", "history", claim, "--json").data, "list": gct("claims", "list", "--doc", doc,
            "--json").data, "review": gct("review", "list", claim, "--json").data,
            "pending": gct("review", "pending", "--json").data, "plan": seen["plan"]} == seen
    assert gct("correct", claim, "--value", "1,235", "--as", "ana", "--capacity", "c", "--rationale", "r").code == 0
    assert [len(rows(db, t)) for t in ("highlight", "correction", "review_company")] == [1, 1, 1]
    # Matrix: the highlight stays on v1, no longer binds, and is not a renewed-review entry.
    new = newest(gct, claim)
    vs = versions(gct, claim)
    assert [(h["claim_version"], h["binds"]) for h in vs[version]["highlights"]] == [(version, False)]
    assert vs[new]["highlights"] == [] and "(on an earlier version)" in gct("highlight", "list", claim).out
    needs = gct("claims", "history", claim, "--json").data["claim"]["needs_re_review"]
    assert [e["kind"] for e in needs] == ["company confirmation"]
    assert all(e["entry"]["kind"] != "highlight" for k in gct("review", "pending", "--json").data["kinds"] for e in k["entries"])


# Matrix row "two highlights by one contributor"
def test_two_highlights_by_one_contributor_are_both_listed_and_the_newest_is_latest(ws, db, gct, one):
    doc, claim, version = one
    for note in ("first look", "second look"):
        assert hl(gct, claim, version, note).code == 0
    assert hl(gct, claim, version, "own view", "cara").code == 0
    hs = versions(gct, claim)[version]["highlights"]
    assert [(h["note"], h["contributor"], h["latest"]) for h in hs] == [
        ("first look", "Ana", False), ("second look", "Ana", True), ("own view", "Cara", True)]
    assert "(an earlier highlight of this contributor)" in gct("highlight", "list", claim).out


# AC 5: archive counts them and hides them from the projection; restore brings them back
def test_archive_hides_the_highlights_and_restore_brings_them_back(ws, db, gct, one):
    doc, claim, version = one
    assert hl(gct, claim, version).code == 0
    assert len(projected(ws, gct, "highlight")) == 1
    stored = rows(db, "highlight")
    who = ("--as", "ana", "--capacity", "c", "--rationale", "r")
    assert gct("doc", "archive", doc, "--plan", "--json").data["impact"]["review_records"]["highlight"] == 1
    assert "1 reviewer flags" not in gct("doc", "archive", doc, "--plan").out
    assert "0 reviewer flags, 1 highlights" in gct("doc", "archive", doc, "--plan").out
    assert gct("doc", "archive", doc, *who).code == 0
    assert projected(ws, gct, "highlight") == []
    v = published.open_version(sorted((ws / "published").glob("v*.db"))[-1])
    try:
        assert v.execute("SELECT review_records FROM hidden_by_archive").fetchone()[0] == 1
    finally:
        v.close()
    assert len(versions(gct, claim)[version]["highlights"]) == 1  # still listed
    assert hl(gct, claim, version).code == 4
    assert gct("doc", "restore", doc, *who).code == 0
    assert rows(db, "highlight") == stored and len(projected(ws, gct, "highlight")) == 1


# AC 5: deletion on a synthetic workspace; canaries in a note and capacity found before and not after
D_CANARIES = ("zqhlnote", "zqhlcap")
A_CANARIES = ("zqhlkeepnote", "zqhlkeepcap")


def test_deletion_clears_the_highlights_text_and_keeps_the_rows(ws, db, gct, world):
    d, claim, other = world["d"], world["claim"], world["other"]
    assert hl(gct, claim, newest(gct, claim), D_CANARIES[0], "ana", D_CANARIES[1]).code == 0
    assert hl(gct, other, newest(gct, other), A_CANARIES[0], "ana", A_CANARIES[1]).code == 0
    for _ in range(2):  # both retained versions hold the two highlights
        assert gct("publish", "build").code == 0
    gone, keep = rows(db, "highlight")
    assert scan(ws, canaries=D_CANARIES + A_CANARIES) == set(D_CANARIES + A_CANARIES)
    retained = sorted((ws / "published").glob("v*.db"))
    assert gct("doc", "delete", d, "--confirm", token(db, d), *DELETE_WHO).code == 0
    assert scan(ws, canaries=D_CANARIES + A_CANARIES) == set(A_CANARIES)
    marker = f"cleared with document {d}"
    after = rows(db, "highlight")
    assert after[1] == keep  # another document's highlight is byte-identical
    assert {k: v for k, v in after[0].items() if k not in ("capacity", "note")} == {
        k: v for k, v in gone.items() if k not in ("capacity", "note")}
    assert (after[0]["capacity"], after[0]["note"]) == (marker, marker)
    at = db.execute("SELECT at FROM document_state WHERE document_id = ? AND state = 'deleted'", (d,)).fetchone()[0]
    (e,) = versions(gct, claim)[gone["claim_version_id"]]["highlights"]
    assert e["evidence_deleted"] == {"document": d, "at": at} and e["note"] == marker
    assert f"evidence deleted (document {d}, {at[:10]})" in gct("highlight", "list", claim).out
    for path in retained:
        conn = published.open_version(path)
        try:
            assert [r[0] for r in conn.execute("SELECT id FROM highlight")] == [keep["id"]]
        finally:
            conn.close()


# AC 6
def test_projection_schema_14(ws, db, gct, one):
    doc, claim, version = one
    mark = published.history_mark(db)
    assert hl(gct, claim, version, "a note", "cara").code == 0
    assert published.history_mark(db) != mark
    v = gct("publish", "build", "--json").data["version"]
    conn = published.open_version(ws / "published" / f"v{v}.db")
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        (h,) = [dict(r) for r in conn.execute("SELECT * FROM highlight")]
        tables = {t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    assert meta["projection_schema"] == "16"
    assert {"review_company", "review_auditor", "adjudication", "reviewer_flag", "claim", "comparison"} <= tables
    assert h == {"id": 1, "claim_id": claim, "claim_version_id": version, "contributor_name": "Cara",
                 "contributor_organisation": "Audit LLP", "capacity": "analyst", "note": "a note", "latest": 1,
                 "binds": 1, "created_at": h["created_at"]}
