"""Story 5.3: adjudication of inconsistency candidates and reviewer flags. Synthetic workspaces only; no real report."""
import json
import sqlite3

import pytest

from conftest import make_pdf
from test_deletion import delete, scan
from test_match import BOTH, SCOPE_1, WHO, ids, ready
from test_restate import QUOTE, acme, add, cp2, page_of  # noqa: F401 (acme is a fixture)
from test_review import rec
from gct.workspace import layout, published, runs, store

ADJ = ("low_version_id, high_version_id, state, rationale, procedure, counter_document_id, counter_page, counter_note,"
       " contributor_version_id, capacity, created_at")
FLAG = "claim_version_id, decision, rationale, contributor_version_id, capacity, created_at"
BOB = ("--as", "bob", "--capacity", "auditor", "--rationale")
SELF = ("Identities and capacities are self-declared. GCT does not check them and does not adopt any conclusion as its"
        " own.")  # C5
# Four metrics printed by A for two years and by B for the earlier year with other values: four candidates.
ROWS = [SCOPE_1, ["Total Scope 2 emissions", "tCO2e", "700", "650"], ["Total energy consumed (in GJ)", "", "5,000", "3,600"],
        ["Total volume of water consumption (in kilolitres)", "", "120", "100"]]
OTHER = [["Total Scope 1 emissions", "tCO2e", "1,150"], ["Total Scope 2 emissions", "tCO2e", "640"],
         ["Total energy consumed (in GJ)", "", "3,700"], ["Total volume of water consumption (in kilolitres)", "", "95"]]


@pytest.fixture
def four(ws, gct, make_file, acme):
    """{metric key: (claim of A, claim of B)} for the four FY 2023-24 candidates, and the documents."""
    gct("contributor", "add", "bob", "--name", "Bob")
    a = add(gct, make_file, "a.pdf", ROWS)
    b = add(gct, make_file, "b.pdf", OTHER, periods=BOTH[1:])
    ready(gct)
    ia, ib = ids(gct, a), ids(gct, b)
    keys = ("ghg_scope_1", "ghg_scope_2", "energy_total", "water_consumption_total")
    return {"a": a, "b": b, **{k: (ia[(r[0], "FY 2023-24")], ib[(o[0], "FY 2023-24")])
                               for k, r, o in zip(keys, ROWS, OTHER)}}


def adj(gct, x, y, state, *extra, who=WHO, procedure="compared both printed tables"):
    return gct("adjudicate", "record", x, y, "--state", state, "--procedure", procedure, *who, *extra)


def listing(gct, *args) -> dict:
    return gct("adjudicate", "list", *args, "--json").data


def candidate(gct, x, y, *args) -> dict:
    return next(c for c in listing(gct, *args)["candidates"] if {c["a"]["claim_id"], c["b"]["claim_id"]} == {x, y})


def snapshot(db) -> dict:
    return {t: db.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in ("adjudication", "reviewer_flag")}


def rows(db, table) -> int:
    return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# AC 1
def test_migrations_17_and_18_apply_in_order(tmp_path, gct):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    assert store.migrate(c, up_to=16) == list(range(1, 17))
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.close()
    assert gct("doc", "list", "--workspace", root).code == 0
    c = store.connect(root / layout.DB_NAME)
    assert [r[0] for r in c.execute("SELECT version FROM schema_version ORDER BY version")][-6:] == [16, 17, 18, 19, 20, 21]
    (run,) = runs.list_runs(c)
    assert [e["message"] for e in runs.show_run(c, run["id"])["events"] if e["kind"] == "note"] == ["applied migration 17", "applied migration 18", "applied migration 19", "applied migration 20", "applied migration 21"]
    assert [c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("adjudication", "reviewer_flag")] == [0, 0]
    c.close()


def test_both_tables_are_append_only_and_check_their_values(db):
    db.execute(f"INSERT INTO adjudication ({ADJ}) VALUES (1, 2, 'explained_difference', 'r', 'p', 1, 3, NULL, 1, 'c', 't')")
    db.execute(f"INSERT INTO adjudication ({ADJ}) VALUES (1, 2, 'explained_difference', 'r', 'p', NULL, NULL, 'n', 1, 'c', 't')")
    db.execute(f"INSERT INTO adjudication ({ADJ}) VALUES (1, 2, 'evidence_not_found', 'r', 'p', NULL, NULL, NULL, 1, 'c', 't')")
    db.execute(f"INSERT INTO reviewer_flag ({FLAG}) VALUES (1, 'raised', 'r', 1, 'c', 't')")
    db.execute(f"INSERT INTO reviewer_flag ({FLAG}) VALUES (1, 'withdrawn', 'r', 1, 'c', 't')")
    for table in ("adjudication", "reviewer_flag"):
        for stmt in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
                db.execute(stmt)
    for values in ("2, 1, 'extraction_error', 'r', 'p', NULL, NULL, NULL, 1, 'c', 't'",  # low < high
                   "1, 1, 'extraction_error', 'r', 'p', NULL, NULL, NULL, 1, 'c', 't'",
                   "1, 2, 'restatement', 'r', 'p', NULL, NULL, NULL, 1, 'c', 't'",  # no restatement state (J3)
                   "1, 2, 'explained_difference', 'r', 'p', NULL, NULL, NULL, 1, 'c', 't'",  # counter-evidence
                   "1, 2, 'extraction_error', 'r', 'p', NULL, 3, NULL, 1, 'c', 't'",  # a page needs its document
                   "1, 2, 'extraction_error', NULL, 'p', NULL, NULL, NULL, 1, 'c', 't'",
                   "1, 2, 'extraction_error', 'r', NULL, NULL, NULL, NULL, 1, 'c', 't'"):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f"INSERT INTO adjudication ({ADJ}) VALUES ({values})")
    for values in ("1, 'maybe', 'r', 1, 'c', 't'", "1, 'raised', NULL, 1, 'c', 't'"):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f"INSERT INTO reviewer_flag ({FLAG}) VALUES ({values})")


