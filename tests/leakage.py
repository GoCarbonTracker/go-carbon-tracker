"""Story 7.7 part A: the leakage scanner. found(path, seeds) looks for every seed inside output files the way an
outsider would, from the files alone: raw bytes, decoded text (CSV and text by BOM, HTML with tags removed, XML
element text inside zips, PDF page text, metadata, every PDF object and string token, raw and superseded PDF
streams, undrawn form and appearance streams) and decoded images (exact pixel hash and the marker colour). Every text
part is also searched with \\u escapes and HTML entities undone and with soft hyphens and zero-width characters
dropped. It reads the path and writes nothing there; SQLite copies go to a temporary folder outside it.

Loud by design: a symbolic link under the path is refused, and a part the scanner cannot read (a broken object, zip
member, image or database) does not stop the rest of the scan; at the end found raises Unreadable naming every such
place, so it never returns a result for a scan that skipped a part.

Known ceilings (not decoded; recorded in the TASK-0224 worker notes): Indexed and 16-bit PDF images (reported as
unreadable, so a scan meeting one raises); UTF-16LE text without a BOM; free-page overflow chains and UTF-16
databases (only the dump and raw bytes are searched); a marker under MIN_PIXELS pixels, so a private crop's marker
rectangle must stay above about 7 by 7 pixels at the smallest scale a renderer draws it. Test code only."""
import base64
import hashlib
import html
import io
import os
import re
import sqlite3
import tempfile
import urllib.parse
import zipfile
import zlib
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

from PIL import Image, ImageChops, ImageSequence, UnidentifiedImageError

MARKER, TOLERANCE, MIN_PIXELS = (0, 200, 120), 8, 50  # 7.1 G: the private-image marker colour
TEXT_KINDS = {"document_text", "contributor", "credential", "path"}
KINDS = TEXT_KINDS | {"file_hash", "image"}  # 7.1 G's exact tokens
SAFE = re.compile(r"[A-Za-z0-9-]+")
DIGEST = re.compile(r"[0-9a-fA-F]{64}")
DATA_URI = re.compile(r"data:([^,\"'\s<>]*),([^\"'\s<>]*)")
U_ESCAPE = re.compile(r"\\u([0-9A-Fa-f]{4})")
TAG = re.compile(r"<[^>]*>")
INVISIBLE = dict.fromkeys((0xAD, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF))  # soft hyphen, zero-width, BOM
STREAM = re.compile(rb"stream\r?\n(.*?)endstream", re.S)
PDF_STRING = re.compile(rb"\(|(?<!<)<([0-9A-Fa-f\s]*)>")
ESCAPES = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
MODES = {"DeviceRGB": "RGB", "RGB": "RGB", "DeviceGray": "L", "G": "L", "DeviceCMYK": "CMYK", "CMYK": "CMYK"}
Image.init()
SIGNED = [f for f, (_, accept) in Image.OPEN.items() if accept is not None]  # formats Pillow knows by their bytes


class Unreadable(Exception):
    """Raised by found after the whole scan when any part could not be read; .places names them, .found holds what
    the rest of the scan found."""

    def __init__(self, places, result):
        super().__init__("the scan could not read: " + "; ".join(places))
        self.places, self.found = places, result


def found(path, seeds) -> dict:
    """{seed name: [place]} for every seed found under path (a file or a folder); seeds not found are left out."""
    texts, digests, images = _check(seeds)
    root = Path(path)
    links = [root] if root.is_symlink() else [
        Path(d, n) for d, dirs, names in os.walk(root) for n in dirs + names if Path(d, n).is_symlink()]
    if links:
        raise ValueError("symbolic links under the scanned path: " + ", ".join(map(str, links)))
    files = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root]
    hits, unreadable = {}, []
    with tempfile.TemporaryDirectory() as tmp:
        assert not Path(tmp).resolve().is_relative_to(root.resolve()), "the temporary folder is inside the scanned path"
        for p in files:
            rel = p.relative_to(root).as_posix() if root.is_dir() else p.name
            for kind, place, part in [("text", f"{rel}: path", rel),
                                      *_blob(p.read_bytes(), rel, tmp, p.with_name(p.name + "-wal"))]:
                if kind == "unreadable":
                    unreadable.append(f"{place} ({part})")
                for name, where in _match(kind, place, part, texts, digests, images):
                    hits.setdefault(name, set()).add(where)
    result = {name: sorted(places) for name, places in hits.items()}
    if unreadable:
        raise Unreadable(unreadable, result)
    return result


