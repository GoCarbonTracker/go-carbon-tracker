"""Story 5.4: the review endpoints of the local service. Each write calls the same function as its CLI command, under
the workspace lock, then builds a published version; every refusal is the CLI's and writes nothing. Synthetic
workspaces only."""
import json

import pytest

from test_api import call, cookie
from test_correct import post
from test_lock import holder
from test_match import WHO
from test_restate import QUOTE, cp2
from test_review import counts
from gct.api import server

LEDGER = {"outcome": "accepted", "scope": "Scope 1, FY 2023-24", "conclusion": "We verified it", "contributor": "ana",
          "capacity": "head of sustainability", "evidence_note": "ledger export, row 12"}


@pytest.fixture
def pair(ws, gct, make_file):
    """Acme's candidate pair (cp2 of story 4.2), published, served: (server, restated claim, its newest version,
    original claim)."""
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")
    gct("contributor", "add", "bob", "--name", "Bob")
    _, _, restated, original = cp2(gct, make_file)
    assert gct("publish", "build").code == 0
    version = gct("claims", "history", restated, "--json").data["versions"][-1]["id"]
    srv = server.serve(ws, port=0)
    yield srv, restated, version, original
    srv.stop()


def origin(srv) -> dict:
    return {"Origin": f"http://127.0.0.1:{srv.port}", **cookie(srv)}


def bearer(srv) -> dict:
    return {"Authorization": f"Bearer {srv.token}"}


def history(srv, claim) -> dict:
    status, _, body = call(srv.port, f"/api/claims/{claim}/history", **cookie(srv))
    assert status == 200
    return json.loads(body)


# AC 4 (interaction note 3): each form records through the same function as its CLI command
def test_every_write_records_what_the_cli_records_and_publishes(ws, db, gct, pair):
    srv, claim, version, original = pair
    path = f"/api/claims/{claim}"
    status, data = post(srv, f"{path}/company-confirmations", {**LEDGER, "version": version}, **origin(srv))
    assert status == 200 and data["data_version"] == 2, data
    assert (data["claim"]["version"], data["entry"]["ledger"], data["entry"]["conclusion"]) == (
        version, "company", "We verified it")
    status, data = post(srv, f"{path}/auditor-reviews", {**LEDGER, "version": version, "outcome": "disputed",
                                                         "evidence_document": 1, "evidence_page": 1,
                                                         "date": "2025-06-30"}, **bearer(srv))
    assert status == 200 and data["disagreement"] == {"company": ["accepted"], "auditor": ["disputed"]}
    assert (data["entry"]["evidence_document"], data["entry"]["reviewed_on"]) == (1, "2025-06-30")
    status, data = post(srv, f"{path}/highlights", {"version": version, "note": "look again", "contributor": "bob",
                                                    "capacity": "analyst"}, **origin(srv))
    assert status == 200 and data["entry"]["note"] == "look again" and data["data_version"] == 4
    flag = {"version": version, "rationale": "the trend reads too good", "contributor": "bob", "capacity": "analyst"}
    status, data = post(srv, f"{path}/flags", {**flag, "decision": "raised"}, **origin(srv))
    assert status == 200 and data["flag"]["decision"] == "raised"
    status, data = post(srv, f"{path}/flags", {**flag, "decision": "withdrawn"}, **origin(srv))
    assert status == 200 and data["flag"]["decision"] == "withdrawn"
    status, data = post(srv, "/api/adjudications", {"first": original, "second": claim, "state": "extraction-error",
                                                    "rationale": "misread", "procedure": "compared both pages",
                                                    "contributor": "ana", "capacity": "analyst"}, **origin(srv))
    assert status == 200 and data["adjudication_state"] == "extraction error" and data["next"], data
    # What the CLI lists is what the endpoints wrote; the history endpoint carries it, highlights included.
    listed = gct("review", "list", claim, "--json").data["versions"][-1]
    h = history(srv, claim)["versions"][-1]
    for key in ("company_confirmations", "auditor_reviews", "disagreement"):
        assert h[key] == listed[key], key
    assert h["highlights"] == gct("highlight", "list", claim, "--json").data["versions"][-1]["highlights"]
    assert [f["decision"] for f in h["reviewer_flags"]] == ["raised", "withdrawn"]
    assert [a["state"] for a in h["adjudications"]] == ["extraction_error"]
    assert all(x["self_declared"] for k in ("company_confirmations", "auditor_reviews", "highlights", "reviewer_flags",
                                            "adjudications") for x in h[k])
    assert all(v["highlights"] == [] for v in history(srv, original)["versions"])
    assert gct("publish", "status", "--json").data["current_version"] == 7