# AC 2
def test_candidates_are_exactly_the_unresolved_pairs(ws, db, gct, make_file, four):
    a, b = four["a"], four["b"]
    c = add(gct, make_file, "c.pdf", [["Total Scope 1 emissions", "tCO2e", "999"]], periods=BOTH[1:], boundary="consolidated")
    d = add(gct, make_file, "d.pdf", [["Total Scope 2 emissions", "tCO2e", "641"]], periods=BOTH[1:], boundary=None)
    same = add(gct, make_file, "s.pdf", [["Total Scope 2 emissions", "tCO2e", "650"]], periods=BOTH[1:])
    ready(gct, scoped={a, b, c, same})  # d's boundary statement has no declared pages: an uncertain item
    unresolved = {frozenset((p["a"]["claim_id"], p["b"]["claim_id"])) for p in
                  gct("restate", "list", "--state", "unresolved", "--json").data["pairs"]}
    got = listing(gct)
    assert {frozenset((p["a"]["claim_id"], p["b"]["claim_id"])) for p in got["candidates"]} == unresolved
    assert len(unresolved) == 5 and got["earlier"] == []  # four A-B pairs and B's Scope 2 against s
    assert {p["adjudication_state"] for p in got["candidates"]} == {"unreviewed candidate"}
    assert all(p["adjudications"] == [] for p in got["candidates"])
    assert gct("adjudicate", "list").out.splitlines()[-1] == SELF
    (consolidated,) = ids(gct, c).values()
    (uncertain,) = ids(gct, d).values()
    (twin,) = ids(gct, same).values()
    scope_1, scope_2 = four["ghg_scope_1"], four["ghg_scope_2"]
    assert gct("match", "review", "--json").data["items"][0]["claim"] == uncertain
    before = snapshot(db)
    r = adj(gct, scope_2[0], twin, "evidence-not-found")  # same value
    assert r.code == 4 and "same value" in r.err and "gct restate list" in r.err and "contradiction" not in r.err
    for other in (consolidated, uncertain):
        r = adj(gct, scope_1[0] if other == consolidated else scope_2[0], other, "evidence-not-found")
        assert r.code == 4 and "gct restate list" in r.err, r.err
    assert {consolidated, uncertain, twin} & {x["claim_id"] for p in got["candidates"] for x in (p["a"], p["b"])} == {twin}
    assert snapshot(db) == before
    # Flags are per claim: a claim waiting in the review queue can still be flagged.
    v = db.execute("SELECT MAX(id) FROM claim_version WHERE claim_id = ?", (uncertain,)).fetchone()[0]
    assert gct("flag", "raise", uncertain, "--version", v, *WHO).code == 0


# AC 3
def test_each_state_with_its_fields_verbatim_and_attributed(ws, db, gct, four):
    s1, s2, en, wa = (four[k] for k in ("ghg_scope_1", "ghg_scope_2", "energy_total", "water_consumption_total"))
    why = 'B rounds "to the nearest 50" – see note 4'
    r = adj(gct, *s1, "explained-difference", "--counter-doc", four["b"], "--counter-page", "1",
            "--counter-note", "note 4, rounding", "--follow-up", "none", "--closure-reason", "explained by the report",
            "--json", who=("--as", "ana", "--capacity", "lead reviewer", "--rationale", why))
    assert r.code == 0, r.err
    x = r.data["adjudication"]
    assert (x["state"], x["rationale"], x["procedure"], x["counter_document"], x["counter_page"], x["counter_note"],
            x["follow_up"], x["closure_reason"], x["contributor"], x["organisation"], x["capacity"], x["binds"],
            x["self_declared"], x["evidence_state"], x["counter_company"]) == (
        "explained_difference", why, "compared both printed tables", four["b"], 1, "note 4, rounding", "none",
        "explained by the report", "Ana", "Acme audit", "lead reviewer", True, True, "registered", "Acme")
    assert r.data["adjudication_state"] == "explained difference" and r.data["next"] is None
    out = gct("adjudicate", "list").out
    assert f'explained difference on versions {x["low_version"]} and {x["high_version"]} by Ana (Acme audit), capacity ' \
           f'"lead reviewer": "{why}"; procedure "compared both printed tables"; counter-evidence document ' \
           f'{four["b"]} p1 (Acme, registered); counter-evidence note "note 4, rounding"' in out
    assert x["low_version"] < x["high_version"]
    r = adj(gct, *s2, "extraction-error", "--json")
    assert r.code == 0 and r.data["adjudication_state"] == "extraction error"
    assert f"gct correct {min(s2)} --value TEXT --as KEY --capacity TEXT --rationale TEXT" in r.data["next"]
    assert "does not change the claim" in adj(gct, *s2, "extraction-error").out
    assert adj(gct, *en, "reviewer-confirmed-issue").code == 0
    assert adj(gct, *wa, "evidence-not-found", "--counter-note", "asked for the source table").code == 0
    states = {frozenset((c["a"]["claim_id"], c["b"]["claim_id"])): c["adjudication_state"] for c in listing(gct)["candidates"]}
    assert states == {frozenset(s1): "explained difference", frozenset(s2): "extraction error",
                      frozenset(en): "reviewer-confirmed issue", frozenset(wa): "evidence not found"}
    # An explained difference needs counter-evidence; nothing is written.
    before = snapshot(db)
    r = adj(gct, *wa, "explained-difference")
    assert r.code == 2 and "counter-evidence" in r.err and "--counter-note" in r.err
    assert snapshot(db) == before
    # Every claim the candidate's sides name is untouched: an extraction error corrects nothing.
    assert db.execute("SELECT COUNT(*) FROM claim_version").fetchone()[0] == db.execute(
        "SELECT COUNT(*) FROM claim").fetchone()[0]


