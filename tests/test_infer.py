import json
import sqlite3

import pytest

from conftest import make_pdf
from test_extract import count, newest_run
from gct.stages import infer
from gct.workspace import layout, published, store

WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked on the page")
FY_LINES = ["The Annual Report covers the Financial Year (`FY') ended", "March 31, 2024 for the Company."]
TATA = ["13. Reporting boundary: Report is prepared on a standalone", "basis i.e, Tata Motors Limited (`TML' or `the Company')."]
QUESTION = ["13. Reporting boundary - Are the disclosures under this report made on a",
            "standalone basis (i.e. only for the entity) or on a consolidated basis (i.e. for",
            "the entity and all the entities which form a part of its consolidated financial",
            "statements, taken together)."]
MAHINDRA = QUESTION + ["are made on Standalone c. A brief on types of customers", "basis. Th e Company serves its customers."]
NAV = ["INTEGRATED 4 STATUTORY 132 CONSOLIDATED 262 STANDALONE 383", "REPORT REPORTS FINANCIALS FINANCIALS"]


def page(lines):
    return {"text": [(40, 80 + 20 * i, s) for i, s in enumerate(lines)]}


def add_doc(gct, make_file, name, pages):
    r = gct("doc", "add", make_file(name, make_pdf([page(p) for p in pages])), "--company", "Acme", "--json")
    return r.data["items"][0]["document"]["id"]


def label_claims(db, doc, labels, page_number=1):
    """One hand claim per period label on the page, as the extractor stores it. Returns the claim ids."""
    ids = []
    for label in labels:
        n = db.execute("SELECT COUNT(*) FROM claim").fetchone()[0]
        claim = db.execute("INSERT INTO claim (company_id, document_id, page_number, locator, created_at)"
                           " VALUES (1, ?, ?, ?, 't')", (doc, page_number, f"h{n}")).lastrowid
        new_version(db, claim, label)
        ids.append(claim)
    db.commit()
    return ids


def new_version(db, claim, label):
    version = db.execute("INSERT INTO claim_version (claim_id, run_id, method, config_version, value_text, period_label,"
                         " created_at) VALUES (?, 1, 'hand', 'c', '7', ?, 't')", (claim, label)).lastrowid
    db.execute("INSERT INTO evidence_ref (claim_version_id, document_id, page_number, created_at)"
               " SELECT ?, document_id, page_number, 't' FROM claim WHERE id = ?", (version, claim))
    db.commit()


@pytest.fixture
def acme(ws, gct):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")


def run_infer(gct, *argv):
    r = gct("infer", *argv, "--json")
    assert r.code == 0, (r.out, r.err)
    return r.data


def listed(gct, doc):
    """{claim id: claim record} from claims list --json."""
    return {c["id"]: c for c in gct("claims", "list", "--doc", doc, "--json").data["claims"]}


def period(c):
    p = c["period"]
    return (p["state"], p["kind"], p["start"], p["end"]) if p["state"] != "unresolved" else ("unresolved", p["reason"])


# AC 1
def test_migration_10_applies_to_a_version_9_workspace(tmp_path, gct):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    assert store.migrate(c, up_to=9) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.close()
    assert gct("infer", "groups", "--workspace", root).code == 0
    c = store.connect(root / layout.DB_NAME)
    assert c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 21
    c.close()


