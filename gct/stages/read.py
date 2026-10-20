"""Rung 1: read every page of the selected PDF documents with pdfplumber into JSON artifact files."""
import contextlib
import hashlib
import json
import os
from collections import Counter
from importlib.metadata import version
from pathlib import Path

from gct.ladder import quality
from gct.stages import Result, Stage, run_stage, version_of
from gct.workspace import registry, runs, store

NOT_OPENED = "The PDF could not be opened. It may be damaged or password protected."
NOT_OPENED_NEXT = "Check the file opens in a PDF viewer, then add a readable copy with gct doc add."
RETRY = "Run gct read again. Pages already read are not read twice."
KIND = "reading"
ACTIVE = ("registered", "restored")
NOT_ACTIVE = "the document is no longer active"

# A page whose newest attempt in the run failed, with no ok attempt since.
FAILED_PAGES_SQL = """
SELECT a.item FROM attempt a
WHERE a.run_id = ? AND a.stage = 'read' AND a.outcome = 'failed'
  AND a.id = (SELECT MAX(b.id) FROM attempt b WHERE b.run_id = a.run_id AND b.stage = a.stage AND b.item = a.item)
  AND NOT EXISTS (SELECT 1 FROM attempt c WHERE c.stage = a.stage AND c.item = a.item AND c.outcome = 'ok' AND c.id > a.id)
ORDER BY a.id
"""
# A document that could not be opened in the run (a failure event, no attempt), with no page read ok in a later run.
NOT_OPENED_SQL = """
SELECT e.item FROM run_event e
WHERE e.run_id = ? AND e.kind = 'failure' AND e.stage = 'read' AND instr(e.item, ':') = 0
  AND NOT EXISTS (SELECT 1 FROM attempt a WHERE a.stage = 'read' AND a.item LIKE e.item || ':%'
                  AND a.outcome = 'ok' AND a.run_id > e.run_id)
GROUP BY e.item ORDER BY MIN(e.id)
"""

NEWEST_SQL = """
SELECT p.*, a.sha256 FROM page p JOIN artifact a ON a.id = p.artifact_id
WHERE p.id = (SELECT MAX(q.id) FROM page q WHERE q.document_id = p.document_id AND q.page_number = p.page_number
              AND (? IS NULL OR q.config_version = ?))
  AND p.document_id = ?
ORDER BY p.page_number
"""


def read_config() -> str:
    """Called once per command, so a changed threshold or pdfplumber version is never served a stale reading."""
    return version_of("read", 1, "pdfplumber", version("pdfplumber"), quality.thresholds())


class _Page:
    """A stage item: one page of a document, carrying its open pdfplumber page."""

    def __init__(self, doc: dict, page):
        self.doc, self.page = doc, page

    def __str__(self) -> str:
        return f"{self.doc['id']}:{self.page.page_number}"


def _r(x) -> float:
    return round(float(x), 2)


def read_page(page) -> dict:
    """The reading of one pdfplumber page: coordinates in PDF points, top-left origin, 2 decimals."""
    reading = {
        "page": page.page_number,
        "width": _r(page.width),
        "height": _r(page.height),
        "text": page.extract_text() or "",
        "words": [{"text": w["text"], **{k: _r(w[k]) for k in ("x0", "top", "x1", "bottom")}} for w in page.extract_words()],
        "tables": [{"bbox": [_r(v) for v in t.bbox], "rows": t.extract()} for t in page.find_tables()],
    }
    page.close()  # drop pdfplumber's per-page cache so a long report does not pile up in memory
    return reading


def _summary(row) -> dict:
    return {"page_id": row["id"], "artifact": row["sha256"], "words": row["words"], "tables": row["tables"],
            "flags": json.loads(row["flags"])}


def _work(root: Path, config: str, item: _Page, conn) -> Result:
    doc_id, number = item.doc["id"], item.page.page_number
    done = conn.execute(
        "SELECT p.*, a.sha256 FROM page p JOIN artifact a ON a.id = p.artifact_id"
        " WHERE p.document_id = ? AND p.page_number = ? AND p.config_version = ? ORDER BY p.id DESC LIMIT 1",
        (doc_id, number, config),
    ).fetchone()
    if done is None:  # else an earlier run committed the page but not its attempt
        reading = read_page(item.page)
        flags = quality.check(reading)
        data = json.dumps(reading, sort_keys=True, ensure_ascii=False).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        rel = Path("artifacts") / digest[:2] / f"{digest}.json"
        dest = root / rel
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
        stamp = store.now()
        with store.transaction(conn):
            art = conn.execute(
                "SELECT id FROM artifact WHERE document_id = ? AND sha256 = ? AND kind = ?", (doc_id, digest, KIND)
            ).fetchone()
            art_id = art[0] if art else conn.execute(
                "INSERT INTO artifact (sha256, kind, document_id, path, size_bytes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (digest, KIND, doc_id, rel.as_posix(), len(data), stamp),
            ).lastrowid
            page_id = conn.execute(
                "INSERT INTO page (document_id, page_number, rung, method, config_version, width, height, words, tables,"
                " flags, artifact_id, created_at) VALUES (?, ?, 1, 'pdfplumber', ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, number, config, reading["width"], reading["height"], len(reading["words"]),
                 len(reading["tables"]), json.dumps(flags), art_id, stamp),
            ).lastrowid
        done = conn.execute("SELECT p.*, a.sha256 FROM page p JOIN artifact a ON a.id = p.artifact_id WHERE p.id = ?",
                            (page_id,)).fetchone()
    return Result(output=_summary(done), method="pdfplumber", rung=1)


