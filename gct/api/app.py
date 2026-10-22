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
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from gct import __version__
from gct.workspace import layout, lock, published, registry, runs, store
from gct.workspace.layout import GctError

COOKIE = "gct_session"
OPEN_LAUNCH_URL = "Open the address printed by gct serve."
VIEWER = Path(__file__).resolve().parent.parent / "viewer_dist"  # the committed build (viewer/README.md)
SCALES = {1.5, 3.0}
BACK = "Go back to the start page at /."
HTTP = {layout.USAGE: 400, layout.NOT_FOUND: 404, layout.REFUSED: 409}
CORRECTION_FIELDS = ("value", "unit", "metric", "period_label", "contributor", "capacity", "rationale")
# The JSON body of each review write: (the record's name in messages, text fields, whole-number fields, required fields;
# required are the ones the CLI command requires before its stage function runs).
LEDGER = ("version", "outcome", "scope", "conclusion", "contributor", "capacity")
BODIES = {
    "correction": ("a correction", CORRECTION_FIELDS, (), ()),
    "company": ("a company confirmation", (*LEDGER[1:], "evidence_note", "date"),
                ("version", "evidence_document", "evidence_page"), LEDGER),
    "auditor": ("an auditor review", (*LEDGER[1:], "evidence_note", "date"),
                ("version", "evidence_document", "evidence_page"), LEDGER),
    "flag": ("a reviewer flag", ("decision", "rationale", "contributor", "capacity"), ("version",),
             ("version", "decision", "rationale", "contributor", "capacity")),
    "highlight": ("a highlight", ("note", "contributor", "capacity"), ("version",),
                  ("version", "note", "contributor", "capacity")),
    "adjudication": ("an adjudication", ("state", "rationale", "procedure", "counter_note", "follow_up", "closure_reason",
                                         "contributor", "capacity"),
                     ("first", "second", "counter_document", "counter_page"),
                     ("first", "second", "state", "rationale", "procedure", "contributor", "capacity")),
}
# pdfium is not thread-safe and FastAPI runs these handlers in a thread pool.
_PDFIUM = threading.Lock()

CLAIMS_SQL = """
SELECT c.id, c.locator, c.metric_text, c.value_text, c.unit_text, c.period_label, c.period_kind, c.period_start,
       c.period_end, c.period_state, c.reporting_boundary, c.boundary_detail, c.boundary_state, e.page_number AS page, e.boxes, e.source_match, e.source_match_reason,
       c.boundary_label, c.claim_state, c.version_method, c.correction, c.needs_re_review
FROM claim c JOIN evidence_ref e ON e.claim_version_id = c.claim_version_id
WHERE c.document_id = ? ORDER BY e.page_number IS NULL, e.page_number, c.id, e.id
"""


def error(code: int, cause: str, next_action: str) -> JSONResponse:
    """The same error shape as the CLI's --json output."""
    return JSONResponse({"status": "error", "cause": cause, "next_action": next_action}, status_code=code)


async def _body(request: Request, kind: str) -> dict | JSONResponse:
    """The JSON object of one write, its fields of the right types and the required ones present, else the error."""
    what, text, numbers, required = BODIES[kind]
    name = what.split(" ", 1)[1]
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        return error(415, f"{what.capitalize()} is sent as JSON.", "Send the fields as a JSON object.")
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return error(400, f"The {name} is not a JSON object.", "Send the fields as a JSON object.")
    bad = [k for k in text if k in body and not isinstance(body[k], str)]
    if bad:
        return error(400, f"The {name} field {bad[0]} is not text.",
                     'Send each field as a JSON string, for example "value": "1,300".')
    # bool is an int in Python; true and false are not ids, versions or pages.
    bad = [k for k in numbers if k in body and (not isinstance(body[k], int) or isinstance(body[k], bool))]
    if bad:
        return error(400, f"The {name} field {bad[0]} is not a whole number.",
                     f'Send it as a JSON number, for example "{bad[0]}": 12.')
    missing = [k for k in required if k not in body]
    if missing:
        return error(400, f"The {name} field {missing[0]} is missing.",
                     f"Send every field the command needs: {', '.join(required)}.")
    return body