def test_new_tables_reject_changes_and_bad_values(ws, db, gct, make_file, acme):
    doc = add_doc(gct, make_file, "r.pdf", [FY_LINES + TATA])
    gct("read")
    (claim,) = label_claims(db, doc, ["FY24"])
    gct("infer")
    boundary = next(b["id"] for b in run_infer(gct, "bases")["bases"] if b["kind"] == "reporting_boundary")
    gct("infer", "scope", boundary, "--pages", "1", *WHO)
    gct("infer")
    group = run_infer(gct, "groups", "--state", "proposed")["groups"][0]["id"]
    gct("infer", "accept", group, *WHO)
    for table in ("basis", "basis_scope", "inference", "inference_review"):
        assert count(db, table)
        for stmt in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
                db.execute(stmt)
    bad = [
        "INSERT INTO basis (document_id, page_number, kind, wording, run_id, config_version, created_at)"
        " VALUES (1, 1, 'period', 'w', 1, 'c', 't')",
        "INSERT INTO basis (document_id, page_number, kind, wording, boundary, run_id, config_version, created_at)"
        " VALUES (1, 1, 'reporting_boundary', 'w2', 'group', 1, 'c', 't')",
        "INSERT INTO inference (claim_version_id, field, state, group_key, run_id, config_version, created_at)"
        " VALUES (1, 'unit', 'proposed', 'k', 1, 'c', 't')",
        "INSERT INTO inference (claim_version_id, field, state, group_key, run_id, config_version, created_at)"
        " VALUES (1, 'period', 'accepted', 'k', 1, 'c', 't')",
        "INSERT INTO inference (claim_version_id, field, state, period_kind, group_key, run_id, config_version, created_at)"
        " VALUES (1, 'period', 'proposed', 'month', 'k', 1, 'c', 't')",
        "INSERT INTO inference_review (claim_version_id, field, decision, contributor_version_id, capacity, rationale,"
        " created_at) VALUES (1, 'period', 'approved', 1, 'c', 'r', 't')",
        "INSERT INTO inference_review (claim_version_id, field, decision, boundary, contributor_version_id, capacity,"
        " rationale, created_at) VALUES (1, 'boundary', 'resolved', 'group', 1, 'c', 'r', 't')",
    ]
    for stmt in bad:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(stmt)


# AC 2
def test_dated_labels_resolve_from_the_label_alone(ws, db, gct, make_file, acme):
    doc = add_doc(gct, make_file, "r.pdf", [["A page without any statement."]])
    gct("read")
    labels = ["Balance as at 31st March, 2025", "Balance as at 01-04-2024", "for the year ended March 31, 2024",
              "for the period 1 April 2023 to 31 March 2024", "1 April 2023 to 30 June 2023",
              "1 April 2023 to 30 September 2023", "1 January 2024 to 31 December 2024", "1 April 2023 to 15 May 2023"]
    ids = label_claims(db, doc, labels)
    run_infer(gct)
    got = {c["period"]["label"]: period(c) for c in listed(gct, doc).values()}
    assert [got[label] for label in labels] == [
        ("proposed", "as_at", "2025-03-31", "2025-03-31"),
        ("unresolved", "numeric date order ambiguous"),
        ("proposed", "fiscal_year", "2023-04-01", "2024-03-31"),
        ("proposed", "fiscal_year", "2023-04-01", "2024-03-31"),
        ("proposed", "quarter", "2023-04-01", "2023-06-30"),
        ("proposed", "half", "2023-04-01", "2023-09-30"),
        ("proposed", "calendar_year", "2024-01-01", "2024-12-31"),
        ("unresolved", "span is not a year, half or quarter"),
    ]
    rows = db.execute("SELECT basis_id FROM inference WHERE field = 'period' AND state = 'proposed'").fetchall()
    assert rows and all(r[0] is None for r in rows)  # the label is its own source: no basis row
    line = next(x for x in gct("claims", "list", "--doc", doc).out.splitlines() if x.startswith(f"{ids[0]}  "))
    assert "2025-03-31..2025-03-31 as_at proposed" in line


def test_printed_date_forms():
    assert infer._date("31st March, 2025").isoformat() == "2025-03-31"
    assert infer._date("March 31, 2024").isoformat() == "2024-03-31"
    assert infer._date("31-03-2025").isoformat() == "2025-03-31"
    for text, reason in (("01-04-2024", infer.AMBIGUOUS), ("31st February, 2024", infer.INVALID)):
        with pytest.raises(infer.Unresolved, match=reason):
            infer._date(text)


# AC 3
FY_LABELS = ["FY24", "FY 2023-24", "2023-24", "FY23", "FY 2023-25", "Q1 FY25", "H2 FY 2023-24", "FY24 Q4"]


