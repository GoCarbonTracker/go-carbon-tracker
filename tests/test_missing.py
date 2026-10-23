import json
import shutil
import sqlite3
from collections import Counter

import pdfplumber
import pytest

from conftest import PDF, grid, make_pdf
from old_code import NOW, old_tree, run_old  # noqa: F401 (old_tree is a fixture)
from test_extract import PAGE
from test_link import add_reading
from test_resume import FIVE, failing
from gct.stages import extract, missing, read
from gct.workspace import layout, published, registry, store

OTHER = make_pdf([{"text": [(72, 300, "Water withdrawn 120 kL")]}])
WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "looked at the page")


@pytest.fixture
def docs(ws, gct, make_file):
    """Document 1 is the 3.1 fixture page, document 2 a one-line page; both read and extracted, one contributor."""
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("r.pdf", make_pdf([PAGE])), "--company", "Acme")
    gct("doc", "add", make_file("o.pdf", OTHER), "--company", "Acme")
    gct("read")
    gct("extract")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")


def expect(gct, *argv):
    r = gct("expect", "add", "--company", "Acme", *argv, "--json")
    assert r.code == 0, r.err
    return r.data["expectation"]


def listed(gct, item):
    return next(e for e in gct("expect", "list", "--json").data["expectations"] if e["id"] == item)


# AC 10
def test_migration_9_applies_to_a_version_8_workspace(tmp_path, gct):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    assert store.migrate(c, up_to=8) == [1, 2, 3, 4, 5, 6, 7, 8]
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.close()
    assert gct("contributor", "list", "--workspace", root).code == 0
    c = store.connect(root / layout.DB_NAME)
    assert c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 21
    c.close()


def test_bad_content_type_is_rejected(db, docs, gct):
    gct("pages", "accept", "--doc", 1, "--pages", "1", "--type", "figures", *WHO)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO page_acceptance (document_id, page_number, content_type, artifact_id, contributor_version_id,"
                   " capacity, rationale, created_at) VALUES (1, 1, 'charts', 1, 1, 'c', 'r', 't')")


# AC 11
def test_an_edit_adds_a_version_and_old_records_keep_theirs(db, docs, gct):
    item = expect(gct, "--metric", "water withdrawal", "--doc", 1)["id"]
    assert gct("pages", "accept", "--doc", 1, "--pages", "1", "--type", "figures", *WHO).code == 0
    r = gct("contributor", "edit", "ana", "--name", "Ana Rao", "--json")
    assert (r.data["contributor"]["name"], r.data["contributor"]["organisation"], r.data["contributor"]["version"]) == (
        "Ana Rao", "Acme audit", 2)
    assert [c["name"] for c in gct("contributor", "list", "--json").data["contributors"]] == ["Ana Rao"]
    assert db.execute("SELECT COUNT(*) FROM contributor_version WHERE contributor_key = 'ana'").fetchone()[0] == 2
    assert listed(gct, item)["accepted"] == [{"type": "figures", "accepted": "accepted by Ana (analyst)", "count": 1}]


def test_attribution_needs_a_known_key_every_time(docs, gct):
    r = gct("pages", "accept", "--doc", 1, "--pages", "1", "--type", "figures", "--as", "bob", "--capacity", "c",
            "--rationale", "r")
    assert r.code == 3 and "gct contributor add bob" in r.err
    assert gct("pages", "accept", "--doc", 1, "--pages", "1", "--type", "figures", "--capacity", "c",
               "--rationale", "r").code == 2  # no --as: usage error, nothing prefilled
    assert gct("contributor", "add", "ana", "--name", "Other").code == 4


# AC 12
def test_an_expectation_is_found_by_its_wording_and_period(docs, gct):
    e = expect(gct, "--metric", "  scope 1   EMISSIONS ", "--period", "FY2023-24")
    assert (e["metric_text"], e["found"], e["state"], e["documents"]) == ("scope 1 EMISSIONS", True, None, [1, 2])
    (claim,) = e["claims"]
    assert (claim["value_text"], claim["period_label"]) == ("1,234.5", "FY2023-24")
    assert "found: 1 claims" in gct("expect", "list").out


