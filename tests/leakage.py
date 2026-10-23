"""Story 7.7 part A: the leakage scanner. found(path, seeds) looks for every seed inside output files the way an
outsider would, from the files alone: raw bytes, decoded text (CSV and text by BOM, HTML with tags removed, XML
element text inside zips, PDF page text, metadata, every PDF object and string token, superseded and unlisted PDF
objects, undrawn form and appearance streams) and decoded images (exact pixel hash and the marker colour). Every text
part is also searched with \\u escapes and HTML entities undone and with soft hyphens and zero-width characters
dropped. It reads the path and writes nothing there; SQLite copies go to a temporary folder outside it.

Loud by design: a symbolic link under the path is refused, and a part the scanner cannot read (a broken object, zip
member, image or database) does not stop the rest of the scan; at the end found raises Unreadable naming every such
place, so it never returns a result for a scan that skipped a part. Only bytes with a strong image signature (PNG,
JPEG, GIF, WebP, TIFF) are opened as images (ones that do not decode are text if UTF-8, else unreadable), and a PDF
stream's decoded data never is; object stream members are read as objects. found returns {name: [places]} for the
seeds it finds: a hex image seed by exact pixel hash only, and a marker-colour hit only under the image seeds whose
value is None (7.1 G). parts(path) gives the same parts for checks that are not seeds.

Known ceilings (not decoded; recorded in the TASK-0224 worker notes): 16-bit PDF images, colour spaces other
than device, ICCBased and Indexed over those, and DCT or JPX data with a non-default /Decode (reported as
unreadable, so a scan meeting one raises); UTF-16LE text without a BOM; free-page overflow chains and UTF-16
databases (only the dump and raw bytes are searched); a marker under MIN_PIXELS pixels, so a private crop's marker
rectangle must stay above about 7 by 7 pixels at the smallest scale a renderer draws it. Test code only."""
import base64
import bisect
import contextlib
import hashlib
import html
import io
import os
import re
import sqlite3
import tempfile
import urllib.parse
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

from PIL import Image, ImageChops, ImageSequence

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
PDF_STRING = re.compile(rb"%[^\r\n]*|\(|(?<!<)<([0-9A-Fa-f\s]*)>")
OBJECT = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b")  # an object header anywhere in the file
ESCAPES = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
MODES = {"DeviceRGB": "RGB", "RGB": "RGB", "DeviceGray": "L", "G": "L", "DeviceCMYK": "CMYK", "CMYK": "CMYK"}
IMAGE_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"II*\0", b"MM\0*")  # and RIFF WEBP


class Unreadable(Exception):
    """Raised by found after the whole scan when any part could not be read; .places names them, .found holds what
    the rest of the scan found."""

    def __init__(self, places, result):
        super().__init__("the scan could not read: " + "; ".join(places))
        self.places, self.found = places, result


def found(path, seeds) -> dict:
    """{seed name: [place]} for every seed found under path (a file or a folder); seeds not found are left out."""
    texts, digests, images = _check(seeds)
    hits, unreadable = {}, []
    for kind, place, part in _scan(path):
        if kind == "unreadable":
            unreadable.append(f"{place} ({part})")
        for name, where in _match(kind, place, part, texts, digests, images):
            hits.setdefault(name, set()).add(where)
    result = {name: sorted(places) for name, places in hits.items()}
    if unreadable:
        raise Unreadable(unreadable, result)
    return result


def parts(path) -> list[tuple[str, str, str]]:
    """Every part found reads under path, as (kind, place, value): "text" with its text, "hash" with the file's
    sha256, "image" with the sha256 of its decoded RGB pixels. For the checks that are not seeds (a path pattern, a
    sentence, a mark) and for comparing two outputs part by part. Raises Unreadable as found does."""
    out, unreadable = [], []
    for kind, place, part in _scan(path):
        if kind == "unreadable":
            unreadable.append(f"{place} ({part})")
        else:
            out.append((kind, place, hashlib.sha256(part.convert("RGB").tobytes()).hexdigest()
                        if kind == "image" else part))
    if unreadable:
        raise Unreadable(unreadable, out)
    return out


