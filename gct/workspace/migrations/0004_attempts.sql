CREATE TABLE attempt (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES run(id),
    stage TEXT NOT NULL,
    item TEXT NOT NULL,
    input_version TEXT NOT NULL,
    config_version TEXT NOT NULL,
    method TEXT NULL,
    rung INTEGER NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('ok', 'failed')),
    output TEXT NULL,
    error TEXT NULL,
    cost_estimated REAL NULL,
    cost_confirmed REAL NULL,
    at TEXT NOT NULL
);

CREATE INDEX attempt_key ON attempt (stage, item, input_version, config_version, id);

CREATE TRIGGER attempt_no_update BEFORE UPDATE ON attempt
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER attempt_no_delete BEFORE DELETE ON attempt
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
