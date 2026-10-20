import sqlite3
from contextlib import contextmanager

from gct import __version__
from gct.workspace import store
from gct.workspace.layout import NOT_FOUND, GctError

EVENT_COLUMNS = ("id", "at", "kind", "stage", "item", "method", "outcome", "cost_estimated", "cost_confirmed", "message")

# Every insert below is a single statement on an autocommit connection, so it commits on its own:
# an interrupted process keeps the events written so far.
RUN_SQL = """
SELECT r.id, r.started_at, f.at AS finished_at, r.command, r.gct_version,
       COALESCE(f.outcome, 'interrupted') AS outcome,
       (SELECT COUNT(*) FROM run_event e WHERE e.run_id = r.id) AS events
FROM run r LEFT JOIN run_event f ON f.run_id = r.id AND f.kind = 'finished'
    AND f.id = (SELECT MIN(id) FROM run_event WHERE run_id = r.id AND kind = 'finished')
"""


def start(conn: sqlite3.Connection, command: str) -> int:
    return conn.execute(
        "INSERT INTO run (started_at, command, gct_version) VALUES (?, ?, ?)", (store.now(), command, __version__)
    ).lastrowid


def event(conn, run_id, kind, *, stage=None, item=None, method=None, outcome=None,
          cost_estimated=None, cost_confirmed=None, message=None) -> int:
    return conn.execute(
        "INSERT INTO run_event (run_id, at, kind, stage, item, method, outcome, cost_estimated, cost_confirmed, message)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, store.now(), kind, stage, item, method, outcome, cost_estimated, cost_confirmed, message),
    ).lastrowid


def finish(conn: sqlite3.Connection, run_id: int, outcome: str, message: str | None = None) -> None:
    event(conn, run_id, "finished", outcome=outcome, message=message)


@contextmanager
def run(conn: sqlite3.Connection, command: str):
    """Yield a run id. Finishes ok, or failed with the GctError cause or the exception class name only."""
    run_id = start(conn, command)
    try:
        yield run_id
    except GctError as e:
        finish(conn, run_id, "failed", e.cause)
        raise
    except Exception as e:
        finish(conn, run_id, "failed", type(e).__name__)
        raise
    finish(conn, run_id, "ok")


def list_runs(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(RUN_SQL + " ORDER BY r.id DESC")]


def show_run(conn: sqlite3.Connection, run_id: int) -> dict:
    row = conn.execute(RUN_SQL + " WHERE r.id = ?", (run_id,)).fetchone()
    if row is None:
        raise GctError(NOT_FOUND, f"There is no run with id {run_id}.", "See the runs with: gct run list")
    events = [
        dict(r) for r in conn.execute(f"SELECT {', '.join(EVENT_COLUMNS)} FROM run_event WHERE run_id = ? ORDER BY id", (run_id,))
    ]
    return {
        **dict(row),
        "events": events,
        "methods": sorted({e["method"] for e in events if e["method"] is not None}),
        "failures": sum(e["kind"] == "failure" for e in events),
        "retries": sum(e["kind"] == "retry" for e in events),
        "cost_estimated": sum((e["cost_estimated"] or 0.0 for e in events), 0.0),
        "cost_confirmed": sum((e["cost_confirmed"] or 0.0 for e in events), 0.0),
        "outputs": [f"{e['stage']} {e['item']}" for e in events if e["kind"] == "output"],
    }
