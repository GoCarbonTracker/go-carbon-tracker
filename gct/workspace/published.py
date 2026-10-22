import json
import os
import sqlite3
from pathlib import Path

from gct import __version__
from gct.workspace import store
from gct.workspace.layout import REFUSED, GctError

ACTIVE = "(SELECT s.state FROM document_state s WHERE s.document_id = d.id ORDER BY s.id DESC LIMIT 1)"

# Later stories add their tables here: one CREATE and one INSERT each, filled in _read_history.
PROJECTION_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE company (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sector_ref TEXT, sector_version TEXT);
CREATE TABLE document (
    id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, logical_name TEXT NOT NULL, version INTEGER NOT NULL,
    sha256 TEXT NOT NULL, kind TEXT NOT NULL, file_type TEXT NOT NULL, privacy TEXT NOT NULL, size_bytes INTEGER NOT NULL
);
CREATE TABLE claim (
    id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, document_id INTEGER NOT NULL, page_number INTEGER NOT NULL,
    locator TEXT NOT NULL, sector_ref TEXT, sector_version TEXT, claim_version_id INTEGER NOT NULL, version_method TEXT NOT NULL,
    config_version TEXT NOT NULL, metric_text TEXT, value_text TEXT NOT NULL, value REAL, unit_text TEXT,
    period_label TEXT, period_kind TEXT, period_start TEXT, period_end TEXT, metric_key TEXT,
    reporting_boundary TEXT NOT NULL, boundary_detail TEXT, period_state TEXT NOT NULL, boundary_state TEXT NOT NULL,
    period_basis TEXT, boundary_basis TEXT, proposed_period_kind TEXT, proposed_period_start TEXT,
    proposed_period_end TEXT, proposed_reporting_boundary TEXT, proposed_boundary_detail TEXT, boundary_label TEXT,
    claim_state TEXT NOT NULL, correction TEXT, needs_re_review TEXT NOT NULL, metric_rule TEXT, unit_key TEXT,
    unit_factor REAL, series_id TEXT, match_state TEXT NOT NULL, match_reason TEXT, note TEXT
);
CREATE TABLE series (
    id TEXT PRIMARY KEY, company_id INTEGER NOT NULL, metric_key TEXT, label TEXT, document_id INTEGER,
    reporting_boundary TEXT NOT NULL, boundary_detail TEXT, unit_family TEXT NOT NULL, period_kind TEXT NOT NULL,
    periods INTEGER NOT NULL, latest_period_end TEXT NOT NULL
);
CREATE TABLE series_point (
    series_id TEXT NOT NULL, claim_id INTEGER NOT NULL, claim_version_id INTEGER NOT NULL, period_start TEXT NOT NULL,
    period_end TEXT NOT NULL, value_text TEXT NOT NULL, unit_text TEXT, unit_key TEXT, number REAL, value_base REAL,
    link TEXT NOT NULL, comparable INTEGER NOT NULL, reason TEXT
);
CREATE TABLE comparison (
    series_id TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL, claim_a INTEGER NOT NULL,
    version_a INTEGER NOT NULL, claim_b INTEGER NOT NULL, version_b INTEGER NOT NULL, state TEXT NOT NULL, reason TEXT,
    restatement_id INTEGER
);
CREATE TABLE restatement (
    id INTEGER PRIMARY KEY, original_version_id INTEGER NOT NULL, restated_version_id INTEGER NOT NULL,
    series_key TEXT NOT NULL, decision TEXT NOT NULL, evidence_document_id INTEGER NOT NULL, evidence_page INTEGER,
    evidence_quote TEXT, contributor_name TEXT NOT NULL, contributor_organisation TEXT, capacity TEXT NOT NULL,
    rationale TEXT NOT NULL, created_at TEXT NOT NULL, binds INTEGER NOT NULL
);
CREATE TABLE evidence_ref (
    id INTEGER PRIMARY KEY, claim_version_id INTEGER NOT NULL, document_id INTEGER NOT NULL, page_number INTEGER,
    boxes TEXT, sheet TEXT, cell TEXT, source_match TEXT, source_match_reason TEXT
);
CREATE TABLE expected_item (
    id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, metric_text TEXT NOT NULL, period_label TEXT,
    found INTEGER NOT NULL, claims INTEGER NOT NULL, state TEXT, reasons TEXT NOT NULL, accepted TEXT NOT NULL
);
CREATE TABLE expected_item_document (expected_item_id INTEGER NOT NULL, document_id INTEGER NOT NULL);
CREATE TABLE gap_confirmation (
    id INTEGER PRIMARY KEY, expected_item_id INTEGER NOT NULL, contributor_name TEXT NOT NULL,
    contributor_organisation TEXT, capacity TEXT NOT NULL, rationale TEXT NOT NULL, current INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE page_acceptance (
    id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL, page_number INTEGER NOT NULL, content_type TEXT NOT NULL,
    contributor_name TEXT NOT NULL, contributor_organisation TEXT, capacity TEXT NOT NULL, rationale TEXT NOT NULL,
    current INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE hidden_by_archive (
    document_id INTEGER PRIMARY KEY, logical_name TEXT NOT NULL, archived_at TEXT NOT NULL, claims INTEGER NOT NULL,
    evidence_refs INTEGER NOT NULL, review_records INTEGER NOT NULL
);
CREATE TABLE sheet_mapping (
    id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL, sheet TEXT NOT NULL, position INTEGER NOT NULL, metric_col TEXT,
    value_col TEXT NOT NULL, unit_col TEXT, period_col TEXT, boundary_col TEXT, company_col TEXT, note_col TEXT,
    year_end TEXT, boundary_is TEXT, boundary_detail TEXT, contributor_name TEXT NOT NULL, contributor_organisation TEXT,
    capacity TEXT NOT NULL, rationale TEXT NOT NULL, created_at TEXT NOT NULL
);
"""
# Contributors project their name and organisation only; the sanitised package (E7) decides what leaves.
# Acceptances of an archived document leave with it (counted in hidden_by_archive).
ACCEPTANCE_SQL = f"""
SELECT a.id, a.document_id, a.page_number, a.content_type, c.name, c.organisation, a.capacity, a.rationale,
       a.artifact_id IS (SELECT p.artifact_id FROM page p WHERE p.document_id = a.document_id
                         AND p.page_number = a.page_number ORDER BY p.id DESC LIMIT 1), a.created_at
FROM page_acceptance a JOIN contributor_version c ON c.id = a.contributor_version_id
JOIN document d ON d.id = a.document_id WHERE {ACTIVE} IN ('registered', 'restored') ORDER BY a.id
"""
# Every mapping row of an active spreadsheet, current or superseded (story 4.3).
SHEET_MAPPING_SQL = f"""
SELECT m.id, m.document_id, m.sheet, m.position, m.metric_col, m.value_col, m.unit_col, m.period_col, m.boundary_col,
       m.company_col, m.note_col, m.year_end, m.boundary_is, m.boundary_detail, c.name, c.organisation, m.capacity,
       m.rationale, m.created_at
FROM sheet_mapping m JOIN contributor_version c ON c.id = m.contributor_version_id JOIN document d ON d.id = m.document_id
WHERE {ACTIVE} IN ('registered', 'restored') ORDER BY m.id
"""
COMPANY_COLUMNS = "id, name, sector_ref, sector_version"
DOCUMENT_COLUMNS = "id, company_id, logical_name, version, sha256, kind, file_type, privacy, size_bytes"
# The newest version of each claim of an active document.
NEWEST_CLAIMS = f"""
FROM claim c JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)
JOIN document d ON d.id = c.document_id WHERE {ACTIVE} IN ('registered', 'restored')
"""
CLAIM_COLUMNS = (
    "c.id, c.company_id, c.document_id, c.page_number, c.locator, c.sector_ref, c.sector_version, v.id, v.method,"
    " v.config_version, v.metric_text, v.value_text, v.value, v.unit_text, v.period_label, v.period_kind,"
    " v.period_start, v.period_end, v.metric_key, v.reporting_boundary, v.boundary_detail, v.boundary_label"
)
EVIDENCE_COLUMNS = (
    "e.id, e.claim_version_id, e.document_id, e.page_number, e.boxes, e.sheet, e.cell,"
    " (SELECT s.status FROM source_match s WHERE s.evidence_ref_id = e.id ORDER BY s.id DESC LIMIT 1),"
    " (SELECT s.reason FROM source_match s WHERE s.evidence_ref_id = e.id ORDER BY s.id DESC LIMIT 1)"
)

BUILD_AGAIN = "Build a fresh version with: gct publish build"


def version_path(root: Path, version: int) -> Path:
    return Path(root) / "published" / f"v{version}.db"


def open_version(path: Path) -> sqlite3.Connection:
    """Open a published version read-only."""
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def history_mark(conn: sqlite3.Connection) -> str:
    return ".".join(
        str(conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {t}").fetchone()[0])
        for t in ("company", "document", "document_state", "claim", "claim_version", "evidence_ref", "source_match",
                  # The missing-item states are computed from readings and review records, so those count too.
                  "page", "contributor_version", "expected_item", "page_acceptance", "gap_confirmation",
                  # A failed re-read changes a state without adding a page row.
                  "attempt WHERE stage = 'read'",
                  "basis", "basis_scope", "inference", "inference_review",
                  # A claim's state follows the extractions, including one that found nothing on its page.
                  "correction", "claim_seen", "attempt WHERE stage = 'extract'",
                  "metric_assignment", "match_review", "restatement", "document_state_change",
                  # A sheet extraction can change a spreadsheet claim's state without adding a version (story 4.3).
                  "sheet_mapping", "claim_note", "attempt WHERE stage = 'sheet'")
    )


def pointers(conn: sqlite3.Connection) -> tuple[int | None, int | None]:
    """(current, previous) version numbers from the pointer rows."""
    rows = [r[0] for r in conn.execute("SELECT version FROM published_pointer ORDER BY id")]
    if not rows:
        return None, None
    current = rows[-1]
    return current, next((v for v in reversed(rows[:-1]) if v != current), None)


def current_version(conn: sqlite3.Connection, root: Path) -> tuple[int, Path] | None:
    """The current version number and its file, or None before the first build."""
    current, _ = pointers(conn)
    return None if current is None else (current, version_path(root, current))


def _info(conn: sqlite3.Connection, version: int) -> dict:
    row = conn.execute(
        "SELECT version, built_at, history_mark, companies, documents FROM published_version WHERE version = ?",
        (version,),
    ).fetchone()
    return dict(row)


def _missing(conn: sqlite3.Connection, root: Path) -> dict:
    """The projected rows of expectations (state computed now), their documents, the newest gap confirmation of
    each missing item and every page acceptance."""
    from gct.stages import missing  # the stages import this package

    items, links, gaps = [], [], []
    for (i,) in conn.execute("SELECT id FROM expected_item ORDER BY id").fetchall():
        e = missing.describe(conn, root, i)
        items.append((i, conn.execute("SELECT company_id FROM expected_item WHERE id = ?", (i,)).fetchone()[0],
                      e["metric_text"], e["period_label"], int(e["found"]), len(e["claims"]), e["state"],
                      json.dumps(e["reasons"]), json.dumps(e["accepted"])))
        links += [(i, d) for d in e["documents"]]
        if c := e["confirmation"]:
            gaps.append((c["id"], i, c["contributor"], c["organisation"], c["capacity"], c["rationale"],
                         int(c["current"]), c["created_at"]))
    return {"expected_item": items, "expected_item_document": links, "gap_confirmation": gaps,
            "page_acceptance": conn.execute(ACCEPTANCE_SQL).fetchall()}


def _series(matched: dict) -> dict:
    """The series and series_point rows of a match result (story 4.1). A time series is series_point by period_end."""
    series = [(s["id"], s["company_id"], s["metric_key"], s["label"], s["document_id"], s["reporting_boundary"],
               s["boundary_detail"], s["unit_family"], s["period_kind"], s["periods"], s["latest_period_end"])
              for s in matched["series"].values()]
    points = [(s["id"], p["claim_id"], p["claim_version_id"], p["period_start"], p["period_end"], p["value_text"],
               p["unit_text"], p["unit_key"], p["number"], p["value_base"], p["link"], int(p["comparable"]), p["reason"])
              for s in matched["series"].values() for p in s["points"]]
    return {"series": series, "series_point": points}


def _comparison(conn: sqlite3.Connection, matched: dict) -> dict:
    """The pair states of every same-period set (story 4.2) and every restatement row, withdrawn ones included."""
    from gct.stages import restate  # the stages import this package

    pairs = [(p["series_id"], p["period_start"], p["period_end"], p["a"]["claim_id"], p["a"]["claim_version_id"],
              p["b"]["claim_id"], p["b"]["claim_version_id"], p["state"], p["reason"],
              p["restatement"] and p["restatement"]["id"]) for p in restate.pairs(conn, matched)]
    rows = conn.execute(
        "SELECT r.id, r.original_version_id, r.restated_version_id, r.series_key, r.decision, r.evidence_document_id,"
        " r.evidence_page, r.evidence_quote, c.name, c.organisation, r.capacity, r.rationale, r.created_at,"
        f" {restate.BINDS} FROM restatement r JOIN contributor_version c ON c.id = r.contributor_version_id"
        # A row naming a claim version of an archived document leaves with it; comparison pairs come from
        # match.compute, which already reads active documents only.
        " WHERE (SELECT COUNT(*) FROM claim_version v JOIN claim k ON k.id = v.claim_id JOIN document d ON d.id = k.document_id"
        f" WHERE v.id IN (r.original_version_id, r.restated_version_id) AND {ACTIVE} IN ('registered', 'restored')) = 2"
        " ORDER BY r.id").fetchall()
    return {"comparison": pairs, "restatement": rows}


def _with_inference(conn: sqlite3.Connection, claims, matched: dict) -> list[tuple]:
    """Claim rows with the period and boundary taken in order: resolved, else accepted for the current inference, else
    the claim version's own. A proposal goes to the proposed_* columns only, so a reader of the main fields never
    sees it. Then the boundary label, the claim's state, the correction that made the version and the decisions
    that need re-review (story 3.5), the metric assignment and match state (story 4.1) and the version's note (story
    4.3); metric_key is the assignment's key."""
    from gct.stages import correct, infer  # the stages import this package

    eff, out, per_doc = infer.effective(conn), [], {}
    notes = dict(conn.execute("SELECT claim_version_id, text FROM claim_note ORDER BY id"))
    match = {c["claim_id"]: c for c in matched["claims"]}
    for row in claims:
        doc = row[2]
        if doc not in per_doc:
            per_doc[doc] = correct.states(conn, doc), correct.re_review(conn, doc)
        states, reviews = per_doc[doc]
        made_by = correct.correction_of(conn, row[7])
        extra = (row[-1], states[row[0]], made_by and json.dumps(made_by, ensure_ascii=False),
                 json.dumps(reviews.get(row[0], [])))
        row, e, m = list(row[:-1]), eff[row[0]], match[row[0]]
        row[18] = m["metric_key"]
        extra += (m["rule"], m["unit_key"], m["unit_factor"], m["series_id"], m["state"], m["reason"])
        p, b = e["period"], e["boundary"]
        if p["state"] in ("resolved", "accepted"):
            row[15:18] = p["kind"], p["start"], p["end"]
        if b["state"] in ("resolved", "accepted"):
            row[19:21] = b["boundary"], b["detail"]
        basis = [json.dumps({"page": x["basis"]["page"], "wording": x["basis"]["wording"]}, ensure_ascii=False)
                 if x["basis"] else None for x in (p, b)]
        proposed = ([p["kind"], p["start"], p["end"]] if p["state"] == "proposed" else [None] * 3) + (
            [b["boundary"], b["detail"]] if b["state"] == "proposed" else [None] * 2)
        out.append((*row, p["state"], b["state"], *basis, *proposed, *extra, notes.get(row[7])))
    return out


