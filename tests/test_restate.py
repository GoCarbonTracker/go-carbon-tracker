"""Story 4.2: pair states of same-period sets, the number rule, restatement records, their binding and the projection.
No real report is used."""
import sqlite3

import pytest

from conftest import grid, make_pdf
from test_extract import count
from test_match import BOTH, SCOPE_1, WHO, ids, ready, series
from gct.stages import correct, match, read, restate, version_of
from gct.workspace import layout, published, store

NOTE = "The figures for the previous year have been restated due to reclassification of green attributes."
QUOTE = "The figures for the previous year have been restated"


def page_of(rows, periods=BOTH, boundary="standalone", lines=()) -> dict:
    """One BRSR-shaped page as report() in test_match, with extra text lines (x, y, text) above the table."""
    t = grid(40, 200, [250, 60] + [80] * len(periods), [20] * (len(rows) + 1), [["Parameter", "Unit", *periods], *rows])
    text = [(40, 80, "The financial year ended March 31, 2025."), *lines]
    if boundary:
        text.append((40, 100, f"Reporting boundary: Report is prepared on a {boundary} basis."))
    return {"text": t["text"] + text, "lines": t["lines"]}


def add(gct, make_file, name, rows, *pages, **kw) -> int:
    """A one-page document (more pages when given) of Acme."""
    r = gct("doc", "add", make_file(name, make_pdf([page_of(rows, **kw), *pages])), "--company", "Acme", "--json")
    return r.data["items"][0]["document"]["id"]


@pytest.fixture
def acme(ws, gct):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")


def pairs(gct, *args) -> list:
    return gct("restate", "list", *args, "--json").data["pairs"]


def pair(gct, x, y) -> dict:
    return next(p for p in pairs(gct) if {p["a"]["claim_id"], p["b"]["claim_id"]} == {x, y})


def claims_of(gct, doc) -> list:
    return gct("claims", "list", "--doc", doc, "--json").data["claims"]


def record(gct, original, restated, *extra, page=1, quote=QUOTE):
    return gct("restate", "record", "--original", original, "--restated", restated, "--page", page, "--quote", quote,
               *WHO, *extra)


def cp2(gct, make_file):
    """Document A prints FY2024-25 and a restated FY2023-24 figure with a printed restatement line; document B printed
    the original FY2023-24 figure. Returns (a, b, the restated claim, the original claim)."""
    a = add(gct, make_file, "a.pdf", [SCOPE_1], lines=[(40, 150, NOTE)])
    b = add(gct, make_file, "b.pdf", [["Total Scope 1 emissions", "tCO2e", "1,150"]], periods=BOTH[1:])
    ready(gct)
    return a, b, ids(gct, a)[(SCOPE_1[0], "FY 2023-24")], ids(gct, b)[(SCOPE_1[0], "FY 2023-24")]


# AC 1
def test_migration_13_applies_to_a_version_12_workspace(tmp_path, gct):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    assert store.migrate(c, up_to=12) == list(range(1, 13))
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.close()
    assert gct("restate", "list", "--workspace", root).code == 0
    c = store.connect(root / layout.DB_NAME)
    assert c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 17
    c.close()


def test_restatement_table_is_append_only_and_checks_its_values(db):
    cols = ("original_version_id, restated_version_id, series_key, decision, evidence_document_id, evidence_page,"
            " evidence_quote, contributor_version_id, capacity, rationale, created_at")
    db.execute(f"INSERT INTO restatement ({cols}) VALUES (1, 2, 'k', 'recorded', 1, 3, 'q', 1, 'c', 'r', 't')")
    db.execute(f"INSERT INTO restatement ({cols}) VALUES (1, 2, 'k', 'withdrawn', 1, NULL, NULL, 1, 'c', 'r', 't')")
    for stmt in ("UPDATE restatement SET id = id", "DELETE FROM restatement"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
            db.execute(stmt)
    for values in ("1, 2, 'k', 'maybe', 1, 3, 'q', 1, 'c', 'r', 't'", "2, 2, 'k', 'recorded', 1, 3, 'q', 1, 'c', 'r', 't'",
                   "1, 2, 'k', 'recorded', 1, NULL, 'q', 1, 'c', 'r', 't'",
                   "1, 2, 'k', 'recorded', 1, 3, NULL, 1, 'c', 'r', 't'",
                   "1, 2, 'k', 'withdrawn', NULL, NULL, NULL, 1, 'c', 'r', 't'"):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f"INSERT INTO restatement ({cols}) VALUES ({values})")


