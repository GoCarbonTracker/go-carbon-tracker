import sqlite3

import pytest

from conftest import PDF
from gct.workspace import layout, published, runs, store
from gct.workspace.layout import REFUSED, GctError
from test_messages import INTERNAL_WORDS, internal_names


def counts(path):
    conn = sqlite3.connect(path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    finally:
        conn.close()


@pytest.fixture
def old_ws(tmp_path):
    """A workspace as story 1.2 left it: migrations 1 and 2 only, one company."""
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    conn = store.connect(root / layout.DB_NAME)
    assert store.migrate(conn, up_to=2) == [1, 2]
    conn.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    conn.execute("INSERT INTO company (name, created_at) VALUES ('Acme', 't')")
    conn.close()
    return root


def test_migration_3_applies_to_a_story_1_2_workspace(old_ws):
    conn = store.connect(old_ws / layout.DB_NAME)
    assert store.migrate(conn) == [3, 4, 5, 6, 7, 8, 9]
    assert [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY version")] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert [tuple(r) for r in conn.execute("SELECT name, created_at FROM company")] == [("Acme", "t")]
    assert store.migrate(conn) == []
    conn.close()


def test_fresh_workspace_has_three_migrations(db):
    assert [r[0] for r in db.execute("SELECT version FROM schema_version ORDER BY version")] == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_upgrade_on_open_is_recorded_once(old_ws, gct):
    r = gct("company", "list", "--workspace", old_ws, "--json")
    assert r.code == 0 and [c["name"] for c in r.data["companies"]] == ["Acme"]
    conn = store.connect(old_ws / layout.DB_NAME)
    (run,) = runs.list_runs(conn)
    assert run["command"] == "workspace upgrade" and run["outcome"] == "ok"
    notes = [e for e in runs.show_run(conn, run["id"])["events"] if e["kind"] == "note"]
    assert [e["message"] for e in notes] == ["applied migration 3", "applied migration 4", "applied migration 5", "applied migration 6", "applied migration 7",
                                               "applied migration 8", "applied migration 9"]
    assert gct("company", "list", "--workspace", old_ws).code == 0
    assert len(runs.list_runs(conn)) == 1
    conn.close()


@pytest.mark.parametrize("argv", [
    ["company", "list"], ["company", "add", "Beta"], ["doc", "add", "a.pdf", "--company", "Acme"], ["doc", "list"], ["doc", "show", "1"],
    ["publish", "build"], ["publish", "restore"], ["publish", "status"],
    ["run", "list"], ["run", "show", "1"], ["workspace", "status"],
])
def test_newer_workspace_is_refused_and_untouched(ws, db, gct, argv):
    db.execute("INSERT INTO schema_version (version, applied_at) VALUES (99, 't')")
    db.commit()
    names = internal_names(ws)
    before = counts(ws / "workspace.db")
    for extra in ([], ["--json"]):
        r = gct(*argv, *extra)
        assert r.code == REFUSED, argv
        text = r.out + r.err
        if extra:
            assert r.data["status"] == "error"
            cause, next_action = r.data["cause"], r.data["next_action"]
        else:
            assert r.out == ""
            cause, next_action = r.err.split("\nnext: ")
        assert "newer" in cause and "Install the newer" in next_action
        for word in INTERNAL_WORDS + sorted(names):
            assert word not in text, (argv, word)
    assert counts(ws / "workspace.db") == before


def test_build_and_restore_record_runs(ws, gct):
    conn = store.connect(ws / "workspace.db")
    gct("company", "add", "Acme")
    gct("publish", "build")
    assert gct("publish", "restore").code == REFUSED  # only one version exists
    gct("publish", "build")
    gct("publish", "restore")
    newest = runs.list_runs(conn)
    assert [r["command"] for r in newest] == ["publish restore", "publish build", "publish restore", "publish build"]
    for run, version in zip(newest[:2] + newest[3:], ("1", "2", "1")):
        events = runs.show_run(conn, run["id"])["events"]
        assert [(e["kind"], e["stage"], e["item"]) for e in events] == [
            ("output", "publish", version), ("finished", None, None),
        ]
        assert events[-1]["outcome"] == "ok" and run["outcome"] == "ok"
    refused = runs.show_run(conn, newest[2]["id"])
    assert refused["outcome"] == "failed" and [e["kind"] for e in refused["events"]] == ["finished"]
    assert refused["events"][0]["message"] == "There is no earlier published version to go back to."
    conn.close()


def test_interrupted_run(ws, gct):
    conn = store.connect(ws / "workspace.db")
    run_id = runs.start(conn, "publish build")
    conn.close()
    listed = gct("run", "list", "--json").data["runs"][0]
    shown = gct("run", "show", run_id, "--json").data
    for r in (listed, shown):
        assert r["outcome"] == "interrupted" and r["finished_at"] is None
    assert "interrupted" in gct("run", "list").out
    assert "Outcome: interrupted" in gct("run", "show", run_id).out


def test_two_finished_events_list_the_run_once(ws):
    conn = store.connect(ws / "workspace.db")
    rid = runs.start(conn, "publish build")
    runs.finish(conn, rid, "failed", "first")
    runs.finish(conn, rid, "ok")
    (row,) = runs.list_runs(conn)
    first = runs.show_run(conn, rid)["events"][0]
    assert (row["outcome"], row["finished_at"]) == ("failed", first["at"]) and row["events"] == 2
    assert runs.show_run(conn, rid)["outcome"] == "failed"
    conn.close()


def test_totals(ws, gct):
    conn = store.connect(ws / "workspace.db")
    rid = runs.start(conn, "extract")
    runs.event(conn, rid, "item", item="p1", method="pdfplumber", outcome="ok")
    runs.event(conn, rid, "item", item="p2", method="ocr", outcome="ok")
    runs.event(conn, rid, "failure", message="page unreadable")
    runs.event(conn, rid, "failure", message="page unreadable")
    runs.event(conn, rid, "retry", item="p2")
    runs.event(conn, rid, "cost", cost_estimated=0.5, cost_confirmed=0.4)
    runs.event(conn, rid, "cost", cost_estimated=0.25)
    runs.event(conn, rid, "output", stage="publish", item="2")
    conn.close()
    data = gct("run", "show", rid, "--json").data
    assert data["methods"] == ["ocr", "pdfplumber"]
    assert (data["failures"], data["retries"]) == (2, 1)
    assert data["cost_estimated"] == 0.75 and data["cost_confirmed"] == 0.4
    assert data["outputs"] == ["publish 2"] and len(data["events"]) == 8
    text = gct("run", "show", rid).out
    assert "Estimated cost: 0.75\n" in text and "Confirmed cost: 0.4\n" in text


def test_totals_are_zero_without_costs(ws):
    conn = store.connect(ws / "workspace.db")
    with runs.run(conn, "publish build") as rid:
        pass
    shown = runs.show_run(conn, rid)
    assert shown["cost_estimated"] == 0.0 and shown["cost_confirmed"] == 0.0 and shown["outputs"] == []
    conn.close()


def test_unknown_run(ws, gct):
    r = gct("run", "show", 99, "--json")
    assert r.code == 3 and "gct run list" in r.data["next_action"]


def test_context_manager_failures_keep_events_and_hide_secrets(ws, gct, monkeypatch):
    conn = store.connect(ws / "workspace.db")
    with pytest.raises(GctError):
        with runs.run(conn, "publish build") as rid:
            runs.event(conn, rid, "note", message="before")
            raise GctError(REFUSED, "Refused for a reason.", "Do something.")
    events = runs.show_run(conn, rid)["events"]
    assert [(e["kind"], e["outcome"], e["message"]) for e in events] == [
        ("note", None, "before"), ("finished", "failed", "Refused for a reason."),
    ]
    with pytest.raises(ValueError):
        with runs.run(conn, "publish build") as rid:
            runs.event(conn, rid, "note", message="before")
            raise ValueError("token-abc123")
    assert runs.show_run(conn, rid)["events"][-1]["message"] == "ValueError"

    def boom(*a, **k):
        raise ValueError("token-abc123")

    monkeypatch.setattr(published, "build", boom)
    r = gct("publish", "build")
    assert r.code == 1 and "token-abc123" not in r.out + r.err
    assert runs.list_runs(conn)[0]["outcome"] == "failed"
    assert "token-abc123" not in "\n".join(conn.iterdump())
    conn.close()


def test_workspace_status(ws, gct, make_file):
    fresh = gct("workspace", "status", "--json").data
    assert (fresh["schema_version"], fresh["companies"], fresh["documents"]) == (9, 0, 0)
    assert fresh["published_version"] is None and fresh["runs"] == 0 and fresh["latest_run_outcome"] is None
    assert "Published version: none" in gct("workspace", "status").out
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("a.pdf", PDF), "--company", "Acme")
    gct("doc", "add", make_file("b.pdf", PDF + b"b"), "--company", "Acme")
    gct("publish", "build")
    st = gct("workspace", "status", "--json").data
    assert st["gct_version"] and (st["schema_version"], st["companies"], st["documents"]) == (9, 1, 2)
    assert (st["published_version"], st["runs"], st["latest_run_outcome"]) == (1, 3, "ok")


def test_read_only_commands_write_no_run(ws, gct):
    for argv in (["company", "list"], ["doc", "list"], ["publish", "status"], ["run", "list"], ["workspace", "status"]):
        assert gct(*argv).code == 0
    assert gct("run", "list").out.strip() == "No runs yet."
