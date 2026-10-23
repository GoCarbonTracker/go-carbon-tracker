"""Story 6.4 part A: saved views and guided questions (A1 to A5), on tests/gate_fixture.py. One row of the R2 matrix per
test, unless named otherwise; the G3 backend gate is in tests/test_gate_tables_graphs.py. Synthetic workspaces only."""
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

import gate_fixture
from conftest import make_pdf
from test_api import call, cookie
from test_correct import post
from test_lock import holder
from test_review_api import bearer, origin
from gct.api import server
from gct.stages import saved_view, view
from gct.workspace import layout, published, store

EVERY_FIELD = {
    "company": [2, 1, 1], "document": [1, 2, 6], "metric": ["ghg_scope_1", "unmapped"], "text": "Scope",
    "period": {"from": "2020-04-01"}, "boundary": ["subsidiary_set", "standalone"], "claim_state": ["current"],
    "evidence": ["not-checked", "matched"], "match": ["series", "not-matchable"], "series": ["2b7f0c7666c0"],
    "comparison": ["same", "restatement"], "review": ["corrected", "company-confirmation"],
}
SERIES = "2b7f0c7666c0"  # Acme's Scope 1 (story 6.1's test_view)
LOCKED = "Another gct command is using this workspace."


@pytest.fixture(scope="module")
def built(tmp_path_factory):
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


def later_report(root) -> int:
    """A further Acme report adding two points to its Scope 1 series (FY 2022-23, the same value as before, and FY
    2021-22, new), read, matched and published. Returns the document id."""
    w = ("--workspace", root)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "acme-2023.pdf"
        path.write_bytes(make_pdf([gate_fixture.page([[gate_fixture.SCOPE_1, "tCO2e", "1,000", "900"]],
                                                     ("FY 2022-23", "FY 2021-22"))]))
        doc = gate_fixture.gct("doc", "add", path, "--company", "Acme", *w)["items"][0]["document"]["id"]
    gate_fixture.ready(w, 3)
    gate_fixture.gct("publish", "build", *w)
    return doc


