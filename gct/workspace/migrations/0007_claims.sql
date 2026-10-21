CREATE TABLE claim (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES company(id),
    document_id INTEGER NOT NULL REFERENCES document(id),
    page_number INTEGER NOT NULL,
    locator TEXT NOT NULL,
    sector_ref TEXT,
    sector_version TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (document_id, page_number, locator)
);

CREATE TABLE claim_version (
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
        CHECK (reporting_boundary IN ('standalone', 'subsidiary_set', 'consolidated', 'unknown')),
    boundary_detail TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX claim_version_by_claim ON claim_version (claim_id, id);

CREATE TABLE evidence_ref (
    id INTEGER PRIMARY KEY,
    claim_version_id INTEGER NOT NULL REFERENCES claim_version(id),
    document_id INTEGER NOT NULL REFERENCES document(id),
    page_number INTEGER,
    boxes TEXT,
    sheet TEXT,
    cell TEXT,
    created_at TEXT NOT NULL,
    CHECK ((page_number IS NOT NULL AND sheet IS NULL AND cell IS NULL)
        OR (sheet IS NOT NULL AND page_number IS NULL AND boxes IS NULL))
);

CREATE INDEX evidence_ref_by_version ON evidence_ref (claim_version_id);

CREATE TRIGGER claim_no_update BEFORE UPDATE ON claim
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER claim_no_delete BEFORE DELETE ON claim
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER claim_version_no_update BEFORE UPDATE ON claim_version
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER claim_version_no_delete BEFORE DELETE ON claim_version
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER evidence_ref_no_update BEFORE UPDATE ON evidence_ref
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
CREATE TRIGGER evidence_ref_no_delete BEFORE DELETE ON evidence_ref
BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
