"""Permanent deletion (story 4.5, FR28 to FR32, AD-7, AD-9). The plan stores nothing; only the token it prints deletes.
The database step is one transaction: the tombstone (a 'deleted' document_state row), its attribution, the deletion
record, and the clearing of every content column of the rows attached to the document. Rows are kept, so every
foreign key and every retained review still resolves. Then the original file, its readings, its page images and every
retained published version are purged, each recorded as a step, so a second confirm finishes what a crash or a locked
file left. Copies outside the workspace (exports/, files sent elsewhere, backups) are out of GCT's reach."""
import json
import shutil
import sqlite3
from pathlib import Path

from gct.stages import archive
from gct.stages.infer import _who
from gct.workspace import published, registry, runs, store
from gct.workspace.layout import REFUSED, USAGE, GctError

STEPS = ("database", "files", "artifacts", "renders", "published", "vacuum")
WARNING = "Copies already exported or shared, including files in exports/, cannot be recalled by GCT."
OWN_TEXT = "Your capacity and rationale are kept with the deletion: do not quote the document in them."
MARKER = "cleared with document {}"
NOT_YET = 1 << 62  # the tombstone id while planning: every earlier state change counts

# Classification (P3, P4). A column is kept when it is an id, a foreign key, a state, a reason code, a date, a config
# or rules version, a contributor identity field, or a file fact of the document (sha256, kind, file type, privacy,
# size, version). Every other column is content: CLEAR names how it is cleared on the rows attached to the deleted
# document. tests/test_deletion.py fails when a table or column of the schema is in neither, so a later migration
# has to classify its own.
KEPT = {
    "schema_version": "version applied_at",
    "workspace": "id created_at gct_version",
    "company": "id name sector_ref sector_version created_at",
    "document": "id company_id version sha256 kind file_type privacy size_bytes created_at",
    "document_state": "id document_id state at",
    "published_version": "id version built_at history_mark companies documents gct_version",
    "published_pointer": "id version action at",
    "published_purge": "id version reason at",
    "run": "id started_at command gct_version",
    "run_event": "id run_id at kind stage method outcome cost_estimated cost_confirmed",
    "attempt": "id run_id stage input_version config_version method rung outcome cost_estimated cost_confirmed at",
    # Readings are hashes and measurements; the reading files themselves go in the artifacts step.
    "artifact": "id sha256 kind document_id path size_bytes created_at",
    "page": "id document_id page_number rung method config_version width height words tables flags artifact_id created_at",
    "approval": "id kind provider destination run_id amount granted created_at",
    # A locator is a position (t0r3c2, l5w2), not text.
    "claim": "id company_id document_id page_number locator sector_ref sector_version created_at",
    "claim_version": "id claim_id run_id method config_version created_at",
    "evidence_ref": "id claim_version_id document_id page_number created_at",
    "source_match": "id evidence_ref_id run_id status artifact_id config_version created_at",
    "contributor_version": "id contributor_key name organisation created_at",
    # Expectations are the user's wording and stay (P4).
    "expected_item": "id company_id metric_text period_label created_at",
    "expected_item_document": "expected_item_id document_id",
    "page_acceptance": "id document_id page_number content_type artifact_id contributor_version_id created_at",
    # documents_checked holds document ids, file hashes and reading ids only.
    "gap_confirmation": "id expected_item_id contributor_version_id documents_checked created_at",
    "basis": "id document_id page_number kind run_id config_version created_at",
    "basis_scope": "id basis_id first_page last_page contributor_version_id created_at",
    "inference": "id claim_version_id field state basis_id reason run_id config_version created_at",
    "inference_review": "id inference_id claim_version_id field decision contributor_version_id created_at",
    "correction": "id claim_version_id corrects_version_id fields contributor_version_id created_at",
    "claim_seen": "id claim_version_id page_id config_version run_id created_at",
    "metric_assignment": "id claim_version_id unit_source run_id config_version created_at",
    "match_review": "id claim_version_id reason decision contributor_version_id created_at",
    "restatement": "id original_version_id restated_version_id decision evidence_document_id evidence_page"
                   " contributor_version_id created_at",
    "document_state_change": "id document_state_id contributor_version_id created_at",
    "document_deletion": "id document_state_id plan created_at",
    "document_deletion_step": "id deletion_id step detail created_at",
    # Story 4.3: a mapping's sheet position, a note's version.
    "sheet_mapping": "id document_id position contributor_version_id created_at",
    "claim_note": "id claim_version_id created_at",
}
VERSIONS = "SELECT v.id FROM claim_version v JOIN claim c ON c.id = v.claim_id WHERE c.document_id = :d"
FREE = {"capacity": ":m", "rationale": ":m"}  # contributor-typed text on a record attached to the document (Codex 190)
PERIOD = "period_kind period_start period_end boundary boundary_detail"
# Run text that holds the document's name or source: over-clears by design (Q2). Attempts are other documents' machine
# state (cache keys, parsed outputs), so only fetch attempts, whose item and output carry a name or URL, are matched
# there; an error is text everywhere. RUNS are the document's own doc add runs, ADDRESSES the paths, folders and
# address it was added from, and the company's doc add runs (:company_runs) every add run for its company, all found
# by _own. A failure line of one of its addresses is the document's in any add run for its company.
SAYS = "(" + " OR ".join(f"instr({{c}}, :p{i}) > 0" for i in range(4)) + ")"
RUNS = "run_id IN (SELECT value FROM json_each(:runs))"
ADDRESS = "stage IN ('register', 'fetch') AND item IN (SELECT value FROM json_each(:addresses))"
ADDED = (f"(({RUNS}) OR (run_id IN (SELECT value FROM json_each(:company_runs)) AND kind = 'failure'))"
         f" AND {ADDRESS}")