def _read_history(conn: sqlite3.Connection, root: Path):
    """One consistent snapshot of the history: (mark, companies, active documents, their claims, evidence refs,
    missing-evidence rows)."""
    conn.execute("BEGIN")
    try:
        mark = history_mark(conn)
        companies = conn.execute(f"SELECT {COMPANY_COLUMNS} FROM company ORDER BY id").fetchall()
        docs = conn.execute(
            f"SELECT {DOCUMENT_COLUMNS} FROM document d WHERE {ACTIVE} IN ('registered', 'restored') ORDER BY id"
        ).fetchall()
        from gct.stages import match  # the stages import this package

        matched = match.compute(conn)
        claims = _with_inference(conn, conn.execute(f"SELECT {CLAIM_COLUMNS} {NEWEST_CLAIMS} ORDER BY c.id").fetchall(),
                                 matched)
        refs = conn.execute(
            f"SELECT {EVIDENCE_COLUMNS} FROM evidence_ref e WHERE e.claim_version_id IN (SELECT v.id {NEWEST_CLAIMS})"
            " ORDER BY e.id"
        ).fetchall()
        from gct.stages import archive  # the stages import this package

        extra = {**_missing(conn, root), **_series(matched), **_comparison(conn, matched),
                 "hidden_by_archive": [tuple(h.values()) for h in archive.hidden(conn)],
                 "sheet_mapping": conn.execute(SHEET_MAPPING_SQL).fetchall()}
    finally:
        conn.execute("COMMIT")
    return mark, companies, docs, claims, refs, extra