# AC 2
@pytest.mark.parametrize("text, number", [
    ("29,79,832", 2979832.0), ("1,72,409", 172409.0), ("48,736*", 48736.0), ("43,325", 43325.0),
    ("9,76,828.5", 976828.5), ("1,234,567", 1234567.0), ("48,736*#", 48736.0), ("-1,72,409", -172409.0),
    ("(1,234)", None), ("12,34", None), ("1,2345", None), ("1.234,56", None), ("NA", None), ("-", None), ("*", None),
    (None, None),
])
def test_number_of(text, number):
    assert match.number_of(text) == number


def test_match_metrics_prints_the_versions(ws, gct):
    m = gct("match", "metrics", "--json").data
    assert (m["rules_version"], m["metrics_version"], m["units_version"]) == (2, 2, 1)
    assert gct("match", "metrics").out.splitlines()[0] == "Metric list v2, unit table v1, match rules v2"
    assert match.CONFIG == version_of("match", 1, 2, 2, 1) != version_of("match", 1, 1, 1, 1)


def test_rules_2_adds_one_assignment_row_per_newest_version(ws, db, gct, make_file, acme, monkeypatch):
    config = match.CONFIG
    monkeypatch.setattr(match, "CONFIG", version_of("match", 1, 1, 1, 1))  # a 4.1 workspace
    a = add(gct, make_file, "a.pdf", [SCOPE_1, ["Total volume of water consumption (in kilolitres)", "", "29,79,832", "9"]])
    add(gct, make_file, "d.pdf", [["Total Scope 1 emissions", "tCO2e", "999"]], periods=BOTH[:1], boundary=None)
    ready(gct)
    item = gct("match", "review", "--json").data["items"][0]
    assert gct("match", "link", item["claim"], "--series", item["series"], *WHO).code == 0
    assert gct("correct", ids(gct, a)[(SCOPE_1[0], "FY 2024-25")], "--value", "1,235", *WHO).code == 0
    gct("match")
    before = {r[0]: r[1:] for r in db.execute(
        "SELECT claim_version_id, metric_key, rule, unit_key, unit_factor, unit_source FROM metric_assignment"
        " WHERE id IN (SELECT MAX(id) FROM metric_assignment GROUP BY claim_version_id)")}
    rows, reviews, versions = count(db, "metric_assignment"), count(db, "match_review"), count(db, "claim_version")
    shown = sorted((s["id"], s["periods"]) for s in series(gct))
    newest = [r[0] for r in db.execute("SELECT MAX(id) FROM claim_version GROUP BY claim_id")]
    monkeypatch.setattr(match, "CONFIG", config)
    assert gct("match").code == 0
    assert count(db, "metric_assignment") == rows + len(newest)
    added = db.execute("SELECT claim_version_id, metric_key, rule, unit_key, unit_factor, unit_source, config_version"
                       " FROM metric_assignment ORDER BY id DESC LIMIT ?", (len(newest),)).fetchall()
    assert sorted(r[0] for r in added) == sorted(newest)
    assert all(tuple(r[1:6]) == before[r[0]] and r[6] == match.CONFIG for r in added)
    assert gct("match").code == 0 and count(db, "metric_assignment") == rows + len(newest)
    assert (count(db, "match_review"), count(db, "claim_version")) == (reviews, versions)
    assert sorted((s["id"], s["periods"]) for s in series(gct)) == shown


