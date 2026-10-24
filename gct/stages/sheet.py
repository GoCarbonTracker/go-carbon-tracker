"""Internal-evidence spreadsheets (story 4.3): CSV and XLSX read with the standard library, a contributor's column
mapping per sheet, and the `sheet` stage that makes one claim per data row. The upload confirms nothing: no function
here writes a review, an acceptance, a confirmation or a basis (FR4, S3)."""
import csv
import io
import re
import zipfile
from datetime import date
from functools import lru_cache
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from gct.stages import Result, Stage, result, run_stage, version_of
from gct.stages.extract import FAILED_PAGES_SQL, VERSION_FIELDS, _clean, _doc, _value
from gct.stages.missing import _text, contributor
from gct.stages.read import ACTIVE, NOT_ACTIVE, select
from gct.workspace import registry, runs, store
from gct.workspace.layout import NOT_FOUND, REFUSED, USAGE, GctError

TYPES = ("csv", "xlsx")
METHOD = "sheet-rules"
SHEET_RULES_VERSION = 1
CONFIG = version_of("sheet", 1, SHEET_RULES_VERSION)
ROLES = ("metric", "value", "unit", "period", "boundary", "company", "note")
NO_MAPPING = "no confirmed mapping"
OTHER_COMPANY = "row for another company"
NO_COMPANY = "row without a company"
SHOWN = 5  # data rows printed by gct sheet show
RETRY = "Run gct extract again. Sheets whose file and mapping have not changed are not extracted twice."
FAILED_SQL = FAILED_PAGES_SQL.replace("a.stage = 'extract'", "a.stage = 'sheet'")
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
MAPPING_SQL = """
SELECT m.*, c.name, c.organisation FROM sheet_mapping m JOIN contributor_version c ON c.id = m.contributor_version_id
WHERE m.id IN (SELECT MAX(id) FROM sheet_mapping WHERE document_id = ? GROUP BY sheet) ORDER BY m.position
"""
# The newest extracted version of the claim at one row, with its cell and note: a correction stays current.
ROW_SQL = """
SELECT c.id, v.id AS version_id, v.value_text, v.value, v.unit_text, v.metric_text, v.period_label, v.boundary_label,
       e.cell, (SELECT text FROM claim_note WHERE claim_version_id = v.id ORDER BY id DESC LIMIT 1) AS note
FROM claim c JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id AND method <> 'correction')
LEFT JOIN evidence_ref e ON e.claim_version_id = v.id
WHERE c.document_id = ? AND c.page_number = ? AND c.locator = ?
"""


# Readers: cell text as stored. Number formats, dates and formulas are not interpreted (a formula is its stored value).

def column(i: int) -> str:
    """The column letters of a 0-based index: 0 -> A, 26 -> AA."""
    out, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _grid(cells: dict) -> list[list[str]]:
    """{(row number, column index): text} as rows from row 1, every row as wide as the widest, empty cells ''."""
    if not cells:
        return []
    width = max(c for _, c in cells) + 1
    rows = [[""] * width for _ in range(max(r for r, _ in cells))]
    for (r, c), text in cells.items():
        rows[r - 1][c] = text
    return rows


def _string(el) -> str:
    """A shared or inline string: its own t, or the t of each rich-text run (phonetic runs left out)."""
    parts = [el.find(f"{M}t"), *(r.find(f"{M}t") for r in el.findall(f"{M}r"))]
    return "".join(t.text or "" for t in parts if t is not None)


def _xlsx(path) -> list[tuple[str, list[list[str]]]]:
    with zipfile.ZipFile(path) as z:
        def xml(part):
            return ElementTree.fromstring(z.read(part))

        def part(target: str) -> str:
            return target.lstrip("/") if target.startswith("/") else f"xl/{target}"

        rels = {r.get("Id"): r for r in xml("xl/_rels/workbook.xml.rels").iter(REL)}
        shared = next((part(r.get("Target")) for r in rels.values() if r.get("Type", "").endswith("/sharedStrings")), None)
        strings = [_string(si) for si in xml(shared).iter(f"{M}si")] if shared else []
        book = []
        for s in xml("xl/workbook.xml").iter(f"{M}sheet"):
            cells = {}
            # ponytail: every cell needs its r attribute (optional in the format, written by Excel and LibreOffice);
            # a writer that leaves it out fails the sheet. Upgrade: count positions along each row.
            for c in xml(part(rels[s.get(R_ID)].get("Target"))).iter(f"{M}c"):
                letters, row = re.fullmatch(r"([A-Z]+)(\d+)", c.get("r")).groups()
                kind, v = c.get("t"), c.find(f"{M}v")
                if kind == "inlineStr":
                    text = _string(c.find(f"{M}is"))
                else:  # n (default), str, b, e: the stored text; s: the shared string it points to
                    text = "" if v is None else strings[int(v.text)] if kind == "s" else v.text or ""
                if text:  # an empty cell (a styled one far out at XFD1048576) sizes nothing
                    cells[int(row), _index(letters)] = text
            book.append((s.get("name"), _grid(cells)))
        return book


