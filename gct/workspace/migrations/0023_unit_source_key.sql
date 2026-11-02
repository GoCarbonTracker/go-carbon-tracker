CREATE TABLE metric_assignment_new (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    metric_key TEXT,
    rule TEXT,
    unit_key TEXT,
    unit_factor REAL,
    unit_source TEXT CHECK (unit_source IN ('unit', 'label', 'key')),
    run_id INTEGER NOT NULL REFERENCES run(id),
    config_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO metric_assignment_new (id, claim_version_id, metric_key, rule, unit_key, unit_factor, unit_source, run_id, config_version, created_at)
SELECT id, claim_version_id, metric_key, rule, unit_key, unit_factor, unit_source, run_id, config_version, created_at
FROM metric_assignment;

DROP TABLE metric_assignment;
ALTER TABLE metric_assignment_new RENAME TO metric_assignment;
CREATE INDEX metric_assignment_by_version ON metric_assignment (claim_version_id, id);
CREATE TRIGGER metric_assignment_no_update BEFORE UPDATE ON metric_assignment
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER metric_assignment_no_delete BEFORE DELETE ON metric_assignment
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