# AC 4
def test_a_restatement_goes_through_restate_record(ws, db, gct, make_file, acme):
    a, b, restated, original = cp2(gct, make_file)
    assert "gct restate record" in gct("adjudicate", "record", "--help").out
    before = snapshot(db)
    for word in ("restatement", "restated"):
        r = adj(gct, original, restated, word)
        assert r.code == 4 and "gct restate record --original A --restated B --page N --quote TEXT" in r.err
    assert adj(gct, original, restated, "maybe").code == 2
    assert snapshot(db) == before
    x = adj(gct, original, restated, "evidence-not-found", "--json").data["adjudication"]
    assert gct("restate", "record", "--original", original, "--restated", restated, "--page", 1, "--quote", QUOTE,
               *WHO).code == 0
    got = listing(gct)
    assert got["candidates"] == [] and [(e["id"], e["pair_state"]) for e in got["earlier"]] == [(x["id"], "restatement")]
    assert [e["id"] for e in listing(gct, "--claim", restated)["earlier"]] == [x["id"]]
    assert f"claims {min(original, restated)} and {max(original, restated)}, now restatement: adjudication #{x['id']}" \
           in gct("adjudicate", "list").out
    (row,) = snapshot(db)["adjudication"]  # the restatement record left the adjudication as it was
    assert (row["id"], row["state"], row["rationale"]) == (x["id"], "evidence_not_found", x["rationale"])


# AC 5, AC 6
def test_rows_are_kept_and_a_correction_makes_a_new_candidate(ws, db, gct, four):
    s1 = four["ghg_scope_1"]
    first = adj(gct, *s1, "reviewer-confirmed-issue", "--json").data["adjudication"]
    second = adj(gct, *s1, "evidence-not-found", "--json", who=(*BOB, "no source table")).data["adjudication"]
    held = snapshot(db)
    third = adj(gct, *s1, "explained-difference", "--counter-note", "p3 scope note", "--json").data["adjudication"]
    c = candidate(gct, *s1)
    assert [r["id"] for r in c["adjudications"]] == [first["id"], second["id"], third["id"]]
    assert c["adjudication_state"] == "explained difference" and all(r["binds"] for r in c["adjudications"])
    assert snapshot(db)["adjudication"][:2] == held["adjudication"]  # nothing changes an earlier row
    # A correction of one side makes a new pair: unreviewed, the earlier rows listed under it with binds false.
    assert gct("correct", s1[1], "--value", "1,151", *WHO).code == 0
    ready(gct)
    c = candidate(gct, *s1)
    assert c["adjudication_state"] == "unreviewed candidate"
    assert [(r["id"], r["binds"]) for r in c["adjudications"]] == [(first["id"], False), (second["id"], False),
                                                                     (third["id"], False)]
    assert "(on an earlier version)" in gct("adjudicate", "list", "--claim", s1[0]).out
    assert snapshot(db)["adjudication"][:2] == held["adjudication"] and rows(db, "adjudication") == 3


# AC 7
def test_flags_raise_withdraw_raise_and_the_pipeline_creates_none(ws, db, gct, make_file, four):
    for argv in (["restate", "list"], ["adjudicate", "list"], ["adjudicate", "status"], ["publish", "build"]):
        assert gct(*argv).code == 0
    assert (rows(db, "reviewer_flag"), rows(db, "adjudication")) == (0, 0)
    claim = four["ghg_scope_1"][1]
    v = db.execute("SELECT MAX(id) FROM claim_version WHERE claim_id = ?", (claim,)).fetchone()[0]
    log = [rows(db, t) for t in ("run", "run_event")]
    assert adj(gct, *four["ghg_scope_2"], "evidence-not-found").code == 0  # no run and no run-log line either
    for verb, why in (("raise", "target framed as achieved"), ("withdraw", "the report qualifies it on p9"),
                      ("raise", "the qualification was dropped")):
        r = gct("flag", verb, claim, "--version", v, *WHO[:4], "--rationale", why)
        assert r.code == 0, r.err
        assert "potential greenwashing concern" in r.out and "by Ana (Acme audit) (self-declared)" in r.out
        assert r.out.splitlines()[-1] == SELF
    assert [rows(db, t) for t in ("run", "run_event")] == log
    fs = gct("flag", "list", "--claim", claim, "--json").data["flags"]
    assert [(f["decision"], f["latest"], f["binds"], f["self_declared"]) for f in fs] == [
        ("raised", False, True, True), ("withdrawn", False, True, True), ("raised", True, True, True)]
    out = gct("flag", "list").out
    assert out.count("potential greenwashing concern raised by Ana (Acme audit) (self-declared)") == 2 and SELF in out
    assert gct("flag", "list", "--company", "Acme", "--json").data["flags"] == fs
    # Bob has nothing to withdraw; a version that is not the newest is refused; nothing is written.
    before = snapshot(db)
    r = gct("flag", "withdraw", claim, "--version", v, *BOB, "x")
    assert r.code == 4 and f"gct flag list --claim {claim}" in r.err
    r = gct("flag", "raise", claim, "--version", v - 1, *WHO)
    assert r.code == 4 and f"gct claims history {claim}" in r.err
    assert snapshot(db) == before
    # A correction leaves the flags on the old version, binds false; the new version has none.
    assert gct("correct", claim, "--value", "1,152", *WHO).code == 0
    fs = gct("flag", "list", "--claim", claim, "--json").data["flags"]
    assert [f["binds"] for f in fs] == [False] * 3 and "(on an earlier version)" in gct("flag", "list").out
    assert rows(db, "adjudication") == 1  # the one recorded above; flags made none


