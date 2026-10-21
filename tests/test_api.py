import json
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import pytest

from gct import __version__, cli
from gct.api import app as app_module
from gct.api import server

ROOT = Path(__file__).resolve().parent.parent
INTERNAL_WORDS = ["Traceback", "sqlite", "schema_version", "published_pointer", "published_version"]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))


def call(port, path, **headers):
    """(status, headers, body). Every response is checked for CORS headers and tracebacks."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        r = OPENER.open(req, timeout=10)
    except urllib.error.HTTPError as e:
        r = e
    with r:
        body = r.read().decode()
        status, got = r.getcode(), r.headers
    assert not any(k.lower().startswith("access-control-allow") for k in got.keys())
    assert "Traceback" not in body
    if status >= 400:
        data = json.loads(body)
        assert data["status"] == "error" and data["cause"] and data["next_action"], body
        for word in INTERNAL_WORDS:
            assert word not in body, (path, word)
    return status, got, body


@pytest.fixture
def running(ws):
    srv = server.serve(ws, port=0)
    yield srv
    srv.stop()


def cookie(srv):
    return {"Cookie": f"gct_session={srv.token}"}


def full_flow(srv):
    """The AC3 and AC5 requests. Returns nothing; asserts as it goes."""
    p = srv.port
    status, headers, _ = call(p, f"/?token={srv.token}")
    assert status == 303 and headers["location"] == "/"
    set_cookie = headers["set-cookie"]
    assert set_cookie.startswith(f"gct_session={srv.token};")
    assert "HttpOnly" in set_cookie and "samesite=strict" in set_cookie.lower()
    status, headers, body = call(p, "/", **cookie(srv))
    assert status == 200 and headers["content-type"].startswith("text/html") and '<div id="root">' in body
    assert call(p, "/")[0] == 401
    assert call(p, "/?token=wrong")[0] == 401
    assert call(p, "/api/health", Authorization=f"Bearer {srv.token}")[0] == 200
    assert call(p, "/api/health", Authorization="Bearer wrong")[0] == 401
    assert call(p, "/", Host=f"evil.example:{p}", **cookie(srv))[0] == 403
    assert call(p, "/", Origin="http://evil.example", **cookie(srv))[0] == 403
    assert call(p, "/", Origin=f"http://localhost:{p}", **cookie(srv))[0] == 200
    assert call(p, "/", Host=f"localhost:{p}", **cookie(srv))[0] == 200


def test_binds_loopback_only(running):
    assert running._sock.getsockname()[0] == "127.0.0.1"
    assert running.url == f"http://127.0.0.1:{running.port}/?token={running.token}"


def test_token_cookie_host_and_origin(running):
    full_flow(running)


def test_health_names_the_published_data_version(ws, running, gct):
    status, _, body = call(running.port, "/api/health", **cookie(running))
    assert status == 200
    assert json.loads(body) == {"status": "ok", "gct_version": __version__, "workspace": str(ws.resolve()),
                                "data_version": None}
    assert gct("publish", "build").code == 0
    assert json.loads(call(running.port, "/api/health", **cookie(running))[2])["data_version"] == 1


def test_unknown_path_is_404_json(running):
    status, _, body = call(running.port, "/nothing/here", **cookie(running))
    assert status == 404 and json.loads(body)["status"] == "error"


def test_handler_exception_is_500_json_and_logged(ws, monkeypatch):
    def with_boom(root, token):
        app = app_module.create_app(root, token)

        @app.get("/boom")
        def boom():
            raise RuntimeError("secret detail in published_pointer")

        return app

    monkeypatch.setattr(server, "create_app", with_boom)
    srv = server.serve(ws, port=0)
    try:
        status, _, body = call(srv.port, "/boom", **cookie(srv))
    finally:
        srv.stop()
    data = json.loads(body)
    assert status == 500 and data["cause"] == "Something unexpected went wrong."
    logs = list((ws / "logs").glob("error-*.log"))
    assert len(logs) == 1 and str(logs[0]) in data["next_action"]
    assert "secret detail" in logs[0].read_text() and "secret detail" not in body


def test_token_appears_once_in_output(tmp_path, monkeypatch, capfd):
    """Only the launch URL printed by gct serve --json carries the token; no log line does."""
    # No ws fixture here: it captures through capsys, which cannot be combined with capfd.
    assert cli.main(["workspace", "init", str(tmp_path / "ws")]) == 0
    monkeypatch.setenv("GCT_WORKSPACE", str(tmp_path / "ws"))
    capfd.readouterr()
    seen = {}

    def wait(self):
        seen["token"] = self.token
        full_flow(self)

    monkeypatch.setattr(server.Server, "wait", wait)
    assert cli.main(["serve", "--port", "0", "--no-open", "--json"]) == 0
    out, err = capfd.readouterr()
    data = json.loads(out)
    assert set(data) == {"status", "url", "port"} and seen["token"] in data["url"]
    assert (out + err).count(seen["token"]) == 1


def test_opens_browser_unless_no_open(ws, gct, monkeypatch):
    opened = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    monkeypatch.setattr(server.Server, "wait", lambda self: None)
    r = gct("serve", "--port", "0", "--json")
    assert r.code == 0 and opened == [r.data["url"]]
    assert gct("serve", "--port", "0", "--no-open").code == 0
    assert len(opened) == 1


def test_ctrl_c_exits_quietly(ws, gct, monkeypatch):
    def interrupted(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(server.Server, "wait", interrupted)
    r = gct("serve", "--port", "0", "--no-open")
    assert r.code == 0 and "Traceback" not in r.err


def test_no_host_option(gct):
    help_text = subprocess.run([sys.executable, "-m", "gct", "serve", "--help"], capture_output=True, text=True).stdout
    assert "--port" in help_text and "host" not in help_text.lower()
    assert gct("serve", "--host", "0.0.0.0").code == 2


def test_nothing_mentions_cors():
    for path in (ROOT / "gct").rglob("*.py"):
        assert "cors" not in path.read_text().lower(), path

