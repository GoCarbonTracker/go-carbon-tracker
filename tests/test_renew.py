"""Story 5.2: claim-version binding and renewed review (FR24). A newer claim version asks for the company
confirmations, auditor reviews, reviewer flags and adjudications made on an earlier one to be made again; nothing
recorded earlier moves or changes. Synthetic workspaces only; no real report."""
import json

from test_adjudicate import adj, four  # noqa: F401 (four is a fixture)
from test_api import call, cookie
from test_deletion import token
from test_link import add_reading, doc  # noqa: F401 (doc is a fixture: read and extracted once)
from test_match import WHO, ready
from test_reprocess import ENERGY, claims, set_word
from test_restate import QUOTE, acme, cp2  # noqa: F401 (acme is a fixture)
from test_review import SELF, newest, one, rec  # noqa: F401 (one is a fixture)
from test_sheet import MAP, ROWS, csv_bytes
from gct.api import server
from gct.stages import correct
from gct.workspace import published

KEPT = ("review_company", "review_auditor", "adjudication", "reviewer_flag", "correction", "inference_review")


def snapshot(db) -> dict:
    """R3: every E5 table and the 3.5 record tables, row by row."""
    return {t: [tuple(r) for r in db.execute(f"SELECT * FROM {t} ORDER BY id")] for t in KEPT}


def counts(db) -> dict:
    return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}


def needs(gct, claim) -> list:
    return gct("claims", "history", claim, "--json").data["claim"]["needs_re_review"]


def fix(gct, claim, value):
    return gct("correct", claim, "--value", value, *WHO)


def pending(gct, *args) -> dict:
    """{kind: [(claim, entry)]} of gct review pending."""
    return {k["kind"]: [(e["claim"], e["entry"]) for e in k["entries"]]
            for k in gct("review", "pending", *args, "--json").data["kinds"]}


def flag(gct, verb, claim, version, who=WHO):
    return gct("flag", verb, claim, "--version", version, *who)


def entry(kind, rid, version, other=None) -> dict:
    return {"kind": kind, "id": rid, "version": version, **({"with": dict(zip(("claim", "version"), other))} if other else {})}


# Matrix rows 1 to 4
def test_a_ledger_entry_on_an_earlier_version_asks_for_renewal_and_stays_where_it_was(ws, db, gct, one):
    doc, claim, v1 = one
    company = rec(gct, "company", claim, v1, "rejected", "--json").data["entry"]
    auditor = rec(gct, "auditor", claim, v1, "disputed", "--json", who="cara").data["entry"]
    assert needs(gct, claim) == [] and pending(gct) == {}
    held = snapshot(db)
    assert fix(gct, claim, "1,235").code == 0
    v2 = newest(gct, claim)
    want = [entry("company confirmation", company["id"], v1), entry("auditor review", auditor["id"], v1)]
    assert needs(gct, claim) == want  # any outcome, rejected and disputed included
    out = gct("claims", "history", claim).out
    assert f"needs re-review: company confirmation #{company['id']} on version {v1}" in out
    assert f"needs re-review: auditor review #{auditor['id']} on version {v1}" in out
    assert {k: v for k, v in snapshot(db).items() if k != "correction"} == {k: v for k, v in held.items() if k != "correction"}
    (h1, h2) = gct("claims", "history", claim, "--json").data["versions"]
    assert [(e["id"], e["binds"]) for e in h1["company_confirmations"] + h1["auditor_reviews"]] == [
        (company["id"], False), (auditor["id"], False)]
    assert h2["company_confirmations"] == h2["auditor_reviews"] == []  # nothing is carried to v2
    # A company confirmation on v2 by another contributor clears the company entry; the auditor entry stays.
    assert rec(gct, "company", claim, v2, "accepted", who="bob").code == 0
    assert needs(gct, claim) == want[1:]
    assert rec(gct, "auditor", claim, v2, "accepted", who="dev").code == 0
    assert needs(gct, claim) == []
    assert snapshot(db)["review_company"][:1] == held["review_company"]
    assert snapshot(db)["review_auditor"][:1] == held["review_auditor"]