# AC 13
def test_a_page_that_cannot_be_read_keeps_the_item_incomplete(db, gct, make_file, monkeypatch):
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("five.pdf", FIVE), "--company", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    failing(monkeypatch, {3})
    assert gct("read").code == 4
    run = db.execute("SELECT MAX(id) FROM run").fetchone()[0]
    assert gct("run", "retry", run).code == 4  # still failing
    e = expect(gct, "--metric", "scope 1 emissions")
    assert e["state"] == missing.INCOMPLETE
    assert {"type": "text", "reason": "read failed", "count": 1} in e["reasons"]
    attempts = db.execute("SELECT outcome FROM attempt WHERE stage = 'read' AND item = '1:3'").fetchall()
    assert [a[0] for a in attempts] == ["failed", "failed"]
    r = gct("pages", "accept", "--doc", 1, "--pages", "3", "--type", "figures", *WHO)
    assert r.code == 4 and f"gct run retry {run + 1}" in r.err
    assert gct("pages", "accept", "--doc", 1, "--pages", "1-2", "--type", "text", *WHO).code == 4  # already checked


# AC 14, 15, 15b, 16, 17
def test_the_three_states(ws, db, docs, gct):
    a = expect(gct, "--metric", "water withdrawal", "--doc", 1)["id"]
    b = expect(gct, "--metric", "water withdrawal", "--doc", 2)["id"]
    e = listed(gct, a)
    assert (e["found"], e["state"], e["reasons"]) == (
        False, missing.INCOMPLETE, [{"type": "figures", "reason": "charts not read", "count": 1}])
    assert "  figures: 1 pages, charts not read" in gct("expect", "list").out
    # AC 16 (refusal): an extraction gap is never confirmed as a disclosure gap
    r = gct("gap", "confirm", b, *WHO)
    assert r.code == 4 and "incomplete for figures" in r.err
    # AC 15
    assert gct("pages", "accept", "--doc", 1, "--pages", "1", "--type", "figures", *WHO).code == 0
    e = listed(gct, a)
    assert (e["state"], e["reasons"]) == (missing.NOT_FOUND_IN, [])
    assert e["accepted"] == [{"type": "figures", "accepted": "accepted by Ana (analyst)", "count": 1}]
    assert "  figures: 1 pages accepted by Ana (analyst)" in gct("expect", "list").out
    c = expect(gct, "--metric", "energy intensity", "--doc", 1)["id"]  # stays in state 2 for AC 17
    # AC 16
    r = gct("gap", "confirm", a, *WHO, "--json")
    assert r.code == 0 and r.data["expectation"]["state"] == missing.CONFIRMED
    gap = db.execute("SELECT * FROM gap_confirmation").fetchone()
    assert (gap["contributor_version_id"], gap["capacity"], gap["rationale"]) == (1, "analyst", "looked at the page")
    (checked,) = json.loads(gap["documents_checked"])
    assert checked["id"] == 1 and len(checked["sha256"]) == 64 and checked["artifacts"] == [
        db.execute("SELECT artifact_id FROM page WHERE document_id = 1 ORDER BY id DESC").fetchone()[0]]
    # AC 17
    v = gct("publish", "build", "--json").data
    conn = published.open_version(ws / "published" / f"v{v['version']}.db")
    states = dict(conn.execute("SELECT id, state FROM expected_item"))
    gaps = [tuple(r) for r in conn.execute("SELECT expected_item_id, contributor_name, contributor_organisation, capacity,"
                                           " current FROM gap_confirmation")]
    acc = [tuple(r) for r in conn.execute("SELECT document_id, page_number, content_type, contributor_name, current"
                                          " FROM page_acceptance")]
    docs_of = [tuple(r) for r in conn.execute("SELECT * FROM expected_item_document ORDER BY expected_item_id")]
    conn.close()
    assert states == {a: missing.CONFIRMED, b: missing.INCOMPLETE, c: missing.NOT_FOUND_IN}
    assert len(set(states.values())) == 3
    assert gaps == [(a, "Ana", "Acme audit", "analyst", 1)] and acc == [(1, 1, "figures", "Ana", 1)]
    assert docs_of == [(a, 1, "registered"), (b, 2, "registered"), (c, 1, "registered")]
    # AC 15b: a new reading of the page supersedes its acceptance and the confirmation made on the old one
    add_reading(ws, db, 1, lambda r: None)
    e = listed(gct, a)
    assert e["state"] == missing.INCOMPLETE
    assert {"type": "figures", "reason": "accepted on an earlier reading", "count": 1} in e["reasons"]
    assert {"type": "confirmation", "reason": f"earlier gap confirmation #{gap['id']} was made on older readings",
            "count": 1} in e["reasons"]
    assert e["confirmation"]["current"] is False
    assert "made on older readings, not current" in gct("expect", "list").out
    assert db.execute("SELECT COUNT(*) FROM gap_confirmation").fetchone()[0] == 1
    v = gct("publish", "build", "--json").data
    conn = published.open_version(ws / "published" / f"v{v['version']}.db")
    assert [tuple(r) for r in conn.execute("SELECT current FROM page_acceptance")] == [(0,)]  # F6: the reading it accepted is gone
    conn.close()


