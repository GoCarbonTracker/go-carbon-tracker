"""Story 7.4: crops.cut, the evidence images of the PDF reports (and 7.5's viewer pages). Bands and whole pages are
compared with the viewer's own page endpoint (AC 2): the plain page, the three test_viewer.FRAME_CASES and a two-up
spread page."""
import hashlib
import io
import json

import pytest

from conftest import make_pdf
from test_viewer import FRAME_CASES, png, reshaped
from gct.api import server
from gct.reports import crops
from gct.workspace import registry
from gct.workspace.layout import NOT_FOUND, GctError

SLACK = 1.5 * crops.SCALE  # tests/test_viewer.py:128


def spread() -> bytes:
    """A two-up spread (7.4-P1, the Tata page 1 and 177 pattern): MediaBox 1224 by 792, CropBox the right half, the
    word in the right half."""
    import pypdfium2

    pdf = pypdfium2.PdfDocument(make_pdf([{"text": [(800, 300, "Scope")]}], size=(1224, 792)))
    pdf[0].set_cropbox(612, 0, 1224, 792)
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()
    return out.getvalue()


PAGES = {"plain": lambda: make_pdf([{"text": [(200, 300, "Scope")]}]),
         **{k: (lambda c=c: reshaped(c)) for k, c in FRAME_CASES.items()}, "spread": spread}


def entry(id_, sha, page=1, boxes=None, **kw):
    return {"id": id_, "kind": "claim", "document_id": 1, "sha256": sha, "page": page, "boxes": boxes, "sheet": None,
            "cell": None, "header": None, "row": None, "marked": None, **kw}


def cell(id_, sha):
    return {**entry(id_, sha, page=None), "sheet": "s", "cell": "B2", "header": ["a", "b"], "row": ["1", "2"],
            "marked": 1}


def image(data):
    from PIL import Image

    return Image.open(io.BytesIO(data)).convert("RGB")


def ink(im):
    """The bounding box of the dark pixels, the outline's (luminance about 66) masked first."""
    from PIL import Image, ImageChops

    ring = ImageChops.difference(im, Image.new("RGB", im.size, crops.OUTLINE)).convert("L").point(
        lambda v: 255 if v == 0 else 0)
    im = im.copy()
    im.paste((255, 255, 255), (0, 0, *im.size), ring)
    return im.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()


def outline(band, rects):
    """The expected outline pixels, written out here: each box's rectangle grown by 2, minus every box's rectangle,
    inside the band."""
    out = set()
    for x0, y0, x1, y1 in rects:
        out |= {(x, y) for x in range(x0 - 2, x1 + 2) for y in range(y0 - 2, y1 + 2)
                if band[0] <= x < band[2] and band[1] <= y < band[3]}
    for x0, y0, x1, y1 in rects:
        out -= {(x, y) for x in range(x0, x1) for y in range(y0, y1)}
    return {(x - band[0], y - band[1]) for x, y in out}


@pytest.fixture
def page(request, ws, gct, db, make_file):
    """A workspace holding the case's one-page PDF, read and published: (root, sha256, frame, the word's box)."""
    gct("company", "add", "Acme")
    gct("doc", "add", make_file(f"{request.param}.pdf", PAGES[request.param]()), "--company", "Acme")
    gct("read")
    gct("publish", "build")
    (sha,) = [p.name for p in (ws / "files").rglob("*") if p.is_file()]
    (rel,) = db.execute("SELECT a.path FROM page p JOIN artifact a ON a.id = p.artifact_id").fetchone()
    (word,) = [w for w in json.loads((ws / rel).read_text(encoding="utf-8"))["words"] if w["text"] == "Scope"]
    frame = crops._frames(registry.stored_path(ws, sha))[0]
    return ws, sha, frame, [word["x0"], word["top"], word["x1"], word["bottom"]]


# AC 2: crops equal the viewer
@pytest.mark.parametrize("page", list(PAGES), indirect=True)
def test_a_band_and_a_whole_page_equal_the_viewer_render(page, monkeypatch):
    root, sha, frame, box = page
    renders = []
    real = crops._render
    monkeypatch.setattr(crops, "_render", lambda *a: renders.append(a[1:]) or real(*a))
    wide = [box[0] - 30, box[1] - 4, box[2] + 30, box[3] + 4]
    got = crops.cut(root, {"evidence": [entry(1, sha, boxes=[box]), entry(2, sha), entry(3, sha, boxes=[box, wide])]})
    assert sorted(renders) == [(1, 1.5), (1, 3.0)]  # three entries on one page: one render per scale
    s = server.serve(root, port=0)
    try:
        status, _, full = png(s, "/api/documents/1/pages/1.png?scale=3.0")
        assert status == 200
        assert got[2] == png(s, "/api/documents/1/pages/1.png?scale=1.5")[2]  # the whole page, byte for byte
    finally:
        s.stop()
    viewer = image(full)
    assert viewer.size == (round(frame["width"] * 3), round(frame["height"] * 3))
    left, top = frame["left"], frame["top"]
    x0, x1 = 0, frame["width"] * 3
    if page_is_spread := frame["width"] > 1.4 * frame["height"]:
        x0 = frame["width"] / 2 * 3  # the word is in the right half, so the band is that half (7.4-P1)
    for id_, boxes in ((1, [box]), (3, [box, wide])):
        band = crops._pixels((x0, (min(b[1] for b in boxes) - 24 - top) * 3, x1,
                              (max(b[3] for b in boxes) + 24 - top) * 3), viewer.size)
        rects = [crops._pixels(((b[0] - left) * 3, (b[1] - top) * 3, (b[2] - left) * 3, (b[3] - top) * 3),
                               viewer.size) for b in boxes]
        cut, want = image(got[id_]), viewer.crop(band)
        assert cut.size == (band[2] - band[0], band[3] - band[1]), (id_, cut.size, band)
        ring = outline(band, rects)
        assert ring and {cut.getpixel(p) for p in ring} == {crops.OUTLINE}
        for p in ring:  # outside the outline, the band is the viewer's pixels
            cut.putpixel(p, want.getpixel(p))
        assert cut.tobytes() == want.tobytes(), id_
        # the word's ink (outline masked) lies inside its box mapped into the band (test_viewer.py:120-132)
        bx0, by0, bx1, by1 = ((box[0] - left) * 3 - band[0], (box[1] - top) * 3 - band[1],
                              (box[2] - left) * 3 - band[0], (box[3] - top) * 3 - band[1])
        found = ink(cut)
        assert found and bx0 - SLACK <= found[0] and found[2] <= bx1 + SLACK, (id_, found, (bx0, bx1))
        assert by0 - SLACK <= found[1] and found[3] <= by1 + SLACK, (id_, found, (by0, by1))
    assert page_is_spread == (frame["width"] == 1224)