FETCH = "stage = 'fetch' AND "
# The sheet stage keys its items and lines on ids (document:position, or the document), so its rows of the deleted
# document are found by that key; their output and messages hold the sheet name (story 4.3).
SHEET = "stage = 'sheet' AND (item = CAST(:d AS TEXT) OR substr(item, 1, length(:d) + 1) = :d || ':')"
# A sheet reference's check reads "cell D7 under mapping #2 reads <the cell's text>, not the claim's value".
REFS = "SELECT id FROM evidence_ref WHERE document_id = :d"


def _nulls(cols: str) -> dict:
    return dict.fromkeys(cols.split(), "NULL")


def _said(when: dict) -> tuple[str, dict]:
    """{column: condition of a row whose column is cleared} as (rows attached, {column: value written})."""
    return (" OR ".join(f"({w})" for w in when.values()),
            {c: f"CASE WHEN {c} IS NOT NULL AND ({w}) THEN :m ELSE {c} END" for c, w in when.items()})


# {table: (rows attached to document :d, {content column: value written})}. :m is "cleared with document N"; a NOT NULL
# column inside a UNIQUE key gets a value unique per row, a CHECK-bound one the value its CHECK allows.
CLEAR = {
    "document": ("id = :d", {"logical_name": ":m", "source": "NULL"}),
    "document_state": ("document_id = :d", {"note": "NULL"}),
    "claim_version": (f"id IN ({VERSIONS})", {
        **_nulls("metric_text value unit_text period_label period_kind period_start period_end metric_key boundary_detail"
                 " boundary_label"), "value_text": "''", "reporting_boundary": "'unknown'"}),
    "evidence_ref": (f"document_id = :d OR claim_version_id IN ({VERSIONS})",
                     {"boxes": "NULL", "sheet": "CASE WHEN sheet IS NULL THEN NULL ELSE '' END", "cell": "NULL"}),
    "page_acceptance": ("document_id = :d", FREE),
    "gap_confirmation": ("EXISTS (SELECT 1 FROM json_each(documents_checked) j WHERE json_extract(j.value, '$.id') = :d)",
                         FREE),
    "basis": ("document_id = :d", {"wording": ":m || ', basis ' || id",
                                   **_nulls("fy_end period_start period_end boundary boundary_detail")}),
    "basis_scope": ("basis_id IN (SELECT id FROM basis WHERE document_id = :d)", FREE),
    "inference": (f"claim_version_id IN ({VERSIONS})", {**_nulls(PERIOD), "group_key": "''"}),
    "inference_review": (f"claim_version_id IN ({VERSIONS})", {**_nulls(PERIOD), **FREE}),
    "correction": (f"claim_version_id IN ({VERSIONS})", FREE),
    "metric_assignment": (f"claim_version_id IN ({VERSIONS})", _nulls("metric_key rule unit_key unit_factor")),
    # A series key holds the printed label of an unmapped series.
    "match_review": (f"claim_version_id IN ({VERSIONS})", {"series_key": "''", **FREE}),
    "restatement": (f"original_version_id IN ({VERSIONS}) OR restated_version_id IN ({VERSIONS}) OR evidence_document_id = :d",
                    {"series_key": "''", "evidence_quote": "CASE WHEN evidence_quote IS NULL THEN NULL ELSE '' END", **FREE}),
    # The deletion's own record (:sid) is the deleting contributor's and is kept.
    "document_state_change": ("document_state_id IN (SELECT id FROM document_state WHERE document_id = :d)"
                              " AND document_state_id < :sid", FREE),
    # An item is read back by retry (ids, paths), so only the register and fetch lines of the document's own runs that
    # name one of its addresses, and the failure lines of its addresses in its company's other add runs, lose theirs,
    # with the selection notes of its own runs; a sheet line's item is ids. The
    # text rule reaches free-text messages only: another document's register line ("document M") and another run's
    # selection note are machine-read and stay.
    "run_event": _said({"item": ADDED,
                        "message": f"({ADDED}) OR ({RUNS} AND kind = 'note' AND message LIKE '{runs.SELECTION}%')"
                                   f" OR ({SHEET}) OR ({SAYS.format(c='message')}"
                                   " AND NOT (kind = 'item' AND stage = 'register' AND message GLOB 'document [0-9]*')"
                                   f" AND NOT (kind = 'note' AND message LIKE '{runs.SELECTION}%'))"}),
    "attempt": (f"({FETCH}({SAYS.format(c='item')} OR {SAYS.format(c='output')})) OR {SAYS.format(c='error')}"
                f" OR ({SHEET})", {
        "item": f"CASE WHEN {FETCH}{SAYS.format(c='item')} THEN :m ELSE item END",
        # A sheet output stays JSON, for the states read from it, with the sheet name cleared.
        "output": f"CASE WHEN output IS NULL THEN NULL WHEN {SHEET} THEN json_set(output, '$.sheet', :m)"
                  f" WHEN {FETCH}{SAYS.format(c='output')} THEN :m ELSE output END",
        "error": f"CASE WHEN error IS NOT NULL AND ({SAYS.format(c='error')} OR ({SHEET})) THEN :m ELSE error END"}),
    "source_match": (f"evidence_ref_id IN ({REFS}) AND reason LIKE 'cell %'", {"reason": ":m"}),
    "sheet_mapping": ("document_id = :d", {
        "sheet": "''", "value_col": "''", **FREE,
        **_nulls("metric_col unit_col period_col boundary_col company_col note_col year_end boundary_is boundary_detail")}),
    "claim_note": (f"claim_version_id IN ({VERSIONS})", {"text": "''"}),
}

