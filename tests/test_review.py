"""Story 5.1: company confirmations and auditor reviews, the two ledgers. Labelled test entries on synthetic workspaces
only; no real report and no copy of a real workspace is used."""
import re
import sqlite3

import pytest

from conftest import make_pdf
from test_deletion import WHO as DELETE_WHO, scan, token, world  # noqa: F401 (world is a fixture)
from old_code import labels_table
from test_match import SCOPE_1, ids
from test_restate import acme, add  # noqa: F401 (acme is a fixture)
from test_sheet import MAP, ROWS, csv_bytes
from gct.stages import extract
from gct.workspace import published, store

SELF = ("Identities and capacities are self-declared. GCT does not check them and does not adopt any conclusion as its"
        " own.")
NOTE = ("--evidence-note", "ledger export, row 12")
WORDS = re.compile(r"verified|assured|certified|compliant", re.I)
CONTRIBUTORS = (("bob", "Bob", "Acme Ltd"), ("cara", "Cara", "Audit LLP"), ("dev", "Dev", None))


def rec(gct, ledger, claim, version, outcome="accepted", *extra, who="ana", capacity="head of sustainability",
        scope="Scope 1, FY 2024-25", conclusion="agrees with our records", evidence=NOTE):
    return gct("review", ledger, claim, "--version", version, "--outcome", outcome, "--scope", scope,
               "--conclusion", conclusion, "--as", who, "--capacity", capacity, *evidence, *extra)


def newest(gct, claim) -> int:
    return gct("claims", "history", claim, "--json").data["versions"][-1]["id"]


def listed(gct, claim) -> dict:
    """{version id: version record} of gct review list."""
    return {v["id"]: v for v in gct("review", "list", claim, "--json").data["versions"]}


