CREATE TABLE review_company (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    scope TEXT NOT NULL,
    reviewed_on TEXT NOT NULL,
    conclusion TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'rejected', 'disputed')),
    evidence_document_id INTEGER REFERENCES document(id),
    evidence_page INTEGER,
    evidence_note TEXT,
    created_at TEXT NOT NULL,
    CHECK (evidence_document_id IS NOT NULL OR evidence_note IS NOT NULL),
    CHECK (evidence_page IS NULL OR evidence_document_id IS NOT NULL)
);

CREATE INDEX review_company_by_version ON review_company (claim_version_id);

CREATE TRIGGER review_company_no_update BEFORE UPDATE ON review_company
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER review_company_no_delete BEFORE DELETE ON review_company
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TABLE review_auditor (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    scope TEXT NOT NULL,
    reviewed_on TEXT NOT NULL,
    conclusion TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'rejected', 'disputed')),
    evidence_document_id INTEGER REFERENCES document(id),
    evidence_page INTEGER,
    evidence_note TEXT,
    created_at TEXT NOT NULL,
    CHECK (evidence_document_id IS NOT NULL OR evidence_note IS NOT NULL),
    CHECK (evidence_page IS NULL OR evidence_document_id IS NOT NULL)
);

CREATE INDEX review_auditor_by_version ON review_auditor (claim_version_id);

CREATE TRIGGER review_auditor_no_update BEFORE UPDATE ON review_auditor
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER review_auditor_no_delete BEFORE DELETE ON review_auditor
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
