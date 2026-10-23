import hashlib
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from conftest import PDF
from gct.stages import version_of
from gct.workspace import intake

CSV = b"a,b\n1,2\n"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def files_on_disk(ws):
    return sorted(str(p.relative_to(ws)) for p in (ws / "files").rglob("*"))


def row_counts(db):
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def events(gct, kind=None):
    run_id = gct("run", "list", "--json").data["runs"][0]["id"]
    shown = gct("run", "show", run_id, "--json").data
    assert shown["command"] == "doc add"
    return [e for e in shown["events"] if kind is None or e["kind"] == kind]


@pytest.fixture
def acme(ws, gct):
    gct("company", "add", "Acme")
    return ws


@pytest.fixture
def web():
    """A local HTTP server on 127.0.0.1. url(path) gives an address; hits lists the paths requested."""
    hits, routes = [], {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            code, headers, body = routes.get(self.path, (404, {}, b"not here"))
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = lambda path: f"http://127.0.0.1:{srv.server_port}{path}"  # noqa: E731
    routes.update({
        "/r.pdf": (200, {"Content-Type": "application/pdf"}, PDF),
        "/r2.pdf": (200, {}, PDF + b"2"),
        "/big.pdf": (200, {}, PDF + b"x" * 1000),
        "/page.html": (200, {"Content-Type": "text/html"}, b"<html><body>Annual report</body></html>"),
        "/data.csv": (200, {}, CSV),
        "/hop": (302, {"Location": url("/r2.pdf")}, b""),
        "/to-ftp": (302, {"Location": "ftp://127.0.0.1/r.pdf"}, b""),
        "/to-file": (301, {"Location": "file:///etc/passwd"}, b""),
    })
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield SimpleNamespace(url=url, hits=hits)
    srv.shutdown()
    srv.server_close()


def test_batch_of_files_is_one_run(acme, gct, make_file):
    files = [make_file(n, PDF + n.encode()) for n in ("a.pdf", "b.pdf", "c.pdf")]
    r = gct("doc", "add", *files, "--company", "Acme")
    assert r.code == 0 and r.out.splitlines()[-1] == "3 registered"
    assert r.out.splitlines()[0] == "registered 1: a.pdf (version 1, private, availability unknown)"
    assert len(gct("run", "list", "--json").data["runs"]) == 1
    assert [(e["kind"], e["stage"], e["item"], e["outcome"]) for e in events(gct, "item")] == [
        ("item", "register", str(f), "ok") for f in files
    ]


def test_folder_registers_recognised_direct_children_by_name(acme, gct, make_file, tmp_path):
    folder = tmp_path / "reports"
    (folder / "sub").mkdir(parents=True)
    (folder / "b.pdf").write_bytes(PDF + b"b")
    (folder / "a.pdf").write_bytes(PDF + b"a")
    (folder / "c.csv").write_bytes(CSV)
    (folder / "notes.txt").write_text("hello")
    (folder / "sub" / "deep.pdf").write_bytes(PDF + b"deep")
    r = gct("doc", "add", folder, "--company", "Acme", "--json")
    assert r.code == 0
    assert [(i["source"], i["action"]) for i in r.data["items"]] == [
        (str(folder / n), "registered") for n in ("a.pdf", "b.pdf", "c.csv")
    ]
    assert [i["document"]["file_type"] for i in r.data["items"]] == ["pdf", "pdf", "csv"]

    (tmp_path / "nothing").mkdir()
    (tmp_path / "nothing" / "x.txt").write_text("x")
    r = gct("doc", "add", tmp_path / "nothing", "--company", "Acme", "--json")
    assert r.code == 4 and [i["action"] for i in r.data["items"]] == ["refused"]
    assert r.data["items"][0]["source"] == str(tmp_path / "nothing")


def test_same_bytes_twice_in_one_batch(acme, gct, make_file, db):
    r = gct("doc", "add", make_file("a.pdf"), make_file("copy.pdf"), "--company", "Acme", "--json")
    first, second = r.data["items"]
    assert r.code == 0 and (first["action"], second["action"]) == ("registered", "duplicate")
    assert second["document"]["id"] == first["document"]["id"]
    assert db.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 1
    assert [e["outcome"] for e in events(gct, "item")] == ["ok", "duplicate"]


def test_batch_keeps_going(acme, gct, make_file, tmp_path):
    good, missing, text = make_file("good.pdf"), tmp_path / "missing.pdf", make_file("notes.txt", b"plain words")
    r = gct("doc", "add", good, missing, text, "--company", "Acme", "--json")
    assert r.code == 4 and r.data["status"] == "partial"
    assert [i["action"] for i in r.data["items"]] == ["registered", "refused", "refused"]
    assert "does not exist" in r.data["items"][1]["cause"] and "not a PDF" in r.data["items"][2]["cause"]
    assert str(missing) in r.data["next_action"] and str(text) in r.data["next_action"]
    assert str(good) not in r.data["next_action"]
    assert [e["item"] for e in events(gct, "failure")] == [str(missing), str(text)]
    human = gct("doc", "add", good, missing, "--company", "Acme")
    assert human.code == 4 and human.out.splitlines()[-1] == "1 duplicate, 1 refused"
    assert str(missing) in human.err


def test_url_fetch_and_cache(acme, gct, web, db):
    u = web.url("/r.pdf")
    r = gct("doc", "add", u, "--company", "Acme", "--json")
    assert r.code == 0
    (item,) = r.data["items"]
    assert (item["action"], item["cached"]) == ("registered", False)
    doc = item["document"]
    assert (doc["source"], doc["logical_name"], doc["file_type"], doc["sha256"]) == (u, "r.pdf", "pdf", sha(PDF))
    assert (acme / "files" / sha(PDF)[:2] / sha(PDF)).read_bytes() == PDF
    assert files_on_disk(acme) == [f"files/{sha(PDF)[:2]}", f"files/{sha(PDF)[:2]}/{sha(PDF)}"]
    fetch = [e for e in events(gct, "item") if e["stage"] == "fetch"]
    assert [(e["item"], e["method"], e["outcome"]) for e in fetch] == [(u, "urllib", "ok")]
    rows = db.execute("SELECT input_version, config_version, outcome FROM attempt WHERE stage = 'fetch' AND item = ?",
                      (u,)).fetchall()
    assert [tuple(x) for x in rows] == [(version_of(u), version_of("fetch", 1), "ok")]
    assert web.hits == ["/r.pdf"]

    again = gct("doc", "add", u, "--company", "Acme", "--json")
    assert again.code == 0 and web.hits == ["/r.pdf"]
    (item,) = again.data["items"]
    assert (item["action"], item["cached"], item["document"]["id"]) == ("duplicate", True, doc["id"])
    assert db.execute("SELECT COUNT(*) FROM attempt").fetchone()[0] == 1


def test_url_csv_is_recognised_from_the_address_name(acme, gct, web):
    r = gct("doc", "add", web.url("/data.csv"), "--company", "Acme", "--json")
    assert r.code == 0 and r.data["items"][0]["document"]["file_type"] == "csv"


def test_url_refusals_are_failed_items_and_the_batch_continues(acme, gct, web, db, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{s.getsockname()[1]}/r.pdf"
    monkeypatch.setattr(intake, "MAX_BYTES", 100)
    urls = [web.url("/page.html"), web.url("/gone.pdf"), closed, web.url("/big.pdf"), web.url("/r.pdf")]
    r = gct("doc", "add", *urls, "--company", "Acme", "--json")
    assert r.code == 4 and r.data["status"] == "partial"
    items = r.data["items"]
    assert [i["action"] for i in items] == ["failed", "failed", "failed", "failed", "registered"]
    assert "not return a PDF" in items[0]["cause"]
    assert "HTTP error 404" in items[1]["cause"]
    assert "could not be reached" in items[2]["cause"]
    assert "larger than the limit" in items[3]["cause"]
    assert all(u in r.data["next_action"] for u in urls[:4]) and urls[4] not in r.data["next_action"]
    outcomes = db.execute("SELECT item, outcome FROM attempt ORDER BY id").fetchall()
    assert [tuple(x) for x in outcomes] == [(u, "failed") for u in urls[:4]] + [(urls[4], "ok")]
    assert [e["item"] for e in events(gct, "failure")] == urls[:4]
    assert not any(p.name.startswith(".") for p in (acme / "files").rglob("*"))  # no temporary file left


def test_redirects(acme, gct, web):
    r = gct("doc", "add", web.url("/hop"), web.url("/to-ftp"), web.url("/to-file"), "--company", "Acme", "--json")
    followed, ftp, file = r.data["items"]
    assert followed["action"] == "registered" and followed["document"]["sha256"] == sha(PDF + b"2")
    assert web.hits[:2] == ["/hop", "/r2.pdf"]
    for refused in (ftp, file):
        assert refused["action"] == "failed" and "redirected" in refused["cause"]
    assert r.code == 4


def test_plan_stores_nothing(acme, gct, web, db, make_file, tmp_path):
    before, disk = row_counts(db), files_on_disk(acme)
    a, b = make_file("a.pdf"), make_file("b.pdf", PDF + b"b")
    r = gct("doc", "add", a, b, web.url("/r.pdf"), "--company", "Acme", "--plan")
    assert r.code == 0
    assert r.out.splitlines() == [
        f"would register: {a} (private, availability unknown)", f"would register: {b} (private, availability unknown)",
        f"would fetch: {web.url('/r.pdf')} (private, availability unknown)",
        "2 would register, 1 would fetch. Nothing was stored.",
    ]
    assert row_counts(db) == before and files_on_disk(acme) == disk and web.hits == []

    missing = gct("doc", "add", tmp_path / "missing.pdf", "--company", "Acme", "--plan", "--json")
    assert missing.code == 0 and missing.data["status"] == "ok"
    assert missing.data["items"][0]["action"] == "refused" and missing.data["items"][0]["cause"]
    assert row_counts(db) == before


def test_plan_reports_duplicates(acme, gct, make_file):
    first = gct("doc", "add", make_file("a.pdf"), "--company", "Acme", "--json").data["items"][0]["document"]
    r = gct("doc", "add", make_file("again.pdf"), make_file("new.pdf", PDF + b"n"), make_file("twice.pdf", PDF + b"n"),
            "--company", "Acme", "--plan", "--json")
    assert [(i["action"], (i["document"] or {}).get("id")) for i in r.data["items"]] == [
        ("duplicate", first["id"]), ("would register", None), ("duplicate", None),
    ]


def test_company_is_explicit(acme, gct, db, make_file, web):
    gct("company", "add", "Beta")
    r = gct("doc", "add", make_file("a.pdf"), web.url("/r.pdf"), "--company", "beta", "--json")
    assert {i["company"] for i in r.data["items"]} == {"Beta"}
    assert {d["company"] for d in gct("doc", "list", "--json").data["documents"]} == {"Beta"}
    before = row_counts(db)
    assert gct("doc", "add", make_file("b.pdf", PDF + b"b")).code == 2
    unknown = gct("doc", "add", make_file("c.pdf", PDF + b"c"), web.url("/r2.pdf"), "--company", "Nobody")
    assert unknown.code == 3 and "gct company add" in unknown.err
    assert row_counts(db) == before and web.hits == ["/r.pdf"]


def test_name_with_several_items_is_a_usage_error(acme, gct, db, make_file):
    before = row_counts(db)
    r = gct("doc", "add", make_file("a.pdf"), make_file("b.pdf", PDF + b"b"), "--company", "Acme", "--name", "X")
    assert r.code == 2 and "--name" in r.err
    assert row_counts(db) == before


def test_local_source_text_kept_and_url_stores_url(acme, gct, make_file, web):
    local = gct("doc", "add", make_file("a.pdf"), "--company", "Acme", "--json").data["items"][0]["document"]
    assert local["source"] is None
    url = gct("doc", "add", web.url("/r2.pdf"), "--company", "Acme", "--source", "website", "--json")
    assert url.data["items"][0]["document"]["source"] == web.url("/r2.pdf")


def test_url_csv_with_name_is_recognised_from_the_address(acme, gct, web):
    u = web.url("/data.csv")
    r = gct("doc", "add", u, "--company", "Acme", "--name", "emissions", "--json")
    assert r.code == 0
    (item,) = r.data["items"]
    doc = item["document"]
    assert (item["action"], doc["logical_name"], doc["file_type"]) == ("registered", "emissions", "csv")
    again = gct("doc", "add", u, "--company", "Acme", "--name", "emissions", "--json")
    assert again.code == 0
    (item,) = again.data["items"]
    assert (item["action"], item["cached"], item["document"]["id"]) == ("duplicate", True, doc["id"])


def test_unreadable_file_is_refused_and_the_batch_continues(acme, gct, make_file, tmp_path, monkeypatch):
    good = make_file("good.pdf")
    folder = tmp_path / "locked"
    folder.mkdir()
    bad = folder / "locked.pdf"
    bad.write_bytes(PDF + b"locked")
    real = intake.registry.detect_file_type

    def detect(path, name=None):
        if str(path) == str(bad):
            raise PermissionError(13, "Permission denied", str(path))
        return real(path, name)

    monkeypatch.setattr(intake.registry, "detect_file_type", detect)
    r = gct("doc", "add", good, bad, "--company", "Acme", "--json")
    assert r.code == 4
    assert [i["action"] for i in r.data["items"]] == ["registered", "refused"]
    assert r.data["items"][1]["cause"] == f"The file {bad} could not be read."
    assert "permissions" in r.data["items"][1]["next_action"]
    assert [d["logical_name"] for d in gct("doc", "list", "--json").data["documents"]] == ["good.pdf"]

    plan = gct("doc", "add", folder, "--company", "Acme", "--plan", "--json")
    assert plan.code == 0
    assert [(i["source"], i["action"], i["cause"]) for i in plan.data["items"]] == [
        (str(bad), "refused", f"The file {bad} could not be read."),
    ]