def dump(root) -> dict:
    """Every row of every table of workspace.db (R3)."""
    with sqlite3.connect(root / layout.DB_NAME) as conn:
        tables = [t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {t: sorted(map(repr, conn.execute(f"SELECT * FROM {t}"))) for t in tables}


def rows(root) -> list[tuple]:
    with sqlite3.connect(root / layout.DB_NAME) as conn:
        return conn.execute("SELECT * FROM saved_view ORDER BY id").fetchall()


def save(gct, root, name, flt, *extra):
    return gct("view", "save", name, "--filter", json.dumps(flt), *extra, "--as", "ana", "--workspace", root, "--json")


def opened(gct, root, name, *extra) -> dict:
    r = gct("view", "open", name, *extra, "--workspace", root, "--json")
    assert r.code == 0, r.out
    return r.data


def records(gct, root, flt, *extra) -> dict:
    return gct("view", "records", "--filter", json.dumps(flt), *extra, "--workspace", root, "--json").data


def without_view(answer: dict) -> dict:
    return {k: v for k, v in answer.items() if k != "view"}


# R2: save and open a filter with every F1 field, and the empty filter
@pytest.mark.parametrize("flt", [EVERY_FIELD, {}, {"company": [1]}], ids=["every field", "empty", "company"])
def test_save_stores_the_normalised_filter_and_open_answers_what_records_answers(gws, gct, flt):
    r = save(gct, gws, "v", flt)
    assert r.code == 0, r.out
    normal = view.normalise(flt)
    assert r.data["view"]["filter"] == normal and r.data["data_version"] == 1
    assert [(x[1], x[2], json.loads(x[3]), x[4]) for x in rows(gws)] == [("v", "save", normal, "tables")]
    assert without_view(opened(gct, gws, "v")) == records(gct, gws, flt)
    assert without_view(opened(gct, gws, "v", "--shape", "graph")) == records(gct, gws, flt, "--shape", "graph")
    assert without_view(opened(gct, gws, "v", "--limit", "3", "--offset", "2", "--sort", "value:desc")) == records(
        gct, gws, flt, "--limit", "3", "--offset", "2", "--sort", "value:desc")
    assert save(gct, gws, "g", flt, "--section", "graphs").code == 0
    assert without_view(opened(gct, gws, "g")) == records(gct, gws, flt, "--shape", "graph")


# R2: name empty, 81 characters, with a line break, control characters only; section maps; bad filters
BAD = [
    ("", {}, [], "The saved view name is empty."),
    ("   ", {}, [], "The saved view name is empty."),
    ("x" * 81, {}, [], "The saved view name is longer than 80 characters."),
    ("a\nb", {}, [], "The saved view name has a line break or another control character."),
    ("\x01\x02", {}, [], "The saved view name has a line break or another control character."),
    ("v", {}, ["--section", "maps"], "The section maps is not tables or graphs."),
    ("v", {"colour": [1]}, [], "The filter has no field colour."),
    ("v", {"company": []}, [], "The filter field company is not a list of one or more values."),
    ("v", {"text": "x" * 201}, [], "The filter field text is not text of 1 to 200 characters."),
]


@pytest.mark.parametrize("name, flt, extra, cause", BAD, ids=[c[3] + str(i) for i, c in enumerate(BAD)])
def test_a_bad_name_section_or_filter_is_refused_and_writes_nothing(gws, srv, gct, name, flt, extra, cause):
    before = dump(gws)
    r = save(gct, gws, name, flt, *extra)
    assert r.code == 2 and r.data["cause"] == cause and r.data["next_action"], r.data
    body = {"name": name, "filter": flt, "contributor": "ana", **({"section": extra[1]} if extra else {})}
    status, data = post(srv, "/api/views", body, **bearer(srv))
    assert status == 400 and data["cause"] == cause
    assert dump(gws) == before


# R2: unknown contributor key
def test_an_unknown_contributor_is_refused_with_the_add_line(gws, srv, gct):
    before = dump(gws)
    r = gct("view", "save", "v", "--filter", "{}", "--as", "zed", "--workspace", gws, "--json")
    assert r.code == 3 and r.data["next_action"] == "Add one with: gct contributor add zed --name NAME"
    status, data = post(srv, "/api/views", {"name": "v", "filter": {}, "contributor": "zed"}, **bearer(srv))
    assert status == 404 and "gct contributor add zed" in data["next_action"]
    assert save(gct, gws, "w", {}).code == 0
    r = gct("view", "remove", "w", "--as", "zed", "--workspace", gws, "--json")
    assert r.code == 3 and "gct contributor add zed" in r.data["next_action"]
    assert len(rows(gws)) == 1 and {k for k, v in dump(gws).items() if v != before[k]} == {"saved_view"}


# R2: save twice under one name, different filters; two names with one filter; case and spaces
def test_a_second_save_under_a_name_comes_first_and_keeps_the_earlier(gws, gct):
    assert save(gct, gws, "Scope", {"company": [1]}).code == 0
    r = save(gct, gws, "Scope", {"company": [2]}, "--section", "graphs")
    assert r.data["view"]["earlier"] == 1 and r.data["view"]["filter"] == {"company": [2]}
    assert len(rows(gws)) == 2
    for name in ("Other", "  scope  "):
        assert save(gct, gws, name, {"company": [2]}).code == 0
    listed = gct("view", "list", "--workspace", gws, "--json").data
    assert [(v["name"], v["filter"], v["earlier"]) for v in listed["views"]] == [
        ("Other", {"company": [2]}, 0), ("Scope", {"company": [2]}, 1), ("scope", {"company": [2]}, 0)]
    assert listed["hidden"] == 0 and listed["data_version"] == 1
    o = opened(gct, gws, "Scope")
    assert o["view"]["section"] == "graphs" and o["matched"] == 5 and "nodes" in o


# R2: remove, then list, open, remove again; then save again under the name
def test_a_removed_view_is_not_listed_and_can_be_saved_again(gws, gct):
    assert save(gct, gws, "Scope 1", {"company": [1]}).code == 0
    r = gct("view", "remove", "Scope 1", "--as", "ana", "--workspace", gws, "--json")
    assert r.code == 0 and r.data["removed"]["name"] == "Scope 1" and r.data["removed"]["contributor"] == "Ana"
    assert r.data["data_version"] == 1
    day = r.data["removed"]["removed_at"][:10]
    assert gct("view", "list", "--workspace", gws, "--json").data == {
        "status": "ok", "data_version": 1, "views": [], "hidden": 1}
    for argv in (["open", "Scope 1"], ["remove", "Scope 1", "--as", "ana"]):
        r = gct("view", *argv, "--workspace", gws, "--json")
        assert r.code == 3 and r.data["cause"] == f"Saved view Scope 1 was removed on {day}."
        assert r.data["next_action"] == "Save it again with: gct view save 'Scope 1' --filter JSON --as KEY"
    for argv in (["open", "Nobody"], ["remove", "Nobody", "--as", "ana"]):
        r = gct("view", *argv, "--workspace", gws, "--json")
        assert r.code == 3 and r.data["cause"] == "There is no saved view named Nobody."
        assert r.data["next_action"] == "See the saved views with: gct view list"
    assert save(gct, gws, "Scope 1", {"company": [2]}).data["view"]["earlier"] == 1
    listed = gct("view", "list", "--workspace", gws, "--json").data
    assert [v["name"] for v in listed["views"]] == ["Scope 1"] and listed["hidden"] == 0
    assert [x[2] for x in rows(gws)] == ["save", "remove", "save"]


# R2: a filter naming a series; a new report adds points to that series (series id is a hash of its key)
def test_a_view_of_a_series_takes_in_the_points_of_a_later_report(gws, gct):
    assert save(gct, gws, "series", {"series": [SERIES]}, "--section", "graphs").code == 0
    before = opened(gct, gws, "series", "--shape", "table")
    doc = later_report(gws)
    after = opened(gct, gws, "series", "--shape", "table")
    new = {r["claim"]["id"] for r in after["rows"]} - {r["claim"]["id"] for r in before["rows"]}
    assert after["data_version"] == 2 and len(new) == 2
    assert {r["claim"]["document"] for r in after["rows"] if r["claim"]["id"] in new} == {doc}
    s = opened(gct, gws, "series", "--shape", "series")
    assert s["drawable"] and len(s["points"]) == after["matched"] == before["matched"] + 2


# R2: a document named in the filter is deleted
def test_deleting_a_document_leaves_the_view_as_it_was(gws, gct):
    assert save(gct, gws, "balance", {"document": [7]}).code == 0
    kept = rows(gws)
    w = ("--workspace", gws)
    token = gct("doc", "delete", "7", *w, "--json").data["token"]
    assert gct("doc", "delete", "7", "--confirm", token, "--as", "ana", "--capacity", "analyst", "--rationale", "r",
               *w).code == 0
    assert rows(gws) == kept
    assert gct("publish", "build", *w).code == 0
    o = opened(gct, gws, "balance")
    assert o["matched"] == 0 and o["deleted_in_filter"] == [{"document_id": 7, "text": "Document 7 was permanently deleted."}]
    assert "Document 7 was permanently deleted." in gct("view", "open", "balance", *w).out


# R2: a stored filter no longer accepted
def test_a_stored_filter_that_is_no_longer_accepted_is_refused_naming_the_field(gws, gct):
    with sqlite3.connect(gws / layout.DB_NAME) as conn:
        conn.execute("INSERT INTO saved_view (name, action, filter, section, contributor_version_id, created_at)"
                     " VALUES ('old', 'save', '{\"colour\": [1]}', 'tables', 1, 't')")
    before = dump(gws)
    r = gct("view", "open", "old", "--workspace", gws, "--json")
    assert r.code == 2 and r.data["cause"] == "The filter has no field colour."
    assert dump(gws) == before


# R2: a graphs view matching more than the graph limit
def test_a_graphs_view_over_the_limit_says_so(gws, gct, monkeypatch):
    monkeypatch.setattr(view, "GRAPH_LIMIT", 3)
    assert save(gct, gws, "all", {}, "--section", "graphs").code == 0
    o = opened(gct, gws, "all")
    assert o["drawable"] is False and o["nodes"] == [] and o["reason"] == "14 claims match; a graph draws at most 3." \
                                                                         " Narrow the filter."


# R2: save through the API while the CLI holds the lock
def test_a_save_while_the_workspace_is_locked_is_refused(gws, srv):
    before = dump(gws)
    p = holder(gws)
    try:
        for path, body in (("/api/views", {"name": "v", "filter": {}, "contributor": "ana"}),
                           ("/api/views/remove", {"name": "v", "contributor": "ana"})):
            status, data = post(srv, path, body, **bearer(srv))
            assert status == 409 and data["cause"] == LOCKED, path
    finally:
        p.kill()
        p.wait()
    assert dump(gws) == before


# R2 and R3 (A5, AC 4): a save and a removal through the API add one row each and build nothing
def test_an_api_save_and_removal_add_one_row_and_build_nothing(gws, srv, gct):
    status_before = gct("publish", "status", "--workspace", gws, "--json").data
    before = dump(gws)
    status, data = post(srv, "/api/views", {"name": "v", "filter": {"company": [1]}, "contributor": "ana"},
                        **origin(srv))
    assert status == 200 and data["data_version"] == 1
    cli = gct("view", "list", "--workspace", gws, "--json").data
    assert data == {"status": "ok", "view": cli["views"][0], "data_version": 1}
    status, _, listed = call(srv.port, "/api/views", **cookie(srv))
    assert status == 200 and json.loads(listed) == cli
    after = dump(gws)
    assert {t for t in before if after[t] != before[t]} == {"saved_view"} and len(after["saved_view"]) == 1
    status, data = post(srv, "/api/views/remove", {"name": "v", "contributor": "ana"}, **bearer(srv))
    assert status == 200 and data["removed"]["name"] == "v" and data["data_version"] == 1
    final = dump(gws)
    assert {t for t in before if final[t] != before[t]} == {"saved_view"} and len(final["saved_view"]) == 2
    assert gct("publish", "status", "--workspace", gws, "--json").data == status_before
    assert sorted(p.name for p in (gws / "published").iterdir()) == ["v1.db"]


# R2: the guard, Origin and content type on the new routes
def test_the_new_routes_are_guarded(gws, srv):
    body = {"name": "v", "filter": {}, "contributor": "ana"}
    for path in ("/api/views", "/api/views/remove"):
        assert post(srv, path, body, **cookie(srv))[0] == 403  # a cookie without an Origin
        assert post(srv, path, body, Origin="http://evil.example", **cookie(srv))[0] == 403
        assert post(srv, path, body)[0] == 401
        assert post(srv, path, b"name=v", "application/x-www-form-urlencoded", **origin(srv))[0] == 415
        assert post(srv, path, [body], **origin(srv))[0] == 400
        assert post(srv, path, {**body, "name": 7}, **origin(srv))[1]["cause"] == "The saved view field name is not text."
        assert post(srv, path, {"name": "v"}, **origin(srv))[1]["cause"] == "The saved view field contributor is missing."
    status, data = post(srv, "/api/views", {**body, "filter": "{}"}, **origin(srv))
    assert status == 400 and data["cause"] == "The saved view field filter is not a JSON object."
    assert post(srv, "/api/views", {"name": "v", "contributor": "ana"}, **origin(srv))[0] == 400
    p = srv.port
    for path in ("/api/views", "/api/questions"):
        assert call(p, path, **cookie(srv))[0] == 200 and call(p, path, **bearer(srv))[0] == 200
        assert call(p, path)[0] == 401
        assert call(p, path, Host=f"evil.example:{p}", **cookie(srv))[0] == 403
    assert post(srv, "/api/views/remove", body, Host=f"evil.example:{p}", **bearer(srv))[0] == 403
    assert rows(gws) == []


# R2: no published version; a projection below 14
def test_open_and_questions_need_a_version_and_save_list_remove_do_not(gws, ws, gct):
    w = ("--workspace", ws)
    assert gct("contributor", "add", "ana", "--name", "Ana", *w).code == 0
    r = gct("view", "save", "v", "--filter", "{}", "--as", "ana", *w, "--json")
    assert r.code == 0 and r.data["data_version"] is None
    assert gct("view", "list", *w, "--json").data["data_version"] is None
    for argv in (["open", "v"], ["questions"]):
        r = gct("view", *argv, *w, "--json")
        assert r.code == 4 and r.data["cause"] == "There is no published data version yet."
        assert r.data["next_action"] == "Create one with: gct publish build"
    s = server.serve(ws, port=0)
    try:
        status, _, data = call(s.port, "/api/questions", **bearer(s))
        assert status == 409 and json.loads(data)["next_action"] == "Create one with: gct publish build"
        assert call(s.port, "/api/views", **bearer(s))[0] == 200
    finally:
        s.stop()
    r = gct("view", "remove", "v", "--as", "ana", *w, "--json")
    assert r.code == 0 and r.data["data_version"] is None
    assert save(gct, gws, "v", {}).code == 0
    with sqlite3.connect(published.version_path(gws, 1)) as conn:
        conn.execute("UPDATE meta SET value = '13' WHERE key = 'projection_schema'")
    for argv in (["open", "v"], ["questions"]):
        r = gct("view", *argv, "--workspace", gws, "--json")
        assert r.code == 4 and r.data["cause"] == "Data version 1 was built by an older gct and cannot be filtered."


# R2: a workspace upgraded from 0019 and from 0017
@pytest.mark.parametrize("old", [17, 19])
def test_migration_20_applies_in_order_and_the_table_is_insert_only(tmp_path, gct, monkeypatch, old):
    real = store.migrate
    monkeypatch.setattr(store, "migrate", lambda conn, up_to=None: real(conn, old))
    root = tmp_path / "old"
    assert gct("workspace", "init", root).code == 0
    assert gct("contributor", "add", "ana", "--name", "Ana", "--workspace", root).code == 0
    db = sqlite3.connect(root / "workspace.db")
    assert db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == old
    monkeypatch.setattr(store, "migrate", real)
    assert gct("view", "list", "--workspace", root).code == 0
    assert [v for (v,) in db.execute("SELECT version FROM schema_version ORDER BY version")][old - 1:] == list(
        range(old, 21))
    notes = [m for (m,) in db.execute("SELECT message FROM run_event WHERE kind = 'note' ORDER BY id")]
    assert notes == [f"applied migration {n}" for n in range(old + 1, 21)]
    assert db.execute("SELECT COUNT(*) FROM saved_view").fetchone()[0] == 0
    assert gct("view", "save", "v", "--filter", "{}", "--as", "ana", "--workspace", root).code == 0
    for stmt in ("UPDATE saved_view SET name = 'x'", "DELETE FROM saved_view"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
            db.execute(stmt)
    for bad in ("('v', 'save', NULL, 'tables', 1, 't')", "('v', 'save', 'not json', 'tables', 1, 't')",
                "('v', 'remove', '{}', 'tables', 1, 't')", "('v', 'keep', '{}', 'tables', 1, 't')",
                "('v', 'save', '{}', 'maps', 1, 't')"):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO saved_view (name, action, filter, section, contributor_version_id, created_at)"
                       f" VALUES {bad}")
    db.close()


# R2 and AC 5: the guided questions on the G1 fixture; each count is what gct view records gives for its filter
def test_each_guided_question_counts_what_records_counts(built, gct):
    q = gct("view", "questions", "--workspace", built, "--json").data
    assert q["data_version"] == 1 and [x["key"] for x in q["questions"]] == [k for k, _, _, _ in saved_view.QUESTIONS]
    for x in q["questions"]:
        r = records(gct, built, x["filter"])
        assert x["matched"] == r["matched"] and x["filter"] == r["filter"], x["key"]
        assert set(x) == {"key", "text", "filter", "section", "matched", "choices"}
        assert (x["choices"] == []) is (x["key"] != "metric-over-time")
    counts = {x["key"]: x["matched"] for x in q["questions"]}
    assert counts == {"restated": 2, "different-values": 2, "metric-over-time": 13, "not-matched-to-source": 0,
                      "ledgers-disagree": 1, "needs-renewed-review": 1}
    choices = q["questions"][2]["choices"]
    values = records(gct, built, {}, "--shape", "values")["series"]
    assert len(choices) == 4 and {c["company"] for c in choices} == {"Acme", "Beta"}
    for c in choices:
        assert set(c) == {"series", "company", "label", "periods", "filter"} and c["filter"] == {"series": [c["series"]]}
        s = records(gct, built, c["filter"], "--shape", "series")
        assert s["drawable"] and len({(p["period_start"], p["period_end"]) for p in s["points"]}) == c["periods"] >= 2
    assert {c["series"] for c in choices} < {s["id"] for s in values}
    out = gct("view", "questions", "--workspace", built).out
    assert "metric-over-time  How did one figure change across reports?  4 series with two or more periods" in out
    assert "not-matched-to-source  Which figures could not be matched to their place in the source?  0 claims in" \
           " data version 1 (tables)" in out


def test_the_questions_endpoint_answers_what_the_command_answers(built, gct):
    s = server.serve(built, port=0)
    try:
        status, _, body = call(s.port, "/api/questions", **bearer(s))
        assert status == 200 and json.loads(body) == gct("view", "questions", "--workspace", built, "--json").data
        status, _, body = call(s.port, "/api/questions?data_version=9", **bearer(s))
        assert status == 409 and json.loads(body)["cause"].startswith("Data version 9 is no longer the current one")
        assert call(s.port, "/api/questions?data_version=x", **bearer(s))[0] == 400
        assert call(s.port, "/api/questions?data_version=1", **bearer(s))[0] == 200
    finally:
        s.stop()


# R2: claim_ids (6.1 F11 a) re-checked: an older version and unknown ids
def test_claim_ids_on_an_older_version_and_unknown_ids(gws, srv, gct):
    status, data = post(srv, "/api/records", {"claim_ids": [1, 999]}, **bearer(srv))
    assert status == 200 and [x["claim_id"] for x in data["not_found"]] == [999]
    assert gct("publish", "build", "--workspace", gws).code == 0
    status, data = post(srv, "/api/records", {"claim_ids": [1], "data_version": 1}, **bearer(srv))
    assert status == 409 and data["cause"] == ("Data version 1 is no longer the current one; the current version is"
                                               " 2.")


# R2: a view name typed with "verified"; GCT's own words never say verified, assured, certified or compliant
def test_gcts_own_words_never_say_verified(gws, gct):
    name = "verified figures"
    w = ("--workspace", gws)
    outs = [gct("view", "save", name, "--filter", "{}", "--as", "ana", *w).out, gct("view", "list", *w).out,
            gct("view", "open", name, *w).out, gct("view", "remove", name, "--as", "ana", *w).out,
            gct("view", "open", name, *w).err, gct("view", "questions", *w).out]
    assert name in outs[0] and name in outs[1]
    for out in outs:
        own = out.replace(name, "").replace(gate_fixture.VERIFIED, "").lower()
        assert not any(word in own for word in ("verified", "assured", "certified", "compliant")), out
    for _, text, _, _ in saved_view.QUESTIONS:
        assert not any(word in text.lower() for word in ("verified", "assured", "certified", "compliant"))


# R3: listing, opening and the questions write nothing, on the command line and through the API
def test_no_read_writes_anything(gws, srv, gct):
    assert save(gct, gws, "v", {"company": [1]}).code == 0
    before = dump(gws)
    w = ("--workspace", gws)
    for argv in (["list"], ["open", "v"], ["open", "v", "--shape", "graph"], ["open", "nobody"], ["questions"],
                 ["open", "v", "--sort", "value:up"]):
        gct("view", *argv, *w)
        gct("view", *argv, *w, "--json")
    for path in ("/api/views", "/api/questions", "/api/questions?data_version=9"):
        call(srv.port, path, **bearer(srv))
    assert dump(gws) == before
