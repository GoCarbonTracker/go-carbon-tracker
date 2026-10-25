"""Rung 1 extraction: fixed reading rules over each page reading. A labelled no-model baseline; its accuracy is not measured."""
import json
import re
from pathlib import Path

from gct.models.semantic_filter import classify_sentence
from gct.stages import Result, Stage, result, run_stage, version_of
from gct.stages.read import ACTIVE, NEWEST_SQL, NOT_ACTIVE, _centre_in, _cluster, select
from gct.stages.read import lines as _lines
from gct.workspace import registry, runs, store

METHOD = "rung1-rules"
RULES_VERSION = 6
READ_FIRST = "read it first: gct read"
RETRY = "Run gct extract again. Pages already extracted are not extracted twice."

# Detects units; never converts them. A space or a slash inside the unit as printed is allowed ("t CO2e").
UNITS = {"tCO2e", "tCO2", "tonnes", "t", "kt", "Mt", "MWh", "GWh", "kWh", "GJ", "TJ", "kL", "ML", "m3", "%", "million tonnes CO2e", "ktCO2e", "kt CO2e"}
NUMBER = re.compile(r"(\(?-?\d(?:[\d,.]*\d)?\)?)(\S*)")
WESTERN = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?")
INDIAN = re.compile(r"-?\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d+)?")
YEAR = re.compile(r"199\d|20\d\d|2100")
PERIOD = re.compile(r"(?<!\w)(?<!\d[,.])(?:FY\s?\d{2,4}(?:-\d{2,4})?|\d{4}-\d{2,4}|199\d|20\d\d|2100)(?!\w|[,.]\d)")
FOOTNOTE_RE = re.compile(r"^[\*#†\^]+$|^\([a-g]\)$", re.I)
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


def _is_unit_cell(text: str) -> bool:
    if not text:
        return False
    if _unit(text):
        return True
    import gct.stages.match as match
    return match.unit_text_of(text) in match.UNITS


def _figure(token: str):
    """(number as printed, attached unit or None) when the token is a figure, else None. Years are not figures."""
    clean = token.rstrip(".,;:")
    m = NUMBER.fullmatch(clean)
    if not m:
        return None
    number, rest = m.groups()
    is_footnote = bool(rest and FOOTNOTE_RE.fullmatch(rest))
    if is_footnote:
        rest = ""
    if rest and not _unit(rest):
        return None
    if not rest and YEAR.fullmatch(number):
        return None
    return (clean if is_footnote else number), (rest or None)


def _cell_figure(text: str):
    """A table cell holding one figure, optionally followed by a unit word."""
    first, _, rest = text.partition(" ")
    fig = _figure(first)
    if not fig or not rest:
        return fig
    return (fig[0], _unit(rest)) if fig[1] is None and _unit(rest) else None


def _value(number: str) -> float | None:
    """Western or Indian grouped numbers get a value after trailing footnote marks are removed."""
    s = str(number or "").strip().rstrip("*#†^").strip()
    return float(s.replace(",", "")) if WESTERN.fullmatch(s) or INDIAN.fullmatch(s) else None


