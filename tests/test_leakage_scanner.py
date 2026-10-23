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

from leakage import MARKER, found
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


def text_seed(value, kind="document text"):
    return {"name": value, "kind": kind, "expect": "complete_only", "value": value}


CROP_A, CROP_B, RENDER, HASHED = crop((30, 20)), crop((24, 18)), png(picture(GREY, (30, 30))), b"shareable bytes\n"
SEEDS = [text_seed(v) for v in V.values()] + [
    {"name": "GCT-LEAK-SCAN-HASH-25", "kind": "file hash", "expect": "complete_only",
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
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 12 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


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
    V["shared"]: ["book.xlsx > xl/sharedStrings.xml: XML", "book.xlsx > xl/sharedStrings.xml: unescaped"],
    V["inline"]: ["book.xlsx > xl/worksheets/sheet1.xml: XML"],
    V["sheet"]: ["book.xlsx > xl/workbook.xml: XML"],
    V["core"]: ["book.xlsx > docProps/core.xml: XML"],
    V["comment"]: ["book.xlsx > xl/comments1.xml: XML"],
    V["csv"]: ["table.csv: text"],
    V["case"]: ["table.csv: text"],
    V["utf16"]: ["table16.csv: text"],
    V["json"]: ["data.json: JSON strings"],
    V["entity"]: ["page.html: unescaped"],
    V["datajson"]: ["page.html > data URI 1: JSON strings"],
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
MARKED = ["doc.pdf: object 6 image", "doc.pdf: object 8 image", "doc.pdf: page 1 inline image",
          "book.xlsx > xl/media/image1.png", "page.html > data URI 2"]
for _name in IMAGES:
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
    seeds = [{"name": "GCT-LEAK-SCAN-SCENE-01", "kind": "image", "expect": "complete_only", "value": pixels(scene)}]
    assert found(tmp_path, seeds) == {"GCT-LEAK-SCAN-SCENE-01": [
        "double.png: marker colour", "half.png: marker colour", "lossless.png: marker colour",
        "lossless.png: pixel hash", "lossy.jpg: marker colour"]}
    assert found(tmp_path / "half.png", seeds) == {"GCT-LEAK-SCAN-SCENE-01": ["half.png: marker colour"]}


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
    for kind in ("document text", "contributor", "credential", "path"):
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
    with pytest.raises(ValueError, match="unknown kind"):
        found(tmp_path, [text_seed("GCT-LEAK-CANARY-01", kind="supplier")])
    with pytest.raises(ValueError, match="hex digest"):
        found(tmp_path, [{"name": "h", "kind": "file hash", "expect": "complete_only", "value": "GCT-LEAK-CANARY-01"}])
    with pytest.raises(ValueError, match="hex digest"):
        found(tmp_path, [{"name": "i", "kind": "image", "expect": "complete_only", "value": None,
                          "render_sha256": "not-a-digest"}])


def test_seed_lists_in_the_7_1_shape_are_accepted_together(tmp_path):
    """AC 5: 7.1's seed names and kinds (G) beside 7.7's own GCT-LEAK-CANARY- additions, hex digests exempt, are
    accepted together; on an empty folder nothing is found. (Part B repeats this with report_fixture.SEEDS.)"""
    digest = hashlib.sha256(b"x").hexdigest()
    seeds_7_1 = [text_seed("GCT-PRIVATE-CANARY-01"), text_seed("GCT-PRIVATE-CANARY-02", "contributor"),
                 text_seed("sk-GCTFAKEKEY0001", "credential"), text_seed("GCT-PATH-CANARY", "path"),
                 {"name": "GCT-PRIVATE-CANARY-03", "kind": "image", "expect": "complete_only", "value": "marker",
                  "render_sha256": digest.upper()},
                 {"name": "GCT-PRIVATE-CANARY-04", "kind": "file hash", "expect": "complete_only",
                  "value": hashlib.sha256(b"y").hexdigest()}]
    seeds_7_7 = [text_seed("GCT-LEAK-CANARY-01"), text_seed("GCT-LEAK-ROOT-01", "path"),
                 {"name": "GCT-LEAK-CANARY-02", "kind": "image", "expect": "complete_only", "value": digest[::-1]}]
    assert found(tmp_path, seeds_7_1 + seeds_7_7) == {}
    (tmp_path / "x.bin").write_bytes(b"x")
    assert found(tmp_path, seeds_7_1 + seeds_7_7) == {"GCT-PRIVATE-CANARY-03": ["x.bin: file hash"]}
