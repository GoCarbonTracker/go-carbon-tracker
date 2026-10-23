"""XLSX and CSV reports (story 7.3): each report as one workbook <stem>.xlsx and one folder <stem>/ of CSV files, from
the dataset alone. Every table, title, heading and fixed line comes from the dataset's columns and words; a cell is
printed(...) of its dataset field. XLSX refuses before anything is written when a cell or a sheet exceeds what the
format holds; CSV has neither limit."""
import csv
import json
import re

MAX_ROWS = 1_048_576  # rows of an XLSX sheet, band and heading included
MAX_CELL = 32_767  # UTF-16 units of an XLSX cell
NEXT_STEP = "Export CSV or JSON for this selection, or narrow the filter."
CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
NUMBER = re.compile(r"[+-]?\d[\d,]*(\.\d+)?")
# The sub-tables C3 nests in each list's rows: named here, since an empty list shows no nesting and its sub-table
# sheets are still written. unpaired_restatements (top level) belongs to the restatement log; pair lists get the pair
# sides; every report gets documents.
SUBS = {"evidence_index": ("records", "disagreements"), "restatement_log": ("restatements", "adjudications"),
        "candidates": ("restatements", "adjudications"), "expectations": ("reasons", "accepted", "declared")}
PAIRS = ("restatement_log", "candidates")
ATTRIBUTED = ("contributor", "correction.contributor", "confirmation.contributor")


class Refusal(Exception):
    """The format cannot hold the data. export.write turns it into the command's refusal; cause names tables, ids and
    headings only (it reaches the run log)."""

    def __init__(self, cause: str, next_step: str):
        super().__init__(cause)
        self.cause, self.next_step = cause, next_step


def dotted(row, key):
    """A row value by its columns key: a dotted key walks the object (None under a null object); outside_selection's
    a and b are its two items."""
    value = row
    for part in key.split("."):
        if value is None:
            return None
        value = value[{"a": 0, "b": 1}[part]] if isinstance(value, list) else value[part]
    return value


def _value(value, row, key, words):
    """The value as a cell before the text transforms: a number stays a number, an empty text is ''."""
    if key in row.get("withheld", ()):  # also under a null object (launch ruling B5)
        return words["withheld"]
    if key.startswith("outside_selection."):
        return words["outside_selection"] if value else ""
    if value is None:
        return ""
    if isinstance(value, bool):
        return words["fixed"]["booleans"]["true" if value else "false"]
    if isinstance(value, list):
        return words["fixed"]["separator"].join(map(str, value))
    return value


def _cell(value, row, key, fmt, words) -> tuple:
    """(cell value, characters replaced, prefixed): a number, a non-empty text after the format's transforms, or
    None for an empty cell. 1: control characters, U+FFFE and U+FFFF become U+FFFD. 2, XLSX: carriage returns become
    line feeds. 3, CSV: a text that a spreadsheet program could read as a formula gets one leading '."""
    v = _value(value, row, key, words)
    if not isinstance(v, str):
        return v, 0, 0
    if not v:
        return None, 0, 0
    v, replaced = CONTROL.subn("�", v)
    if fmt == "xlsx":
        return v.replace("\r\n", "\n").replace("\r", "\n"), replaced, 0
    prefix = v[0] in "\t\r" or (v[0] in "=+-@" and not NUMBER.fullmatch(v))
    return "'" * prefix + v, replaced, int(prefix)


def printed(value, row, key, fmt, words) -> str:
    """The text a cell of key holds for value in fmt ("xlsx" or "csv"), "" for an empty cell. A number is the text
    the file holds: "%.16g" in XLSX (openpyxl's form), str in CSV (the csv module's)."""
    v = _cell(value, row, key, fmt, words)[0]
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return "%.16g" % v if fmt == "xlsx" else str(v)
    return v


def _table(dataset, t, columns, rows) -> dict:
    return {"id": t, "title": dataset["words"]["fixed"]["titles"][t], "columns": columns, "rows": rows}


