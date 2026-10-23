"""The PDF reports (story 7.4): one PDF per report the command names, its rows from the dataset's columns, then an
evidence appendix holding the page images crops.cut made for exactly the evidence that PDF's rows cite. Layout
provisional until practitioner feedback (U23): A4 portrait, 36 pt margins, reportlab's own Vera fonts.

Every data string reaches the page through one Paragraph path (_Ink): normalised, each character the font cannot
draw replaced by its NFKC form or [U+XXXX], then escaped, so the text a reader sees is the text extracted and no
markup in a value is ever read as markup. Renderers never read the workspace (7.1 C4): reportlab and Pillow are
imported inside write, and the only files read are reportlab's own fonts."""
import functools
import os
import struct
import unicodedata
from io import BytesIO
from xml.sax.saxutils import escape

SECTIONS = ("candidates", "expectations", "documents_checked", "extraction_limits", "archived", "deleted")
PAIRS = ("restatement_log", "candidates")  # tables whose rows have two sides
FONTS = {"GCTVera": "Vera.ttf", "GCTVeraBold": "VeraBd.ttf"}  # never DarkGarden (7.4-P10)
BODY, BOLD = FONTS
SCALES = {True: 3.0, False: 1.5}  # crops.cut's scales: a band (boxes), a whole page (7.4-P2, 7.4-P12)
MARGIN, INDENT = 36, 12
HANG = 36  # every line after a paragraph's first, from a value's newline or a wrap, starts this far right of it (F1)
SIZE, LEADING = 8.5, 10.5


class Refusal(Exception):
    """A dataset or crops map this renderer will not print; gct report refuses with cause and next_step."""

    def __init__(self, cause: str, next_step: str):
        super().__init__(cause)
        self.cause, self.next_step = cause, next_step


def _dotted(row, key):
    """A row value by its columns key: a dotted key walks the object (null when the object is null);
    outside_selection's a and b are its two items."""
    value = row
    for part in key.split("."):
        if value is None:
            return None
        value = value[{"a": 0, "b": 1}[part]] if isinstance(value, list) else value[part]
    return value


def _shown(value, row, key, words) -> str:
    """The one print form of a dataset value (7.1 C2a, C3)."""
    if row is not None and key in row["withheld"]:
        return words["withheld"]
    if key is not None and key.startswith("outside_selection."):
        return words["outside_selection"] if value else ""
    if value is None:
        return ""
    if isinstance(value, bool):
        return words["fixed"]["booleans"]["true" if value else "false"]
    if isinstance(value, list):
        return words["fixed"]["separator"].join(str(x) for x in value)
    return str(value)


def _plain(s: str, cmap) -> tuple[str, int]:
    """Steps 0 and 1 of the text path: NFC, line ends and tabs, then each character outside the font's cmap replaced
    by its NFKC form when that form is drawable, else by [U+XXXX] (a newline is kept). Returns the text and the number
    of characters replaced."""
    s = unicodedata.normalize("NFC", s).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    out, n = [], 0
    for c in s:
        if c == "\n" or ord(c) in cmap:
            out.append(c)
            continue
        n += 1
        f = unicodedata.normalize("NFKC", c)
        out.append(f if f != c and all(ord(x) in cmap for x in f) else f"[U+{ord(c):04X}]")
    return "".join(out), n


class _Ink:
    """Prepares every string drawn in one PDF and counts what it replaced."""

    def __init__(self, cmaps):
        self.cmaps, self.replaced = cmaps, 0

    def __call__(self, s: str, font: str = BODY) -> str:
        text, n = _plain(s, self.cmaps[font])
        self.replaced += n
        return escape(text).replace("\n", "<br/>")


def _attributed(rows, columns) -> bool:
    """7.1 C2a, as 7.3 words it: a row with a non-null contributor or dotted *.contributor column."""
    keys = [c["key"] for c in columns if c["key"] == "contributor" or c["key"].endswith(".contributor")]
    return any(_dotted(r, k) is not None for r in rows for k in keys)


