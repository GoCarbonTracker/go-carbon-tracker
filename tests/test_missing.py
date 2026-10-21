import json
import sqlite3

import pytest

from conftest import PDF, grid, make_pdf
from test_extract import PAGE
from test_link import add_reading
from test_resume import FIVE, failing
from gct.stages import extract, missing, read
from gct.workspace import layout, published, store

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
    assert c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 11
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
    assert docs_of == [(a, 1), (b, 2), (c, 1)]
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
