"""Story 7.7 part A: the leakage scanner's self-tests (section 5, ACs 1 to 5). Every file is planted by hand in the test,
with a distinct seed in each hiding place, and its negative twin (the same builder with shareable strings and grey
images) reports nothing. Seeds are in 7.1 G's shape {name, kind, expect, value}; report_fixture.SEEDS is part B's."""
import base64
import codecs
import hashlib
import io
import json
import sqlite3
import zipfile
import zlib

import pypdfium2 as pdfium
import pytest
from PIL import Image

from leakage import MARKER, Unreadable, found
from pdf_layouts import pdf as text_pdf
from test_deletion import scan  # the 4.5 raw byte search

KEYS = ("pdftext", "pdfsplit", "title", "uri", "outline", "unused", "shared", "inline", "sheet", "core", "comment",
        "csv", "case", "json", "entity", "datajson", "row", "index", "wal", "name", "dir", "nested", "dot", "incoming",
        "utf16")
V = {k: f"GCT-LEAK-SCAN-{k.upper()}-{i:02}" for i, k in enumerate(KEYS, 1)}
V["case"] = "GCT-Leak-Scan-Case-13"  # printed upper case
SHAREABLE = {k: f"Shareable-{k}-00" for k in KEYS}
GREY = (128, 128, 128)


def crop(size, flip=False):
    """A lossless crop stand-in: a grey gradient (never near the marker)."""
    img = Image.linear_gradient("L").resize(size).convert("RGB")
    return img.transpose(Image.Transpose.FLIP_TOP_BOTTOM) if flip else img


def picture(colour, size=(40, 40)):
    return Image.new("RGB", size, colour)


def png(img) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def jpeg(img) -> bytes:
    out = io.BytesIO()
    img.save(out, "JPEG", quality=95)
    return out.getvalue()


def pixels(img) -> str:
    return hashlib.sha256(img.convert("RGB").tobytes()).hexdigest()


def text_seed(value, kind="document_text"):
    return {"name": value, "kind": kind, "expect": "complete_only", "value": value}


CROP_A, CROP_B, RENDER, HASHED = crop((30, 20)), crop((24, 18)), png(picture(GREY, (30, 30))), b"shareable bytes\n"
SEEDS = [text_seed(v) for v in V.values()] + [
    {"name": "GCT-LEAK-SCAN-HASH-25", "kind": "file_hash", "expect": "complete_only",
     "value": hashlib.sha256(HASHED).hexdigest()},
    {"name": "GCT-LEAK-SCAN-CROPA-26", "kind": "image", "expect": "complete_only", "value": pixels(CROP_A)},
    {"name": "GCT-LEAK-SCAN-CROPB-27", "kind": "image", "expect": "complete_only", "value": pixels(CROP_B)},
    {"name": "GCT-LEAK-SCAN-RENDER-28", "kind": "image", "expect": "complete_only", "value": None,
     "render_sha256": hashlib.sha256(RENDER).hexdigest()},
]
IMAGES = [s["name"] for s in SEEDS if s["kind"] == "image"]


# --- hand-written files ----------------------------------------------------------------------------------------------

def _stream(attrs: bytes, data: bytes) -> bytes:
    return b"<< %s /Length %d >>\nstream\n" % (attrs, len(data)) + data + b"\nendstream"


def _a85(data: bytes) -> bytes:
    return base64.a85encode(data) + b"~>"  # as reportlab writes it: no <~ prefix


def _utf16(s: str) -> bytes:
    return b"<" + (codecs.BOM_UTF16_BE + s.encode("utf-16-be")).hex().upper().encode() + b">"


def hand_pdf(v, mark, crop_a, crop_b) -> bytes:
    """Objects: 1 catalog, 2 pages, 3 page, 4 content (A85 and Flate), 5 font, 6 Flate image, 7 A85 and Flate image,
    8 DCT image, 9 link annotation (hex URI), 10 outlines, 11 outline item (UTF-16BE title), 12 info (UTF-16BE
    /Title), 13 an unused Flate stream, 14 an unused Flate image. The page also draws an inline image."""
    a, b = v["pdfsplit"][:17], v["pdfsplit"][17:]  # one token printed on two lines
    content = (f"BT /F1 12 Tf 72 720 Td ({v['pdftext']}) Tj ET\nBT /F1 12 Tf 72 690 Td ({a}) Tj 0 -14 Td ({b}) Tj ET\n"
               "q 40 0 0 40 72 500 cm /Im1 Do Q\nq 30 0 0 20 72 450 cm /Im2 Do Q\nq 40 0 0 40 72 380 cm /Im3 Do Q\n"
               "q 10 0 0 10 72 340 cm BI /W 10 /H 10 /CS /RGB /BPC 8 ID\n").encode() + mark.resize((10, 10)).tobytes() \
        + b"\nEI Q\n"
    img = b"/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 "
    uri = b"<" + f"https://example.invalid/{v['uri']}".encode().hex().encode() + b">"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R /Outlines 10 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> "
        b"/XObject << /Im1 6 0 R /Im2 7 0 R /Im3 8 0 R >> >> /Contents 4 0 R /Annots [9 0 R] >>",
        _stream(b"/Filter [/ASCII85Decode /FlateDecode]", _a85(zlib.compress(content))),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        _stream(img % mark.size + b"/Filter /FlateDecode", zlib.compress(mark.tobytes())),
        _stream(img % crop_a.size + b"/Filter [/ASCII85Decode /FlateDecode]", _a85(zlib.compress(crop_a.tobytes()))),
        _stream(img % mark.size + b"/Filter /DCTDecode", jpeg(mark)),
        b"<< /Type /Annot /Subtype /Link /Rect [72 300 300 320] /A << /S /URI /URI %s >> >>" % uri,
        b"<< /Type /Outlines /First 11 0 R /Last 11 0 R /Count 1 >>",
        b"<< /Title %s /Parent 10 0 R /Dest [3 0 R /Fit] >>" % _utf16(v["outline"]),
        b"<< /Title %s /Producer (hand) >>" % _utf16(v["title"]),
        _stream(b"/Filter /FlateDecode", zlib.compress(f"BT ({v['unused']}) Tj ET".encode())),
        _stream(img % crop_b.size + b"/Filter /FlateDecode", zlib.compress(crop_b.tobytes())),
    ]
    return assemble(objs, info=12)


def assemble(objs, info=None, update=None) -> bytes:
    """A PDF of the object bodies (object n is objs[n - 1]); update {n: body} appends an incremental update section
    that replaces or adds those objects, leaving the earlier copies in the file."""
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref, size = len(out), len(objs) + 1 + len(set(update or ()) - set(range(1, len(objs) + 1)))
    info = b" /Info %d 0 R" % info if info else b""
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R%s >>\nstartxref\n%d\n%%%%EOF\n" % (size, info, xref)
    if update:
        new = {}
        for n, body in update.items():
            new[n] = len(out)
            out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
        prev, xref = xref, len(out)
        out += b"xref\n" + b"".join(b"%d 1\n%010d 00000 n \n" % (n, o) for n, o in sorted(new.items()))
        out += b"trailer\n<< /Size %d /Root 1 0 R%s /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (size, info, prev, xref)
    return bytes(out)


