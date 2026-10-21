"""Rung 1: read every page of the selected PDF documents with pdfplumber into JSON artifact files."""
import contextlib
import hashlib
import json
import os
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from statistics import median

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


# Text directions in the order their groups are written to `text` and numbered as lines, and for each the direction
# in which its next line starts (pdfplumber's line_dir).
DIRS = ("ltr", "rtl", "ttb", "btt")
LINE_DIR = {"ltr": "ttb", "rtl": "ttb", "ttb": "rtl", "btt": "ltr"}
LINE_TOL = 2  # points: words whose line-axis positions differ by this or less are on one line (3.1)
ROW_TOL = 3  # points: pdfplumber's own y_tolerance, the one that merged columns into one text line
# Columns: a block of at least GUTTER_LINES lines splits into columns at a gap at least GUTTER wide that no word or
# table of the block crosses; a gap of BLOCK_GAP or more across the lines splits a region into blocks. Mahindra AR
# p114 prints its item-13 answer 8 pt from the question, with word gaps of 2 to 4 pt; a form item of one or two lines
# keeps its label and answer on one line. A gap one line's own words border on both sides is a word space unless it is
# more than OVER_SPACE wider than that line's middle space: Tata AR p134 row 4 prints "depreciation, amortization,"
# 6.3 pt apart, its other spaces 6.2 to 6.3, so "amortization," alone past that gap is no column.
GUTTER = 6
GUTTER_LINES = 3
OVER_SPACE = 1
BLOCK_GAP = 5


def read_config() -> str:
    """Called once per command, so a changed threshold or pdfplumber version is never served a stale reading."""
    return version_of("read", 4, "pdfplumber", version("pdfplumber"), quality.thresholds(),
                      DIRS, LINE_TOL, ROW_TOL, GUTTER, GUTTER_LINES, OVER_SPACE, BLOCK_GAP)


def char_dir(ch) -> str:
    """The reading direction of one character, from its text matrix: rotations inside an unrotated page."""
    a, b = ch["matrix"][:2]
    return "btt" if b > 0 else "ttb" if b < 0 else "rtl" if a < 0 else "ltr"


def _dir(w) -> str:
    return w.get("dir", "ltr")  # readings before config 3 carry no direction


def _extent(w) -> tuple:
    """((from, to) across lines, (from, to) along the reading direction) of a box, in its direction's own frame:
    lines are numbered and words ordered by ascending values."""
    across, along = ((w["top"], w["bottom"]), (w["x0"], w["x1"])) if _dir(w) in ("ltr", "rtl") else \
        ((w["x0"], w["x1"]), (w["top"], w["bottom"]))
    if _dir(w) == "ttb":
        across = (-across[1], -across[0])
    if _dir(w) in ("rtl", "btt"):
        along = (-along[1], -along[0])
    return across, along


def _centre_in(w: dict, box) -> bool:
    x0, top, x1, bottom = box
    return x0 <= (w["x0"] + w["x1"]) / 2 <= x1 and top <= (w["top"] + w["bottom"]) / 2 <= bottom


def _cluster(words, tol) -> list[list[dict]]:
    """Words of one direction grouped on their line axis within tol, each line in reading order."""
    out = []
    for w in sorted(words, key=lambda w: (_extent(w)[0][0], _extent(w)[1][0])):
        if out and _extent(w)[0][0] - _extent(out[-1][0])[0][0] <= tol:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(line, key=lambda w: _extent(w)[1][0]) for line in out]


def lines(words) -> list[list[dict]]:
    """Text lines in reading order: by direction group (DIRS), then column, then along the line axis. A line never
    crosses a column gutter, and a rotated line runs along its own axis. Words without dir or col read as ltr, 0."""
    groups = {}
    for w in words:
        groups.setdefault((DIRS.index(_dir(w)), w.get("col", 0)), []).append(w)
    return [line for key in sorted(groups) for line in _cluster(groups[key], LINE_TOL)]


def _widest_gap(spans, least, ok):
    """The middle of the widest gap at least `least` wide between the (from, to) spans with ok(from, to), or None."""
    best, reach = None, None
    for start, end in sorted(spans):
        if reach is not None and start - reach >= least and (best is None or start - reach > best[1] - best[0]) \
                and ok(reach, start):
            best = (reach, start)
        reach = end if reach is None else max(reach, end)
    return best and (best[0] + best[1]) / 2