async def _object(request: Request, what: str) -> dict | JSONResponse:
    """The JSON object of a read sent as a POST body (story 6.1), else the error as _body gives it."""
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        return error(415, f"{what} is sent as JSON.", "Send the fields as a JSON object.")
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return error(400, f"{what} is not a JSON object.", "Send the fields as a JSON object.")
    return body


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
        by_bearer = bearer.startswith("Bearer ") and _same(bearer[len("Bearer "):], token)
        if not (by_bearer or _same(request.cookies.get(COOKIE), token)):
            return error(401, "This browser has not been let in yet.", OPEN_LAUNCH_URL)
        # A change is accepted with the token itself, or with the cookie from a page this service served (its Origin).
        if request.method not in ("GET", "HEAD") and not by_bearer and origin is None:
            return error(403, "A change must come from the viewer page itself.", OPEN_LAUNCH_URL)
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
        if int(_query(root, "SELECT value FROM meta WHERE key = 'projection_schema'")[0]["value"]) < 5:
            return error(409, "The published data was built by an older gct and has no claim states or corrections.",
                         "Build a fresh version with: gct publish build")
        # ponytail: one row per evidence ref; M1 stages write one ref per claim version.
        rows = _query(root, CLAIMS_SQL, doc_id)
        return {"status": "ok", "document": doc_id, "claims": [
            {**r, **{k: None if r[k] is None else json.loads(r[k]) for k in ("boxes", "correction", "needs_re_review")}}
            for r in rows]}

    @app.get("/api/claims/{claim_id:int}/history")
    def claim_history(claim_id: int):
        # The published version decides which claims are shown; their history is read from the workspace itself.
        if not _query(root, "SELECT id FROM claim WHERE id = ?", claim_id):
            return error(404, f"There is no claim {claim_id} in the published data.", BACK)
        from gct.stages import correct, highlight  # only these endpoints pay for the stages

        conn = store.connect(root / layout.DB_NAME)
        try:
            h = correct.history(conn, claim_id)
            for v in h["versions"]:  # story 5.4: correct.history is story 5.2's, so highlights are added here
                v["highlights"] = highlight.entries(conn, v["id"])
            return {"status": "ok", **h}
        finally:
            conn.close()

    @app.get("/api/companies/{company_id:int}/candidates")
    def candidates(company_id: int):
        rows = _query(root, "SELECT name FROM company WHERE id = ?", company_id)
        if not rows:
            return error(404, f"There is no company {company_id} in the published data.", BACK)
        from gct.stages import adjudicate

        conn = store.connect(root / layout.DB_NAME)
        try:
            return {"status": "ok", "company": company_id, **adjudicate.listed(conn, rows[0]["name"])}
        except GctError as e:
            return error(HTTP[e.code], e.cause, e.next_action)
        finally:
            conn.close()

    # Tables and Graphs (story 6.1): every read resolves the published version once and runs all its queries on that
    # one file (F2), never through _query, which resolves the current version again on each call.
    def _pinned(data_version, read) -> dict | JSONResponse:
        from gct.stages import view

        conn = store.connect(root / layout.DB_NAME)
        try:
            _, pconn = view.pinned(conn, root, data_version)
        except GctError as e:
            return error(HTTP[e.code], e.cause, e.next_action)
        finally:
            conn.close()
        try:
            return read(pconn)
        except GctError as e:
            return error(HTTP[e.code], e.cause, e.next_action)
        finally:
            pconn.close()

    @app.post("/api/records")
    async def records(request: Request):
        body = await _object(request, "A records request")
        if isinstance(body, JSONResponse):
            return body
        from gct.stages import view

        unknown = sorted(set(body) - set(view.REQUEST))
        if unknown:
            return error(400, f"A records request has no field {unknown[0]}.", f"Send only: {', '.join(view.REQUEST)}.")
        pin = body.get("data_version")
        if pin is not None and (not isinstance(pin, int) or isinstance(pin, bool)):
            return error(400, "The data version is not a whole number.", 'Send it as a JSON number, for example "data_version": 3.')
        return await run_in_threadpool(_pinned, pin, lambda pconn: view.answer(
            pconn, body.get("filter", {}), body.get("shape", "table"), body.get("offset", 0),
            body.get("limit", view.LIMIT), body.get("sort"), body.get("claim_ids")))

    @app.get("/api/documents/{doc_id:int}/cells")
    def cells(doc_id: int, sheet: str | None = None, cell: str | None = None, data_version: str | None = None):
        # Typed as text: a missing or malformed value gets gct's own refusal, not FastAPI's 422.
        if data_version is not None and not data_version.isdigit():
            return error(400, "The data version is not a whole number.", "Ask with data_version=N, for example 3.")
        from gct.stages import view

        return _pinned(None if data_version is None else int(data_version),
                       lambda pconn: view.cells(pconn, root, doc_id, sheet, cell))

    def _write(record) -> dict | JSONResponse:
        """record(conn), the same function as the CLI command, under the workspace lock, then a new published
        version."""
        try:
            held = lock.hold(root)
        except GctError as e:
            return error(409, e.cause, e.next_action)
        conn = store.connect(root / layout.DB_NAME)
        try:
            r = record(conn)
            with runs.run(conn, "publish build") as run_id:
                v = published.build(conn, root)
                runs.event(conn, run_id, "output", stage="publish", item=str(v["version"]))
        except GctError as e:
            return error(HTTP[e.code], e.cause, e.next_action)
        finally:
            conn.close()
            lock.release(held)
        return {"status": "ok", **r, "data_version": v["version"]}

    @app.post("/api/claims/{claim_id:int}/corrections")
    async def correct_claim(claim_id: int, request: Request):
        body = await _body(request, "correction")
        if isinstance(body, JSONResponse):
            return body
        from gct.stages import correct

        return await run_in_threadpool(_write, lambda conn: correct.correct(
            conn, claim_id, body.get("contributor"), body.get("capacity"), body.get("rationale"),
            value_text=body.get("value"), unit_text=body.get("unit"), metric_text=body.get("metric"),
            period_label=body.get("period_label")))

    async def _ledger(claim_id: int, request: Request, ledger: str):
        body = await _body(request, ledger)
        if isinstance(body, JSONResponse):
            return body
        from gct.stages import review

        return await run_in_threadpool(_write, lambda conn: review.record(
            conn, root, ledger, claim_id, body["version"], body["outcome"], body["scope"], body["conclusion"],
            body["contributor"], body["capacity"], body.get("evidence_document"), body.get("evidence_page"),
            body.get("evidence_note"), body.get("date")))

    @app.post("/api/claims/{claim_id:int}/company-confirmations")
    async def company_confirmation(claim_id: int, request: Request):
        return await _ledger(claim_id, request, "company")

    @app.post("/api/claims/{claim_id:int}/auditor-reviews")
    async def auditor_review(claim_id: int, request: Request):
        return await _ledger(claim_id, request, "auditor")

    @app.post("/api/claims/{claim_id:int}/flags")
    async def flag(claim_id: int, request: Request):
        body = await _body(request, "flag")
        if isinstance(body, JSONResponse):
            return body
        from gct.stages import adjudicate

        do = {"raised": adjudicate.raise_flag, "withdrawn": adjudicate.withdraw_flag}.get(body["decision"])
        if do is None:
            return error(400, f"The reviewer flag decision {body['decision']} is not raised or withdrawn.",
                         'Send "decision": "raised" to raise a flag or "withdrawn" to withdraw yours.')
        return await run_in_threadpool(_write, lambda conn: {"flag": do(
            conn, claim_id, body["version"], body["rationale"], body["contributor"], body["capacity"])})

    @app.post("/api/claims/{claim_id:int}/highlights")
    async def highlight_claim(claim_id: int, request: Request):
        body = await _body(request, "highlight")
        if isinstance(body, JSONResponse):
            return body
        from gct.stages import highlight

        return await run_in_threadpool(_write, lambda conn: highlight.record(
            conn, claim_id, body["version"], body["note"], body["contributor"], body["capacity"]))

    @app.post("/api/adjudications")
    async def adjudication(request: Request):
        body = await _body(request, "adjudication")
        if isinstance(body, JSONResponse):
            return body
        from gct.stages import adjudicate

        return await run_in_threadpool(_write, lambda conn: adjudicate.record(
            conn, root, body["first"], body["second"], body["state"], body["rationale"], body["procedure"],
            body["contributor"], body["capacity"], body.get("counter_document"), body.get("counter_page"),
            body.get("counter_note"), body.get("follow_up"), body.get("closure_reason")))

    return app
