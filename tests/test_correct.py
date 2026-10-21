"""Story 3.5: corrections from the CLI and the viewer's endpoint; nothing earlier changes."""
import json
import sqlite3
import urllib.error
import urllib.request

import pytest

from test_api import OPENER, call, cookie
from test_extract import count
from test_link import add_reading, doc  # noqa: F401  (doc is a fixture: read and extracted once)
from test_lock import holder
from test_reprocess import ENERGY, WHO, claims, drop_word, published_claims, set_word
from gct.api import server
from gct.workspace import published

HISTORY = ("claim_version", "evidence_ref", "source_match", "inference", "inference_review")


@pytest.fixture
def ana(gct):
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")


def snapshot(db):
    return {t: [tuple(r) for r in db.execute(f"SELECT * FROM {t} ORDER BY id")] for t in HISTORY}


# AC 6
def test_a_correction_is_a_new_version_and_nothing_earlier_changes(ws, db, doc, gct, ana):
    gct("link")
    gct("infer")
    cid = claims(gct, doc)[ENERGY]["id"]
    gct("infer", "resolve", cid, "--field", "period", "--kind", "calendar_year", "--start", "2023-01-01",
        "--end", "2023-12-31", *WHO)
    before = snapshot(db)
    old = claims(gct, doc)[ENERGY]
    r = gct("correct", cid, "--value", "4,570", *WHO, "--json")
    assert r.code == 0
    first = r.data["correction"]
    assert (first["fields"], first["replaced"]["value_text"], first["contributor"], first["capacity"],
            first["rationale"]) == (["value_text"], "4,560", "Ana", "analyst", "checked on the page")
    assert first["created_at"] and first["corrects_version"] < r.data["version"]
    after = snapshot(db)
    for t in HISTORY:  # every earlier row is still there, unchanged
        assert after[t][:len(before[t])] == before[t], t
    assert len(after["claim_version"]) == len(before["claim_version"]) + 1
    assert len(after["evidence_ref"]) == len(before["evidence_ref"]) + 1
    new_ref = after["evidence_ref"][-1]
    old_ref = next(e for e in before["evidence_ref"] if e[1] == first["corrects_version"])
    assert new_ref[2:5] == old_ref[2:5]  # same document, page and boxes
    c = claims(gct, doc)[ENERGY]
    assert (c["id"], c["value_text"], c["value"], c["method"]) == (old["id"], "4,570", 4570.0, "correction")
    # A second correction cites the first.
    second = gct("correct", cid, "--unit", "GWh", *WHO, "--json").data
    assert second["correction"]["corrects_version"] == r.data["version"]
    assert second["correction"]["replaced"]["value_text"] == "4,570"
    # The corrected value is not printed on the page, so its location is cited, never matched.
    gct("link")
    c = claims(gct, doc)[ENERGY]
    assert (c["source_match"], c["source_match_reason"]) == ("cited", "box does not reproduce the figure")
    out = gct("claims", "history", cid).out
    assert "correction #1 of version" in out and "replaced 4,560" in out and "correction #2" in out
    for table in ("correction", "claim_seen"):
        for stmt in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
                db.execute(stmt)


def test_a_correction_needs_a_current_claim_and_a_change(ws, db, doc, gct, ana):
    cid = claims(gct, doc)[ENERGY]["id"]
    r = gct("correct", cid, "--value", "4,560", *WHO)
    assert r.code == 4 and "already has those values" in r.err
    add_reading(ws, db, doc, set_word("4,560", "4,570"))
    r = gct("correct", cid, "--value", "4,580", *WHO)
    assert r.code == 4 and "page read again, not yet extracted" in r.err and "gct extract" in r.err
    assert count(db, "correction") == 0


# AC 7
def test_re_processing_never_drops_a_correction(ws, db, doc, gct, ana):
    cid = claims(gct, doc)[ENERGY]["id"]
    gct("correct", cid, "--value", "4,570", *WHO)
    versions = count(db, "claim_version")
    add_reading(ws, db, doc, lambda r: r.update(again=True))  # a re-read that finds the same figure
    gct("extract")
    c = claims(gct, doc)[ENERGY]
    assert (count(db, "claim_version"), c["value_text"], c["method"], c["claim_state"]) == (
        versions, "4,570", "correction", "current")
    assert c["needs_re_review"] == []
    add_reading(ws, db, doc, set_word("4,560", "4,590"))  # a re-read that finds a different figure
    gct("extract")
    c = claims(gct, doc)[ENERGY]
    assert (c["value_text"], c["method"], c["claim_state"]) == ("4,590", "rung1-rules", "current")
    fix = db.execute("SELECT * FROM correction").fetchone()
    assert c["needs_re_review"] == [{"kind": "correction", "id": fix["id"], "version": fix["claim_version_id"]}]
    versions = gct("claims", "history", cid, "--json").data["versions"]
    assert [(v["method"], v["value_text"]) for v in versions] == [
        ("rung1-rules", "4,560"), ("correction", "4,570"), ("rung1-rules", "4,590")]
    # A correction on the current version clears the entry.
    gct("correct", cid, "--value", "4,595", *WHO)
    assert claims(gct, doc)[ENERGY]["needs_re_review"] == []