def _write_projection(path: Path, meta: dict, companies, docs, claims, refs, extra: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    out = sqlite3.connect(tmp, isolation_level=None)
    try:
        out.execute("PRAGMA journal_mode = DELETE")
        out.execute("BEGIN")
        for stmt in filter(str.strip, PROJECTION_SCHEMA.split(";")):
            out.execute(stmt)
        out.executemany("INSERT INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in meta.items()])
        out.executemany(f"INSERT INTO company VALUES ({','.join('?' * 4)})", [tuple(r) for r in companies])
        out.executemany(f"INSERT INTO document VALUES ({','.join('?' * 9)})", [tuple(r) for r in docs])
        out.executemany(f"INSERT INTO claim VALUES ({','.join('?' * 41)})", [tuple(r) for r in claims])
        out.executemany(f"INSERT INTO evidence_ref VALUES ({','.join('?' * 9)})", [tuple(r) for r in refs])
        for table, rows in extra.items():
            rows = [tuple(r) for r in rows]
            if rows:
                out.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)
        out.execute("COMMIT")
    except BaseException:
        out.close()
        tmp.unlink(missing_ok=True)
        raise
    out.close()
    check = open_version(tmp)
    try:
        ok = (
            check.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()[0] == str(meta["version"])
            and check.execute("SELECT COUNT(*) FROM company").fetchone()[0] == len(companies)
            and check.execute("SELECT COUNT(*) FROM document").fetchone()[0] == len(docs)
            and check.execute("SELECT COUNT(*) FROM claim").fetchone()[0] == len(claims)
        )
    finally:
        check.close()
    if not ok:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("the new published version did not verify")
    os.replace(tmp, path)


def build(conn: sqlite3.Connection, root: Path) -> dict:
    """Write the next version from current history and make it current."""
    root = Path(root)
    (root / "published").mkdir(exist_ok=True)
    version = (conn.execute("SELECT MAX(version) FROM published_version").fetchone()[0] or 0) + 1
    mark, companies, docs, claims, refs, extra = _read_history(conn, root)
    built_at = store.now()
    hid = extra["hidden_by_archive"]
    meta = {
        "version": version, "built_at": built_at, "history_mark": mark,
        "gct_version": __version__, "projection_schema": 9,
        "hidden_by_archive": json.dumps({"documents": len(hid), **{k: sum(h[i] for h in hid) for i, k in (
            (3, "claims"), (4, "evidence_refs"), (5, "review_records"))}}),
    }
    _write_projection(version_path(root, version), meta, companies, docs, claims, refs, extra)
    with store.transaction(conn):
        conn.execute(
            "INSERT INTO published_version (version, built_at, history_mark, companies, documents, gct_version)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (version, built_at, mark, len(companies), len(docs), __version__),
        )
        conn.execute(
            "INSERT INTO published_pointer (version, action, at) VALUES (?, 'build', ?)", (version, built_at)
        )
    _retain(conn, root)
    return _info(conn, version)


def _retain(conn: sqlite3.Connection, root: Path) -> None:
    """Keep the files of the current and previous version only. A file that cannot be removed waits."""
    keep = set(pointers(conn))
    purged = {r[0] for r in conn.execute("SELECT version FROM published_purge")}
    gone = []
    for (v,) in conn.execute("SELECT version FROM published_version ORDER BY version").fetchall():
        if v in keep or v in purged:
            continue
        try:
            version_path(root, v).unlink(missing_ok=True)
        except OSError:  # on Windows a reader may hold the file open
            continue
        gone.append(v)
    if gone:
        with store.transaction(conn):
            conn.executemany(
                "INSERT INTO published_purge (version, reason, at) VALUES (?, 'retention', ?)",
                [(v, store.now()) for v in gone],
            )


def _holds_deleted(conn: sqlite3.Connection, path: Path) -> bool:
    ver = open_version(path)
    try:
        ids = [r[0] for r in ver.execute("SELECT id FROM document")]
    finally:
        ver.close()
    return any(
        conn.execute(
            "SELECT 1 FROM document_state WHERE document_id = ? AND id = "
            "(SELECT MAX(id) FROM document_state WHERE document_id = ?) AND state = 'deleted'",
            (i, i),
        ).fetchone()
        for i in ids
    )


def restore(conn: sqlite3.Connection, root: Path) -> dict:
    """Make the previous version current again. Nothing is rebuilt and no file is touched."""
    _, previous = pointers(conn)
    if previous is None:
        raise GctError(REFUSED, "There is no earlier published version to go back to.", BUILD_AGAIN)
    path = version_path(root, previous)
    if not path.is_file():
        raise GctError(REFUSED, f"Version {previous} is no longer on disk.", BUILD_AGAIN)
    if _holds_deleted(conn, path):
        raise GctError(
            REFUSED,
            f"Version {previous} still contains a document that has since been deleted, so it cannot be made current again.",
            BUILD_AGAIN,
        )
    with store.transaction(conn):
        conn.execute(
            "INSERT INTO published_pointer (version, action, at) VALUES (?, 'restore', ?)", (previous, store.now())
        )
    return _info(conn, previous)


def status(conn: sqlite3.Connection, root: Path) -> dict:
    current, previous = pointers(conn)
    files = [
        r[0] for r in conn.execute("SELECT version FROM published_version ORDER BY version")
        if version_path(root, r[0]).is_file()
    ]
    info = _info(conn, current) if current is not None else {
        "version": None, "built_at": None, "history_mark": None, "companies": None, "documents": None,
    }
    return {
        "current_version": info["version"], "built_at": info["built_at"], "history_mark": info["history_mark"],
        "companies": info["companies"], "documents": info["documents"], "previous_version": previous,
        "stale": current is not None and info["history_mark"] != history_mark(conn), "files": files,
    }