@pytest.mark.parametrize("page", ["offset"], indirect=True)
def test_forgetting_the_frame_origin_puts_the_ink_outside_the_band(page, monkeypatch):
    """AC 2: the offset case (MediaBox 100 100 712 892, frame left 100, top -100) is the one that fails if cut maps a
    box without subtracting the frame's left and top."""
    root, sha, frame, box = page
    assert (frame["left"], frame["top"]) == (100, -100)
    assert ink(image(crops.cut(root, {"evidence": [entry(1, sha, boxes=[box])]})[1]))
    real = crops._frames
    monkeypatch.setattr(crops, "_frames", lambda p: tuple({**f, "left": 0, "top": 0} for f in real(p)))
    assert ink(image(crops.cut(root, {"evidence": [entry(1, sha, boxes=[box])]})[1])) is None


def test_a_spread_band_takes_one_half_unless_the_boxes_cross_the_centre():
    frame, size = {"left": 0, "top": 0, "width": 1224, "height": 792}, (3672, 2376)
    assert crops._band(frame, [[100, 100, 200, 112]], size)[0] == (0, 228, 1836, 408)
    assert crops._band(frame, [[700, 100, 800, 112]], size)[0] == (1836, 228, 3672, 408)
    assert crops._band(frame, [[600, 100, 700, 112]], size)[0] == (0, 228, 3672, 408)
    assert crops._band({**frame, "width": 1100}, [[100, 100, 200, 112]], (3300, 2376))[0] == (0, 228, 3300, 408)


def test_pixels_clamps_then_floors_and_ceils():
    assert crops._pixels((-3.5, 1.2, 10.01, 19.99), (10, 30)) == (0, 1, 10, 20)
    assert crops._pixels((2.0, 3.0, 4.0, 5.0), (10, 10)) == (2, 3, 4, 5)
    assert crops._pixels((5.5, -1, 50, 50), (10, 10)) == (5, 0, 10, 10)


# AC 3 and 9: exactly the dataset's page entries, the cap, a missing original, the same bytes twice
@pytest.mark.parametrize("page", ["plain"], indirect=True)
def test_one_item_per_page_entry_none_for_cells_and_the_same_bytes_twice(page):
    root, sha, _, box = page
    dataset = {"evidence": [entry(4, sha, boxes=[box]), cell(5, sha), entry(7, sha), entry(9, sha, boxes=[box])]}
    first = crops.cut(root, dataset)
    assert list(first) == [4, 7, 9] and first[4] == first[9]
    assert crops.cut(root, dataset) == first
    assert crops.cut(root, {"evidence": [cell(5, sha)]}) == {}
    assert hashlib.sha256(image(first[4]).tobytes()).hexdigest()  # the image seed is computed at test time (C4a)


@pytest.mark.parametrize("page", ["plain"], indirect=True)
def test_above_the_cap_nothing_is_rendered(page, monkeypatch):
    root, sha, _, box = page
    monkeypatch.setattr(crops, "_render", lambda *a: pytest.fail("rendered above the cap"))
    many = [entry(n, sha, boxes=[box]) for n in range(1, crops.LIMIT + 2)]
    assert crops.LIMIT == 500 and crops.cut(root, {"evidence": many + [cell(999, sha)]}) == {}
    monkeypatch.undo()
    assert len(crops.cut(root, {"evidence": many[:crops.LIMIT]})) == crops.LIMIT


@pytest.mark.parametrize("page", ["plain"], indirect=True)
def test_a_missing_original_is_refused_before_any_render(page, monkeypatch):
    root, sha, _, box = page
    other = "0" * 64
    monkeypatch.setattr(crops, "_render", lambda *a: pytest.fail("rendered before the check"))
    with pytest.raises(GctError) as e:
        crops.cut(root, {"evidence": [entry(1, sha, boxes=[box]), {**entry(2, other), "document_id": 7}]})
    assert (e.value.code, e.value.cause, e.value.next_action) == (
        NOT_FOUND, "The stored copy of document 7 is missing from the workspace.",
        "Add the same file again with gct doc add to restore it, then run the report again.")
