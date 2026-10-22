"""Rung 1 extraction: fixed reading rules over each page reading. A labelled no-model baseline; its accuracy is not measured."""
import json
import re
from pathlib import Path

from gct.stages import Result, Stage, result, run_stage, version_of
from gct.stages.read import ACTIVE, NEWEST_SQL, NOT_ACTIVE, _centre_in, _cluster, select
from gct.stages.read import lines as _lines
from gct.workspace import registry, runs, store

METHOD = "rung1-rules"
RULES_VERSION = 5
READ_FIRST = "read it first: gct read"
RETRY = "Run gct extract again. Pages already extracted are not extracted twice."

# Detects units; never converts them. A space or a slash inside the unit as printed is allowed ("t CO2e").
UNITS = {"tCO2e", "tCO2", "tonnes", "t", "kt", "Mt", "MWh", "GWh", "kWh", "GJ", "TJ", "kL", "ML", "m3", "%"}
NUMBER = re.compile(r"(\(?-?\d(?:[\d,.]*\d)?\)?)(\S*)")
WESTERN = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")
YEAR = re.compile(r"199\d|20\d\d|2100")
PERIOD = re.compile(r"(?<!\w)(?<!\d[,.])(?:FY\s?\d{2,4}(?:-\d{2,4})?|\d{4}-\d{2,4}|199\d|20\d\d|2100)(?!\w|[,.]\d)")
# Column headers printed above a table: lines within HEADER_BAND points of its top; words WORD_GAP points apart or
# closer are one header. A boundary header is kept as printed and never becomes a reporting boundary (rule B2).
HEADER_BAND = 30
WORD_GAP = 6
BOUNDARY = re.compile(r"(?:standalone|consolidated)\*?", re.I)
DASHES = ("-", "–", "—")  # a dash cell is empty, never a row label (Tata AR p134 row 5: "-", "-", "699.80")
# A comparison year: the period right after a comparison phrase, for every text figure. No change-word gate: Tata AR
# p135 prints "volumes have decreased by" and "12% as compared to FY23." on two lines.
COMPARED = re.compile(r"\b(?:as\s+compared\s+to|compared\s+to|as\s+against|vs\.?|versus)\s*$", re.I)
FAILED_PAGES_SQL = """
SELECT a.item FROM attempt a
WHERE a.run_id = ? AND a.stage = 'extract' AND a.outcome = 'failed'
  AND a.id = (SELECT MAX(b.id) FROM attempt b WHERE b.run_id = a.run_id AND b.stage = a.stage AND b.item = a.item)
  AND NOT EXISTS (SELECT 1 FROM attempt c WHERE c.stage = a.stage AND c.item = a.item AND c.outcome = 'ok' AND c.id > a.id)
ORDER BY a.id
"""
CLAIMS_SQL = """
SELECT c.id, c.page_number, c.locator, v.value_text, v.value, v.unit_text, v.metric_text, v.period_label,
       v.reporting_boundary, v.boundary_label, v.method, e.boxes, s.status AS source_match, s.reason AS source_match_reason
FROM claim c JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)
LEFT JOIN evidence_ref e ON e.claim_version_id = v.id
LEFT JOIN source_match s ON s.id = (SELECT MAX(id) FROM source_match WHERE evidence_ref_id = e.id)
WHERE c.document_id = ? ORDER BY c.page_number, c.id
"""


def extract_config() -> str:
    return version_of("extract", 1, RULES_VERSION)


def _clean(s) -> str:
    return " ".join(str(s or "").split())


def _unit(text: str) -> str | None:
    return text if text.replace(" ", "").replace("/", "") in UNITS else None


def _figure(token: str):
    """(number as printed, attached unit or None) when the token is a figure, else None. Years are not figures."""
    m = NUMBER.fullmatch(token.rstrip(".,;:"))
    if not m:
        return None
    number, rest = m.groups()
    if rest and not _unit(rest):
        return None
    if not rest and YEAR.fullmatch(number):
        return None
    return number, rest or None


def _cell_figure(text: str):
    """A table cell holding one figure, optionally followed by a unit word."""
    first, _, rest = text.partition(" ")
    fig = _figure(first)
    if not fig or not rest:
        return fig
    return (fig[0], _unit(rest)) if fig[1] is None and _unit(rest) else None