# The published projection (schema 10): a column naming the document, one of its claims or claim versions makes the
# purge delete the row; content and kept are as above. deleted_document lists ids on purpose.
PROJECTION = {
    "meta": {"key": "kept", "value": "kept"},
    "company": dict.fromkeys(("id", "name", "sector_ref", "sector_version"), "kept"),
    "document": {"id": "document", "logical_name": "content",
                 **dict.fromkeys(("company_id", "version", "sha256", "kind", "file_type", "privacy", "size_bytes"), "kept")},
    "claim": {"id": "claim", "document_id": "document", "claim_version_id": "version",
              **dict.fromkeys(("company_id", "page_number", "locator", "sector_ref", "sector_version", "version_method",
                               "config_version", "period_state", "boundary_state", "claim_state", "needs_re_review",
                               "series_id", "match_state", "match_reason"), "kept"),
              **dict.fromkeys(("metric_text", "value_text", "value", "unit_text", "period_label", "period_kind",
                               "period_start", "period_end", "metric_key", "reporting_boundary", "boundary_detail",
                               "period_basis", "boundary_basis", "proposed_period_kind", "proposed_period_start",
                               "proposed_period_end", "proposed_reporting_boundary", "proposed_boundary_detail",
                               "boundary_label", "correction", "metric_rule", "unit_key", "unit_factor", "note"), "content")},
    "series": {"document_id": "document", **dict.fromkeys(("id", "company_id", "unit_family", "periods"), "kept"),
               **dict.fromkeys(("metric_key", "label", "reporting_boundary", "boundary_detail", "period_kind",
                                "latest_period_end"), "content")},
    "series_point": {"claim_id": "claim", "claim_version_id": "version",
                     **dict.fromkeys(("series_id", "link", "comparable", "reason"), "kept"),
                     **dict.fromkeys(("period_start", "period_end", "value_text", "unit_text", "unit_key", "number",
                                      "value_base"), "content")},
    "comparison": {"claim_a": "claim", "claim_b": "claim", "version_a": "version", "version_b": "version",
                   **dict.fromkeys(("series_id", "state", "reason", "restatement_id"), "kept"),
                   **dict.fromkeys(("period_start", "period_end"), "content")},
    "restatement": {"original_version_id": "version", "restated_version_id": "version",
                    "evidence_document_id": "document",
                    **dict.fromkeys(("id", "decision", "evidence_page", "contributor_name", "contributor_organisation",
                                     "created_at", "binds"), "kept"),
                    **dict.fromkeys(("series_key", "evidence_quote", "capacity", "rationale"), "content")},
    "evidence_ref": {"claim_version_id": "version", "document_id": "document",
                     **dict.fromkeys(("id", "page_number", "source_match", "source_match_reason"), "kept"),
                     **dict.fromkeys(("boxes", "sheet", "cell"), "content")},
    "expected_item": {"accepted": "content", **dict.fromkeys(
        ("id", "company_id", "metric_text", "period_label", "found", "claims", "state", "reasons"), "kept")},
    "expected_item_document": {"expected_item_id": "kept", "document_id": "document"},
    "gap_confirmation": {**dict.fromkeys(("id", "expected_item_id", "contributor_name", "contributor_organisation",
                                          "current", "created_at"), "kept"), "capacity": "content", "rationale": "content"},
    "page_acceptance": {"document_id": "document", **dict.fromkeys(
        ("id", "page_number", "content_type", "contributor_name", "contributor_organisation", "current", "created_at"),
        "kept"), "capacity": "content", "rationale": "content"},
    "hidden_by_archive": {"document_id": "document", "logical_name": "content",
                          **dict.fromkeys(("archived_at", "claims", "evidence_refs", "review_records"), "kept")},
    "deleted_document": {"document_id": "kept", "deleted_at": "kept"},
    "sheet_mapping": {"document_id": "document", **dict.fromkeys(
        ("id", "position", "contributor_name", "contributor_organisation", "created_at"), "kept"), **dict.fromkeys(
        ("sheet", "metric_col", "value_col", "unit_col", "period_col", "boundary_col", "company_col", "note_col",
         "year_end", "boundary_is", "boundary_detail", "capacity", "rationale"), "content")},
}


