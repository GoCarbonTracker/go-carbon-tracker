CREATE TABLE sheet_mapping (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id),
    sheet TEXT NOT NULL,
    position INTEGER NOT NULL,
    metric_col TEXT,
    value_col TEXT NOT NULL,
    unit_col TEXT,
    period_col TEXT,
    boundary_col TEXT,
    company_col TEXT,
    note_col TEXT,
    year_end TEXT CHECK (year_end GLOB '[01][0-9]-[0-3][0-9]' AND substr(year_end, 1, 2) BETWEEN '01' AND '12'
                         AND substr(year_end, 4, 2) BETWEEN '01' AND '31'),
    boundary_is TEXT CHECK (boundary_is IN ('standalone', 'consolidated', 'subsidiary_set')),
    boundary_detail TEXT,
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX sheet_mapping_by_sheet ON sheet_mapping (document_id, sheet, id);

CREATE TABLE claim_note (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX claim_note_by_version ON claim_note (claim_version_id, id);

CREATE TRIGGER sheet_mapping_no_update BEFORE UPDATE ON sheet_mapping
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER sheet_mapping_no_delete BEFORE DELETE ON sheet_mapping
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER claim_note_no_update BEFORE UPDATE ON claim_note
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER claim_note_no_delete BEFORE DELETE ON claim_note
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
