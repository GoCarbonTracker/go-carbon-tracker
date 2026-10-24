"""Evidence images for the reports (story 7.4, 7.1 C4a; 7.5 calls cut too). cut(root, dataset) makes one PNG per page
entry of dataset["evidence"] from the stored original, with the viewer's renderer (gct.evidence.pages), fresh: the
viewer's render cache is neither read nor written. It runs under the lock gct report holds for build, crops and
render, never opens workspace.db or a version file and never reads a label (the builder applied them)."""
import itertools
import json
import math
import unicodedata
from io import BytesIO
from pathlib import Path

from gct.evidence.pages import _frames, _render
from gct.models.redact import scrub
from gct.workspace import registry
from gct.workspace.layout import NOT_FOUND, GctError

LIMIT = 500  # 7.4-P3: more page entries than this, and no image is made
SCALE, PAGE_SCALE = 3.0, 1.5  # a band (7.4-P2), a whole page (the viewer's scale, 7.4-P12)
MARGIN = 24  # points above and below the boxes' union (7.4-P1)
SPREAD = 1.4  # a frame wider than this times its height is a two-up spread (7.4-P1)
OUTLINE, GROW = (220, 0, 0), 2  # 7.4-P11: the ring of pixels just outside each box


def _credential(text):
    normal = unicodedata.normalize("NFKC", text)
    return scrub(text) != text or scrub(normal) != normal


def credential_documents(conn, root, documents) -> set:
    """Document ids with credentials in cached, source text, metadata or annotations. No pixels are inspected."""
    held = set()

    def _scan_val(val) -> bool:
        if val is None:
            return False
        if isinstance(val, str):
            return _credential(val)
        if isinstance(val, bytes):
            for enc in ("utf-8", "utf-16", "utf-16-be", "latin-1"):
                try:
                    if _credential(val.decode(enc)):
                        return True
                except UnicodeDecodeError:
                    pass
        if hasattr(val, "name") and isinstance(val.name, str):
            return _credential(val.name)
        if isinstance(val, (list, tuple)):
            return any(_scan_val(x) for x in val)
        if isinstance(val, dict):
            return any(_scan_val(k) or _scan_val(v) for k, v in val.items())
        return False

    def _scan_stream(stream) -> bool:
        if not hasattr(stream, "get_data"):
            return False
        try:
            if _scan_val(stream.get_data()):
                return True
        except Exception:
            return True

        from pdfminer.pdfinterp import PDFContentParser
        from pdfminer.psexceptions import PSEOF

        try:
            parser = PDFContentParser([stream])
            while True:
                try:
                    (_, obj) = parser.nextobject()
                except PSEOF:
                    if (parser.curtype is not None or parser.context or
                            getattr(parser, "paren", 0) > 0 or
                            getattr(parser, "_parse1", None) != getattr(parser, "_parse_main", None)):
                        return True  # Incomplete container or literal fails closed
                    break
                if _scan_val(obj):
                    return True
                if isinstance(obj, list):
                    combined = b"".join(x for x in obj if isinstance(x, bytes))
                    if _scan_val(combined):
                        return True
        except Exception:
            return True  # Parser failure withholds the document (fail closed)
        return False

    for d in documents:
        if d["file_type"] not in ("pdf", "csv", "xlsx"):
            continue
        for r in conn.execute("SELECT a.path FROM page p JOIN artifact a ON a.id = p.artifact_id"
                              " WHERE p.document_id = ? ORDER BY p.id", (d["id"],)):
            try:
                text = json.loads((Path(root) / r["path"]).read_text(encoding="utf-8"))["text"]
                if not isinstance(text, str):
                    continue
                if _credential(text):
                    held.add(d["id"])
            except (OSError, ValueError, KeyError, TypeError):
                continue  # The stored PDF supplies text when the reading cannot.

        stored = registry.stored_path(Path(root), d["sha256"])
        if d["file_type"] == "pdf":
            import pdfplumber
            from pdfminer.pdftypes import resolve1

            try:
                with pdfplumber.open(stored) as pdf:
                    if pdf.metadata and _scan_val(pdf.metadata):
                        held.add(d["id"])
                    for info_dict in getattr(pdf.doc, "info", []):
                        if _scan_val(resolve1(info_dict)):
                            held.add(d["id"])
                    if hasattr(pdf.doc, "catalog") and isinstance(pdf.doc.catalog, dict):
                        cat = resolve1(pdf.doc.catalog)
                        if isinstance(cat, dict) and "Metadata" in cat:
                            if _scan_stream(resolve1(cat["Metadata"])):
                                held.add(d["id"])

                    for page in pdf.pages:
                        text = page.extract_text() or ""
                        if _credential(text):
                            held.add(d["id"])
                        annots = resolve1(page.page_obj.attrs.get("Annots"))
                        if isinstance(annots, (list, tuple)):
                            for a_ref in annots:
                                annot = resolve1(a_ref)
                                if not isinstance(annot, dict):
                                    continue
                                for key in ("Contents", "RC", "TU", "T"):
                                    if _scan_val(resolve1(annot.get(key))):
                                        held.add(d["id"])
                                ap = resolve1(annot.get("AP"))
                                if isinstance(ap, dict):
                                    for sub in ap.values():
                                        entry = resolve1(sub)
                                        streams = [resolve1(v) for v in entry.values()] if isinstance(entry, dict) else [entry]
                                        for s in streams:
                                            if _scan_stream(s):
                                                held.add(d["id"])
                        page.close()
            except Exception:  # Any PDF read failure must withhold the whole document.
                held.add(d["id"])

        elif d["file_type"] in ("csv", "xlsx"):
            try:
                if d["file_type"] == "csv":
                    import csv

                    text = stored.read_text(encoding="utf-8-sig")
                    if _credential(text):
                        held.add(d["id"])
                    else:
                        for row in csv.reader(text.splitlines()):
                            for cell in row:
                                if _credential(cell):
                                    held.add(d["id"])
                                    break
                else:  # xlsx
                    import zipfile
                    from xml.etree import ElementTree

                    with zipfile.ZipFile(stored) as z:
                        for name in z.namelist():
                            if name.endswith((".xml", ".rels")):
                                try:
                                    root_el = ElementTree.fromstring(z.read(name))
                                    for t in root_el.itertext():
                                        if t and _credential(t):
                                            held.add(d["id"])
                                            break
                                except Exception:
                                    pass
                    if d["id"] not in held:
                        from gct.stages import sheet

                        for _, rows in sheet.read_book(str(stored), "xlsx", d.get("logical_name", "")):
                            for row in rows:
                                for cell in row:
                                    if cell and _credential(cell):
                                        held.add(d["id"])
                                        break
            except Exception:
                held.add(d["id"])
    return held


