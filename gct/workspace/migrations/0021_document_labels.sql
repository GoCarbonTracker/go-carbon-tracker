CREATE TABLE document_label (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id),
    privacy TEXT NOT NULL CHECK (privacy IN ('private', 'shareable')),
    availability TEXT NOT NULL CHECK (availability IN ('public', 'internal', 'unknown')),
    contributor_version_id INTEGER REFERENCES contributor_version(id),
    capacity TEXT,
    rationale TEXT,
    created_at TEXT NOT NULL,
    CHECK ((contributor_version_id IS NULL AND capacity IS NULL AND rationale IS NULL)
           OR (contributor_version_id IS NOT NULL AND capacity IS NOT NULL AND rationale IS NOT NULL))
);

CREATE INDEX document_label_by_document ON document_label (document_id);

CREATE TRIGGER document_label_no_update BEFORE UPDATE ON document_label
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER document_label_no_delete BEFORE DELETE ON document_label
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