def _scan(path):
    """(kind, place, part) of every file under path: its relative path as text, then _blob's parts."""
    root = Path(path)
    links = [root] if root.is_symlink() else [
        Path(d, n) for d, dirs, names in os.walk(root) for n in dirs + names if Path(d, n).is_symlink()]
    if links:
        raise ValueError("symbolic links under the scanned path: " + ", ".join(map(str, links)))
    files = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root]
    with tempfile.TemporaryDirectory() as tmp:
        assert not Path(tmp).resolve().is_relative_to(root.resolve()), "the temporary folder is inside the scanned path"
        for p in files:
            rel = p.relative_to(root).as_posix() if root.is_dir() else p.name
            yield "text", f"{rel}: path", rel
            yield from _blob(p.read_bytes(), rel, tmp, p.with_name(p.name + "-wal"))


def _check(seeds):
    """Seed hygiene (section 3): kinds are 7.1 G's six tokens, text seeds use [A-Za-z0-9-] only, digests are sha256
    hex (exempt from the charset), no value is a substring of another. Returns the text seeds [(name, casefolded
    value)], {digest: [name]} and the names of the image seeds whose value is None (the marker seeds)."""
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
            if value is None:  # 7.1 G: a marker hit is reported only under an image seed whose value is None
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


def _blob(data: bytes, place: str, tmp: str, wal: Path | None = None, typed=True):
    """Every part of one file or embedded file: its hash, its raw bytes as Latin-1, then its type's parts. The type is
    decided by the bytes, never the extension. A PDF stream's decoded data (typed=False) is only ever text: pixel
    bytes can begin with any file signature."""
    yield "hash", place, hashlib.sha256(data).hexdigest()
    yield "text", f"{place}: raw bytes", data.decode("latin-1")
    if not typed:
        decoders = [_text]
    elif b"%PDF-" in data[:1024]:
        decoders = [_pdf]
    elif data.startswith(b"PK\x03\x04"):
        decoders = [_zip]
    elif data.startswith(b"SQLite format 3\0"):
        decoders = [_sqlite]
    elif data.startswith(IMAGE_SIGNATURES) or data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        decoders = [_image]
    else:
        decoders = [_text]
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
    """The raw file's string tokens (stream data blanked, comments skipped), then through pdfplumber: page text (also
    reversed), inline images, the metadata, every object of every xref section, and every other object body in the
    file (a copy an incremental update superseded, or one no xref section lists), each parsed as an object at its
    byte position. A listed id is skipped only when proven free: every xref section listing it marks it free, no
    header for it is in the file and no object stream holds it; any other id getobj cannot read is unreadable. An
    inline image's empty filter array is read as no filter (_empty_inline_filters). Each part is read on its own."""
    import pdfplumber

    streams = [m.span(1) for m in STREAM.finditer(data)]  # stream data, blanked below with its length kept
    strings = list(_strings(STREAM.sub(lambda m: m[0][:m.start(1) - m.start()] + b" " * len(m[1]) + b"endstream", data)))
    yield "text", f"{place}: string tokens", _tokens(strings)
    with _empty_inline_filters(), pdfplumber.open(io.BytesIO(data)) as pdf:
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
        live, doc, resources = set(), pdf.doc, {}  # (objid, byte position) of the copy getobj returns
        try:  # content stream objid -> its page's resources, to interpret a superseded copy of a page's content
            for page in pdf.pages:
                refs = page.page_obj.attrs.get("Contents")
                for ref in refs if isinstance(refs, list) else [refs]:
                    resources.setdefault(getattr(ref, "objid", None), page.page_obj.resources)
        except Exception as e:  # noqa: BLE001
            yield _bad(f"{place}: page resources", e)
        members, free = set(), []  # object stream members read in either pass; listed ids every section marks free
        for x, xref in enumerate(doc.xrefs, 1):
            try:
                objids = list(xref.get_objids())
            except Exception as e:  # noqa: BLE001
                yield _bad(f"{place}: xref section {x}", e)
                continue
            for objid in objids:
                if _marked_free(doc, objid):
                    free.append(objid)
                    continue
                where = f"{place}: object {objid}"
                yield from _guard(where, _pdf_object(doc, lambda objid=objid: doc.getobj(objid), where, tmp,
                                                     members=members))
                live |= {(objid, _newest_pos(doc, objid))}
        spans = [a[:2] for a in strings]  # strings and comments
        headers = set()
        for m in OBJECT.finditer(data):
            objid, pos = int(m[1]), m.start(1)
            if _inside(streams, pos) or _inside(spans, pos):  # not a header
                continue
            headers.add(objid)
            if (objid, pos) in live:  # the live copy
                continue
            where = f"{place}: object {objid} at byte {pos}"
            yield from _guard(where, _pdf_object(doc, lambda m=m: _parse_at(doc, m), where, tmp, resources.get(objid),
                                                 members=members))
        for objid in dict.fromkeys(free):  # skipped only when proven free: no header and in no object stream
            if objid in headers or objid in members:
                where = f"{place}: object {objid}"
                yield from _guard(where, _pdf_object(doc, lambda objid=objid: doc.getobj(objid), where, tmp))