def test_a_confirmation_that_no_longer_holds(ws, db, docs, gct):
    a = expect(gct, "--metric", "water withdrawal", "--doc", 1)["id"]
    gct("pages", "accept", "--doc", 1, "--pages", "1", "--type", "figures", *WHO)
    r = gct("gap", "confirm", a, *WHO)
    assert r.code == 0 and 'GCT looked only for the exact wording "water withdrawal" on the pages.' in r.out
    gct("publish", "build")
    # The same readings, then a failed re-read of page 1: the state changes without a new page row (F3, F4)
    db.execute("INSERT INTO attempt (run_id, stage, item, input_version, config_version, outcome, at)"
               " VALUES (1, 'read', '1:1', 'x', 'x', 'failed', 't')")
    db.commit()
    assert gct("publish", "status", "--json").data["stale"] is True
    e = listed(gct, a)
    assert e["state"] == missing.INCOMPLETE and e["confirmation"]["current"] is False
    assert {"type": "confirmation", "count": 1,
            "reason": "earlier gap confirmation #1 no longer holds: processing incomplete"} in e["reasons"]
    # A claim that carries the wording makes the item found; the confirmation is still shown, not current (F5)
    claim = db.execute("INSERT INTO claim (company_id, document_id, page_number, locator, created_at)"
                       " VALUES (1, 1, 1, 'h1', 't')").lastrowid
    version = db.execute("INSERT INTO claim_version (claim_id, run_id, method, config_version, metric_text, value_text,"
                         " created_at) VALUES (?, 1, 'hand', 'c', 'Water withdrawal', '7', 't')", (claim,)).lastrowid
    # Seen by the newest extraction of page 1, so the claim is current (story 3.5: only current claims count)
    page = db.execute("SELECT MAX(id) FROM page WHERE document_id = 1").fetchone()[0]
    db.execute("INSERT INTO claim_seen (claim_version_id, page_id, config_version, run_id, created_at)"
               " VALUES (?, ?, ?, 1, 't')", (version, page, extract.extract_config()))
    db.commit()
    e = listed(gct, a)
    assert (e["found"], e["state"], e["confirmation"]["id"], e["confirmation"]["current"]) == (True, None, 1, False)
    assert "gap confirmation #1 by Ana (analyst): the figure is found now, not current" in gct("expect", "list").out


# Decision U: wording printed beside a table whose rows have no label column is an extraction gap
def test_printed_wording_without_a_claim_is_not_a_gap(ws, gct, make_file):
    page = grid(72, 120, [80, 80], [20, 20], [["FY2023-24", "FY2022-23"], ["1,234.5", "1,100"]])
    page["text"].append((72, 100, "Scope 1 emissions (tCO2e)"))
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("u.pdf", make_pdf([page])), "--company", "Acme")
    gct("read")
    gct("extract")
    gct("contributor", "add", "ana", "--name", "Ana")
    item = expect(gct, "--metric", "scope 1   EMISSIONS")["id"]
    accepted = [gct("pages", "accept", "--doc", 1, "--pages", "1", "--type", t, *WHO) for t in missing.TYPES]
    # Accepting does not say it clears anything: the figures acceptance reads as an acceptance only
    assert accepted[2].out.strip() == "Document 1, figures: pages 1 accepted by Ana (analyst). This is an acceptance, not a check."
    e = listed(gct, item)
    assert (e["found"], e["state"]) == (False, missing.INCOMPLETE)
    assert e["reasons"] == [{"type": "text", "reason": "wording printed but no figure extracted", "count": 1,
                             "pages": ["1:1"]}]
    out = gct("expect", "list").out
    assert "  text: 1 pages, wording printed but no figure extracted (1:1)" in out
    assert out.strip().endswith("Matching uses the literal wording, so the same figure under different wording can still"
                                " exist. A gap confirmation is the contributor's own judgment, not a conclusion GCT"
                                " draws from absent wording.")
    r = gct("gap", "confirm", item, *WHO)
    assert r.code == 4
    assert ("Expectation 1 cannot be confirmed as a gap: the wording is printed on document 1 page 1 but no figure"
            " carrying it was extracted, so this is an extraction gap, not a disclosure gap.") in r.err
    assert "Check those pages; a correction step comes in a later version." in r.err
    assert "Read, retry or accept" not in r.err