def withheld(dataset, entry):
    """The dataset notice that withholds this entry's image, or None. Notices retain the schema's evidence fields."""
    prefix = f"Evidence images for document {entry['document_id']} ("
    return next((n for n in dataset.get("notices", ()) if n.startswith(prefix)), None)


def _pixels(rect, size) -> tuple[int, int, int, int]:
    """The half-open pixel rectangle of a real-valued one: clamped to size, then left and top floored, right and
    bottom ceiled. One rule for the band and for every box."""
    (x0, y0, x1, y1), (w, h) = rect, size
    x0, x1 = (min(max(x, 0), w) for x in (x0, x1))
    y0, y1 = (min(max(y, 0), h) for y in (y0, y1))
    return math.floor(x0), math.floor(y0), math.ceil(x1), math.ceil(y1)


def _band(frame, boxes, size) -> tuple[tuple, list]:
    """The band's pixel rectangle in the render (7.4-P1) and each box's pixel rectangle in the render. Boxes are
    [x0, top, x1, bottom] in points, absolute in the frame, whose left and top need not be 0, 0."""
    left, top, width = frame["left"], frame["top"], frame["width"]
    x0, x1 = left, left + width
    if width > SPREAD * frame["height"]:
        middle = left + width / 2
        if all(b[2] <= middle for b in boxes):
            x1 = middle
        elif all(b[0] >= middle for b in boxes):
            x0 = middle
    y0, y1 = min(b[1] for b in boxes) - MARGIN, max(b[3] for b in boxes) + MARGIN
    band = _pixels(((x0 - left) * SCALE, (y0 - top) * SCALE, (x1 - left) * SCALE, (y1 - top) * SCALE), size)
    return band, [_pixels(((b[0] - left) * SCALE, (b[1] - top) * SCALE, (b[2] - left) * SCALE, (b[3] - top) * SCALE),
                          size) for b in boxes]


def _outline(band, rects):
    """The outline mask of a band ('L', 255 on outline pixels): every box's rectangle grown by GROW, minus every box's
    rectangle, clamped to the band."""
    from PIL import Image

    bx, by = band[0], band[1]
    mask = Image.new("L", (band[2] - bx, band[3] - by), 0)
    for x0, y0, x1, y1 in rects:
        mask.paste(255, (x0 - GROW - bx, y0 - GROW - by, x1 + GROW - bx, y1 + GROW - by))
    for x0, y0, x1, y1 in rects:
        mask.paste(0, (x0 - bx, y0 - by, x1 - bx, y1 - by))
    return mask


def _crop(png: bytes, frame, boxes) -> bytes:
    from PIL import Image

    page = Image.open(BytesIO(png)).convert("RGB")
    band, rects = _band(frame, boxes, page.size)
    out = page.crop(band)
    out.paste(OUTLINE, (0, 0, *out.size), _outline(band, rects))
    data = BytesIO()
    out.save(data, "PNG")
    return data.getvalue()


def cut(root, dataset) -> dict:
    """{evidence id: PNG bytes} for exactly the page entries of dataset["evidence"]; {} above LIMIT. A band at SCALE
    with every box outlined for an entry with boxes, the page's render at PAGE_SCALE unchanged for a whole-page one;
    cell entries get nothing. Each (original, page, scale) is rendered once per call."""
    pages = [e for e in dataset["evidence"] if e["page"] is not None and not withheld(dataset, e)]
    if len(pages) > LIMIT:
        return {}
    missing = sorted({e["document_id"] for e in dataset["evidence"]  # withheld entries too: 7.4's refusal stands
                      if e["page"] is not None and not registry.stored_path(root, e["sha256"]).is_file()})
    if missing:
        raise GctError(NOT_FOUND, f"The stored copy of document {missing[0]} is missing from the workspace.",
                       "Add the same file again with gct doc add to restore it, then run the report again.")

    def key(e):
        return e["sha256"], e["page"], SCALE if e["boxes"] else PAGE_SCALE

    out = {}
    for (sha, number, scale), group in itertools.groupby(sorted(pages, key=key), key):
        path = registry.stored_path(root, sha)
        png = _render(path, number, scale)  # one render held at a time
        for e in group:
            out[e["id"]] = _crop(png, _frames(path)[number - 1], e["boxes"]) if e["boxes"] else png
    return dict(sorted(out.items()))