def _value(number: str) -> float | None:
    """Only the unambiguous Western form gets a value; parentheses never infer a sign."""
    return float(number.replace(",", "")) if WESTERN.fullmatch(number) else None


def _union(ws) -> list:
    return [min(w["x0"] for w in ws), min(w["top"] for w in ws), max(w["x1"] for w in ws), max(w["bottom"] for w in ws)]


def _claim(locator, metric, number, unit, period, boxes, boundary=None) -> dict:
    return {"locator": locator, "metric_text": metric, "value_text": number, "value": _value(number),
            "unit_text": unit, "period_label": period, "boundary_label": boundary, "boxes": boxes}


def _overlaps(a0, a1, b0, b1) -> bool:
    return a0 < b1 and a1 > b0


def _outside(reading: dict) -> list[dict]:
    """Left-to-right words outside every table."""
    return [w for w in reading["words"] if w.get("dir", "ltr") == "ltr"
            and not any(_centre_in(w, t["bbox"]) for t in reading["tables"])]


def _headers(reading: dict, t: int, spans: list) -> dict:
    """{column: {"period": .., "boundary": ..}} from the header lines printed just above table t: the lines within
    HEADER_BAND of its top, nearest first, stopping at a line that is not all period and boundary words or that has
    another table between it and this one. A header word group heads each column whose x-range it overlaps."""
    x0, top, x1, _ = reading["tables"][t]["bbox"]
    band = [w for w in _outside(reading) if 0 <= top - w["bottom"] <= HEADER_BAND and _overlaps(w["x0"], w["x1"], x0, x1)]
    others = [o["bbox"] for i, o in enumerate(reading["tables"]) if i != t]
    out = {}
    for line in sorted(_cluster(band, 2), key=lambda line: -max(w["bottom"] for w in line)):
        bottom = max(w["bottom"] for w in line)
        if any(b[1] >= bottom and b[3] <= top and _overlaps(b[0], b[2], x0, x1) for b in others):
            break
        groups = []
        for w in line:  # adjacent words within WORD_GAP are one header ("FY 24")
            if groups and w["x0"] - groups[-1][-1]["x1"] <= WORD_GAP:
                groups[-1].append(w)
            else:
                groups.append([w])
        heads = [(" ".join(w["text"] for w in g), g[0]["x0"], g[-1]["x1"]) for g in groups]
        kinds = ["period" if PERIOD.fullmatch(s) else "boundary" if BOUNDARY.fullmatch(s) else None for s, *_ in heads]
        if None in kinds:
            break
        for (s, g0, g1), kind in zip(heads, kinds):
            for c, span in enumerate(spans):
                if span and _overlaps(g0, g1, span[0], span[2]):
                    out.setdefault(c, {}).setdefault(kind, s)  # the nearest header of a kind wins
    return out


def _row_label(reading: dict, t: int, cells_row: list) -> str | None:
    """The words left of table t whose vertical centre falls inside the row's cell band."""
    # ponytail: no column-region test; the cut that keeps a label column beside its table (Tata AR p134) also files
    # it with the text below, so a prose column left of a detected table would lend its line. Upgrade: regions
    # recorded per reading, not only a column number.
    x0 = reading["tables"][t]["bbox"][0]
    boxes = [c for c in cells_row if c]
    if not boxes:
        return None
    top, bottom = min(b[1] for b in boxes), max(b[3] for b in boxes)
    left = [w for w in _outside(reading) if w["x1"] <= x0 and top <= (w["top"] + w["bottom"]) / 2 <= bottom]
    # Figure and unit words right of the last wording word are value columns printed outside the bbox (Mahindra AR
    # p75), never the label; a row with no wording has no label. Numbers inside the wording stay ("Scope 1 emissions").
    wording = [w for w in left if not (_figure(w["text"]) or _unit(w["text"]) or w["text"] in DASHES
                                       or w["text"].lower() in ("unit", "units"))]
    if not wording:
        return None
    end = max(w["x1"] for w in wording)
    left = [w for w in left if w["x0"] < end]
    return _clean(" ".join(w["text"] for line in _lines(left) for w in line)) or None


