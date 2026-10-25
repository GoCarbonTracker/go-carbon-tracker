"""Story 4.4: archive and restore a document. No real report is used."""
import json
import sqlite3

import pytest

from test_api import call, cookie
from test_extract import count
from test_match import SCOPE_1, WHO, acme, add, ready  # noqa: F401 (acme is a fixture)
from gct.api import server
from gct.stages import read
from gct.workspace import layout, published, registry, runs, store

B_ROW = [["Total Scope 1 emissions", "tCO2e", "1,150"]]
UNCERTAIN = [["Total Scope 1 emissions", "tCO2e", "999"]]
# Every table that holds a document's history; an archive adds only to the first two.
HISTORY = ("document_state", "document_state_change", "document", "claim", "claim_version", "evidence_ref",
           "source_match", "page", "artifact", "attempt", "basis", "inference", "inference_review", "correction",
           "claim_seen", "metric_assignment", "match_review", "expected_item", "expected_item_document",
           "page_acceptance", "gap_confirmation")


@pytest.fixture
def two(ws, gct, make_file, acme):
    """Documents a (FY 2024-25 and FY 2023-24) and b (FY 2023-24): one ghg_scope_1 series of three points whose
    FY 2023-24 period is a same-period set; d has no boundary statement, so its point is an uncertain item."""
    a = add(gct, make_file, "a.pdf", [SCOPE_1])
    b = add(gct, make_file, "b.pdf", B_ROW, periods=("FY 2023-24",))
    d = add(gct, make_file, "d.pdf", UNCERTAIN, periods=("FY 2024-25",), boundary=None)
    ready(gct)
    return a, b, d


def counts(db) -> dict:
    return {t: count(db, t) for t in HISTORY}


def scope_1(gct) -> dict:
    (s,) = gct("series", "list", "--json").data["series"]
    return gct("series", "show", s["id"], "--all", "--json").data["series"]


def built(gct, ws) -> dict:
    v = gct("publish", "build", "--json").data
    conn = published.open_version(ws / "published" / f"v{v['version']}.db")
    try:
        return {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")] for t in (
            "meta", "document", "claim", "evidence_ref", "series", "series_point", "expected_item_document",
            "page_acceptance", "gap_confirmation", "hidden_by_archive", "comparison", "restatement")}
    finally:
        conn.close()