def _extract_unit(text: str) -> str | None:
    """Scan parentheticals in text (right-to-left) and return the first valid unit."""
    if not text:
        return None
    matches = re.findall(r"\(([^()]+)\)", text)
    for g in reversed(matches):
        g_clean = g.strip()
        if any(op in g_clean for op in ("+", "=", "–", "—", "-")):
            continue
        if re.fullmatch(r"[a-z]|\b(?:i|ii|iii|iv|v|vi|vii|viii|ix|x)\b", g_clean, re.I):
            continue
        if re.search(r"market-based|location-based|standalone|consolidated", g_clean, re.I):
            continue
        cand = re.sub(r"^(?:in\s+)", "", g_clean, flags=re.I).strip()
        cand_norm = cand.lower().replace(" ", "").replace("/", "").replace("-", "")
        if _unit(cand) or cand in UNITS or cand_norm in {u.lower().replace(" ", "").replace("/", "").replace("-", "") for u in UNITS}:
            return g_clean
        from gct.stages.match import UNITS as MATCH_UNITS
        if cand_norm in MATCH_UNITS or any(cand_norm.endswith(k) for k in MATCH_UNITS) or "co2" in cand_norm or "joule" in cand_norm or "tonne" in cand_norm:
            return g_clean
    return None


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
    band = [w for w in reading["words"] if -4 <= top - w["bottom"] <= HEADER_BAND and (w["top"] + w["bottom"]) / 2 <= top + 2
            and _overlaps(w["x0"], w["x1"], x0, x1)]
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
        kinds = ["period" if PERIOD.search(s) else "boundary" if BOUNDARY.fullmatch(s) else None for s, *_ in heads]
        if None in kinds:
            break
        for (s, g0, g1), kind in zip(heads, kinds):
            val = re.sub(r"(?:[\*#†\^]|\([a-g]\))+$", "", s).strip() if kind == "period" else s
            for c, span in enumerate(spans):
                if span and _overlaps(g0, g1, span[0], span[2]):
                    out.setdefault(c, {}).setdefault(kind, val)  # the nearest header of a kind wins
    return out


def _row_label(reading: dict, t: int, cells_row: list) -> str | None:
    """The words left of table t whose vertical centre falls inside the row's cell band."""
    boxes = [c for c in cells_row if c]
    if not boxes:
        return None
    first_cell_x0 = min(b[0] for b in boxes)
    top, bottom = min(b[1] for b in boxes), max(b[3] for b in boxes)
    left = [w for w in reading["words"] if w.get("dir", "ltr") == "ltr" and w["x1"] <= first_cell_x0 and top <= (w["top"] + w["bottom"]) / 2 <= bottom]
    wording = [w for w in left if not (_figure(w["text"]) or _unit(w["text"]) or w["text"] in DASHES
                                       or w["text"].lower() in ("unit", "units"))]
    if not wording:
        return None
    end = max(w["x1"] for w in wording)
    left = [w for w in left if w["x0"] < end]
    return _clean(" ".join(w["text"] for line in _lines(left) for w in line)) or None