def test_fiscal_year_labels_resolve_only_through_one_statement(ws, db, gct, make_file, acme):
    with_fy = add_doc(gct, make_file, "fy.pdf", [FY_LINES])
    without = add_doc(gct, make_file, "none.pdf", [["No year statement here."]])
    both = add_doc(gct, make_file, "both.pdf", [FY_LINES, ["Its financial year ended December 31, 2023."]])
    gct("read")
    for d in (with_fy, without, both):
        label_claims(db, d, FY_LABELS)
    run_infer(gct)
    got = {c["period"]["label"]: period(c) for c in listed(gct, with_fy).values()}
    fy = ("proposed", "fiscal_year", "2023-04-01", "2024-03-31")
    assert [got[x] for x in FY_LABELS] == [
        fy, fy, fy, ("proposed", "fiscal_year", "2022-04-01", "2023-03-31"),
        ("unresolved", "label years not consecutive"),
        ("proposed", "quarter", "2024-04-01", "2024-06-30"),
        ("proposed", "half", "2023-10-01", "2024-03-31"),
        ("proposed", "quarter", "2024-01-01", "2024-03-31"),
    ]
    c = next(c for c in listed(gct, with_fy).values() if c["period"]["label"] == "FY24")
    assert c["period"]["basis"]["page"] == 1 and "ended March 31, 2024" in c["period"]["basis"]["wording"]
    none = {c["period"]["label"]: period(c) for c in listed(gct, without).values()}
    assert [none[x] for x in FY_LABELS] == [got[x] for x in FY_LABELS]
    conflict = {period(c) for c in listed(gct, both).values() if c["period"]["label"] != "FY 2023-25"}
    assert conflict == {("unresolved", "fiscal year end conflict: p1 and p2")}


def test_calendar_labels_need_no_statement():
    assert infer.period_of("CY24", [])[:3] == ("calendar_year", *map(infer.date.fromisoformat, ("2024-01-01", "2024-12-31")))
    kind, start, end, basis = infer.period_of("Q3 CY2024", [])
    assert (kind, start.isoformat(), end.isoformat(), basis) == ("quarter", "2024-07-01", "2024-09-30", None)
    assert infer.period_of("calendar year 2024", [])[0] == "calendar_year"


# AC 4
def test_other_labels_stay_unresolved_with_their_reasons(ws, db, gct, make_file, acme):
    doc = add_doc(gct, make_file, "r.pdf", [FY_LINES])
    gct("read")
    label_claims(db, doc, ["2024", "Q2", "H1", None, "Q1-Q3"])
    run_infer(gct)
    assert sorted(period(c) for c in listed(gct, doc).values()) == [
        ("unresolved", "bare year"), ("unresolved", "label not recognised"), ("unresolved", "no period label"),
        ("unresolved", "quarter or half without a year"), ("unresolved", "quarter or half without a year")]
    v = gct("publish", "build", "--json").data
    conn = published.open_version(ws / "published" / f"v{v['version']}.db")
    rows = conn.execute("SELECT period_kind, period_start, period_end, period_state, proposed_period_start FROM claim").fetchall()
    conn.close()
    assert {tuple(r) for r in rows} == {(None, None, None, "unresolved", None)}


# AC 5
def test_boundary_statements_and_what_is_never_one(ws, db, gct, make_file, acme):
    doc = add_doc(gct, make_file, "r.pdf", [TATA, QUESTION, NAV, MAHINDRA])
    gct("read")
    label_claims(db, doc, ["FY24"])
    run_infer(gct)
    data = run_infer(gct, "bases")
    (b,) = data["bases"]
    assert (b["page"], b["kind"], b["boundary"], b["detail"]) == (1, "reporting_boundary", "standalone",
                                                                   "Tata Motors Limited (‘TML’ or ‘the Company’)")
    assert b["scope"] is None
    assert data["headings"] == [{"document": doc, "page": 2, "reason": "heading without a readable answer"},
                                {"document": doc, "page": 4, "reason": "heading without a readable answer"}]
    text = gct("infer", "bases").out
    assert f"document {doc} p4  heading without a readable answer" in text and "no pages declared" in text
    assert "conflict" not in json.dumps(listed(gct, doc))