# AC 1 and AC 9: a 4.1 workspace gets 0013 (story 4.2), 0014 then 0015 (story 4.3), in order, in one recorded upgrade
def test_migrations_13_14_then_15_apply_to_a_version_12_workspace(tmp_path, gct):
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
    assert [r[0] for r in c.execute("SELECT version FROM schema_version ORDER BY version")][-11:] == [
        12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
    (run,) = runs.list_runs(c)
    assert [e["message"] for e in runs.show_run(c, run["id"])["events"] if e["kind"] == "note"] == [
        "applied migration 13", "applied migration 14", "applied migration 15", "applied migration 16",
        "applied migration 17", "applied migration 18", "applied migration 19", "applied migration 20",
        "applied migration 21", "applied migration 22"]
    assert {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} >= {
        "restatement", "document_state_change", "sheet_mapping", "claim_note"}
    c.close()


def test_state_change_is_append_only_and_one_per_state(db):
    db.execute("INSERT INTO company (name, created_at) VALUES ('Acme', 't')")
    db.execute("INSERT INTO document (company_id, logical_name, version, sha256, kind, file_type, privacy, size_bytes,"
               " created_at) VALUES (1, 'a.pdf', 1, 'x', 'report', 'pdf', 'private', 1, 't')")
    db.execute("INSERT INTO document_state (document_id, state, at) VALUES (1, 'archived', 't')")
    row = ("INSERT INTO document_state_change (document_state_id, contributor_version_id, capacity, rationale,"
           " created_at) VALUES (1, 1, 'analyst', 'superseded', 't')")
    db.execute(row)
    for stmt in ("UPDATE document_state_change SET id = id", "DELETE FROM document_state_change"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
            db.execute(stmt)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        db.execute(row)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO document_state_change (document_state_id, contributor_version_id, capacity,"
                   " created_at) VALUES (1, 1, 'analyst', 't')")


# AC 2
def test_archive_stores_one_state_and_one_change_and_keeps_everything(ws, db, gct, two):
    a, b, d = two
    gct("expect", "add", "--company", "Acme", "--metric", "scope 1 emissions")
    gct("pages", "accept", "--doc", b, "--pages", "1", "--type", "figures", *WHO)
    before = counts(db)
    r = gct("doc", "archive", b, *WHO, "--json")
    assert r.code == 0 and r.data["document"]["state"] == "archived"
    after = counts(db)
    assert {t: after[t] - before[t] for t in HISTORY if after[t] != before[t]} == {"document_state": 1,
                                                                                 "document_state_change": 1}
    change = db.execute("SELECT x.*, s.state, s.document_id FROM document_state_change x"
                        " JOIN document_state s ON s.id = x.document_state_id").fetchone()
    assert (change["document_id"], change["state"], change["capacity"], change["rationale"]) == (
        b, "archived", "analyst", "checked on the page")
    assert change["contributor_version_id"] == db.execute("SELECT MAX(id) FROM contributor_version").fetchone()[0]
    assert registry.stored_path(ws, db.execute("SELECT sha256 FROM document WHERE id = ?", (b,)).fetchone()[0]).is_file()
    again = gct("doc", "archive", b, *WHO)
    assert again.code == 4 and f"Document {b} is already archived." in again.err and f"gct doc restore {b}" in again.err
    assert gct("doc", "archive", b, "--plan").code == 4
    active = gct("doc", "restore", a, *WHO)
    assert active.code == 4 and f"Document {a} is not archived" in active.err
    assert gct("doc", "archive", a).code == 2  # the attribution is needed without --plan
    assert counts(db) == after
    assert gct("doc", "restore", b, *WHO).code == 0
    assert counts(db)["document_state_change"] == after["document_state_change"] + 1
    assert gct("doc", "show", b, "--json").data["document"]["state"] == "restored"


# AC 3
def test_an_archived_document_leaves_every_active_output(ws, db, gct, two):
    a, b, d = two
    e = gct("expect", "add", "--company", "Acme", "--metric", "scope 1 emissions", "--json").data["expectation"]["id"]
    assert {c["document_id"] for c in gct("expect", "list", "--json").data["expectations"][0]["claims"]} == {a, b, d}
    assert len(scope_1(gct)["points"]) == 3 and gct("match", "review", "--json").data["items"]
    for doc in (b, d):
        assert gct("doc", "archive", doc, *WHO).code == 0
    of_b = ("SELECT COUNT(*) FROM attempt WHERE item = ? OR item LIKE ?", (str(b), f"{b}:%"))
    attempts = db.execute(*of_b).fetchone()[0]
    for step in ("read", "extract", "link", "infer", "match"):
        r = gct(step, "--json")
        assert r.code == 0 and [x["id"] for x in r.data["documents"]] == [a], step
        named = gct(step, *(("--doc", b) if step in ("infer", "match") else (b,)), "--json")
        assert named.code == 0, step
        assert [(x["id"], x["action"], x["cause"]) for x in named.data["documents"]] == [(b, "skipped", read.NOT_ACTIVE)]
    assert db.execute(*of_b).fetchone()[0] == attempts  # nothing was written for b
    shown = scope_1(gct)
    assert [(p["document_id"], p["same_period"]) for p in shown["points"]] == [(a, 1), (a, 1)]
    assert shown["same_period_sets"] == 0
    (st,) = gct("match", "status", "--json").data["companies"]
    assert (st["claims"], st["same_period_sets"], st["uncertain_items"]) == (2, 0, 0)
    assert gct("match", "review", "--json").data["items"] == []
    (x,) = gct("expect", "list", "--json").data["expectations"]
    assert x["id"] == e and x["documents"] == [a] and {c["document_id"] for c in x["claims"]} == {a}


# AC 4
def test_writes_on_an_archived_document_are_refused(ws, db, gct, two):
    a, b, d = two
    claim = gct("claims", "list", "--doc", b, "--json").data["claims"][0]["id"]
    basis = next(x["id"] for x in gct("infer", "bases", "--json").data["bases"]
                 if x["document"] == b and x["kind"] == "reporting_boundary")
    assert gct("doc", "archive", b, *WHO).code == 0
    before = counts(db)
    for argv in (["correct", claim, "--value", "1,151"],
                 ["infer", "resolve", claim, "--field", "boundary", "--boundary", "standalone"],
                 ["infer", "reject", "--claim", claim, "--field", "period"],
                 ["infer", "scope", basis, "--pages", "1"],
                 ["pages", "accept", "--doc", b, "--pages", "1", "--type", "figures"]):
        r = gct(*argv, *WHO)
        assert r.code == 4 and r.err == f"error: Document {b} is archived.\nnext: Restore it with: gct doc restore {b}\n", argv
    assert counts(db) == before
    h = gct("claims", "history", claim, "--json")
    assert h.code == 0 and h.data["claim"]["document_state"] == "archived" and h.data["versions"]
    assert f"document {b} (archived)" in gct("claims", "history", claim).out.splitlines()[0]
    assert gct("doc", "pages", b).out.splitlines()[0] == f"Document {b} is archived."
    assert gct("doc", "pages", b, "--json").data["document_state"] == "archived"  # review L1
    assert gct("doc", "pages", a, "--json").data["document_state"] == "registered"
    assert gct("doc", "pages", a).out.splitlines()[0].startswith("p1")


def test_a_gap_confirmed_while_archived_reads_older_after_restore(ws, db, gct, two):
    a, b, d = two
    e = gct("expect", "add", "--company", "Acme", "--metric", "water", "--doc", a, b, "--json").data["expectation"]["id"]
    for doc in (a, b):
        assert gct("pages", "accept", "--doc", doc, "--pages", "1", "--type", "figures", *WHO).code == 0
    assert gct("doc", "archive", b, *WHO).code == 0
    r = gct("gap", "confirm", e, *WHO, "--json")
    x = r.data["expectation"]
    assert r.code == 0 and x["state"] == "confirmed disclosure gap" and x["documents"] == [a]
    assert gct("doc", "restore", b, *WHO).code == 0
    (x,) = gct("expect", "list", "--json").data["expectations"]
    assert x["documents"] == [a, b] and x["confirmation"]["current"] is False
    assert x["state"] == "not found in successfully processed material"
    assert {"type": "confirmation", "count": 1,
            "reason": f"earlier gap confirmation #{x['confirmation']['id']} was made on older readings"} in x["reasons"]


def test_an_expectation_with_every_document_archived_is_never_a_gap(ws, db, gct, two):
    # review M2
    a, b, d = two
    e = gct("expect", "add", "--company", "Acme", "--metric", "water", "--doc", b, "--json").data["expectation"]["id"]
    assert gct("pages", "accept", "--doc", b, "--pages", "1", "--type", "figures", *WHO).code == 0
    (before,) = gct("expect", "list", "--json").data["expectations"]
    assert before["state"] == "not found in successfully processed material"
    assert gct("doc", "archive", b, *WHO).code == 0
    (x,) = gct("expect", "list", "--json").data["expectations"]
    assert (x["documents"], x["state"]) == ([], "processing incomplete or failed")
    assert x["reasons"] == [{"type": "document", "reason": "no active document in its declared set", "count": 1}]
    head, reason = gct("expect", "list").out.splitlines()[:2]
    assert head.endswith(f"documents none active (archived: {b})  processing incomplete or failed")
    assert reason == "  document: no active document in its declared set (1 declared)"  # review LOW-2
    gaps = count(db, "gap_confirmation")
    r = gct("gap", "confirm", e, *WHO)
    assert r.code == 4 and r.err == (
        f"error: Expectation {e} cannot be confirmed as a gap: no document in its declared set is active.\n"
        f"next: Restore one with: gct doc restore {b}. See the expectations with: gct expect list\n")
    assert count(db, "gap_confirmation") == gaps
    assert gct("doc", "restore", b, *WHO).code == 0
    assert gct("expect", "list", "--json").data["expectations"] == [before]


def test_a_gap_confirmation_stays_projected_and_is_not_counted_as_hidden(ws, gct, two):
    # review LOW-1: y over {a, b} confirmed, then b archived
    a, b, d = two
    for doc in (a, b):
        assert gct("pages", "accept", "--doc", doc, "--pages", "1", "--type", "figures", *WHO).code == 0
    y = gct("expect", "add", "--company", "Acme", "--metric", "water", "--doc", a, b, "--json").data["expectation"]["id"]
    assert gct("gap", "confirm", y, *WHO).code == 0
    impact = gct("doc", "archive", b, "--plan", "--json").data["impact"]
    assert "gap_confirmation" not in impact["review_records"] and impact["expected_items"] == [y]
    assert "gap confirmation" not in gct("doc", "archive", b, "--plan").out
    assert gct("doc", "archive", b, *WHO).code == 0
    p = built(gct, ws)
    assert [g["expected_item_id"] for g in p["gap_confirmation"]] == [y]
    assert [h["review_records"] for h in p["hidden_by_archive"]] == [sum(impact["review_records"].values())]


def test_expect_add_refuses_an_archived_document(ws, db, gct, two):
    # review M2
    a, b, d = two
    assert gct("doc", "archive", b, *WHO).code == 0
    items = count(db, "expected_item")
    r = gct("expect", "add", "--company", "Acme", "--metric", "water", "--doc", a, b)
    assert r.code == 4 and r.err == f"error: Document {b} is archived.\nnext: Restore it with: gct doc restore {b}\n"
    assert count(db, "expected_item") == items
    default = gct("expect", "add", "--company", "Acme", "--metric", "water", "--json").data["expectation"]
    assert default["documents"] == [a, d]


def test_adding_an_archived_document_again_says_how_to_restore_it(ws, gct, two, tmp_path):
    # review L2
    a, b, d = two
    assert gct("doc", "archive", b, *WHO).code == 0
    src = tmp_path / "src" / "b.pdf"
    for argv in (("doc", "add", src, "--company", "Acme"), ("doc", "add", src, "--company", "Acme", "--plan")):
        r = gct(*argv)
        assert r.code == 0
        lines = r.out.splitlines()
        assert lines[0] == f"duplicate of {b}: {src}" and lines[1] == f"It is archived. Restore it with: gct doc restore {b}"
        (item,) = gct(*argv, "--json").data["items"]
        assert (item["action"], item["cause"], item["next_action"]) == (
            "duplicate", None, f"Restore it with: gct doc restore {b}")
    (item,) = gct("doc", "add", tmp_path / "src" / "a.pdf", "--company", "Acme", "--json").data["items"]
    assert (item["action"], item["next_action"]) == ("duplicate", None)


# AC 5
def test_plan_shows_the_impact_and_stores_nothing(ws, db, gct, two):
    a, b, d = two
    e = gct("expect", "add", "--company", "Acme", "--metric", "scope 1 emissions", "--json").data["expectation"]["id"]
    gct("pages", "accept", "--doc", b, "--pages", "1", "--type", "figures", *WHO)
    mark = published.history_mark(db)
    plan = gct("doc", "archive", b, "--plan", "--json")
    assert plan.code == 0 and plan.data["state_change"] is None and plan.data["document"]["state"] == "registered"
    assert published.history_mark(db) == mark
    text = gct("doc", "archive", b, "--plan").out
    assert text.rstrip().endswith("Nothing was stored.") and "2 values become 1" in text
    i = plan.data["impact"]
    sid = scope_1(gct)["id"]
    assert (i["claims"], i["evidence_refs"], i["uncertain_items"], i["expected_items"]) == (1, 1, 0, [e])
    assert [(s["id"], s["metric_key"], s["points"], s["points_left"]) for s in i["series"]] == [(sid, "ghg_scope_1", 1, 2)]
    assert [(s["series"], s["period_end"], s["points"], s["points_left"]) for s in i["same_period_sets"]] == [
        (sid, "2024-03-31", 2, 1)]
    reviews = db.execute("SELECT COUNT(*) FROM inference_review r JOIN claim_version v ON v.id = r.claim_version_id"
                         " JOIN claim c ON c.id = v.claim_id WHERE c.document_id = ?", (b,)).fetchone()[0]
    assert reviews and i["review_records"] == {"inference_review": reviews, "correction": 0, "match_review": 0,
                                               "page_acceptance": 1, "restatement": 0, "sheet_mapping": 0,
                                               "review_company": 0, "review_auditor": 0,
                                               "adjudication": 0, "reviewer_flag": 0, "highlight": 0}
    assert gct("doc", "archive", d, "--plan", "--json").data["impact"]["uncertain_items"] == 1
    real = gct("doc", "archive", b, *WHO, "--json").data
    assert real["impact"] == i and real["state_change"]["state"] == "archived"
    assert published.history_mark(db) != mark


# AC 6
def test_restore_brings_every_output_back_unchanged(ws, db, gct, two):
    a, b, d = two
    sid = scope_1(gct)["id"]

    def outputs():
        p = built(gct, ws)
        return (gct("match", "status", "--json").data, gct("series", "show", sid, "--all", "--json").data,
                p["claim"], p["series"], p["series_point"])

    before = outputs()
    assert gct("doc", "archive", b, *WHO).code == 0
    assert outputs() != before
    assert gct("doc", "restore", b, *WHO).code == 0
    assert outputs() == before


# AC 7
def test_projection_hides_archived_documents_and_counts_them(ws, db, gct, two):
    a, b, d = two
    gct("expect", "add", "--company", "Acme", "--metric", "scope 1 emissions")
    gct("pages", "accept", "--doc", b, "--pages", "1", "--type", "figures", *WHO)
    p = built(gct, ws)
    assert {m["key"]: m["value"] for m in p["meta"]}["projection_schema"] == "16"
    assert p["hidden_by_archive"] == [] and b in {x["id"] for x in p["document"]}
    assert [x["document_id"] for x in p["page_acceptance"]] == [b]
    mark = published.history_mark(db)
    impact = gct("doc", "archive", b, *WHO, "--json").data["impact"]
    assert published.history_mark(db) != mark
    p = built(gct, ws)
    meta = {m["key"]: m["value"] for m in p["meta"]}
    assert b not in {x["id"] for x in p["document"]}
    assert not [r for t in ("claim", "evidence_ref") for r in p[t] if r["document_id"] == b]
    claims_of_b = {c for (c,) in db.execute("SELECT id FROM claim WHERE document_id = ?", (b,))}
    assert not [r for r in p["series_point"] if r["claim_id"] in claims_of_b]
    # Story 7.1 part B (K8) changes 4.4 AC 7 on purpose: the archived declared document stays linked, by id and state.
    assert {(r["document_id"], r["state"]) for r in p["expected_item_document"]} == {
        (a, "registered"), (b, "archived"), (d, "registered")}
    assert p["page_acceptance"] == [] and impact["review_records"]["page_acceptance"] == 1  # review M1
    (h,) = p["hidden_by_archive"]
    at = db.execute("SELECT at FROM document_state WHERE document_id = ? ORDER BY id DESC LIMIT 1", (b,)).fetchone()[0]
    assert h == {"document_id": b, "logical_name": "b.pdf", "archived_at": at, "claims": impact["claims"],
                 "evidence_refs": impact["evidence_refs"], "review_records": sum(impact["review_records"].values())}
    assert json.loads(meta["hidden_by_archive"]) == {"documents": 1, "claims": 1, "evidence_refs": 1,
                                                    "review_records": h["review_records"]}
    srv = server.serve(ws, port=0)
    try:
        assert call(srv.port, f"/api/documents/{b}", **cookie(srv))[0] == 404
        assert call(srv.port, f"/api/documents/{a}", **cookie(srv))[0] == 200
    finally:
        srv.stop()
    mark = published.history_mark(db)
    assert gct("doc", "restore", b, *WHO).code == 0
    assert published.history_mark(db) != mark
    assert built(gct, ws)["hidden_by_archive"] == []


# AC 8
def test_doc_list_and_show_name_the_state_and_who_archived(ws, db, gct, two):
    a, b, d = two
    assert gct("doc", "show", b, "--json").data["state_change"] is None
    assert gct("doc", "archive", b, *WHO).code == 0
    lines = gct("doc", "list").out.splitlines()
    assert [line.split()[-1] for line in lines] == ["registered", "archived", "registered"]
    active = gct("doc", "list", "--active")
    assert [line.split()[0] for line in active.out.splitlines()[:-1]] == [str(a), str(d)]
    assert active.out.splitlines()[-1] == "1 archived document hidden. Show every document with: gct doc list"
    j = gct("doc", "list", "--active", "--json").data
    assert [x["id"] for x in j["documents"]] == [a, d] and j["hidden_by_archive"] == 1
    assert gct("doc", "list", "--json").data["hidden_by_archive"] == 0
    show = gct("doc", "show", b, "--json").data
    at = db.execute("SELECT at FROM document_state WHERE document_id = ? ORDER BY id DESC LIMIT 1", (b,)).fetchone()[0]
    assert show["state_change"] == {"state": "archived", "at": at, "contributor": "Ana", "organisation": "Acme audit",
                                    "capacity": "analyst", "rationale": "checked on the page"}
    assert gct("doc", "show", b).out.splitlines()[-1] == (
        f"archived by Ana, Acme audit (analyst) at {at}: checked on the page")


# Integration with story 4.2: restatements of an archived document
def test_restatements_leave_with_an_archived_document_and_come_back(ws, gct, make_file, acme):
    from test_restate import cp2, record

    a, b, restated, original = cp2(gct, make_file)
    assert record(gct, original, restated).code == 0
    listed = gct("restate", "list", "--json").data, gct("restate", "list").out
    full = built(gct, ws)
    assert (len(full["comparison"]), len(full["restatement"])) == (1, 1)
    # The record names b's version as the original, so it counts as one of b's review records.
    plan = gct("doc", "archive", b, "--plan", "--json").data["impact"]["review_records"]
    assert plan["restatement"] == 1 and "1 restatement records" in gct("doc", "archive", b, "--plan").out
    assert gct("doc", "archive", b, *WHO).code == 0
    # 2a: the pair and the record naming a version of document b leave the projection
    hid = built(gct, ws)
    assert (hid["comparison"], hid["restatement"]) == ([], [])
    assert [h["review_records"] for h in hid["hidden_by_archive"]] == [sum(plan.values())]
    # 2b
    show, v = gct("restate", "show", original), gct("restate", "show", original, "--json").data["claim"]["version"]
    assert show.code == 0 and show.out.splitlines()[:2] == [
        f"claim {original}  document {b} p1  version {v}  Document {b} is archived.", "No pairs."]
    assert "None" not in show.out
    # 2c
    for r in (record(gct, original, restated),
              gct("restate", "withdraw", "--original", original, "--restated", restated, *WHO)):
        assert r.code == 4 and r.err.startswith(f"error: Document {b} is archived.") and f"gct doc restore {b}" in r.err
    # 2d
    assert gct("doc", "restore", b, *WHO).code == 0
    assert (gct("restate", "list", "--json").data, gct("restate", "list").out) == listed
    back = built(gct, ws)
    assert (back["comparison"], back["restatement"]) == (full["comparison"], full["restatement"])


# Story 4.3 on 4.4: a superseded mapping is a review record too, as it is projected beside the current one
def test_archive_and_restore_of_a_spreadsheet(ws, gct, make_file, acme):
    from test_sheet import MAP, ROWS, add as add_sheet, csv_bytes

    doc = add_sheet(gct, make_file, "m.csv", csv_bytes(ROWS))
    gct("sheet", "map", doc, "--sheet", "m", "--metric", "Metric", "--value", "Value", *WHO)  # superseded
    gct("sheet", "map", doc, "--sheet", "m", *MAP, *WHO)  # current
    gct("extract", doc)

    def mappings(p):
        return [(m["id"], m["document_id"], m["value_col"], m["note_col"]) for m in p["sheet_mapping"]]

    def projected():
        v = gct("publish", "build", "--json").data
        conn = published.open_version(ws / "published" / f"v{v['version']}.db")
        try:
            return {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1")]
                    for t in ("sheet_mapping", "claim", "hidden_by_archive")}
        finally:
            conn.close()

    before = projected()
    assert mappings(before) == [(1, doc, "Value", None), (2, doc, "Value", "Note")] and len(before["claim"]) == 2
    plan = gct("doc", "archive", doc, "--plan", "--json").data["impact"]
    assert plan["review_records"]["sheet_mapping"] == 2 and ", 2 sheet mappings" in gct("doc", "archive", doc, "--plan").out
    real = gct("doc", "archive", doc, *WHO, "--json").data
    assert real["impact"] == plan and real["impact"]["review_records"]["sheet_mapping"] == 2
    hid = projected()
    assert hid["sheet_mapping"] == [] and hid["claim"] == []
    assert [(h["document_id"], h["claims"], h["review_records"]) for h in hid["hidden_by_archive"]] == [
        (doc, 2, sum(plan["review_records"].values()))] and sum(plan["review_records"].values()) == 2
    assert gct("doc", "restore", doc, *WHO).code == 0
    back = projected()
    assert mappings(back) == mappings(before) and back["claim"] == before["claim"] and back["hidden_by_archive"] == []