# AC 8
def test_counts_never_inflate_and_gct_never_says_contradiction(ws, db, gct, four):
    s1, s2, en = four["ghg_scope_1"], four["ghg_scope_2"], four["energy_total"]
    assert adj(gct, *s1, "explained-difference", "--counter-note", "p4 scope note").code == 0
    assert adj(gct, *s2, "reviewer-confirmed-issue").code == 0
    assert adj(gct, *en, "reviewer-confirmed-issue").code == 0
    assert gct("correct", en[1], "--value", "3,701", *WHO).code == 0
    ready(gct)
    (st,) = gct("adjudicate", "status", "--json").data["companies"]
    assert st == {"company": "Acme", "candidates": 4, "unreviewed": 2, "explained_difference": 1, "extraction_error": 0,
                  "reviewer_confirmed_issue": 1, "evidence_not_found": 0}
    assert gct("adjudicate", "status").out.strip() == (
        "Acme: 4 candidates, of which 2 unreviewed, 1 explained difference, 0 extraction error, "
        "1 reviewer-confirmed issue, 0 evidence not found")
    assert gct("adjudicate", "status", "--company", "Acme", "--json").data["companies"] == [st]
    v = db.execute("SELECT MAX(id) FROM claim_version WHERE claim_id = ?", (s2[0],)).fetchone()[0]
    assert gct("flag", "raise", s2[0], "--version", v, *WHO).code == 0
    texts = [r[0] for r in db.execute("SELECT rationale FROM adjudication UNION SELECT procedure FROM adjudication"
                                      " UNION SELECT counter_note FROM adjudication UNION SELECT capacity FROM adjudication"
                                      " UNION SELECT rationale FROM reviewer_flag") if r[0]]
    out = "\n".join(gct(*argv).out + gct(*argv).err for argv in (
        ["adjudicate", "list"], ["adjudicate", "status"], ["flag", "list"], ["adjudicate", "record", "--help"],
        ["flag", "raise", "--help"], ["adjudicate", "list", "--state", "unreviewed"], ["--help"]))
    for t in texts:
        out = out.replace(t, "")
    for word in ("contradiction", "verified", "assured", "certified", "compliant"):
        assert word not in out.casefold(), word


# AC 9
def test_refusals_write_nothing_and_name_a_next_step(ws, db, gct, make_file, four):
    s1 = four["ghg_scope_1"]
    sheet = gct("doc", "add", make_file("s.csv", b"metric,value\nscope 1,1\n"), "--company", "Acme", "--json"
                ).data["items"][0]["document"]["id"]
    before = snapshot(db)
    cases = [
        (adj(gct, 99, s1[1], "evidence-not-found"), 3, "gct claims list"),
        (adj(gct, *s1, "evidence-not-found", who=("--as", "zed", "--capacity", "c", "--rationale", "r")), 3,
         "gct contributor add zed"),
        (adj(gct, *s1, "evidence-not-found", "--counter-doc", 99), 3, "gct doc list"),
        (adj(gct, s1[0], s1[0], "evidence-not-found"), 4, "gct adjudicate list"),
        (adj(gct, s1[0], four["ghg_scope_2"][1], "evidence-not-found"), 4, "gct restate list"),
        (adj(gct, *s1, "evidence-not-found", who=("--as", "ana", "--capacity", " ", "--rationale", "r")), 2, "--capacity"),
        (adj(gct, *s1, "evidence-not-found", who=("--as", "ana", "--capacity", "c", "--rationale", " ")), 2, "--rationale"),
        (adj(gct, *s1, "evidence-not-found", procedure=" "), 2, "--procedure"),
        (adj(gct, *s1, "evidence-not-found", "--follow-up", ""), 2, "--follow-up"),
        (adj(gct, *s1, "evidence-not-found", "--closure-reason", " "), 2, "--closure-reason"),
        (adj(gct, *s1, "explained-difference", "--counter-note", " "), 2, "--counter-note"),
        (adj(gct, *s1, "evidence-not-found", "--counter-page", 1), 2, "--counter-doc ID --counter-page N"),
        (adj(gct, *s1, "explained-difference", "--counter-doc", four["b"], "--counter-page", 2), 4, "from 1 to 1"),
        (adj(gct, *s1, "explained-difference", "--counter-doc", sheet, "--counter-page", 1), 4, "--counter-note"),
        (gct("flag", "raise", 99, "--version", 1, *WHO), 3, "gct claims list"),
        (gct("flag", "raise", s1[0], "--version", 1, *WHO[:4], "--rationale", ""), 2, "--rationale"),
    ]
    for r, code, step in cases:
        assert r.code == code and step in r.err, (r.err, code, step)
        assert "contradiction" not in r.err
    assert snapshot(db) == before
    # Archived on either side or as counter-evidence: refused with the restore step.
    assert gct("doc", "archive", four["b"], *WHO).code == 0
    for r in (adj(gct, *s1, "evidence-not-found"), adj(gct, *s1, "explained-difference", "--counter-doc", four["b"]),
              gct("flag", "raise", s1[1], "--version", 1, *WHO), gct("flag", "list", "--claim", s1[1])):
        assert r.code == 4 and f"gct doc restore {four['b']}" in r.err, r.err
    assert snapshot(db) == before