def _marked_free(doc, objid) -> bool:
    """Every xref section that lists objid marks it free, and one does (an xref stream entry of type 0). pdfminer's
    PDFXRefStream.get_objids reads each /Index range's entries from the start of the stream data, so it can list an
    id whose own entry is free, and getobj then raises PDFObjectNotFound. An xref table holds only its in-use entries
    to pdfminer, so a table listing objid marks it in use."""
    from pdfminer.pdfdocument import PDFXRefStream

    marked = False
    for xref in doc.xrefs:
        if not isinstance(xref, PDFXRefStream):
            if objid in xref.get_objids():
                return False
            continue
        index = 0
        for start, n in xref.ranges:
            if start <= objid < start + n:
                entry = xref.data[xref.entlen * (index + objid - start):][:xref.entlen]
                kind = int.from_bytes(entry[:xref.fl1], "big") if xref.fl1 else 1  # no type field: in use
                if kind != 0:
                    return False
                marked = True
                break
            index += n
    return marked


def _newest_pos(doc, objid):
    """The byte position of the copy getobj returns (the first xref section listing it), None in an object stream."""
    for xref in doc.xrefs:
        try:
            strmid, index, _ = xref.get_pos(objid)
        except KeyError:
            continue
        return None if strmid is not None else index


def _parse_at(doc, m):
    """The object whose "N G obj" header starts at m, parsed as pdfminer parses a listed one."""
    from pdfminer.pdftypes import PDFStream

    obj = doc._getobj_parse(m.start(1), int(m[1]))  # the reviewer's route: pdfminer has no public call for it
    if isinstance(obj, PDFStream):
        obj.set_objid(int(m[1]), int(m[2]))
    return obj


def _page_text(page, where):
    text = page.extract_text() or ""
    yield "text", f"{where} text", text
    yield "text", f"{where} text reversed", text[::-1]  # bottom-to-top text comes out last character first


def _inside(spans, pos) -> bool:
    """True when pos falls in one of spans, sorted (start, end) pairs that do not overlap."""
    k = bisect.bisect_right(spans, (pos, float("inf"))) - 1
    return k >= 0 and pos < spans[k][1]


