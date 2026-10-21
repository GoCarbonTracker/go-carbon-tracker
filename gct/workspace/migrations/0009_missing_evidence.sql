CREATE TABLE contributor_version (
    id INTEGER PRIMARY KEY,
    contributor_key TEXT NOT NULL,
    name TEXT NOT NULL,
    organisation TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX contributor_version_by_key ON contributor_version (contributor_key, id);

CREATE TABLE expected_item (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES company(id),
    metric_text TEXT NOT NULL,
    period_label TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE expected_item_document (
    expected_item_id INTEGER NOT NULL REFERENCES expected_item(id),
    document_id INTEGER NOT NULL REFERENCES document(id),
    UNIQUE (expected_item_id, document_id)
);

CREATE TABLE page_acceptance (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id),
    page_number INTEGER NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('text', 'tables', 'figures')),
    artifact_id INTEGER NOT NULL REFERENCES artifact(id),
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX page_acceptance_by_page ON page_acceptance (document_id, page_number, content_type, id);

CREATE TABLE gap_confirmation (
    id INTEGER PRIMARY KEY,
    expected_item_id INTEGER NOT NULL REFERENCES expected_item(id),
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    documents_checked TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TRIGGER contributor_version_no_update BEFORE UPDATE ON contributor_version
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER contributor_version_no_delete BEFORE DELETE ON contributor_version
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER expected_item_no_update BEFORE UPDATE ON expected_item
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER expected_item_no_delete BEFORE DELETE ON expected_item
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER expected_item_document_no_update BEFORE UPDATE ON expected_item_document
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER expected_item_document_no_delete BEFORE DELETE ON expected_item_document
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER page_acceptance_no_update BEFORE UPDATE ON page_acceptance
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER page_acceptance_no_delete BEFORE DELETE ON page_acceptance
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER gap_confirmation_no_update BEFORE UPDATE ON gap_confirmation
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER gap_confirmation_no_delete BEFORE DELETE ON gap_confirmation
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