def coded(s: str):
    """A font whose codes are not ASCII (as a TrueType subset): code i + 1 draws the i-th distinct character of s.
    Returns the font object and s as a hex string in those codes; only extract_text or form text can read it."""
    glyph = {"-": "hyphen", **dict(zip("0123456789", "zero one two three four five six seven eight nine".split()))}
    chars = sorted(set(s))
    names = b" ".join(b"/" + glyph.get(c, c).encode() for c in chars)
    font = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /Type /Encoding /Differences [1 %s] >> >>"
    return font % names, b"<" + bytes(chars.index(c) + 1 for c in s).hex().encode() + b">"


def page_pdf(content: bytes, font=b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", extra=(), page=b"",
             **kw) -> bytes:
    """One page drawing content (Flate) with font F1 as object 5; extra objects from 6 on; page adds page entries."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> "
            b"/Contents 4 0 R %s>>" % page, _stream(b"/Filter /FlateDecode", zlib.compress(content)), font, *extra]
    return assemble(objs, **kw)


def zipped(members: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return out.getvalue()


def workbook(v, media) -> bytes:
    """An XLSX zip as openpyxl lays one out: shared string (first letter as an XML entity), inline string cell, sheet
    name, docProps/core.xml title, a comments part and xl/media/image1.png."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    shared = f"&#{ord(v['shared'][0])};{v['shared'][1:]}"
    return zipped({
        "[Content_Types].xml": head + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "xl/workbook.xml": head + f'<workbook {ns}><sheets><sheet name="{v["sheet"]}" sheetId="1"/></sheets></workbook>',
        "xl/sharedStrings.xml": head + f"<sst {ns}><si><t>{shared}</t></si></sst>",
        "xl/worksheets/sheet1.xml": head + f'<worksheet {ns}><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c>'
                                           f'<c r="B1" t="inlineStr"><is><t>{v["inline"]}</t></is></c></row>'
                                           "</sheetData></worksheet>",
        "xl/comments1.xml": head + f'<comments {ns}><commentList><comment ref="A1"><text><t>{v["comment"]}</t></text>'
                                   "</comment></commentList></comments>",
        "docProps/core.xml": head + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
                                    'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                                    f"<dc:title>{v['core']}</dc:title></cp:coreProperties>",
        "xl/media/image1.png": png(media),
    })


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def plant(folder, v, mark, crop_a, crop_b, render, hashed):
    """Every self-test file of section 5 in one folder. Returns the open connection that holds w.db's -wal."""
    files = {
        "doc.pdf": hand_pdf(v, mark, crop_a, crop_b),
        "book.xlsx": workbook(v, mark),
        "table.csv": codecs.BOM_UTF8 + f"company,note,case\r\nAcme,{v['csv']},{v['case'].upper()}\r\n".encode(),
        "table16.csv": f"company,note\r\nAcme,{v['utf16']}\r\n".encode("utf-16"),  # with its BOM
        "data.json": ('{"rows": [{"note": "\\u%04x%s"}]}' % (ord(v["json"][0]), v["json"][1:])).encode(),
        "page.html": (f"<!doctype html><html><body><p>&#{ord(v['entity'][0])};{v['entity'][1:]}</p>"
                      f'<a href="data:application/json;base64,{b64(json.dumps({"note": v["datajson"]}).encode())}">j</a>'
                      f'<img src="data:image/png;base64,{b64(png(mark))}"></body></html>').encode(),
        f"notes-{v['name']}.txt": b"shareable notes\n",
        f"{v['dir']}/readme.txt": b"shareable readme\n",
        "hashed.bin": hashed,
        "render.png": render,
        "crop.png": png(crop_a),
        "outer.zip": zipped({"inner.zip": zipped({"note.txt": v["nested"]})}),
        ".hidden": v["dot"].encode(),
        "files/ab/.incoming-0001": v["incoming"].encode(),
    }
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    (folder / "db").mkdir()
    con = sqlite3.connect(folder / "db" / "w.db")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (a TEXT, b TEXT)")
    con.execute("CREATE INDEX t_ab ON t (a || '-' || b)")  # the index alone holds a-b
    con.execute("INSERT INTO t VALUES (?, 'x')", (v["row"],))
    con.execute("INSERT INTO t VALUES (?, ?)", (v["index"][:-3], v["index"][-2:]))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.execute("INSERT INTO t VALUES (?, 'x')", (v["wal"],))  # only in the -wal while con stays open
    con.commit()
    return con


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    folder = tmp_path_factory.mktemp("planted")
    con = plant(folder, V, picture(MARKER), CROP_A, CROP_B, RENDER, HASHED)
    yield folder
    con.close()


@pytest.fixture(scope="module")
def shareable(tmp_path_factory):
    """The negative twin: shareable strings, grey images, other crops, other bytes, and a grey render of a page."""
    folder = tmp_path_factory.mktemp("shareable")
    con = plant(folder, SHAREABLE, picture(GREY), crop((30, 20), True), crop((24, 18), True),
                png(picture((90, 90, 90), (30, 30))), b"other bytes\n")
    (folder / "page-render.png").write_bytes(png(grey_render()))
    yield folder
    con.close()


def grey_render():
    page = text_pdf([{"text": [(72, 72, "Scope 1 emissions 1,234 tCO2e"), (72, 100, "Shareable page")],
                      "lines": [(72, 110, 400, 110)]}])
    return pdfium.PdfDocument(page)[0].render(scale=2).to_pil()


# Where each seed must be reported (a subset of what found returns; section 5).
EXPECTED = {
    V["pdftext"]: ["doc.pdf: page 1 text", "doc.pdf: object 4 stream: raw bytes"],
    V["pdfsplit"]: ["doc.pdf: page 1 text"],
    V["title"]: ["doc.pdf: metadata", "doc.pdf: object 12"],
    V["uri"]: ["doc.pdf: object 9"],
    V["outline"]: ["doc.pdf: object 11"],
    V["unused"]: ["doc.pdf: object 13 stream: raw bytes"],
    V["shared"]: ["book.xlsx > xl/sharedStrings.xml: XML", "book.xlsx > xl/sharedStrings.xml: text, unescaped"],
    V["inline"]: ["book.xlsx > xl/worksheets/sheet1.xml: XML"],
    V["sheet"]: ["book.xlsx > xl/workbook.xml: XML"],
    V["core"]: ["book.xlsx > docProps/core.xml: XML"],
    V["comment"]: ["book.xlsx > xl/comments1.xml: XML"],
    V["csv"]: ["table.csv: text"],
    V["case"]: ["table.csv: text"],
    V["utf16"]: ["table16.csv: text"],
    V["json"]: ["data.json: text, unescaped"],
    V["entity"]: ["page.html: text, unescaped"],
    V["datajson"]: ["page.html > data URI 1: text"],
    V["row"]: ["db/w.db: raw bytes", "db/w.db: database dump"],
    V["index"]: ["db/w.db: raw bytes"],
    V["wal"]: ["db/w.db-wal: raw bytes", "db/w.db: -wal raw bytes", "db/w.db: database dump"],
    V["name"]: [f"notes-{V['name']}.txt: path"],
    V["dir"]: [f"{V['dir']}/readme.txt: path"],
    V["nested"]: ["outer.zip > inner.zip > note.txt: raw bytes"],
    V["dot"]: [".hidden: raw bytes"],
    V["incoming"]: ["files/ab/.incoming-0001: raw bytes"],
    "GCT-LEAK-SCAN-HASH-25": ["hashed.bin: file hash"],
    "GCT-LEAK-SCAN-CROPA-26": ["doc.pdf: object 7 image: pixel hash", "crop.png: pixel hash"],
    "GCT-LEAK-SCAN-CROPB-27": ["doc.pdf: object 14 image: pixel hash"],
    "GCT-LEAK-SCAN-RENDER-28": ["render.png: file hash"],
}
MARKED = ["doc.pdf: object 6 image", "doc.pdf: object 8 image", "doc.pdf: page 1 inline image 1",
          "book.xlsx > xl/media/image1.png", "page.html > data URI 2"]