def classification() -> dict:
    """{table: {column: 'kept' or 'content'}} for workspace.db."""
    return {t: {**dict.fromkeys(cols.split(), "kept"), **dict.fromkeys(CLEAR.get(t, ("", {}))[1], "content")}
            for t, cols in KEPT.items()}


def _own(conn, doc: dict) -> tuple[list[int], list[int], list[str]]:
    """(RUNS, the company's doc add runs, ADDRESSES): the document's own doc add runs, every doc add run whose
    selection names its company, and the paths, folders and address it was added from, whatever its logical name. Its
    register lines are found by the id they record (on a workspace written before that, by a path that still holds
    the same file in a run for the document's company); their items, the folders their runs' sources give that hold
    one of them, and its source are the addresses, their runs are its runs. So is any other doc add run for its
    company whose sources are all addresses, or that gives its name or source, each compared whole (a failed add
    before a successful one, an old add of a file moved since), unless a register line of that run names another
    document."""
    me, company = f"document {doc['id']}", doc["company"].strip().casefold()

    def ours(sel) -> bool:
        return sel is not None and str(sel.get("company") or "").strip().casefold() == company

    def old(r) -> bool:  # an id-less line: the same bytes, added for this company
        return (ours(runs.selection(conn, r["run_id"])) and Path(r["item"]).is_file()
                and registry._hash_file(Path(r["item"])) == doc["sha256"])

    mine = [r for r in conn.execute("SELECT run_id, item, message FROM run_event WHERE kind = 'item'"
                                    " AND stage = 'register' AND (message = ? OR message IS NULL)", (me,))
            if r["message"] or old(r)]
    own = {r["run_id"] for r in mine}
    parents = {str(Path(r["item"]).parent) for r in mine}
    folders = {s for run_id in own for s in (runs.selection(conn, run_id) or {}).get("sources") or () if s in parents}
    addresses = {r["item"] for r in mine} | folders | ({doc["source"]} if doc["source"] else set())
    company_runs = []
    for (run_id,) in conn.execute("SELECT id FROM run WHERE command = 'doc add'").fetchall():
        sel = runs.selection(conn, run_id)
        if not ours(sel):
            continue
        company_runs.append(run_id)
        sources, name, source = sel.get("sources") or [], sel.get("name"), sel.get("source")
        given = ((sources and set(sources) <= addresses) or name == doc["logical_name"]
                 or (source is not None and source == doc["source"]))
        if run_id not in own and given and conn.execute(
                "SELECT 1 FROM run_event WHERE run_id = ? AND kind = 'item' AND stage = 'register'"
                " AND message GLOB 'document [0-9]*' AND message <> ?", (run_id, me)).fetchone() is None:
            own.add(run_id)
    return sorted(own), company_runs, sorted(addresses)