def _check(seeds):
    """Seed hygiene (section 3): kinds are 7.1 G's six tokens, text seeds use [A-Za-z0-9-] only, digests are sha256
    hex (exempt from the charset), no value is a substring of another. Returns the text seeds [(name, casefolded
    value)], {digest: [name]} and the image seed names."""
    names = [s["name"] for s in seeds]
    if len(set(names)) != len(names):
        raise ValueError("seed names repeat")
    texts, digests, images, values = [], {}, [], []
    for s in seeds:
        kind, name, value = s["kind"], s["name"], s.get("value")
        if kind not in KINDS:
            raise ValueError(f"seed {name}: unknown kind {kind!r}")
        if kind == "image":
            # render_sha256 is a stored render's file hash; value is the crop's decoded RGB hash (None until 7.4).
            for field, d in (("render_sha256", s.get("render_sha256")), ("value", value)):
                if d is None:
                    continue
                if not (isinstance(d, str) and DIGEST.fullmatch(d)):
                    raise ValueError(f"seed {name}: {field} is a sha256 hex digest")
                digests.setdefault(d.lower(), []).append(name)
                values.append((name, d.casefold()))
            images.append(name)
            continue
        rule = DIGEST if kind == "file_hash" else SAFE
        if not isinstance(value, str) or not rule.fullmatch(value):
            raise ValueError(f"seed {name}: " + ("a file hash is a sha256 hex digest" if kind == "file_hash" else
                                                 "a text seed uses only A-Z, a-z, 0-9 and -"))
        texts.append((name, value.casefold()))
        if kind == "file_hash":
            digests.setdefault(value.lower(), []).append(name)
        values.append((name, value.casefold()))
    for a, va in values:
        for b, vb in values:
            if a != b and va in vb:
                raise ValueError(f"seed {a}'s value is inside seed {b}'s")
    return texts, digests, images


def _match(kind, place, part, texts, digests, images):
    if kind == "text":
        for label, t in _variants(part):
            # As is, case-folded and with white space removed in one search: seeds are ASCII with no white space.
            hay = "".join(t.translate(INVISIBLE).casefold().split())
            yield from ((name, place + label) for name, v in texts if v in hay)
    elif kind == "hash":
        yield from ((name, f"{place}: file hash") for name in digests.get(part, ()))
    elif kind == "image":
        rgb = part.convert("RGB")
        yield from ((name, f"{place}: pixel hash") for name in digests.get(hashlib.sha256(rgb.tobytes()).hexdigest(), ()))
        if images and _marker(rgb):
            yield from ((name, f"{place}: marker colour") for name in images)


def _variants(text):
    """The text, and the text with \\u escapes and HTML entities undone (NDJSON, JSON in a script, entities in any
    text), when that differs."""
    undone = U_ESCAPE.sub(lambda m: chr(int(m[1], 16)), text) if "\\u" in text else text
    undone = html.unescape(undone) if "&" in undone else undone
    return [("", text)] + ([(", unescaped", undone)] if undone != text else [])


def _marker(rgb) -> bool:
    """At least MIN_PIXELS pixels within TOLERANCE of MARKER in every channel."""
    r, g, b = (band.point(lambda v, c=c: 255 if abs(v - c) <= TOLERANCE else 0) for band, c in zip(rgb.split(), MARKER))
    return ImageChops.multiply(ImageChops.multiply(r, g), b).histogram()[255] >= MIN_PIXELS


def _bad(place, e):
    return "unreadable", place, f"{type(e).__name__}: {e}"


def _guard(place, parts):
    """The parts, then one unreadable entry for place if producing them raised."""
    try:
        yield from parts
    except Exception as e:  # noqa: BLE001 (reported, and found raises at the end)
        yield _bad(place, e)


def _blob(data: bytes, place: str, tmp: str, wal: Path | None = None):
    """Every part of one file or embedded file: its hash, its raw bytes as Latin-1, then its type's parts. The type is
    decided by the bytes, never the extension."""
    yield "hash", place, hashlib.sha256(data).hexdigest()
    yield "text", f"{place}: raw bytes", data.decode("latin-1")
    if b"%PDF-" in data[:1024]:
        decoders = [_pdf]
    elif data.startswith(b"PK\x03\x04"):
        decoders = [_zip]
    elif data.startswith(b"SQLite format 3\0"):
        decoders = [_sqlite]
    else:
        decoders = [_image, _text]
    for decode in decoders:
        yield from _guard(place, decode(data, place, tmp, wal))


def _text(data, place, tmp, wal):
    """CSV and other text by its BOM (utf-8-sig default, as sheet._csv); HTML with tags removed; XML element text and
    attribute values; every data: URI decoded as its own file."""
    text = data.decode("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig", "replace")
    yield "text", f"{place}: text", text
    if text.lstrip().startswith("<"):
        yield "text", f"{place}: HTML text", TAG.sub("", text)
        try:
            tree = ElementTree.fromstring(data)
        except (ElementTree.ParseError, ValueError):
            tree = None
        if tree is not None:
            yield "text", f"{place}: XML", "\0".join(
                t for e in tree.iter() for t in ("".join(e.itertext()), *e.attrib.values()) if t)
    for i, m in enumerate(DATA_URI.finditer(html.unescape(text)), 1):
        yield from _guard(f"{place} > data URI {i}", _data_uri(m, f"{place} > data URI {i}", tmp))