for _name in (s["name"] for s in SEEDS if s["kind"] == "image" and s["value"] is None):  # 7.1 G: the marker seeds
    EXPECTED[_name] = EXPECTED[_name] + [f"{m}: marker colour" for m in MARKED]


def test_every_planted_seed_is_found_with_its_place(planted):
    """AC 1: every seed of every hiding place, and the place it was found."""
    result = found(planted, SEEDS)
    assert set(result) == {s["name"] for s in SEEDS}
    for name, places in EXPECTED.items():
        assert set(places) <= set(result[name]), (name, result[name])
    # The index seed is only in the index pages, the -wal seed only in the -wal: the dump and raw bytes are needed.
    assert "db/w.db: database dump" not in result[V["index"]]
    assert "db/w.db: raw bytes" not in result[V["wal"]]


def test_negative_files_report_nothing(shareable):
    """AC 1 and AC 3: the same files with shareable strings, grey images and a grey page render."""
    assert found(shareable, SEEDS) == {}


def test_a_raw_byte_search_misses_what_needs_decoding(planted):
    """AC 2: the 4.5 scan (raw bytes of every file) misses the PDF, image, zipped and escaped seeds found above."""
    values = {s["name"]: s["value"] for s in SEEDS if s["value"]}
    raw = scan(planted, canaries=tuple(values.values()))
    decoded = ["pdftext", "pdfsplit", "title", "uri", "outline", "unused", "shared", "inline", "sheet", "core", "comment",
               "nested", "json", "entity", "datajson", "utf16"]
    missed = [V[k] for k in decoded] + [values["GCT-LEAK-SCAN-CROPA-26"], values["GCT-LEAK-SCAN-CROPB-27"]]
    assert not raw & set(missed), raw & set(missed)
    assert {V["csv"], V["row"], V["dot"]} <= raw  # the raw search itself works
    result = found(planted, SEEDS)
    assert all(s in result for s in [V[k] for k in decoded] + IMAGES)


def test_marker_survives_scaling_and_pixel_hash_is_exact(tmp_path):
    """AC 3: the marker in a 0.5 and 2 times scaled copy of a crop; the pixel hash of a lossless copy only."""
    scene = picture(GREY, (100, 100))
    scene.paste(picture(MARKER), (30, 30))
    (tmp_path / "half.png").write_bytes(png(scene.resize((50, 50))))
    (tmp_path / "double.png").write_bytes(png(scene.resize((200, 200))))
    (tmp_path / "lossless.png").write_bytes(png(scene))
    (tmp_path / "lossy.jpg").write_bytes(jpeg(scene))
    seeds = [{"name": "GCT-LEAK-SCAN-SCENE-01", "kind": "image", "expect": "complete_only", "value": pixels(scene)},
             {"name": "GCT-LEAK-SCAN-MARKER-02", "kind": "image", "expect": "complete_only", "value": None}]
    assert found(tmp_path, seeds) == {"GCT-LEAK-SCAN-SCENE-01": ["lossless.png: pixel hash"],
                                      "GCT-LEAK-SCAN-MARKER-02": [
        "double.png: marker colour", "half.png: marker colour", "lossless.png: marker colour",
        "lossy.jpg: marker colour"]}
    assert found(tmp_path / "half.png", seeds) == {"GCT-LEAK-SCAN-MARKER-02": ["half.png: marker colour"]}