def test_indian_grouping_gets_a_base_value_and_nothing_is_rewritten(ws, db, gct, make_file, acme):
    a = add(gct, make_file, "a.pdf", [["Total volume of water consumption (in kilolitres)", "", "29,79,832", "9,76,828.5"]])
    ready(gct)
    claim = ids(gct, a)[("Total volume of water consumption (in kilolitres)", "FY 2024-25")]
    versions = count(db, "claim_version")
    assert db.execute("SELECT value_text, value FROM claim_version WHERE claim_id = ?", (claim,)).fetchone()[:] == (
        "29,79,832", None)
    (s,) = series(gct, "water_consumption_total")
    points = gct("series", "show", s["id"], "--all", "--json").data["series"]["points"]
    assert [(p["value_text"], p["number"], p["value_base"]) for p in points] == [
        ("9,76,828.5", 976828.5, 976828.5), ("29,79,832", 2979832.0, 2979832.0)]
    assert "29,79,832  in kilolitres  2.97983e+06 kl" in gct("series", "show", s["id"]).out
    v = gct("publish", "build", "--json").data["version"]
    conn = published.open_version(ws / "published" / f"v{v}.db")
    try:
        assert conn.execute("SELECT value_text, number, value_base FROM series_point WHERE claim_id = ?",
                            (claim,)).fetchone()[:] == ("29,79,832", 2979832.0, 2979832.0)
        assert conn.execute("SELECT value_text, value FROM claim WHERE id = ?", (claim,)).fetchone()[:] == ("29,79,832", None)
    finally:
        conn.close()
    assert count(db, "claim_version") == versions
    assert db.execute("SELECT value_text, value FROM claim_version WHERE claim_id = ?", (claim,)).fetchone()[:] == (
        "29,79,832", None)


# AC 3
def test_states_across_two_reports(ws, db, gct, make_file, acme):
    a = add(gct, make_file, "a.pdf", [SCOPE_1, ["Total Scope 2 emissions", "tCO2e", "700", "650"],
                                      ["Total energy consumed (in GJ)", "", "5,000", "3,600"]])
    b = add(gct, make_file, "b.pdf", [["Total Scope 1 emissions", "tCO2e", "1,100"], ["Total Scope 2 emissions", "tCO2e", "640"],
                                      ["Total energy consumed (in MWh)", "", "1,000"]], periods=BOTH[1:])
    ready(gct)
    ia, ib = ids(gct, a), ids(gct, b)
    got = {(p["metric_key"], p["state"], p["reason"]) for p in pairs(gct)}
    assert got == {("ghg_scope_1", "same value", None), ("ghg_scope_2", "unresolved conflict", None),
                   ("energy_total", "same value", None)}
    p = pair(gct, ia[("Total energy consumed (in GJ)", "FY 2023-24")], ib[("Total energy consumed (in MWh)", "FY 2023-24")])
    assert (p["a"]["document_id"], p["b"]["document_id"], p["a"]["value_base"], p["b"]["value_text"]) == (a, b, 3600.0, "1,000")
    assert len(pairs(gct)) == 3 and all(p["state"] in restate.STATES for p in pairs(gct))
    (st,) = gct("match", "status", "--json").data["companies"]
    assert st["pairs"] == {"same value": 2, "unresolved conflict": 1}
    assert "pairs by state: 2 same value, 1 unresolved conflict" in gct("match", "status").out