def _table_claims(reading: dict):
    for t, table in enumerate(reading["tables"]):
        rows = [[_clean(c) for c in row] for row in table["rows"]]
        cells = table.get("cells") or []  # readings before reading config 2 have no cell boxes
        header = rows[0]
        unit_cols = [c for c, h in enumerate(header) if h.lower() in ("unit", "units")]
        # Each column's x-range: its first cell box in any row (a merged cell leaves None).
        spans = [next((row[c] for row in cells if c < len(row) and row[c]), None) for c in range(len(header))]
        heads = _headers(reading, t, spans) if cells else {}
        for r, row in enumerate(rows):
            # The label is the first non-empty cell that is not a figure; a row without one has no label cell and
            # takes the words printed left of the table on its row.
            at = next((c for c, s in enumerate(row) if s and s not in DASHES and not _cell_figure(s)), None)
            label = row[at] if at is not None else _row_label(reading, t, cells[r]) if r < len(cells) else None
            suffix = label and re.search(r"\(([^()]+)\)$", label)
            for c in range(len(row)):
                fig = None if c == at or c in unit_cols else _cell_figure(row[c])
                if not fig:
                    continue
                head = heads.get(c, {})
                period = (header[c] if r and PERIOD.search(header[c]) else None) or head.get("period")
                unit = (row[unit_cols[0]] if unit_cols else None) or fig[1] or (suffix and suffix[1])
                box = cells[r][c] if r < len(cells) and c < len(cells[r]) else None
                inside = [w for w in reading["words"] if box and _centre_in(w, box)]
                exact = inside and " ".join(w["text"] for line in _lines(inside) for w in line) == row[c]
                yield _claim(f"t{t}r{r}c{c}", label, fig[0], unit or None, period, [_union(inside)] if exact else None,
                             head.get("boundary"))


def _text_claims(reading: dict):
    h = reading["height"]
    bboxes = [t["bbox"] for t in reading["tables"]]
    words = [w for w in reading["words"]
             if w["top"] >= 0.05 * h and w["bottom"] <= 0.95 * h and not any(_centre_in(w, b) for b in bboxes)]
    for n, line in enumerate(_lines(words)):
        for i, w in enumerate(line):
            fig = _figure(w["text"])
            if not fig:
                continue
            number, unit = fig
            used = 1
            if unit is None:
                for k in (2, 1):  # a unit of two words ("t CO2e") or one
                    nxt = line[i + 1:i + 1 + k]
                    if len(nxt) == k and (unit := _unit(" ".join(x["text"] for x in nxt).rstrip(".,;:"))):
                        used += k
                        break
            if unit is None:
                continue
            rest = " ".join(x["text"] for x in line[:i] + line[i + used:])
            # A figure never takes its comparison year.
            period = next((m for m in PERIOD.finditer(rest) if not COMPARED.search(rest[:m.start()])), None)
            yield _claim(f"l{n}w{i}", _clean(" ".join(x["text"] for x in line[:i])), number, unit,
                         period and period[0], [_union(line[i:i + used])])


def rules(reading: dict) -> list[dict]:
    return [*_table_claims(reading), *_text_claims(reading)]


class _Page:
    """A stage item: the newest reading of one page."""

    def __init__(self, doc: dict, row):
        self.doc, self.row = doc, row

    def __str__(self) -> str:
        return f"{self.doc['id']}:{self.row['page_number']}"