def _params(conn, doc: dict, sid: int) -> dict:
    texts = [t for x in (doc["logical_name"], doc["source"]) if x for t in dict.fromkeys((x, json.dumps(x)[1:-1]))]
    texts = (texts + [None] * 4)[:4]
    own, company_runs, addresses = _own(conn, doc)
    return {"d": doc["id"], "sid": sid, "m": MARKER.format(doc["id"]), "runs": json.dumps(own),
            "company_runs": json.dumps(company_runs), "addresses": json.dumps(addresses),
            **{f"p{i}": t for i, t in enumerate(texts)}}


def _counts(conn, params: dict) -> dict:
    """{table: rows whose content is cleared}."""
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE {where}", params).fetchone()[0]
            for t, (where, _) in CLEAR.items()}


def _clear(conn, table: str, params: dict) -> None:
    where, values = CLEAR[table]
    conn.execute(f"UPDATE {table} SET {', '.join(f'{c} = {v}' for c, v in values.items())} WHERE {where}", params)


def targets(conn, root, doc: dict) -> dict:
    """{step: (paths to remove, paths kept because a document not deleted uses them)} for the three file steps:
    the original file, the reading files and the page images."""
    root, d, sha = Path(root), doc["id"], doc["sha256"]
    shared = conn.execute(f"SELECT 1 FROM document d WHERE d.sha256 = ? AND d.id <> ? AND {registry.NOT_DELETED}",
                          (sha, d)).fetchone() is not None
    mine = {p for (p,) in conn.execute("SELECT path FROM artifact WHERE document_id = ?", (d,))}
    used = {p for (p,) in conn.execute("SELECT a.path FROM artifact a JOIN document d ON d.id = a.document_id"
                                       f" WHERE d.id <> ? AND {registry.NOT_DELETED}", (d,))}
    original, renders = [registry.stored_path(root, sha)], [root / "artifacts" / "pages" / sha]
    return {"files": ([], original) if shared else (original, []),
            "artifacts": (sorted(root / p for p in mine - used), sorted(root / p for p in mine & used)),
            "renders": ([], renders) if shared else (renders, [])}


def versions(conn, root) -> list[int]:
    """The published versions whose file is still in the workspace."""
    return [v for (v,) in conn.execute("SELECT version FROM published_version ORDER BY version").fetchall()
            if published.version_path(root, v).is_file()]


def _impact(conn, doc: dict) -> dict:
    """archive.impact() for an active document; an archived one already gives no active points (Q1)."""
    if doc["state"] != "archived":
        return archive.impact(conn, doc["id"])
    return {**archive.counts(conn, doc["id"]), "series": [], "same_period_sets": [], "uncertain_items": 0,
            "expected_items": [i for (i,) in conn.execute(
                "SELECT expected_item_id FROM expected_item_document WHERE document_id = ? ORDER BY expected_item_id",
                (doc["id"],))]}


def token(doc: dict) -> str:
    return doc["sha256"][:12]