# Matrix rows 5 and 6
def test_a_flag_still_raised_asks_for_renewal_and_a_withdrawn_one_does_not(ws, db, gct, one):
    doc, claim, v1 = one
    assert flag(gct, "raise", claim, v1).code == 0
    assert flag(gct, "withdraw", claim, v1).code == 0
    assert fix(gct, claim, "1,235").code == 0
    assert needs(gct, claim) == []  # withdrawn on v1 by its only contributor
    v2 = newest(gct, claim)
    bob = ("--as", "bob", "--capacity", "auditor", "--rationale", "framed as achieved")
    assert flag(gct, "raise", claim, v2).code == 0
    assert flag(gct, "withdraw", claim, v2).code == 0
    raised = gct("flag", "raise", claim, "--version", v2, *bob, "--json").data["flag"]
    assert fix(gct, claim, "1,236").code == 0
    v3 = newest(gct, claim)
    assert needs(gct, claim) == [entry("reviewer flag", raised["id"], v2)]  # Bob's latest on v2 is raised
    before = snapshot(db)
    r = flag(gct, "withdraw", claim, v2, bob)
    assert r.code == 4 and f"gct claims history {claim}" in r.err  # not the newest version
    assert snapshot(db) == before and needs(gct, claim) == [entry("reviewer flag", raised["id"], v2)]
    assert f"reviewer flag #{raised['id']} on version {v2}" in gct("claims", "history", claim).out
    assert flag(gct, "raise", claim, v3).code == 0  # any flag row on the current version clears it
    assert needs(gct, claim) == []
    assert snapshot(db)["reviewer_flag"][:len(before["reviewer_flag"])] == before["reviewer_flag"]


# Matrix row 7
def test_an_adjudication_asks_both_claims_while_their_pair_is_unreviewed(ws, db, gct, four):
    a, b = four["ghg_scope_1"]
    other_a, other_b = four["ghg_scope_2"]
    x = adj(gct, a, b, "evidence-not-found", "--json").data["adjudication"]
    y = adj(gct, other_a, other_b, "reviewer-confirmed-issue", "--json").data["adjudication"]
    va, vb = (x["low_version"], x["high_version"]) if x["low_claim"] == a else (x["high_version"], x["low_version"])
    assert needs(gct, a) == needs(gct, b) == []
    held = snapshot(db)
    assert fix(gct, b, "1,151").code == 0
    ready(gct)  # the corrected claim joins a pair again once its period and boundary are reviewed again
    assert needs(gct, b) == [entry("adjudication", x["id"], vb, (a, va))]
    assert needs(gct, a) == [entry("adjudication", x["id"], va, (b, vb))]  # unchanged, its pair is unreviewed
    assert needs(gct, other_a) == needs(gct, other_b) == []  # the other pair still binds
    assert f"needs re-review: adjudication #{x['id']} on version {vb} with claim {a} version {va}" in gct(
        "claims", "history", b).out
    assert pending(gct)["adjudication"] == [(a, entry("adjudication", x["id"], va, (b, vb))),
                                            (b, entry("adjudication", x["id"], vb, (a, va)))]
    assert snapshot(db)["adjudication"] == held["adjudication"]
    assert [r["binds"] for r in gct("adjudicate", "list", "--claim", other_a, "--json").data["candidates"][0][
        "adjudications"]] == [True] and y["id"] > x["id"]
    # A binding adjudication of the claims' current pair clears both entries.
    assert adj(gct, a, b, "extraction-error").code == 0
    assert needs(gct, a) == needs(gct, b) == [] and "adjudication" not in pending(gct)


