CREATE TABLE published_version (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    built_at TEXT NOT NULL,
    history_mark TEXT NOT NULL,
    companies INTEGER NOT NULL,
    documents INTEGER NOT NULL,
    gct_version TEXT NOT NULL
);

CREATE TABLE published_pointer (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL REFERENCES published_version(version),
    action TEXT NOT NULL CHECK (action IN ('build', 'restore')),
    at TEXT NOT NULL
);

CREATE TABLE published_purge (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL REFERENCES published_version(version),
    reason TEXT NOT NULL CHECK (reason IN ('retention', 'deletion')),
    at TEXT NOT NULL
);

CREATE TRIGGER published_version_no_update BEFORE UPDATE ON published_version
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER published_version_no_delete BEFORE DELETE ON published_version
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TRIGGER published_pointer_no_update BEFORE UPDATE ON published_pointer
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER published_pointer_no_delete BEFORE DELETE ON published_pointer
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TRIGGER published_purge_no_update BEFORE UPDATE ON published_purge
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER published_purge_no_delete BEFORE DELETE ON published_purge
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
