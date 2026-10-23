"""Story 7.7 part A: the leakage scanner. found(path, seeds) looks for every seed inside output files the way an
outsider would, from the files alone: raw bytes, decoded text (JSON, CSV, HTML, XML inside zips, PDF text, metadata
and every PDF object) and decoded images (exact pixel hash and the marker colour). It reads the path and writes
nothing there; SQLite copies go to a temporary folder outside it. Test code only."""
import base64
import hashlib
import html
import io
import json
import re
import sqlite3
import tempfile
import urllib.parse
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image, ImageChops

MARKER, TOLERANCE, MIN_PIXELS = (0, 200, 120), 8, 50  # 7.1 G: the private-image marker colour
TEXT_KINDS = {"document text", "contributor", "credential", "path"}
SAFE = re.compile(r"[A-Za-z0-9-]+")
DIGEST = re.compile(r"[0-9a-fA-F]{64}")
DATA_URI = re.compile(r"data:([^,\"'\s<>]*),([^\"'\s<>]*)")
MODES = {"DeviceRGB": "RGB", "RGB": "RGB", "DeviceGray": "L", "G": "L", "DeviceCMYK": "CMYK", "CMYK": "CMYK"}


def found(path, seeds) -> dict:
    """{seed name: [place]} for every seed found under path (a file or a folder); seeds not found are left out."""
    texts, digests, images = _check(seeds)
    root = Path(path)
    files = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root]
    hits = {}
    with tempfile.TemporaryDirectory() as tmp:
        assert not Path(tmp).resolve().is_relative_to(root.resolve()), "the temporary folder is inside the scanned path"
        for p in files:
            rel = p.relative_to(root).as_posix() if root.is_dir() else p.name
            parts = [("text", f"{rel}: path", rel), *_blob(p.read_bytes(), rel, tmp, p.with_name(p.name + "-wal"))]
            for kind, place, part in parts:
                for name, where in _match(kind, place, part, texts, digests, images):
                    hits.setdefault(name, set()).add(where)
    return {name: sorted(places) for name, places in hits.items()}


def _check(seeds):
    """Seed hygiene (section 3): text seeds use [A-Za-z0-9-] only, hex digests are exempt, no value is a substring of
    another. Returns the text seeds [(name, casefolded value)], {digest: [name]} and the image seed names."""
    names = [s["name"] for s in seeds]
    if len(set(names)) != len(names):
        raise ValueError("seed names repeat")
    texts, digests, images, values = [], {}, [], []
    for s in seeds:
        kind, name, value = s["kind"].replace("_", " ").replace("-", " "), s["name"], s.get("value")
        if kind in TEXT_KINDS:
            if not isinstance(value, str) or not SAFE.fullmatch(value):
                raise ValueError(f"seed {name}: a text seed uses only A-Z, a-z, 0-9 and -")
            texts.append((name, value.casefold()))
        elif kind == "file hash":
            if not isinstance(value, str) or not DIGEST.fullmatch(value):
                raise ValueError(f"seed {name}: a file hash is a sha256 hex digest")
            texts.append((name, value.casefold()))
            digests.setdefault(value.lower(), []).append(name)
        elif kind == "image":
            # render_sha256 is a stored image file's hash; a hex value is the decoded RGB hash part B passes in. Any
            # other value (7.1 may describe the marker colour there) is not searched: the marker is checked always.
            render = s.get("render_sha256")
            if render is not None and not (isinstance(render, str) and DIGEST.fullmatch(render)):
                raise ValueError(f"seed {name}: render_sha256 is a sha256 hex digest")
            for d in (render, value):
                if isinstance(d, str) and DIGEST.fullmatch(d):
                    digests.setdefault(d.lower(), []).append(name)
                    values.append((name, d.casefold()))
            images.append(name)
            continue
        else:
            raise ValueError(f"seed {name}: unknown kind {s['kind']!r}")
        values.append((name, value.casefold()))
    for a, va in values:
        for b, vb in values:
            if a != b and va in vb:
                raise ValueError(f"seed {a}'s value is inside seed {b}'s")
    return texts, digests, images


def _match(kind, place, part, texts, digests, images):
    if kind == "text":
        # As is, case-folded and with white space removed in one search: seeds are ASCII with no white space.
        hay = "".join(part.casefold().split())
        yield from ((name, place) for name, v in texts if v in hay)
    elif kind == "hash":
        yield from ((name, f"{place}: file hash") for name in digests.get(part, ()))
    else:
        rgb = part.convert("RGB")
        yield from ((name, f"{place}: pixel hash") for name in digests.get(hashlib.sha256(rgb.tobytes()).hexdigest(), ()))
        if images and _marker(rgb):
            yield from ((name, f"{place}: marker colour") for name in images)


def _marker(rgb) -> bool:
    """At least MIN_PIXELS pixels within TOLERANCE of MARKER in every channel."""
    r, g, b = (band.point(lambda v, c=c: 255 if abs(v - c) <= TOLERANCE else 0) for band, c in zip(rgb.split(), MARKER))
    return ImageChops.multiply(ImageChops.multiply(r, g), b).histogram()[255] >= MIN_PIXELS