# Matrix row 8
def test_a_pair_that_became_a_restatement_asks_for_no_adjudication(ws, db, gct, make_file, acme):
    _, _, restated, original = cp2(gct, make_file)
    x = adj(gct, original, restated, "evidence-not-found", "--json").data["adjudication"]
    assert fix(gct, original, "1,149").code == 0
    ready(gct)
    assert [e["kind"] for e in needs(gct, original)] == [e["kind"] for e in needs(gct, restated)] == ["adjudication"]
    assert gct("restate", "record", "--original", original, "--restated", restated, "--page", 1, "--quote", QUOTE,
               *WHO).code == 0
    assert needs(gct, original) == needs(gct, restated) == []
    (row,) = snapshot(db)["adjudication"]
    assert row[0] == x["id"]


# Matrix row 9
def test_a_re_extraction_that_makes_a_new_version_asks_as_a_correction_does(ws, db, doc, gct):
    gct("contributor", "add", "ana", "--name", "Ana")
    cid = claims(gct, doc)[ENERGY]["id"]
    v1 = newest(gct, cid)
    company = rec(gct, "company", cid, v1, "accepted", "--json").data["entry"]
    assert flag(gct, "raise", cid, v1).code == 0
    add_reading(ws, db, doc, set_word("4,560", "4,570"))
    assert gct("extract").code == 0
    assert newest(gct, cid) != v1 and claims(gct, doc)[ENERGY]["claim_state"] == "current"
    (fl,) = snapshot(db)["reviewer_flag"]
    assert needs(gct, cid) == [entry("company confirmation", company["id"], v1), entry("reviewer flag", fl[0], v1)]
    assert claims(gct, doc)[ENERGY]["needs_re_review"] == needs(gct, cid)


# Matrix row 10
def test_a_re_mapped_spreadsheet_claim_asks_as_a_correction_does(ws, db, gct, make_file, acme):
    sheet = gct("doc", "add", make_file("s.csv", csv_bytes(ROWS)), "--company", "Acme", "--kind", "evidence",
                "--json").data["items"][0]["document"]["id"]
    assert gct("sheet", "map", sheet, "--sheet", "s", *MAP, *WHO).code == 0 and gct("extract", sheet).code == 0
    cid = claims(gct, sheet)["s1r2"]["id"]
    v1 = newest(gct, cid)
    auditor = rec(gct, "auditor", cid, v1, "accepted", "--json").data["entry"]
    assert gct("sheet", "map", sheet, "--sheet", "s", *MAP[:-2], *WHO).code == 0  # the note left out: a new version
    assert gct("extract", sheet).code == 0
    assert newest(gct, cid) != v1
    assert needs(gct, cid) == [entry("auditor review", auditor["id"], v1)]
    assert pending(gct, "--doc", sheet) == {"auditor review": [(cid, entry("auditor review", auditor["id"], v1))]}


# Matrix row 11
def test_an_archived_documents_claims_leave_the_list_and_come_back_unchanged(ws, db, gct, one):
    doc, claim, v1 = one
    company = rec(gct, "company", claim, v1, "accepted", "--json").data["entry"]
    assert fix(gct, claim, "1,235").code == 0
    listed = pending(gct)
    assert listed == {"company confirmation": [(claim, entry("company confirmation", company["id"], v1))]}
    held = snapshot(db)
    who = ("--as", "ana", "--capacity", "c", "--rationale", "r")
    assert gct("doc", "archive", doc, *who).code == 0
    assert pending(gct) == {} and pending(gct, "--company", "Acme") == {}
    r = gct("review", "pending", "--doc", doc)
    assert r.code == 4 and f"gct doc restore {doc}" in r.err
    assert gct("doc", "restore", doc, *who).code == 0
    assert pending(gct) == listed and snapshot(db) == held