def _iou(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    inter = max(w, 0) * max(h, 0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else float(a == b)


def _same_claim(old, f) -> bool:
    """Identity rule (story 3.5 S2): the boxes overlap (IoU >= 0.5), or neither has a box and the wording is equal."""
    boxes = old["boxes"] and json.loads(old["boxes"])
    if boxes and f["boxes"]:
        return _iou(_union_box(boxes), _union_box(f["boxes"])) >= IOU
    return not boxes and not f["boxes"] and old["metric_text"] == f["metric_text"]


def _union_box(boxes) -> list:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


IOU = 0.5
VERSION_FIELDS = ("value_text", "value", "unit_text", "metric_text", "period_label", "boundary_label")
# The newest extracted version of every claim at a locator or one of its ~n successors on one page.
FAMILY_SQL = """
SELECT c.id, c.locator, v.id AS version_id, v.value_text, v.value, v.unit_text, v.metric_text, v.period_label,
       v.boundary_label, e.boxes
FROM claim c JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id AND method <> 'correction')
LEFT JOIN evidence_ref e ON e.claim_version_id = v.id
WHERE c.document_id = ? AND c.page_number = ? AND (c.locator = ? OR c.locator LIKE ? || '~%')
ORDER BY c.id
"""


def _claim_for(conn, doc_id, page, f, stamp):
    """(claim id, its newest extracted version or None) that the figure continues; a new claim when none does."""
    family = conn.execute(FAMILY_SQL, (doc_id, page, f["locator"], f["locator"])).fetchall()
    old = next((r for r in family if _same_claim(r, f)), None)
    if old is not None:
        return old["id"], old
    taken = {r["locator"] for r in conn.execute("SELECT locator FROM claim WHERE document_id = ? AND page_number = ?"
                                                " AND (locator = ? OR locator LIKE ? || '~%')",
                                                (doc_id, page, f["locator"], f["locator"]))}
    locator = f["locator"] if f["locator"] not in taken else next(
        loc for n in range(2, len(taken) + 3) if (loc := f"{f['locator']}~{n}") not in taken)
    claim_id = conn.execute("INSERT INTO claim (company_id, document_id, page_number, locator, created_at)"
                            " VALUES ((SELECT company_id FROM document WHERE id = ?), ?, ?, ?, ?)",
                            (doc_id, doc_id, page, locator, stamp)).lastrowid
    return claim_id, None


def _changed(old, f) -> bool:
    boxes = old["boxes"] and json.loads(old["boxes"])
    return any(old[k] != f.get(k) for k in VERSION_FIELDS) or (boxes or None) != (f["boxes"] or None)


def page_key(item: _Page) -> str:
    """The reading row, not the artifact sha: a page read back to an earlier reading (A, B, A) is extracted again."""
    return f"page {item.row['id']}"


def _work(root: Path, config: str, run_id: int, item: _Page, conn) -> Result:
    from gct.stages import link  # link imports this module

    path = conn.execute("SELECT path FROM artifact WHERE id = ?", (item.row["artifact_id"],)).fetchone()[0]
    reading = json.loads((root / path).read_text(encoding="utf-8"))
    found = rules(reading)
    doc_id, page, stamp = item.doc["id"], item.row["page_number"], store.now()
    with store.transaction(conn):
        for f in found:
            claim_id, old = _claim_for(conn, doc_id, page, f, stamp)
            # A new version only when the figure differs from the claim's newest extracted one, so a re-run after a
            # crash, or a re-read that finds the same figure, adds none and a correction stays current.
            if old is not None and not _changed(old, f):
                version_id = old["version_id"]
            else:
                version_id = conn.execute(
                    "INSERT INTO claim_version (claim_id, run_id, method, config_version, metric_text, value_text, value,"
                    " unit_text, period_label, boundary_label, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (claim_id, run_id, METHOD, config, f["metric_text"], f["value_text"], f["value"], f["unit_text"],
                     f["period_label"], f.get("boundary_label"), stamp),
                ).lastrowid
                ref_id = conn.execute(
                    "INSERT INTO evidence_ref (claim_version_id, document_id, page_number, boxes, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (version_id, doc_id, page, None if f["boxes"] is None else json.dumps(f["boxes"]), stamp),
                ).lastrowid
                status = link.match({"sheet": None, **f}, reading)
                link.record(conn, ref_id, run_id, status, item.row["artifact_id"], stamp)
            conn.execute("INSERT OR IGNORE INTO claim_seen (claim_version_id, page_id, config_version, run_id, created_at)"
                         " VALUES (?, ?, ?, ?, ?)", (version_id, item.row["id"], config, run_id, stamp))
    no_box = sum(f["boxes"] is None for f in found)
    return Result(output={"figures": len(found), "no_box": no_box}, method=METHOD, rung=1)


def _doc(d: dict, action: str, cause=None, next_action=None, **counts) -> dict:
    out = {"id": d["id"], "logical_name": d["logical_name"], "pages": 0, "extracted": 0, "cached": 0, "failed": 0,
           "figures": 0, "no_box": 0, "action": action, "cause": cause, "next_action": next_action}
    return {**out, **counts}


def _extract(conn, root, run_id, docs, wanted=None) -> list[dict]:
    """Extract each document in the run. wanted maps a document id to the page numbers to retry (absent: every page)."""
    root, config = Path(root), extract_config()
    stage = Stage("extract", config, lambda item, conn: _work(root, config, run_id, item, conn), page_key)
    out = []
    for d in docs:
        only = (wanted or {}).get(d["id"])
        items = [_Page(d, r) for r in conn.execute(NEWEST_SQL, (None, None, d["id"]))
                 if only is None or r["page_number"] in only]
        if not items:
            runs.event(conn, run_id, "note", stage="extract", item=str(d["id"]), message=READ_FIRST)
            out.append(_doc(d, "skipped", "No page of this document has been read yet.", READ_FIRST))
            continue
        counts = run_stage(conn, run_id, stage, items)
        done = [o for i in items if (o := result(conn, "extract", i, page_key(i), config))]
        failed = counts["failed"]
        out.append(_doc(
            d, "extracted", f"{failed} of {len(items)} pages could not be extracted." if failed else None,
            RETRY if failed else None, pages=len(items), extracted=counts["processed"], cached=counts["cached"],
            failed=failed, figures=sum(o["figures"] for o in done),
            no_box=sum(o.get("no_box", o.get("unresolved", 0)) for o in done),  # attempts before 3.3 say "unresolved"
        ))
    return out


def extract(conn, root, ids=(), company=None, notes=()) -> tuple[int | None, list[dict]]:
    """Extract the selection in one run. A page without a reading is skipped with a note, never failed.
    Returns the run id (None when there was nothing to extract) and one record per document.
    CSV and XLSX documents go to their own stage, sheet (story 4.3): a selection holding both makes two runs."""
    from gct.stages import sheet  # sheet imports this module

    docs = select(conn, ids, company)
    pdfs = [d for d in docs if d["file_type"] not in sheet.TYPES]
    run_id, out = None, []
    if pdfs:
        with runs.run(conn, "extract") as run_id:
            runs.record(conn, run_id, {"ids": list(ids), "company": company}, notes)
            out = [_doc(d, "skipped", NOT_ACTIVE) for d in pdfs if d["state"] not in ACTIVE]
            out += _extract(conn, root, run_id, [d for d in pdfs if d["state"] in ACTIVE])
    if len(pdfs) < len(docs):  # sheet.sheet skips a named archived spreadsheet the same way
        sheet_run, sheets = sheet.sheet(conn, root, ids, company, notes)
        run_id, out = run_id or sheet_run, out + sheets
    return run_id, out


def failed(conn, run_id: int) -> dict:
    """{document id: page numbers} whose extraction failed in the run and has not succeeded since."""
    out = {}
    for (item,) in conn.execute(FAILED_PAGES_SQL, (run_id,)):
        doc_id, number = map(int, item.split(":"))
        out.setdefault(doc_id, set()).add(number)
    return dict(sorted(out.items()))


def retry(conn, root, wanted: dict, notes=()) -> tuple[int, list[dict]]:
    """Extract again exactly the failed pages (see failed) in a new run. A document no longer active is skipped."""
    docs = [registry.show_document(conn, i) for i in wanted]
    active = [d for d in docs if d["state"] in ACTIVE]
    with runs.run(conn, "extract") as run_id:
        runs.record(conn, run_id, {"ids": [d["id"] for d in active], "company": None}, notes)
        out = [_doc(d, "skipped", NOT_ACTIVE) for d in docs if d["state"] not in ACTIVE]
        out += _extract(conn, root, run_id, active, wanted)
    return run_id, out


def claims(conn, doc_id: int) -> list[dict]:
    """The newest version of every claim of one document, with its evidence boxes (None: no box) and the newest
    source match status (None: not checked yet)."""
    registry.show_document(conn, doc_id)
    return [{**dict(r), "boxes": None if r["boxes"] is None else json.loads(r["boxes"])}
            for r in conn.execute(CLAIMS_SQL, (doc_id,))]