def test_printed_wording_with_figures_for_another_period(ws, gct, make_file):
    page = grid(72, 100, [160, 80], [20, 20], [["", "FY2022-23"], ["Scope 1 emissions (tCO2e)", "1,100"]])
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("p.pdf", make_pdf([page])), "--company", "Acme")
    gct("read")
    gct("extract")
    gct("contributor", "add", "ana", "--name", "Ana")
    item = expect(gct, "--metric", "Scope 1", "--period", "FY2023-24")["id"]
    for t in missing.TYPES:
        gct("pages", "accept", "--doc", 1, "--pages", "1", "--type", t, *WHO)
    e = listed(gct, item)
    assert (e["found"], e["state"]) == (False, missing.INCOMPLETE)
    assert e["reasons"] == [{"type": "text", "reason": "wording printed; figures found only for other or missing period"
                             " labels", "count": 1, "pages": ["1:1"]}]
    r = gct("gap", "confirm", item, *WHO)
    assert r.code == 4 and ("the wording is printed on document 1 page 1, but the figures found there carry a period"
                            " label other than FY2023-24, or none.") in r.err
    assert "Check those pages; a correction step comes in a later version." in r.err


# Q19 (F7): an interrupted read leaves later pages with no attempt; they count as not read
def test_an_interrupted_read_leaves_pages_not_read(db, gct, make_file, monkeypatch):
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("five.pdf", FIVE), "--company", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    real = failing(monkeypatch, {3}, KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        gct("read")
    monkeypatch.setattr(read, "read_page", real)
    assert [r[0] for r in db.execute("SELECT item FROM attempt WHERE stage = 'read' ORDER BY id")] == ["1:1", "1:2"]
    e = expect(gct, "--metric", "scope 1 emissions")
    assert e["state"] == missing.INCOMPLETE
    assert {"type": "figures", "reason": "not read", "count": 3} in e["reasons"]
    r = gct("pages", "accept", "--doc", 1, "--pages", "1-5", "--type", "figures", *WHO)
    assert r.code == 4 and "Page 3 has not been read" in r.err and "gct read 1" in r.err
    assert gct("gap", "confirm", e["id"], *WHO).code == 4


def test_a_document_without_a_page_set(ws, gct, make_file):
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("bad.pdf", PDF), "--company", "Acme")
    e = expect(gct, "--metric", "scope 1")
    assert (e["state"], e["reasons"]) == (missing.INCOMPLETE, [{"type": "document", "reason": "not opened", "count": 1}])


# Story 3.5 S2: only current claims count, so an expectation is never found through a claim the newest reading lost.
def test_a_claim_that_is_not_current_does_not_make_an_expectation_found(ws, db, docs, gct):
    def blank(reading):
        reading["words"], reading["text"] = [], ""

    item = expect(gct, "--metric", "water withdrawn", "--doc", 2)["id"]
    assert listed(gct, item)["found"] is True
    add_reading(ws, db, 2, blank)  # document 2's page holds only the water line
    for step in ("page read again, not yet extracted", "not found in the newest reading"):
        (claim,) = gct("claims", "list", "--doc", 2, "--json").data["claims"]
        assert claim["claim_state"] == step
        e = listed(gct, item)
        assert (e["found"], e["claims"]) == (False, []) and e["state"] is not None, e
        gct("extract")


# Story 7.1 part B: the published version's page limits, accepted entries by id, declared links and checked documents.
ONLY = "Quillon Acceptor"  # accepts pages only, so a name scan can tell where acceptances project it (B3)
BY_ONLY = ("--as", "only", "--capacity", "reviewer", "--rationale", "looked at the page")
METRIC = "scope 1 emissions"


def one_page(text: str) -> bytes:
    return make_pdf([{"text": [(72, 300, text)]}])


