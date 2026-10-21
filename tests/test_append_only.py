import sqlite3

import pytest

from conftest import make_pdf
from gct.stages import Stage, run_stage
from gct.workspace import runs, store


def test_every_table_is_append_only(ws, db, gct, make_file):
    # Put a row in every table so the UPDATE and DELETE actually fire their triggers.
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme")
    page = {"text": [(72, 72, "Scope 1 120 tCO2e"), (72, 120, "Reporting boundary: Report is prepared on a standalone basis.")]}
    gct("doc", "add", make_file("b.pdf", make_pdf([page])), "--company", "Acme")
    gct("read")
    gct("extract")
    gct("contributor", "add", "ana", "--name", "Ana")
    gct("infer")
    who = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked by eye")
    gct("infer", "scope", "1", "--pages", "1", *who)
    gct("infer")
    gct("infer", "resolve", "1", "--field", "period", "--kind", "calendar_year", "--start", "2024-01-01",
        "--end", "2024-12-31", *who)
    gct("expect", "add", "--company", "Acme", "--metric", "water", "--doc", "2")
    gct("pages", "accept", "--doc", "2", "--pages", "1", "--type", "figures", *who)
    gct("gap", "confirm", "1", *who)
    for _ in range(3):  # three builds, so published_purge also holds a row
        gct("publish", "build")
    gct("approve", "spend", "1")
    conn = store.connect(ws / "workspace.db")
    with runs.run(conn, "test stage") as rid:
        run_stage(conn, rid, Stage("tiny", "c1", lambda item, conn: item, lambda item: "v1"), ["a"])
    conn.close()
    tables = [
        r["name"]
        for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name <> 'schema_version'")
    ]
    assert tables
    triggers = db.execute("SELECT tbl_name, sql FROM sqlite_master WHERE type = 'trigger'").fetchall()
    for table in tables:
        sqls = [t["sql"].upper() for t in triggers if t["tbl_name"] == table]
        assert any("BEFORE UPDATE" in s for s in sqls), f"{table} has no UPDATE trigger"
        assert any("BEFORE DELETE" in s for s in sqls), f"{table} has no DELETE trigger"
        first_col = db.execute(f"PRAGMA table_info({table})").fetchone()["name"]
        has_rows = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert has_rows, f"test setup left {table} empty"
        for stmt in (f"UPDATE {table} SET {first_col} = {first_col}", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
                db.execute(stmt)


def test_schema_version_is_the_one_writable_table(db):
    db.execute("UPDATE schema_version SET applied_at = applied_at")
    db.execute("INSERT INTO schema_version (version, applied_at) VALUES (2, 't')")
