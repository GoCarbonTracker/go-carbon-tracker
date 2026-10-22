CREATE TABLE adjudication (
    id INTEGER PRIMARY KEY,
    low_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    high_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    state TEXT NOT NULL CHECK (state IN ('explained_difference', 'extraction_error', 'reviewer_confirmed_issue',
                                         'evidence_not_found')),
    rationale TEXT NOT NULL,
    procedure TEXT NOT NULL,
    counter_document_id INTEGER REFERENCES document(id),
    counter_page INTEGER,
    counter_note TEXT,
    follow_up TEXT,
    closure_reason TEXT,
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (low_version_id < high_version_id),
    CHECK (state <> 'explained_difference' OR counter_document_id IS NOT NULL OR counter_note IS NOT NULL),
    CHECK (counter_page IS NULL OR counter_document_id IS NOT NULL)
);

CREATE INDEX adjudication_by_pair ON adjudication (low_version_id, high_version_id, id);
CREATE INDEX adjudication_by_high ON adjudication (high_version_id);

CREATE TRIGGER adjudication_no_update BEFORE UPDATE ON adjudication
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER adjudication_no_delete BEFORE DELETE ON adjudication
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TABLE reviewer_flag (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    decision TEXT NOT NULL CHECK (decision IN ('raised', 'withdrawn')),
    rationale TEXT NOT NULL,
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX reviewer_flag_by_version ON reviewer_flag (claim_version_id);

CREATE TRIGGER reviewer_flag_no_update BEFORE UPDATE ON reviewer_flag
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER reviewer_flag_no_delete BEFORE DELETE ON reviewer_flag
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