@pytest.fixture
def limits(ws, db, gct, make_file, monkeypatch):
    """Acme: 1 five pages (1 accepted on an earlier reading, 2 read then a failed re-read, 3 failed, 4 and 5 read), 2
    one clean page, 3 archived and 4 restored (each with an accepted page), all read; then 5 two pages never read, 6 a
    CSV and 7 a PDF that does not open. Beta: 8 holds document 2's file, never read. Expectations 1 over 2
    (confirmable), 2 over 1, 3, 4, 5, 6, 7, 3 (Beta) over 8, 4 over 2."""
    gct("company", "add", "Acme")
    gct("company", "add", "Beta")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")
    gct("contributor", "add", "only", "--name", ONLY)
    five = make_pdf([{"text": [(72, 300, f"Page {n} of the long report")]} for n in range(1, 6)])
    for name, data in (("m.pdf", five), ("c.pdf", one_page("Water withdrawn 120 kL")),
                       ("arch.pdf", one_page("Archived page")), ("rest.pdf", one_page("Restored page"))):
        assert gct("doc", "add", make_file(name, data), "--company", "Acme").code == 0
    failing(monkeypatch, {3})
    assert gct("read").code == 4
    for name, data in (("n.pdf", make_pdf([{"text": [(72, 300, "Never read")]}] * 2)),
                       ("s.csv", b"metric,value\nwater,5\n"), ("bad.pdf", PDF)):
        assert gct("doc", "add", make_file(name, data), "--company", "Acme").code == 0, name
    assert gct("doc", "add", make_file("c.pdf", one_page("Water withdrawn 120 kL")), "--company", "Beta").code == 0
    for doc, who in ((1, WHO), (2, WHO), (3, BY_ONLY), (4, BY_ONLY)):
        assert gct("pages", "accept", "--doc", doc, "--pages", "1", "--type", "figures", *who).code == 0
    add_reading(ws, db, 1, lambda r: None)  # page 1's acceptance is now on an earlier reading
    db.execute("INSERT INTO attempt (run_id, stage, item, input_version, config_version, outcome, at)"
               " VALUES (1, 'read', '1:2', 'x', 'x', 'failed', 't')")  # a failed re-read after a successful read
    db.commit()
    for argv in (("--doc", 2), ("--doc", 1, 3, 4, 5, 6, 7)):
        expect(gct, "--metric", METRIC, *argv)
    assert gct("expect", "add", "--company", "Beta", "--metric", METRIC, "--doc", 8).code == 0
    expect(gct, "--metric", "energy intensity", "--doc", 2)
    assert gct("doc", "archive", 3, *WHO).code == 0
    assert gct("doc", "archive", 4, *WHO).code == 0
    assert gct("doc", "restore", 4, *WHO).code == 0


# B9's commands: a multi-page accept, a new expectation, a gap confirmation, and the list before and after.
CHANGES = (("expect", "list", "--json"), ("pages", "accept", "--doc", 1, "--pages", "4-5", "--type", "figures", *BY_ONLY,
                                          "--json"),
           ("expect", "add", "--company", "Acme", "--metric", "water intensity", "--doc", 1, "--json"),
           ("gap", "confirm", 1, *WHO, "--json"), ("expect", "list", "--json"))


def acceptance(db, doc: int, page: int) -> dict:
    i = db.execute("SELECT id FROM page_acceptance WHERE document_id = ? AND page_number = ? ORDER BY id DESC LIMIT 1",
                   (doc, page)).fetchone()[0]
    return {"type": "figures", "acceptance_id": i, "count": 1}