# AC 6
def test_a_boundary_applies_only_inside_declared_ranges(ws, db, gct, make_file, acme):
    doc = add_doc(gct, make_file, "r.pdf", [TATA, ["p2"], ["p3"], ["p4"],
                                            ["The report is prepared on a consolidated basis."]])
    gct("read")
    ids = {p: label_claims(db, doc, [None], p)[0] for p in (1, 2, 3, 4)}

    def states():
        return {p: (c["boundary"]["state"], c["boundary"]["boundary"], c["boundary"]["reason"])
                for p, c in ((c["page_number"], c) for c in listed(gct, doc).values())}

    run_infer(gct)
    assert set(states().values()) == {("unresolved", "unknown", "no boundary statement covers this page")}
    standalone, consolidated = (b["id"] for b in run_infer(gct, "bases")["bases"])
    gct("infer", "scope", standalone, "--pages", "1-3", *WHO)
    run_infer(gct)
    s = states()
    assert s[1] == s[2] == s[3] == ("proposed", "standalone", None)
    assert s[4] == ("unresolved", "unknown", "no boundary statement covers this page")
    gct("infer", "scope", consolidated, "--pages", "3-4", *WHO)
    run_infer(gct)
    s = states()
    assert s[2] == ("proposed", "standalone", None) and s[4] == ("proposed", "consolidated", None)
    assert s[3] == ("unresolved", "unknown", f"boundary conflict: basis #{standalone} and #{consolidated}")
    assert gct("infer", "scope", standalone, "--pages", "4-9", *WHO).code == 4


# AC 7
def test_no_single_value_is_forced(ws, db, gct, make_file, acme):
    doc = add_doc(gct, make_file, "r.pdf", [FY_LINES + TATA])
    gct("read")
    label_claims(db, doc, ["FY24", "FY23", "Balance as at 31st March, 2025", "2025"])
    (unlabelled,) = label_claims(db, doc, [None], 1)
    run_infer(gct)
    cs = listed(gct, doc)
    results = [period(c) for c in cs.values() if c["id"] != unlabelled]
    assert len({r for r in results if r[0] == "proposed"}) == 3 and results.count(("unresolved", "bare year")) == 1
    assert period(cs[unlabelled]) == ("unresolved", "no period label")
    assert {c["boundary"]["state"] for c in cs.values()} == {"proposed"}  # single boundary defaults to 1..len(pages)


# AC 8
def test_groups_bulk_accept_and_a_new_version_needs_accepting_again(ws, db, gct, make_file, acme):
    doc = add_doc(gct, make_file, "r.pdf", [FY_LINES])
    gct("read")
    ids = label_claims(db, doc, ["FY24", "FY 2023-24", "2023-24", "2024"])
    run_infer(gct)
    gs = run_infer(gct, "groups", "--state", "proposed")["groups"]
    (g,) = [g for g in gs if g["field"] == "period"]
    assert (g["claims"], g["start"], g["end"], g["basis"]["page"]) == (3, "2023-04-01", "2024-03-31", 1)
    assert g["reviews"] == {"accepted": 0, "resolved": 0, "rejected": 0, "open": 3}
    assert f"{g['id']}  document {doc}  period  proposed  2023-04-01..2024-03-31 fiscal_year" in gct("infer", "groups").out
    r = gct("infer", "accept", g["id"], *WHO)
    assert r.code == 0 and "This confirms the fiscal year end stated on page 1" in r.out
    assert count(db, "inference_review") == 3
    assert {period(c) for c in listed(gct, doc).values() if c["id"] in ids[:3]} == {
        ("accepted", "fiscal_year", "2023-04-01", "2024-03-31")}
    v = gct("publish", "build", "--json").data
    conn = published.open_version(ws / "published" / f"v{v['version']}.db")
    main = conn.execute("SELECT period_start, period_end, period_state FROM claim WHERE period_label = 'FY24'").fetchone()
    conn.close()
    assert tuple(main) == ("2023-04-01", "2024-03-31", "accepted")
    new_version(db, ids[0], "FY24")  # a later extraction makes a new claim version
    run_infer(gct)
    assert period(listed(gct, doc)[ids[0]]) == ("proposed", "fiscal_year", "2023-04-01", "2024-03-31")
    assert gct("infer", "accept", "000000000000", *WHO).code == 3
    unresolved = next(g for g in run_infer(gct, "groups", "--state", "unresolved")["groups"] if g["field"] == "period")
    assert gct("infer", "accept", unresolved["id"], *WHO).code == 4