def _plan(dataset, report) -> list[tuple]:
    """What one PDF prints, in order: ("title", depth, table, rows) opens a table or sub-table (rows for the
    self-declared caption); ("row", depth, table, row) is a row block opened by its row-key heading; ("sub", depth,
    table, row) a sub-table row, without one; ("side", depth, "claim_a" or "claim_b", row or None, outside) a pair
    side. Tables come from the report object's own nesting; documents and unpaired restatements are named."""
    cols = dataset["columns"]
    sides = {r["claim_id"]: r for r in dataset["evidence_index"] + dataset["related_claims"]}
    out = []

    def block(table, rows, depth, kind):
        out.append(("title", depth, table, rows))
        for r in rows:
            out.append((kind, depth, table, r))
            if table in PAIRS:
                found = [sides.get(r[k]) for k in ("claim_a", "claim_b")]
                out.append(("title", depth + 1, "pair_sides", [x for x in found if x]))
                for k, side, outside in zip(("claim_a", "claim_b"), found, r["outside_selection"]):
                    out.append(("side", depth + 1, k, side, outside))
            for k, v in r.items():
                if isinstance(v, dict) and "rows" in v and v["rows"]:
                    block(k, v["rows"], depth + 1, "sub")

    if report == "gap_report":
        for s in SECTIONS:
            block(s, dataset["gap_report"][s], 0, "row")
    else:
        block(report, dataset[report], 0, "row")
    if report == "restatement_log" and dataset["unpaired_restatements"]["rows"]:
        block("unpaired_restatements", dataset["unpaired_restatements"]["rows"], 0, "sub")
    if dataset["documents"]:
        block("documents", dataset["documents"], 0, "sub")
    return out


def _rows(plan):
    """(table, row) for every row a plan prints, pair sides included."""
    for item in plan:
        if item[0] in ("row", "sub"):
            yield item[2], item[3]
        elif item[0] == "side" and item[3] is not None:
            yield "evidence_index", item[3]


def _withheld(dataset, entry):
    """The builder's credential-withholding notice for this document, or None."""
    prefix = f"Evidence images for document {entry['document_id']} ("
    return next((n for n in dataset["notices"] if n.startswith(prefix)), None)


def _check(dataset, reports, crops):
    """The three refusals (story 7.4 Design, "Refusals"), before any file is opened."""
    again = "Run the report again. If this message repeats, report it as a fault in GCT."
    ids = {e["id"] for e in dataset["evidence"]}
    pages = {e["id"] for e in dataset["evidence"] if e["page"] is not None and not _withheld(dataset, e)}
    if odd := sorted(set(crops) - ids):
        raise Refusal(f"A page image was made for evidence E{odd[0]}, which this report's data does not hold.", again)
    if crops and (lacking := sorted(pages - set(crops))):
        raise Refusal(f"No page image was made for evidence E{lacking[0]}.", again)
    version = dataset["data_version"]["version"]
    for report in reports:
        other = sorted((r["id"], r["data_version"]) for _, r in _rows(_plan(dataset, report))
                       if r["data_version"] != version)
        if other:
            title = dataset["words"]["fixed"]["titles"][report]
            raise Refusal(f"Row {other[0][0]} of {title} comes from data version {other[0][1]}, but this report is"
                          f" for data version {version}.", "Run the report again so every row comes from one data version.")