# AC 4 (interaction note 4): the candidates list matches gct adjudicate list for the company
def test_candidates_match_gct_adjudicate_list(ws, gct, pair):
    srv, claim, version, original = pair
    status, _, body = call(srv.port, "/api/companies/1/candidates", **cookie(srv))
    data = json.loads(body)
    cli = gct("adjudicate", "list", "--company", "Acme", "--json").data
    assert status == 200 and data == {**cli, "company": 1}
    assert [{c["a"]["claim_id"], c["b"]["claim_id"]} for c in data["candidates"]] == [{claim, original}]
    assert data["candidates"][0]["adjudication_state"] == "unreviewed candidate"
    assert call(srv.port, "/api/companies/9/candidates", **cookie(srv))[0] == 404
    assert call(srv.port, "/api/companies/1/candidates")[0] == 401


def bodies(claim, version, original) -> dict:
    """{path: a body the endpoint accepts}."""
    flag = {"version": version, "rationale": "r", "contributor": "ana", "capacity": "c", "decision": "raised"}
    return {f"/api/claims/{claim}/company-confirmations": {**LEDGER, "version": version},
            f"/api/claims/{claim}/auditor-reviews": {**LEDGER, "version": version},
            f"/api/claims/{claim}/highlights": {"version": version, "note": "n", "contributor": "ana", "capacity": "c"},
            f"/api/claims/{claim}/flags": flag,
            "/api/adjudications": {"first": original, "second": claim, "state": "evidence-not-found", "rationale": "r",
                                   "procedure": "p", "contributor": "ana", "capacity": "c"}}


# AC 4 and 6, matrix rows "foreign Origin", "non-JSON body", "workspace locked": refused, nothing written
def test_every_write_refusal_writes_nothing(ws, db, gct, pair):
    srv, claim, version, original = pair
    before = counts(db)
    for path, body in bodies(claim, version, original).items():
        text = next(k for k, v in body.items() if isinstance(v, str))
        number = "version" if "version" in body else "first"
        cases = [(post(srv, path, body, **cookie(srv)), 403),  # a cookie with no Origin
                 (post(srv, path, body, Origin="http://evil.example", **cookie(srv)), 403),
                 (post(srv, path, body, Origin="http://evil.example", **bearer(srv)), 403),
                 (post(srv, path, body), 401),
                 (post(srv, path, b"version=1", "application/x-www-form-urlencoded", **origin(srv)), 415),
                 (post(srv, path, b"[1]", "text/plain", **bearer(srv)), 415),
                 (post(srv, path, [body], **origin(srv)), 400),
                 (post(srv, path, {**body, text: 7}, **origin(srv)), 400),
                 (post(srv, path, {**body, number: "12"}, **origin(srv)), 400),
                 (post(srv, path, {**body, number: True}, **origin(srv)), 400),
                 (post(srv, path, {k: v for k, v in body.items() if k != number}, **origin(srv)), 400)]
        for (status, data), expected in cases:
            assert status == expected, (path, status, data)
            assert data["status"] == "error" and data["cause"] and data["next_action"], data
        assert cases[7][0][1]["cause"].endswith(f"field {text} is not text.")
        assert cases[9][0][1]["cause"].endswith(f"field {number} is not a whole number.")
        assert cases[10][0][1]["cause"].endswith(f"field {number} is missing.")
        p = holder(ws)
        try:
            status, data = post(srv, path, body, **bearer(srv))
            assert status == 409 and data["cause"] == "Another gct command is using this workspace."
        finally:
            p.kill()
            p.wait()
        assert counts(db) == before, path