def plan(conn, root, doc_id: int) -> dict:
    """What deleting the document removes and keeps. Writes nothing."""
    doc = registry.show_document(conn, doc_id)
    if doc["state"] == "deleted":
        raise _was_deleted(conn, doc)
    return {"document": doc, "impact": _impact(conn, doc),
            "clears": {t: n for t, n in _counts(conn, _params(conn, doc, NOT_YET)).items() if n},
            "files": {s: {"remove": sum(p.exists() for p in r), "keep": len(k)} for s, (r, k) in targets(conn, root, doc).items()},
            "versions": versions(conn, root), "warning": WARNING, "token": token(doc)}


def _deletion(conn, doc_id: int):
    return conn.execute("SELECT x.id, s.at FROM document_deletion x JOIN document_state s ON s.id = x.document_state_id"
                        " WHERE s.document_id = ?", (doc_id,)).fetchone()


def _was_deleted(conn, doc: dict) -> GctError:
    s = status(conn, doc["id"])
    next_action = (f"Finish removing it with: gct doc delete {doc['id']} --confirm {token(doc)}" if s["pending"] else
                   "Deletion cannot be undone. List the documents with: gct doc list")
    return GctError(REFUSED, f"Document {doc['id']} was deleted on {s['at'][:10]}.", next_action)


def _step(conn, deletion_id: int, step: str, detail: dict) -> None:
    conn.execute("INSERT INTO document_deletion_step (deletion_id, step, detail, created_at) VALUES (?, ?, ?, ?)",
                 (deletion_id, step, json.dumps(detail), store.now()))


def _database(conn, root, doc: dict, who: dict, capacity: str, rationale: str) -> None:
    """P2: tombstone, attribution, deletion record and the clearing, in one transaction. The append-only UPDATE
    triggers of the cleared tables are dropped and created again from their stored SQL inside it, so a failure
    leaves every trigger and row as it was."""
    d = doc["id"]
    with store.transaction(conn):
        stamp = store.now()
        sid = conn.execute("INSERT INTO document_state (document_id, state, at) VALUES (?, 'deleted', ?)",
                           (d, stamp)).lastrowid
        conn.execute("INSERT INTO document_state_change (document_state_id, contributor_version_id, capacity, rationale,"
                     " created_at) VALUES (?, ?, ?, ?, ?)", (sid, who["version"], capacity, rationale, stamp))
        params = _params(conn, doc, sid)
        counts = _counts(conn, params)
        files = {s: {"remove": len(r), "keep": len(k)} for s, (r, k) in targets(conn, root, doc).items()}
        did = conn.execute("INSERT INTO document_deletion (document_state_id, plan, created_at) VALUES (?, ?, ?)",
                           (sid, json.dumps({"clears": counts, "files": files, "versions": versions(conn, root)}),
                            stamp)).lastrowid
        triggers = dict(conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND name IN"
                                     f" ({', '.join('?' * len(CLEAR))})", [f"{t}_no_update" for t in CLEAR]).fetchall())
        for name in triggers:
            conn.execute(f"DROP TRIGGER {name}")
        for table in CLEAR:
            _clear(conn, table, params)
        for sql in triggers.values():
            conn.execute(sql)
        _step(conn, did, "database", counts)


def _remove(conn, root, doc: dict, step: str) -> dict:
    remove, keep = targets(conn, root, doc)[step]
    gone = [p for p in remove if p.exists()]
    for p in gone:
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    return {"removed": len(gone), "kept": len(keep)}


def _published(conn, root, doc: dict) -> dict:
    """Every retained version file loses the document's rows (published.purge); a published_purge row each."""
    d = doc["id"]
    claims = [c for (c,) in conn.execute("SELECT id FROM claim WHERE document_id = ?", (d,))]
    vs = [v for (v,) in conn.execute(VERSIONS, {"d": d})]
    gaps = [g for (g,) in conn.execute(f"SELECT id FROM gap_confirmation WHERE {CLEAR['gap_confirmation'][0]}", {"d": d})]
    done = versions(conn, root)
    for v in done:
        published.purge(published.version_path(root, v), d, claims, vs, gaps, MARKER.format(d))
    return {"versions": done}


def _vacuum(conn, root, doc: dict) -> dict:
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
    return {}


WORK = {"files": lambda c, r, d: _remove(c, r, d, "files"), "artifacts": lambda c, r, d: _remove(c, r, d, "artifacts"),
        "renders": lambda c, r, d: _remove(c, r, d, "renders"), "published": _published, "vacuum": _vacuum}