def _strings(data: bytes):
    """(start, end, bytes) of every literal (...) and hex <...> string in PDF bytes, escapes undone (octal included),
    and (start, end, None) of every % comment outside a string (its "(" opens nothing); an odd-length hex string gets
    its final 0; an unclosed "(" spans only itself, so the bytes after it are still read."""
    pos = 0
    while m := PDF_STRING.search(data, pos):
        if m[0][:1] == b"%":
            yield m.start(), m.end(), None
            pos = m.end()
            continue
        if m[0] == b"(":
            s, end = _literal(data, m.end())
            pos = m.end() if end is None else end
        else:
            h = re.sub(rb"\s", b"", m[1])
            s, pos = bytes.fromhex((h + b"0" * (len(h) % 2)).decode()), m.end()
        yield m.start(), pos, s


def _tokens(strings) -> str:
    """The strings of _strings, UTF-16BE by its BOM, else Latin-1."""
    return "\0".join(s[2:].decode("utf-16-be", "replace") if s[:2] == b"\xfe\xff" else s.decode("latin-1")
                     for _, _, s in strings if s is not None)


def _literal(data, i):
    """The literal string starting after the "(" at i - 1, and the position after its ")" (None when unclosed)."""
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
    return bytes(out), None


def _pdf_object(doc, get, where, tmp, resources=None, members=None):
    """One object of doc (get() reads it): its strings and names; a stream decoded (an image to pixels; an embedded
    file as its own file; any other stream as text with its string tokens; a form or appearance stream, drawn or not,
    and a superseded page content stream with its page's resources, also interpreted for text and inline images; an
    object stream's members each as an object)."""
    from pdfminer.pdftypes import PDFStream, resolve1

    obj = get()
    yield "text", where, "\0".join(_pdf_strings(obj))
    if isinstance(obj, PDFStream):
        subtype = getattr(resolve1(obj.get("Subtype")), "name", None)
        if subtype == "Image":
            yield from _pdf_image(obj, f"{where} image")
            return
        data = obj.get_data()
        yield "text", f"{where} stream string tokens", _tokens(_strings(data))
        kind = getattr(resolve1(obj.get("Type")), "name", None)
        yield from _blob(data, f"{where} stream", tmp, typed=kind == "EmbeddedFile")
        if subtype == "Form" or "BBox" in obj.attrs or resources is not None:
            yield from _form(obj, where, resources)
        if kind == "ObjStm":  # its members, current or superseded, parsed as pdfminer parses them
            objs, n = doc._get_objects(obj)  # pdfminer's own member parse: it has no public call for it
            if members is not None:
                members.update(objs[:2 * n:2])
            for objid, member in zip(objs[:2 * n:2], objs[2 * n:]):
                yield from _pdf_object(doc, lambda member=member: member, f"{where} member {objid}", tmp)


@contextlib.contextmanager
def _empty_inline_filters():
    """While interpreting: an inline image's empty filter array (/F [] or /Filter [], no filter) is dropped before
    pdfminer reads its dictionary, as its PDFContentParser.do_keyword indexes filter[0] and raises IndexError on it."""
    from pdfminer import pdfinterp
    from pdfminer.psparser import literal_name

    class Parser(pdfinterp.PDFContentParser):
        def do_keyword(self, pos, token):
            if token is self.KEYWORD_ID and self.curtype == "inline":
                if len(self.curstack) % 2 == 0:  # else pdfminer's own "Invalid dictionary construct" error
                    pairs = zip(self.curstack[::2], self.curstack[1::2])
                    self.curstack = [x for k, v in pairs if not (v[1] == [] and literal_name(k[1]) in ("F", "Filter"))
                                     for x in (k, v)]
            super().do_keyword(pos, token)

    pdfinterp.PDFContentParser, original = Parser, pdfinterp.PDFContentParser
    try:
        yield
    finally:
        pdfinterp.PDFContentParser = original