def cli_error(gct, *argv) -> dict:
    r = gct(*argv, "--json")
    assert r.code != 0
    return {"status": "error", "cause": r.data["cause"], "next_action": r.data["next_action"]}


# AC 4 (interaction note 3) and matrix rows "claim corrected after the panel loaded", "pair no longer a candidate"
def test_the_cli_refusals_arrive_with_their_text_and_next_step(ws, db, gct, pair):
    srv, claim, version, original = pair
    assert gct("correct", claim, "--value", "1,101", *WHO).code == 0  # the claim changed after the panel loaded
    before = counts(db)
    stale = bodies(claim, version, original)
    who = ("--as", "ana", "--capacity", "c")
    cli = {f"/api/claims/{claim}/company-confirmations": ("review", "company", claim, "--version", version, "--outcome",
                                                          "accepted", "--scope", LEDGER["scope"], "--conclusion",
                                                          LEDGER["conclusion"], *who, "--evidence-note", "n"),
           f"/api/claims/{claim}/auditor-reviews": ("review", "auditor", claim, "--version", version, "--outcome",
                                                    "accepted", "--scope", LEDGER["scope"], "--conclusion",
                                                    LEDGER["conclusion"], *who, "--evidence-note", "n"),
           f"/api/claims/{claim}/highlights": ("highlight", "add", claim, "--version", version, "--note", "n", *who),
           f"/api/claims/{claim}/flags": ("flag", "raise", claim, "--version", version, *who, "--rationale", "r")}
    for path, argv in cli.items():
        status, data = post(srv, path, stale[path], **origin(srv))
        assert status == 409 and data == cli_error(gct, *argv), (path, data)
        assert "is not" in data["cause"] and f"gct claims history {claim}" in data["next_action"]
    # A corrected claim is in no pair until infer and match run again: the pair is not a candidate now.
    status, data = post(srv, "/api/adjudications", stale["/api/adjudications"], **origin(srv))
    assert status == 409 and data == cli_error(gct, "adjudicate", "record", original, claim, "--state",
                                               "evidence-not-found", "--procedure", "p", *who, "--rationale", "r")
    assert "has not been matched yet" in data["cause"]
    status, data = post(srv, "/api/adjudications", {**stale["/api/adjudications"], "state": "restatement"},
                        **origin(srv))
    assert status == 409 and "gct restate record" in data["next_action"]
    status, data = post(srv, f"/api/claims/{claim}/flags", {**stale[f"/api/claims/{claim}/flags"], "decision": "x"},
                        **origin(srv))
    assert status == 400 and "raised or withdrawn" in data["cause"]
    status, data = post(srv, "/api/claims/999/highlights", stale[f"/api/claims/{claim}/highlights"], **origin(srv))
    assert status == 404 and data["cause"] == "There is no claim 999."
    assert counts(db) == before


def test_a_pair_restated_meanwhile_is_refused_with_its_state(ws, db, gct, pair):
    srv, claim, version, original = pair
    assert gct("restate", "record", "--original", original, "--restated", claim, "--page", 1, "--quote", QUOTE,
               *WHO).code == 0
    before = counts(db)
    status, data = post(srv, "/api/adjudications", bodies(claim, version, original)["/api/adjudications"],
                        **origin(srv))
    assert status == 409 and f"are restatement" in data["cause"], data
    assert counts(db) == before
    status, _, body = call(srv.port, "/api/companies/1/candidates", **cookie(srv))
    assert json.loads(body)["candidates"] == []