def _csv(path) -> list[list[str]]:
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(text[:65536], delimiters=registry.DELIMITERS)
    except csv.Error:  # one column, or a sample the sniffer cannot decide: comma
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    width = max(map(len, rows), default=0)
    return [r + [""] * (width - len(r)) for r in rows]


@lru_cache(maxsize=4)
def read_book(path: str, file_type: str, name: str) -> tuple:
    """((sheet name, rows), ...) in workbook order; rows[0] is row 1. A CSV is one sheet named after its file.
    The stored file never changes (its name is its sha256), so a few books stay cached."""
    if file_type == "csv":
        return ((PurePosixPath(name).stem, _csv(path)),)
    return tuple(_xlsx(path))


def _book(root, doc: dict) -> tuple:
    try:
        return read_book(str(registry.stored_path(Path(root), doc["sha256"])), doc["file_type"], doc["logical_name"])
    except (KeyError, IndexError, AttributeError, TypeError, ValueError, ElementTree.ParseError, zipfile.BadZipFile,
            csv.Error):
        raise GctError(REFUSED, f"Document {doc['id']} could not be read as a spreadsheet.",
                       "Save the file again as CSV or XLSX and add it with: gct doc add FILE --kind evidence") from None


# Mappings (S1): a contributor's record per sheet; the newest row per sheet is current.

def _spreadsheet(conn, doc_id: int) -> dict:
    d = registry.show_document(conn, doc_id)
    if d["file_type"] not in TYPES:
        raise GctError(REFUSED, f"Document {doc_id} is a {d['file_type']} file. Only CSV and XLSX documents have sheets.",
                       "See the documents with: gct doc list")
    return d


def mappings(conn, doc_id: int) -> dict:
    """{sheet name: current mapping row} of one document."""
    return {m["sheet"]: m for m in conn.execute(MAPPING_SQL, (doc_id,))}


def mapping_ids(conn, doc_id: int) -> list[int]:
    return [m["id"] for m in mappings(conn, doc_id).values()]


def _record(m) -> dict:
    return {"id": m["id"], "document": m["document_id"], "sheet": m["sheet"], "position": m["position"],
            **{r: m[f"{r}_col"] for r in ROLES}, "year_end": m["year_end"], "boundary_is": m["boundary_is"],
            "boundary_detail": m["boundary_detail"], "contributor": m["name"], "organisation": m["organisation"],
            "capacity": m["capacity"], "rationale": m["rationale"], "created_at": m["created_at"]}


def show(conn, root, doc_id: int) -> list[dict]:
    """Each sheet with its header row, its first data rows as stored and its current mapping."""
    d = _spreadsheet(conn, doc_id)
    current = mappings(conn, doc_id)
    return [{"name": name, "position": i, "header": rows[0] if rows else [],
             "rows": [{"row": n, "cells": cells} for n, cells in enumerate(rows[1:SHOWN + 1], 2)],
             "mapping": _record(current[name]) if name in current else None}
            for i, (name, rows) in enumerate(_book(root, d), 1)]


def _year_end(value: str) -> str:
    m = re.fullmatch(r"(\d\d)-(\d\d)", value.strip())
    try:
        date(2000, int(m[1]), int(m[2]))  # a leap year, so 02-29 is a year end
    except (TypeError, ValueError):
        raise GctError(USAGE, f"{value} is not a year end like 03-31.",
                       "Give --year-end as MM-DD, the month and day the fiscal year ends.") from None
    return m[0]