# AC 4
def test_what_is_never_compared(ws, db, gct, make_file, acme):
    same = ("FY 2024-25", "FY 2024-25")
    a = add(gct, make_file, "a.pdf", [SCOPE_1, ["Total waste generated (A+B+C)", "A+B+C", "300", "250"]])
    b = add(gct, make_file, "b.pdf", [["Total Scope 1 emissions", "tCO2e", "(1,100)"]], periods=BOTH[1:])
    r = add(gct, make_file, "r.pdf", [["Total Scope 2 emissions", "tCO2e", "70", "65"],
                                      ["Total waste generated (A+B+C)", "A+B+C", "30", "25"]], periods=same)
    c = add(gct, make_file, "c.pdf", [SCOPE_1], boundary="consolidated")
    t = add(gct, make_file, "t.pdf", [["Total Scope 1 emissions", "tCO2", "1,234"]], periods=BOTH[:1])
    d = add(gct, make_file, "d.pdf", [["Total Scope 1 emissions", "tCO2e", "999"]], periods=BOTH[:1], boundary=None)
    ready(gct)
    (item,) = [i for i in gct("match", "review", "--json").data["items"] if i["reporting_boundary"] == "standalone"]
    assert item["claim"] == ids(gct, d)[(SCOPE_1[0], "FY 2024-25")]
    assert gct("match", "link", item["claim"], "--series", item["series"], *WHO).code == 0
    got = {(p["metric_key"], p["period_start"], p["state"], p["reason"]) for p in pairs(gct)}
    assert got == {("ghg_scope_1", "2023-04-01", "not compared", "no numeric value"),
                   ("ghg_scope_1", "2024-04-01", "not compared", "reviewed, not comparable"),
                   ("ghg_scope_2", "2024-04-01", "not compared", "same table row"),
                   ("waste_total", "2024-04-01", "not compared", "unit as printed")}
    paired = {x["claim_id"] for p in pairs(gct) for x in (p["a"], p["b"])}
    assert not paired & {cl["id"] for doc in (c, t) for cl in claims_of(gct, doc)}  # never in one series
    assert len(pairs(gct, "--state", "not-compared")) == 4


# AC 5
def test_same_document_differing_values_are_an_unresolved_conflict(ws, db, gct, make_file, acme):
    label = "Total volume of water consumption (in kilolitres)"
    pdf = make_pdf([{"text": [*page_of([[label, "", "29,79,832", "100"]])["text"],
                              *grid(40, 300, [250, 60, 80, 80], [20, 20], [["Parameter", "Unit", *BOTH],
                                                                           [label, "", "9,76,828", "90"]])["text"]],
                     "lines": [*page_of([[label, "", "29,79,832", "100"]])["lines"],
                               *grid(40, 300, [250, 60, 80, 80], [20, 20], [[""] * 4, [""] * 4])["lines"]]}])
    doc = gct("doc", "add", make_file("w.pdf", pdf), "--company", "Acme", "--json").data["items"][0]["document"]["id"]
    ready(gct)
    got = [(p["period_start"], p["a"]["value_text"], p["b"]["value_text"], p["a"]["document_id"], p["b"]["document_id"],
            p["state"]) for p in pairs(gct)]
    assert sorted(got) == [("2023-04-01", "100", "90", doc, doc, "unresolved conflict"),
                           ("2024-04-01", "29,79,832", "9,76,828", doc, doc, "unresolved conflict")]