def _table_claims(reading: dict):
    for t, table in enumerate(reading["tables"]):
        raw_rows = table["rows"]
        cells = table.get("cells") or []  # readings before reading config 2 have no cell boxes
        raw_header = raw_rows[0] if raw_rows else []
        header = [_clean(c) for c in raw_header]
        table_default_unit = _extract_unit(raw_header[0]) if raw_header else None
        unit_cols = [c for c, h in enumerate(header) if h.lower() in ("unit", "units")]
        spans = [next((row[c] for row in cells if c < len(row) and row[c]), None) for c in range(len(header))]
        heads = _headers(reading, t, spans) if cells else {}

        # Detect parallel numeric columns to the right of t["bbox"]
        x0, top, x1, bottom = table["bbox"]
        band_right = [w for w in reading["words"] if -4 <= top - w["bottom"] <= HEADER_BAND
                      and (w["top"] + w["bottom"]) / 2 <= top + 2 and w["x0"] >= x1 - 5]
        parallel_cols = []
        if band_right:
            for line in sorted(_cluster(band_right, 2), key=lambda line: -max(w["bottom"] for w in line)):
                groups = []
                for w in sorted(line, key=lambda w: w["x0"]):
                    if groups and w["x0"] - groups[-1][-1]["x1"] <= WORD_GAP:
                        groups[-1].append(w)
                    else:
                        groups.append([w])
                for g in groups:
                    s = " ".join(w["text"] for w in g)
                    m = PERIOD.search(s)
                    if m:
                        p_period = m.group(0)
                        g0, g1 = g[0]["x0"], g[-1]["x1"]
                        last_w = (spans[-1][2] - spans[-1][0]) if spans and spans[-1] else (x1 - x0)
                        c_x0 = x1 if not parallel_cols else parallel_cols[-1]["x1"]
                        c_x1 = max(g1 + 10, c_x0 + last_w)
                        parallel_cols.append({"period": p_period, "x0": c_x0, "x1": c_x1})

        # If table default unit not found in header[0], inspect rows for a unit
        if not table_default_unit:
            for r in range(1, len(raw_rows)):
                for c in range(len(raw_rows[r])):
                    u = _extract_unit(raw_rows[r][c])
                    if u:
                        table_default_unit = u
                        break
                if table_default_unit:
                    break

        for r, row in enumerate(raw_rows):
            cell_lines = [(c or "").split("\n") for c in row]
            max_l = max((len(cl) for cl in cell_lines), default=1)
            # Only split into multiple lines if figure cells have multiple lines
            if max_l > 1 and not any(len(cl) > 1 and any(_figure(tk) for tk in cl) for c, cl in enumerate(cell_lines)):
                max_l = 1

            for l_idx in range(max_l):
                sub_row = [_clean(cell_lines[c][l_idx] if l_idx < len(cell_lines[c]) else "") for c in range(len(row))]
                raw_sub_row = [cell_lines[c][l_idx] if l_idx < len(cell_lines[c]) else "" for c in range(len(row))]
                row_unit_cell = None
                at = None
                for c, s in enumerate(sub_row):
                    if s and s not in DASHES and not _cell_figure(s):
                        if _is_unit_cell(s):
                            if row_unit_cell is None:
                                row_unit_cell = s
                            continue
                        if s.lower() in ("unit", "units", "uom"):
                            continue
                        at = c
                        break
                label = sub_row[at] if at is not None else (_row_label(reading, t, cells[r]) if r < len(cells) else None)
                row_unit = _extract_unit(raw_sub_row[at]) if at is not None else _extract_unit(label)
                for c in range(len(sub_row)):
                    fig = None if c == at or c in unit_cols else _cell_figure(sub_row[c])
                    if not fig:
                        continue
                    head = heads.get(c, {})
                    h_clean = re.sub(r"(?:[\*#†\^]|\([a-g]\))+$", "", header[c]).strip() if header[c] else ""
                    period = (h_clean if r and (PERIOD.search(h_clean) or "as at" in h_clean.lower()) else None) or head.get("period")
                    unit = (sub_row[unit_cols[0]] if unit_cols else None) or fig[1] or row_unit_cell or row_unit or table_default_unit
                    box = cells[r][c] if r < len(cells) and c < len(cells[r]) else None
                    inside = [w for w in reading["words"] if box and _centre_in(w, box)]
                    if max_l > 1:
                        inside_lines = _lines(inside)
                        line_w = inside_lines[l_idx] if l_idx < len(inside_lines) else []
                        exact = line_w and " ".join(w["text"] for w in line_w) == sub_row[c]
                        box_to_use = [_union(line_w)] if exact else ([_union(inside)] if inside else None)
                    else:
                        exact = inside and " ".join(w["text"] for line in _lines(inside) for w in line) == sub_row[c]
                        box_to_use = [_union(inside)] if exact else None
                    loc = f"t{t}r{r}c{c}" if max_l == 1 else f"t{t}r{r}l{l_idx}c{c}"
                    yield _claim(loc, label, fig[0], unit or None, period, box_to_use, head.get("boundary"))

            # Parallel numeric columns to the right of t["bbox"]
            if parallel_cols and r > 0 and r < len(cells):
                boxes = [c for c in cells[r] if c]
                if boxes:
                    r_top, r_bottom = min(b[1] for b in boxes), max(b[3] for b in boxes)
                    row_unit_cell = None
                    at = None
                    for c, s in enumerate(row):
                        s_clean = _clean(s)
                        if s_clean and s_clean not in DASHES and not _cell_figure(s_clean):
                            if _is_unit_cell(s_clean):
                                if row_unit_cell is None:
                                    row_unit_cell = s_clean
                                continue
                            if s_clean.lower() in ("unit", "units", "uom"):
                                continue
                            at = c
                            break
                    label = _clean(row[at]) if at is not None else _row_label(reading, t, cells[r])
                    row_unit = _extract_unit(row[at]) if at is not None else _extract_unit(label)
                    unit = row_unit_cell or row_unit or table_default_unit
                    for p_idx, pcol in enumerate(parallel_cols):
                        p_box = [pcol["x0"], r_top, pcol["x1"], r_bottom]
                        inside = [w for w in reading["words"] if _centre_in(w, p_box)]
                        if inside:
                            txt = " ".join(w["text"] for line in _lines(inside) for w in line)
                            fig = _cell_figure(txt)
                            if fig:
                                exact = " ".join(w["text"] for line in _lines(inside) for w in line) == txt
                                loc = f"t{t}r{r}c{len(row) + p_idx}"
                                yield _claim(loc, label, fig[0], unit or None, pcol["period"], [_union(inside)] if exact else None, None)


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


