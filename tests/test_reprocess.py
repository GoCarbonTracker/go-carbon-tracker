"""Story 3.5: re-reading and re-extracting. Readings of one page are made by hand (see the story's Dev notes)."""
import json

from test_extract import count
from test_link import add_reading, doc  # noqa: F401  (doc is a fixture: read and extracted once)
from gct.stages import extract
from gct.workspace import published

ENERGY = "l0w2"  # "Energy consumed 4,560 MWh in 2023"
WATER = "l1w1"   # "Water 1,23,456 kL"
WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked on the page")


def word(reading, text):
    return next(w for w in reading["words"] if w["text"] == text)


def set_word(text, new):
    def change(reading):
        word(reading, text)["text"] = new
    return change


def move_line(text, dx):
    """Move the whole printed line holding the word: same line and word numbers, another place on the page."""
    def change(reading):
        top = word(reading, text)["top"]
        for w in reading["words"]:
            if w["top"] == top:
                w["x0"] += dx
                w["x1"] += dx
    return change


def drop_word(text):
    def change(reading):
        reading["words"].remove(word(reading, text))
    return change


def claims(gct, doc, *state):
    """{locator: claim record} from gct claims list --json."""
    rows = gct("claims", "list", "--doc", doc, *(("--state", state[0]) if state else ()), "--json").data["claims"]
    return {c["locator"]: c for c in rows}


def published_claims(gct, ws):
    v = gct("publish", "build", "--json").data
    conn = published.open_version(ws / "published" / f"v{v['version']}.db")
    try:
        return {r["locator"]: dict(r) for r in conn.execute("SELECT * FROM claim")}
    finally:
        conn.close()


# AC 8
def test_a_figure_absent_from_the_new_reading_is_not_found_and_stays_listed(ws, db, doc, gct):
    add_reading(ws, db, doc, drop_word("1,23,456"))
    gct("extract")
    c = claims(gct, doc)[WATER]
    assert c["claim_state"] == "not found in the newest reading"
    assert WATER in claims(gct, doc, "not-found") and WATER not in claims(gct, doc, "current")
    assert published_claims(gct, ws)[WATER]["claim_state"] == "not found in the newest reading"
    assert "not found in the newest reading  1,23,456" in gct("claims", "list", "--doc", doc).out


def test_a_reused_locator_at_another_place_is_a_new_claim(ws, db, doc, gct):
    add_reading(ws, db, doc, move_line("4,560", 300))  # same line and word number, boxes do not overlap
    gct("extract")
    cs = claims(gct, doc)
    assert cs[ENERGY]["claim_state"] == "not found in the newest reading"
    assert cs[ENERGY + "~2"]["claim_state"] == "current" and cs[ENERGY + "~2"]["value_text"] == "4,560"
    # Extracting that reading again under other rules continues ~2; it never opens ~3.
    before = count(db, "claim")
    add_reading(ws, db, doc, lambda r: r.update(again=True))  # another reading, same figures
    gct("extract")
    assert count(db, "claim") == before and claims(gct, doc)[ENERGY + "~2"]["claim_state"] == "current"


def test_an_overlapping_box_with_a_new_value_is_a_new_version_of_the_same_claim(ws, db, doc, gct):
    claims_before, versions_before = count(db, "claim"), count(db, "claim_version")
    add_reading(ws, db, doc, set_word("4,560", "4,570"))
    gct("extract")
    c = claims(gct, doc)[ENERGY]
    assert (c["value_text"], c["claim_state"]) == ("4,570", "current")
    assert count(db, "claim") == claims_before and count(db, "claim_version") == versions_before + 1
    h = gct("claims", "history", c["id"], "--json").data
    assert [v["value_text"] for v in h["versions"]] == ["4,560", "4,570"]
    assert [[s["status"] for e in v["evidence_refs"] for s in e["source_match"]] for v in h["versions"]] == [
        ["matched"], ["matched"]]


def test_a_page_read_again_but_not_extracted(ws, db, doc, gct):
    add_reading(ws, db, doc, set_word("4,560", "4,570"))
    states = {c["claim_state"] for c in claims(gct, doc).values()}
    assert states == {"page read again, not yet extracted"}
    assert len(claims(gct, doc, "not-extracted")) == 4 and claims(gct, doc, "current") == {}


def test_a_page_read_back_to_an_earlier_reading_is_extracted_again(ws, db, doc, gct):
    first = db.execute("SELECT artifact_id, width, height, words, tables FROM page ORDER BY id LIMIT 1").fetchone()
    add_reading(ws, db, doc, set_word("4,560", "4,570"))
    gct("extract")
    # Reading A again: a new page row pointing at the first artifact (A, B, A).
    db.execute("INSERT INTO page (document_id, page_number, rung, method, config_version, width, height, words, tables,"
               " flags, artifact_id, created_at) VALUES (?, 1, 1, 'again', 'c3', ?, ?, ?, ?, '[]', ?, 't')",
               (doc, first["width"], first["height"], first["words"], first["tables"], first["artifact_id"]))
    db.commit()
    gct("extract")
    c = claims(gct, doc)[ENERGY]
    assert (c["value_text"], c["claim_state"]) == ("4,560", "current")


