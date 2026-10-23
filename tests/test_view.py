"""Story 6.1: the shared filter model and records API (F1 to F11), on tests/gate_fixture.py. One row of the R2 matrix
per test, unless named otherwise; the G1 gate itself is tests/test_gate_tables_graphs.py."""
import json
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

import gate_fixture
from test_api import call, cookie
from test_correct import post
from test_messages import INTERNAL_WORDS, internal_names
from test_review_api import bearer, origin
from gct.api import server
from gct.stages import view
from gct.workspace import layout, published, store

ROOT = Path(__file__).resolve().parent.parent
EVERY = [1, 2, 3, 4, 5, 6, 7, 8, 13, 14, 15, 16, 17, 18]  # 9 and 10: archived document 4; 11 and 12: deleted 5
WHO = ["--as", "ana", "--capacity", "analyst", "--rationale", "checked"]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """The gate workspace, built once; tests that write use gws, a copy."""
    return gate_fixture.build(tmp_path_factory.mktemp("gate") / "ws")


@pytest.fixture
def gws(built, tmp_path):
    shutil.copytree(built, tmp_path / "gws")  # not "ws": conftest's ws fixture makes that one
    return tmp_path / "gws"


@pytest.fixture
def srv(gws):
    s = server.serve(gws, port=0)
    yield s
    s.stop()


def ask(root, flt=None, data_version=None, **kw) -> dict:
    """view.answer on the current version, as the endpoint and the command call it."""
    conn = store.connect(root / layout.DB_NAME)
    try:
        _, pconn = view.pinned(conn, root, data_version)
    finally:
        conn.close()
    try:
        return view.answer(pconn, {} if flt is None else flt, **kw)
    finally:
        pconn.close()


def ids(answer) -> list[int]:
    return sorted(r["claim"]["id"] for r in answer["rows"])


def records(srv, body, **headers):
    return post(srv, "/api/records", body, **(headers or bearer(srv)))


