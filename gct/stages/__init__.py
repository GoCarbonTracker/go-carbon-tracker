"""The contract every processing stage runs through: attempts are insert-only, a result is the newest ok attempt for its key."""
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from gct.models.redact import scrub
from gct.workspace import runs, store
from gct.workspace.layout import REFUSED, GctError

KEY = "stage = ? AND item = ? AND input_version = ? AND config_version = ?"


def version_of(*parts) -> str:
    return hashlib.sha256("\x00".join(map(str, parts)).encode("utf-8")).hexdigest()


class SentFailure(GctError):
    """A call that failed after it was sent: its estimated cost still counts as spent."""

    def __init__(self, cause: str, next_action: str, *, cost_estimated: float):
        super().__init__(REFUSED, cause, next_action)
        self.cost_estimated = cost_estimated


@dataclass
class Result:
    output: Any = None
    method: str | None = None
    rung: int | None = None
    cost_estimated: float | None = None
    cost_confirmed: float | None = None


@dataclass
class Stage:
    name: str
    config_version: str
    work: Callable[[Any, sqlite3.Connection], Any]
    input_version: Callable[[Any], str]


def _state(conn, key) -> str | None:
    """'ok' if any ok attempt exists for the key, else 'failed' if any attempt does, else None."""
    row = conn.execute(f"SELECT outcome FROM attempt WHERE {KEY} ORDER BY outcome = 'ok' DESC, id DESC LIMIT 1", key).fetchone()
    return row[0] if row else None


def _attempt(conn, run_id, key, outcome, r: Result, output, error) -> None:
    conn.execute(
        "INSERT INTO attempt (run_id, stage, item, input_version, config_version, method, rung, outcome, output, error,"
        " cost_estimated, cost_confirmed, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, *key, r.method, r.rung, outcome, output, scrub(error), r.cost_estimated, r.cost_confirmed, store.now()),
    )


def run_stage(conn, run_id: int, stage: Stage, items, *, only_failed: bool = False) -> dict:
    """Process the items whose key has no ok attempt. Returns counts processed, cached, failed, skipped."""
    counts = {"processed": 0, "cached": 0, "failed": 0, "skipped": 0}
    for item in items:
        name = str(item)
        key = (stage.name, name, stage.input_version(item), stage.config_version)
        state = _state(conn, key)
        if state == "ok":
            counts["cached"] += 1
            continue
        if state is None and only_failed:
            counts["skipped"] += 1
            continue
        if state == "failed":
            runs.event(conn, run_id, "retry", stage=stage.name, item=name)
        try:
            r = stage.work(item, conn)
            r = r if isinstance(r, Result) else Result(output=r)
            output = json.dumps(r.output)
        except Exception as e:
            error = e.cause if isinstance(e, GctError) else type(e).__name__
            with store.transaction(conn):
                _attempt(conn, run_id, key, "failed", Result(cost_estimated=getattr(e, "cost_estimated", None)), None, error)
                runs.event(conn, run_id, "failure", stage=stage.name, item=name, message=error)
            counts["failed"] += 1
            continue
        with store.transaction(conn):
            _attempt(conn, run_id, key, "ok", r, output, None)
            runs.event(conn, run_id, "item", stage=stage.name, item=name, method=r.method, outcome="ok")
            if r.cost_estimated is not None or r.cost_confirmed is not None:
                runs.event(conn, run_id, "cost", stage=stage.name, item=name, method=r.method,
                           cost_estimated=r.cost_estimated, cost_confirmed=r.cost_confirmed)
        counts["processed"] += 1
    return counts


def result(conn, stage: str, item, input_version: str, config_version: str):
    """The output of the newest ok attempt for exactly this key, or None."""
    row = conn.execute(
        f"SELECT output FROM attempt WHERE {KEY} AND outcome = 'ok' ORDER BY id DESC LIMIT 1",
        (stage, str(item), input_version, config_version),
    ).fetchone()
    return None if row is None else json.loads(row[0])


def status(conn, stage: str, items, input_version, config_version: str) -> list[tuple]:
    """(item, state) with state ok, failed, stale (an ok result exists only under other versions) or pending."""
    out = []
    for item in items:
        iv = input_version(item) if callable(input_version) else input_version
        state = _state(conn, (stage, str(item), iv, config_version))
        if state is None:
            older = conn.execute(
                "SELECT 1 FROM attempt WHERE stage = ? AND item = ? AND outcome = 'ok' LIMIT 1", (stage, str(item))
            ).fetchone()
            # Only failed attempts under other versions leave nothing to reuse, so the item reads pending.
            state = "stale" if older else "pending"
        out.append((item, state))
    return out
