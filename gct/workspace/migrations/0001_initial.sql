CREATE TABLE schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE workspace (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    created_at TEXT NOT NULL,
    gct_version TEXT NOT NULL
);

CREATE TABLE company (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    sector_ref TEXT NULL,
    sector_version TEXT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE document (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES company(id),
    logical_name TEXT NOT NULL,
    version INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('report', 'evidence')),
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'xlsx', 'csv')),
    privacy TEXT NOT NULL CHECK (privacy IN ('private', 'shareable')),
    size_bytes INTEGER NOT NULL,
    source TEXT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (company_id, logical_name, version)
);

CREATE TABLE document_state (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id),
    state TEXT NOT NULL CHECK (state IN ('registered', 'archived', 'restored', 'deleted')),
    note TEXT NULL,
    at TEXT NOT NULL
);

CREATE TRIGGER workspace_no_update BEFORE UPDATE ON workspace
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER workspace_no_delete BEFORE DELETE ON workspace
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TRIGGER company_no_update BEFORE UPDATE ON company
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER company_no_delete BEFORE DELETE ON company
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TRIGGER document_no_update BEFORE UPDATE ON document
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER document_no_delete BEFORE DELETE ON document
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TRIGGER document_state_no_update BEFORE UPDATE ON document_state
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER document_state_no_delete BEFORE DELETE ON document_state
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