# B1 to B5
def test_the_published_version_holds_page_limits_and_ids_only(ws, db, gct, limits, monkeypatch):
    for argv in CHANGES[1:4]:
        assert gct(*argv).code == 0
    opened, real = Counter(), pdfplumber.open
    monkeypatch.setattr(pdfplumber, "open", lambda path, *a, **k: opened.update([str(path)]) or real(path, *a, **k))
    assert gct("publish", "build").code == 0
    # Each stored PDF that is active is opened once, though four expectations and two companies read document 2's file
    assert len(opened) == 5 and set(opened.values()) == {1}
    conn = published.open_version(ws / "published" / "v1.db")
    pages = {(r["document_id"], r["page_number"]): dict(r) for r in conn.execute("SELECT * FROM page")}
    # B1: no rows for the archived document, the CSV or the PDF that does not open
    assert sorted(pages) == [(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (2, 1), (4, 1), (5, 1), (5, 2), (8, 1)]
    measured = ("rung", "method", "words", "tables", "flags", "width", "height")
    for (d, p), row in pages.items():
        expected = []
        for t in missing.TYPES:
            ready, note, acc = missing.page_ready(db, d, p, t)
            expected.append(f"accepted #{acc}" if acc is not None else None if ready else note)
        assert [row[f"limit_{t}"] for t in missing.TYPES] == expected, (d, p)
        assert "Ana" not in str(row) and ONLY not in str(row)
        newest = missing._newest_page(db, d, p)
        if row["read_state"] == "read":
            assert [row[k] for k in measured] == [newest[k] for k in measured]
        else:
            assert [row[k] for k in measured] == [None] * 7
    # B2: the reading states, a failed re-read after a success included (the workspace still has that reading)
    assert {k: r["read_state"] for k, r in pages.items()} == {
        (1, 1): "read", (1, 2): "read failed", (1, 3): "read failed", (1, 4): "read", (1, 5): "read", (2, 1): "read",
        (4, 1): "read", (5, 1): "not read", (5, 2): "not read", (8, 1): "not read"}
    assert missing._newest_page(db, 1, 2) is not None
    assert (pages[1, 1]["method"], pages[1, 1]["limit_figures"]) == ("later", missing.EARLIER)
    assert pages[1, 2]["limit_text"] == "read failed" and pages[5, 1]["limit_text"] == "not read"
    for doc, page in ((1, 4), (1, 5), (2, 1), (4, 1)):
        assert pages[doc, page]["limit_figures"] == f"accepted #{acceptance(db, doc, page)['acceptance_id']}"
    # B3: ids and counts only; the earlier-reading and the archived document's acceptances are not counted
    accepted = {i: json.loads(a) for i, a in conn.execute("SELECT id, accepted FROM expected_item")}
    assert accepted == {1: [acceptance(db, 2, 1)], 2: [acceptance(db, 1, 4), acceptance(db, 1, 5), acceptance(db, 4, 1)],
                        3: [], 4: [acceptance(db, 2, 1)], 5: [acceptance(db, 1, 4), acceptance(db, 1, 5)]}
    tables = [t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    assert {t for t in tables for r in conn.execute(f"SELECT * FROM {t}") if ONLY in str(tuple(r))} == {"page_acceptance"}
    # B4: every declared document not deleted, archived and restored ones with their state; each company its own
    assert [tuple(r) for r in conn.execute("SELECT * FROM expected_item_document")] == [
        (1, 2, "registered"), (2, 1, "registered"), (2, 3, "archived"), (2, 4, "restored"), (2, 5, "registered"),
        (2, 6, "registered"), (2, 7, "registered"), (3, 8, "registered"), (4, 2, "registered"), (5, 1, "registered")]
    # B5: the confirmation's documents and readings, without sha256
    (checked,) = conn.execute("SELECT documents_checked FROM gap_confirmation").fetchone()
    stored = db.execute("SELECT documents_checked FROM gap_confirmation").fetchone()[0]
    assert json.loads(checked) == [{"id": x["id"], "artifacts": x["artifacts"]} for x in json.loads(stored)]
    assert "sha256" not in checked and json.loads(checked)[0]["id"] == 2
    conn.close()


# Xiao's review probe files (fix round 2) on which a /Count shortcut differed from the walk, with the walk's answer.
ODD_PDFS = {
    "MediaBox_not_array": ((None, "not opened"), (
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R "
        b"4 0 R 5 0 R] /Count 3  >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>"
        b"\nendobj\n4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendobj\n5 0 obj\n<< /Ty"
        b"pe /Page /Parent 2 0 R /MediaBox 7 >>\nendobj\nxref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000058 00000 n \n0000000128 00000 n \n0000000200 00000 n \n0000000272 00000 n \ntrailer\n<< /Siz"
        b"e 6 /Root 1 0 R  >>\nstartxref\n331\n%%EOF\n"
    )),
    "bad_MediaBox": ((None, "not opened"), (
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R "
        b"4 0 R 5 0 R] /Count 3  >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>"
        b"\nendobj\n4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendobj\n5 0 obj\n<< /Ty"
        b"pe /Page /Parent 2 0 R /MediaBox [0 0 /a /b] >>\nendobj\nxref\n0 6\n0000000000 65535 f \n0000000009 "
        b"00000 n \n0000000058 00000 n \n0000000128 00000 n \n0000000200 00000 n \n0000000272 00000 n \ntraile"
        b"r\n<< /Size 6 /Root 1 0 R  >>\nstartxref\n341\n%%EOF\n"
    )),
    "count_1048575,_1_page": ((1, None), (
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R]"
        b" /Count 1048575  >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendo"
        b"bj\nxref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000122 00000 n \nt"
        b"railer\n<< /Size 4 /Root 1 0 R  >>\nstartxref\n194\n%%EOF\n"
    )),
    "count_too_large_(9_of_3)": ((3, None), (
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R "
        b"4 0 R 5 0 R] /Count 9  >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>"
        b"\nendobj\n4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendobj\n5 0 obj\n<< /Ty"
        b"pe /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendobj\nxref\n0 6\n0000000000 65535 f \n00000000"
        b"09 00000 n \n0000000058 00000 n \n0000000128 00000 n \n0000000200 00000 n \n0000000272 00000 n \ntra"
        b"iler\n<< /Size 6 /Root 1 0 R  >>\nstartxref\n344\n%%EOF\n"
    )),
    "count_too_small_(1_of_3)": ((3, None), (
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R "
        b"4 0 R 5 0 R] /Count 1  >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>"
        b"\nendobj\n4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendobj\n5 0 obj\n<< /Ty"
        b"pe /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendobj\nxref\n0 6\n0000000000 65535 f \n00000000"
        b"09 00000 n \n0000000058 00000 n \n0000000128 00000 n \n0000000200 00000 n \n0000000272 00000 n \ntra"
        b"iler\n<< /Size 6 /Root 1 0 R  >>\nstartxref\n344\n%%EOF\n"
    )),
    "cycle": ((0, None), (
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R]"
        b" /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\nxref\n0 4\n0000000"
        b"000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \ntrailer\n<< /Size 4 /Ro"
        b"ot 1 0 R  >>\nstartxref\n172\n%%EOF\n"
    )),
    "duplicate_kid": ((2, None), (
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R "
        b"3 0 R 4 0 R] /Count 3  >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>"
        b"\nendobj\n4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendobj\nxref\n0 5\n0000"
        b"000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000128 00000 n \n0000000200 00000 n "
        b"\ntrailer\n<< /Size 5 /Root 1 0 R  >>\nstartxref\n272\n%%EOF\n"
    )),
    "incremental_adds_page,_stale_count_2": ((3, None), (
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R "
        b"4 0 R] /Count 2  >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendo"
        b"bj\n4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendobj\nxref\n0 5\n0000000000"
        b" 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000122 00000 n \n0000000194 00000 n \ntrail"
        b"er\n<< /Size 5 /Root 1 0 R  >>\nstartxref\n266\n%%EOF\n2 0 obj\n<< /Type /Pages /Kids [3 0 R 4 0 R 5"
        b" 0 R] /Count 2 >>\nendobj\n5 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendobj"
        b"\nxref\n2 1\n0000000430 00000 n \n5 1\n0000000499 00000 n \ntrailer\n<< /Size 6 /Root 1 0 R /Prev 26"
        b"6 >>\nstartxref\n571\n%%EOF\n"
    )),
    "kid_is_array": ((2, None), (
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R "
        b"4 0 R 5 0 R] /Count 3  >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>"
        b"\nendobj\n4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendobj\n5 0 obj\n[1 2 3"
        b"]\nendobj\nxref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000128 0000"
        b"0 n \n0000000200 00000 n \n0000000272 00000 n \ntrailer\n<< /Size 6 /Root 1 0 R  >>\nstartxref\n295"
        b"\n%%EOF\n"
    )),
    "kid_missing_object": ((2, None), (
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R "
        b"4 0 R 9 0 R] /Count 3  >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>"
        b"\nendobj\n4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendobj\nxref\n0 5\n0000"
        b"000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000128 00000 n \n0000000200 00000 n "
        b"\ntrailer\n<< /Size 5 /Root 1 0 R  >>\nstartxref\n272\n%%EOF\n"
    )),
    "kid_without_Type": ((2, None), (
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R "
        b"4 0 R 5 0 R] /Count 3  >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>"
        b"\nendobj\n4 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]  >>\nendobj\n5 0 obj\n<< /Pa"
        b"rent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\nxref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n"
        b"0000000058 00000 n \n0000000128 00000 n \n0000000200 00000 n \n0000000272 00000 n \ntrailer\n<< /Siz"
        b"e 6 /Root 1 0 R  >>\nstartxref\n331\n%%EOF\n"
    )),
}


