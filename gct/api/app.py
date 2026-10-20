import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException

from gct import __version__
from gct.workspace import layout, published, store

COOKIE = "gct_session"
OPEN_LAUNCH_URL = "Open the address printed by gct serve."


def error(code: int, cause: str, next_action: str) -> JSONResponse:
    """The same error shape as the CLI's --json output."""
    return JSONResponse({"status": "error", "cause": cause, "next_action": next_action}, status_code=code)


def _same(given: str | None, token: str) -> bool:
    return given is not None and secrets.compare_digest(given.encode(), token.encode())


def _data_version(root: Path) -> int | None:
    conn = store.connect(root / layout.DB_NAME)
    try:
        current = published.current_version(conn, root)
    finally:
        conn.close()
    return None if current is None else current[0]


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
            return error(404, f"There is nothing at {request.url.path}.", "Go back to the start page at /.")
        return error(exc.status_code, str(exc.detail), "Go back to the start page at /.")

    @app.get("/", response_class=HTMLResponse)
    def home():
        version = _data_version(root)
        data = "no published version yet" if version is None else f"published data version {version}"
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>GoCarbonTracker</title></head><body>"
            f"<h1>GoCarbonTracker</h1><p>gct {__version__}, {data}.</p>"
            "<p>The viewer is not built yet.</p></body></html>"
        )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "gct_version": __version__, "workspace": str(root.resolve()),
                "data_version": _data_version(root)}

    return app