def map_sheet(conn, root, doc_id: int, sheet: str, cols: dict, year_end=None, boundary_is=None, boundary_detail=None,
              key=None, capacity=None, rationale=None) -> dict:
    """Store one mapping row: which header of row 1 holds each role. It confirms the column meaning, never a value."""
    d = _spreadsheet(conn, doc_id)
    registry.require_active(conn, doc_id)  # no mapping on an archived document (story 4.4)
    book = _book(root, d)
    names = [n for n, _ in book]
    if sheet not in names:
        raise GctError(NOT_FOUND, f"Document {doc_id} has no sheet named {sheet}.", f"See its sheets with: gct sheet show {doc_id}")
    position = names.index(sheet) + 1
    rows = book[position - 1][1]
    header = [_clean(h) for h in rows[0]] if rows else []
    if cols.get("value") is None:
        raise GctError(USAGE, "The value column is missing.", f"Give it, for example: gct sheet map {doc_id} --sheet {sheet} --value Value")
    cols = {r: _clean(c) for r, c in cols.items() if c is not None}
    for role, col in cols.items():
        n = header.count(col)
        if n == 0:
            raise GctError(REFUSED, f"{col} is not a header in row 1 of sheet {sheet}.",
                           f"Give a header exactly as printed in row 1: gct sheet show {doc_id}")
        if n > 1:
            raise GctError(REFUSED, f"{col} is printed {n} times in row 1 of sheet {sheet}, so its column is ambiguous.",
                           "Map a column whose header is printed once, or add the file again with distinct headers.")
    year_end = year_end and _year_end(year_end)
    detail = _clean(boundary_detail) or None
    if detail and not boundary_is:
        raise GctError(USAGE, "A boundary detail needs a declared boundary.",
                       'Give both, for example: --boundary-is subsidiary_set --boundary-detail "the company and two plants"')
    who = contributor(conn, key)
    capacity = _text(capacity, "capacity", '--capacity "sustainability analyst"')
    rationale = _text(rationale, "rationale", '--rationale "the column headers of the metering export"')
    with store.transaction(conn):
        conn.execute(f"INSERT INTO sheet_mapping (document_id, sheet, position, {', '.join(f'{r}_col' for r in ROLES)},"
                     " year_end, boundary_is, boundary_detail, contributor_version_id, capacity, rationale, created_at)"
                     f" VALUES ({', '.join('?' * (len(ROLES) + 10))})",
                     (doc_id, sheet, position, *(cols.get(r) for r in ROLES), year_end, boundary_is, detail,
                      who["version"], capacity, rationale, store.now()))
    return _record(mappings(conn, doc_id)[sheet])


# Extraction (S2): the stage `sheet`, one item per mapped sheet.

def figures(rows: list, mapping, company: str) -> tuple[list[dict], int, int]:
    """(one figure per data row whose value cell is not empty, rows skipped because their company cell names another
    company than the document's, rows skipped because their company cell is empty)."""
    header = [_clean(h) for h in rows[0]]
    cols = {r: header.index(mapping[f"{r}_col"]) for r in ROLES if mapping[f"{r}_col"] is not None}
    out, other, blank = [], 0, 0
    for n, row in enumerate(rows[1:], 2):
        cell = {r: row[c].strip() or None for r, c in cols.items()}
        if cell["value"] is None:
            continue
        if "company" in cols and cell["company"] is None:
            blank += 1
            continue
        if "company" in cols and _clean(cell["company"]).casefold() != _clean(company).casefold():
            other += 1
            continue
        out.append({"locator": f"s{mapping['position']}r{n}", "cell": f"{column(cols['value'])}{n}",
                    "metric_text": cell.get("metric"), "value_text": cell["value"], "value": _value(cell["value"]),
                    "unit_text": cell.get("unit"), "period_label": cell.get("period"),
                    "boundary_label": cell.get("boundary"), "note": cell.get("note")})
    return out, other, blank


def _status(rows: list, mapping, n: int, value_text: str) -> tuple[str, str | None]:
    """(status, reason) of row n's value cell under a mapping against a claim's value as stored (S5)."""
    c = [_clean(h) for h in rows[0]].index(mapping["value_col"])
    text = rows[n - 1][c].strip() if n <= len(rows) else ""
    if text == value_text:
        return "matched", None
    return "cited", f"cell {column(c)}{n} under mapping #{mapping['id']} reads {text or 'nothing'}, not the claim's value"


class _Sheet:
    """A stage item: one sheet with its current mapping."""

    def __init__(self, doc: dict, mapping):
        self.doc, self.mapping = doc, mapping

    def __str__(self) -> str:
        return f"{self.doc['id']}:{self.mapping['position']}"


def _input(item: _Sheet) -> str:
    return version_of(item.doc["sha256"], item.mapping["id"])