# AC 9
def test_individual_resolve_and_reject(ws, db, gct, make_file, acme):
    doc = add_doc(gct, make_file, "r.pdf", [FY_LINES])
    gct("read")
    first, second, third = label_claims(db, doc, ["2024", "FY24", "FY23"])
    run_infer(gct)
    bad = gct("infer", "resolve", first, "--field", "period", "--kind", "calendar_year", "--start", "2024-12-31",
              "--end", "2024-01-01", *WHO)
    assert bad.code == 2 and "after the end" in bad.err
    ok = gct("infer", "resolve", first, "--field", "period", "--kind", "calendar_year", "--start", "2024-01-01",
             "--end", "2024-12-31", *WHO)
    assert ok.code == 0, ok.err
    p = listed(gct, doc)[first]["period"]
    assert (p["state"], p["kind"], p["start"], p["end"]) == ("resolved", "calendar_year", "2024-01-01", "2024-12-31")
    assert (p["review"]["contributor"], p["review"]["capacity"], p["review"]["rationale"]) == (
        "Ana", "analyst", "checked on the page")
    b = gct("infer", "resolve", first, "--field", "boundary", "--boundary", "consolidated", "--detail", "Acme group", *WHO)
    assert b.code == 0 and listed(gct, doc)[first]["boundary"]["detail"] == "Acme group"
    r = gct("infer", "reject", "--claim", second, "--field", "period", *WHO)
    assert r.code == 0, r.err
    p = listed(gct, doc)[second]["period"]
    assert (p["state"], p["start"], p["reason"], p["review"]["decision"]) == ("unresolved", None, "rejected", "rejected")
    assert gct("infer", "reject", "--claim", second, "--field", "period", *WHO).code == 4  # nothing proposed now
    g = next(g for g in run_infer(gct, "groups")["groups"] if g["field"] == "period" and g["reviews"]["rejected"])
    assert g["reviews"]["rejected"] == 1
    group = listed(gct, doc)[third]["period"]["group"]
    assert gct("infer", "reject", group, *WHO).code == 0 and period(listed(gct, doc)[third]) == ("unresolved", "rejected")
    v = gct("publish", "build", "--json").data
    conn = published.open_version(ws / "published" / f"v{v['version']}.db")
    rows = dict(conn.execute("SELECT id, period_kind FROM claim"))
    conn.close()
    assert rows == {first: "calendar_year", second: None, third: None}
    # the claim versions keep what was extracted; inference and review live beside them
    assert {tuple(r) for r in db.execute("SELECT period_kind, period_start, period_end, reporting_boundary, boundary_detail"
                                         " FROM claim_version")} == {(None, None, None, "unknown", None)}


# AC 10
def test_rerun_is_cached_and_scopes_survive(ws, db, gct, make_file, acme):
    doc = add_doc(gct, make_file, "r.pdf", [FY_LINES + TATA])
    gct("read")
    label_claims(db, doc, ["FY24", "2024"])
    (d,) = run_infer(gct)["documents"]
    assert (d["inferred"], d["cached"], d["bases"]) == (1, 0, 2)
    rows = [count(db, t) for t in ("basis", "inference")]
    (d,) = run_infer(gct)["documents"]
    assert (d["inferred"], d["cached"]) == (0, 1) and [count(db, t) for t in ("basis", "inference")] == rows
    boundary = next(b["id"] for b in run_infer(gct, "bases")["bases"] if b["kind"] == "reporting_boundary")
    gct("infer", "scope", boundary, "--pages", "1", *WHO)
    (d,) = run_infer(gct)["documents"]
    assert d["inferred"] == 1 and count(db, "basis") == rows[0]
    assert d["boundary"]["proposed"] == 2
    (d,) = run_infer(gct)["documents"]
    assert d["cached"] == 1 and d["boundary"]["proposed"] == 2