# AC 6
def test_record_withdraw_and_refusals(ws, db, gct, make_file, acme, monkeypatch):
    a, b, restated, original = cp2(gct, make_file)
    newer = ids(gct, a)[(SCOPE_1[0], "FY 2024-25")]
    assert pair(gct, original, restated)["state"] == "unresolved conflict"
    for argv, words in [
        ((original, restated, "--quote", "restated due to a typo"), "not printed on page 1"),
        ((original, restated, "--page", "2"), "Page 2 is not in document"),
        ((original, newer), "are not in one same-period set"),
        ((original, restated, "--as", "bob"), "no contributor with key bob"),
    ]:
        r = gct("restate", "record", "--original", argv[0], "--restated", argv[1], "--page", 1, "--quote", QUOTE, *WHO,
                *argv[2:])
        assert r.code in (3, 4) and words in r.err, (argv, r.err)
    assert record(gct, original, restated, quote="the figures for the previous year have been restated").code == 4  # case kept
    assert gct("restate", "record", "--original", original, "--restated", restated, "--page", 1, "--quote", QUOTE,
               "--capacity", "c", "--rationale", "r").code == 2  # no --as
    assert count(db, "restatement") == 0
    r = record(gct, original, restated, "--json", quote=f"  {QUOTE.replace(' ', '   ')} ")  # whitespace collapsed
    assert r.code == 0, r.err
    rec = r.data["restatement"]
    assert (rec["decision"], rec["document"], rec["page"], rec["quote"], rec["contributor"], rec["capacity"]) == (
        "recorded", a, 1, QUOTE, "Ana", "analyst")
    assert (r.data["pair"]["state"], r.data["pair"]["restatement"]["id"]) == ("restatement", rec["id"])
    assert pair(gct, original, restated)["restatement"]["id"] == rec["id"]
    again = record(gct, original, restated)
    assert again.code == 4 and "are restatement, not an unresolved conflict" in again.err
    assert gct("restate", "withdraw", "--original", restated, "--restated", original, *WHO).code == 4  # other order
    w = gct("restate", "withdraw", "--original", original, "--restated", restated, *WHO, "--json")
    assert w.code == 0 and (w.data["restatement"]["decision"], w.data["pair"]["state"]) == ("withdrawn", "unresolved conflict")
    assert (w.data["restatement"]["document"], w.data["restatement"]["page"]) == (a, None)
    assert gct("restate", "withdraw", "--original", original, "--restated", restated, *WHO).code == 4
    shown = gct("restate", "show", restated, "--json").data
    rows = [x for v in shown["versions"] if v["claim"] == restated for x in v["reviews"]["restatements"]]
    assert [(x["decision"], x["role"]) for x in rows] == [("recorded", "restated"), ("withdrawn", "restated")]
    assert "withdrawn" in gct("restate", "show", restated).out
    # not compared and same value pairs are refused
    assert gct("correct", original, "--value", "1,100", *WHO).code == 0
    r = record(gct, original, restated)
    assert r.code == 4 and "newest version" in r.err and "has not been matched yet" in r.err and "gct match" in r.err
    ready(gct)
    r = record(gct, original, restated)
    assert r.code == 4 and "are same value, not an unresolved conflict" in r.err
    real = correct.states
    monkeypatch.setattr(correct, "states", lambda conn, doc: {k: "not found in the newest reading" for k in real(conn, doc)})
    r = record(gct, original, restated)
    assert r.code == 4 and "is not found in the newest reading" in r.err


def test_record_refuses_a_page_not_read_and_a_same_row_pair(ws, db, gct, make_file, acme, monkeypatch):
    real = read.read_page

    def second_fails(page):
        if page.page_number == 2:
            raise ValueError("unreadable")
        return real(page)

    monkeypatch.setattr(read, "read_page", second_fails)
    a = add(gct, make_file, "a.pdf", [SCOPE_1], {"text": [(40, 80, NOTE)]})
    b = add(gct, make_file, "b.pdf", [["Total Scope 1 emissions", "tCO2e", "1,150"]], periods=BOTH[1:])
    row = add(gct, make_file, "r.pdf", [["Total Scope 2 emissions", "tCO2e", "70", "65"]], periods=(BOTH[0], BOTH[0]))
    assert gct("read").code == 4  # page 2 of document a stays unread
    for step in ("extract", "infer"):
        gct(step)
    for basis in gct("infer", "bases", "--json").data["bases"]:
        if basis["kind"] == "reporting_boundary":
            gct("infer", "scope", basis["id"], "--pages", "1", *WHO)
    gct("infer")
    for g in gct("infer", "groups", "--state", "proposed", "--json").data["groups"]:
        gct("infer", "accept", g["id"], *WHO)
    gct("match")
    restated, original = ids(gct, a)[(SCOPE_1[0], "FY 2023-24")], ids(gct, b)[(SCOPE_1[0], "FY 2023-24")]
    r = record(gct, original, restated, page=2)
    assert r.code == 4 and "Page 2 of document" in r.err and "has not been read" in r.err and f"gct read {a}" in r.err
    x, y = (c["id"] for c in claims_of(gct, row))
    r = record(gct, x, y)
    assert r.code == 4 and "not compared (same table row)" in r.err
    r = record(gct, original, x)  # Scope 1 against Scope 2: different series
    assert r.code == 4 and "are not in one same-period set of one series" in r.err


