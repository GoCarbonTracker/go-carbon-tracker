CREATE TABLE claim_version_new (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES claim(id),
    run_id INTEGER NOT NULL REFERENCES run(id),
    method TEXT NOT NULL,
    config_version TEXT NOT NULL,
    metric_text TEXT,
    value_text TEXT NOT NULL,
    value REAL,
    unit_text TEXT,
    period_label TEXT,
    period_kind TEXT,
    period_start TEXT,
    period_end TEXT,
    metric_key TEXT,
    reporting_boundary TEXT NOT NULL DEFAULT 'unknown'
        CHECK (reporting_boundary IN ('standalone', 'subsidiary_set', 'consolidated', 'segment', 'unknown')),
    boundary_detail TEXT,
    created_at TEXT NOT NULL,
    boundary_label TEXT
);

INSERT INTO claim_version_new (id, claim_id, run_id, method, config_version, metric_text, value_text, value, unit_text, period_label, period_kind, period_start, period_end, metric_key, reporting_boundary, boundary_detail, created_at, boundary_label)
SELECT id, claim_id, run_id, method, config_version, metric_text, value_text, value, unit_text, period_label, period_kind, period_start, period_end, metric_key, reporting_boundary, boundary_detail, created_at, boundary_label
FROM claim_version;

DROP TABLE claim_version;
ALTER TABLE claim_version_new RENAME TO claim_version;
CREATE INDEX claim_version_by_claim ON claim_version (claim_id, id);
CREATE TRIGGER claim_version_no_update BEFORE UPDATE ON claim_version
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER claim_version_no_delete BEFORE DELETE ON claim_version
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TABLE basis_new (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id),
    page_number INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('fiscal_year_end', 'reporting_boundary')),
    wording TEXT NOT NULL,
    fy_end TEXT,
    period_start TEXT,
    period_end TEXT,
    boundary TEXT CHECK (boundary IN ('standalone', 'subsidiary_set', 'consolidated', 'segment', 'unknown')),
    boundary_detail TEXT,
    run_id INTEGER NOT NULL REFERENCES run(id),
    config_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (document_id, page_number, kind, wording)
);

INSERT INTO basis_new (id, document_id, page_number, kind, wording, fy_end, period_start, period_end, boundary, boundary_detail, run_id, config_version, created_at)
SELECT id, document_id, page_number, kind, wording, fy_end, period_start, period_end, boundary, boundary_detail, run_id, config_version, created_at
FROM basis;

DROP TABLE basis;
ALTER TABLE basis_new RENAME TO basis;
CREATE TRIGGER basis_no_update BEFORE UPDATE ON basis
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER basis_no_delete BEFORE DELETE ON basis
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TABLE inference_new (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    field TEXT NOT NULL CHECK (field IN ('period', 'boundary')),
    state TEXT NOT NULL CHECK (state IN ('proposed', 'machine-inferred', 'unresolved')),
    period_kind TEXT CHECK (period_kind IN ('fiscal_year', 'calendar_year', 'half', 'quarter', 'as_at')),
    period_start TEXT,
    period_end TEXT,
    boundary TEXT CHECK (boundary IN ('standalone', 'subsidiary_set', 'consolidated', 'segment', 'unknown')),
    boundary_detail TEXT,
    basis_id INTEGER REFERENCES basis(id),
    reason TEXT,
    group_key TEXT NOT NULL,
    run_id INTEGER NOT NULL REFERENCES run(id),
    config_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO inference_new (id, claim_version_id, field, state, period_kind, period_start, period_end, boundary, boundary_detail, basis_id, reason, group_key, run_id, config_version, created_at)
SELECT id, claim_version_id, field, state, period_kind, period_start, period_end, boundary, boundary_detail, basis_id, reason, group_key, run_id, config_version, created_at
FROM inference;

DROP TABLE inference;
ALTER TABLE inference_new RENAME TO inference;
CREATE INDEX inference_by_claim ON inference (claim_version_id, field, id);
CREATE TRIGGER inference_no_update BEFORE UPDATE ON inference
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER inference_no_delete BEFORE DELETE ON inference
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TABLE inference_review_new (
    id INTEGER PRIMARY KEY,
    inference_id INTEGER REFERENCES inference(id),
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    field TEXT NOT NULL CHECK (field IN ('period', 'boundary')),
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'resolved', 'rejected')),
    period_kind TEXT CHECK (period_kind IN ('fiscal_year', 'calendar_year', 'half', 'quarter', 'as_at')),
    period_start TEXT,
    period_end TEXT,
    boundary TEXT CHECK (boundary IN ('standalone', 'subsidiary_set', 'consolidated', 'segment', 'unknown')),
    boundary_detail TEXT,
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO inference_review_new (id, inference_id, claim_version_id, field, decision, period_kind, period_start, period_end, boundary, boundary_detail, contributor_version_id, capacity, rationale, created_at)
SELECT id, inference_id, claim_version_id, field, decision, period_kind, period_start, period_end, boundary, boundary_detail, contributor_version_id, capacity, rationale, created_at
FROM inference_review;

DROP TABLE inference_review;
ALTER TABLE inference_review_new RENAME TO inference_review;
CREATE INDEX inference_review_by_claim ON inference_review (claim_version_id, field, id);
CREATE TRIGGER inference_review_no_update BEFORE UPDATE ON inference_review
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER inference_review_no_delete BEFORE DELETE ON inference_review
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;

CREATE TABLE sheet_mapping_new (
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
    boundary_is TEXT CHECK (boundary_is IN ('standalone', 'consolidated', 'subsidiary_set', 'segment')),
    boundary_detail TEXT,
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO sheet_mapping_new (id, document_id, sheet, position, metric_col, value_col, unit_col, period_col, boundary_col, company_col, note_col, year_end, boundary_is, boundary_detail, contributor_version_id, capacity, rationale, created_at)
SELECT id, document_id, sheet, position, metric_col, value_col, unit_col, period_col, boundary_col, company_col, note_col, year_end, boundary_is, boundary_detail, contributor_version_id, capacity, rationale, created_at
FROM sheet_mapping;

DROP TABLE sheet_mapping;
ALTER TABLE sheet_mapping_new RENAME TO sheet_mapping;
CREATE INDEX sheet_mapping_by_sheet ON sheet_mapping (document_id, sheet, id);
CREATE TRIGGER sheet_mapping_no_update BEFORE UPDATE ON sheet_mapping
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER sheet_mapping_no_delete BEFORE DELETE ON sheet_mapping
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