def two_docs(db, gct, make_file):
    first = add_doc(gct, make_file, "a.pdf", [FY_LINES])
    second = add_doc(gct, make_file, "b.pdf", [FY_LINES + ["second"]])
    gct("read")
    label_claims(db, first, ["FY24"])
    label_claims(db, second, ["FY23"])
    return first, second


def test_retry_only_the_failed_documents_of_an_infer_run(ws, db, gct, make_file, acme, monkeypatch):
    first, second = two_docs(db, gct, make_file)
    real = infer.period_of

    def flaky(label, bases):
        if label == "FY23":
            raise ValueError("boom")
        return real(label, bases)

    monkeypatch.setattr(infer, "period_of", flaky)
    r = gct("infer", "--json")
    assert r.code == 4 and r.data["status"] == "partial" and r.data["next_action"] == infer.RETRY
    n = newest_run(db)
    monkeypatch.setattr(infer, "period_of", real)
    r = gct("run", "retry", n, "--json")
    assert r.code == 0 and (r.data["run_id"], r.data["of_run"]) == (n + 1, n)
    (d,) = r.data["documents"]
    assert (d["id"], d["inferred"], d["failed"]) == (second, 1, 0)
    assert gct("run", "resume", n + 1).code == 4  # it finished
    assert gct("run", "retry", n, "--json").data["documents"] == []


def test_resume_an_interrupted_infer(ws, db, gct, make_file, acme, monkeypatch):
    first, second = two_docs(db, gct, make_file)
    real = infer.period_of

    def stop(label, bases):
        if label == "FY23":
            raise KeyboardInterrupt
        return real(label, bases)

    monkeypatch.setattr(infer, "period_of", stop)
    with pytest.raises(KeyboardInterrupt):
        gct("infer")
    n = newest_run(db)
    monkeypatch.setattr(infer, "period_of", real)
    r = gct("run", "resume", n, "--json")
    assert r.code == 0 and r.data["of_run"] == n
    assert [(d["id"], d["inferred"], d["cached"]) for d in r.data["documents"]] == [(first, 0, 1), (second, 1, 0)]
    assert gct("run", "resume", n).out.splitlines()[0] == f"Run {n + 2} resumes run {n}."


# AC 11
def test_projection_carries_only_accepted_or_resolved_values_in_the_main_fields(ws, db, gct, make_file, acme):
    doc = add_doc(gct, make_file, "r.pdf", [FY_LINES + TATA])
    gct("read")
    fy, other = label_claims(db, doc, ["FY24", "FY23"])
    run_infer(gct)
    boundary = next(b["id"] for b in run_infer(gct, "bases")["bases"] if b["kind"] == "reporting_boundary")
    gct("infer", "scope", boundary, "--pages", "1", *WHO)
    run_infer(gct)

    def projected():
        v = gct("publish", "build", "--json").data
        conn = published.open_version(ws / "published" / f"v{v['version']}.db")
        rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM claim")}
        assert conn.execute("SELECT value FROM meta WHERE key = 'projection_schema'").fetchone()[0] == "16"
        conn.close()
        return v, rows

    before, rows = projected()
    r = rows[fy]
    assert (r["period_kind"], r["period_start"], r["reporting_boundary"], r["boundary_detail"]) == (
        "fiscal_year", "2023-04-01", "standalone", "Tata Motors Limited (‘TML’ or ‘the Company’)")
    assert (r["period_state"], r["boundary_state"]) == ("proposed", "proposed")
    assert (r["proposed_period_kind"], r["proposed_period_start"], r["proposed_period_end"]) == (
        "fiscal_year", "2023-04-01", "2024-03-31")
    assert (r["proposed_reporting_boundary"], r["proposed_boundary_detail"]) == (
        "standalone", "Tata Motors Limited (‘TML’ or ‘the Company’)")
    assert json.loads(r["period_basis"])["page"] == 1
    for c in listed(gct, doc).values():
        if c["id"] == fy:
            gct("infer", "accept", c["period"]["group"], *WHO)
            gct("infer", "accept", c["boundary"]["group"], *WHO)
    mark = published.history_mark(db)
    assert mark != before["history_mark"]
    after, rows = projected()
    r = rows[fy]
    assert (r["period_kind"], r["period_start"], r["period_end"], r["period_state"]) == (
        "fiscal_year", "2023-04-01", "2024-03-31", "accepted")
    assert (r["reporting_boundary"], r["boundary_state"], r["proposed_reporting_boundary"]) == ("standalone", "accepted", None)
    assert rows[other]["boundary_state"] == "accepted"  # the boundary group held both claims
    assert (rows[other]["period_start"], rows[other]["proposed_period_start"]) == ("2022-04-01", "2022-04-01")
    assert after["history_mark"] != before["history_mark"]


