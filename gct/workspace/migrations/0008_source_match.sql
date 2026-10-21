CREATE TABLE source_match (
    id INTEGER PRIMARY KEY,
    evidence_ref_id INTEGER NOT NULL REFERENCES evidence_ref(id),
    run_id INTEGER NOT NULL REFERENCES run(id),
    status TEXT NOT NULL CHECK (status IN ('matched', 'cited', 'unresolved')),
    reason TEXT,
    artifact_id INTEGER REFERENCES artifact(id),
    config_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX source_match_by_ref ON source_match (evidence_ref_id, id);

CREATE TRIGGER source_match_no_update BEFORE UPDATE ON source_match
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER source_match_no_delete BEFORE DELETE ON source_match
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