def _cut(items) -> list[list]:
    """Recursive cut of (across, along, key) boxes of one direction into regions in reading order: columns first (a
    gap along the lines no box crosses, in a block of GUTTER_LINES lines or more, that is no word space), else blocks
    (a gap across them)."""
    lines, n, order = {}, 0, sorted(items, key=lambda i: i[0][0])
    for prev, i in zip([None, *order], order):
        n += prev is not None and i[0][0] - prev[0][0] > ROW_TOL
        if not isinstance(i[2], tuple):  # words only: a table box is on no line of its own
            lines.setdefault(n, []).append(i[1])

    def no_word_space(lo, hi) -> bool:
        """False when one line's own words make both edges of the gap and it is at most OVER_SPACE wider than the
        line's middle word space."""
        # ponytail: OVER_SPACE is set from one justified line (p134 row 4). Upgrade: a layout model rung (2.5 to 2.8).
        # Measured ceiling (all 822 real pages): unruled multi-line table headers (Tata AR p476, p285) read row by row
        # across their header columns, since on a line whose words each sit in a different column the middle word
        # space is the gutter. No claim or basis changes on the story's reports; for 3.6.
        for spans in lines.values():
            spans = sorted(spans)
            pairs = list(zip(spans, spans[1:]))
            others = [b[0] - a[1] for a, b in pairs if (a[1], b[0]) != (lo, hi)]
            if len(others) < len(pairs) and others and hi - lo <= median(others) + OVER_SPACE:
                return False
        return True

    for side, least, ok in ((1, GUTTER, no_word_space), (0, BLOCK_GAP, lambda lo, hi: True)):
        if side and n + 1 < GUTTER_LINES:
            continue
        at = _widest_gap([i[side] for i in items], least, ok)
        if at is not None:
            return _cut([i for i in items if i[side][0] < at]) + _cut([i for i in items if i[side][0] >= at])
    return [items]


def _columns(words, bboxes) -> None:
    """Set col on each word: its region's number in reading order within its direction, from words outside every
    table, with each table one box no cut can cross. A word inside a table takes the table's region."""
    # ponytail: a gap across both columns at one height splits them into blocks read one after the other; prose
    # paragraphs that end level in both columns read top block first. Upgrade: a layout model rung (2.5 to 2.8).
    for d in DIRS:
        group = [w for w in words if w["dir"] == d]
        if not group:
            continue
        inside = {id(w): next((t for t, b in enumerate(bboxes) if _centre_in(w, b)), None) for w in group}
        items = [(*_extent(w), id(w)) for w in group if inside[id(w)] is None]
        items += [(*_extent({"dir": d, **dict(zip(("x0", "top", "x1", "bottom"), b))}), ("table", t))
                  for t, b in enumerate(bboxes) if t in inside.values()]
        region, n, end = {}, -1, None
        for leaf in _cut(items):  # a region wholly below the one before continues its column: one column is col 0
            if end is None or min(a[0] for a, _, _ in leaf) < end:
                n += 1
            end = max(a[1] for a, _, _ in leaf)
            region.update({key: n for _, _, key in leaf})
        for w in group:
            w["col"] = region[id(w) if inside[id(w)] is None else ("table", inside[id(w)])]


def _words(page) -> list[dict]:
    """Words built per direction group with pdfplumber's word extractor, each with its direction; never reversed."""
    out = []
    for d in DIRS:
        if not any(char_dir(c) == d for c in page.chars):
            continue
        group = page.filter(lambda o, d=d: o.get("object_type") != "char" or char_dir(o) == d)
        out += [{"text": w["text"], **{k: _r(w[k]) for k in ("x0", "top", "x1", "bottom")}, "dir": d}
                for w in group.extract_words(char_dir=d, line_dir=LINE_DIR[d], char_dir_rotated=d,
                                             line_dir_rotated=LINE_DIR[d])]
    return out


class _Page:
    """A stage item: one page of a document, carrying its open pdfplumber page."""

    def __init__(self, doc: dict, page):
        self.doc, self.page = doc, page

    def __str__(self) -> str:
        return f"{self.doc['id']}:{self.page.page_number}"


def _r(x) -> float:
    return round(float(x), 2)


def read_page(page) -> dict:
    """The reading of one pdfplumber page: coordinates in PDF points, top-left origin, 2 decimals. Words, lines, cell
    text and `text` follow each character's own direction; `text` is written column by column."""
    tables = [{"bbox": [_r(v) for v in t.bbox], "cells": [[c and [_r(v) for v in c] for c in row.cells] for row in t.rows]}
              for t in page.find_tables()]
    words = _words(page)
    _columns(words, [t["bbox"] for t in tables])
    ordered = lines(words)
    for t in tables:  # cell text from the words inside the cell, in their own reading order, never t.extract()
        t["rows"] = [[None if c is None else "\n".join(" ".join(w["text"] for w in line)
                                                     for line in lines([w for w in words if _centre_in(w, c)]))
                      for c in row] for row in t["cells"]]
    reading = {
        "page": page.page_number,
        "width": _r(page.width),
        "height": _r(page.height),
        "text": "\n".join(" ".join(w["text"] for w in line) for line in ordered),
        "words": [w for line in ordered for w in line],
        "tables": [{"bbox": t["bbox"], "rows": t["rows"], "cells": t["cells"]} for t in tables],
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