def _data_uri(m, place, tmp):
    params, payload = m.groups()
    raw = base64.b64decode(payload + "=" * (-len(payload) % 4)) if params.endswith(";base64") else \
        urllib.parse.unquote_to_bytes(payload)
    yield from _blob(raw, place, tmp)


def _zip(data, place, tmp, wal):
    """Every member's name and bytes, each member decoded as its own type; a member that cannot be read is reported
    and the next one is read."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            where = f"{place} > {info.filename}"
            yield "text", f"{where}: member name", info.filename
            try:
                member = z.read(info)
            except Exception as e:  # noqa: BLE001
                yield _bad(where, e)
                continue
            yield from _blob(member, where, tmp)


def _pdf(data, place, tmp, wal):
    """The raw file's string tokens and every raw stream segment inflated (superseded and unreferenced objects
    included), then through pdfplumber: page text (also reversed), inline images, the metadata, and every object of
    every xref section. Each page, image and object is read on its own."""
    import pdfplumber

    yield "text", f"{place}: string tokens", _tokens(STREAM.sub(b"stream\nendstream", data))
    for i, m in enumerate(STREAM.finditer(data), 1):
        raw = _inflate(m[1])
        if raw is not None:
            yield "text", f"{place}: raw stream {i} string tokens", _tokens(raw)
            yield from _blob(raw, f"{place}: raw stream {i}", tmp)
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            where = f"{place}: page {n}"
            yield from _guard(f"{where} text", _page_text(page, where))
            try:
                inline = [im["stream"] for im in page.images if im["stream"].objid is None]  # not in the object table
            except Exception as e:  # noqa: BLE001
                yield _bad(f"{where} images", e)
                inline = []
            for k, stream in enumerate(inline, 1):
                yield from _guard(f"{where} inline image {k}", _pdf_image(stream, f"{where} inline image {k}"))
        yield from _guard(f"{place}: metadata", iter([("text", f"{place}: metadata",
                                                         "\0".join(map(str, pdf.metadata.values())))]))
        for x, xref in enumerate(pdf.doc.xrefs, 1):
            try:
                objids = list(xref.get_objids())
            except Exception as e:  # noqa: BLE001
                yield _bad(f"{place}: xref section {x}", e)
                continue
            for objid in objids:
                where = f"{place}: object {objid}"
                yield from _guard(where, _pdf_object(pdf.doc, objid, where, tmp))


def _page_text(page, where):
    text = page.extract_text() or ""
    yield "text", f"{where} text", text
    yield "text", f"{where} text reversed", text[::-1]  # bottom-to-top text comes out last character first


def _inflate(segment):
    """A raw stream segment inflated (Flate, or A85 then Flate as reportlab writes); None when it is neither."""
    segment = segment.rstrip(b"\r\n")
    for prepare in (lambda s: s, lambda s: base64.a85decode(s.strip().removesuffix(b"~>"))):
        try:
            return zlib.decompressobj().decompress(prepare(segment)) or None
        except (zlib.error, ValueError):
            continue
    return None


def _tokens(data: bytes) -> str:
    """Every literal (...) and hex <...> string in PDF bytes, escapes undone (octal included), UTF-16BE by its BOM."""
    strings, pos = [], 0
    while m := PDF_STRING.search(data, pos):
        if m[0] == b"(":
            s, pos = _literal(data, m.end())
        else:
            h = re.sub(rb"\s", b"", m[1])
            s, pos = bytes.fromhex((h + b"0" * (len(h) % 2)).decode()), m.end()
        strings.append(s[2:].decode("utf-16-be", "replace") if s[:2] == b"\xfe\xff" else s.decode("latin-1"))
    return "\0".join(strings)


def _literal(data, i):
    """The literal string starting after the "(" at i - 1, and the position after its ")"."""
    out, depth = bytearray(), 1
    while i < len(data):
        c, i = data[i], i + 1
        if c == 0x5C and i < len(data):  # backslash
            c, i = data[i], i + 1
            if 0x30 <= c <= 0x37:
                j = i - 1
                while i < len(data) and i < j + 3 and 0x30 <= data[i] <= 0x37:
                    i += 1
                out.append(int(data[j:i], 8) & 0xFF)
            elif c == 0x0D:  # line continuation
                i += data[i:i + 1] == b"\n"
            elif c != 0x0A:
                out.append(ESCAPES.get(c, c))
        elif c == 0x28:
            depth += 1
            out.append(c)
        elif c == 0x29:
            depth -= 1
            if not depth:
                return bytes(out), i
            out.append(c)
        else:
            out.append(c)
    return bytes(out), i


def _pdf_object(doc, objid, where, tmp):
    """One object: its strings and names; a stream decoded (an image to pixels; any other stream as its own file
    with its string tokens; a form or appearance stream, drawn or not, also interpreted for its text)."""
    from pdfminer.pdftypes import PDFStream, resolve1

    obj = doc.getobj(objid)
    yield "text", where, "\0".join(_pdf_strings(obj))
    if isinstance(obj, PDFStream):
        subtype = getattr(resolve1(obj.get("Subtype")), "name", None)
        if subtype == "Image":
            yield from _pdf_image(obj, f"{where} image")
            return
        data = obj.get_data()
        yield "text", f"{where} stream string tokens", _tokens(data)
        yield from _blob(data, f"{where} stream", tmp)
        if subtype == "Form" or "BBox" in obj.attrs:
            yield "text", f"{where} form text", _form_text(obj)


def _form_text(stream) -> str:
    """The text a form XObject or appearance stream would draw, interpreted with its own resources."""
    from pdfminer.converter import TextConverter
    from pdfminer.layout import LAParams
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdftypes import resolve1

    out, manager = io.StringIO(), PDFResourceManager()
    device = TextConverter(manager, out, laparams=LAParams())
    box = [float(v) for v in resolve1(stream.get("BBox"))] if stream.get("BBox") else [0, 0, 1000, 1000]
    page = SimpleNamespace(pageid=0, mediabox=box, cropbox=box, rotate=0)
    device.begin_page(page, (1, 0, 0, 1, 0, 0))
    PDFPageInterpreter(manager, device).render_contents(resolve1(stream.get("Resources")) or {}, [stream])
    device.end_page(page)
    return out.getvalue()


def _pdf_strings(obj):
    from pdfminer.pdftypes import PDFStream
    from pdfminer.psparser import PSLiteral
    from pdfminer.utils import decode_text

    if isinstance(obj, PDFStream):
        obj = obj.attrs
    if isinstance(obj, bytes):
        yield decode_text(obj)  # UTF-16BE with its BOM, else PDFDocEncoding
    elif isinstance(obj, PSLiteral):
        yield str(obj.name)  # a name, #-escapes undone
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _pdf_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _pdf_strings(v)


def _pdf_image(stream, where):
    """DCT and JPX data opened by Pillow; other data rebuilt from width, height and colour space (8-bit grey, RGB,
    CMYK and ICCBased, 1-bit masks). Any other image raises, so it is reported as unreadable."""
    from pdfminer.pdftypes import LITERALS_DCT_DECODE, LITERALS_JPX_DECODE, resolve1

    data = stream.get_data()
    if any(f in LITERALS_DCT_DECODE or f in LITERALS_JPX_DECODE for f, _ in stream.get_filters()):
        yield "image", where, Image.open(io.BytesIO(data))
        return
    a = {k: resolve1(v) for k, v in stream.attrs.items()}
    cs, bits = a.get("ColorSpace", a.get("CS")), a.get("BitsPerComponent", a.get("BPC"))
    if isinstance(cs, list) and getattr(cs[0], "name", None) == "ICCBased":
        mode = {1: "L", 3: "RGB", 4: "CMYK"}.get(resolve1(cs[1]).get("N"))
    else:
        mode = MODES.get(getattr(cs, "name", None))
    if a.get("ImageMask", a.get("IM")) is True or (mode == "L" and bits == 1):
        mode = "1"
    elif mode is None or bits != 8:
        raise ValueError(f"image colour space {cs!r} at {bits} bits is not decoded")
    yield "image", where, Image.frombytes(mode, (a.get("Width", a.get("W")), a.get("Height", a.get("H"))), data)


def _sqlite(data, place, tmp, wal):
    """The -wal's raw bytes, and iterdump() of a copy of the database and its -wal made in tmp (the copy merges the
    WAL); nothing is opened in the scanned path."""
    folder = Path(tempfile.mkdtemp(dir=tmp))
    (folder / "copy.db").write_bytes(data)
    if wal is not None and wal.is_file():
        w = wal.read_bytes()
        yield "text", f"{place}: -wal raw bytes", w.decode("latin-1")
        (folder / "copy.db-wal").write_bytes(w)
    con = sqlite3.connect(folder / "copy.db")
    try:
        dump = "\n".join(con.iterdump())
    finally:
        con.close()
    yield "text", f"{place}: database dump", dump


def _image(data, place, tmp, wal):
    """Any image Pillow recognises by its bytes, every frame."""
    try:
        img = Image.open(io.BytesIO(data), formats=SIGNED)
    except UnidentifiedImageError:
        return
    for i, frame in enumerate(ImageSequence.Iterator(img)):
        yield "image", place if i == 0 else f"{place} frame {i + 1}", frame.copy()
