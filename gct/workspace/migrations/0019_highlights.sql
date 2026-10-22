CREATE TABLE highlight (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX highlight_by_version ON highlight (claim_version_id);

CREATE TRIGGER highlight_no_update BEFORE UPDATE ON highlight
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER highlight_no_delete BEFORE DELETE ON highlight
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