# Matrix row 12
def test_a_deleted_documents_claims_leave_the_list_and_keep_the_marker(ws, db, gct, one):
    doc, claim, v1 = one
    company = rec(gct, "company", claim, v1, "accepted", "--json").data["entry"]
    assert fix(gct, claim, "1,235").code == 0
    assert pending(gct) != {}
    assert gct("doc", "delete", doc, "--confirm", token(db, doc), *WHO).code == 0
    assert pending(gct) == {} and gct("review", "pending").out.startswith("No claim needs renewed review.")
    at = db.execute("SELECT at FROM document_state WHERE document_id = ? AND state = 'deleted'", (doc,)).fetchone()[0]
    (v,) = [x for x in gct("claims", "history", claim, "--json").data["versions"] if x["id"] == v1]
    (e,) = v["company_confirmations"]
    assert e["id"] == company["id"] and e["evidence_deleted"] == {"document": doc, "at": at}
    assert e["conclusion"] == f"cleared with document {doc}"
    assert f"evidence deleted (document {doc}, {at[:10]})" in gct("claims", "history", claim).out


# Matrix row 13 (runs unchanged on b6e7fc2: a workspace with no E5 rows keeps the 3.5 entries exactly)
def test_without_e5_records_the_3_5_entries_are_unchanged(ws, db, doc, gct):
    gct("contributor", "add", "ana", "--name", "Ana")
    cid = claims(gct, doc)[ENERGY]["id"]
    gct("infer")
    assert gct("infer", "resolve", cid, "--field", "period", "--kind", "calendar_year", "--start", "2023-01-01",
               "--end", "2023-12-31", *WHO).code == 0
    assert gct("correct", cid, "--value", "4,570", *WHO).code == 0
    add_reading(ws, db, doc, set_word("4,560", "4,590"))
    assert gct("extract").code == 0
    review = db.execute("SELECT id, claim_version_id FROM inference_review").fetchone()
    fixed = db.execute("SELECT id, claim_version_id FROM correction").fetchone()
    got = claims(gct, doc)[ENERGY]["needs_re_review"]
    assert got == [{"kind": "correction", "id": fixed[0], "version": fixed[1]},
                   {"kind": "period review", "id": review[0], "version": review[1]}]
    assert gct("claims", "history", cid, "--json").data["claim"]["needs_re_review"] == got
    assert f"needs re-review: correction #{fixed[0]} on version {fixed[1]}" in gct("claims", "history", cid).out


# AC 2 and AC 3
def test_every_surface_shows_the_same_entries_and_no_row_changes(ws, db, gct, four):
    a, b = four["ghg_scope_1"]
    vb = newest(gct, b)
    assert rec(gct, "company", b, vb).code == 0
    assert rec(gct, "auditor", b, vb, "disputed", who="bob").code == 0
    assert flag(gct, "raise", b, vb).code == 0
    assert adj(gct, a, b, "evidence-not-found").code == 0
    assert fix(gct, b, "1,151").code == 0
    ready(gct)
    held, rows = snapshot(db), counts(db)
    want = needs(gct, b)
    assert [e["kind"] for e in want] == ["company confirmation", "auditor review", "reviewer flag", "adjudication"]
    shown = gct("restate", "show", b, "--json").data
    assert shown["claim"]["needs_re_review"] == want
    assert sorted(map(json.dumps, (e for es in pending(gct).values() for c, e in es if c == b))) == sorted(
        map(json.dumps, want))
    listed = {c["id"]: c for c in gct("claims", "list", "--doc", four["b"], "--json").data["claims"]}
    assert listed[b]["needs_re_review"] == want
    for argv in (("claims", "history", b), ("restate", "show", b), ("review", "pending"),
                 ("claims", "list", "--doc", four["b"])):
        out = gct(*argv).out
        assert all(correct.entry_text(e) in out for e in want), argv
        assert out.count(SELF) == (argv[0] != "claims" or argv[1] == "history"), argv
    assert snapshot(db) == held and counts(db) == rows  # read commands create and change nothing
    assert gct("publish", "build").code == 0
    srv = server.serve(ws, port=0)
    try:
        status, _, body = call(srv.port, f"/api/claims/{b}/history", **cookie(srv))
        assert status == 200 and json.loads(body)["claim"]["needs_re_review"] == want
    finally:
        srv.stop()
    assert snapshot(db) == held
    # Every show command lists every record on the earlier version, binds false, nowhere else.
    old = vb
    for versions in (gct("claims", "history", b, "--json").data["versions"],
                     [{**v["reviews"], "id": v["id"]} for v in shown["versions"] if v["claim"] == b]):
        (v,) = [x for x in versions if x["id"] == old]
        assert [len(v[k]) for k in ("company_confirmations", "auditor_reviews", "reviewer_flags", "adjudications")] == [1, 1, 1, 1]
        assert not any(r["binds"] for k in ("company_confirmations", "auditor_reviews", "reviewer_flags", "adjudications")
                       for r in v[k])
        assert all(not x[k] for x in versions if x["id"] != old for k in ("company_confirmations", "reviewer_flags"))
    out = gct("restate", "show", b).out
    assert "company confirmation #" in out and "reviewer flag #" in out and "adjudication #" in out


