import functools
import io
import json
import os
import secrets
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from gct import __version__
from gct.workspace import layout, published, registry, store

COOKIE = "gct_session"
OPEN_LAUNCH_URL = "Open the address printed by gct serve."
VIEWER = Path(__file__).resolve().parent.parent / "viewer_dist"  # the committed build (viewer/README.md)
SCALES = {1.5, 3.0}
BACK = "Go back to the start page at /."
# pdfium is not thread-safe and FastAPI runs these handlers in a thread pool.
_PDFIUM = threading.Lock()

CLAIMS_SQL = """
SELECT c.id, c.locator, c.metric_text, c.value_text, c.unit_text, c.period_label, c.period_kind, c.period_start,
       c.period_end, c.period_state, c.reporting_boundary, c.boundary_detail, c.boundary_state, e.page_number AS page, e.boxes, e.source_match, e.source_match_reason
FROM claim c JOIN evidence_ref e ON e.claim_version_id = c.claim_version_id
WHERE c.document_id = ? ORDER BY e.page_number IS NULL, e.page_number, c.id, e.id
"""


def error(code: int, cause: str, next_action: str) -> JSONResponse:
    """The same error shape as the CLI's --json output."""
    return JSONResponse({"status": "error", "cause": cause, "next_action": next_action}, status_code=code)


def _same(given: str | None, token: str) -> bool:
    return given is not None and secrets.compare_digest(given.encode(), token.encode())


def _current(root: Path) -> tuple[int, Path] | None:
    conn = store.connect(root / layout.DB_NAME)
    try:
        return published.current_version(conn, root)
    finally:
        conn.close()


def _data_version(root: Path) -> int | None:
    current = _current(root)
    return None if current is None else current[0]


def _query(root: Path, sql: str, *params) -> list[dict] | None:
    """Rows from the current published version, or None before the first build."""
    current = _current(root)
    if current is None:
        return None
    conn = published.open_version(current[1])
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


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


def _write_once(path: Path, data: bytes) -> None:
    """Write to a temporary file in the same folder, then rename: a half-written file is never served."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".incoming-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def create_app(root: Path, token: str) -> FastAPI:
    root = Path(root)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        port = request.scope["server"][1]  # the port actually bound, also when started on port 0
        if request.headers.get("host") not in {f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost"}:
            return error(403, "This service only answers requests addressed to this computer.", OPEN_LAUNCH_URL)
        origin = request.headers.get("origin")
        if origin is not None and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            return error(403, "Requests from other web pages are not accepted.", OPEN_LAUNCH_URL)
        if request.url.path == "/" and "token" in request.query_params:
            if not _same(request.query_params["token"], token):
                return error(401, "That address has an old or wrong session key.", OPEN_LAUNCH_URL)
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
            return response
        bearer = request.headers.get("authorization", "")
        if not (_same(request.cookies.get(COOKIE), token)
                or (bearer.startswith("Bearer ") and _same(bearer[len("Bearer "):], token))):
            return error(401, "This browser has not been let in yet.", OPEN_LAUNCH_URL)
        try:
            return await call_next(request)
        except Exception:
            log = layout.write_error_log(root)
            return error(500, "Something unexpected went wrong.", f"Details were written to {log}.")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        if exc.status_code == 404:
            return error(404, f"There is nothing at {request.url.path}.", BACK)
        return error(exc.status_code, str(exc.detail), BACK)

    @app.get("/")
    def home():
        # Checked on every load: after an upgrade it names new asset files.
        return FileResponse(VIEWER / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/assets", StaticFiles(directory=VIEWER / "assets", check_dir=False), name="assets")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "gct_version": __version__, "workspace": str(root.resolve()),
                "data_version": _data_version(root)}

    @app.get("/api/companies")
    def companies():
        rows = _query(root, "SELECT id, name FROM company ORDER BY name, id")
        return {"status": "ok", "data_version": _data_version(root), "companies": rows or []}

    @app.get("/api/companies/{company_id:int}/documents")
    def documents(company_id: int):
        if not _query(root, "SELECT id FROM company WHERE id = ?", company_id):
            return error(404, f"There is no company {company_id} in the published data.", BACK)
        rows = _query(root, "SELECT id, logical_name, version, kind, file_type FROM document"
                            " WHERE company_id = ? ORDER BY logical_name, version", company_id)
        return {"status": "ok", "company": company_id, "documents": rows}

    def pdf_of(doc_id: int) -> dict | JSONResponse:
        rows = _query(root, "SELECT id, company_id, logical_name, version, sha256, file_type FROM document"
                            " WHERE id = ?", doc_id)
        if not rows:
            return error(404, f"There is no document {doc_id} in the published data.", BACK)
        if rows[0]["file_type"] != "pdf":
            return error(404, f"Document {doc_id} is not a PDF, so it has no pages to show.", BACK)
        return {**rows[0], "path": registry.stored_path(root, rows[0]["sha256"])}

    @app.get("/api/documents/{doc_id:int}")
    def document(doc_id: int):
        d = pdf_of(doc_id)
        if isinstance(d, JSONResponse):
            return d
        pages = [{k: f[k] for k in ("left", "top", "width", "height")} for f in _frames(d["path"])]
        return {"status": "ok", "document": {k: d[k] for k in ("id", "company_id", "logical_name", "version")},
                "page_count": len(pages), "pages": pages}

    @app.get("/api/documents/{doc_id:int}/pages/{number:int}.png")
    def page_png(doc_id: int, number: int, scale: str = "1.5"):
        try:
            value = float(scale)
        except ValueError:
            value = None
        if value not in SCALES:
            return error(400, f"The scale {scale} is not offered.", "Ask for scale=1.5 (the default) or scale=3.0.")
        d = pdf_of(doc_id)
        if isinstance(d, JSONResponse):
            return d
        # ponytail: no eviction in M1 (W2); the cache grows with every page and scale viewed.
        cached = root / "artifacts" / "pages" / d["sha256"] / f"{number}@{value}.png"
        if not cached.is_file():
            if not 1 <= number <= len(_frames(d["path"])):  # cached per file: no page is opened twice
                return error(404, f"Document {doc_id} has no page {number}.", BACK)
            _write_once(cached, _render(d["path"], number, value))
        return FileResponse(cached, media_type="image/png")

    @app.get("/api/documents/{doc_id:int}/claims")
    def claims(doc_id: int):
        if not _query(root, "SELECT id FROM document WHERE id = ?", doc_id):
            return error(404, f"There is no document {doc_id} in the published data.", BACK)
        if int(_query(root, "SELECT value FROM meta WHERE key = 'projection_schema'")[0]["value"]) < 4:
            return error(409, "The published data was built by an older gct and has no period dates.",
                         "Build a fresh version with: gct publish build")
        # ponytail: one row per evidence ref; M1 stages write one ref per claim version.
        rows = _query(root, CLAIMS_SQL, doc_id)
        return {"status": "ok", "document": doc_id, "claims": [
            {**r, "boxes": None if r["boxes"] is None else json.loads(r["boxes"])} for r in rows]}

    return app