def dump(root) -> dict:
    """Every row of every table of workspace.db (R3)."""
    with sqlite3.connect(root / layout.DB_NAME) as conn:
        tables = [t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {t: sorted(map(repr, conn.execute(f"SELECT * FROM {t}"))) for t in tables}


S1, ENERGY = ["1", "2", "5", "6", "13", "14"], ["3", "4", "7", "8"]
CASES = [
    ({}, EVERY),
    ({"company": [2]}, [13, 14, 15, 16, 17]),
    ({"document": [3]}, [18]),
    ({"metric": ["ghg_scope_1"]}, [1, 2, 5, 6, 13, 14]),
    ({"metric": ["unmapped"]}, [17]),
    ({"text": "SCOPE 1"}, [1, 2, 5, 6, 13, 14]),
    ({"text": "total energy"}, [3, 4, 7, 8]),
    ({"period": {"from": "2024-04-01", "to": "2025-03-31"}}, [1, 3, 13, 15, 18]),
    ({"period": {"to": "2024-03-31"}}, [2, 4, 5, 6, 7, 8, 14, 16]),
    ({"boundary": ["subsidiary_set"]}, [13, 14]),
    ({"boundary": ["unknown"]}, [17]),
    ({"claim_state": ["current"]}, EVERY),
    ({"claim_state": ["not-found", "not-extracted"]}, []),
    ({"evidence": ["not-checked"]}, [14]),
    ({"evidence": ["cited", "unresolved"]}, []),
    ({"match": ["not-matchable"]}, [17]),
    ({"series": ["2b7f0c7666c0"]}, [1, 2, 5, 6]),
    ({"comparison": ["restatement"]}, [2, 5]),
    ({"comparison": ["unresolved"]}, [4, 7]),
    ({"review": ["company-confirmation"]}, [1]),
    ({"review": ["auditor-review"]}, [1]),  # 14's auditor review is on its older version
    ({"review": ["disagreement"]}, [1]),
    ({"review": ["flag-raised"]}, [13]),
    ({"review": ["highlight"]}, [3]),
    ({"review": ["needs-re-review"]}, [14]),
    ({"review": ["corrected"]}, [14]),
    ({"review": ["adjudicated"]}, [4, 7]),
    ({"review": ["highlight", "flag-raised"]}, [3, 13]),  # OR within a field
    ({"company": [1], "metric": ["ghg_scope_1"], "period": {"from": "2023-04-01", "to": "2024-03-31"}}, [2, 5]),
    ({"company": [1, 2], "boundary": ["standalone", "subsidiary_set"], "match": ["series"], "review": ["corrected"]},
     [14]),
    ({"text": "zzz"}, []),
]


# R2: every field alone, combined, and the empty object
@pytest.mark.parametrize("flt, expected", CASES, ids=[json.dumps(c[0]) for c in CASES])
def test_each_field_alone_and_together(built, flt, expected):
    a = ask(built, flt, limit=1000)
    assert ids(a) == expected and a["matched"] == len(expected)
    assert a["data_version"] == 1 and a["filter"] == view.normalise(flt)


def test_a_filter_is_normalised_without_a_connection():
    assert view.normalise({"company": [2, 1, 2], "review": ["highlight", "corrected"]}) == {
        "company": [1, 2], "review": ["corrected", "highlight"]}
    assert view.normalise({}) == {}


BAD = [
    ({"company": []}, "The filter field company is not a list of one or more values."),
    ({"colour": ["red"]}, "The filter has no field colour."),
    ({"company": ["1"]}, 'The filter field company takes ids, and "1" is not one.'),
    ({"company": [True]}, "The filter field company takes ids, and true is not one."),
    ({"metric": ["co2"]}, "co2 is not a value of the filter field metric."),
    ({"text": "x" * 201}, "The filter field text is not text of 1 to 200 characters."),
    ({"text": ""}, "The filter field text is not text of 1 to 200 characters."),
    ({"period": {"from": "2024-13-01"}}, "The filter field period.from is not a date in the form YYYY-MM-DD."),
    ({"period": {"from": "2025-04-01", "to": "2024-03-31"}}, "The filter field period ends before it starts."),
    ({"period": {}}, "The filter field period is not an object with from, to or both."),
    (["company"], "The filter is not a JSON object."),
]


# R2: refusals name the field, 400 and exit 2, nothing written
@pytest.mark.parametrize("flt, cause", BAD, ids=[c[1] for c in BAD])
def test_a_bad_filter_is_refused_naming_the_field(gws, srv, gct, flt, cause):
    before = dump(gws)
    status, body = records(srv, {"filter": flt})
    assert (status, body["status"], body["cause"]) == (400, "error", cause) and body["next_action"]
    r = gct("view", "records", "--filter", json.dumps(flt), "--workspace", gws, "--json")
    assert r.code == 2 and r.data["cause"] == cause
    assert dump(gws) == before


OTHER = [
    ({"shape": "pie"}, 'The shape "pie" is not one of table, graph, series, values.'),
    ({"limit": 0}, "The limit is not a whole number from 1 to 1000."),
    ({"limit": 1001}, "The limit is not a whole number from 1 to 1000."),
    ({"limit": True}, "The limit is not a whole number from 1 to 1000."),
    ({"offset": -1}, "The offset is not a whole number of 0 or more."),
    ({"sort": [{"key": "value"}, {"key": "page"}]}, "The sort is not a list of at most one key."),
    ({"sort": [{"key": "colour"}]}, "A sort element is not a key with asc or desc."),
    ({"claim_ids": list(range(1, 1002))}, "The claim ids are not a list of 1 to 1000 whole numbers."),
    ({"claim_ids": []}, "The claim ids are not a list of 1 to 1000 whole numbers."),
    ({"claim_ids": [True]}, "The claim ids are not a list of 1 to 1000 whole numbers."),
    ({"shape": "values", "claim_ids": [1]},
     "The values shape lists the values of every claim the filter selects, so it takes no claim ids."),
    ({"filters": {}}, "A records request has no field filters."),
    ({"data_version": "1"}, "The data version is not a whole number."),
    ({"data_version": True}, "The data version is not a whole number."),
]


@pytest.mark.parametrize("body, cause", OTHER, ids=[c[1] for c in OTHER])
def test_the_other_request_fields_are_refused_like_the_filter(srv, body, cause):
    status, answer = records(srv, body)
    assert (status, answer["cause"]) == (400, cause) and answer["next_action"]


def test_415_and_400_never_fastapi_422(srv):
    assert post(srv, "/api/records", b"{}", content_type="text/plain", **bearer(srv))[0] == 415
    status, body = post(srv, "/api/records", b"[1]", content_type="text/plain", **bearer(srv))
    assert status == 415 and body["status"] == "error"
    req = post(srv, "/api/records", "not json", content_type="application/json", **bearer(srv))
    assert req[0] == 400  # a JSON string is not an object
    assert call(srv.port, "/api/documents/3/cells?sheet=acme-meter&cell=B2&data_version=x", **bearer(srv))[0] == 400


# R2: a publish build between two queries of one request
def test_every_part_of_an_answer_is_from_one_version(gws, srv, gct, monkeypatch):
    assert gct("correct", "1", "--value", "9,999", *WHO, "--workspace", gws).code == 0  # not yet published
    original, built = view.select, []

    def select_then_build(pconn, flt):
        out = original(pconn, flt)
        if not built:  # the first query has run; another writer publishes before the next ones
            built.append(gct("publish", "build", "--workspace", gws).code)
        return out

    monkeypatch.setattr(view, "select", select_then_build)
    for pin, shape, value in ((1, "table", "1,234"), (2, "graph", "9,999"), (3, "table", "9,999")):
        built.clear()  # each request is pinned to the current version and a build lands in its middle
        status, a = records(srv, {"filter": {"document": [1]}, "shape": shape, "data_version": pin})
        assert status == 200 and built == [0] and a["data_version"] == pin
        rows = a.get("rows") or [n["row"] for n in a.get("nodes", []) if n["kind"] == "claim"]
        assert {r["claim"]["value_text"] for r in rows if r["claim"]["id"] == 1} == {value}, shape
    built.clear()
    status, a = records(srv, {"filter": {"series": ["4ec43b1266be"]}, "shape": "series", "data_version": 4})
    assert status == 200 and built == [0] and a["data_version"] == 4 and a["drawable"]
    assert ask(gws)["data_version"] == 5  # four builds happened, none mixed into an answer


# R2: an older pin, after a write and after gct publish restore
def test_a_stale_pin_is_refused_with_both_numbers(gws, srv, gct):
    status, _ = post(srv, "/api/claims/1/corrections", {"value": "1,235", "contributor": "ana", "capacity": "analyst",
                                                        "rationale": "typo"}, **bearer(srv))
    assert status == 200  # the write published version 2
    for body in ({"data_version": 1}, {"data_version": 1, "shape": "graph"}, {"data_version": 1, "shape": "values"}):
        status, a = records(srv, body)
        assert (status, a) == (409, {"status": "error",
                                     "cause": "Data version 1 is no longer the current one; the current version is 2.",
                                     "next_action": "Reload to see version 2."})
    assert gct("publish", "restore", "--workspace", gws).code == 0  # back to 1
    status, a = records(srv, {"data_version": 2})
    assert status == 409 and a["cause"] == "Data version 2 is no longer the current one; the current version is 1."
    assert records(srv, {"data_version": 1})[0] == 200
    status, _, body = call(srv.port, "/api/documents/3/cells?sheet=acme-meter&cell=B2&data_version=2", **bearer(srv))
    assert status == 409 and "rows" not in json.loads(body)


# R2: no published version; a projection older than 14
def test_no_version_and_an_older_projection_are_refused(gws, ws, gct, tmp_path):
    r = gct("view", "records", "--workspace", ws, "--json")
    assert r.code == 4 and r.data["cause"] == "There is no published data version yet."
    assert r.data["next_action"] == "Create one with: gct publish build"
    s = server.serve(ws, port=0)
    try:
        status, a = records(s, {})
        assert status == 409 and a["next_action"] == "Create one with: gct publish build"
    finally:
        s.stop()
    for schema in ("13", "5"):
        with sqlite3.connect(published.version_path(gws, 1)) as conn:
            conn.execute("UPDATE meta SET value = ? WHERE key = 'projection_schema'", (schema,))
        r = gct("view", "records", "--workspace", gws, "--json")
        assert r.code == 4 and r.data["cause"] == "Data version 1 was built by an older gct and cannot be filtered."
        assert "gct publish build" in r.data["next_action"]


# R2: two companies with the same metric key and period
def test_two_companies_are_separated_and_never_compared(built):
    flt = {"metric": ["ghg_scope_1"], "period": {"from": "2024-04-01", "to": "2025-03-31"}}
    assert ids(ask(built, {**flt, "company": [1]})) == [1] and ids(ask(built, {**flt, "company": [2]})) == [13]
    g = ask(built, flt, shape="graph")
    assert {n["id"] for n in g["nodes"] if n["kind"] == "claim"} == {"claim:1", "claim:13"}
    assert not [e for e in g["edges"] if e["kind"] == "comparison"]


# R2: an unknown period under a period filter
def test_an_unknown_period_is_not_matched_and_is_counted(built):
    a = ask(built, {"company": [2], "period": {"from": "2024-04-01"}})
    assert ids(a) == [13, 15] and a["excluded"] == {"period_unknown": 1}  # 17, "2025"
    assert ask(built, {"company": [1], "period": {"from": "2024-04-01"}})["excluded"] == {"period_unknown": 0}
    assert ask(built, {"company": [2]})["excluded"] == {"period_unknown": 0}  # no period condition


HIDDEN = "2 claims of 1 archived document are not in this or any view. Restore a document to include its claims."


# R2: an archived document; restore brings its claims back on the next version
def test_an_archived_document_is_in_no_shape_until_restored(gws, gct):
    for shape in ("table", "graph", "series", "values"):
        a = ask(gws, {"document": [4]}, shape=shape)
        assert a["matched"] == 0, shape
    a = ask(gws)
    assert a["hidden_by_archive"] == {"documents": 1, "claims": 2, "text": HIDDEN,
                                      "by_document": [{"document_id": 4, "name": "acme-old.pdf", "claims": 2}]}
    assert 9 not in ids(ask(gws, limit=1000))
    assert gct("doc", "restore", "4", *WHO, "--workspace", gws).code == 0
    assert gct("publish", "build", "--workspace", gws).code == 0
    a = ask(gws, {"document": [4]})
    assert ids(a) == [9, 10] and a["hidden_by_archive"]["text"] is None and a["data_version"] == 2


# R2: a deleted document named in the filter
def test_a_deleted_document_is_named_and_has_no_rows(built, gct):
    a = ask(built, {"document": [5, 3]})
    assert ids(a) == [18] and a["deleted_in_filter"] == [{"document_id": 5, "text": "Document 5 was permanently deleted."}]
    a = ask(built, {"document": [5]}, shape="graph")
    assert a["matched"] == 0 and a["drawable"] is False and a["deleted_in_filter"][0]["document_id"] == 5
    r = gct("view", "records", "--filter", '{"document": [5]}', "--workspace", built)
    assert "Document 5 was permanently deleted." in r.out and "No claims match this filter in data version 1." in r.out


# R2: the spreadsheet claim, its row, its node and its cells
def test_a_spreadsheet_claim_carries_its_sheet_and_cell(built, srv):
    (row,) = ask(built, {"document": [3]})["rows"]
    assert (row["claim"]["page"], row["claim"]["sheet"], row["claim"]["cell"]) == (None, "acme-meter", "B2")
    assert row["evidence"]["location"] == {"document": 3, "page": None, "sheet": "acme-meter", "cell": "B2",
                                           "claim_id": 18, "resolved": True, "reason": None}
    g = ask(built, {"document": [3]}, shape="graph")
    assert "cell:3:acme-meter!B2" in {n["id"] for n in g["nodes"]} and not [n for n in g["nodes"] if n["kind"] == "page"]
    period = next(n for n in g["nodes"] if n["kind"] == "period")
    assert period["evidence"] == [{"document": 3, "page": None, "sheet": None, "cell": None, "claim_id": None,
                                   "resolved": False, "reason": "no page: declared in sheet mapping #1 by Ana"}]
    status, _, body = call(srv.port, "/api/documents/3/cells?sheet=acme-meter&cell=B2&data_version=1", **bearer(srv))
    c = json.loads(body)
    assert status == 200 and c["header"][:3] == ["Metric", "Value", "Unit"] and c["row"] == 2
    assert c["cells"][c["column"]] == "700" and c["columns"][c["column"]] == "B" and c["data_version"] == 1


# Review F2 (Moka, 2026-10-23): an unresolved source match keeps the page its reference names; Tables and Graphs open
# what the Evidence view opens
def test_an_unresolved_match_still_opens_its_page(gws, srv, gct):
    from test_gate_tables_graphs import opens
    with sqlite3.connect(gws / "workspace.db") as db:
        # A newer link row for claim 1's reference (append-only; the newest row is the match)
        db.execute("INSERT INTO source_match (evidence_ref_id, run_id, status, reason, config_version, created_at)"
                   " SELECT evidence_ref_id, run_id, 'unresolved', 'page not read: gct read', config_version, 't'"
                   " FROM source_match WHERE evidence_ref_id IN (SELECT e.id FROM evidence_ref e JOIN claim_version v"
                   " ON v.id = e.claim_version_id WHERE v.claim_id = 1)")
    assert gct("publish", "build", "--workspace", gws).code == 0
    (row,) = ask(gws, {"evidence": ["unresolved"]})["rows"]
    page = row["evidence"]["page"]
    assert (row["claim"]["id"], row["evidence"]["text"]) == (1, "unresolved: page not read: gct read")
    assert row["evidence"]["location"] == {"document": row["claim"]["document"], "page": page, "sheet": None,
                                           "cell": None, "claim_id": 1, "resolved": True, "reason": None}
    assert opens(srv, row["evidence"]["location"], 2)
    g = ask(gws, {"evidence": ["unresolved"]}, shape="graph")
    assert f"page:{row['claim']['document']}:{page}" in {n["id"] for n in g["nodes"]}


CELLS = [
    ("/api/documents/1/cells?sheet=s&cell=A1", 409, "Document 1 is a PDF, so it has pages, not cells."),
    ("/api/documents/4/cells?sheet=s&cell=A1", 409, "Document 4 is archived."),
    ("/api/documents/5/cells?sheet=s&cell=A1", 409, "Document 5 was permanently deleted."),
    ("/api/documents/99/cells?sheet=s&cell=A1", 404, "There is no document 99 in data version 1."),
    ("/api/documents/3/cells?cell=B2", 400, "Give the sheet and the cell."),
    ("/api/documents/3/cells?sheet=Sheet9&cell=B2", 404, "Document 3 has no sheet Sheet9."),
    ("/api/documents/3/cells?sheet=acme-meter&cell=B9", 404, "Cell B9 is outside sheet acme-meter."),
    ("/api/documents/3/cells?sheet=acme-meter&cell=H1", 404, "Cell H1 is outside sheet acme-meter."),
    ("/api/documents/3/cells?sheet=acme-meter&cell=b2", 400, "b2 is not a cell such as C7."),
]


@pytest.mark.parametrize("path, code, cause", CELLS, ids=[c[2] for c in CELLS])
def test_the_cells_endpoint_refuses_with_a_next_step(srv, path, code, cause):
    status, _, body = call(srv.port, path, **bearer(srv))
    b = json.loads(body)
    assert (status, b["status"], b["cause"]) == (code, "error", cause) and b["next_action"]


# R2: a claim compared with a claim outside the filter
def test_a_comparison_outside_the_selection_is_counted_not_drawn(built):
    g = ask(built, {"document": [2]}, shape="graph")
    node = {n["id"]: n for n in g["nodes"]}
    assert node["claim:5"]["outside"] == 1 and node["claim:5"]["outside_text"] == "1 related claim outside this selection"
    assert node["claim:6"]["outside"] == 0 and node["claim:6"]["outside_text"] is None
    assert not [e for e in g["edges"] if e["kind"] == "comparison"]
    g = ask(built, {"document": [1, 2]}, shape="graph")
    (edge,) = [e for e in g["edges"] if e["id"] == "comparison:2:5"]
    assert edge["state"] == "restatement" and [x["claim_id"] for x in edge["evidence"]] == [2, 5]


# R2: review records on an older version only
def test_reviews_count_on_the_current_version_only(built):
    (row,) = ask(built, claim_ids=[14])["rows"]
    rv = row["review"]
    assert rv["auditor"] == [] and rv["needs_re_review"] == 1 and rv["corrected"] is True
    assert rv["text"] == "needs renewed review: 1; corrected"
    rows = {r["claim"]["id"]: r["review"] for r in ask(built, limit=1000)["rows"]}
    assert rows[1]["text"] == "company accepted; auditor disputed; disagreement"
    assert rows[1]["disagreement"] == {"company": ["accepted"], "auditor": ["disputed"]}
    assert rows[4]["text"] == "adjudications: 1" and rows[4]["adjudications"] == [
        {"id": 1, "state": "explained difference", "with": 7}]
    assert rows[4]["candidate_pairs"] == [7]
    assert rows[5]["text"] == "no review records"


# R2: contributor text with "verified" stays inside the contributor's text
def test_gcts_own_words_never_say_verified(built, gct):
    texts = []
    for shape in ("table", "graph", "series"):
        a = ask(built, {"document": [1]} if shape != "series" else {"series": ["2b7f0c7666c0"]}, shape=shape)
        rows = a.get("rows") or a.get("points") or [n["row"] for n in a["nodes"] if n["kind"] == "claim"]
        texts += [x for r in rows for x in (r["evidence"]["text"], r["review"]["text"])]
        texts += [a["hidden_by_archive"]["text"], a.get("empty") or "", a.get("reason") or ""]
        texts += [n["label"] for n in a.get("nodes", [])]
    for shape in ("table", "graph", "series"):
        texts.append(gct("view", "records", "--shape", shape, "--filter", '{"document": [1]}', "--workspace", built).out)
    for t in texts:
        assert not re.search(r"verified|assured|certified|compliant", t or "", re.I), t
    g = ask(built, {"document": [1]}, shape="graph")
    (auditor,) = [n for n in g["nodes"] if n["kind"] == "auditor"]
    assert auditor["text"] == f"not {gate_fixture.VERIFIED}" and auditor["self_declared"] is True


# R2: claim ids beside the filter (F11 a)
def test_claim_ids_limit_the_answer_and_list_the_others(built, srv):
    a = ask(built, {"company": [1]}, claim_ids=[13, 1, 9, 999])
    assert ids(a) == [1] and a["matched"] == 1
    assert a["not_found"] == [{"claim_id": i, "reason": "not in data version 1 or not matched by this filter"}
                              for i in (9, 13, 999)]
    g = ask(built, {"company": [1]}, shape="graph", claim_ids=[1, 2])
    assert {n["id"] for n in g["nodes"] if n["kind"] == "claim"} == {"claim:1", "claim:2"}
    assert records(srv, {"claim_ids": list(range(1, 1002))})[0] == 400


# R2: sort by value with claims without a value, every page in turn (F11 b)
def test_paging_a_sort_reads_each_claim_once_with_nulls_last(built, tmp_path):
    copy = tmp_path / "v.db"
    shutil.copy(published.version_path(built, 1), copy)
    with sqlite3.connect(copy) as conn:
        conn.execute("UPDATE claim SET value = NULL WHERE id IN (2, 7, 13, 17)")
    pconn = published.open_version(copy)
    try:
        for way in ("asc", "desc"):
            seen = []
            for offset in range(0, 15, 3):
                a = view.answer(pconn, {}, offset=offset, limit=3, sort=[{"key": "value", "dir": way}])
                seen += [(r["claim"]["value"], r["claim"]["id"]) for r in a["rows"]]
            assert sorted(i for _, i in seen) == EVERY
            known = [v for v, _ in seen if v is not None]
            assert known == sorted(known, reverse=way == "desc")
            assert seen[-4:] == [(None, 2), (None, 7), (None, 13), (None, 17)]  # last either way, by id
        a = view.answer(pconn, {}, offset=100, limit=3)
        assert a["rows"] == [] and a["matched"] == 14 and a["empty"] is None
    finally:
        pconn.close()


def test_the_default_order_is_company_document_page_then_id(built):
    order = [r["claim"]["id"] for r in ask(built, limit=1000)["rows"]]
    assert order == [5, 6, 7, 8, 1, 2, 3, 4, 18, 13, 14, 15, 16, 17]  # acme-2024, acme-2025, acme-meter; Beta


def test_the_graph_limit_refuses_to_draw(built, monkeypatch):
    monkeypatch.setattr(view, "GRAPH_LIMIT", 3)
    g = ask(built, {"document": [1]}, shape="graph")
    assert g["drawable"] is False and g["nodes"] == [] and g["matched"] == 4 and g["graph_limit"] == 3
    assert g["reason"] == "4 claims match; a graph draws at most 3. Narrow the filter."
    assert ask(built, {"document": [3]}, shape="graph")["drawable"] is True


def test_series_shape_needs_one_series(built):
    s = ask(built, {"series": ["2b7f0c7666c0"]}, shape="series")
    assert s["drawable"] and s["series"]["metric_key"] == "ghg_scope_1"
    assert [(p["claim"]["id"], p["period_order"]) for p in s["points"]] == [(6, 0), (2, 1), (5, 1), (1, 2)]
    assert all(p["evidence"]["location"]["resolved"] for p in s["points"])
    assert [(c["claim_a"], c["claim_b"], c["state"]) for c in s["comparisons"]] == [(2, 5, "restatement")]
    assert ask(built, {"metric": ["ghg_scope_1"]}, shape="series")["reason"] == "These claims are in 2 series; pick one."
    assert ask(built, {"document": [7]}, shape="series")["reason"].startswith("These claims are in no series: ")


def test_values_list_the_metric_keys_and_series_of_a_selection(built):
    v = ask(built, {"company": [2]}, shape="values")
    assert set(v) == {"status", "data_version", "filter", "matched", "metric_keys", "series"}
    assert v["metric_keys"] == [{"metric_key": "ghg_scope_1", "claims": 2}, {"metric_key": "waste_total", "claims": 2},
                                {"metric_key": "unmapped", "claims": 1}]
    assert [(s["id"], s["points"]) for s in v["series"]] == [("54f8c286bac9", 2), ("a8ba08a9df9c", 2)]


# R3: no E6 read writes anything
def test_no_read_writes_anything(gws, srv, gct):
    before = dump(gws)
    for body in ({}, {"shape": "graph"}, {"shape": "series", "filter": {"series": ["2b7f0c7666c0"]}},
                 {"shape": "values"}, {"filter": {"company": []}}, {"data_version": 9}, {"claim_ids": [1, 999]}):
        records(srv, body)
    for path in ("/api/documents/3/cells?sheet=acme-meter&cell=B2", "/api/documents/1/cells?sheet=a&cell=A1",
                 "/api/documents/3/cells?sheet=acme-meter&cell=Z9"):
        call(srv.port, path, **bearer(srv))
    for argv in ([], ["--shape", "graph"], ["--shape", "values"], ["--filter", "{}"], ["--filter", "[]"],
                 ["--claims", "1,x"], ["--sort", "value:up"]):
        gct("view", "records", *argv, "--workspace", gws)
        gct("view", "records", *argv, "--workspace", gws, "--json")
    assert dump(gws) == before


# AC 3: the two new routes are guarded like every other
def test_the_new_routes_are_guarded(srv):
    p = srv.port
    status, _ = records(srv, {}, **origin(srv))
    assert status == 200
    assert records(srv, {}, **cookie(srv))[0] == 403  # a cookie without an Origin
    assert records(srv, {}, Origin="http://evil.example", **cookie(srv))[0] == 403
    assert records(srv, {}, **{"X-None": "1"})[0] == 401
    cells = "/api/documents/3/cells?sheet=acme-meter&cell=B2"
    assert call(p, cells, **cookie(srv))[0] == 200 and call(p, cells, **bearer(srv))[0] == 200
    assert call(p, cells)[0] == 401
    assert call(p, cells, Origin="http://evil.example", **cookie(srv))[0] == 403
    assert call(p, cells, Host=f"evil.example:{p}", **cookie(srv))[0] == 403


# AC 5: the command, its text and its JSON
def test_view_records_prints_the_version_and_the_rows(built, gct):
    r = gct("view", "records", "--filter", '{"company": [1]}', "--limit", "2", "--sort", "value:desc",
            "--workspace", built)
    assert r.code == 0
    lines = r.out.splitlines()
    assert lines[0] == "9 claims match in data version 1."
    assert lines[1] == HIDDEN
    assert lines[2].startswith("3  Acme  acme-2025.pdf p1  5,000") and lines[-1] == "Rows 1 to 2 of 9."
    j = gct("view", "records", "--filter", '{"company": [1]}', "--limit", "2", "--sort", "value:desc", "--workspace",
            built, "--json")
    assert j.data == ask(built, {"company": [1]}, limit=2, sort=[{"key": "value", "dir": "desc"}])
    path = Path(built).parent / "f.json"
    path.write_text('{"document": [3]}')
    assert gct("view", "records", "--filter", f"@{path}", "--workspace", built, "--json").data["matched"] == 1
    assert gct("view", "records", "--claims", "1,2", "--workspace", built, "--json").data["matched"] == 2
    assert "view" in gct("--help").out.split("{", 1)[1].split("}", 1)[0]


def test_view_messages_have_cause_next_action_and_no_internals(gws, gct):
    names = internal_names(gws)
    # No F1 field or value word, request field or sort key is a workspace table or column name, so none is exempt.
    contract = {*view.FIELDS, *view.REQUEST, *view.SORTS, *(v for c in view.CHOICES.values() if c for v in c)}
    assert "claim_version_id" in names and not names & contract
    w = ["--workspace", gws]
    cases = [(["--filter", "{"], 2), (["--filter", "[]"], 2), (["--filter", '{"colour": []}'], 2),
             (["--filter", '{"company": ["a"]}'], 2), (["--filter", '{"text": ""}'], 2), (["--filter", "@nowhere.json"], 3),
             (["--sort", "value:up"], 2), (["--sort", "colour"], 2), (["--claims", "1,x"], 2), (["--limit", "0"], 2),
             (["--shape", "values", "--claims", "1"], 2)]
    for argv, code in cases:
        human, machine = gct("view", "records", *argv, *w), gct("view", "records", *argv, *w, "--json")
        assert human.code == machine.code == code and human.out == "", (argv, human.out)
        assert human.err.startswith("error: ") and "\nnext: " in human.err, (argv, human.err)
        assert machine.data["status"] == "error" and machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in [*INTERNAL_WORDS, *names]:
                assert word not in text, (argv, word)
    for shape in ("table", "graph", "series", "values"):
        out = gct("view", "records", "--shape", shape, *w).out
        assert not any(word in out for word in [*INTERNAL_WORDS, *names]), (shape, out)


# docs/views.md lists the exact keys of every object of the answers (AC 7), which 6.2 and 6.3 build on
def test_docs_views_lists_the_exact_keys(built):
    doc = (ROOT / "docs" / "views.md").read_text()
    listed = dict(re.findall(r"^- `([a-z ]+)`: (.+)$", doc, re.M))
    keys = lambda line: {k.strip("` ") for k in line.split(",")}  # noqa: E731
    t, g = ask(built, {"document": [1, 2, 3]}), ask(built, shape="graph")
    s, v = ask(built, {"series": ["2b7f0c7666c0"]}, shape="series"), ask(built, shape="values")
    nodes = {n["kind"]: n for n in g["nodes"]}
    conn = store.connect(built / layout.DB_NAME)
    _, pconn = view.pinned(conn, built)
    conn.close()
    cells = view.cells(pconn, built, 3, "acme-meter", "B2")
    pconn.close()
    found = {
        "table": t, "graph": g, "series": s, "values": v, "row": t["rows"][0], "row claim": t["rows"][0]["claim"],
        "row evidence": t["rows"][0]["evidence"], "row review": t["rows"][0]["review"],
        "location": t["rows"][0]["evidence"]["location"], "claim node": nodes["claim"], "node": nodes["page"],
        "review node": nodes["auditor"], "hyperedge": g["hyperedges"][0],
        "edge": next(e for e in g["edges"] if e["kind"] == "comparison"), "point": s["points"][0],
        "series comparison": s["comparisons"][0], "series info": s["series"], "cells": cells,
        "values metric": v["metric_keys"][0], "values series": v["series"][0],
        "hidden by archive": t["hidden_by_archive"],
    }
    assert set(listed) == set(found), set(listed) ^ set(found)
    for name, obj in found.items():
        assert keys(listed[name]) == set(obj), name
    for kind in ("page", "cell", "period", "boundary", "series"):
        assert set(nodes[kind]) == keys(listed["node"]), kind
    for kind in ("company", "auditor", "flag", "highlight", "adjudication"):
        assert set(nodes[kind]) == keys(listed["review node"]), kind
    assert all(set(e) == keys(listed["edge"]) for e in g["edges"])