def test_api_claims_show_only_accepted_values(ws, db, gct, make_file, acme):
    from test_api import call, cookie
    from gct.api import server

    doc = add_doc(gct, make_file, "r.pdf", [TATA + FY_LINES])
    gct("read")
    claim, other = label_claims(db, doc, [None, None])
    accepted, proposed = label_claims(db, doc, ["FY24", "FY23"])
    run_infer(gct)
    boundary = next(b["id"] for b in run_infer(gct, "bases")["bases"] if b["kind"] == "reporting_boundary")
    gct("infer", "scope", boundary, "--pages", "1", *WHO)
    run_infer(gct)
    gct("infer", "reject", "--claim", other, "--field", "boundary", *WHO)
    gct("infer", "resolve", claim, "--field", "boundary", "--boundary", "standalone", *WHO)
    gct("infer", "resolve", claim, "--field", "period", "--kind", "calendar_year", "--start", "2024-01-01",
        "--end", "2024-12-31", *WHO)
    gct("infer", "accept", listed(gct, doc)[accepted]["period"]["group"], *WHO)
    v = gct("publish", "build", "--json").data

    def api():
        srv = server.serve(ws, port=0)
        try:
            return call(srv.port, f"/api/documents/{doc}/claims", **cookie(srv))
        finally:
            srv.stop()

    status, _, body = api()
    assert status == 200
    rows = {c["id"]: c for c in json.loads(body)["claims"]}
    assert rows[claim]["reporting_boundary"] == "standalone" and rows[other]["reporting_boundary"] == "unknown"
    assert (rows[other]["boundary_state"], rows[accepted]["boundary_state"]) == ("unresolved", "proposed")
    period = ("period_label", "period_kind", "period_start", "period_end", "period_state")
    assert [rows[claim][k] for k in period] == [None, "calendar_year", "2024-01-01", "2024-12-31", "resolved"]
    assert [rows[accepted][k] for k in period] == ["FY24", "fiscal_year", "2023-04-01", "2024-03-31", "accepted"]
    assert [rows[proposed][k] for k in period] == ["FY23", "fiscal_year", "2022-04-01", "2023-03-31", "proposed"]
    assert not any(k.startswith("proposed") for k in rows[proposed])
    old = sqlite3.connect(ws / "published" / f"v{v['version']}.db")  # as if built by gct before projection 4
    old.execute("UPDATE meta SET value = '3' WHERE key = 'projection_schema'")
    old.commit()
    old.close()
    status, _, body = api()
    assert status == 409 and "gct publish build" in json.loads(body)["next_action"]


# Review fixes (Xiao, 2026-10-21)
def test_shorter_periods_ended_are_not_years():
    for label in ("Half year ended 30 September 2024", "For the half-year ended 30th September, 2024",
                  "Quarter ended 30 June 2024", "Nine months ended 31 December 2024",
                  "Quarter and year ended 31 March 2024", "Six months and year ended March 31, 2024",
                  "Half year and year ended 31 March 2024"):
        with pytest.raises(infer.Unresolved, match=infer.NOT_RECOGNISED):
            infer.period_of(label, [])
    assert infer.period_of("for the year ended March 31, 2024", [])[0] == "fiscal_year"