def _work(root: Path, run_id: int, item: _Sheet, conn) -> Result:
    from gct.stages import link  # link imports this module

    name, rows = _book(root, item.doc)[item.mapping["position"] - 1]
    found, other, blank = figures(rows, item.mapping, item.doc["company"])
    doc_id, position, stamp, ids = item.doc["id"], item.mapping["position"], store.now(), []
    with store.transaction(conn):
        for f in found:
            old = conn.execute(ROW_SQL, (doc_id, position, f["locator"])).fetchone()
            claim_id = old["id"] if old else conn.execute(
                "INSERT INTO claim (company_id, document_id, page_number, locator, created_at)"
                " VALUES ((SELECT company_id FROM document WHERE id = ?), ?, ?, ?, ?)",
                (doc_id, doc_id, position, f["locator"], stamp)).lastrowid
            ids.append(claim_id)
            # A new version only where a field, the value cell or the note changed (claim versions as 3.5).
            if old and all(old[k] == f[k] for k in (*VERSION_FIELDS, "cell", "note")):
                continue
            version_id = conn.execute(
                "INSERT INTO claim_version (claim_id, run_id, method, config_version, metric_text, value_text, value,"
                " unit_text, period_label, boundary_label, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (claim_id, run_id, METHOD, CONFIG, f["metric_text"], f["value_text"], f["value"], f["unit_text"],
                 f["period_label"], f["boundary_label"], stamp)).lastrowid
            ref_id = conn.execute("INSERT INTO evidence_ref (claim_version_id, document_id, sheet, cell, created_at)"
                                  " VALUES (?, ?, ?, ?, ?)", (version_id, doc_id, name, f["cell"], stamp)).lastrowid
            if f["note"]:
                conn.execute("INSERT INTO claim_note (claim_version_id, text, created_at) VALUES (?, ?, ?)",
                             (version_id, f["note"], stamp))
            n = int(f["locator"].rsplit("r", 1)[1])
            link.record(conn, ref_id, run_id, _status(rows, item.mapping, n, f["value_text"]), None, stamp)
    return Result(output={"sheet": name, "figures": len(found), "other_company": other, "no_company": blank,
                          "claims": ids}, method=METHOD)


def _extract(conn, root, run_id, docs, wanted=None) -> list[dict]:
    """Extract each spreadsheet in the run. wanted maps a document id to the sheet positions to retry (absent: all)."""
    root = Path(root)
    stage = Stage("sheet", CONFIG, lambda item, conn: _work(root, run_id, item, conn), _input)
    out = []
    for d in docs:
        only = (wanted or {}).get(d["id"])
        try:
            names = [n for n, _ in _book(root, d)]
        except GctError as e:
            out.append(_doc(d, "skipped", e.cause, e.next_action))
            continue
        current = mappings(conn, d["id"])
        items = [_Sheet(d, current[n]) for n in names if n in current and (only is None or current[n]["position"] in only)]
        notes = [] if only else [f"sheet {n}: {NO_MAPPING}" for n in names if n not in current]
        for message in notes:
            runs.event(conn, run_id, "note", stage="sheet", item=str(d["id"]), message=message)
        if not items:
            out.append(_doc(d, "skipped", "; ".join(notes) or NO_MAPPING, f"map its columns first: gct sheet show {d['id']}"))
            continue
        counts = run_stage(conn, run_id, stage, items)
        done = [o for i in items if (o := result(conn, "sheet", i, _input(i), CONFIG))]
        for o in done:
            notes += [f"sheet {o['sheet']}: {n} skipped ({why})" for n, why in
                      ((o["other_company"], OTHER_COMPANY), (o.get("no_company", 0), NO_COMPANY)) if n]
        failed = counts["failed"]
        if failed:
            notes.insert(0, f"{failed} of {len(items)} sheets could not be extracted")
        out.append(_doc(d, "extracted", "; ".join(notes) or None, RETRY if failed else None, pages=len(items),
                        extracted=counts["processed"], cached=counts["cached"], failed=failed,
                        figures=sum(o["figures"] for o in done)))
    return out


def sheet(conn, root, ids=(), company=None, notes=()) -> tuple[int | None, list[dict]]:
    """Extract the CSV and XLSX documents of the selection in one `sheet` run (gct extract sends them here).
    Returns the run id (None when the selection holds none) and one record per document."""
    docs = [d for d in select(conn, ids, company) if d["file_type"] in TYPES]
    if not docs:
        return None, []
    with runs.run(conn, "sheet") as run_id:
        runs.record(conn, run_id, {"ids": list(ids), "company": company}, notes)
        out = [_doc(d, "skipped", NOT_ACTIVE) for d in docs if d["state"] not in ACTIVE]
        out += _extract(conn, root, run_id, [d for d in docs if d["state"] in ACTIVE])
    return run_id, out


