CREATE TABLE document_deletion (
    id INTEGER PRIMARY KEY,
    document_state_id INTEGER UNIQUE NOT NULL REFERENCES document_state(id),
    plan TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE document_deletion_step (
    id INTEGER PRIMARY KEY,
    deletion_id INTEGER NOT NULL REFERENCES document_deletion(id),
    step TEXT NOT NULL CHECK (step IN ('database', 'files', 'artifacts', 'renders', 'published', 'vacuum')),
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (deletion_id, step)
);

CREATE TRIGGER document_deletion_no_update BEFORE UPDATE ON document_deletion
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER document_deletion_no_delete BEFORE DELETE ON document_deletion
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TRIGGER document_deletion_step_no_update BEFORE UPDATE ON document_deletion_step
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER document_deletion_step_no_delete BEFORE DELETE ON document_deletion_step
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
