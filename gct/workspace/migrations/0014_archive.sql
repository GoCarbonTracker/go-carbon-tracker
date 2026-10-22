CREATE TABLE document_state_change (
    id INTEGER PRIMARY KEY,
    document_state_id INTEGER UNIQUE NOT NULL REFERENCES document_state(id),
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TRIGGER document_state_change_no_update BEFORE UPDATE ON document_state_change
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER document_state_change_no_delete BEFORE DELETE ON document_state_change
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
