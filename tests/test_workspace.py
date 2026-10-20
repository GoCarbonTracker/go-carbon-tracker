import sqlite3

import pytest

from gct.workspace import store

EXPECTED_COLUMNS = {
    "schema_version": ["version", "applied_at"],
    "workspace": ["id", "created_at", "gct_version"],
    "company": ["id", "name", "sector_ref", "sector_version", "created_at"],
    "document": [
        "id", "company_id", "logical_name", "version", "sha256", "kind", "file_type",
        "privacy", "size_bytes", "source", "created_at",
    ],
    "document_state": ["id", "document_id", "state", "note", "at"],
    "published_version": ["id", "version", "built_at", "history_mark", "companies", "documents", "gct_version"],
    "published_pointer": ["id", "version", "action", "at"],
    "published_purge": ["id", "version", "reason", "at"],
    "run": ["id", "started_at", "command", "gct_version"],
    "run_event": [
        "id", "run_id", "at", "kind", "stage", "item", "method", "outcome", "cost_estimated", "cost_confirmed", "message",
    ],
    "attempt": [
        "id", "run_id", "stage", "item", "input_version", "config_version", "method", "rung", "outcome", "output",
        "error", "cost_estimated", "cost_confirmed", "at",
    ],
    "artifact": ["id", "sha256", "kind", "document_id", "path", "size_bytes", "created_at"],
    "page": [
        "id", "document_id", "page_number", "rung", "method", "config_version", "width", "height", "words", "tables",
        "flags", "artifact_id", "created_at",
    ],
}
NULLABLE = {("company", "sector_ref"), ("company", "sector_version"), ("document", "source"), ("document_state", "note")} | {
    ("run_event", c) for c in ("stage", "item", "method", "outcome", "cost_estimated", "cost_confirmed", "message")
} | {("attempt", c) for c in ("method", "rung", "output", "error", "cost_estimated", "cost_confirmed")}


def test_init_creates_exact_layout(ws):
    assert {p.name for p in ws.iterdir()} == {
        "workspace.db", "files", "artifacts", "published", "exports", "logs",
    }
    for name in ("files", "artifacts", "published", "exports", "logs"):
        assert list((ws / name).iterdir()) == []


def test_tables_and_columns(db):
    tables = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == set(EXPECTED_COLUMNS)
    for table, columns in EXPECTED_COLUMNS.items():
        info = db.execute(f"PRAGMA table_info({table})").fetchall()
        assert [r["name"] for r in info] == columns
        for r in info:
            if r["name"] != "id":
                assert bool(r["notnull"]) == ((table, r["name"]) not in NULLABLE), (table, r["name"])


def test_schema_version_row_and_workspace_row(db):
    assert [r["version"] for r in db.execute("SELECT version FROM schema_version")] == [1, 2, 3, 4, 5]
    row = db.execute("SELECT * FROM workspace").fetchone()
    assert row["id"] == 1 and row["gct_version"]


def test_check_constraints(db):
    db.execute("INSERT INTO company (name, created_at) VALUES ('A', 't')")
    base = "INSERT INTO document (company_id, logical_name, version, sha256, kind, file_type, privacy, size_bytes, created_at) VALUES (1, 'n', 1, 's', ?, ?, ?, 1, 't')"
    db.execute(base, ("report", "pdf", "private"))
    for bad in (("memo", "pdf", "private"), ("report", "docx", "private"), ("report", "pdf", "public")):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(base.replace("'n', 1", "'m', 2"), bad)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO document_state (document_id, state, at) VALUES (1, 'gone', 't')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (2, 't', 'v')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO company (name, created_at) VALUES ('A', 't')")


def test_unique_company_logical_name_version(db):
    db.execute("INSERT INTO company (name, created_at) VALUES ('A', 't')")
    row = "INSERT INTO document (company_id, logical_name, version, sha256, kind, file_type, privacy, size_bytes, created_at) VALUES (1, 'n', 1, 's', 'report', 'pdf', 'private', 1, 't')"
    db.execute(row)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(row)


def test_wal_and_foreign_keys(ws, db):
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn = store.connect(ws / "workspace.db")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO document (company_id, logical_name, version, sha256, kind, file_type, privacy, size_bytes, created_at)"
            " VALUES (99, 'n', 1, 's', 'report', 'pdf', 'private', 1, 't')"
        )
    conn.close()


def test_init_refuses_non_empty_folder(tmp_path, gct):
    (tmp_path / "stuff.txt").write_text("x")
    r = gct("workspace", "init", tmp_path)
    assert r.code == 4 and "not empty" in r.err


def test_init_existing_workspace_changes_nothing(ws, gct):
    before = {p: p.read_bytes() for p in ws.rglob("*") if p.is_file()}
    r = gct("workspace", "init", ws, "--json")
    assert r.code == 0 and r.data["status"] == "already_initialised"
    assert {p: p.read_bytes() for p in ws.rglob("*") if p.is_file()} == before


def test_init_accepts_empty_existing_folder(tmp_path, gct):
    (tmp_path / "empty").mkdir()
    assert gct("workspace", "init", tmp_path / "empty").code == 0


def test_discovery_order(tmp_path, ws, gct, monkeypatch):
    other = tmp_path / "other"
    assert gct("workspace", "init", other).code == 0
    gct("company", "add", "InOther", "--workspace", other)
    monkeypatch.chdir(tmp_path)  # no workspace here or above
    monkeypatch.delenv("GCT_WORKSPACE", raising=False)
    assert gct("company", "list").code == 3
    # --workspace
    assert [c["name"] for c in gct("company", "list", "--workspace", other, "--json").data["companies"]] == ["InOther"]
    # environment variable
    monkeypatch.setenv("GCT_WORKSPACE", str(other))
    assert len(gct("company", "list", "--json").data["companies"]) == 1
    # --workspace wins over the variable
    assert gct("company", "list", "--workspace", ws, "--json").data["companies"] == []
    # nearest parent
    monkeypatch.delenv("GCT_WORKSPACE")
    monkeypatch.chdir(ws / "files")
    assert gct("company", "list", "--json").code == 0


def test_no_workspace_message_names_three_ways(tmp_path, gct, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GCT_WORKSPACE", raising=False)
    r = gct("company", "list")
    assert r.code == 3
    assert "--workspace" in r.err and "GCT_WORKSPACE" in r.err and "inside a workspace" in r.err