# AC 7
def test_a_new_version_unbinds_the_record(ws, db, gct, make_file, acme):
    a, b, restated, original = cp2(gct, make_file)
    rid = record(gct, original, restated, "--json").data["restatement"]["id"]
    old = db.execute("SELECT MAX(id) FROM claim_version WHERE claim_id = ?", (restated,)).fetchone()[0]
    assert gct("correct", restated, "--value", "1,101", *WHO).code == 0
    ready(gct)
    assert pair(gct, original, restated)["state"] == "unresolved conflict"
    shown = gct("restate", "show", restated, "--json").data
    (p,) = shown["pairs"]
    assert p["state"] == "unresolved conflict" and shown["claim"]["version"] != old
    by = {v["id"]: v["reviews"]["restatements"] for v in shown["versions"] if v["claim"] == restated}
    assert [x["id"] for x in by[old]] == [rid] and by[shown["claim"]["version"]] == []
    assert f"restatement #{rid} recorded" in gct("restate", "show", restated).out


# AC 8
def test_show_lists_every_review_of_both_versions(ws, db, gct, make_file, acme):
    add(gct, make_file, "a.pdf", [SCOPE_1])
    d = add(gct, make_file, "d.pdf", [["Total Scope 1 emissions", "tCO2e", "1,150"]], periods=BOTH[1:], boundary=None,
            lines=[(40, 150, NOTE)])
    ready(gct)
    claim = ids(gct, d)[(SCOPE_1[0], "FY 2023-24")]
    (item,) = gct("match", "review", "--json").data["items"]
    assert gct("match", "link", claim, "--series", item["series"], *WHO).code == 0
    assert gct("correct", claim, "--value", "1,160", *WHO).code == 0
    assert gct("infer", "resolve", claim, "--field", "boundary", "--boundary", "standalone", *WHO).code == 0
    ready(gct)
    assert gct("link").code == 0
    other = next(c["id"] for c in claims_of(gct, 1) if c["period_label"] == "FY 2023-24")
    assert record(gct, other, claim).code == 0
    shown = gct("restate", "show", claim, "--json").data
    old, new = (v["reviews"] for v in shown["versions"] if v["claim"] == claim)
    assert [(x["field"], x["decision"]) for x in old["inference_reviews"]] == [("period", "accepted")]
    assert [x["role"] for x in old["corrections"]] == ["replaced this version"]
    assert [(x["decision"], x["series"]) for x in old["match_reviews"]] == [("linked", item["series"])]
    assert old["restatements"] == []
    assert sorted((x["field"], x["decision"]) for x in new["inference_reviews"]) == [("boundary", "resolved"),
                                                                                    ("period", "accepted")]
    assert [x["role"] for x in new["corrections"]] == ["made this version"]
    assert [x["status"] for x in new["source_match"]] == ["cited"]  # the box prints 1,150, the correction says 1,160
    assert [x["status"] for x in old["source_match"]] == ["matched"]
    assert [(x["decision"], x["role"], x["current"]) for x in new["restatements"]] == [("recorded", "restated", True)]
    assert any(v["claim"] == other for v in shown["versions"])  # the other version of the pair
    out = gct("restate", "show", claim).out
    for words in ("period review", "correction", "replaced this version", "match review", "location p1: cited",
                  "restatement #1 recorded"):
        assert words in out, words