def rows(db, table) -> list[dict]:
    return [dict(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY id")]


def counts(db) -> dict:
    return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}


def first_claim(gct, make_file) -> tuple[int, int, int]:
    """Acme's one-page report, read and extracted: (document, its FY 2024-25 Scope 1 claim, that claim's version)."""
    doc = add(gct, make_file, "a.pdf", [SCOPE_1])
    assert gct("read").code == 0 and gct("extract").code == 0
    claim = ids(gct, doc)[(SCOPE_1[0], "FY 2024-25")]
    return doc, claim, newest(gct, claim)


@pytest.fixture
def one(ws, gct, make_file, acme):  # noqa: F811
    for key, name, org in CONTRIBUTORS:
        gct("contributor", "add", key, "--name", name, *(("--organisation", org) if org else ()))
    return first_claim(gct, make_file)


def projected(ws, gct, table) -> list[dict]:
    v = gct("publish", "build", "--json").data["version"]
    conn = published.open_version(ws / "published" / f"v{v}.db")
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
    finally:
        conn.close()


# AC 1, matrix column "workspace upgraded from 0016"
def test_migration_17_upgrades_a_4_5_workspace_and_both_tables_are_append_only(tmp_path, gct, make_file, monkeypatch):
    real = store.migrate
    monkeypatch.setattr(store, "migrate", lambda conn, up_to=None: real(conn, 16))
    root = tmp_path / "old"
    assert gct("workspace", "init", root).code == 0
    labels_table(root)  # story 7.1 part A (Q1): the current doc add writes it
    monkeypatch.setenv("GCT_WORKSPACE", str(root))
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    doc = add(gct, make_file, "a.pdf", [SCOPE_1])
    assert gct("read").code == 0 and gct("extract").code == 0
    db = sqlite3.connect(root / "workspace.db")
    claim = db.execute("SELECT claim_id FROM claim_version WHERE period_label = 'FY 2024-25'").fetchone()[0]
    assert db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 16
    db.execute("DROP TABLE document_label")  # the upgrade below creates it (Q1)
    monkeypatch.setattr(store, "migrate", real)
    r = gct("review", "list", claim)
    assert r.code == 0 and "company confirmations: none" in r.out and "auditor reviews: none" in r.out, r.out
    assert db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 22
    notes = [m for (m,) in db.execute("SELECT message FROM run_event WHERE kind = 'note' ORDER BY id DESC LIMIT 6")]
    assert notes == ["applied migration 22", "applied migration 21", "applied migration 20", "applied migration 19",
                     "applied migration 18", "applied migration 17"]
    for t in ("review_company", "review_auditor"):
        assert db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
        cols = "claim_version_id, contributor_version_id, capacity, scope, reviewed_on, conclusion, outcome, created_at"
        good = "1, 1, 'c', 's', '2024-01-01', 'x', 'accepted', 't'"
        for bad in (f"INSERT INTO {t} ({cols}) VALUES ({good})",  # neither evidence document nor note
                    f"INSERT INTO {t} ({cols}, evidence_note, evidence_page) VALUES ({good}, 'n', 2)",
                    f"INSERT INTO {t} ({cols}, evidence_note) VALUES ({good.replace('accepted', 'verified')}, 'n')"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(bad)
        db.execute(f"INSERT INTO {t} ({cols}, evidence_note) VALUES ({good}, 'n')")
        for stmt in (f"UPDATE {t} SET outcome = outcome", f"DELETE FROM {t}"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
                db.execute(stmt)
    db.close()


# AC 2, matrix columns "spreadsheet claim" and "evidence doc of another company"
def test_a_record_writes_one_row_with_every_field_in_its_own_table(ws, db, gct, make_file, one):
    doc, claim, version = one
    gct("company", "add", "Beta")
    beta = gct("doc", "add", make_file("beta.pdf", make_pdf([{}, {}])), "--company", "Beta", "--json")
    beta = beta.data["items"][0]["document"]["id"]
    conclusion = "  We have verified   the figure against the meter log.  "
    r = rec(gct, "company", claim, version, "accepted", "--evidence-doc", beta, "--evidence-page", 2, "--date",
            "2025-06-30", "--json", conclusion=conclusion,
            evidence=("--evidence-note", "meter log, sheet Plant 2, cell C7"))
    assert r.code == 0, r.err
    (row,) = rows(db, "review_company")
    assert rows(db, "review_auditor") == []
    assert {k: row[k] for k in row if k not in ("id", "created_at")} == {
        "claim_version_id": version, "contributor_version_id": 1, "capacity": "head of sustainability",
        "scope": "Scope 1, FY 2024-25", "reviewed_on": "2025-06-30", "conclusion": conclusion, "outcome": "accepted",
        "evidence_document_id": beta, "evidence_page": 2, "evidence_note": "meter log, sheet Plant 2, cell C7"}
    e = r.data["entry"]
    assert r.data["claim"] == {"id": claim, "document": doc, "company": "Acme", "version": version}
    assert (e["contributor"], e["organisation"], e["conclusion"], e["evidence_company"], e["evidence_state"]) == (
        "Ana", "Acme audit", conclusion, "Beta", "registered")
    text = rec(gct, "auditor", claim, version, "accepted", "--evidence-doc", beta, conclusion=conclusion).out
    assert "company Acme" in text and "by Ana (Acme audit)" in text and f'"{conclusion}"' in text
    assert "(Beta)" in text and text.count(SELF) == 1
    assert len(rows(db, "review_company")) == 1 and len(rows(db, "review_auditor")) == 1
    # A spreadsheet claim is recordable while current; its evidence is a note, never a page.
    sheet = gct("doc", "add", make_file("m.csv", csv_bytes(ROWS)), "--company", "Acme", "--kind", "evidence", "--json")
    sheet = sheet.data["items"][0]["document"]["id"]
    name = gct("sheet", "show", sheet, "--json").data["sheets"][0]["name"]
    assert gct("sheet", "map", sheet, "--sheet", name, *MAP, "--as", "ana", "--capacity", "a", "--rationale", "r").code == 0
    assert gct("extract", sheet).code == 0
    cell = gct("claims", "list", "--doc", sheet, "--json").data["claims"][0]["id"]
    assert rec(gct, "auditor", cell, newest(gct, cell)).code == 0
    refused = rec(gct, "auditor", cell, newest(gct, cell), "accepted", "--evidence-doc", sheet, "--evidence-page", 1)
    assert refused.code == 4 and "A spreadsheet has no pages; give the sheet and cell with --evidence-note." in refused.err


def refusal_cases(gct, db, make_file, one) -> list[tuple]:
    """(argv, exit code) for every refusal of AC 3, on a workspace prepared for them."""
    doc, claim, version = one
    other = add(gct, make_file, "b.pdf", [SCOPE_1[:3]])
    gone = add(gct, make_file, "c.pdf", [["Total Scope 2 emissions", "tCO2e", "77", "70"]])
    sheet = gct("doc", "add", make_file("m.csv", csv_bytes(ROWS)), "--company", "Acme", "--kind", "evidence", "--json")
    sheet = sheet.data["items"][0]["document"]["id"]
    assert gct("read").code == 0 and gct("extract").code == 0
    gone_claim = gct("claims", "list", "--doc", gone, "--json").data["claims"][0]["id"]
    other_claim = gct("claims", "list", "--doc", other, "--json").data["claims"][0]["id"]
    who = ("--as", "ana", "--capacity", "c", "--rationale", "r")
    assert gct("doc", "archive", other, *who).code == 0
    assert gct("doc", "delete", gone, "--confirm", token(db, gone), *who).code == 0

    def r(*extra, c=claim, v=version, outcome="accepted", evidence=NOTE, **kw):
        return ["review", "company", c, "--version", v, "--outcome", outcome, "--scope", kw.get("scope", "s"),
                "--conclusion", kw.get("conclusion", "x"), "--as", kw.get("who", "ana"),
                "--capacity", kw.get("capacity", "c"), *evidence, *extra]

    return [(r(c=99), 3), (r(who="nobody"), 3), (r(evidence=("--evidence-doc", 99)), 3),
            (r(c=other_claim, v=newest(gct, other_claim)), 4), (r(c=gone_claim, v=newest(gct, gone_claim)), 4),
            (r(v=99), 4), (r(capacity=" "), 2), (r(scope=""), 2), (r(conclusion="  "), 2), (r(outcome="verified"), 2),
            (r("--date", "2025-13-01"), 2), (r("--date", "30-06-2025"), 2), (r("--date", "2999-01-01"), 2),
            (r(evidence=()), 2), (r("--evidence-page", 1), 2),
            (r("--evidence-doc", doc, "--evidence-page", 9), 4), (r("--evidence-doc", doc, "--evidence-page", 0), 4),
            (r("--evidence-doc", sheet, "--evidence-page", 1), 4),
            (r(evidence=("--evidence-doc", other)), 4), (r(evidence=("--evidence-doc", gone)), 4)]


# AC 3
def test_every_refusal_writes_nothing_and_the_next_record_succeeds_once(ws, db, gct, make_file, one, monkeypatch):
    doc, claim, version = one
    cases = refusal_cases(gct, db, make_file, one)
    before = counts(db)
    for argv, code in cases:
        out = gct(*argv)
        assert out.code == code, (argv, out.err)
        assert out.err.startswith("error: ") and "\nnext: " in out.err, (argv, out.err)
        assert counts(db) == before, argv
    with monkeypatch.context() as m:  # the page read again with other rules: the claim is not current
        m.setattr(extract, "extract_config", lambda: "extract-other")
        out = rec(gct, "company", claim, version)
        assert out.code == 4 and "not yet extracted" in out.err and f"gct extract {doc}" in out.err
    assert counts(db) == before
    assert rec(gct, "company", claim, version).code == 0
    assert counts(db) == {**before, "review_company": 1}


# AC 4
def test_the_two_ledgers_are_independent(ws, db, gct, one):
    doc, claim, version = one
    assert rec(gct, "company", claim, version).code == 0
    assert rec(gct, "auditor", claim, version, "disputed", who="cara", conclusion="sample did not agree").code == 0
    auditor, shown = rows(db, "review_auditor"), listed(gct, claim)[version]["auditor_reviews"]
    assert rec(gct, "company", claim, version, "rejected", who="bob").code == 0
    assert rows(db, "review_auditor") == auditor and listed(gct, claim)[version]["auditor_reviews"] == shown
    v = listed(gct, claim)[version]
    assert [e["contributor"] for e in v["company_confirmations"]] == ["Ana", "Bob"] and len(v["auditor_reviews"]) == 1
    h = gct("claims", "history", claim, "--json").data["versions"][-1]
    assert (h["company_confirmations"], h["auditor_reviews"]) == (v["company_confirmations"], v["auditor_reviews"])
    text = gct("review", "list", claim).out
    assert "company confirmations:" in text and "auditor reviews:" in text


# AC 5, matrix column "contributor edited later"
def test_every_outcome_is_kept_and_only_the_newest_per_contributor_is_latest(ws, db, gct, one):
    doc, claim, version = one
    for outcome in ("accepted", "disputed", "rejected"):
        assert rec(gct, "company", claim, version, outcome).code == 0
    before = rows(db, "review_company")
    assert gct("contributor", "edit", "ana", "--name", "Ana Rao").code == 0
    assert rec(gct, "auditor", claim, version, who="cara").code == 0
    assert rows(db, "review_company") == before
    es = listed(gct, claim)[version]["company_confirmations"]
    assert [(e["outcome"], e["latest"], e["contributor"]) for e in es] == [
        ("accepted", False, "Ana"), ("disputed", False, "Ana"), ("rejected", True, "Ana")]
    assert rec(gct, "company", claim, version, "accepted").out.count("by Ana Rao (Acme audit)") == 1
    assert [e["latest"] for e in listed(gct, claim)[version]["company_confirmations"]] == [False, False, False, True]


# AC 6
def test_a_disagreement_is_computed_between_the_ledgers_only(ws, db, gct, one):
    doc, claim, version = one
    assert rec(gct, "company", claim, version).code == 0
    assert rec(gct, "company", claim, version, "rejected", who="bob").code == 0  # a split inside one ledger
    assert listed(gct, claim)[version]["disagreement"] is None
    assert rec(gct, "auditor", claim, version, "accepted", who="cara").code == 0
    assert rec(gct, "auditor", claim, version, "rejected", who="dev").code == 0
    assert listed(gct, claim)[version]["disagreement"] is None  # equal positions
    assert rec(gct, "auditor", claim, version, "disputed", who="dev").code == 0
    assert listed(gct, claim)[version]["disagreement"] == {"company": ["accepted", "rejected"],
                                                           "auditor": ["accepted", "disputed"]}
    assert (f"company confirmation and auditor review disagree on version {version}: company accepted, rejected;"
            " auditor accepted, disputed") in gct("review", "list", claim).out
    assert gct("correct", claim, "--value", "1,235", "--as", "ana", "--capacity", "c", "--rationale", "r").code == 0
    vs = listed(gct, claim)
    new = max(vs)
    assert vs[version]["disagreement"] == {"company": ["accepted", "rejected"], "auditor": ["accepted", "disputed"]}
    assert vs[new]["disagreement"] is None and vs[new]["company_confirmations"] == vs[new]["auditor_reviews"] == []
    h = {v["id"]: v for v in gct("claims", "history", claim, "--json").data["versions"]}
    assert h[version]["disagreement"] == vs[version]["disagreement"] and h[new]["disagreement"] is None


# AC 7, matrix column "older (non-newest) version"
def test_entries_bind_only_on_the_newest_version(ws, db, gct, one):
    doc, claim, version = one
    assert rec(gct, "company", claim, version).code == 0
    assert all(e["binds"] for e in listed(gct, claim)[version]["company_confirmations"])
    assert gct("correct", claim, "--value", "1,235", "--as", "ana", "--capacity", "c", "--rationale", "r").code == 0
    new = newest(gct, claim)
    old = rec(gct, "auditor", claim, version)
    assert old.code == 4 and f"newest is {new}" in old.err and f"gct claims history {claim}" in old.err
    assert rec(gct, "auditor", claim, new).code == 0
    vs = listed(gct, claim)
    assert [e["binds"] for e in vs[version]["company_confirmations"]] == [False]
    assert [e["binds"] for e in vs[new]["auditor_reviews"]] == [True]
    assert [(v["id"], v["binds"]) for v in vs.values()] == [(version, False), (new, True)]
    assert "(on an earlier version)" in gct("review", "list", claim).out


# AC 8
def test_gct_never_certifies_and_says_so_once(ws, db, gct, one):
    doc, claim, version = one
    typed = ["Scope 1 assured scope", "We verified and certified it as compliant", "lead assurer", "verified on site"]
    r = rec(gct, "auditor", claim, version, "accepted", "--json", scope=typed[0], conclusion=typed[1],
            capacity=typed[2], evidence=("--evidence-note", typed[3]))
    entries = [r.data["entry"]]
    outs = [rec(gct, "company", claim, version, scope=typed[0], conclusion=typed[1], capacity=typed[2],
                evidence=("--evidence-note", typed[3])).out,
            gct("review", "list", claim).out, gct("claims", "history", claim).out]
    data = [gct("review", "list", claim, "--json").data, gct("claims", "history", claim, "--json").data]
    for out in outs:
        assert out.count(SELF) == 1, out
        for t in typed:
            out = out.replace(t, "")
        assert not WORDS.search(out), out
    for d in data:
        v = d["versions"][-1]
        entries += v["company_confirmations"] + v["auditor_reviews"]

    def keys(x):
        if isinstance(x, dict):
            return [k for k in x] + [k for v in x.values() for k in keys(v)]
        return [k for v in x for k in keys(v)] if isinstance(x, list) else []

    assert not [k for d in data for k in keys(d) if WORDS.search(k)]
    assert len(entries) == 5 and all(e["self_declared"] is True for e in entries)


# AC 9
def test_adding_and_processing_evidence_writes_no_ledger_row(ws, db, gct, make_file, acme):  # noqa: F811
    add(gct, make_file, "a.pdf", [SCOPE_1])
    sheet = gct("doc", "add", make_file("m.csv", csv_bytes(ROWS)), "--company", "Acme", "--kind", "evidence", "--json")
    sheet = sheet.data["items"][0]["document"]["id"]
    name = gct("sheet", "show", sheet, "--json").data["sheets"][0]["name"]
    assert gct("sheet", "map", sheet, "--sheet", name, *MAP, "--as", "ana", "--capacity", "a", "--rationale", "r").code == 0
    for step in ("read", "extract", "link", "infer", "match"):
        assert gct(step).code == 0, step
    assert db.execute("SELECT COUNT(*) FROM claim").fetchone()[0] > 0
    assert rows(db, "review_company") == rows(db, "review_auditor") == []


# AC 10: the review-records gate (labelled test entries)
def test_review_records_gate(ws, db, gct, one):
    doc, claim, version = one
    for ledger, outcome, who, conclusion in (("company", "accepted", "ana", "matches the ledger"),
                                             ("company", "disputed", "ana", "boundary differs from ours"),
                                             ("company", "rejected", "bob", "not our figure"),
                                             ("auditor", "accepted", "cara", "verified against invoices"),
                                             ("auditor", "disputed", "dev", "sample did not agree")):
        assert rec(gct, ledger, claim, version, outcome, who=who, conclusion=conclusion).code == 0
    before = rows(db, "review_company") + rows(db, "review_auditor")
    v = listed(gct, claim)[version]
    company, auditor = v["company_confirmations"], v["auditor_reviews"]
    assert [(e["contributor"], e["organisation"], e["outcome"], e["latest"]) for e in company] == [
        ("Ana", "Acme audit", "accepted", False), ("Ana", "Acme audit", "disputed", True),
        ("Bob", "Acme Ltd", "rejected", True)]
    assert [(e["contributor"], e["organisation"], e["outcome"], e["conclusion"], e["latest"]) for e in auditor] == [
        ("Cara", "Audit LLP", "accepted", "verified against invoices", True), ("Dev", None, "disputed",
                                                                               "sample did not agree", True)]
    assert v["disagreement"] == {"company": ["rejected", "disputed"], "auditor": ["accepted", "disputed"]}
    assert all(e["self_declared"] and e["ledger"] == "company" for e in company)
    assert all(e["ledger"] == "auditor" for e in auditor)
    gct("review", "list", claim)
    gct("claims", "history", claim)
    assert gct("correct", claim, "--value", "1,235", "--as", "ana", "--capacity", "c", "--rationale", "r").code == 0
    assert rows(db, "review_company") + rows(db, "review_auditor") == before


# AC 11, matrix columns "claim doc archived" and "evidence doc archived after recording"
def test_archive_hides_the_entries_and_restore_brings_them_back(ws, db, gct, make_file, one):
    doc, claim, version = one
    other = add(gct, make_file, "b.pdf", [["Total Scope 2 emissions", "tCO2e", "77", "70"]])
    assert gct("read").code == 0 and gct("extract").code == 0
    cited = gct("claims", "list", "--doc", other, "--json").data["claims"][0]["id"]
    assert rec(gct, "company", claim, version).code == 0
    assert rec(gct, "auditor", claim, version, who="cara").code == 0
    assert rec(gct, "company", cited, newest(gct, cited), "accepted", "--evidence-doc", doc, "--evidence-page", 1).code == 0
    stored = rows(db, "review_company") + rows(db, "review_auditor")
    who = ("--as", "ana", "--capacity", "c", "--rationale", "r")
    plan = gct("doc", "archive", doc, "--plan", "--json").data["impact"]["review_records"]
    assert (plan["review_company"], plan["review_auditor"]) == (1, 1)
    assert "1 company confirmations, 1 auditor reviews" in gct("doc", "archive", doc, "--plan").out
    assert gct("doc", "archive", doc, *who).code == 0
    v = gct("publish", "build", "--json").data["version"]
    conn = published.open_version(ws / "published" / f"v{v}.db")
    hidden = conn.execute("SELECT review_records FROM hidden_by_archive WHERE document_id = ?", (doc,)).fetchone()[0]
    company = [dict(r) for r in conn.execute("SELECT * FROM review_company")]
    auditor = conn.execute("SELECT COUNT(*) FROM review_auditor").fetchone()[0]
    conn.close()
    assert hidden == sum(plan.values()) and hidden >= 2 and auditor == 0
    assert [(r["claim_id"], r["evidence_state"]) for r in company] == [(cited, "archived")]  # cites the archived one
    (e,) = listed(gct, cited)[newest(gct, cited)]["company_confirmations"]
    assert e["evidence_state"] == "archived" and "archived" in gct("review", "list", cited).out
    assert len(listed(gct, claim)[version]["company_confirmations"]) == 1  # still listed, document archived
    assert rec(gct, "auditor", claim, version).code == 4
    assert rec(gct, "auditor", cited, newest(gct, cited), evidence=("--evidence-doc", doc)).code == 4
    assert gct("doc", "restore", doc, *who).code == 0
    assert rows(db, "review_company") + rows(db, "review_auditor") == stored
    assert len(projected(ws, gct, "review_company")) == 2 and len(projected(ws, gct, "review_auditor")) == 1


# AC 12 (on AC 9's synthetic deletion layout of story 4.5)
D_CANARIES = ("zqdscope", "zqdconcl", "zqdcap", "zqdnote")
A_CANARIES = ("zqascope", "zqaconcl", "zqacap", "zqanote")


def test_deletion_clears_the_entries_text_and_keeps_the_rows(ws, db, gct, world):
    d, claim, other = world["d"], world["claim"], world["other"]
    gct("contributor", "add", "cara", "--name", "Cara", "--organisation", "Audit LLP")
    dv, av = newest(gct, claim), newest(gct, other)
    s, c, cap, n = D_CANARIES
    assert rec(gct, "company", claim, dv, "accepted", scope=s, conclusion=c, capacity=cap,
               evidence=("--evidence-note", n)).code == 0
    s, c, cap, n = A_CANARIES
    assert rec(gct, "auditor", other, av, "disputed", "--evidence-doc", d, "--evidence-page", 1, who="cara", scope=s,
               conclusion=c, capacity=cap, evidence=("--evidence-note", n)).code == 0
    assert rec(gct, "company", other, av, "rejected").code == 0  # the surviving claim's other entry
    for _ in range(2):  # both retained versions hold the three entries
        assert gct("publish", "build").code == 0
    keep = rows(db, "review_company")[1]
    assert scan(ws, canaries=D_CANARIES + A_CANARIES) == set(D_CANARIES + A_CANARIES)
    retained = sorted((ws / "published").glob("v*.db"))
    assert len(retained) == 2
    r = gct("doc", "delete", d, "--confirm", token(db, d), *DELETE_WHO)
    assert r.code == 0, r.err
    assert scan(ws, canaries=D_CANARIES + A_CANARIES) == set()
    marker = f"cleared with document {d}"
    (dc, ac), (aud,) = rows(db, "review_company"), rows(db, "review_auditor")
    assert ac == keep
    for row, outcome in ((dc, "accepted"), (aud, "disputed")):
        assert (row["capacity"], row["scope"], row["conclusion"], row["evidence_note"]) == (marker,) * 4
        assert row["outcome"] == outcome and row["reviewed_on"] and row["contributor_version_id"]
    assert (aud["evidence_document_id"], aud["evidence_page"]) == (d, 1)
    at = db.execute("SELECT at FROM document_state WHERE document_id = ? AND state = 'deleted'", (d,)).fetchone()[0]
    for cl, v, kind in ((claim, dv, "company_confirmations"), (other, av, "auditor_reviews")):
        (e,) = listed(gct, cl)[v][kind]
        assert e["evidence_deleted"] == {"document": d, "at": at} and e["conclusion"] == marker
        assert f"evidence deleted (document {d}, {at[:10]})" in gct("review", "list", cl).out
    for path in retained:
        conn = published.open_version(path)
        try:
            assert [r[0] for r in conn.execute("SELECT id FROM review_company")] == [keep["id"]]
            assert conn.execute("SELECT COUNT(*) FROM review_auditor").fetchone()[0] == 0
        finally:
            conn.close()
    (p,) = projected(ws, gct, "review_auditor")
    assert (p["claim_id"], p["conclusion"], p["capacity"], p["evidence_state"]) == (other, marker, marker, "deleted")
    assert [r["id"] for r in projected(ws, gct, "review_company")] == [keep["id"]]


# AC 13
def test_projection_schema_11(ws, db, gct, make_file, one):
    doc, claim, version = one
    mark = published.history_mark(db)
    assert rec(gct, "company", claim, version, "accepted", "--evidence-doc", doc, "--evidence-page", 1).code == 0
    assert published.history_mark(db) != mark
    mark = published.history_mark(db)
    assert rec(gct, "auditor", claim, version, who="cara").code == 0
    assert published.history_mark(db) != mark
    v = gct("publish", "build", "--json").data["version"]
    conn = published.open_version(ws / "published" / f"v{v}.db")
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        (c,) = [dict(r) for r in conn.execute("SELECT * FROM review_company")]
        (a,) = [dict(r) for r in conn.execute("SELECT * FROM review_auditor")]
    finally:
        conn.close()
    assert meta["projection_schema"] == "16"
    assert list(c) == list(a) == ["id", "claim_id", "claim_version_id", "contributor_name", "contributor_organisation",
                                  "contributor_version", "capacity", "scope", "reviewed_on", "conclusion", "outcome",
                                  "evidence_document_id", "evidence_page", "evidence_note", "evidence_state", "latest",
                                  "binds", "created_at"]
    assert (c["claim_id"], c["claim_version_id"], c["contributor_name"], c["evidence_document_id"], c["evidence_page"],
            c["evidence_state"], c["latest"], c["binds"]) == (claim, version, "Ana", doc, 1, "registered", 1, 1)
    assert (a["contributor_name"], a["contributor_organisation"], a["evidence_document_id"], a["evidence_note"]) == (
        "Cara", "Audit LLP", None, NOTE[1])
