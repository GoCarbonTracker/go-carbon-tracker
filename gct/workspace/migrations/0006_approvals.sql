CREATE TABLE approval (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('spend_cap', 'run_allowance', 'transfer')),
    provider TEXT NULL,
    destination TEXT NULL,
    run_id INTEGER NULL REFERENCES run(id),
    amount REAL NULL CHECK (amount >= 0),
    granted INTEGER NOT NULL CHECK (granted IN (0, 1)),
    created_at TEXT NOT NULL,
    CHECK ((provider IS NOT NULL) = (kind = 'transfer')),
    CHECK ((destination IS NOT NULL) = (kind = 'transfer')),
    CHECK ((run_id IS NOT NULL) = (kind = 'run_allowance')),
    CHECK ((amount IS NOT NULL) = (kind IN ('spend_cap', 'run_allowance'))),
    CHECK (kind = 'transfer' OR granted = 1)
);

CREATE TRIGGER approval_no_update BEFORE UPDATE ON approval
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER approval_no_delete BEFORE DELETE ON approval
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
