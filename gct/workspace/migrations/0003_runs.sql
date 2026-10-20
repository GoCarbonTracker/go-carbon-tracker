CREATE TABLE run (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    command TEXT NOT NULL,
    gct_version TEXT NOT NULL
);

CREATE TABLE run_event (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES run(id),
    at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('note', 'item', 'failure', 'retry', 'cost', 'output', 'finished')),
    stage TEXT NULL,
    item TEXT NULL,
    method TEXT NULL,
    outcome TEXT NULL,
    cost_estimated REAL NULL,
    cost_confirmed REAL NULL,
    message TEXT NULL
);

CREATE TRIGGER run_no_update BEFORE UPDATE ON run
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER run_no_delete BEFORE DELETE ON run
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TRIGGER run_event_no_update BEFORE UPDATE ON run_event
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER run_event_no_delete BEFORE DELETE ON run_event
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