# AC 10
def test_the_projection_and_the_api_carry_the_correction(ws, db, doc, gct, ana):
    gct("publish", "build")
    mark = published.history_mark(db)
    cid = claims(gct, doc)[ENERGY]["id"]
    gct("correct", cid, "--value", "4,570", *WHO)
    assert published.history_mark(db) != mark
    p = published_claims(gct, ws)[ENERGY]
    assert (p["value_text"], p["version_method"], p["claim_state"]) == ("4,570", "correction", "current")
    assert json.loads(p["correction"])["replaced"]["value_text"] == "4,560"
    srv = server.serve(ws, port=0)
    try:
        status, _, body = call(srv.port, f"/api/documents/{doc}/claims", **cookie(srv))
        row = next(c for c in json.loads(body)["claims"] if c["id"] == cid)
        assert status == 200 and row["correction"]["contributor"] == "Ana" and row["claim_state"] == "current"
        status, _, body = call(srv.port, f"/api/claims/{cid}/history", **cookie(srv))
        assert status == 200 and [v["method"] for v in json.loads(body)["versions"]] == ["rung1-rules", "correction"]
        assert call(srv.port, "/api/claims/999/history", **cookie(srv))[0] == 404
    finally:
        srv.stop()


def post(srv, path, body, content_type="application/json", **headers):
    data = json.dumps(body).encode() if content_type == "application/json" else body
    req = urllib.request.Request(f"http://127.0.0.1:{srv.port}{path}", data=data, method="POST",
                                 headers={"Content-Type": content_type, **headers})
    try:
        r = OPENER.open(req, timeout=10)
    except urllib.error.HTTPError as e:
        r = e
    with r:
        return r.getcode(), json.loads(r.read().decode())


# AC 10b
def test_the_correction_endpoint_and_its_guard(ws, db, doc, gct, ana):
    gct("publish", "build")
    cid = claims(gct, doc)[ENERGY]["id"]
    body = {"value": "4,570", "contributor": "ana", "capacity": "analyst", "rationale": "misread"}
    path = f"/api/claims/{cid}/corrections"
    srv = server.serve(ws, port=0)
    try:
        origin = {"Origin": f"http://127.0.0.1:{srv.port}"}
        rows = {t: count(db, t) for t in ("claim_version", "correction", "published_version")}
        refusals = [
            (post(srv, path, body, **cookie(srv)), 403),
            (post(srv, path, body, Origin="http://evil.example", **cookie(srv)), 403),
            (post(srv, path, body), 401),
            (post(srv, path, b"value=1", "application/x-www-form-urlencoded", **origin, **cookie(srv)), 415),
            (post(srv, path, {"contributor": "ana", "capacity": "a", "rationale": "r"}, **origin, **cookie(srv)), 400),
            (post(srv, "/api/claims/999/corrections", body, **origin, **cookie(srv)), 404),
        ]
        for (status, data), expected in refusals:
            assert status == expected and data["status"] == "error" and data["cause"] and data["next_action"]
        p = holder(ws)
        try:
            status, data = post(srv, path, body, Authorization=f"Bearer {srv.token}")
            assert status == 409 and data["cause"] == "Another gct command is using this workspace."
        finally:
            p.kill()
            p.wait()
        assert {t: count(db, t) for t in rows} == rows
        status, data = post(srv, path, body, Authorization=f"Bearer {srv.token}")
        assert status == 200 and data["correction"]["replaced"]["value_text"] == "4,560"
        assert data["data_version"] == 2
        status, data = post(srv, path, {**body, "value": "4,580"}, **origin, **cookie(srv))
        assert status == 200 and data["data_version"] == 3 and data["correction"]["replaced"]["value_text"] == "4,570"
        row = next(c for c in json.loads(call(srv.port, f"/api/documents/{doc}/claims", **cookie(srv))[2])["claims"]
                   if c["id"] == cid)
        assert (row["value_text"], row["version_method"]) == ("4,580", "correction")
        # A claim that is not current gets the CLI's refusal.
        add_reading(ws, db, doc, drop_word("4,560"))
        gct("extract")
        status, data = post(srv, path, body, **origin, **cookie(srv))
        assert status == 409 and data["cause"] == f"Claim {cid} is not found in the newest reading, so it cannot be corrected."
    finally:
        srv.stop()


def test_a_field_that_is_not_text_is_refused_and_a_failed_build_keeps_the_correction(ws, db, doc, gct, ana,
                                                                                    monkeypatch):
    gct("publish", "build")
    cid = claims(gct, doc)[ENERGY]["id"]
    body = {"value": "4,570", "contributor": "ana", "capacity": "analyst", "rationale": "misread"}
    path = f"/api/claims/{cid}/corrections"
    srv = server.serve(ws, port=0)
    try:
        bearer = {"Authorization": f"Bearer {srv.token}"}
        rows = {t: count(db, t) for t in ("claim_version", "correction", "published_version")}
        for bad in ({"value": ["1,300"]}, {"value": 0}, {"value": None}, {"rationale": 7}):
            status, data = post(srv, path, {**body, **bad}, **bearer)
            assert status == 400 and data["cause"] == f"The correction field {next(iter(bad))} is not text.", data
        assert {t: count(db, t) for t in rows} == rows
        # O4: the correction is committed before the build; a failed build leaves it with no new published version.
        monkeypatch.setattr(published, "build", lambda conn, root: 1 / 0)
        status, data = post(srv, path, body, **bearer)
        assert status == 500 and data["cause"] == "Something unexpected went wrong."
        assert count(db, "correction") == rows["correction"] + 1
        assert count(db, "published_version") == rows["published_version"]
    finally:
        srv.stop()
