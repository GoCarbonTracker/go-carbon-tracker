CREATE TABLE metric_assignment (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    metric_key TEXT,
    rule TEXT,
    unit_key TEXT,
    unit_factor REAL,
    unit_source TEXT CHECK (unit_source IN ('unit', 'label')),
    run_id INTEGER NOT NULL REFERENCES run(id),
    config_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX metric_assignment_by_version ON metric_assignment (claim_version_id, id);

CREATE TABLE match_review (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    series_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('linked', 'not_linked')),
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX match_review_by_version ON match_review (claim_version_id, series_key, id);

CREATE TRIGGER metric_assignment_no_update BEFORE UPDATE ON metric_assignment
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER metric_assignment_no_delete BEFORE DELETE ON metric_assignment
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER match_review_no_update BEFORE UPDATE ON match_review
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER match_review_no_delete BEFORE DELETE ON match_review
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
