CREATE TABLE restatement (
    id INTEGER PRIMARY KEY,
    original_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    restated_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    series_key TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('recorded', 'withdrawn')),
    evidence_document_id INTEGER NOT NULL REFERENCES document(id),
    evidence_page INTEGER,
    evidence_quote TEXT,
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (original_version_id <> restated_version_id),
    CHECK (decision = 'withdrawn' OR (evidence_page IS NOT NULL AND evidence_quote IS NOT NULL))
);

CREATE INDEX restatement_by_pair ON restatement (original_version_id, restated_version_id, id);
CREATE INDEX restatement_by_restated ON restatement (restated_version_id);

CREATE TRIGGER restatement_no_update BEFORE UPDATE ON restatement
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER restatement_no_delete BEFORE DELETE ON restatement
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
