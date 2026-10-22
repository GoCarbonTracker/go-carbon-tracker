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
    "approval": ["id", "kind", "provider", "destination", "run_id", "amount", "granted", "created_at"],
    "claim": ["id", "company_id", "document_id", "page_number", "locator", "sector_ref", "sector_version", "created_at"],
    "claim_version": [
        "id", "claim_id", "run_id", "method", "config_version", "metric_text", "value_text", "value", "unit_text",
        "period_label", "period_kind", "period_start", "period_end", "metric_key", "reporting_boundary",
        "boundary_detail", "created_at", "boundary_label",
    ],
    "correction": [
        "id", "claim_version_id", "corrects_version_id", "fields", "contributor_version_id", "capacity", "rationale",
        "created_at",
    ],
    "claim_seen": ["id", "claim_version_id", "page_id", "config_version", "run_id", "created_at"],
    "evidence_ref": ["id", "claim_version_id", "document_id", "page_number", "boxes", "sheet", "cell", "created_at"],
    "source_match": ["id", "evidence_ref_id", "run_id", "status", "reason", "artifact_id", "config_version", "created_at"],
    "contributor_version": ["id", "contributor_key", "name", "organisation", "created_at"],
    "expected_item": ["id", "company_id", "metric_text", "period_label", "created_at"],
    "expected_item_document": ["expected_item_id", "document_id"],
    "page_acceptance": [
        "id", "document_id", "page_number", "content_type", "artifact_id", "contributor_version_id", "capacity",
        "rationale", "created_at",
    ],
    "gap_confirmation": [
        "id", "expected_item_id", "contributor_version_id", "capacity", "rationale", "documents_checked", "created_at",
    ],
    "basis": [
        "id", "document_id", "page_number", "kind", "wording", "fy_end", "period_start", "period_end", "boundary",
        "boundary_detail", "run_id", "config_version", "created_at",
    ],
    "basis_scope": [
        "id", "basis_id", "first_page", "last_page", "contributor_version_id", "capacity", "rationale", "created_at",
    ],
    "inference": [
        "id", "claim_version_id", "field", "state", "period_kind", "period_start", "period_end", "boundary",
        "boundary_detail", "basis_id", "reason", "group_key", "run_id", "config_version", "created_at",
    ],
    "inference_review": [
        "id", "inference_id", "claim_version_id", "field", "decision", "period_kind", "period_start", "period_end",
        "boundary", "boundary_detail", "contributor_version_id", "capacity", "rationale", "created_at",
    ],
    "metric_assignment": [
        "id", "claim_version_id", "metric_key", "rule", "unit_key", "unit_factor", "unit_source", "run_id",
        "config_version", "created_at",
    ],
    "match_review": [
        "id", "claim_version_id", "series_key", "reason", "decision", "contributor_version_id", "capacity", "rationale",
        "created_at",
    ],
    "restatement": [
        "id", "original_version_id", "restated_version_id", "series_key", "decision", "evidence_document_id",
        "evidence_page", "evidence_quote", "contributor_version_id", "capacity", "rationale", "created_at",
    ],
    "document_state_change": ["id", "document_state_id", "contributor_version_id", "capacity", "rationale", "created_at"],
    "sheet_mapping": [
        "id", "document_id", "sheet", "position", "metric_col", "value_col", "unit_col", "period_col", "boundary_col",
        "company_col", "note_col", "year_end", "boundary_is", "boundary_detail", "contributor_version_id", "capacity",
        "rationale", "created_at",
    ],
    "claim_note": ["id", "claim_version_id", "text", "created_at"],
    "document_deletion": ["id", "document_state_id", "plan", "created_at"],
    "document_deletion_step": ["id", "deletion_id", "step", "detail", "created_at"],
    **dict.fromkeys(("review_company", "review_auditor"), [
        "id", "claim_version_id", "contributor_version_id", "capacity", "scope", "reviewed_on", "conclusion", "outcome",
        "evidence_document_id", "evidence_page", "evidence_note", "created_at"]),
    "adjudication": [
        "id", "low_version_id", "high_version_id", "state", "rationale", "procedure", "counter_document_id",
        "counter_page", "counter_note", "follow_up", "closure_reason", "contributor_version_id", "capacity", "created_at",
    ],
    "reviewer_flag": ["id", "claim_version_id", "decision", "rationale", "contributor_version_id", "capacity", "created_at"],
    "highlight": ["id", "claim_version_id", "contributor_version_id", "capacity", "note", "created_at"],
}
VALUES = ("period_kind", "period_start", "period_end", "boundary", "boundary_detail")
NULLABLE = {("company", "sector_ref"), ("company", "sector_version"), ("document", "source"), ("document_state", "note")} | {
    ("run_event", c) for c in ("stage", "item", "method", "outcome", "cost_estimated", "cost_confirmed", "message")
} | {("attempt", c) for c in ("method", "rung", "output", "error", "cost_estimated", "cost_confirmed")} | {
    ("approval", c) for c in ("provider", "destination", "run_id", "amount")
} | {("claim", "sector_ref"), ("claim", "sector_version")} | {
    ("claim_version", c) for c in ("metric_text", "value", "unit_text", "period_label", "period_kind", "period_start", "period_end",
                                   "metric_key", "boundary_detail", "boundary_label")
} | {("evidence_ref", c) for c in ("page_number", "boxes", "sheet", "cell")} | {
    ("source_match", "reason"), ("source_match", "artifact_id"), ("contributor_version", "organisation"),
    ("expected_item", "period_label")} | {
    ("basis", c) for c in ("fy_end", "period_start", "period_end", "boundary", "boundary_detail")} | {
    ("inference", c) for c in (*VALUES, "basis_id", "reason")} | {("inference_review", c) for c in ("inference_id", *VALUES)} | {
    ("metric_assignment", c) for c in ("metric_key", "rule", "unit_key", "unit_factor", "unit_source")} | {
    ("restatement", "evidence_page"), ("restatement", "evidence_quote")} | {
    ("sheet_mapping", c) for c in ("metric_col", "unit_col", "period_col", "boundary_col", "company_col", "note_col",
                                   "year_end", "boundary_is", "boundary_detail")} | {
    (t, c) for t in ("review_company", "review_auditor") for c in ("evidence_document_id", "evidence_page", "evidence_note")} | {
    ("adjudication", c) for c in ("counter_document_id", "counter_page", "counter_note", "follow_up", "closure_reason")}


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
    assert [r["version"] for r in db.execute("SELECT version FROM schema_version")] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
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