def _blob(data: bytes, place: str, tmp: str, wal: Path | None = None):
    """Every part of one file or embedded file: its hash, its raw bytes as Latin-1, then its type's parts. The type is
    decided by the first bytes, never the extension."""
    yield "hash", place, hashlib.sha256(data).hexdigest()
    yield "text", f"{place}: raw bytes", data.decode("latin-1")
    decode = next((d for magic, d in DECODERS if data.startswith(magic)), _text)
    try:
        yield from decode(data, place, tmp, wal)
    except Exception:  # noqa: BLE001
        # ponytail: a file its decoder cannot read is left to its raw bytes; part B's injected-row check is what fails
        # a format the scanner cannot read.
        pass


def _text(data, place, tmp, wal):
    """CSV and other text by its BOM (utf-8-sig default, as sheet._csv), JSON strings, HTML or XML unescaped and parsed,
    and every data: URI decoded as its own file."""
    text = data.decode("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig", "replace")
    yield "text", f"{place}: text", text
    try:
        yield "text", f"{place}: JSON strings", "\0".join(_strings(json.loads(text)))
    except ValueError:
        pass
    if text.lstrip().startswith("<"):
        text = html.unescape(text)
        yield "text", f"{place}: unescaped", text
        try:
            tree = ElementTree.fromstring(data)
            yield "text", f"{place}: XML", "\0".join(
                t for e in tree.iter() for t in (e.text, e.tail, *e.attrib.values()) if t)
        except ElementTree.ParseError:
            pass
    for i, m in enumerate(DATA_URI.finditer(text), 1):
        params, payload = m.groups()
        raw = base64.b64decode(payload + "=" * (-len(payload) % 4)) if params.endswith(";base64") else \
            urllib.parse.unquote_to_bytes(payload)
        yield from _blob(raw, f"{place} > data URI {i}", tmp)


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _zip(data, place, tmp, wal):
    """Every member's name and bytes; each member is decoded as its own type (XML, nested zip, PDF, image, database)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            yield "text", f"{place} > {info.filename}: member name", info.filename
            yield from _blob(z.read(info), f"{place} > {info.filename}", tmp)


def _pdf(data, place, tmp, wal):
    """extract_text() per page, the metadata, every string and decoded stream of every object in every xref section
    (used or not), every image XObject and every inline image decoded to pixels."""
    import pdfplumber
    from pdfminer.pdftypes import PDFStream, resolve1

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            yield "text", f"{place}: page {n} text", page.extract_text() or ""
            for im in page.images:
                if im["stream"].objid is None:  # inline: not in the object table
                    yield from _pdf_image(im["stream"], f"{place}: page {n} inline image")
        yield "text", f"{place}: metadata", "\0".join(map(str, pdf.metadata.values()))
        for xref in pdf.doc.xrefs:
            for objid in xref.get_objids():
                try:
                    obj = pdf.doc.getobj(objid)
                except Exception:  # noqa: BLE001 (a free or broken entry)
                    continue
                where = f"{place}: object {objid}"
                yield "text", where, "\0".join(_pdf_strings(obj))
                if isinstance(obj, PDFStream):
                    if getattr(resolve1(obj.get("Subtype")), "name", None) == "Image":
                        yield from _pdf_image(obj, f"{where} image")
                    else:
                        yield from _blob(obj.get_data(), f"{where} stream", tmp)


def _pdf_strings(obj):
    from pdfminer.pdftypes import PDFStream
    from pdfminer.psparser import PSLiteral
    from pdfminer.utils import decode_text

    if isinstance(obj, PDFStream):
        obj = obj.attrs
    if isinstance(obj, bytes):
        yield decode_text(obj)  # UTF-16BE with its BOM, else PDFDocEncoding
    elif isinstance(obj, PSLiteral):
        yield str(obj.name)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _pdf_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _pdf_strings(v)


def _pdf_image(stream, where):
    """DCT and JPX data opened by Pillow; other data rebuilt from width, height and colour space."""
    from pdfminer.pdftypes import LITERALS_DCT_DECODE, LITERALS_JPX_DECODE, resolve1

    data = stream.get_data()
    if any(f in LITERALS_DCT_DECODE or f in LITERALS_JPX_DECODE for f, _ in stream.get_filters()):
        yield "image", where, Image.open(io.BytesIO(data))
        return
    a = {k: resolve1(v) for k, v in stream.attrs.items()}
    cs = a.get("ColorSpace", a.get("CS"))
    if isinstance(cs, list) and getattr(cs[0], "name", None) == "ICCBased":
        mode = {1: "L", 3: "RGB", 4: "CMYK"}.get(resolve1(cs[1]).get("N"))
    else:
        mode = MODES.get(getattr(cs, "name", None))
    # ponytail: 8-bit grey, RGB and CMYK only; indexed and 1-bit images are left to their raw bytes.
    if mode and a.get("BitsPerComponent", a.get("BPC")) == 8:
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
    img = Image.open(io.BytesIO(data))
    img.load()
    yield "image", place, img


DECODERS = ((b"%PDF-", _pdf), (b"PK\x03\x04", _zip), (b"SQLite format 3\0", _sqlite),
            (b"\x89PNG\r\n\x1a\n", _image), (b"\xff\xd8\xff", _image))
