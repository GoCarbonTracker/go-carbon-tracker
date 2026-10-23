import sqlite3

import pytest

from gct.stages import Result, Stage, result, run_stage, status, version_of
from gct.workspace import layout, runs, store
from gct.workspace.layout import REFUSED, GctError


@pytest.fixture
def conn(ws):
    c = store.connect(ws / "workspace.db")
    yield c
    c.close()


def make_stage(calls, versions=None, config="c1", fail=None):
    """A test stage: output is a dict naming the item and its input version; `fail(item)` may raise."""
    versions = versions if versions is not None else {}

    def work(item, conn):
        calls.append(item)
        if fail:
            fail(item)
        return {"item": item, "input": versions.get(item, "v1")}

    return Stage("demo", config, work, lambda item: versions.get(item, "v1"))


def go(conn, stage, items, **kw):
    with runs.run(conn, "test stage") as rid:
        counts = run_stage(conn, rid, stage, items, **kw)
    return rid, counts


def attempts(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM attempt ORDER BY id")]


def kinds(conn, rid):
    return [e["kind"] for e in runs.show_run(conn, rid)["events"]]


def test_version_of():
    assert version_of("a", 1) == version_of("a", "1") != version_of("a1")
    assert len(version_of()) == 64


def test_migration_4_applies_to_a_story_1_3_workspace(tmp_path):
    root = tmp_path / "old"
    root.mkdir()
    conn = store.connect(root / layout.DB_NAME)
    assert store.migrate(conn, up_to=3) == [1, 2, 3]
    conn.execute("INSERT INTO company (name, created_at) VALUES ('Acme', 't')")
    rid = runs.start(conn, "publish build")
    assert store.migrate(conn) == [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
    assert [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY version")] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
    assert [tuple(r) for r in conn.execute("SELECT name, created_at FROM company")] == [("Acme", "t")]
    assert [r["id"] for r in runs.list_runs(conn)] == [rid]
    conn.close()


def test_attempt_rejects_update_and_delete(conn, db):
    go(conn, make_stage([]), ["a"])
    for stmt in ("UPDATE attempt SET outcome = outcome", "DELETE FROM attempt"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
            db.execute(stmt)


def test_cache_hit(conn):
    calls = []
    stage = make_stage(calls)
    assert go(conn, stage, ["a", "b", "c"])[1] == {"processed": 3, "cached": 0, "failed": 0, "skipped": 0}
    before = attempts(conn)
    rid, counts = go(conn, stage, ["a", "b", "c"])
    assert counts == {"processed": 0, "cached": 3, "failed": 0, "skipped": 0}
    assert calls == ["a", "b", "c"] and attempts(conn) == before
    assert kinds(conn, rid) == ["finished"]


def test_input_change_reruns_only_that_item(conn):
    calls, versions = [], {}
    stage = make_stage(calls, versions)
    go(conn, stage, ["a", "b", "c"])
    old_row = attempts(conn)[1]
    versions["b"] = "v2"
    assert go(conn, stage, ["a", "b", "c"])[1]["processed"] == 1
    assert calls == ["a", "b", "c", "b"]
    assert result(conn, "demo", "b", "v1", "c1") == {"item": "b", "input": "v1"}
    assert result(conn, "demo", "b", "v2", "c1") == {"item": "b", "input": "v2"}
    assert attempts(conn)[1] == old_row and len(attempts(conn)) == 4


def test_config_change_reruns_every_item(conn):
    calls = []
    go(conn, make_stage(calls, config="c1"), ["a", "b"])

    def work(item, conn):
        calls.append(item)
        return f"new {item}"

    assert go(conn, Stage("demo", "c2", work, lambda item: "v1"), ["a", "b"])[1]["processed"] == 2
    assert calls == ["a", "b", "a", "b"]
    for item in ("a", "b"):
        assert result(conn, "demo", item, "v1", "c1") == {"item": item, "input": "v1"}
        assert result(conn, "demo", item, "v1", "c2") == f"new {item}"


def failing(item):
    if item == "b":
        raise ValueError("key-xyz")


def test_failure_is_isolated_and_hides_the_message(conn, capsys):
    calls = []
    rid, counts = go(conn, make_stage(calls, fail=failing), ["a", "b", "c"])
    assert counts == {"processed": 2, "cached": 0, "failed": 1, "skipped": 0}
    assert calls == ["a", "b", "c"]
    rows = attempts(conn)
    assert [(r["item"], r["outcome"], r["error"]) for r in rows] == [
        ("a", "ok", None), ("b", "failed", "ValueError"), ("c", "ok", None),
    ]
    events = runs.show_run(conn, rid)["events"]
    (failure,) = [e for e in events if e["kind"] == "failure"]
    assert (failure["stage"], failure["item"], failure["message"]) == ("demo", "b", "ValueError")
    out, err = capsys.readouterr()
    assert "key-xyz" not in "\n".join(conn.iterdump()) + out + err


def test_gct_error_records_its_cause(conn):
    def refuse(item):
        raise GctError(REFUSED, "Page 3 cannot be read.", "Do something.")

    go(conn, make_stage([], fail=refuse), ["a"])
    assert attempts(conn)[0]["error"] == "Page 3 cannot be read."


def test_retry_only_failed(conn):
    go(conn, make_stage([], fail=failing), ["a", "b", "c"])
    calls = []
    rid, counts = go(conn, make_stage(calls), ["a", "b", "c", "d"], only_failed=True)
    assert counts == {"processed": 1, "cached": 2, "failed": 0, "skipped": 1}
    assert calls == ["b"]
    assert [(e["kind"], e["item"]) for e in runs.show_run(conn, rid)["events"]] == [
        ("retry", "b"), ("item", "b"), ("finished", None),
    ]
    rows = attempts(conn)
    assert [(r["item"], r["outcome"]) for r in rows[3:]] == [("b", "ok")]
    assert "d" not in {r["item"] for r in rows}
    assert runs.show_run(conn, rid)["retries"] == 1


def test_interruption_keeps_committed_items(conn):
    def interrupt(item):
        if item == "c":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        go(conn, make_stage([], fail=interrupt), ["a", "b", "c"])
    assert [(r["item"], r["outcome"]) for r in attempts(conn)] == [("a", "ok"), ("b", "ok")]
    assert runs.list_runs(conn)[0]["outcome"] == "interrupted"
    calls = []
    assert go(conn, make_stage(calls), ["a", "b", "c"])[1] == {"processed": 1, "cached": 2, "failed": 0, "skipped": 0}
    assert calls == ["c"]
    assert [(r["item"], r["outcome"]) for r in attempts(conn)] == [("a", "ok"), ("b", "ok"), ("c", "ok")]


def test_status_and_stale_never_served(conn):
    versions = {}
    go(conn, make_stage([], versions, fail=failing), ["a", "b", "s"])
    versions["s"] = "v2"
    assert status(conn, "demo", ["a", "b", "s", "n"], lambda item: versions.get(item, "v1"), "c1") == [
        ("a", "ok"), ("b", "failed"), ("s", "stale"), ("n", "pending"),
    ]
    assert result(conn, "demo", "s", "v2", "c1") is None
    assert status(conn, "demo", ["a"], "v1", "c2") == [("a", "stale")]
    assert result(conn, "demo", "a", "v1", "c2") is None


def test_costs_and_methods_reach_the_run_log(conn):
    stage = Stage("demo", "c1", lambda item, conn: Result("text", "ocr", 2, 0.5, 0.4), lambda item: "v1")
    rid, _ = go(conn, stage, ["p1"])
    (row,) = attempts(conn)
    assert (row["method"], row["rung"], row["cost_estimated"], row["cost_confirmed"]) == ("ocr", 2, 0.5, 0.4)
    shown = runs.show_run(conn, rid)
    assert [(e["kind"], e["method"]) for e in shown["events"]] == [("item", "ocr"), ("cost", "ocr"), ("finished", None)]
    assert shown["methods"] == ["ocr"]
    assert shown["cost_estimated"] == 0.5 and shown["cost_confirmed"] == 0.4


def test_outputs_round_trip(conn):
    nested = {"rows": [[1, 2], ["x", None]], "meta": {"ok": True}}
    outputs = {"d": nested, "n": None}
    go(conn, Stage("demo", "c1", lambda item, conn: outputs[item], lambda item: "v1"), ["d", "n"])
    assert result(conn, "demo", "d", "v1", "c1") == nested
    assert result(conn, "demo", "n", "v1", "c1") is None
    assert attempts(conn)[1]["output"] == "null"
    assert status(conn, "demo", ["n"], "v1", "c1") == [("n", "ok")]


def test_unserialisable_output_is_a_failed_attempt(conn):
    go(conn, Stage("demo", "c1", lambda item, conn: object(), lambda item: "v1"), ["a"])
    assert [(r["outcome"], r["error"]) for r in attempts(conn)] == [("failed", "TypeError")]
