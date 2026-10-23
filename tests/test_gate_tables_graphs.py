"""The Tables-and-Graphs gate, G1 (story 6.1 section G): on tests/gate_fixture.py, for a fixed matrix of filters, the
table's claim ids (every page) are the graph's claim nodes, each claim's evidence location on its row is the one on its
node, both answers name the pinned version, and every evidence location on a row, node or edge opens through the real
endpoints (a page PNG, a sheet's cells) or is explicitly unresolved."""
import json
import urllib.parse
import urllib.request

import pytest

import gate_fixture
from test_api import OPENER, call
from test_correct import post
from test_review_api import bearer
from gct.api import server

FILTERS = [
    {},
    {"company": [2]}, {"document": [3]}, {"metric": ["ghg_scope_1"]}, {"text": "energy"},
    {"period": {"from": "2024-04-01", "to": "2025-03-31"}}, {"boundary": ["subsidiary_set"]},
    {"claim_state": ["current"]}, {"evidence": ["not-checked"]}, {"match": ["not-matchable"]},
    {"series": ["2b7f0c7666c0"]}, {"comparison": ["restatement"]}, {"review": ["disagreement"]},
    {"company": [1], "metric": ["energy_total"], "comparison": ["unresolved"]},
    {"document": [1, 2, 6], "period": {"to": "2024-03-31"}, "review": ["corrected", "adjudicated"]},
    {"company": [1, 2], "boundary": ["standalone"], "evidence": ["matched"]},
    {"document": [5]},  # matches nothing: the deleted document
]


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    s = server.serve(gate_fixture.build(tmp_path_factory.mktemp("gate") / "ws"), port=0)
    yield s
    s.stop()


def records(srv, body):
    status, answer = post(srv, "/api/records", body, **bearer(srv))
    assert status == 200, answer
    return answer


def opens(srv, loc, version) -> bool:
    """A location opens through the real endpoints, or says it cannot."""
    if not loc["resolved"]:
        return bool(loc["reason"])
    if loc["sheet"] is not None:
        q = urllib.parse.urlencode({"sheet": loc["sheet"], "cell": loc["cell"], "data_version": version})
        return call(srv.port, f"/api/documents/{loc['document']}/cells?{q}", **bearer(srv))[0] == 200
    req = urllib.request.Request(f"http://127.0.0.1:{srv.port}/api/documents/{loc['document']}/pages/{loc['page']}.png",
                                 headers=bearer(srv))
    with OPENER.open(req, timeout=10) as r:  # a refusal raises
        return r.getcode() == 200 and r.read(4) == b"\x89PNG"


@pytest.mark.parametrize("flt", FILTERS, ids=[json.dumps(f) for f in FILTERS])
def test_a_table_and_a_graph_of_one_filter_hold_the_same_claims_and_evidence(srv, flt):
    version = records(srv, {"shape": "values"})["data_version"]
    rows, offset = [], 0
    while True:  # every page of the table, two rows at a time
        t = records(srv, {"filter": flt, "data_version": version, "offset": offset, "limit": 2})
        assert t["data_version"] == version
        rows += t["rows"]
        offset += 2
        if offset >= t["matched"]:
            break
    g = records(srv, {"filter": flt, "data_version": version, "shape": "graph"})
    assert g["data_version"] == version and g["drawable"] is (t["matched"] > 0)
    claims = {n["id"]: n for n in g["nodes"] if n["kind"] == "claim"}
    table = [r["claim"]["id"] for r in rows]
    assert len(table) == len(set(table)) == t["matched"] == g["matched"]
    assert {f"claim:{i}" for i in table} == set(claims)
    seen = set()
    for r in rows:
        node = claims[f"claim:{r['claim']['id']}"]
        assert node["evidence"] == [r["evidence"]["location"]] and node["row"] == r
        for loc in [r["evidence"]["location"]]:
            assert opens(srv, loc, version), loc
    for item in g["nodes"] + g["edges"]:
        for loc in item["evidence"]:
            key = json.dumps(loc, sort_keys=True)
            if key not in seen:
                seen.add(key)
                assert opens(srv, loc, version), (item["id"], loc)


