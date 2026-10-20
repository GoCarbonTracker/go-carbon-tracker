CREATE TABLE artifact (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL,
    kind TEXT NOT NULL,
    document_id INTEGER NOT NULL REFERENCES document(id),
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (document_id, sha256, kind)
);

CREATE TABLE page (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id),
    page_number INTEGER NOT NULL,
    rung INTEGER NOT NULL,
    method TEXT NOT NULL,
    config_version TEXT NOT NULL,
    width REAL NOT NULL,
    height REAL NOT NULL,
    words INTEGER NOT NULL,
    tables INTEGER NOT NULL,
    flags TEXT NOT NULL,
    artifact_id INTEGER NOT NULL REFERENCES artifact(id),
    created_at TEXT NOT NULL
);

CREATE INDEX page_by_document ON page (document_id, page_number, id);

CREATE TRIGGER artifact_no_update BEFORE UPDATE ON artifact
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER artifact_no_delete BEFORE DELETE ON artifact
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER page_no_update BEFORE UPDATE ON page
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER page_no_delete BEFORE DELETE ON page
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