# AC 5
def test_projection_13_carries_the_new_kinds(ws, db, gct, one):
    doc, claim, v1 = one
    company = rec(gct, "company", claim, v1, "accepted", "--json").data["entry"]
    assert fix(gct, claim, "1,235").code == 0
    v = gct("publish", "build", "--json").data["version"]
    conn = published.open_version(ws / "published" / f"v{v}.db")
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        got = json.loads(conn.execute("SELECT needs_re_review FROM claim WHERE id = ?", (claim,)).fetchone()[0])
    finally:
        conn.close()
    assert meta["projection_schema"] == "16"
    assert got == [entry("company confirmation", company["id"], v1)]


# B3
def test_review_pending_groups_by_kind_with_the_command_that_renews_each(ws, db, gct, make_file, four):
    a, b = four["ghg_scope_1"]
    c = four["energy_total"][0]
    vb, vc = newest(gct, b), newest(gct, c)
    assert rec(gct, "company", b, vb).code == 0 and rec(gct, "auditor", c, vc).code == 0
    assert flag(gct, "raise", c, vc).code == 0
    assert adj(gct, a, b, "evidence-not-found").code == 0
    assert fix(gct, b, "1,151").code == 0 and fix(gct, c, "5,001").code == 0
    ready(gct)
    data = gct("review", "pending", "--json").data
    kinds = [k["kind"] for k in data["kinds"]]
    assert kinds == ["company confirmation", "auditor review", "reviewer flag", "adjudication"]
    renew = {(k["kind"], e["claim"]): e["renew"] for k in data["kinds"] for e in k["entries"]}
    vb2, vc2 = newest(gct, b), newest(gct, c)
    assert renew[("company confirmation", b)].startswith(f"gct review company {b} --version {vb2} --outcome")
    assert renew[("auditor review", c)].startswith(f"gct review auditor {c} --version {vc2} --outcome")
    assert renew[("reviewer flag", c)] == f"gct flag raise {c} --version {vc2} --as KEY --capacity TEXT --rationale TEXT"
    assert renew[("adjudication", b)].startswith(f"gct adjudicate record {b} {a} --state STATE")
    assert renew[("adjudication", a)].startswith(f"gct adjudicate record {a} {b} --state STATE")
    assert all(set(e) == {"claim", "document", "company", "version", "entry", "renew"} for k in data["kinds"]
               for e in k["entries"])
    assert {e["company"] for k in data["kinds"] for e in k["entries"]} == {"Acme"}
    out = gct("review", "pending").out
    assert out.splitlines()[0] == "company confirmation:" and out.count(SELF) == 1
    assert f"  renew: gct flag raise {c} --version {vc2}" in out
    # Filters: one document, one company; unknown ones are refused.
    assert set(pending(gct, "--doc", four["a"])) == {"auditor review", "reviewer flag", "adjudication"}
    assert pending(gct, "--company", "Acme") == pending(gct)
    assert gct("review", "pending", "--company", "Nobody").code == 3
    assert gct("review", "pending", "--doc", 99).code == 3
