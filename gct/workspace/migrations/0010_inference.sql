CREATE TABLE basis (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES document(id),
    page_number INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('fiscal_year_end', 'reporting_boundary')),
    wording TEXT NOT NULL,
    fy_end TEXT,
    period_start TEXT,
    period_end TEXT,
    boundary TEXT CHECK (boundary IN ('standalone', 'subsidiary_set', 'consolidated', 'unknown')),
    boundary_detail TEXT,
    run_id INTEGER NOT NULL REFERENCES run(id),
    config_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (document_id, page_number, kind, wording)
);

CREATE TABLE basis_scope (
    id INTEGER PRIMARY KEY,
    basis_id INTEGER NOT NULL REFERENCES basis(id),
    first_page INTEGER NOT NULL,
    last_page INTEGER NOT NULL,
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX basis_scope_by_basis ON basis_scope (basis_id, id);

CREATE TABLE inference (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    field TEXT NOT NULL CHECK (field IN ('period', 'boundary')),
    state TEXT NOT NULL CHECK (state IN ('proposed', 'unresolved')),
    period_kind TEXT CHECK (period_kind IN ('fiscal_year', 'calendar_year', 'half', 'quarter', 'as_at')),
    period_start TEXT,
    period_end TEXT,
    boundary TEXT CHECK (boundary IN ('standalone', 'subsidiary_set', 'consolidated', 'unknown')),
    boundary_detail TEXT,
    basis_id INTEGER REFERENCES basis(id),
    reason TEXT,
    group_key TEXT NOT NULL,
    run_id INTEGER NOT NULL REFERENCES run(id),
    config_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX inference_by_claim ON inference (claim_version_id, field, id);

CREATE TABLE inference_review (
    id INTEGER PRIMARY KEY,
    inference_id INTEGER REFERENCES inference(id),
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    field TEXT NOT NULL CHECK (field IN ('period', 'boundary')),
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'resolved', 'rejected')),
    period_kind TEXT CHECK (period_kind IN ('fiscal_year', 'calendar_year', 'half', 'quarter', 'as_at')),
    period_start TEXT,
    period_end TEXT,
    boundary TEXT CHECK (boundary IN ('standalone', 'subsidiary_set', 'consolidated', 'unknown')),
    boundary_detail TEXT,
    contributor_version_id INTEGER NOT NULL REFERENCES contributor_version(id),
    capacity TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX inference_review_by_claim ON inference_review (claim_version_id, field, id);

CREATE TRIGGER basis_no_update BEFORE UPDATE ON basis
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER basis_no_delete BEFORE DELETE ON basis
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER basis_scope_no_update BEFORE UPDATE ON basis_scope
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER basis_scope_no_delete BEFORE DELETE ON basis_scope
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER inference_no_update BEFORE UPDATE ON inference
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER inference_no_delete BEFORE DELETE ON inference
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER inference_review_no_update BEFORE UPDATE ON inference_review
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER inference_review_no_delete BEFORE DELETE ON inference_review
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