# Fix round 2: the page count is the read stage's own pdfplumber walk, whatever /Count says, or "not opened".
def test_the_page_count_is_the_read_stages_walk(tmp_path):
    def walk(path):
        try:
            with pdfplumber.open(path) as pdf:
                return len(pdf.pages), None
        except Exception:
            return None, "not opened"

    files = dict(ODD_PDFS)
    files |={"page": ((1, None), make_pdf([PAGE])), "five": ((5, None), FIVE), "no eof": ((5, None), FIVE[:-6]),
              "count 0": ((5, None), FIVE.replace(b"/Count 5", b"/Count 0")),
              "count 1": ((5, None), FIVE.replace(b"/Count 5", b"/Count 1"))}
    files |= {name: ((None, "not opened"), data) for name, data in (
        ("conftest PDF", PDF), ("broken", b"%PDF-1.4 broken"), ("truncated", FIVE[: len(FIVE) // 2]),
        ("xref damaged", FIVE.replace(b"xref", b"xrex")), ("csv", b"metric,value\nwater,5\n"), ("empty", b""))}
    for name, (expected, data) in files.items():
        path = registry.stored_path(tmp_path, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        assert missing.page_count(tmp_path, {"file_type": "pdf", "sha256": name}) == expected == walk(path), name


# Fix round 2 (AC16): a /Count smaller than the pages read never lets the unchecked pages be confirmed as a gap.
def test_a_wrong_page_count_in_the_file_does_not_confirm_a_gap(ws, gct, make_file):
    three = make_pdf([{"text": [(72, 300, f"Water withdrawn {n} kL")]} for n in (1, 2, 3)])
    gct("company", "add", "Acme")
    assert gct("doc", "add", make_file("c1.pdf", three.replace(b"/Count 3", b"/Count 1")), "--company", "Acme").code == 0
    gct("read")
    gct("contributor", "add", "ana", "--name", "Ana")
    item = expect(gct, "--metric", METRIC)["id"]
    assert gct("pages", "accept", "--doc", 1, "--pages", "1", "--type", "figures", *WHO).code == 0
    r = gct("gap", "confirm", item, *WHO)
    assert r.code == 4 and "processing is incomplete for figures" in r.err
    assert {"type": "figures", "reason": missing.CHARTS, "count": 2} in listed(gct, item)["reasons"]
    assert gct("publish", "build").code == 0
    conn = published.open_version(ws / "published" / "v1.db")
    assert [r[0] for r in conn.execute("SELECT read_state FROM page ORDER BY page_number")] == ["read"] * 3
    conn.close()


# B9 (R3): the CLI prints what the code before projection 15 printed, and a confirmation it stored stays current.
def test_outputs_and_stored_confirmations_of_the_older_code_are_unchanged(ws, db, gct, limits, old_tree, tmp_path,
                                                                         monkeypatch):
    twin = tmp_path / "twin"
    shutil.copytree(ws, twin)
    old = run_old(old_tree, twin, *CHANGES, now=NOW, newer=True)  # the workspace is at schema 21
    monkeypatch.setattr(store, "now", lambda: NOW)
    new = [gct(*argv) for argv in CHANGES]
    assert [n.code for n in new] == [0] * len(CHANGES)
    assert [(o["code"], o["out"], o["err"]) for o in old] == [(n.code, n.out, n.err) for n in new]
    reasons = {(r["type"], r["reason"], r["count"]) for e in new[0].data["expectations"] if e["id"] == 2
               for r in e["reasons"]}
    assert reasons == {("figures", missing.EARLIER, 1), ("figures", missing.CHARTS, 2), ("document", "not a PDF", 1),
                       ("document", "not opened", 1),
                       *((t, why, 2) for t in missing.TYPES for why in ("read failed", "not read"))}
    # The old shape still merges one line per name and capacity: pages 4 and 5 of document 1 and document 4's page
    assert next(e for e in new[-1].data["expectations"] if e["id"] == 2)["accepted"] == [
        {"type": "figures", "accepted": f"accepted by {ONLY} (reviewer)", "count": 3}]
    old_db = sqlite3.connect(twin / layout.DB_NAME)
    stored = "SELECT documents_checked FROM gap_confirmation"
    assert old_db.execute(stored).fetchall() == [tuple(r) for r in db.execute(stored)]
    old_db.close()
    (e,) = [e for e in gct("expect", "list", "--workspace", twin, "--json").data["expectations"] if e["id"] == 1]
    assert (e["state"], e["confirmation"]["current"]) == (missing.CONFIRMED, True)