def test_no_marker_on_grey_renders(tmp_path):
    """AC 3: a grey render of a shareable page, at two scales, has no marker hit."""
    img = grey_render()
    (tmp_path / "a.png").write_bytes(png(img))
    (tmp_path / "b.jpg").write_bytes(jpeg(img.resize((img.width // 2, img.height // 2))))
    assert found(tmp_path, [s for s in SEEDS if s["kind"] == "image"]) == {}


def snapshot(folder) -> dict:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def test_the_scanner_writes_nothing(planted, tmp_path):
    """AC 4: the scanned folder (an open WAL database included) keeps every byte and file; a closed WAL database gets
    no -wal or -shm beside it; a database file scanned alone still reads its -wal."""
    before = snapshot(planted)
    assert {"db/w.db-wal", "db/w.db-shm"} <= set(before)
    found(planted, SEEDS)
    assert snapshot(planted) == before

    con = sqlite3.connect(tmp_path / "c.db")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (a TEXT)")
    con.execute("INSERT INTO t VALUES ('GCT-LEAK-SCAN-CLOSED-01')")
    con.commit()
    con.close()
    assert snapshot(tmp_path) == {"c.db": hashlib.sha256((tmp_path / "c.db").read_bytes()).hexdigest()}
    before = snapshot(tmp_path)
    seed = [text_seed("GCT-LEAK-SCAN-CLOSED-01")]
    assert "c.db: database dump" in found(tmp_path, seed)["GCT-LEAK-SCAN-CLOSED-01"]
    assert snapshot(tmp_path) == before

    alone = found(planted / "db" / "w.db", SEEDS)[V["wal"]]
    assert alone == ["w.db: -wal raw bytes", "w.db: database dump"]


@pytest.mark.parametrize("value", ["GCT LEAK", "GCT_LEAK-01", "GCT-LÉAK-01", "GCT-LEAK/01", "", None])
def test_seed_hygiene_refuses_unsafe_text(tmp_path, value):
    """AC 5: a text seed outside [A-Za-z0-9-] is refused, for every text kind."""
    for kind in ("document_text", "contributor", "credential", "path"):
        with pytest.raises(ValueError, match="uses only"):
            found(tmp_path, [{"name": "s", "kind": kind, "expect": "never", "value": value}])


def test_seed_hygiene_refuses_substrings_and_bad_shapes(tmp_path):
    """AC 5: a value inside another (7.1's -1 beside -10, case-folded), a repeated name, an unknown kind and a file
    hash or render_sha256 that is not a hex digest are refused."""
    for pair in (("GCT-PRIVATE-CANARY-1", "GCT-PRIVATE-CANARY-10"), ("gct-leak-canary-01", "GCT-LEAK-CANARY-01")):
        with pytest.raises(ValueError, match="inside"):
            found(tmp_path, [text_seed(pair[0]), text_seed(pair[1])])
    with pytest.raises(ValueError, match="repeat"):
        found(tmp_path, [text_seed("GCT-LEAK-CANARY-01"), dict(text_seed("GCT-LEAK-CANARY-02"), name="GCT-LEAK-CANARY-01")])
    for kind in ("supplier", "document text", "document-text", "file hash", "Image"):  # 7.1 G's exact tokens only
        with pytest.raises(ValueError, match="unknown kind"):
            found(tmp_path, [text_seed("GCT-LEAK-CANARY-01", kind=kind)])
    with pytest.raises(ValueError, match="value is a sha256 hex digest"):  # an image value is the decoded RGB hash
        found(tmp_path, [{"name": "i", "kind": "image", "expect": "complete_only", "value": "marker"}])
    with pytest.raises(ValueError, match="hex digest"):
        found(tmp_path, [{"name": "h", "kind": "file_hash", "expect": "complete_only", "value": "GCT-LEAK-CANARY-01"}])
    with pytest.raises(ValueError, match="hex digest"):
        found(tmp_path, [{"name": "i", "kind": "image", "expect": "complete_only", "value": None,
                          "render_sha256": "not-a-digest"}])


def test_seed_lists_in_the_7_1_shape_are_accepted_together(tmp_path):
    """AC 5: 7.1's seed names and kinds (G) beside 7.7's own GCT-LEAK-CANARY- additions, hex digests exempt, are
    accepted together; on an empty folder nothing is found. (Part B repeats this with report_fixture.SEEDS.)"""
    digest = hashlib.sha256(b"x").hexdigest()
    seeds_7_1 = [text_seed("GCT-PRIVATE-CANARY-01"), text_seed("GCT-PRIVATE-CANARY-02", "contributor"),
                 text_seed("sk-GCTFAKEKEY0001", "credential"), text_seed("GCT-PATH-CANARY", "path"),
                 {"name": "GCT-PRIVATE-CANARY-03", "kind": "image", "expect": "complete_only", "value": None,
                  "render_sha256": digest.upper()},
                 {"name": "GCT-PRIVATE-CANARY-04", "kind": "file_hash", "expect": "complete_only",
                  "value": hashlib.sha256(b"y").hexdigest()}]
    seeds_7_7 = [text_seed("GCT-LEAK-CANARY-01"), text_seed("GCT-LEAK-ROOT-01", "path"),
                 {"name": "GCT-LEAK-CANARY-02", "kind": "image", "expect": "complete_only", "value": digest[::-1]}]
    assert found(tmp_path, seeds_7_1 + seeds_7_7) == {}
    (tmp_path / "x.bin").write_bytes(b"x")
    assert found(tmp_path, seeds_7_1 + seeds_7_7) == {"GCT-PRIVATE-CANARY-03": ["x.bin: file hash"]}


# --- review fix round 1 (Xiao's probes, /tmp/xiao-7-7-a-review/) -----------------------------------------------------

def put(folder, files: dict):
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    return folder


def where(result, name, place):
    """True when one of the seed's places starts with place."""
    return any(p.startswith(place) for p in result.get(name, ()))


def ahx(data: bytes) -> bytes:
    """A stream only pdfminer decodes: ASCIIHex is neither Flate nor a <...> string token."""
    return _stream(b"/Filter /ASCIIHexDecode", data.hex().encode() + b">")


RGB_IMAGE = b"/Type /XObject /Subtype /Image /Width %d /Height %d /BitsPerComponent %d /ColorSpace %s "
BAD_INLINE = b"q 10 0 0 10 72 340 cm BI /W 10 /H 10 /CS /RGB /BPC 8 ID\n" + b"\x80" * 30 + b"\nEI Q\n"


def test_an_unreadable_part_is_reported_and_the_rest_is_read(tmp_path):
    """B1: one bad inline image, one bad image object or one zip member with a bad CRC neither stops the rest of the
    file (later pages, metadata, later objects and members) nor passes silently: found raises Unreadable naming
    every bad place, with what the rest of the scan found."""
    page2, title, later, member = (f"GCT-LEAK-FIX-{k}-01" for k in ("PAGE", "TITLE", "LATER", "MEMBER"))
    font, codes = coded(page2)
    res = b"/Resources << /Font << /F1 5 0 R >> >>"
    two_pages = assemble([
        b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R 7 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] %s /Contents 4 0 R >>" % res,
        _stream(b"/Filter /FlateDecode", zlib.compress(b"BT /F1 12 Tf 72 700 Td <01> Tj ET\n" + BAD_INLINE)), font,
        b"<< /Title %s >>" % _utf16(title),
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] %s /Contents 8 0 R >>" % res,
        _stream(b"/Filter /FlateDecode", zlib.compress(b"BT /F1 12 Tf 72 700 Td " + codes + b" Tj ET"))], info=6)
    bad_object = page_pdf(b"BT /F1 12 Tf 72 700 Td (clean) Tj ET", extra=[
        _stream(RGB_IMAGE % (10, 10, 8, b"/DeviceRGB") + b"/Filter /FlateDecode", zlib.compress(b"\x80" * 30)),
        ahx(f"({later})".encode())])
    zip_ok = zipped({"a.txt": b"clean", "b.txt": member.encode()})
    i, j = zip_ok.index(b"PK\x03\x04") + 14, zip_ok.index(b"PK\x01\x02") + 16  # the first member's CRC, twice
    bad_zip = zip_ok[:i] + b"\0\0\0\0" + zip_ok[i + 4:j] + b"\0\0\0\0" + zip_ok[j + 4:]
    put(tmp_path, {"two.pdf": two_pages, "object.pdf": bad_object, "c.zip": bad_zip})
    seeds = [text_seed(s) for s in (page2, title, later, member)]
    with pytest.raises(Unreadable) as e:
        found(tmp_path, seeds)
    assert [p.split(" (")[0] for p in e.value.places] == ["c.zip > a.txt", "object.pdf: object 6",
                                                          "two.pdf: page 1 inline image 1"], e.value.places
    assert where(e.value.found, page2, "two.pdf: page 2 text")
    assert where(e.value.found, title, "two.pdf: metadata")
    assert where(e.value.found, later, "object.pdf: object 7 stream")
    assert where(e.value.found, member, "c.zip > b.txt")


def test_superseded_and_every_xref_section_are_read(tmp_path):
    """I1: an incremental update replaces the page content (Flate) and the UTF-16BE /Info /Title; the old copies stay
    in the file and are found. Objects only in the older and only in the newer section are both walked."""
    content, info, old, new = (f"GCT-LEAK-FIX-{k}-02" for k in ("CONTENT", "INFO", "OLDSECTION", "NEWSECTION"))
    pdf = page_pdf(b"BT /F1 12 Tf 72 700 Td (%s) Tj ET" % content.encode(),
                   extra=[b"<< /Title %s >>" % _utf16(info), ahx(f"({old})".encode())], info=6,
                   update={4: _stream(b"/Filter /FlateDecode", zlib.compress(b"BT /F1 12 Tf 72 700 Td (clean) Tj ET")),
                           6: b"<< /Title (clean) >>", 8: ahx(f"({new})".encode())})
    result = found(put(tmp_path, {"a.pdf": pdf}), [text_seed(s) for s in (content, info, old, new)])
    assert where(result, content, "a.pdf: object 4 at byte")  # the superseded copy, parsed as an object
    assert where(result, info, "a.pdf: object 6 at byte") and where(result, info, "a.pdf: string tokens")
    assert where(result, old, "a.pdf: object 7 stream") and where(result, new, "a.pdf: object 8 stream")
    assert not where(result, content, "a.pdf: page 1 text")  # the page shows the new content only


def test_pdf_text_extract_text_misses(tmp_path):
    """I2: hex and octal strings in an unused stream, coded text drawn bottom to top, an undrawn form XObject and an
    annotation appearance stream (interpreted for their text), a token kerned apart into two words, a name written
    with #-escapes, and a header after a leading byte."""
    s = {k: f"GCT-LEAK-FIX-{k}-03" for k in ("HEX", "OCTAL", "ROTATED", "FORM", "APPEARANCE", "KERNED", "NAME",
                                            "PREFIX")}
    blank = b"BT /F1 12 Tf 72 700 Td (clean) Tj ET"
    files = {
        "hex.pdf": page_pdf(blank, extra=[_stream(b"/Filter /FlateDecode", zlib.compress(
            b"BT <%s> Tj ET" % s["HEX"].encode().hex().encode()))]),
        "octal.pdf": page_pdf(blank, extra=[_stream(b"/Filter /FlateDecode", zlib.compress(
            b"BT (" + b"".join(b"\\%03o" % c for c in s["OCTAL"].encode()) + b") Tj ET"))]),
        "kerned.pdf": page_pdf(b"BT /F1 12 Tf 72 700 Td [(%s) -1000 (%s)] TJ ET" % (
            s["KERNED"][:9].encode(), s["KERNED"][9:].encode())),
        "name.pdf": page_pdf(blank, extra=[b"<< /Label /#47%s >>" % s["NAME"][1:].encode()]),
        "prefix.pdf": b"\n" + page_pdf(b"BT /F1 12 Tf 72 700 Td (%s) Tj ET" % s["PREFIX"].encode()),
    }
    font, codes = coded(s["ROTATED"])
    files["rotated.pdf"] = page_pdf(b"BT /F1 12 Tf 0 12 -12 0 72 300 Tm " + codes + b" Tj ET", font)
    font, codes = coded(s["FORM"])
    files["form.pdf"] = page_pdf(blank, font, extra=[_stream(
        b"/Type /XObject /Subtype /Form /BBox [0 0 600 100] /Resources << /Font << /F1 5 0 R >> >> "
        b"/Filter /FlateDecode", zlib.compress(b"BT /F1 12 Tf 10 10 Td " + codes + b" Tj ET"))])
    font, codes = coded(s["APPEARANCE"])
    files["appearance.pdf"] = page_pdf(blank, font, page=b"/Annots [6 0 R] ", extra=[
        b"<< /Type /Annot /Subtype /Widget /Rect [72 300 300 320] /AP << /N 7 0 R >> >>",
        _stream(b"/BBox [0 0 228 20] /Resources << /Font << /F1 5 0 R >> >>",
                b"BT /F1 12 Tf 2 5 Td " + codes + b" Tj ET")])
    result = found(put(tmp_path, files), [text_seed(v) for v in s.values()])
    assert where(result, s["HEX"], "hex.pdf: object 6 stream string tokens")
    assert where(result, s["OCTAL"], "octal.pdf: object 6 stream string tokens")
    assert where(result, s["ROTATED"], "rotated.pdf: page 1 text reversed")
    assert where(result, s["FORM"], "form.pdf: object 6 form text")
    assert where(result, s["APPEARANCE"], "appearance.pdf: object 7 form text")
    assert where(result, s["KERNED"], "kerned.pdf: page 1 text")
    assert where(result, s["NAME"], "name.pdf: object 6")
    assert where(result, s["PREFIX"], "prefix.pdf: page 1 text")
    assert scan(tmp_path, canaries=tuple(s.values())) == set()  # none of them is in the raw bytes


def test_text_split_by_markup_escapes_or_invisible_characters(tmp_path):
    """I3 and the text item: rich-text runs in a shared string, <mark> and <wbr> inside a word, &shy; and &#8203;
    inside a word, a \\u escape in NDJSON and in a JSON <script>, an entity in a Markdown file, a percent-encoded
    data: URI and a seed in a zip member's name."""
    s = {k: f"GCT-LEAK-FIX-{k}-04" for k in ("RICH", "MARK", "WBR", "SHY", "ZWSP", "NDJSON", "SCRIPT", "MARKDOWN",
                                            "PERCENT", "MEMBERNAME")}
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rich = f'<sst {ns}><si><r><t>{s["RICH"][:9]}</t></r><r><rPr><b/></rPr><t>{s["RICH"][9:]}</t></r></si></sst>'
    u = lambda v: "\\u%04x%s" % (ord(v[0]), v[1:])  # noqa: E731
    files = {
        "rich.xlsx": zipped({"xl/sharedStrings.xml": rich}),
        "mark.html": f"<!doctype html><p>{s['MARK'][:9]}<mark>{s['MARK'][9:14]}</mark>{s['MARK'][14:]}</p>".encode(),
        "wbr.html": f"<!doctype html><p>{s['WBR'][:9]}<wbr>{s['WBR'][9:]}</p>".encode(),
        "shy.html": f"<!doctype html><p>{s['SHY'][:9]}&shy;{s['SHY'][9:]}</p>".encode(),
        "zwsp.html": f"<!doctype html><p>{s['ZWSP'][:9]}&#8203;{s['ZWSP'][9:]}</p>".encode(),
        "rows.jsonl": ('{"a": "%s"}\n{"b": 1}\n' % u(s["NDJSON"])).encode(),
        "script.html": ('<!doctype html><script type="application/json">{"a": "%s"}</script>' % u(s["SCRIPT"])).encode(),
        "notes.md": f"# notes\n&#{ord(s['MARKDOWN'][0])};{s['MARKDOWN'][1:]}\n".encode(),
        "percent.html": f'<!doctype html><a href="data:text/plain,%{ord(s["PERCENT"][0]):02X}{s["PERCENT"][1:]}">'
                        "p</a>".encode(),
        "names.zip": zipped({f"{s['MEMBERNAME']}.txt": b"clean"}),
    }
    result = found(put(tmp_path, files), [text_seed(v) for v in s.values()])
    assert where(result, s["RICH"], "rich.xlsx > xl/sharedStrings.xml: XML")
    for k in ("MARK", "WBR", "SHY", "ZWSP"):
        assert where(result, s[k], f"{k.lower()}.html: HTML text"), k
    assert where(result, s["NDJSON"], "rows.jsonl: text, unescaped")
    assert where(result, s["SCRIPT"], "script.html: text, unescaped")
    assert where(result, s["MARKDOWN"], "notes.md: text, unescaped")
    assert where(result, s["PERCENT"], "percent.html > data URI 1: text")
    assert where(result, s["MEMBERNAME"], f"names.zip > {s['MEMBERNAME']}.txt: member name")


def test_pdf_image_colour_spaces(tmp_path):
    """I4: ICCBased (N 3) and DeviceCMYK images in the marker colour, DeviceGray and 1-bit images by pixel hash; a
    16-bit image is not decoded and is reported as unreadable (known ceiling, loud); an Indexed image is read through
    its palette."""
    marker_cmyk = Image.new("CMYK", (20, 20), (255, 55, 135, 0))
    assert marker_cmyk.convert("RGB").getpixel((0, 0)) == MARKER
    grey, mask = Image.linear_gradient("L").resize((16, 12)), Image.new("1", (13, 9))
    mask.paste(1, (2, 2, 9, 7))
    icc = _stream(b"/N 3 /Filter /FlateDecode", zlib.compress(b"icc"))
    good = page_pdf(b"BT /F1 12 Tf 72 700 Td (clean) Tj ET", extra=[
        _stream(RGB_IMAGE % (20, 20, 8, b"[/ICCBased 7 0 R]") + b"/Filter /FlateDecode",
                zlib.compress(picture(MARKER, (20, 20)).tobytes())), icc,
        _stream(RGB_IMAGE % (20, 20, 8, b"/DeviceCMYK") + b"/Filter /FlateDecode", zlib.compress(marker_cmyk.tobytes())),
        _stream(RGB_IMAGE % (16, 12, 8, b"/DeviceGray") + b"/Filter /FlateDecode", zlib.compress(grey.tobytes())),
        _stream(RGB_IMAGE % (13, 9, 1, b"/DeviceGray") + b"/Filter /FlateDecode", zlib.compress(mask.tobytes()))])
    seeds = [{"name": n, "kind": "image", "expect": "complete_only", "value": v}
             for n, v in (("GCT-LEAK-FIX-GREY-05", pixels(grey)), ("GCT-LEAK-FIX-MASK-05", pixels(mask)),
                          ("GCT-LEAK-FIX-MARKER-05", None))]
    result = found(put(tmp_path / "good", {"a.pdf": good}), seeds)
    for obj in (6, 8):
        assert where(result, "GCT-LEAK-FIX-MARKER-05", f"a.pdf: object {obj} image: marker colour"), obj
    assert where(result, "GCT-LEAK-FIX-GREY-05", "a.pdf: object 9 image: pixel hash")
    assert where(result, "GCT-LEAK-FIX-MASK-05", "a.pdf: object 10 image: pixel hash")

    palette = bytes(MARKER) + bytes(GREY)
    bad = page_pdf(b"BT /F1 12 Tf 72 700 Td (clean) Tj ET", extra=[
        _stream(RGB_IMAGE % (20, 20, 8, b"[/Indexed /DeviceRGB 1 <%s>]" % palette.hex().encode())
                + b"/Filter /FlateDecode", zlib.compress(b"\0" * 400)),
        _stream(RGB_IMAGE % (20, 20, 16, b"/DeviceRGB") + b"/Filter /FlateDecode",
                zlib.compress(bytes((0, 0, 0, 200, 0, 120)) * 400))])
    with pytest.raises(Unreadable) as e:
        found(put(tmp_path / "bad", {"b.pdf": bad}), seeds)
    assert [p.split(" (")[0] for p in e.value.places] == ["b.pdf: object 7"]
    assert where(e.value.found, "GCT-LEAK-FIX-MARKER-05", "b.pdf: object 6 image: marker colour")


def test_any_image_pillow_opens(tmp_path):
    """The images item: GIF and WebP files, and a marker only in the second frame of an animated GIF."""
    scene = picture(GREY, (100, 100))
    scene.paste(picture(MARKER), (30, 30))
    files = {}
    for fmt, kw in (("GIF", {}), ("WEBP", {"lossless": True})):
        out = io.BytesIO()
        scene.save(out, fmt, **kw)
        files[f"a.{fmt.lower()}"] = out.getvalue()
    out = io.BytesIO()
    picture(GREY, (100, 100)).save(out, "GIF", save_all=True, append_images=[scene], duration=100)
    files["animated.gif"] = out.getvalue()
    seed = {"name": "GCT-LEAK-FIX-IMAGE-06", "kind": "image", "expect": "complete_only", "value": None}
    assert found(put(tmp_path, files), [seed]) == {"GCT-LEAK-FIX-IMAGE-06": [
        "a.gif: marker colour", "a.webp: marker colour", "animated.gif frame 2: marker colour"]}


def test_symbolic_links_are_refused(tmp_path):
    """The symlinks item: a linked folder, a linked file and a dangling link are refused before anything is read."""
    outside = tmp_path / "outside"
    put(outside, {"x.txt": b"GCT-LEAK-FIX-LINKED-07"})
    folder = put(tmp_path / "scanned", {"plain.txt": b"clean"})
    (folder / "dir").symlink_to(outside, target_is_directory=True)
    (folder / "file.txt").symlink_to(outside / "x.txt")
    (folder / "dangling").symlink_to(tmp_path / "nowhere")
    with pytest.raises(ValueError, match="symbolic links") as e:
        found(folder, [text_seed("GCT-LEAK-FIX-LINKED-07")])
    assert all(str(folder / n) in str(e.value) for n in ("dir", "file.txt", "dangling"))


# --- review fix round 2 (Xiao's second review, /tmp/xiao-7-7-a-review-r2/) ------------------------------------------

MARKER_SEED = {"name": "GCT-LEAK-FIX-MARKER-08", "kind": "image", "expect": "complete_only", "value": None}


def image_object(img, dct=False, extra=b""):
    data = jpeg(img) if dct else zlib.compress(img.tobytes())
    mode = {"RGB": b"/DeviceRGB", "L": b"/DeviceGray"}[img.mode]
    return _stream(RGB_IMAGE % (*img.size, 8, mode) + extra + (b"/Filter /DCTDecode" if dct else b"/Filter /FlateDecode"),
                   data)


def test_superseded_and_orphan_objects_are_parsed_as_objects(tmp_path):
    """B1 (round 2): a copy an incremental update superseded, or an object no xref section lists, is parsed as an
    object: an uncompressed content stream with a hex or an octal seed, a Flate one in a coded font (interpreted with
    its page's resources), an AHx one, a Flate and a DCT image in the marker colour, an orphan image after %%EOF, and
    an inline marker image inside an undrawn form."""
    s = {k: f"GCT-LEAK-FIX-{k}-08" for k in ("HEX", "OCTAL", "CODED", "AHX")}
    clean = _stream(b"", b"BT /F1 12 Tf 72 700 Td (clean) Tj ET")
    hexed = b"<%s>" % s["HEX"].encode().hex().encode()
    octal = b"(" + b"".join(b"\\%03o" % c for c in s["OCTAL"].encode()) + b")"
    font, codes = coded(s["CODED"])

    def replaced(content, font=b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", new=clean):
        """A page whose content object 4 an incremental update replaced by new."""
        return assemble([
            b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> "
            b"/Contents 4 0 R >>", content, font], update={4: new})
    files = {
        "hex.pdf": replaced(_stream(b"", b"BT /F1 12 Tf 72 700 Td " + hexed + b" Tj ET")),
        "octal.pdf": replaced(_stream(b"", b"BT /F1 12 Tf 72 700 Td " + octal + b" Tj ET")),
        "coded.pdf": replaced(_stream(b"/Filter /FlateDecode", zlib.compress(b"BT /F1 12 Tf 72 700 Td " + codes + b" Tj ET")),
                              font, _stream(b"/Filter /FlateDecode", zlib.compress(b"BT /F1 12 Tf 72 700 Td <01> Tj ET"))),
        "ahx.pdf": replaced(ahx(b"BT /F1 12 Tf 72 700 Td (%s) Tj ET" % s["AHX"].encode())),
    }
    draw = b"q 40 0 0 40 72 600 cm /Im1 Do Q"
    page = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>"
    head = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", page,
            _stream(b"", draw)]
    mark, grey = picture(MARKER), picture(GREY)
    for name, dct in (("flate-image.pdf", False), ("dct-image.pdf", True)):
        files[name] = assemble(head + [image_object(mark, dct)], update={5: image_object(grey, dct)})
    files["orphan.pdf"] = assemble(head + [image_object(grey)]) + b"9 0 obj\n" + image_object(mark) + b"\nendobj\n"
    inline = b"q 40 0 0 40 0 0 cm BI /W 40 /H 40 /CS /RGB /BPC 8 ID\n" + mark.tobytes() + b"\nEI Q"
    files["form.pdf"] = page_pdf(b"BT /F1 12 Tf 72 700 Td (clean) Tj ET", extra=[_stream(
        b"/Type /XObject /Subtype /Form /BBox [0 0 100 100] /Filter /FlateDecode", zlib.compress(inline))])
    for name, pdf in files.items():
        result = found(put(tmp_path / name.removesuffix(".pdf"), {name: pdf}), [text_seed(v) for v in s.values()]
                       + [MARKER_SEED])
        assert result, name
        expect = {"hex.pdf": (s["HEX"], "object 4 at byte"), "octal.pdf": (s["OCTAL"], "object 4 at byte"),
                  "coded.pdf": (s["CODED"], "object 4 at byte"), "ahx.pdf": (s["AHX"], "object 4 at byte"),
                  "flate-image.pdf": ("GCT-LEAK-FIX-MARKER-08", "object 5 at byte"),
                  "dct-image.pdf": ("GCT-LEAK-FIX-MARKER-08", "object 5 at byte"),
                  "orphan.pdf": ("GCT-LEAK-FIX-MARKER-08", "object 9 at byte"),
                  "form.pdf": ("GCT-LEAK-FIX-MARKER-08", "object 6 form inline image 1: marker colour")}[name]
        assert where(result, expect[0], f"{name}: {expect[1]}"), (name, result)
    coded_places = found(tmp_path / "coded", [text_seed(s["CODED"])])[s["CODED"]]
    assert any(p.endswith("form text") for p in coded_places)  # only interpretation reads coded text


def dark_pdf(first: bytes, mode="RGB", smask=False) -> bytes:
    """A clean page with one clean 120 by 80 image, A85 and Flate as reportlab writes it, whose pixel bytes begin with
    first (as Xiao's real/dark* reportlab files: dark pixels that read as a PCX, PPM, BMP, JPEG or TIFF signature)."""
    channels = {"RGB": 3, "L": 1}[mode]
    pixels_ = (first + b"\xff" * (120 * 80 * channels))[:120 * 80 * channels]
    cs = {"RGB": b"/DeviceRGB", "L": b"/DeviceGray"}[mode]
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> "
            b"/XObject << /Im1 6 0 R >> >> /Contents 4 0 R >>",
            _stream(b"/Filter [/ASCII85Decode /FlateDecode]", _a85(zlib.compress(
                b"BT /F1 12 Tf 72 700 Td (clean chart) Tj ET\nq 120 0 0 80 72 400 cm /Im1 Do Q"))),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            _stream(RGB_IMAGE % (120, 80, 8, cs) + (b"/SMask 7 0 R " if smask else b"")
                    + b"/Filter [/ASCII85Decode /FlateDecode]", _a85(zlib.compress(pixels_)))]
    if smask:
        objs.append(_stream(RGB_IMAGE % (120, 80, 8, b"/DeviceGray") + b"/Filter [/ASCII85Decode /FlateDecode]",
                            _a85(zlib.compress((b"BM" + b"\xff" * 9600)[:9600]))))
    return assemble(objs)


def test_clean_pixels_that_start_with_a_file_signature_are_not_images(tmp_path):
    """B2: decoded stream bytes are never offered to Pillow, so clean reportlab-style images whose pixels begin with
    a PCX, PPM, BMP, JPEG or TIFF signature give {} and no Unreadable (Xiao's real/dark and real/dark2 files)."""
    files = {"dark_pcx.pdf": dark_pdf(bytes((10, 0, 0))), "p6_ppm.pdf": dark_pdf(bytes((80, 54, 200))),
             "pf_ppm.pdf": dark_pdf(bytes((80, 102, 120))), "slate_bmp.pdf": dark_pdf(bytes((66, 77, 90))),
             "gray_bm.pdf": dark_pdf(bytes((66, 77)), "L"), "jpeg_sig.pdf": dark_pdf(bytes((255, 216, 255))),
             "tiff_sig.pdf": dark_pdf(bytes((73, 73, 42, 0, 8, 0))),
             "smask_bm.pdf": dark_pdf(b"\n" * 6, smask=True)}
    # Two more clean cases: a non-image stream (an ICC profile, a font) whose bytes begin with a JPEG signature, and
    # stream data that reads like an object header (the object scan skips stream data).
    blank = b"BT /F1 12 Tf 72 700 Td (clean) Tj ET"
    files["signature_stream.pdf"] = page_pdf(blank, extra=[_stream(b"/N 3", b"\xff\xd8\xff\xe0 clean profile bytes")])
    files["header_in_stream.pdf"] = page_pdf(blank, extra=[_stream(b"", b"99 0 obj\n<< /A (x")])
    assert found(put(tmp_path, files), [text_seed("GCT-LEAK-FIX-NOPE-09"), MARKER_SEED]) == {}


def test_an_embedded_file_is_decoded_as_its_own_file(tmp_path):
    """An /EmbeddedFile stream is the one PDF stream decoded by its type: a zip attached to a PDF is read member by
    member."""
    seed = "GCT-LEAK-FIX-ATTACHED-13"
    attached = zipped({"note.txt": seed.encode() * 3})
    pdf = page_pdf(b"BT /F1 12 Tf 72 700 Td (clean) Tj ET", extra=[
        _stream(b"/Type /EmbeddedFile /Filter /FlateDecode", zlib.compress(attached))])
    result = found(put(tmp_path, {"a.pdf": pdf}), [text_seed(seed)])
    assert result == {seed: ["a.pdf: object 6 stream > note.txt: raw bytes", "a.pdf: object 6 stream > note.txt: text"]}


def test_only_strong_signatures_are_opened_as_images(tmp_path):
    """I1 (round 2): text that begins like a weak image signature (P1, P6, SIMPLE, DDS, an EPS header) is text, with
    no Unreadable; a PNG whose header is broken is reported as unreadable."""
    texts = {"p1.txt": b"P1 notes\nall clean\n", "p6.txt": b"P6 2 2 255\nxx", "simple.txt": b"SIMPLE  =   T / ok\n",
             "dds.txt": b"DDS |notes\n", "fig.eps": b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage\n",
             "bm.csv": b"BMI,score\n21,3\n"}
    assert found(put(tmp_path / "texts", texts), [text_seed("GCT-LEAK-FIX-NOPE-10"), MARKER_SEED]) == {}
    broken = bytearray(png(picture(MARKER)))
    broken[29] ^= 0xFF  # the IHDR CRC
    with pytest.raises(Unreadable) as e:
        found(put(tmp_path / "png", {"a.png": bytes(broken)}), [MARKER_SEED])
    assert [p.split(" (")[0] for p in e.value.places] == ["a.png"]


def test_comments_and_odd_hex_in_string_tokens(tmp_path):
    """M1 and M2: a "(" inside a % comment does not swallow the tokens after it (a superseded UTF-16BE /Info /Title
    found by the raw token pass), and an odd-length hex string gets its final 0 without losing the rest of the file."""
    title, odd, later = "GCT-LEAK-FIX-TITLE-11", "GCT-LEAK-FIX-ODD-10", "GCT-LEAK-FIX-LATER-11"
    pdf = assemble([b"<< /Type /Catalog /Pages 2 0 R >>\n% made by tool (beta", b"<< /Type /Pages /Kids [] /Count 0 >>",
                    b"<< /Title %s >>" % _utf16(title)], info=3, update={3: b"<< /Title (clean) >>"})
    odd_hex = odd.encode().hex()[:-1].encode()  # "...3130" written "...313": the final 0 is implied
    pdf2 = page_pdf(b"BT /F1 12 Tf 72 700 Td <%s> Tj ET (%s) Tj" % (odd_hex, later.encode()))
    result = found(put(tmp_path, {"a.pdf": pdf, "b.pdf": pdf2}), [text_seed(v) for v in (title, odd, later)])
    assert where(result, title, "a.pdf: string tokens")
    assert where(result, odd, "b.pdf: object 4 stream string tokens")
    assert where(result, later, "b.pdf: object 4 stream string tokens")


def test_guards_name_the_page_images_xref_section_and_data_uri(tmp_path, monkeypatch):
    """I2 (round 2): when listing a page's images or an xref section's objects raises, or a data: URI does not
    decode, Unreadable names that place and the rest of the file is read."""
    import pdfplumber.page
    from pdfminer.pdfdocument import PDFXRef

    seed = "GCT-LEAK-FIX-REST-12"
    put(tmp_path, {"a.pdf": page_pdf(b"BT /F1 12 Tf 72 700 Td (%s) Tj ET" % seed.encode()),
                   "b.html": b'<!doctype html><a href="data:text/plain;base64,QUJDR">x</a>'})  # 5 characters

    def refuse(*a, **k):
        raise RuntimeError("refused by the test")
    monkeypatch.setattr(pdfplumber.page.Page, "images", property(refuse))
    monkeypatch.setattr(PDFXRef, "get_objids", refuse)
    with pytest.raises(Unreadable) as e:
        found(tmp_path, [text_seed(seed)])
    assert [p.split(" (")[0] for p in e.value.places] == ["a.pdf: page 1 images", "a.pdf: xref section 1",
                                                          "b.html > data URI 1"], e.value.places
    assert where(e.value.found, seed, "a.pdf: page 1 text")


def objstm_pdf(member: bytes, update: dict) -> bytes:
    """Catalog 1, pages 2, object 5 (member) inside the Flate object stream 4, an xref stream 6; update {n: body}
    appends an incremental update section replacing those objects, 4 as an object stream holding body as object 5
    (as Codex's round 3 probe)."""
    out, offsets = bytearray(b"%PDF-1.5\n"), {}

    def objstm(body):
        return _stream(b"/Type /ObjStm /N 1 /First 4 /Filter /FlateDecode", zlib.compress(b"5 0 " + body))
    for n, body in ((1, b"<< /Type /Catalog /Pages 2 0 R >>"), (2, b"<< /Type /Pages /Kids [] /Count 0 >>"),
                    (4, objstm(member))):
        offsets[n] = len(out)
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    offsets[6] = len(out)
    entries = b"".join(bytes([2]) + (4).to_bytes(4, "big") + bytes(2) if n == 5 else
                       bytes([1]) + offsets[n].to_bytes(4, "big") + bytes(2) if n in offsets else
                       bytes([0]) + bytes(4) + b"\xff\xff" for n in range(7))
    out += b"6 0 obj\n" + _stream(b"/Type /XRef /Size 7 /Root 1 0 R /W [1 4 2]", entries) + b"\nendobj\n"
    out += b"startxref\n%d\n%%%%EOF\n" % offsets[6]
    new = {}
    for n, body in update.items():
        new[n] = len(out)
        out += b"%d 0 obj\n" % n + (objstm(body) if n == 4 else body) + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n" + b"".join(b"%d 1\n%010d 00000 n \n" % (n, o) for n, o in sorted(new.items()))
    out += b"trailer\n<< /Size 7 /Root 1 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (offsets[6], xref)
    return bytes(out)


def test_object_stream_members_are_parsed_as_objects(tmp_path):
    """B1 (round 3): every member of every object stream is parsed as an object, so a name's #XX escapes are undone:
    a member an update superseded in a current object stream, and a member of an object stream the update itself
    superseded."""
    seed = "GCT-LEAK-FIX-OBJSTM-13"
    name = b"<< /Secret /" + b"".join(b"#%02X" % c for c in seed.encode()) + b" >>"
    put(tmp_path, {"member.pdf": objstm_pdf(name, {5: b"<< /Secret /clean >>"}),
                   "container.pdf": objstm_pdf(name, {4: b"<< /Secret /clean >>"})})
    result = found(tmp_path, [text_seed(seed)])
    assert where(result, seed, "member.pdf: object 4 member 5"), result
    assert where(result, seed, "container.pdf: object 4 at byte"), result
    assert not where(result, seed, "container.pdf: object 4 member"), result  # the current container is clean


def test_object_headers_inside_strings_and_comments_are_not_objects(tmp_path):
    """N1 (round 3): "N G obj" inside a literal string or a % comment is not an object header (clean files give {}),
    and an unclosed "(" does not hide an orphan object after it."""
    clean = b"BT /F1 12 Tf 72 700 Td (clean) Tj ET"
    put(tmp_path / "clean", {"title.pdf": page_pdf(clean, extra=[b"<< /Title (99 0 obj stream) >>"]),
                             "comment.pdf": page_pdf(clean, extra=[b"<< /Title (ok) >>\n% 98 0 obj stream"])})
    assert found(tmp_path / "clean", [text_seed("GCT-LEAK-FIX-NOPE-10"), MARKER_SEED]) == {}
    orphan = page_pdf(clean) + b"(unclosed\n9 0 obj\n" + image_object(picture(MARKER)) + b"\nendobj\n"
    result = found(put(tmp_path / "orphan", {"a.pdf": orphan}), [MARKER_SEED])
    assert where(result, "GCT-LEAK-FIX-MARKER-08", "a.pdf: object 9 at byte"), result


def test_text_that_begins_with_a_strong_signature_is_text(tmp_path):
    """N2 (round 3): bytes with a strong image signature that do not decode as an image are text when they decode as
    UTF-8; a GIF that is neither is reported as unreadable (as the broken PNG above is)."""
    seed = "GCT-LEAK-FIX-GIFTEXT-12"
    texts = {"a.txt": b"GIF89a is a format\n", "b.txt": b"GIF87a %s\n" % seed.encode(),
             "c.txt": b"RIFF1234WEBP notes\n",
             "d.txt": b"GIF89a\x10\x00\x10\x00\x00\x00\x00,\x00\x00\x00\x00\x10\x00\x10\x00\x00\x02\x02D\x01"}  # opens, then fails to load
    result = found(put(tmp_path / "texts", texts), [text_seed(seed), MARKER_SEED])
    assert list(result) == [seed] and where(result, seed, "b.txt: text"), result
    with pytest.raises(Unreadable) as e:
        found(put(tmp_path / "gif", {"a.gif": b"GIF89a\xff\xfe\x00broken"}), [MARKER_SEED])
    assert [p.split(" (")[0] for p in e.value.places] == ["a.gif"]