def newest(db, claim) -> int:
    return db.execute("SELECT MAX(id) FROM claim_version WHERE claim_id = ?", (claim,)).fetchone()[0]


def version_file(gct, ws) -> dict:
    """A fresh build's adjudication and reviewer_flag rows and its meta."""
    v = gct("publish", "build", "--json").data["version"]
    conn = published.open_version(ws / "published" / f"v{v}.db")
    try:
        return {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1")]
                for t in ("adjudication", "reviewer_flag", "meta")}
    finally:
        conn.close()


# AC 10
def test_archive_counts_both_kinds_and_restore_brings_them_back(ws, db, gct, make_file, four):
    a, b, s1, s2 = four["a"], four["b"], four["ghg_scope_1"], four["ghg_scope_2"]
    c = add(gct, make_file, "c.pdf", [["Total Scope 3 emissions", "tCO2e", "5", "4"]])
    assert adj(gct, *s1, "reviewer-confirmed-issue").code == 0
    assert adj(gct, *s2, "explained-difference", "--counter-doc", c, "--counter-page", 1).code == 0
    for claim in s1:
        assert gct("flag", "raise", claim, "--version", newest(db, claim), *WHO).code == 0
    # An archived counter-evidence document: the row stays listed and projected with the document's state.
    assert gct("doc", "archive", c, *WHO).code == 0
    (row,) = candidate(gct, *s2)["adjudications"]
    assert row["evidence_state"] == "archived" and candidate(gct, *s2)["adjudication_state"] == "explained difference"
    assert "(Acme, archived)" in gct("adjudicate", "list").out
    assert len(version_file(gct, ws)["adjudication"]) == 2
    assert gct("doc", "restore", c, *WHO).code == 0
    shown = listing(gct)
    assert candidate(gct, *s2)["adjudications"][0]["evidence_state"] == "restored"
    # Archiving a side's document: counted in the impact, out of the list and the projection, back on restore.
    held = snapshot(db)
    plan = gct("doc", "archive", b, "--plan", "--json").data["impact"]["review_records"]
    assert (plan["adjudication"], plan["reviewer_flag"]) == (2, 1)
    assert "2 adjudications, 1 reviewer flags" in gct("doc", "archive", b, "--plan").out
    assert gct("doc", "archive", b, *WHO).code == 0
    assert listing(gct) == {"status": "ok", "candidates": [], "hidden": 0, "earlier": []}
    assert gct("adjudicate", "status", "--json").data["companies"] == []
    assert [f["claim"] for f in gct("flag", "list", "--json").data["flags"]] == [s1[0]]
    p = version_file(gct, ws)
    hid = {m["key"]: m["value"] for m in p["meta"]}["hidden_by_archive"]
    assert p["adjudication"] == [] and [f["claim_id"] for f in p["reviewer_flag"]] == [s1[0]]
    assert json.loads(hid)["review_records"] >= 3
    assert rows(db, "adjudication") == 2 and rows(db, "reviewer_flag") == 2
    assert gct("doc", "restore", b, *WHO).code == 0
    assert listing(gct) == shown and len(version_file(gct, ws)["adjudication"]) == 2
    assert snapshot(db) == held  # archive and restore change no row
    assert {x["document_id"] for c_ in shown["candidates"] for x in (c_["a"], c_["b"])} == {a, b}


# AC 12
def test_projection_12(ws, db, gct, four):
    s1 = four["ghg_scope_1"]
    first = version_file(gct, ws)
    assert {m["key"]: m["value"] for m in first["meta"]}["projection_schema"] == "15"
    assert first["adjudication"] == first["reviewer_flag"] == []
    x = adj(gct, *s1, "evidence-not-found", "--follow-up", "ask B", "--json").data["adjudication"]
    assert gct("publish", "status", "--json").data["stale"]  # history_mark moved
    f = gct("flag", "raise", s1[1], "--version", newest(db, s1[1]), *WHO, "--json").data["flag"]
    p = version_file(gct, ws)
    (row,) = p["adjudication"]
    assert row == {"id": x["id"], "low_version_id": x["low_version"], "high_version_id": x["high_version"],
                   "low_claim_id": x["low_claim"], "high_claim_id": x["high_claim"], "state": "evidence_not_found",
                   "rationale": "checked on the page", "procedure": "compared both printed tables",
                   "counter_document_id": None, "counter_page": None, "counter_note": None, "follow_up": "ask B",
                   "closure_reason": None, "contributor_name": "Ana", "contributor_organisation": "Acme audit",
                   "capacity": "analyst", "binds": 1, "created_at": x["created_at"]}
    (flag,) = p["reviewer_flag"]
    assert flag == {"id": f["id"], "claim_id": s1[1], "claim_version_id": f["version"], "decision": "raised",
                    "rationale": "checked on the page", "contributor_name": "Ana", "contributor_organisation": "Acme audit",
                    "capacity": "analyst", "latest": 1, "binds": 1, "created_at": f["created_at"]}
    assert gct("correct", s1[1], "--value", "1,151", *WHO).code == 0
    p = version_file(gct, ws)
    assert [r["binds"] for r in p["adjudication"]] == [0] and [r["binds"] for r in p["reviewer_flag"]] == [0]