# AC 11
def test_a_second_run_with_nothing_changed_adds_no_rows(ws, db, doc, gct):
    gct("contributor", "add", "ana", "--name", "Ana")
    gct("link")
    gct("infer")
    tables = ("claim", "claim_version", "claim_seen", "source_match", "inference", "evidence_ref")
    before = {t: count(db, t) for t in tables}
    for stage in ("read", "extract", "link", "infer"):
        (d,) = gct(stage, "--json").data["documents"]
        assert d.get("cached") and not (d.get("read") or d.get("extracted") or d.get("checked") or d.get("inferred")), stage
    assert {t: count(db, t) for t in tables} == before


def test_new_extract_rules_that_find_the_same_figures_add_no_version(ws, db, doc, gct, monkeypatch):
    versions, seen = count(db, "claim_version"), count(db, "claim_seen")
    assert {c["claim_state"] for c in claims(gct, doc).values()} == {"current"}
    monkeypatch.setattr(extract, "extract_config", lambda: "rules of a later story")
    assert {c["claim_state"] for c in claims(gct, doc).values()} == {"page read again, not yet extracted"}
    gct("extract")
    assert count(db, "claim_version") == versions and count(db, "claim_seen") == seen + 4
    assert {c["claim_state"] for c in claims(gct, doc).values()} == {"current"}


# AC 5 (the S half: a new reading under new configs gives a new version of the same claim; old one kept)
def test_a_fresh_extraction_under_new_configs_shows_the_new_value(ws, db, doc, gct, monkeypatch):
    old = claims(gct, doc)[ENERGY]
    monkeypatch.setattr(extract, "extract_config", lambda: "config 3")
    add_reading(ws, db, doc, set_word("4,560", "4,570"))
    gct("extract")
    gct("link")
    c = claims(gct, doc)[ENERGY]
    assert (c["id"], c["value_text"], c["claim_state"], c["source_match"]) == (old["id"], "4,570", "current", "matched")
    versions = gct("claims", "history", c["id"], "--json").data["versions"]
    assert [(v["value_text"], [s["status"] for e in v["evidence_refs"] for s in e["source_match"]]) for v in versions] == [
        ("4,560", ["matched"]), ("4,570", ["matched"])]


# AC 5 on the rotated fixture: read and extracted at configs 2/2, then at 3/3
def test_the_rotated_figure_gets_a_new_version_of_the_same_claim_after_reading_again(ws, gct, make_file, monkeypatch):
    from pdf_layouts import ROTATED
    from test_reading_order import OLD_CONFIG, add, old_read_page
    from gct.stages import read

    doc = add(gct, make_file, ROTATED)
    real = read.read_page, read.read_config, extract.extract_config
    monkeypatch.setattr(read, "read_page", old_read_page)
    monkeypatch.setattr(read, "read_config", lambda: OLD_CONFIG)
    monkeypatch.setattr(extract, "extract_config", lambda: "extract config 2, kept by the test")
    for stage in ("read", "extract", "link"):
        gct(stage)
    before = claims(gct, doc)["t0r0c1"]
    # A reading without text directions no longer confirms the reversed figure it produced (R3).
    assert (before["value_text"], before["source_match"]) == ("92.0", "cited")
    for module, name, value in zip((read, read, extract), ("read_page", "read_config", "extract_config"), real):
        monkeypatch.setattr(module, name, value)
    assert claims(gct, doc)["t0r0c1"]["claim_state"] == "page read again, not yet extracted"
    for stage in ("read", "extract", "link"):
        assert gct(stage).code == 0
    c = claims(gct, doc)["t0r0c1"]
    assert (c["id"], c["value_text"], c["claim_state"], c["source_match"]) == (before["id"], "0.29", "current", "matched")
    versions = gct("claims", "history", c["id"], "--json").data["versions"]
    assert [(v["value_text"], [s["status"] for e in v["evidence_refs"] for s in e["source_match"]]) for v in versions] == [
        ("92.0", ["cited"]), ("0.29", ["matched"])]


# AC 9
def test_a_resolved_period_on_an_older_version_needs_re_review(ws, db, doc, gct):
    gct("contributor", "add", "ana", "--name", "Ana")
    cid = claims(gct, doc)[ENERGY]["id"]
    gct("infer")
    r = gct("infer", "resolve", cid, "--field", "period", "--kind", "calendar_year", "--start", "2023-01-01",
            "--end", "2023-12-31", *WHO)
    assert r.code == 0
    review = db.execute("SELECT * FROM inference_review").fetchone()
    assert published_claims(gct, ws)[ENERGY]["period_start"] == "2023-01-01"
    add_reading(ws, db, doc, set_word("4,560", "4,570"))
    gct("extract")
    c = claims(gct, doc)[ENERGY]
    (entry,) = c["needs_re_review"]
    assert entry == {"kind": "period review", "id": review["id"], "version": review["claim_version_id"]}
    assert f"needs re-review: period review #{review['id']} on version {review['claim_version_id']}" in gct(
        "claims", "list", "--doc", doc).out
    p = published_claims(gct, ws)[ENERGY]
    assert p["period_start"] is None and json.loads(p["needs_re_review"]) == [entry]
    assert [tuple(r) for r in db.execute("SELECT * FROM inference_review")] == [tuple(review)]
    # A review recorded on the current version clears the entry.
    gct("infer")
    gct("infer", "resolve", cid, "--field", "period", "--kind", "calendar_year", "--start", "2023-01-01",
        "--end", "2023-12-31", *WHO)
    assert claims(gct, doc)[ENERGY]["needs_re_review"] == []