def _finish(conn, root, doc: dict) -> list[str]:
    """Run every step not yet recorded; returns the steps that failed (they stay pending)."""
    did = _deletion(conn, doc["id"])["id"]
    done = {s for (s,) in conn.execute("SELECT step FROM document_deletion_step WHERE deletion_id = ?", (did,))}
    failed = []
    for step in STEPS[1:]:
        if step in done:
            continue
        try:
            detail = WORK[step](conn, root, doc)
        except (OSError, sqlite3.Error):
            failed.append(step)
            continue
        with store.transaction(conn):
            if step == "published":
                conn.executemany("INSERT INTO published_purge (version, reason, at) VALUES (?, 'deletion', ?)",
                                 [(v, store.now()) for v in detail["versions"]])
            _step(conn, did, step, detail)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # the step rows written after VACUUM leave the log too
    return failed


def delete(conn, root, doc_id: int, given: str, key, capacity, rationale) -> dict:
    """Delete a document after its plan was seen (the token), or finish the steps an earlier delete left pending."""
    doc = registry.show_document(conn, doc_id)
    if given != token(doc):
        raise GctError(REFUSED, f"That is not the confirmation token of document {doc_id}.",
                       f"See the plan and its token with: gct doc delete {doc_id}")
    if doc["state"] != "deleted":
        missing = [f for f, v in (("--as", key), ("--capacity", capacity), ("--rationale", rationale)) if v is None]
        if missing:
            raise GctError(USAGE, f"Deleting needs {', '.join(missing)}.",
                           f"Give them, for example: gct doc delete {doc_id} --confirm {given} --as KEY --capacity TEXT"
                           " --rationale TEXT")
        _database(conn, root, doc, *_who(conn, key, capacity, rationale))
    elif not status(conn, doc_id)["pending"]:
        raise _was_deleted(conn, doc)
    failed = _finish(conn, root, doc)
    if failed:
        raise GctError(REFUSED, f"Document {doc_id} is deleted, but these steps did not finish: {', '.join(failed)}.",
                       f"Close any program using the workspace files, then finish with: gct doc delete {doc_id}"
                       f" --confirm {given}")
    return status(conn, doc_id)


RECORDS = {
    "page acceptance": "SELECT a.id, 'p' || a.page_number || ' ' || a.content_type, c.name, c.organisation, a.capacity,"
                       " a.rationale, a.created_at FROM page_acceptance a"
                       " JOIN contributor_version c ON c.id = a.contributor_version_id WHERE a.document_id = ?",
    "basis scope": "SELECT s.id, 'pages ' || s.first_page || '-' || s.last_page, c.name, c.organisation, s.capacity,"
                   " s.rationale, s.created_at FROM basis_scope s JOIN basis b ON b.id = s.basis_id"
                   " JOIN contributor_version c ON c.id = s.contributor_version_id WHERE b.document_id = ?",
    "sheet mapping": "SELECT m.id, 'sheet ' || m.position, c.name, c.organisation, m.capacity, m.rationale, m.created_at"
                     " FROM sheet_mapping m JOIN contributor_version c ON c.id = m.contributor_version_id"
                     " WHERE m.document_id = ?",
    "state change": "SELECT x.id, s.state, c.name, c.organisation, x.capacity, x.rationale, x.created_at"
                    " FROM document_state_change x JOIN document_state s ON s.id = x.document_state_id"
                    " JOIN contributor_version c ON c.id = x.contributor_version_id"
                    " WHERE s.document_id = ? AND s.state <> 'deleted'",
}


def status(conn, doc_id: int) -> dict | None:
    """None unless the document was deleted; else when, the steps done and pending, and the records attached to the
    document itself that stay (each with its marker, P5)."""
    row = _deletion(conn, doc_id)
    if row is None:
        return None
    done = {s for (s,) in conn.execute("SELECT step FROM document_deletion_step WHERE deletion_id = ?", (row["id"],))}
    mark = registry.evidence_deleted(conn, doc_id)
    records = [{"kind": kind, "id": r[0], "what": r[1], "contributor": r[2], "organisation": r[3], "capacity": r[4],
                "rationale": r[5], "created_at": r[6], "evidence_deleted": mark}
               for kind, sql in RECORDS.items() for r in conn.execute(sql + " ORDER BY 1", (doc_id,))]
    return {"at": row["at"], "steps": [s for s in STEPS if s in done], "pending": [s for s in STEPS if s not in done],
            "records": records}