# AC 11: destructive, on this synthetic workspace only
def test_deletion_clears_the_text_and_keeps_the_rows(ws, db, gct, make_file, four):
    b, s1, s2 = four["b"], four["ghg_scope_1"], four["ghg_scope_2"]
    c = add(gct, make_file, "c.pdf", [["Total Scope 3 emissions", "tCO2e", "5", "4"]])
    d = add(gct, make_file, "d.pdf", [["Total volume of water consumption (in kilolitres)", "", "97"]], periods=BOTH[1:])
    ready(gct)
    water_a = four["water_consumption_total"][0]
    (water_d,) = ids(gct, d).values()

    def canaried(x, y, tag, *extra):
        r = gct("adjudicate", "record", x, y, "--state", "explained-difference", "--procedure", f"zqproc{tag}",
                "--follow-up", f"zqfollow{tag}", "--closure-reason", f"zqclose{tag}", "--counter-note", f"zqnote{tag}",
                "--as", "ana", "--capacity", f"zqcap{tag}", "--rationale", f"zqrat{tag}", *extra, "--json")
        assert r.code == 0, r.err
        return r.data["adjudication"]["id"]

    x = canaried(*s1, "x", "--counter-doc", c, "--counter-page", 1)  # cites C, between A and B
    y = canaried(*s2, "y")  # between A and B
    z = adj(gct, water_a, water_d, "evidence-not-found", "--json").data["adjudication"]["id"]  # A and D: survives
    raised = {}
    for claim, why in ((s1[1], "zqflagb"), (s1[0], "plain")):
        raised[claim] = gct("flag", "raise", claim, "--version", newest(db, claim), *WHO[:4], "--rationale", why,
                            "--json").data["flag"]["id"]
    xs = {f"zq{k}x" for k in ("proc", "follow", "close", "note", "cap", "rat")}
    ys = {f"zq{k}y" for k in ("proc", "follow", "close", "note", "cap", "rat")} | {"zqflagb"}
    for _ in range(2):
        assert gct("publish", "build").code == 0
    assert scan(ws, canaries=xs | ys) == xs | ys  # the scan can fail: before deletion it finds every canary

    def row(table, i):
        return tuple(db.execute(f"SELECT * FROM {table} WHERE id = ?", (i,)).fetchone())

    kept = {("adjudication", z): row("adjudication", z), ("reviewer_flag", raised[s1[0]]): row("reviewer_flag", raised[s1[0]])}
    untouched = {**kept, ("adjudication", y): row("adjudication", y), ("reviewer_flag", raised[s1[1]]): row(
        "reviewer_flag", raised[s1[1]])}
    # The counter-evidence document goes: X keeps ids, state, page and dates, its text is cleared, it stays listed.
    old_x = dict(db.execute("SELECT * FROM adjudication WHERE id = ?", (x,)).fetchone())
    assert delete(gct, db, c).code == 0
    marker = f"cleared with document {c}"
    new_x = dict(db.execute("SELECT * FROM adjudication WHERE id = ?", (x,)).fetchone())
    assert {k: v for k, v in new_x.items() if v != old_x[k]} == dict.fromkeys(
        ("rationale", "procedure", "counter_note", "follow_up", "closure_reason", "capacity"), marker)
    assert all(row(t, i) == v for (t, i), v in untouched.items())
    (shown,) = [r for r in candidate(gct, *s1)["adjudications"] if r["id"] == x]
    when = db.execute("SELECT at FROM document_state WHERE document_id = ? AND state = 'deleted'", (c,)).fetchone()[0]
    assert shown["evidence_state"] == "deleted" and shown["evidence_deleted"] == {"document": c, "at": when}
    assert candidate(gct, *s1)["adjudication_state"] == "explained difference"
    assert f"evidence deleted (document {c}, {when[:10]})" in gct("adjudicate", "list").out
    assert scan(ws, canaries=xs) == set()
    held = snapshot(db)
    r = adj(gct, *s1, "explained-difference", "--counter-doc", c)  # a deleted document is no counter-evidence
    assert r.code == 4 and f"Document {c} was deleted." in r.err and snapshot(db) == held
    # A later build projects X again, its text cleared.
    (again,) = [r for r in version_file(gct, ws)["adjudication"] if r["id"] == x]
    assert (again["rationale"], again["counter_document_id"], again["counter_page"]) == (marker, c, 1)
    # A side's document goes: Y and B's flag are cleared and leave every output; Z and A's flag are byte-identical.
    assert delete(gct, db, b).code == 0
    marker = f"cleared with document {b}"
    gone_y = dict(db.execute("SELECT * FROM adjudication WHERE id = ?", (y,)).fetchone())
    assert (gone_y["state"], gone_y["rationale"], gone_y["procedure"], gone_y["counter_note"], gone_y["capacity"]) == (
        "explained_difference", marker, marker, marker, marker)
    gone_flag = dict(db.execute("SELECT * FROM reviewer_flag WHERE id = ?", (raised[s1[1]],)).fetchone())
    assert (gone_flag["decision"], gone_flag["rationale"], gone_flag["capacity"]) == ("raised", marker, marker)
    assert all(row(t, i) == v for (t, i), v in kept.items())
    assert rows(db, "adjudication") == 3 and rows(db, "reviewer_flag") == 2
    held = snapshot(db)
    for r in (adj(gct, *s2, "evidence-not-found"), gct("flag", "raise", s1[1], "--version", newest(db, s1[1]), *WHO)):
        assert r.code == 4 and f"Document {b} was deleted." in r.err
    assert snapshot(db) == held
    assert scan(ws, canaries=xs | ys) == set()
    assert [r["id"] for r in version_file(gct, ws)["adjudication"]] == [z]
    assert {r["id"] for c_ in listing(gct)["candidates"] for r in c_["adjudications"]} == {z}
    assert [f["id"] for f in gct("flag", "list", "--json").data["flags"]] == [raised[s1[0]]]