def _doc(d: dict, action: str, cause=None, next_action=None, **counts) -> dict:
    out = {"id": d["id"], "logical_name": d["logical_name"], "pages": 0, "read": 0, "cached": 0, "flagged": 0,
           "failed": 0, "flags": {}, "action": action, "cause": cause, "next_action": next_action}
    return {**out, **counts}


def select(conn, ids, company) -> list[dict]:
    """Exactly the given ids, else every active document (of one company when given). Unknown ids or company raise."""
    if company is not None:
        registry._find_company(conn, company)
    if not ids:
        return [d for d in registry.list_documents(conn, company) if d["state"] in ACTIVE]
    return [registry.show_document(conn, i) for i in dict.fromkeys(ids)]


def _read(conn, root, run_id, docs, wanted=None) -> list[dict]:
    """Read each document in the run. wanted maps a document id to the page numbers to retry (None: every page)."""
    import pdfplumber  # 0.8 s; only commands that read pay for it

    root = Path(root)
    config = read_config()
    stage = Stage("read", config, lambda item, conn: _work(root, config, item, conn),
                  lambda item: version_of(item.doc["sha256"], item.page.page_number))
    out = []
    for d in docs:
        if d["file_type"] != "pdf":
            out.append(_doc(d, "skipped", "not a PDF"))
            continue
        only = (wanted or {}).get(d["id"])
        with contextlib.ExitStack() as stack:
            try:
                pages = stack.enter_context(pdfplumber.open(registry.stored_path(root, d["sha256"]))).pages
            except Exception:
                runs.event(conn, run_id, "failure", stage="read", item=str(d["id"]), message=NOT_OPENED)
                out.append(_doc(d, "failed", NOT_OPENED, NOT_OPENED_NEXT))
                continue
            items = [_Page(d, p) for p in pages if only is None or p.page_number in only]
            # only_failed=False: retry's pages are already the failed set, and a changed config must still read them.
            counts = run_stage(conn, run_id, stage, items)
        rows = conn.execute(NEWEST_SQL, (config, config, d["id"])).fetchall()
        flags = Counter(f for r in rows for f in json.loads(r["flags"]))
        failed = counts["failed"]
        out.append(_doc(
            d, "read", f"{failed} of {len(pages)} pages could not be read." if failed else None,
            RETRY if failed else None, pages=len(pages), read=counts["processed"], cached=counts["cached"],
            flagged=sum(bool(json.loads(r["flags"])) for r in rows), failed=failed, flags=dict(sorted(flags.items())),
        ))
    return out


def read(conn, root, ids=(), company=None, notes=()) -> tuple[int | None, list[dict]]:
    """Read the selection in one run. A damaged document or a failing page is reported and the run keeps going.
    Returns the run id (None when there was nothing to read) and one record per document."""
    docs = select(conn, ids, company)
    if not docs:
        return None, []
    with runs.run(conn, "read") as run_id:
        runs.record(conn, run_id, {"ids": list(ids), "company": company}, notes)
        out = _read(conn, root, run_id, docs)
    return run_id, out


def failed(conn, run_id: int) -> dict:
    """{document id: page numbers to retry, or None to read it again in full} for what failed in the run
    and has not been read ok since."""
    out = {}
    for (item,) in conn.execute(NOT_OPENED_SQL, (run_id,)):
        out[int(item)] = None
    for (item,) in conn.execute(FAILED_PAGES_SQL, (run_id,)):
        doc_id, number = map(int, item.split(":"))
        if out.get(doc_id, set()) is not None:
            out.setdefault(doc_id, set()).add(number)
    return dict(sorted(out.items()))


def retry(conn, root, wanted: dict, notes=()) -> tuple[int, list[dict]]:
    """Read again exactly what failed (see failed) in a new run. A document no longer active is skipped."""
    docs = [registry.show_document(conn, i) for i in wanted]
    active = [d for d in docs if d["state"] in ACTIVE]
    with runs.run(conn, "read") as run_id:
        runs.record(conn, run_id, {"ids": [d["id"] for d in active], "company": None}, notes)
        out = [_doc(d, "skipped", NOT_ACTIVE) for d in docs if d["state"] not in ACTIVE]
        out += _read(conn, root, run_id, active, wanted)
    return run_id, out


def pages(conn, doc_id: int) -> list[dict]:
    """The newest page row per page number, whatever configuration made it."""
    registry.show_document(conn, doc_id)
    return [
        {"page_number": r["page_number"], "rung": r["rung"], "method": r["method"], "width": r["width"],
         "height": r["height"], "words": r["words"], "tables": r["tables"], "flags": json.loads(r["flags"]),
         "artifact": r["sha256"]}
        for r in conn.execute(NEWEST_SQL, (None, None, doc_id))
    ]
