CREATE TABLE saved_view (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('save', 'remove')),
    filter TEXT CHECK (filter IS NULL OR json_valid(filter)),
    section TEXT CHECK (section IN ('tables', 'graphs')),
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    created_at TEXT NOT NULL,
    CHECK ((action = 'save') = (filter IS NOT NULL AND section IS NOT NULL))
);

CREATE INDEX saved_view_by_name ON saved_view (name);

CREATE TRIGGER saved_view_no_update BEFORE UPDATE ON saved_view
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER saved_view_no_delete BEFORE DELETE ON saved_view
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