def _form(stream, where, resources=None):
    """The text and inline images a stream would draw, interpreted with resources (by default its own: a form
    XObject or appearance stream)."""
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import LAParams, LTContainer, LTImage, LTTextContainer
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdftypes import resolve1

    manager = PDFResourceManager()
    device = PDFPageAggregator(manager, laparams=LAParams())
    box = [float(v) for v in resolve1(stream.get("BBox"))] if stream.get("BBox") else [0, 0, 1000, 1000]
    page = SimpleNamespace(pageid=0, mediabox=box, cropbox=box, rotate=0)
    device.begin_page(page, (1, 0, 0, 1, 0, 0))
    own = resolve1(stream.get("Resources")) or {}
    PDFPageInterpreter(manager, device).render_contents(own if resources is None else resources, [stream])
    device.end_page(page)
    texts, inline = [], []

    def walk(item):
        if isinstance(item, LTTextContainer):
            texts.append(item.get_text())
        elif isinstance(item, LTImage):
            inline.extend([item.stream] if item.stream.objid is None else [])  # a drawn XObject is its own object
        elif isinstance(item, LTContainer):
            for child in item:
                walk(child)

    walk(device.get_result())
    yield "text", f"{where} form text", "\n".join(texts)
    for k, s in enumerate(inline, 1):
        yield from _guard(f"{where} form inline image {k}", _pdf_image(s, f"{where} form inline image {k}"))


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
    CMYK and ICCBased, 1-bit masks, and Indexed over one of those at 1, 2, 4 or 8 bits), each through its /Decode
    array when it has one (an Indexed image's maps samples to indices). Any other image or Decode raises, so it is
    reported as unreadable; DCT and JPX data with a Decode array other than the default raise too (Pillow's reading
    of an Adobe CMYK JPEG already inverts it, so a Decode on top is not known to draw as a renderer would)."""
    from pdfminer.pdftypes import LITERALS_DCT_DECODE, LITERALS_JPX_DECODE, resolve1

    data = stream.get_data()
    a = {k: resolve1(v) for k, v in stream.attrs.items()}
    if any(f in LITERALS_DCT_DECODE or f in LITERALS_JPX_DECODE for f, _ in stream.get_filters()):
        image = Image.open(io.BytesIO(data))
        decode = a.get("Decode", a.get("D"))
        if decode is not None and [resolve1(x) for x in decode] != [0, 1] * len(image.mode):
            raise ValueError(f"image Decode {decode!r} on DCT or JPX data is not decoded")
        yield "image", where, image
        return
    cs, bits = a.get("ColorSpace", a.get("CS")), a.get("BitsPerComponent", a.get("BPC"))
    size = (a.get("Width", a.get("W")), a.get("Height", a.get("H")))
    if isinstance(cs, list) and getattr(cs[0], "name", None) in ("Indexed", "I"):
        yield "image", where, _indexed(cs, bits, size, data, a.get("Decode", a.get("D")))
        return
    mode = _mode(cs)
    if a.get("ImageMask", a.get("IM")) is True or (mode == "L" and bits == 1):
        mode = "1"
    elif mode is None or bits != 8:
        raise ValueError(f"image colour space {cs!r} at {bits} bits is not decoded")
    image = Image.frombytes(mode, size, data)
    decode = a.get("Decode", a.get("D"))
    if decode is not None:  # each component through its [Dmin Dmax] range, as a renderer draws it (clipped to 0-1)
        tables = _decode(decode, 1 if mode == "1" else 8, 1 if mode == "1" else len(mode))
        if mode == "1":  # Pillow holds the two samples as 0 and 255
            image, tables = image.convert("L"), [[t[v >= 128] for v in range(256)] for t in tables]
        image = image.point([round(min(max(v, 0), 1) * 255) for t in tables for v in t])
    yield "image", where, image


def _mode(cs):
    """The Pillow mode of a device or ICCBased colour space, None for any other."""
    from pdfminer.pdftypes import resolve1

    cs = resolve1(cs)
    if isinstance(cs, list) and getattr(cs[0], "name", None) == "ICCBased":
        return {1: "L", 3: "RGB", 4: "CMYK"}.get(resolve1(cs[1]).get("N"))
    return MODES.get(getattr(cs, "name", None))


def _indexed(cs, bits, size, data, decode=None):
    """An Indexed image ([/Indexed base hival lookup], 1, 2, 4 or 8 bits) as the image of its base colour space whose
    pixels are the palette entries its indices pick, so it hashes as that direct image would; a Decode array maps
    each sample to its index first, accepted only when every possible sample maps to a whole index in 0 to hival
    (the default and its reverse, for example). An index above hival, any other Decode or a lookup shorter than its
    entries raises."""
    from pdfminer.pdftypes import PDFStream, resolve1

    base, hival, lookup = _mode(cs[1]), resolve1(cs[2]), resolve1(cs[3])
    lookup = lookup.get_data() if isinstance(lookup, PDFStream) else lookup
    lookup = lookup.encode("latin-1") if isinstance(lookup, str) else lookup
    if base is None or bits not in (1, 2, 4, 8) or not isinstance(lookup, bytes):
        raise ValueError(f"image colour space {cs!r} at {bits} bits is not decoded")
    n = len(base)  # components per palette entry: L 1, RGB 3, CMYK 4
    if len(lookup) < (hival + 1) * n:
        raise ValueError(f"Indexed lookup holds {len(lookup)} bytes, fewer than {(hival + 1) * n}")
    indices = Image.frombytes("P", size, data, "raw", "P" if bits == 8 else f"P;{bits}").tobytes()
    if decode is not None:  # each sample to its index, before the palette
        decoded = _decode(decode, bits, 1)[0]
        # Fail closed: readers round a fractional index differently (Codex fix check 1: Poppler and PDFium disagree
        # on [0.5 0.5]), so every possible sample must decode to a whole index in 0 to hival.
        if not all(float(v).is_integer() and 0 <= v <= hival for v in decoded):
            raise ValueError(f"Indexed image Decode {decode!r} does not map every sample to a whole index in 0 to"
                             f" hival {hival}")
        index = [int(v) for v in decoded]
        indices = indices.translate(bytes(i if 0 <= i <= hival else 0 for i in index + [0] * (256 - len(index))))
    if max(indices, default=0) > hival:
        raise ValueError(f"Indexed image index {max(indices)} above hival {hival}")
    planes = [Image.frombytes("L", size, indices.translate(bytes(lookup[i * n + k] if i <= hival else 0
                                                                for i in range(256)))) for k in range(n)]
    return Image.merge(base, planes)


def _decode(decode, bits, n):
    """Per component, the value each sample s (0 to 2 ** bits - 1) decodes to under a Decode array of n [Dmin Dmax]
    pairs: Dmin + s * (Dmax - Dmin) / (2 ** bits - 1), a colour component from 0 to 1 or an Indexed index. Any other
    Decode (wrong length, not numbers) raises, so the image is unreadable."""
    from pdfminer.pdftypes import resolve1

    d = [resolve1(x) for x in decode] if isinstance(decode, list) else None
    if d is None or len(d) != 2 * n or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in d):
        raise ValueError(f"image Decode {decode!r} is not decoded")
    last = 2 ** bits - 1
    return [[d[2 * k] + s * (d[2 * k + 1] - d[2 * k]) / last for s in range(last + 1)] for k in range(n)]


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
    """A PNG, JPEG, GIF, WebP or TIFF file (strong signature), every frame; one that does not decode is text when it
    decodes as UTF-8 ("GIF89a is a format"), else it raises, so it is reported as unreadable."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise e from None  # not text either: the image error is reported
        yield from _text(data, place, tmp, wal)
        return
    for i, frame in enumerate(ImageSequence.Iterator(img)):
        yield "image", place if i == 0 else f"{place} frame {i + 1}", frame.copy()