# AC 9
def test_cp2_two_periods_and_one_restated_value(ws, db, gct, make_file, acme):
    a, b, restated, original = cp2(gct, make_file)
    (s,) = series(gct, "ghg_scope_1")
    assert gct("publish", "build").code == 0  # before the record
    rid = record(gct, original, restated, "--json").data["restatement"]["id"]
    shown = gct("series", "show", s["id"], "--all", "--json").data["series"]
    assert shown["periods"] == 2
    assert [(p["value_text"], p["document_id"], [q["state"] for q in p["pairs"]]) for p in shown["points"]] == [
        ("1,100", a, ["restatement"]), ("1,150", b, ["restatement"]), ("1,234", a, [])]
    out = gct("series", "show", s["id"], "--all").out
    assert out.count(f"same period: 2 values, restatement #{rid}") == 2
    assert f"document {a} p1" in out and f"document {b} p1" in out
    listed = gct("restate", "list").out
    assert f"restatement #{rid}" in listed and "1,100 tCO2e" in listed and "1,150 tCO2e" in listed
    out = gct("restate", "show", restated).out
    assert f'document {a} p1: "{QUOTE}"' in out

    def check(v, records):
        conn = published.open_version(ws / "published" / f"v{v}.db")
        try:
            points = conn.execute("SELECT value_text, number FROM series_point WHERE period_end = '2024-03-31'"
                                  " ORDER BY value_text").fetchall()
            assert [tuple(p) for p in points] == [("1,100", 1100.0), ("1,150", 1150.0)]
            assert conn.execute("SELECT COUNT(*) FROM restatement").fetchone()[0] == records
            state = conn.execute("SELECT state, restatement_id FROM comparison WHERE period_end = '2024-03-31'").fetchone()
            assert tuple(state) == (("restatement", rid) if records else ("unresolved conflict", None))
        finally:
            conn.close()

    check(1, 0)
    v2 = gct("publish", "build", "--json").data["version"]
    check(v2, 1)
    check(gct("publish", "build", "--json").data["version"], 1)
    assert gct("publish", "restore", "--json").data["version"] == v2  # restored: both values and the record
    check(v2, 1)
    check(gct("publish", "build", "--json").data["version"], 1)  # rebuilt after the restore
    assert count(db, "restatement") == 1


# AC 10
def test_projection_schema_7(ws, db, gct, make_file, acme):
    a, b, restated, original = cp2(gct, make_file)

    def build():
        v = gct("publish", "build", "--json").data
        conn = published.open_version(ws / "published" / f"v{v['version']}.db")
        try:
            return (dict(conn.execute("SELECT key, value FROM meta").fetchall()),
                    [dict(r) for r in conn.execute("SELECT * FROM comparison")],
                    [dict(r) for r in conn.execute("SELECT * FROM restatement ORDER BY id")])
        finally:
            conn.close()

    meta, comparison, rows = build()
    assert meta["projection_schema"] == "11" and rows == []
    (c,) = comparison
    assert (c["claim_a"], c["claim_b"], c["state"], c["reason"], c["restatement_id"]) == (
        restated, original, "unresolved conflict", None, None)
    mark = published.history_mark(db)
    rid = record(gct, original, restated, "--json").data["restatement"]["id"]
    assert published.history_mark(db) != mark
    mark = published.history_mark(db)
    gct("restate", "withdraw", "--original", original, "--restated", restated, *WHO)
    assert published.history_mark(db) != mark
    _, (c,), rows = build()
    assert (c["state"], c["restatement_id"]) == ("unresolved conflict", None)
    assert [(r["id"], r["decision"], r["evidence_page"], r["evidence_quote"], r["contributor_name"],
             r["contributor_organisation"]) for r in rows] == [
        (rid, "recorded", 1, QUOTE, "Ana", "Acme audit"), (rid + 1, "withdrawn", None, None, "Ana", "Acme audit")]
    assert "contributor_version_id" not in rows[0]
    assert gct("publish", "status", "--json").data["stale"] is False


