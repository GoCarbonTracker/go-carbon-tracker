"""Source match: whether a claim's stored location reproduces its figure on the newest reading of its page.
A procedure result, never a verification. For rung-1 claims `matched` follows from how the box was made;
the check exists for later rungs, corrections and re-reads."""
import json
from pathlib import Path

from gct.stages import Result, Stage, run_stage, version_of
from gct.stages.extract import FAILED_PAGES_SQL, _centre_in, _lines, _union
from gct.stages.read import ACTIVE, NEWEST_SQL, NOT_ACTIVE, select
from gct.workspace import registry, runs, store

CONFIG = version_of("link", 1)
NOT_READ = "page not read: gct read"
EXTRACT_FIRST = "extract it first: gct extract"
RETRY = "Run gct link again. Locations already checked against the same reading are not checked twice."
FAILED_SQL = FAILED_PAGES_SQL.replace("a.stage = 'extract'", "a.stage = 'link'")
# The evidence refs of the newest version of every claim of one document.
REFS_SQL = """
SELECT e.id, e.page_number, e.boxes, e.sheet, v.value_text, v.unit_text
FROM claim c JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)
JOIN evidence_ref e ON e.claim_version_id = v.id
WHERE c.document_id = ? ORDER BY e.id
"""
NEWEST_MATCH = "(SELECT MAX(id) FROM source_match WHERE evidence_ref_id = e.id)"


def match(ref: dict, reading: dict | None) -> tuple[str, str | None]:
    """(status, reason) for one evidence ref (boxes decoded) against a page reading (None: the page has none)."""
    if ref["sheet"] is not None:
        return "unresolved", "spreadsheet check not built"
    if reading is None:
        return "unresolved", NOT_READ
    if not ref["boxes"]:
        return "cited", "no box"
    box = _union([dict(zip(("x0", "top", "x1", "bottom"), b)) for b in ref["boxes"]])
    inside = [w for w in reading["words"] if _centre_in(w, box)]
    printed = " ".join(w["text"] for line in _lines(inside) for w in line).rstrip(".,;:")
    value, unit = ref["value_text"], ref["unit_text"]
    # Decision S: the figure as printed, alone or with its stored unit attached or as the next word(s). Nothing else.
    if printed in (value, *((value + unit, f"{value} {unit}") if unit else ())):
        return "matched", None
    return "cited", "box does not reproduce the figure"


def record(conn, ref_id: int, run_id: int, status: tuple, artifact_id, stamp: str) -> None:
    """Insert a status row unless the newest one for the ref already says the same against the same reading."""
    row = (*status, artifact_id, CONFIG)
    last = conn.execute("SELECT status, reason, artifact_id, config_version FROM source_match"
                        " WHERE evidence_ref_id = ? ORDER BY id DESC LIMIT 1", (ref_id,)).fetchone()
    if last is None or tuple(last) != row:
        conn.execute("INSERT INTO source_match (evidence_ref_id, run_id, status, reason, artifact_id, config_version,"
                     " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (ref_id, run_id, *row, stamp))


class _Ref:
    """A stage item: one evidence ref with the newest reading of its page (None: not read)."""

    def __init__(self, doc: dict, ref: dict, page):
        self.doc, self.ref, self.page = doc, ref, page

    def __str__(self) -> str:
        return f"{self.doc['id']}:{self.ref['id']}"


def _work(root: Path, run_id: int, item: _Ref, conn) -> Result:
    reading = None
    if item.page is not None:
        path = conn.execute("SELECT path FROM artifact WHERE id = ?", (item.page["artifact_id"],)).fetchone()[0]
        reading = json.loads((root / path).read_text(encoding="utf-8"))
    status = match(item.ref, reading)
    with store.transaction(conn):
        record(conn, item.ref["id"], run_id, status, item.page and item.page["artifact_id"], store.now())
    return Result(output={"status": status[0]}, method="link")


def _doc(d: dict, action: str, cause=None, next_action=None, **counts) -> dict:
    out = {"id": d["id"], "logical_name": d["logical_name"], "refs": 0, "checked": 0, "cached": 0, "failed": 0,
           "matched": 0, "cited": 0, "unresolved": 0, "action": action, "cause": cause, "next_action": next_action}
    return {**out, **counts}


def _link(conn, root, run_id, docs, wanted=None) -> list[dict]:
    """Check each document's refs in the run. wanted maps a document id to the ref ids to retry (absent: all)."""
    root = Path(root)
    stage = Stage("link", CONFIG, lambda item, conn: _work(root, run_id, item, conn),
                  # The page row, not the artifact sha: a newer row may point back at an earlier artifact (A, B, A).
                  lambda item: f"page {item.page['id']}" if item.page is not None else "none")
    out = []
    for d in docs:
        only = (wanted or {}).get(d["id"])
        pages = {p["page_number"]: p for p in conn.execute(NEWEST_SQL, (None, None, d["id"]))}
        items = [_Ref(d, {**dict(r), "boxes": r["boxes"] and json.loads(r["boxes"])}, pages.get(r["page_number"]))
                 for r in conn.execute(REFS_SQL, (d["id"],)) if only is None or r["id"] in only]
        if not items:
            runs.event(conn, run_id, "note", stage="link", item=str(d["id"]), message=EXTRACT_FIRST)
            out.append(_doc(d, "skipped", "This document has no claims yet.", EXTRACT_FIRST))
            continue
        counts = run_stage(conn, run_id, stage, items)
        ids = ",".join(str(i.ref["id"]) for i in items)
        statuses = dict(conn.execute(f"SELECT s.status, COUNT(*) FROM evidence_ref e JOIN source_match s"
                                     f" ON s.id = {NEWEST_MATCH} WHERE e.id IN ({ids}) GROUP BY s.status").fetchall())
        failed = counts["failed"]
        out.append(_doc(
            d, "checked", f"{failed} of {len(items)} locations could not be checked." if failed else None,
            RETRY if failed else None, refs=len(items), checked=counts["processed"], cached=counts["cached"],
            failed=failed, **statuses,
        ))
    return out


def link(conn, root, ids=(), company=None, notes=()) -> tuple[int | None, list[dict]]:
    """Check the source locations of the selection's newest claims in one run. Never opens a PDF."""
    docs = select(conn, ids, company)
    if not docs:
        return None, []
    with runs.run(conn, "link") as run_id:
        runs.record(conn, run_id, {"ids": list(ids), "company": company}, notes)
        out = _link(conn, root, run_id, docs)
    return run_id, out


def failed(conn, run_id: int) -> dict:
    """{document id: ref ids} whose check failed in the run and has not succeeded since."""
    out = {}
    for (item,) in conn.execute(FAILED_SQL, (run_id,)):
        doc_id, ref_id = map(int, item.split(":"))
        out.setdefault(doc_id, set()).add(ref_id)
    return dict(sorted(out.items()))


def retry(conn, root, wanted: dict, notes=()) -> tuple[int, list[dict]]:
    """Check again exactly the failed refs (see failed) in a new run. A document no longer active is skipped."""
    docs = [registry.show_document(conn, i) for i in wanted]
    active = [d for d in docs if d["state"] in ACTIVE]
    with runs.run(conn, "link") as run_id:
        runs.record(conn, run_id, {"ids": [d["id"] for d in active], "company": None}, notes)
        out = [_doc(d, "skipped", NOT_ACTIVE) for d in docs if d["state"] not in ACTIVE]
        out += _link(conn, root, run_id, active, wanted)
    return run_id, out