def write(dataset, reports, folder, crops) -> dict:
    """Writes <report>.pdf into folder for each of reports (dataset keys), each file opened with mode x and streamed
    by reportlab. crops is the one dict crops.cut returned; {} with a page entry in the dataset is the image cap."""
    import reportlab
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _check(dataset, reports, crops)
    fonts = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    for name, file in FONTS.items():
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, os.path.join(fonts, file)))
    cmaps = {name: pdfmetrics.getFont(name).face.charToGlyph for name in FONTS}
    words, fixed = dataset["words"], dataset["words"]["fixed"]
    titles, headings, sep = fixed["titles"], fixed["headings"], fixed["separator"]
    cols, evidence = dataset["columns"], {e["id"]: e for e in dataset["evidence"]}
    documents = {d["id"]: d for d in dataset["documents"]}
    cap = not crops and any(e["page"] is not None and not _withheld(dataset, e) for e in dataset["evidence"])
    width, height = A4
    text_width, room = width - 2 * MARGIN, height - 2 * MARGIN - 4 * LEADING

    @functools.cache
    def style(name, font=BODY, size=SIZE, depth=0, before=0, hang=HANG):
        """Only a paragraph's first line starts at the block's margin, so no value can open a line there."""
        return ParagraphStyle(name, fontName=font, fontSize=size, leading=size + 2, leftIndent=depth * INDENT + hang,
                              firstLineIndent=-hang, spaceBefore=before)

    def each(texts, name, depth=0, before=0):
        """One paragraph per structural line, the first spaced from what precedes it."""
        return [Paragraph(t, style(name, depth=depth, before=before if k == 0 else 0)) for k, t in enumerate(texts)]

    class Picture(Flowable):
        """One PNG drawn as is (reportlab embeds its RGB pixels, never resampled), scaled at draw time only."""

        def __init__(self, png, boxes):
            super().__init__()
            w, h = struct.unpack(">II", png[16:24])  # the IHDR chunk: no image is opened here
            f = min(1 / SCALES[boxes], text_width / w, room / h)  # never upscaled (7.4-P2)
            self.png, self.width, self.height = png, w * f, h * f

        def wrap(self, *a):
            return self.width, self.height

        def draw(self):
            self.canv.drawImage(ImageReader(BytesIO(self.png)), 0, 0, self.width, self.height)

    files, notes = [], []
    for report in reports:
        name = f"{report.replace('_', '-')}.pdf"
        ink = _Ink(cmaps)
        title = titles[report]
        plan = _plan(dataset, report)
        mode = dataset["mode"]

        def lines(table, row, depth):
            out = [f"{ink(c['heading'])}: {ink(_shown(_dotted(row, c['key']), row, c['key'], words))}"
                   for c in cols[table]]
            if row["evidence"]:
                out.append(f"{ink(fixed['pdf']['evidence'])}: {ink(sep.join(f'E{i}' for i in row['evidence']))}")
            return each(out, "l", depth, 4)

        body = []
        for kind, depth, table, *rest in plan:
            if kind == "title":
                text = titles[table]
                body.append(Paragraph(ink(text, BOLD), style("t", BOLD, 10 if depth == 0 else SIZE, depth, 8)))
                if _attributed(rest[0], cols["evidence_index" if table == "pair_sides" else table]):
                    body.append(Paragraph(ink(words["self_declared"]), style("c", depth=depth)))
            elif kind == "row":
                row = rest[0]
                heading = fixed["pdf"]["row"].format(title=titles[table], id=row["id"])
                body.append(Paragraph(ink(heading, BOLD), style("h", BOLD, depth=depth, before=8)))
                body += lines(table, row, depth)
            elif kind == "sub":
                body += lines(table, rest[0], depth)
            else:
                side, outside = rest
                body.append(Paragraph(ink(headings[table], BOLD), style("s", BOLD, depth=depth, before=4)))
                if outside:
                    body.append(Paragraph(ink(words["outside_selection"]), style("o", depth=depth)))
                if side is not None:
                    body += lines("evidence_index", side, depth)

        # The appendix: every evidence id this PDF's rows cite, in document and page order.
        citing = {}
        for table, row in _rows(plan):
            for i in row["evidence"]:
                citing.setdefault(i, []).append(row)
        cited = sorted(citing, key=lambda i: (evidence[i]["document_id"], evidence[i]["page"] or 0,
                                              evidence[i]["sheet"] or "", evidence[i]["cell"] or "", i))
        if cited:
            body.append(Paragraph(ink(fixed["pdf"]["appendix"], BOLD), style("a", BOLD, 12, before=12)))
            if cap:
                body.append(Paragraph(ink(fixed["image_limit"]), style("cap")))
        for i in cited:
            e, rows = evidence[i], citing[i]
            doc = documents[e["document_id"]]
            doc_name = _shown(doc["name"], None, None, words)
            where = [("document_name", doc["name"]), ("document_version", doc["version"])]
            where += [("page", e["page"])] if e["page"] is not None else [("sheet", e["sheet"]), ("cell", e["cell"])]
            entry = [Paragraph(ink(f"E{i}", BOLD), style("e", BOLD, before=10)),
                     *each([f"{ink(headings[k])}: {ink(_shown(v, None, k, words))}" for k, v in where], "w")]
            binding = any(r.get("binds") is not False for r in rows)  # a non-binding record shows its location only
            if note := _withheld(dataset, e):
                entry.append(Paragraph(ink(note), style("w")))
            elif e["page"] is not None and binding and not cap:
                claims = sorted(r["claim_id"] for r in rows if r.get("claim_id") is not None)
                alt = (fixed["image_alt"].format(claim=claims[0], document=doc_name, page=e["page"]) if claims else
                       fixed["image_alt_entry"].format(evidence=i, document=doc_name, page=e["page"]))
                caption = [Paragraph(ink(alt), style("i"))]
                if e["boxes"]:
                    caption.append(Paragraph(ink(fixed["image_cap"]), style("i")))
                entry.append(KeepTogether([Picture(crops[i], bool(e["boxes"])), *caption]))
            if e["header"] is not None:  # a cell: its row transposed with the header, the cited cell in bold (D16)
                n = max(len(e["header"]), len(e["row"]))
                cells = [[Paragraph(ink(x, BOLD if k == e["marked"] else BODY), style("x", BOLD if k == e["marked"]
                                                                                       else BODY))
                          for x in (e["header"][k] if k < len(e["header"]) else "",
                                    e["row"][k] if k < len(e["row"]) else "")] for k in range(n)]
                table = Table(cells, colWidths=[text_width * 0.4, text_width * 0.6], hAlign="LEFT", splitInRow=1)
                table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, (0.6, 0.6, 0.6)),
                                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                entry.append(table)
            texts = list(dict.fromkeys(r["evidence_text"] for r in rows if r.get("evidence_text") is not None))
            if texts:
                entry.append(Paragraph(f"{ink(headings['evidence_text'])}: {ink(sep.join(texts))}", style("w")))
            body += entry

        # The first page: identity, the dataset's own keys, mode, filter, notices, then the notes.
        first = [Paragraph(ink(title, BOLD), style("T", BOLD, 16))]
        about = [f"{ink(fixed['identity'][k])}: {ink(_shown(v, None, k, words))}"
                 for k, v in dataset["data_version"].items()]
        about += [f"{ink(fixed['dataset'][k])}: {ink(_shown(dataset[k], None, k, words))}"
                  for k in ("gct_version", "built_at", "dataset_schema", "include")]
        about += [ink(fixed["mode"][mode]), f"{ink(fixed['dataset']['filter'])}:"]
        flt = dataset["filter"]
        for k, v in flt.items():
            if k == "withheld":
                continue
            for kk, vv in (v.items() if isinstance(v, dict) else [(None, v)]):
                shown = words["withheld"] if k in flt.get("withheld", []) else _shown(vv, None, None, words)
                about.append(f"{ink(k if kk is None else f'{k}.{kk}')}: {ink(shown)}")
        first += each(about, "d", before=6)
        first += [Paragraph(ink(n), style("n", before=4)) for n in dataset["notices"]]
        if any(_attributed([r], cols[t]) for t, r in _rows(plan)):
            first.append(Paragraph(ink(words["self_declared"]), style("n", before=4)))
        footer = [ink(title), ink(f"{fixed['data_version']} {dataset['data_version']['version']}"),
                  ink(dataset["data_version"]["sha256"][:12])]
        notice = [ink(words["privacy_notice"])] if mode == "sanitised" else []
        pages = ink(fixed["pdf"]["page"]), ink(fixed["pdf"]["of"])
        if ink.replaced:
            first.append(Paragraph(ink(fixed["pdf"]["font_note"]), style("n", before=4)))
        small = style("f", size=7, hang=0)

        class Pages(Canvas):
            """Holds each page until the end, so every footer can say how many pages there are."""

            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self._held = []

            def showPage(self):
                self._held.append(dict(self.__dict__))
                self._startPage()

            def save(self):
                for n, state in enumerate(self._held, 1):
                    self.__dict__.update(state)
                    p = Paragraph(sep.join([*footer, f"{pages[0]} {n} {pages[1]} {len(self._held)}", *notice]), small)
                    p.wrapOn(self, text_width, MARGIN)
                    p.drawOn(self, MARGIN, MARGIN / 2 - 4)
                    super().showPage()
                super().save()

        with open(folder / name, "xb") as f:
            doc = SimpleDocTemplate(f, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                                    bottomMargin=MARGIN, invariant=1, title=title, author="GCT", creator="GCT",
                                    subject=dataset["gct_version"])
            doc.build([*first, Spacer(1, 12), *body], canvasmaker=Pages)
        files.append(name)
        notes.append(f"{name}: {ink.replaced} characters not in the PDF's font were printed as their NFKC form or as"
                     " their code point.")
    return {"files": files, "notes": notes}
