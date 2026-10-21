ALTER TABLE claim_version ADD COLUMN boundary_label TEXT;

CREATE TABLE correction (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    corrects_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    fields TEXT NOT NULL,
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX correction_by_version ON correction (claim_version_id);

CREATE TABLE claim_seen (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    page_id INTEGER NOT NULL REFERENCES page(id),
    config_version TEXT NOT NULL,
    run_id INTEGER NOT NULL REFERENCES run(id),
    created_at TEXT NOT NULL,
    UNIQUE (claim_version_id, page_id, config_version)
);

CREATE INDEX claim_seen_by_page ON claim_seen (page_id, config_version);

CREATE TRIGGER correction_no_update BEFORE UPDATE ON correction
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER correction_no_delete BEFORE DELETE ON correction
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER claim_seen_no_update BEFORE UPDATE ON claim_seen
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER claim_seen_no_delete BEFORE DELETE ON claim_seen
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