def test_the_matrix_covers_every_fixture_item(srv):
    """The fixture holds what G1 lists, so the matrix above exercises it."""
    t = records(srv, {"limit": 1000})
    rows = {r["claim"]["id"]: r for r in t["rows"]}
    kinds = {r["claim"]["period"]["kind"] for r in rows.values()}
    assert {"fiscal_year", "as_at"} <= kinds
    assert any(r["claim"]["boundary"]["value"] == "subsidiary_set" for r in rows.values())
    assert any(r["claim"]["sheet"] for r in rows.values())
    review = [r["review"] for r in rows.values()]
    assert any(v["disagreement"] for v in review) and any(v["flags_raised"] for v in review)
    assert any(v["highlights"] for v in review) and any(v["needs_re_review"] for v in review)
    assert any(v["adjudications"] for v in review) and any(v["candidate_pairs"] for v in review)
    assert t["hidden_by_archive"]["documents"] == 1
    assert records(srv, {"filter": {"comparison": ["restatement"]}})["matched"] == 2
    assert records(srv, {"filter": {"document": [5]}})["deleted_in_filter"]
    assert len({r["claim"]["company"] for r in rows.values()}) == 2


# G3 (story 6.4 part A, backend): a saved view re-opened after a further report includes that report's qualifying
# claims and names the new version; after an archive it shows the remaining claims and the F7 count; after a restore
# the claims are back. Each version is checked right after its build (only the current and previous files are kept).
def test_g3_a_saved_view_follows_later_reports_archives_and_restores(tmp_path, gct):
    from test_saved_view import later_report

    root = gate_fixture.build(tmp_path / "g3")
    w = ("--workspace", root)

    def opened(name):
        r = gct("view", "open", name, "--limit", "1000", *w, "--json")
        assert r.code == 0, r.out
        return r.data

    # One view matching some claims today, one matching none today (FY 2021-22 is in no report yet).
    for name, flt in (("scope 1", {"company": [1], "metric": ["ghg_scope_1"]}),
                      ("early", {"text": "scope 1", "period": {"to": "2022-03-31"}})):
        assert gct("view", "save", name, "--filter", json.dumps(flt), "--as", "ana", *w).code == 0
    v1 = opened("scope 1")
    assert v1["data_version"] == 1 and opened("early")["matched"] == 0
    doc = later_report(root)
    v2 = opened("scope 1")
    new = {r["claim"]["id"] for r in v2["rows"]} - {r["claim"]["id"] for r in v1["rows"]}
    assert v2["data_version"] == 2 and len(new) == 2
    assert {r["claim"]["document"] for r in v2["rows"] if r["claim"]["id"] in new} == {doc}
    early = opened("early")
    assert early["data_version"] == 2 and [r["claim"]["document"] for r in early["rows"]] == [doc]
    who = ("--as", "ana", "--capacity", "analyst", "--rationale", "superseded")
    assert gct("doc", "archive", str(doc), *who, *w).code == 0 and gct("publish", "build", *w).code == 0
    v3 = opened("scope 1")
    assert v3["data_version"] == 3 and {r["claim"]["id"] for r in v3["rows"]} == {r["claim"]["id"] for r in v1["rows"]}
    assert v3["hidden_by_archive"]["documents"] == 2 and v3["hidden_by_archive"]["claims"] == 4
    assert v3["hidden_by_archive"]["text"] == ("4 claims of 2 archived documents are not in this or any view. Restore a"
                                               " document to include its claims.")
    assert opened("early")["matched"] == 0
    assert gct("doc", "restore", str(doc), *who, *w).code == 0 and gct("publish", "build", *w).code == 0
    v4 = opened("scope 1")
    assert v4["data_version"] == 4 and v4["rows"] == v2["rows"] and v4["hidden_by_archive"]["documents"] == 1