# Fix round 1, F1
def test_show_says_why_a_claim_has_no_pairs(ws, db, gct, make_file, acme):
    from test_messages import INTERNAL_WORDS, internal_names

    a, b, restated, original = cp2(gct, make_file)
    d = add(gct, make_file, "d.pdf", [["Total Scope 1 emissions", "tCO2e", "999"]], periods=BOTH[:1], boundary=None)
    ready(gct)
    newer, unsure = ids(gct, a)[(SCOPE_1[0], "FY 2024-25")], ids(gct, d)[(SCOPE_1[0], "FY 2024-25")]
    assert gct("correct", restated, "--value", "1,101", *WHO).code == 0
    m = gct("restate", "show", unsure, "--json").data["claim"]
    assert m["match_state"] == "uncertain" and m["match_reason"]
    for claim, line in [(newer, "No pairs: the claim shares no period."),
                        (original, "No pairs: the claim shares no period."),  # a series claim alone in its period
                        (restated, "No pairs: the claim is in no series: not matchable (not mapped yet: gct match)."),
                        (unsure, f"No pairs: the claim is in no series: uncertain ({m['match_reason']}).")]:
        out = gct("restate", "show", claim).out
        assert out.splitlines()[1] == line, (claim, out)
        assert not [w for w in [*INTERNAL_WORDS, *internal_names(ws)] if w in line], (claim, line)


# Fix round 1, F2
def test_a_record_on_an_earlier_version_does_not_bind(ws, db, gct, make_file, acme):
    a, b, restated, original = cp2(gct, make_file)
    rid = record(gct, original, restated, "--json").data["restatement"]["id"]

    def rows(claim) -> set:
        shown = gct("restate", "show", claim, "--json").data
        return {(x["id"], x["current"], x["binds"]) for v in shown["versions"] for x in v["reviews"]["restatements"]}

    def projected() -> list:
        conn = published.open_version(ws / "published" / f"v{gct('publish', 'build', '--json').data['version']}.db")
        try:
            return [tuple(r) for r in conn.execute("SELECT id, binds FROM restatement ORDER BY id")]
        finally:
            conn.close()

    assert rows(restated) == rows(original) == {(rid, True, True)} and projected() == [(rid, 1)]
    assert "(on an earlier version)" not in gct("restate", "show", restated).out
    assert gct("correct", restated, "--value", "1,101", *WHO).code == 0
    ready(gct)
    assert rows(restated) == rows(original) == {(rid, True, False)} and projected() == [(rid, 0)]
    line = next(x for x in gct("restate", "show", restated).out.splitlines() if f"restatement #{rid}" in x)
    assert line.endswith(" (on an earlier version)") and "(superseded)" not in line
    w = gct("restate", "withdraw", "--original", original, "--restated", restated, *WHO)
    assert w.code == 4 and "nothing to withdraw" in w.err
    assert count(db, "restatement") == 1


# Fix round 1, F3
def test_show_on_the_original_lists_the_old_restated_version(ws, db, gct, make_file, acme):
    a, b, restated, original = cp2(gct, make_file)
    rid = record(gct, original, restated, "--json").data["restatement"]["id"]
    old = db.execute("SELECT MAX(id) FROM claim_version WHERE claim_id = ?", (restated,)).fetchone()[0]
    assert gct("correct", restated, "--value", "1,101", *WHO).code == 0
    ready(gct)
    versions = gct("restate", "show", original, "--json").data["versions"]
    by = {v["id"]: v for v in versions}
    assert len(by) == len(versions) and by[old]["claim"] == restated
    assert [x["role"] for x in by[old]["reviews"]["corrections"]] == ["replaced this version"]
    assert [x["id"] for x in by[old]["reviews"]["restatements"]] == [rid]
    assert f"claim {restated} version {old}:" in gct("restate", "show", original).out