def failed(conn, run_id: int) -> dict:
    """{document id: sheet positions} whose extraction failed in the run and has not succeeded since."""
    out = {}
    for (item,) in conn.execute(FAILED_SQL, (run_id,)):
        doc_id, position = map(int, item.split(":"))
        out.setdefault(doc_id, set()).add(position)
    return dict(sorted(out.items()))


def retry(conn, root, wanted: dict, notes=()) -> tuple[int, list[dict]]:
    """Extract again exactly the failed sheets in a new run. A document no longer active is skipped."""
    docs = [registry.show_document(conn, i) for i in wanted]
    active = [d for d in docs if d["state"] in ACTIVE]
    with runs.run(conn, "sheet") as run_id:
        runs.record(conn, run_id, {"ids": [d["id"] for d in active], "company": None}, notes)
        out = [_doc(d, "skipped", NOT_ACTIVE) for d in docs if d["state"] not in ACTIVE]
        out += _extract(conn, root, run_id, active, wanted)
    return run_id, out


# What other stages ask of a spreadsheet document.

def states(conn, doc_id: int) -> dict | None:
    """{claim id: state} of a CSV or XLSX document (None for any other): current when the newest extraction of its
    sheet under the current mapping and config found it (Q1). A PDF's states come from its readings (correct.states)."""
    from gct.stages import correct  # correct sends spreadsheet documents here

    d = conn.execute("SELECT file_type, sha256 FROM document WHERE id = ?", (doc_id,)).fetchone()
    if d is None or d["file_type"] not in TYPES:
        return None
    seen = {}
    for m in mappings(conn, doc_id).values():
        o = result(conn, "sheet", f"{doc_id}:{m['position']}", version_of(d["sha256"], m["id"]), CONFIG)
        seen[m["position"]] = o and set(o["claims"])
    return {cid: correct.NOT_EXTRACTED if seen.get(position) is None else correct.CURRENT if cid in seen[position]
            else correct.NOT_FOUND_STATE
            for cid, position in conn.execute("SELECT id, page_number FROM claim WHERE document_id = ?", (doc_id,))}


def declarations(conn, doc_id: int) -> list[tuple[int, dict]]:
    """(sheet position, statement) for each current mapping's --year-end and --boundary-is (S4). The wording names
    the mapping, so it is never mistaken for printed text; a boundary carries its mapping for the scope."""
    out = []
    for m in mappings(conn, doc_id).values():
        wording = f"declared in sheet mapping #{m['id']} by {m['name']}"
        if m["year_end"]:
            out.append((m["position"], {"kind": "fiscal_year_end", "wording": wording, "fy_end": m["year_end"]}))
        if m["boundary_is"]:
            out.append((m["position"], {"kind": "reporting_boundary", "wording": wording, "boundary": m["boundary_is"],
                                         "boundary_detail": m["boundary_detail"], "mapping": m}))
    return out


def link_input(conn, doc: dict, name: str) -> str:
    """The link item version of a sheet reference: the file and the sheet's current mapping (Q5)."""
    m = mappings(conn, doc["id"]).get(name)
    return f"sheet {version_of(doc['sha256'], m and m['id'])}"


def check(conn, root, doc: dict, ref: dict) -> tuple[str, str | None]:
    """(status, reason) of one sheet reference: the value cell of its row under the sheet's current mapping (S5)."""
    m = mappings(conn, doc["id"]).get(ref["sheet"])
    if m is None:
        return "unresolved", NO_MAPPING
    rows = _book(root, doc)[m["position"] - 1][1]
    return _status(rows, m, int(re.sub(r"\D", "", ref["cell"])), ref["value_text"])


def cells(conn, claim_id: int) -> dict:
    """{evidence ref id: {"sheet", "cell"}} of every version of one claim (both None for a page)."""
    return {r[0]: {"sheet": r[1], "cell": r[2]} for r in conn.execute(
        "SELECT e.id, e.sheet, e.cell FROM evidence_ref e JOIN claim_version v ON v.id = e.claim_version_id"
        " WHERE v.claim_id = ?", (claim_id,))}


def refs(conn, claim_ids) -> dict:
    """{claim id: {"sheet", "cell"}} of the newest version's evidence of each claim (both None for a page)."""
    ids = ",".join(str(int(i)) for i in claim_ids)
    return {r[0]: {"sheet": r[1], "cell": r[2]} for r in conn.execute(
        "SELECT c.id, e.sheet, e.cell FROM claim c JOIN evidence_ref e ON e.claim_version_id ="
        f" (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id) WHERE c.id IN ({ids}) ORDER BY e.id")}