# AC 3, AC 9, J4 (review finding F1): contributor text is kept exactly as typed; only an empty value is refused.
def typed(tag) -> str:
    return f"  {tag}  with   gaps\nsecond line \t "


def counts(db) -> dict:
    tables = [t for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {t: rows(db, t) for t in tables}


def test_adjudication_text_is_kept_exactly_as_typed(ws, db, gct, four):
    s1 = four["ghg_scope_1"]
    words = {k: typed(k) for k in ("rationale", "procedure", "capacity", "counter_note", "follow_up", "closure_reason")}
    r = gct("adjudicate", "record", *s1, "--state", "explained-difference", "--procedure", words["procedure"],
            "--counter-note", words["counter_note"], "--follow-up", words["follow_up"],
            "--closure-reason", words["closure_reason"], "--as", "ana", "--capacity", words["capacity"],
            "--rationale", words["rationale"], "--json")
    assert r.code == 0, r.err
    x = r.data["adjudication"]
    assert {k: x[k] for k in words} == words
    (stored,) = db.execute("SELECT * FROM adjudication").fetchall()
    assert {k: stored[k] for k in words} == words
    assert {k: candidate(gct, *s1)["adjudications"][0][k] for k in words} == words
    shown = gct("adjudicate", "list").out
    assert all(w in shown for w in words.values())
    again = gct("adjudicate", "record", *s1, "--state", "evidence-not-found", "--procedure", words["procedure"],
                "--as", "ana", "--capacity", words["capacity"], "--rationale", words["rationale"])
    assert again.code == 0 and words["rationale"] in again.out and words["capacity"] in again.out


def test_flag_text_is_kept_exactly_as_typed(ws, db, gct, four):
    claim = four["ghg_scope_1"][1]
    v = newest(db, claim)
    texts = [(typed(f"{n}_rationale"), typed(f"{n}_capacity")) for n in ("raise", "withdraw", "again")]

    def flag(verb, why, cap, *extra):
        return gct("flag", verb, claim, "--version", v, "--as", "ana", "--capacity", cap, "--rationale", why, *extra)

    for verb, (why, cap) in zip(("raise", "withdraw"), texts):
        r = flag(verb, why, cap, "--json")
        assert r.code == 0, r.err
        assert (r.data["flag"]["rationale"], r.data["flag"]["capacity"]) == (why, cap)
    why, cap = texts[2]
    r = flag("raise", why, cap)
    assert r.code == 0 and why in r.out and cap in r.out
    assert [tuple(x) for x in db.execute("SELECT rationale, capacity FROM reviewer_flag ORDER BY id")] == texts
    fs = gct("flag", "list", "--claim", claim, "--json").data["flags"]
    assert [(f["rationale"], f["capacity"]) for f in fs] == texts
    shown = gct("flag", "list").out
    assert all(t in shown for pair in texts for t in pair)


@pytest.mark.parametrize("empty", ["", " ", " \n\t "])
def test_an_empty_text_is_refused_and_writes_nothing(ws, db, gct, four, empty):
    s1 = four["ghg_scope_1"]
    claim = s1[1]
    v = newest(db, claim)
    assert gct("flag", "raise", claim, "--version", v, *WHO).code == 0  # something for withdraw to withdraw
    before = counts(db)

    def record(**over):
        a = {"capacity": "analyst", "rationale": "checked on the page", "procedure": "compared both printed tables"}
        a.update(over)
        extra = [x for k, flag in (("counter_note", "--counter-note"), ("follow_up", "--follow-up"),
                                   ("closure_reason", "--closure-reason")) if k in a for x in (flag, a[k])]
        return gct("adjudicate", "record", *s1, "--state", "evidence-not-found", "--procedure", a["procedure"],
                   "--as", "ana", "--capacity", a["capacity"], "--rationale", a["rationale"], *extra)

    cases = [(record(rationale=empty), "--rationale"), (record(procedure=empty), "--procedure"),
             (record(capacity=empty), "--capacity"), (record(counter_note=empty), "--counter-note"),
             (record(follow_up=empty), "--follow-up"), (record(closure_reason=empty), "--closure-reason")]
    for verb in ("raise", "withdraw"):
        cases.append((gct("flag", verb, claim, "--version", v, "--as", "ana", "--capacity", "analyst",
                          "--rationale", empty), "--rationale"))
        cases.append((gct("flag", verb, claim, "--version", v, "--as", "ana", "--capacity", empty,
                          "--rationale", "checked on the page"), "--capacity"))
    for r, flag in cases:
        assert r.code == 2 and flag in r.err and r.err.startswith("error:") and "next:" in r.err, (r.err, flag)
    assert counts(db) == before


# Rebase onto 5.1: one claim holds a company entry, an auditor entry, an adjudication and a flag.
def test_archive_plan_and_projection_cover_all_four_record_kinds(ws, db, gct, four):
    s1 = four["ghg_scope_1"]
    claim = s1[0]
    version = newest(db, claim)
    assert rec(gct, "company", claim, version, "accepted", who="ana").code == 0
    assert rec(gct, "auditor", claim, version, "disputed", who="bob").code == 0
    assert adj(gct, *s1, "evidence-not-found").code == 0
    assert gct("flag", "raise", claim, "--version", version, *WHO).code == 0
    kinds = ("review_company", "review_auditor", "adjudication", "reviewer_flag")
    plan = gct("doc", "archive", four["a"], "--plan", "--json").data["impact"]["review_records"]
    assert {k: plan[k] for k in kinds} == dict.fromkeys(kinds, 1)
    text = gct("doc", "archive", four["a"], "--plan").out
    assert "1 company confirmations, 1 auditor reviews, 1 adjudications, 1 reviewer flags" in text
    v = gct("publish", "build", "--json").data["version"]
    conn = published.open_version(ws / "published" / f"v{v}.db")
    try:
        assert {m[0]: m[1] for m in conn.execute("SELECT key, value FROM meta")}["projection_schema"] == "15"
        assert {k: conn.execute(f"SELECT COUNT(*) FROM {k}").fetchone()[0] for k in kinds} == dict.fromkeys(kinds, 1)
    finally:
        conn.close()


# P1-1: --company filters rows by company; a row of another company or of a pair that is no candidate now must not crash
def test_company_filter_with_a_second_company_that_has_adjudications(ws, db, gct, make_file, four):
    gct("company", "add", "Beta")
    docs = [gct("doc", "add", make_file(n, make_pdf([page_of(r, periods=p)])), "--company", "Beta", "--json")
            .data["items"][0]["document"]["id"] for n, r, p in (("c.pdf", ROWS[:1], BOTH), ("d.pdf", OTHER[:1], BOTH[1:]))]
    ready(gct)
    pair = next(p for p in gct("restate", "list", "--company", "Beta", "--state", "unresolved", "--json").data["pairs"])
    mine = four["ghg_scope_1"]
    adj(gct, *mine, "explained-difference", "--counter-note", "n")
    assert adj(gct, pair["a"]["claim_id"], pair["b"]["claim_id"], "extraction-error").code == 0
    got = listing(gct, "--company", "Acme")
    assert len(got["candidates"]) == 4 and got["earlier"] == []
    assert [r["state"] for c in got["candidates"] for r in c["adjudications"]] == ["explained_difference"]
    assert [s["company"] for s in gct("adjudicate", "status", "--company", "Acme", "--json").data["companies"]] == ["Acme"]
    assert listing(gct, "--company", "Beta")["candidates"][0]["adjudication_state"] == "extraction error"


def test_company_filter_with_an_adjudication_that_is_no_candidate_now(ws, db, gct, four):
    s1 = four["ghg_scope_1"]
    adj(gct, *s1, "explained-difference", "--counter-note", "n")
    assert gct("correct", s1[1], "--value", "1,100", *WHO).code == 0  # now A's value: the pair is no candidate
    ready(gct)
    got = listing(gct, "--company", "Acme")
    assert [r["state"] for r in got["earlier"]] == ["explained_difference"]
    assert [s["company"] for s in gct("adjudicate", "status", "--company", "Acme", "--json").data["companies"]] == ["Acme"]
    assert gct("adjudicate", "status", "--company", "Acme").code == 0


# P2-1: from the active side the row stays in the show commands, marked with the other document's state
def test_history_and_restate_show_mark_an_archived_other_document(ws, db, gct, four):
    a_claim, b_claim = four["ghg_scope_1"]
    row = adj(gct, a_claim, b_claim, "reviewer-confirmed-issue", "--json").data["adjudication"]
    seen = gct("claims", "history", b_claim, "--json").data["versions"][-1]["adjudications"][0]
    assert seen["other_document_state"] == "registered" and "other document" not in gct("claims", "history", b_claim).out
    assert gct("doc", "archive", four["a"], *WHO).code == 0
    mark = "; other document archived"
    versions = gct("claims", "history", b_claim, "--json").data["versions"]
    assert [(r["id"], r["other_document_state"]) for v in versions for r in v["adjudications"]] == [(row["id"], "archived")]
    assert [l for l in gct("claims", "history", b_claim).out.splitlines() if f"adjudication #{row['id']}" in l][0].endswith(mark)
    shown = gct("restate", "show", b_claim, "--json").data["versions"]
    assert [(r["id"], r["other_document_state"]) for v in shown if v["claim"] == b_claim
            for r in v["reviews"]["adjudications"]] == [(row["id"], "archived")]
    assert any(l.endswith(mark) for l in gct("restate", "show", b_claim).out.splitlines() if f"adjudication #{row['id']}" in l)