def test_a_quarter_or_half_sentence_states_no_year_end():
    for text in ("Operations in FY 2023-24: the quarter ended June 30, 2023 was strong.",
                 "In FY 2023-24 the half year ended September 30, 2023 saw growth.",
                 "In the financial year, the nine months ended December 31, 2023 were slow."):
        assert infer.bases_of({"text": text}) == ([], False)
    (b,), _ = infer.bases_of({"text": "the Financial Year ended March 31, 2024"})
    assert b["fy_end"] == "03-31"


def test_a_negated_sentence_states_no_boundary():
    text = "The Company is not required to report on a consolidated basis as it has no subsidiaries."
    assert infer.bases_of({"text": text}) == ([], False)
    (b,), _ = infer.bases_of({"text": "As the Company has no subsidiaries, this report is prepared on a standalone basis."})
    assert b["boundary"] == "standalone"


def test_century_labels_and_bare_dates():
    basis = [{"id": 1, "page_number": 1, "fy_end": "03-31"}]
    for label in ("FY 1999-00", "1999-00"):
        assert infer.period_of(label, basis)[1:3] == (infer.date(1999, 4, 1), infer.date(2000, 3, 31))
    assert infer.period_of("FY 2099-00", basis)[1:3] == (infer.date(2099, 4, 1), infer.date(2100, 3, 31))
    with pytest.raises(infer.Unresolved, match=infer.NOT_CONSECUTIVE):
        infer.period_of("FY 1999-01", basis)
    with pytest.raises(infer.Unresolved, match=infer.AMBIGUOUS):
        infer.period_of("01-04-2024", [])
    with pytest.raises(infer.Unresolved, match=infer.NOT_RECOGNISED):
        infer.period_of("31-03-2025", [])


def test_group_decisions_never_override_a_claim_by_claim_decision(ws, db, gct, make_file, acme):
    doc = add_doc(gct, make_file, "r.pdf", [FY_LINES])
    gct("read")
    mine, refused, other, third = label_claims(db, doc, ["FY24", "FY 2023-24", "2023-24", "FY 2024"])
    run_infer(gct)
    gct("infer", "resolve", mine, "--field", "period", "--kind", "calendar_year", "--start", "2024-01-01",
        "--end", "2024-12-31", *WHO)
    gct("infer", "reject", "--claim", refused, "--field", "period", *WHO)
    group = listed(gct, doc)[other]["period"]["group"]
    r = gct("infer", "accept", group, *WHO, "--json").data
    assert (r["accepted"], r["skipped"]) == (2, {"rejected": 1, "resolved": 1})
    assert (r["group"]["reviews"]["resolved"], r["group"]["reviews"]["rejected"]) == (1, 1)
    again = gct("infer", "accept", group, *WHO)
    assert "Accepted 0 claims" in again.out and "Left as they were: 2 accepted, 1 rejected, 1 resolved" in again.out
    cs = listed(gct, doc)
    assert period(cs[mine]) == ("resolved", "calendar_year", "2024-01-01", "2024-12-31")
    assert period(cs[refused]) == ("unresolved", "rejected")
    assert period(cs[other])[0] == period(cs[third])[0] == "accepted"
    line = next(x for x in gct("claims", "list", "--doc", doc).out.splitlines() if x.startswith(f"{other}  "))
    assert "2023-24 → 2023-04-01..2024-03-31 fiscal_year accepted" in line
    r = gct("infer", "reject", group, *WHO, "--json").data
    assert (r["rejected"], r["skipped"]) == (2, {"rejected": 1, "resolved": 1})
    cs = listed(gct, doc)
    assert period(cs[mine])[0] == "resolved" and period(cs[other]) == ("unresolved", "rejected")
    # a claim-by-claim decision may still be made over another one
    assert gct("infer", "reject", "--claim", mine, "--field", "period", *WHO).code == 0
    assert period(listed(gct, doc)[mine]) == ("unresolved", "rejected")
    assert gct("infer", "reject", "--claim", mine, "--field", "period", *WHO).code == 4  # already rejected
    assert gct("infer", "resolve", refused, "--field", "period", "--kind", "fiscal_year", "--start", "2023-04-01",
               "--end", "2024-03-31", *WHO).code == 0
    assert period(listed(gct, doc)[refused])[0] == "resolved"