def tables(dataset, report) -> list[dict]:
    """[{id, title, columns, rows}] of one report in sheet order: each list of the report object (the gap report's
    sections in the dataset's order) followed by its sub-tables (rows concatenated in parent order) and, for a pair
    list, the pair sides; the restatement log's unpaired restatements; documents last."""
    cols, obj = dataset["columns"], dataset[report]
    out = []
    for t, rows in obj.items() if isinstance(obj, dict) else [(report, obj)]:
        out.append(_table(dataset, t, cols[t], rows))
        out += [_table(dataset, s, cols[s], [x for r in rows for x in r[s]["rows"]]) for s in SUBS.get(t, ())]
        if report == "restatement_log":
            out.append(_table(dataset, "unpaired_restatements", cols["unpaired_restatements"],
                              dataset["unpaired_restatements"]["rows"]))
        if t in PAIRS:  # each side once, in pair order, the evidence index or related claims row of that id
            rows_by_id = {r["id"]: r for r in (*dataset["evidence_index"], *dataset["related_claims"])}
            ids = dict.fromkeys(c for p in rows for c in (p["claim_a"], p["claim_b"]))
            out.append(_table(dataset, "pair_sides", cols["evidence_index"], [rows_by_id[i] for i in ids]))
    out.append(_table(dataset, "documents", cols["documents"], dataset["documents"]))
    return out


def attributed(table) -> bool:
    """A row with a contributor (records, restatements, adjudications, a correction, a gap confirmation)."""
    keys = [c["key"] for c in table["columns"] if c["key"] in ATTRIBUTED]
    return any(dotted(r, k) is not None for r in table["rows"] for k in keys)