def _semantic_text_claims(reading: dict, existing_claims: list[dict] | None = None):
    h = reading.get("height", 792)
    bboxes = [t["bbox"] for t in reading.get("tables", [])]
    words = [w for w in reading.get("words", [])
             if w.get("dir", "ltr") == "ltr"
             and w["top"] >= 0.05 * h and w["bottom"] <= 0.95 * h
             and not any(_centre_in(w, b) for b in bboxes)]
    if not words:
        return

    # To avoid duplicates: if a sentence already contains a Rung 1 numeric claim, Rung 1 retains priority
    if existing_claims is None:
        existing_claims = list(_text_claims(reading))
    r1_boxes = [b for c in existing_claims for b in (c.get("boxes") or [])]

    body_lines = _lines(words)
    if not body_lines:
        return

    paragraphs = []
    curr_para = []
    for line in body_lines:
        if not curr_para:
            curr_para.append(line)
            continue
        prev_line = curr_para[-1]
        prev_bottom = max(w["bottom"] for w in prev_line)
        curr_top = min(w["top"] for w in line)
        prev_h = prev_bottom - min(w["top"] for w in prev_line)
        gap = curr_top - prev_bottom
        if gap > max(1.5 * prev_h, 8.0) or gap < -2.0:
            paragraphs.append(curr_para)
            curr_para = [line]
        else:
            curr_para.append(line)
    if curr_para:
        paragraphs.append(curr_para)

    for p_idx, para in enumerate(paragraphs):
        para_words = [w for line in para for w in line]
        if not para_words:
            continue

        sentences = []
        curr_sent = []
        for w in para_words:
            curr_sent.append(w)
            txt = w["text"]
            if txt.endswith((".", "!", "?")) and not (
                txt.lower() in ("e.g.", "i.e.", "vs.", "mr.", "ms.", "dr.", "co.", "ltd.", "inc.", "corp.")
                or re.match(r"^\d+\.$", txt)
            ):
                sentences.append(curr_sent)
                curr_sent = []
        if curr_sent:
            sentences.append(curr_sent)

        for s_idx, sent_words in enumerate(sentences):
            sent_text = _clean(" ".join(w["text"] for w in sent_words))
            if not sent_text:
                continue

            if r1_boxes and any(any(_centre_in(w, b) for b in r1_boxes) for w in sent_words):
                continue

            verdict, prob = classify_sentence(sent_text, threshold=0.05)
            if verdict:
                m_period = PERIOD.search(sent_text)
                period = m_period.group(0).strip() if m_period else None
                yield {
                    "locator": f"p{p_idx}s{s_idx}",
                    "metric_text": sent_text,
                    "value_text": None,
                    "value": None,
                    "unit_text": None,
                    "period_label": period,
                    "boundary_label": None,
                    "boxes": [_union(sent_words)],
                    "method": "rung2-climatebert",
                    "claim_probability": prob,
                }


def rules(reading: dict) -> list[dict]:
    tables = list(_table_claims(reading))
    texts = list(_text_claims(reading))
    semantics = list(_semantic_text_claims(reading, existing_claims=texts))
    return [*tables, *texts, *semantics]


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
    return any((old[k] or None) != (f.get(k) or None) for k in VERSION_FIELDS) or (boxes or None) != (f["boxes"] or None)


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
                    (claim_id, run_id, f.get("method") or METHOD, config, f["metric_text"], f["value_text"] or "", f["value"], f["unit_text"],
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
