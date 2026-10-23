"""Page frames and page renders (AD-16, story 7.4): moved unchanged from gct/api/app.py, so the viewer's page images
and the report crops come from one renderer and cannot disagree."""
import functools
import io
import threading
from pathlib import Path

# pdfium is not thread-safe and FastAPI runs these handlers in a thread pool.
_PDFIUM = threading.Lock()


@functools.lru_cache(maxsize=16)  # the path is named by the file's sha256, so its frames never change
def _frames(path: Path) -> tuple[dict, ...]:
    """The frame of each page, used for both the page sizes and the render. It is pdfplumber's: the read stage
    stores boxes in it, so it is taken from pdfplumber rather than recomputed. It covers the MediaBox, whatever
    the CropBox says, and need not start at 0, 0 (left, top). pdf_box is the same rectangle in PDF space, the
    MediaBox as pdfplumber resolved it (inherited from the page tree too), for the renderer to crop to."""
    import pdfplumber  # only the page endpoints pay for it
    from pdfplumber.utils import resolve_all

    with pdfplumber.open(path) as pdf:
        out = []
        for page in pdf.pages:
            left, top, _, _ = page.bbox
            x0, y0, x1, y1 = resolve_all(page.page_obj.attrs["MediaBox"])
            out.append({"left": round(left, 2), "top": round(top, 2), "width": round(page.width, 2),
                        "height": round(page.height, 2),
                        "pdf_box": (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))})
            page.close()
        return tuple(out)


def _render(path: Path, number: int, scale: float) -> bytes:
    """One page as PNG at scale times 72 dpi, covering exactly the page's frame."""
    import pypdfium2

    box = _frames(path)[number - 1]["pdf_box"]
    with _PDFIUM:
        pdf = pypdfium2.PdfDocument(path)
        try:
            page = pdf[number - 1]
            try:
                page.set_cropbox(*box)  # pdfium renders the CropBox; in memory only, nothing is saved
                out = io.BytesIO()
                page.render(scale=scale).to_pil().save(out, "PNG")
                return out.getvalue()
            finally:
                page.close()
        finally:
            pdf.close()