def _about(dataset, any_attributed) -> list[list]:
    """About and about.csv: label and value rows; the mode line, notices and the self-declared line have no label."""
    words = dataset["words"]
    fixed = words["fixed"]
    flt = dict(dataset["filter"])
    hidden = flt.pop("withheld", [])
    echo = json.dumps({k: words["withheld"] if k in hidden else v for k, v in flt.items()}, sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return [fixed["about_csv"], *([fixed["identity"][k], v] for k, v in dataset["data_version"].items()),
            *([fixed["dataset"][k], dataset[k]] for k in ("built_at", "dataset_schema", "gct_version")),
            [None, fixed["mode"][dataset["mode"]]], [fixed["dataset"]["include"], dataset["include"]],
            [fixed["dataset"]["filter"], echo], *([None, n] for n in dataset["notices"]),
            *([[None, words["self_declared"]]] if any_attributed else [])]


def _sheets(dataset, report, fmt) -> list[dict]:
    """The sheets (XLSX) or files (CSV) of one report: About first. head holds the lines above the data: the About
    rows; in XLSX the version band, the notices, the self-declared line where the sheet has an attributed row, one
    blank line and the headings; in CSV the headings alone."""
    words = dataset["words"]
    ts = tables(dataset, report)
    marked = [attributed(t) for t in ts]
    out = [{"id": "about", "title": words["fixed"]["titles"]["about"], "head": _about(dataset, any(marked)),
            "table": None}]
    dv, labels = dataset["data_version"], words["fixed"]["identity"]
    band = [[labels["version"], dv["version"], labels["built_at"], dv["built_at"], labels["sha256"], dv["sha256"],
             words["fixed"]["mode"][dataset["mode"]]], *([n] for n in dataset["notices"])]
    for t, mark in zip(ts, marked):
        heads = [c["heading"] for c in t["columns"]]
        above = [*band, *([[words["self_declared"]]] if mark else []), []] if fmt == "xlsx" else []
        out.append({"id": t["id"], "title": t["title"], "head": [*above, heads], "table": t})
    return out


def _lines(sheet, fmt, words):
    """Each line of a sheet as [(cell value, replaced, prefixed)]."""
    for line in sheet["head"]:
        yield [_cell(v, {}, "", fmt, words) for v in line]
    if t := sheet["table"]:
        for r in t["rows"]:
            yield [_cell(dotted(r, c["key"]), r, c["key"], fmt, words) for c in t["columns"]]


def _check(dataset, report, sheets) -> int:
    """XLSX, before any file: refuses a sheet over MAX_ROWS or a cell over MAX_CELL; returns characters replaced."""
    words, stem, replaced = dataset["words"], report.replace("_", "-"), 0
    for s in sheets:
        t = s["table"]
        if len(s["head"]) + (len(t["rows"]) if t else 0) > MAX_ROWS:
            raise Refusal(f"The {s['title']} table of the {stem} report has more rows than an XLSX sheet can hold"
                          f" ({MAX_ROWS}).", NEXT_STEP)
        for n, line in enumerate(_lines(s, "xlsx", words)):
            for i, (v, rep, _) in enumerate(line):
                replaced += rep
                if isinstance(v, str) and len(v.encode("utf-16-le")) // 2 > MAX_CELL:
                    where = (f"row {t['rows'][n - len(s['head'])]['id']}, column {t['columns'][i]['heading']}"
                             if n >= len(s["head"]) else f"line {n + 1} of the sheet")
                    raise Refusal(f"The {s['title']} table of the {stem} report has a value longer than an XLSX cell"
                                  f" can hold ({where}).", NEXT_STEP)
    return replaced


def write_xlsx(dataset, reports, folder, crops) -> dict:
    """folder/<stem>.xlsx per report. Every check runs over every report before the first file is opened."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.utils import get_column_letter

    books = [(r, _sheets(dataset, r, "xlsx")) for r in reports]
    replaced = sum(_check(dataset, r, sheets) for r, sheets in books)
    files = []
    for report, sheets in books:
        wb = Workbook(write_only=True)
        for s in sheets:
            ws = wb.create_sheet(s["title"])
            if t := s["table"]:  # set before the first row is written (write-only mode)
                h = len(s["head"])
                ws.freeze_panes = f"A{h + 1}"
                ws.auto_filter.ref = f"A{h}:{get_column_letter(len(t['columns']))}{h + len(t['rows'])}"
            for line in _lines(s, "xlsx", dataset["words"]):
                cells = []
                for v, _, _ in line:
                    if isinstance(v, str):  # an inline string: never a formula or an error code
                        v = WriteOnlyCell(ws, value=v)
                        v.data_type = "s"
                    cells.append(v)
                ws.append(cells)
        name = f"{report.replace('_', '-')}.xlsx"
        with open(folder / name, "xb") as fh:
            wb.save(fh)
        files.append(name)
    return {"files": files, "notes": [f"xlsx: {replaced} characters replaced with U+FFFD (control characters, U+FFFE"
                                      " and U+FFFF)."]}


def write_csv(dataset, reports, folder, crops) -> dict:
    """folder/<stem>/about.csv and folder/<stem>/<table id>.csv per report: UTF-8 with a byte order mark, comma, CRLF,
    every text field quoted."""
    files, replaced, prefixed = [], 0, 0
    for report in reports:
        stem = report.replace("_", "-")
        (folder / stem).mkdir()
        for s in _sheets(dataset, report, "csv"):
            name = f"{stem}/{s['id']}.csv"
            with open(folder / name, "x", encoding="utf-8-sig", newline="") as fh:
                out = csv.writer(fh, csv.excel, quoting=csv.QUOTE_NONNUMERIC)
                for line in _lines(s, "csv", dataset["words"]):
                    out.writerow([v for v, _, _ in line])
                    replaced += sum(x[1] for x in line)
                    prefixed += sum(x[2] for x in line)
            files.append(name)
    return {"files": files, "notes": [
        f"csv: {replaced} characters replaced with U+FFFD (control characters, U+FFFE and U+FFFF).",
        f"csv: {prefixed} cells start with ' so that a spreadsheet program reads them as text."]}
