"""Rung 1 extraction: fixed reading rules over each page reading. A labelled no-model baseline; its accuracy is not measured."""
import json
import re
from pathlib import Path

from gct.stages import Result, Stage, result, run_stage, version_of
from gct.stages.read import ACTIVE, NEWEST_SQL, NOT_ACTIVE, select
from gct.workspace import registry, runs, store

METHOD = "rung1-rules"
RULES_VERSION = 2
READ_FIRST = "read it first: gct read"
RETRY = "Run gct extract again. Pages already extracted are not extracted twice."

# Detects units; never converts them. A space or a slash inside the unit as printed is allowed ("t CO2e").
UNITS = {"tCO2e", "tCO2", "tonnes", "t", "kt", "Mt", "MWh", "GWh", "kWh", "GJ", "TJ", "kL", "ML", "m3", "%"}
NUMBER = re.compile(r"(\(?-?\d(?:[\d,.]*\d)?\)?)(\S*)")
WESTERN = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")
YEAR = re.compile(r"199\d|20\d\d|2100")
PERIOD = re.compile(r"(?<!\w)(?<!\d[,.])(?:FY\s?\d{2,4}(?:-\d{2,4})?|\d{4}-\d{2,4}|199\d|20\d\d|2100)(?!\w|[,.]\d)")
FAILED_PAGES_SQL = """
SELECT a.item FROM attempt a
WHERE a.run_id = ? AND a.stage = 'extract' AND a.outcome = 'failed'
  AND a.id = (SELECT MAX(b.id) FROM attempt b WHERE b.run_id = a.run_id AND b.stage = a.stage AND b.item = a.item)
  AND NOT EXISTS (SELECT 1 FROM attempt c WHERE c.stage = a.stage AND c.item = a.item AND c.outcome = 'ok' AND c.id > a.id)
ORDER BY a.id
"""
CLAIMS_SQL = """
SELECT c.page_number, c.locator, v.value_text, v.value, v.unit_text, v.metric_text, v.period_label,
       v.reporting_boundary, v.method, e.boxes
FROM claim c JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)
LEFT JOIN evidence_ref e ON e.claim_version_id = v.id
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


def _centre_in(w: dict, box) -> bool:
    x0, top, x1, bottom = box
    return x0 <= (w["x0"] + w["x1"]) / 2 <= x1 and top <= (w["top"] + w["bottom"]) / 2 <= bottom


def _union(ws) -> list:
    return [min(w["x0"] for w in ws), min(w["top"] for w in ws), max(w["x1"] for w in ws), max(w["bottom"] for w in ws)]


def _lines(words) -> list[list[dict]]:
    """Words grouped by top within 2 points, each line left to right."""
    lines = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and w["top"] - lines[-1][0]["top"] <= 2:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _claim(locator, metric, number, unit, period, boxes) -> dict:
    return {"locator": locator, "metric_text": metric, "value_text": number, "value": _value(number),
            "unit_text": unit, "period_label": period, "boxes": boxes}


def _table_claims(reading: dict):
    for t, table in enumerate(reading["tables"]):
        rows = [[_clean(c) for c in row] for row in table["rows"]]
        cells = table.get("cells") or []  # readings before reading config 2 have no cell boxes
        header = rows[0]
        unit_cols = [c for c, h in enumerate(header) if h.lower() in ("unit", "units")]
        for r, row in enumerate(rows):
            # The label is the first non-empty cell that is not a figure; a row without one has no label.
            at = next((c for c, s in enumerate(row) if s and not _cell_figure(s)), None)
            label = None if at is None else row[at]
            suffix = label and re.search(r"\(([^()]+)\)$", label)
            for c in range(len(row)):
                fig = None if c == at or c in unit_cols else _cell_figure(row[c])
                if not fig:
                    continue
                period = header[c] if r and PERIOD.search(header[c]) else None
                unit = (row[unit_cols[0]] if unit_cols else None) or fig[1] or (suffix and suffix[1])
                box = cells[r][c] if r < len(cells) and c < len(cells[r]) else None
                inside = [w for w in reading["words"] if box and _centre_in(w, box)]
                exact = inside and " ".join(w["text"] for line in _lines(inside) for w in line) == row[c]
                yield _claim(f"t{t}r{r}c{c}", label, fig[0], unit or None, period, [_union(inside)] if exact else None)


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
            period = PERIOD.search(rest)
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


def _work(root: Path, config: str, run_id: int, item: _Page, conn) -> Result:
    path = conn.execute("SELECT path FROM artifact WHERE id = ?", (item.row["artifact_id"],)).fetchone()[0]
    found = rules(json.loads((root / path).read_text(encoding="utf-8")))
    doc_id, page, stamp = item.doc["id"], item.row["page_number"], store.now()
    # ponytail: a crash between this commit and run_stage's attempt row adds a duplicate claim_version on the
    # next run; a guard needs the reading's identity on claim_version, which the schema does not carry yet.
    with store.transaction(conn):
        for f in found:
            conn.execute(
                "INSERT OR IGNORE INTO claim (company_id, document_id, page_number, locator, created_at)"
                " VALUES ((SELECT company_id FROM document WHERE id = ?), ?, ?, ?, ?)",
                (doc_id, doc_id, page, f["locator"], stamp),
            )
            claim_id = conn.execute("SELECT id FROM claim WHERE document_id = ? AND page_number = ? AND locator = ?",
                                    (doc_id, page, f["locator"])).fetchone()[0]
            version_id = conn.execute(
                "INSERT INTO claim_version (claim_id, run_id, method, config_version, metric_text, value_text, value,"
                " unit_text, period_label, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (claim_id, run_id, METHOD, config, f["metric_text"], f["value_text"], f["value"], f["unit_text"],
                 f["period_label"], stamp),
            ).lastrowid
            conn.execute(
                "INSERT INTO evidence_ref (claim_version_id, document_id, page_number, boxes, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (version_id, doc_id, page, None if f["boxes"] is None else json.dumps(f["boxes"]), stamp),
            )
    unresolved = sum(f["boxes"] is None for f in found)
    return Result(output={"figures": len(found), "unresolved": unresolved}, method=METHOD, rung=1)


def _doc(d: dict, action: str, cause=None, next_action=None, **counts) -> dict:
    out = {"id": d["id"], "logical_name": d["logical_name"], "pages": 0, "extracted": 0, "cached": 0, "failed": 0,
           "figures": 0, "unresolved": 0, "action": action, "cause": cause, "next_action": next_action}
    return {**out, **counts}


def _extract(conn, root, run_id, docs, wanted=None) -> list[dict]:
    """Extract each document in the run. wanted maps a document id to the page numbers to retry (absent: every page)."""
    root, config = Path(root), extract_config()
    stage = Stage("extract", config, lambda item, conn: _work(root, config, run_id, item, conn),
                  lambda item: item.row["sha256"])
    out = []
    for d in docs:
        if d["file_type"] != "pdf":
            out.append(_doc(d, "skipped", "not a PDF"))
            continue
        only = (wanted or {}).get(d["id"])
        items = [_Page(d, r) for r in conn.execute(NEWEST_SQL, (None, None, d["id"]))
                 if only is None or r["page_number"] in only]
        if not items:
            runs.event(conn, run_id, "note", stage="extract", item=str(d["id"]), message=READ_FIRST)
            out.append(_doc(d, "skipped", "No page of this document has been read yet.", READ_FIRST))
            continue
        counts = run_stage(conn, run_id, stage, items)
        done = [o for i in items if (o := result(conn, "extract", i, i.row["sha256"], config))]
        failed = counts["failed"]
        out.append(_doc(
            d, "extracted", f"{failed} of {len(items)} pages could not be extracted." if failed else None,
            RETRY if failed else None, pages=len(items), extracted=counts["processed"], cached=counts["cached"],
            failed=failed, figures=sum(o["figures"] for o in done), unresolved=sum(o["unresolved"] for o in done),
        ))
    return out


def extract(conn, root, ids=(), company=None, notes=()) -> tuple[int | None, list[dict]]:
    """Extract the selection in one run. A page without a reading is skipped with a note, never failed.
    Returns the run id (None when there was nothing to extract) and one record per document."""
    docs = select(conn, ids, company)
    if not docs:
        return None, []
    with runs.run(conn, "extract") as run_id:
        runs.record(conn, run_id, {"ids": list(ids), "company": company}, notes)
        out = _extract(conn, root, run_id, docs)
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
    """The newest version of every claim of one document, with its evidence boxes (None: location unresolved)."""
    registry.show_document(conn, doc_id)
    return [{**dict(r), "boxes": None if r["boxes"] is None else json.loads(r["boxes"])}
            for r in conn.execute(CLAIMS_SQL, (doc_id,))]
