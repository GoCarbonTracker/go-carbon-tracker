import hashlib
import json
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import viewer_fixture
from conftest import make_pdf
from test_api import OPENER, call, cookie
from gct.api import app as app_module
from gct.api import server

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"
DIST = ROOT / "gct" / "viewer_dist"
SOURCE_TOP = ["index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json"]


@pytest.fixture
def vws(tmp_path):
    return viewer_fixture.build(tmp_path / "vws")


@pytest.fixture
def srv(vws):
    s = server.serve(vws, port=0)
    yield s
    s.stop()


def get(srv, path, **headers):
    status, _, body = call(srv.port, path, **cookie(srv), **headers)
    return status, json.loads(body)


def png(srv, path, headers=None):
    """(status, content type, bytes) for a binary response, with the session cookie unless headers are given."""
    req = urllib.request.Request(f"http://127.0.0.1:{srv.port}{path}", headers=headers or cookie(srv))
    try:
        r = OPENER.open(req, timeout=30)
    except urllib.error.HTTPError as e:
        r = e
    with r:
        assert not any(k.lower().startswith("access-control-allow") for k in r.headers.keys())
        return r.getcode(), r.headers["content-type"], r.read()


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def claims_by_locator(srv):
    return {c["locator"]: c for c in get(srv, "/api/documents/1/claims")[1]["claims"]}


# AC 8
def test_companies_documents_and_page_sizes_in_points(srv):
    assert get(srv, "/api/companies")[1] == {"status": "ok", "data_version": 1, "companies": [{"id": 1, "name": "Acme"}]}
    status, data = get(srv, "/api/companies/1/documents")
    assert status == 200 and [d["logical_name"] for d in data["documents"]] == ["acme-report.pdf"]
    status, data = get(srv, "/api/documents/1")
    assert status == 200 and data["page_count"] == 3
    assert data["pages"] == [{"left": 0, "top": 0, "width": 612.0, "height": 792.0}] * 3
    assert get(srv, "/api/companies/9/documents")[0] == 404
    assert get(srv, "/api/documents/9")[0] == 404


def reshaped(change) -> bytes:
    """One page with the word Scope, changed by pypdfium2 (change(page)) and saved."""
    import io
    import pypdfium2

    pdf = pypdfium2.PdfDocument(make_pdf([{"text": [(200, 300, "Scope")]}]))
    change(pdf[0])
    out = io.BytesIO()
    pdf.save(out)
    pdf.close()
    return out.getvalue()


FRAME_CASES = {
    "cropped": lambda p: p.set_cropbox(50, 100, 562, 742),  # the review's case (F1)
    "offset": lambda p: p.set_mediabox(100, 100, 712, 892),  # a MediaBox not starting at 0, 0
    "rotated": lambda p: p.set_rotation(90),
}


# AC 8 and review F1: the image, the viewBox and the stored boxes share pdfplumber's frame
@pytest.mark.parametrize("case", FRAME_CASES)
def test_a_stored_box_lands_on_its_word_in_the_png(case, ws, gct, db, make_file):
    import io

    import pdfplumber
    from PIL import Image

    gct("company", "add", "Acme")
    gct("doc", "add", make_file(f"{case}.pdf", reshaped(FRAME_CASES[case])), "--company", "Acme")
    gct("read")
    gct("publish", "build")
    path = next(p for p in (ws / "files").rglob("*") if p.is_file())
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        expected = {"left": page.bbox[0], "top": page.bbox[1], "width": page.width, "height": page.height}
    (rel,) = db.execute("SELECT a.path FROM page p JOIN artifact a ON a.id = p.artifact_id").fetchone()
    reading = json.loads((ws / rel).read_text(encoding="utf-8"))
    (word,) = [w for w in reading["words"] if w["text"] == "Scope"]
    s = server.serve(ws, port=0)
    try:
        (frame,) = get(s, "/api/documents/1")[1]["pages"]
        assert frame == expected and (frame["width"], frame["height"]) == (reading["width"], reading["height"])
        for scale in (1.5, 3.0):
            status, _, data = png(s, f"/api/documents/1/pages/1.png?scale={scale}")
            assert status == 200 and png_size(data) == (round(frame["width"] * scale), round(frame["height"] * scale))
            # The ink of the page is the one word: it must sit inside the word's box drawn in the frame.
            ink = Image.open(io.BytesIO(data)).convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
            x0, top, x1, bottom = ((word[k] - frame[o]) * scale for k, o in
                                   (("x0", "left"), ("top", "top"), ("x1", "left"), ("bottom", "top")))
            slack = 1.5 * scale
            assert ink is not None, case
            assert x0 - slack <= ink[0] and ink[2] <= x1 + slack and top - slack <= ink[1] and ink[3] <= bottom + slack, (
                case, scale, ink, (x0, top, x1, bottom))
            assert ink[2] - ink[0] > 0.8 * (x1 - x0), (case, ink)  # the word itself, not a stray dot
    finally:
        s.stop()


def test_before_the_first_publish_there_is_nothing_to_list(ws):
    s = server.serve(ws, port=0)
    try:
        assert get(s, "/api/companies")[1] == {"status": "ok", "data_version": None, "companies": []}
        assert get(s, "/api/documents/1")[0] == 404
    finally:
        s.stop()


# AC 1 to 3 (the API side; the labels and V3 decision are tested in viewer/test/logic.test.ts)
def test_claims_carry_page_box_and_the_four_source_match_kinds(srv):
    c = claims_by_locator(srv)
    first = c["t0r1c2"]
    assert (first["page"], first["value_text"], first["unit_text"]) == (1, "1,100", "tCO2e")
    assert first["boxes"] == [[316.0, 124.48, 346.02, 136.48]]  # pdfplumber points, top-left origin, as stored
    assert (first["source_match"], first["source_match_reason"]) == ("matched", None)
    assert (c["no-box"]["page"], c["no-box"]["boxes"]) == (2, None)
    assert (c["no-box"]["source_match"], c["no-box"]["source_match_reason"]) == ("cited", "no box")
    assert c["unknown-page"]["page"] == 999
    assert (c["unknown-page"]["source_match"], c["unknown-page"]["source_match_reason"]) == (
        "unresolved", "page not read: gct read")
    assert (c["not-checked"]["source_match"], c["not-checked"]["source_match_reason"]) == (None, None)
    assert get(srv, "/api/documents/9/claims")[0] == 404


def test_claims_carry_state_boundary_label_and_correction(srv):
    c = claims_by_locator(srv)
    assert {x["claim_state"] for x in c.values()} <= {
        "current", "not found in the newest reading", "page read again, not yet extracted"}
    assert (c["t0r1c2"]["version_method"], c["t0r1c2"]["correction"], c["t0r1c2"]["needs_re_review"]) == (
        "rung1-rules", None, [])
    fixed = next(x for x in c.values() if x["page"] == 3)
    assert (fixed["version_method"], fixed["value_text"]) == ("correction", "9,877")
    assert {k: fixed["correction"][k] for k in ("contributor", "capacity", "rationale", "fields")} == {
        "contributor": "Ann", "capacity": "analyst", "rationale": "misread digit", "fields": ["value_text"]}
    assert fixed["correction"]["replaced"]["value_text"] == "9,876"
    assert "boundary_label" in fixed


# AC 5 and 9
def test_page_render_scales_cache_and_errors(vws, srv, monkeypatch):
    calls = []
    real = app_module._render
    monkeypatch.setattr(app_module, "_render", lambda *a: calls.append(a) or real(*a))
    status, kind, data = png(srv, "/api/documents/1/pages/1.png")
    assert (status, kind, png_size(data)) == (200, "image/png", (918, 1188))  # 612 x 792 points at 1.5
    assert png(srv, "/api/documents/1/pages/1.png?scale=1.5")[2] == data
    assert len(calls) == 1
    assert png_size(png(srv, "/api/documents/1/pages/1.png?scale=3.0")[2]) == (1836, 2376)
    assert len(calls) == 2
    (doc_sha,) = [p.name for p in (vws / "artifacts" / "pages").iterdir()]
    assert (vws / "files" / doc_sha[:2] / doc_sha).is_file()  # keyed by the document's hash
    assert sorted(p.name for p in (vws / "artifacts" / "pages" / doc_sha).iterdir()) == ["1@1.5.png", "1@3.0.png"]
    for scale in ("2", "abc", "nan", "1.5x"):
        status, data = get(srv, f"/api/documents/1/pages/1.png?scale={scale}")
        assert status == 400 and data["status"] == "error", scale
    for path in ("/api/documents/1/pages/4.png", "/api/documents/1/pages/0.png", "/api/documents/9/pages/1.png",
                 "/api/documents/1/pages/x.png"):
        assert get(srv, path)[0] == 404, path
    assert len(calls) == 2


def test_a_failed_cache_write_leaves_no_file(vws, srv, monkeypatch):
    def broken(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(app_module.os, "replace", broken)
    assert png(srv, "/api/documents/1/pages/2.png")[0] == 500
    monkeypatch.undo()
    folder = next((vws / "artifacts" / "pages").iterdir())
    assert list(folder.iterdir()) == []  # neither a page nor a half-written temporary file
    assert png(srv, "/api/documents/1/pages/2.png")[0] == 200


# AC 4
ENDPOINTS = ["/", "/api/companies", "/api/companies/1/documents", "/api/documents/1", "/api/documents/1/claims",
             "/api/documents/1/pages/1.png", "/api/companies/1/candidates", "/api/claims/1/history"]


def test_every_endpoint_is_guarded(srv):
    p = srv.port
    for path in ENDPOINTS:
        assert png(srv, path)[0] == 200, path
        assert png(srv, path, {"Authorization": f"Bearer {srv.token}"})[0] == 200, path
        assert call(p, path)[0] == 401, path
        assert call(p, path, Origin="http://evil.example", **cookie(srv))[0] == 403, path
        assert call(p, path, Host=f"evil.example:{p}", **cookie(srv))[0] == 403, path
        req = urllib.request.Request(f"http://127.0.0.1:{p}{path}", data=b"", method="POST",
                                     headers={**cookie(srv), "Origin": f"http://127.0.0.1:{p}"})  # a change needs an Origin
        with pytest.raises(urllib.error.HTTPError) as e:
            OPENER.open(req, timeout=10)
        assert e.value.code == 405, path


# AC 6, served side
def test_the_committed_build_is_served(srv):
    status, headers, body = call(srv.port, "/", **cookie(srv))
    assert status == 200 and headers["content-type"].startswith("text/html")
    assets = [line.split('"')[-2] for line in body.splitlines() if "./assets/" in line]
    assert len(assets) == 2
    for a in assets:
        status, kind, data = png(srv, a.removeprefix("."))
        assert status == 200 and data == (DIST / a.removeprefix("./")).read_bytes()
    assert call(srv.port, "/assets/nothing.js", **cookie(srv))[0] == 404


# AC 6 and 11
def source_hash(folder: Path) -> str:
    """The algorithm of viewer/vite.config.ts: one "<sha256>  <path>\\n" line per source file, sorted by path."""
    files = sorted(SOURCE_TOP + [p.relative_to(folder).as_posix() for p in (folder / "src").rglob("*") if p.is_file()])
    lines = "".join(f"{hashlib.sha256((folder / f).read_bytes()).hexdigest()}  {f}\n" for f in files)
    return hashlib.sha256(lines.encode()).hexdigest()


def test_committed_build_matches_the_source():
    assert (DIST / "SOURCE.sha256").read_text() == source_hash(VIEWER) + "\n", "rebuild with: npm run build in viewer/"


def tree(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_a_rebuild_is_byte_identical(tmp_path):
    if not (VIEWER / "node_modules").is_dir() or not shutil.which("node"):
        pytest.skip("viewer/node_modules or node is not here (see viewer/README.md)")
    out = tmp_path / "dist"
    r = subprocess.run(["node", "node_modules/typescript/bin/tsc", "--noEmit"], cwd=VIEWER, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr  # npm run build type-checks first; so does this
    r = subprocess.run(["node", "node_modules/vite/bin/vite.js", "build", "--outDir", str(out), "--emptyOutDir"],
                       cwd=VIEWER, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert tree(out) == tree(DIST)


# AC 10
def test_viewer_logic_with_node_test():
    if not shutil.which("node"):
        pytest.skip("node is not on PATH; the viewer logic tests need it (contributors only)")
    tests = sorted(p.relative_to(VIEWER).as_posix() for p in (VIEWER / "test").glob("*.test.ts"))
    assert "test/records.test.ts" in tests
    r = subprocess.run(["node", "--test", *tests], cwd=VIEWER, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# Story 6.1: the filter bar's fixed values are gct's (F1)
def test_the_filter_bar_lists_the_values_gct_accepts():
    import re
    from gct.stages import view
    text = (VIEWER / "src" / "records.ts").read_text()
    for field in ("metric", "boundary", "claim_state", "evidence", "match", "comparison", "review"):
        block = re.search(rf"\n  {field}: \[(.*?)(?=\n  [a-z_]+: \[|\n}};)", text, re.S)[1]
        assert tuple(re.findall(r'\["([^"]+)", "', block)) == view.CHOICES[field], field


# Follow-up 1: what Moka's hand run installs must carry the viewer
def test_the_wheel_ships_the_viewer(tmp_path):
    # Built from a copy: setuptools never empties build/lib, so a wheel built in the worktree after a viewer
    # rebuild also carries the old asset files.
    src = tmp_path / "src"
    shutil.copytree(ROOT, src, ignore=shutil.ignore_patterns(".git", ".venv", "node_modules", "build", "*.egg-info",
                                                              "__pycache__", ".pytest_cache"))
    r = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--no-index",
                        "--wheel-dir", str(tmp_path), str(src)], capture_output=True, text=True)
    if r.returncode != 0 and "setuptools" in r.stderr.lower():
        pytest.skip(f"no local setuptools to build a wheel offline: {r.stderr[-200:]}")
    assert r.returncode == 0, r.stderr
    (wheel,) = tmp_path.glob("gct-*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    shipped = {f"gct/viewer_dist/{f}" for f in tree(DIST)}
    assert "gct/viewer_dist/index.html" in shipped
    assert {n for n in names if n.startswith("gct/viewer_dist/")} == shipped
    assert not any("node_modules" in n or n.startswith("viewer/") for n in names)


def browse(srv, tmp_path, *mode):
    """Run tests/viewer_browser.mjs against the server in a headless Chrome; its JSON output."""
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or next(
        (p for p in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"] if Path(p).exists()), None)
    if not chrome or not shutil.which("node"):
        pytest.skip("headless Chrome or node is not installed")
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    browser = subprocess.Popen([chrome, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={tmp_path / 'chrome'}",
                                "--no-first-run", "--disable-gpu", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        r = subprocess.run(["node", str(ROOT / "tests" / "viewer_browser.mjs"), str(port), srv.url, *mode],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
    finally:
        browser.terminate()
        browser.wait(timeout=10)
    return json.loads(r.stdout)


# AC 10b: the form submits in a real (headless) browser; the panel then shows the correction; no form on a claim not current
def test_the_correction_form_in_a_headless_browser(srv, tmp_path):
    out = browse(srv, tmp_path)
    assert "9,877" in out["before"]
    assert "9,878" in out["after"] and "replaced 9,877" in out["after"] and "second look" in out["after"]
    assert out["notCurrentHasForm"] is False
    assert get(srv, "/api/documents/1/claims")[1]["claims"]  # still served after the browser's POST


# Story 5.4 F1: another writer publishes while a company confirmation is being filled in; the stale submission is
# refused, the panel reloads on the new published version, and the refusal with its next step stays on screen.
def test_a_stale_review_keeps_its_refusal_after_another_writer_publishes(vws, srv, tmp_path):
    import re
    import sqlite3
    out = browse(srv, tmp_path, "stale")
    assert out["second_writer"] == 200
    newest = get(srv, "/api/health")[1]["data_version"]
    assert f"published data version {newest}" in out["header"]  # the panel reloaded on the other writer's version
    assert "9,879" in out["panel"]
    assert out["problem"] is not None, out["panel"]
    m = re.fullmatch(r"Version (\d+) is not the newest version of claim (\d+); the newest is (\d+)\. "
                     r"See what version \3 says with: gct claims history \2, then record on --version \3", out["problem"])
    assert m and m[1] != m[3], out["problem"]
    with sqlite3.connect(vws / "workspace.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM review_company WHERE conclusion = 'stale entry'").fetchone() == (0,)


# Story 6.1 AC 7: the Tables and Graphs shell filters and counts on its pinned version; a second writer's publish makes
# the next request stale (409) and the notice offers the new version, which Reload then counts on.
def test_the_shell_counts_on_its_pinned_version_and_offers_a_newer_one(tmp_path, monkeypatch):
    import gate_fixture
    query = app_module._query

    def late_companies(root, sql, *params):  # review F3: the count can arrive before the companies
        if sql.startswith("SELECT id, name FROM company"):
            time.sleep(1.5)
        return query(root, sql, *params)

    monkeypatch.setattr(app_module, "_query", late_companies)
    s = server.serve(gate_fixture.build(tmp_path / "gws"), port=0)
    try:
        out = browse(s, tmp_path, "shell")
    finally:
        s.stop()
    assert out["all"] == "14 claims match in data version 1."
    assert out["acme"] == "9 claims match in data version 1."
    assert out["evidenceHidden"] is True
    assert out["openPanels"] == 1  # review F4
    assert out["covering"] == {"1280": [], "900": []}  # review F4: no open choice panel lies over the count line
    assert "2 claims of 1 archived document are not in this or any view." in out["lines"]
    assert out["series"] == 5
    assert out["second_writer"] == 200
    assert out["notice"] == "Data version 2 is available. Reload"
    assert out["reloaded"] == "14 claims match in data version 2."


# Story 6.1 review F1: a wording set from outside the filter bar (a saved view, story 6.4) stays in the filter after the
# bar's debounce and shows in its input
def test_the_filter_bar_keeps_a_wording_set_from_outside(tmp_path):
    if not (VIEWER / "node_modules").is_dir() or not shutil.which("node"):
        pytest.skip("viewer/node_modules or node is not here (see viewer/README.md)")
    bundle = ("require('node:module').createRequire(require.resolve('vite/package.json'))('esbuild').buildSync({"
              "entryPoints: ['test/filter-bar-harness.tsx'], bundle: true, outfile: process.argv[1], jsx: 'automatic',"
              "define: {'process.env.NODE_ENV': '\"production\"'}, logLevel: 'error'})")
    r = subprocess.run(["node", "-e", bundle, str(tmp_path / "h.js")], cwd=VIEWER, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    (tmp_path / "index.html").write_text('<div id="root"></div><script src="h.js"></script>')
    out = browse(SimpleNamespace(url=(tmp_path / "index.html").as_uri()), tmp_path, "filterbar")
    assert out["log"] == ["{}", '{"text":"scope 1","company":[1]}']
    assert out["input"] == "scope 1"


# Story 6.4 B1 and G3 on the gate fixture (headless Chrome): rows of two companies, one of them a spreadsheet row, go to
# Graphs and back with the same ids, filter and version; the chip; every D10 reason with no tab change; a time series
# both ways; after another writer publishes, a selection of the older version is refused until Reload.
def test_transfer_between_tables_and_graphs(tmp_path):
    import re
    import gate_fixture
    s = server.serve(gate_fixture.build(tmp_path / "gws"), port=0)
    try:
        out = browse(s, tmp_path, "transfer")
    finally:
        s.stop()
    none = "Select rows to show them in Graphs."
    assert out["empty"] == {"buttons": ["Show 0 rows in Graphs (disabled)", "Show as a time series (disabled)"],
                            "reason": none, "tab": "Tables"}
    g = out["toGraphs"]
    assert g["companies"] == ["Beta", "Acme"] and g["cells"] == 1  # two companies; the sheet row with its cell node
    assert g["nodes"] == [f"claim:{i}" for i in g["picked"]]
    assert g["chip"] == {"text": "2 claims from Tables", "label": "Remove the selection: 2 claims from Tables"}
    assert g["line"] == "14 claims match in data version 1." and g["graph"] == "2 claims match in data version 1."
    b = out["back"]  # G3: the same ids, the same filter (count line) and version
    assert b["bar"]["buttons"] == ["Show 2 claims in Tables", "Show this series in Tables (disabled)"]
    assert b["ids"] == g["picked"] and b["line"] == g["line"]
    assert b["caption"] == "Claims matching the filter in published data version 1"
    assert b["chip"]["text"] == "2 claims from Graphs"
    assert g["active"] == "BUTTON Graphs" and b["active"] == "BUTTON Tables"  # review L1, H4: focus on the receiving tab
    assert b["cleared"] is None  # review L2, H3: no "the filter changed" line when only the incoming selection changed
    assert out["removed"]["active"] == "BUTTON Tables"  # focus goes to the tab when the chip goes
    assert out["removed"]["graphsChip"]["text"] == "2 claims from Tables"  # each tab keeps its own chip
    assert out["twoSeries"] == {"reason": "These claims are in 2 series; pick one.", "tab": "Tables"}
    assert out["noSeries"]["reason"].startswith("These claims are in no series: ") and out["noSeries"]["tab"] == "Tables"
    sr = out["series"]
    assert sr["nodes"] == [f"point:{i}" for i in sr["ids"]] and sr["view"] == "Time series"
    assert sr["chip"]["text"] == "Time series: Scope 1 emissions from Tables"
    back = out["seriesBack"]
    assert back["chip"]["text"] == "Time series: Scope 1 emissions from Graphs"
    assert back["ids"] == sr["ids"]  # the series node's claims are the series the rows went to Graphs as
    kinds = {k["kind"]: k for k in out["kinds"]}
    assert kinds["page"]["reason"] == "A page has no rows of its own; select claims or a series."
    assert {"period", "boundary", "company", "auditor", "adjudication", "edge"} <= set(kinds)
    for k in out["kinds"]:
        assert k["reason"].endswith(" has no rows of its own; select claims or a series."), k
        assert k["tab"] == "Graphs" and all(x.endswith("(disabled)") for x in k["buttons"]), k
    assert kinds["adjudication"]["reason"].startswith("An adjudication ")
    assert kinds["edge"]["reason"].startswith("A member edge ")
    assert [len(set(m["ids"])) for m in out["mixed"]] == [2, 2]
    for m in out["mixed"]:  # a series with a claim, then two series (review L3)
        assert m["reason"] == "Select one series, or claims only.", m
        assert m["tab"] == "Graphs" and all(x.endswith("(disabled)") for x in m["buttons"]), m
    assert out["second_writer"] == 200
    assert out["stale"]["reason"] == ("Data version 1 is no longer the current one; the current version is 2. Reload to see"
                                      " version 2.")
    assert out["stale"]["tab"] == "Tables" and out["stale"]["notice"] == "Data version 2 is available. Reload"
    assert out["reloaded"]["reason"] == none and out["reloaded"]["line"] == "14 claims match in data version 2."
    assert not re.search(r"verified|assured|certified|compliant", json.dumps(out), re.I)


# Story 6.4 R2: a selection across three Tables pages is drawn whole and counted by the chip; 501 rows show the limit and
# the tab stays (the 501-claim fixture of story 6.3).
def test_transfer_across_pages_and_the_graph_limit(tmp_path):
    from test_viewer_graphs import big
    s = server.serve(big(tmp_path / "big"), port=0)
    try:
        out = browse(s, tmp_path, "transfer", "limit")
    finally:
        s.stop()
    assert out["across"]["chip"]["text"] == "405 claims from Tables" and out["across"]["nodes"] == 405
    assert out["across"]["graph"] == "405 claims match in data version 1."
    assert out["over"] == {"buttons": ["Show 501 rows in Graphs (disabled)", "Show as a time series"],
                           "reason": "501 rows selected; a graph draws at most 500. Select fewer.", "tab": "Tables"}




# Story 6.4 part B, the views mode (AC 7, AC 8 G3 browser, R2 keyboard rows): the Saved views panel saves the filter bar's
# filter and the tab, says when a name exists and when a chip is showing, removes with a key and a confirmation; Escape
# closes a panel or form and focus returns to its button. A view opened after a later report shows its claims on the
# version current then; after an archive it shows the remaining claims and the F7 line.
def test_saved_views_in_a_headless_browser(tmp_path):
    import sqlite3
    import gate_fixture
    from test_review_api import bearer
    from test_saved_view import later_report
    from test_correct import post
    root = gate_fixture.build(tmp_path / "gws")
    flt = {"company": [1], "metric": ["ghg_scope_1"]}

    def matched(s, version):
        status, a = post(s, "/api/records", {"filter": flt, "data_version": version, "shape": "table", "limit": 1000},
                         **bearer(s))
        assert status == 200, a
        return [r["claim"]["id"] for r in a["rows"]]

    s = server.serve(root, port=0)
    try:
        v1 = matched(s, 1)
        out = browse(s, tmp_path, "views", "save")
        _, listed = get(s, "/api/views")
    finally:
        s.stop()
    assert out["filtered"]["line"] == f"{len(v1)} claims match in data version 1."
    assert sorted(out["filtered"]["ids"]) == sorted(v1)
    assert out["opened"] == {"active": "SECTION Saved views", "expanded": "true",
                             "empty": "No saved views yet. Save the current filter below to come back to it."}
    assert out["escaped"] == {"open": False, "active": "BUTTON Saved views"}
    assert out["tabNext"] == "BUTTON Questions"  # Tab order follows the screen
    assert out["saved"]["items"] == [{"name": "scope 1", "meta": out["saved"]["items"][0]["meta"]}]
    assert out["saved"]["items"][0]["meta"].startswith("Tables · saved ") and out["saved"]["items"][0]["meta"].endswith(" by Ana")
    assert out["saved"]["done"] == "Saved scope 1." and out["saved"]["name"] == ""
    assert out["exists"] == "A view named scope 1 exists. Saving puts this one first and keeps the earlier one."
    assert out["chip"]["chip"] == "1 claim from Tables"
    assert out["chip"]["notes"] == ["The selection is not part of a saved view; a saved view keeps the filter."]
    assert [i["name"] for i in out["chip"]["items"]] == ["scope 1", "with chip"]
    assert out["removeForm"] == {"active": True, "key": "ana"}  # one key for both forms
    assert out["removeEscaped"] == {"form": False, "active": "BUTTON Remove", "panel": True}
    assert [i["name"] for i in out["removed"]["items"]] == ["scope 1"]
    assert out["removed"]["done"] == "Removed with chip. Its record stays in the workspace."
    # What was stored: the filter and the tab, never the chip's ids; a removal is a row; no version was built.
    assert listed["views"][0]["filter"] == flt and listed["views"][0]["section"] == "tables"
    assert listed["hidden"] == 1 and listed["data_version"] == 1
    with sqlite3.connect(root / "workspace.db") as conn:
        rows = conn.execute("SELECT name, action, filter, section FROM saved_view ORDER BY id").fetchall()
    assert rows == [("scope 1", "save", json.dumps(flt), "tables"), ("with chip", "save", json.dumps(flt), "graphs"),
                    ("with chip", "remove", None, None)]

    doc = later_report(root)  # version 2: two more Acme Scope 1 points
    s = server.serve(root, port=0)
    try:
        out = browse(s, tmp_path, "views", "open")  # the page pins 2; another writer publishes 3 before Open
        v3 = matched(s, 3)
    finally:
        s.stop()
    assert out["second_writer"] == 200
    assert out["line"] == f"{len(v3)} claims match in data version 3." and out["notice"] is None
    assert out["caption"] == "Claims matching the filter in published data version 3"
    assert sorted(out["ids"]) == sorted(v3) and len(set(v3) - set(v1)) == 2  # the later report's claims
    assert out["tab"] == "Tables" and out["company"] == "1" and out["metric"] == "1"
    assert out["active"] == "BUTTON Saved views"  # the panel closed and focus went back to its button

    who = ("--as", "ana", "--capacity", "analyst", "--rationale", "superseded", "--workspace", root)
    gate_fixture.gct("doc", "archive", str(doc), *who)
    gate_fixture.gct("publish", "build", "--workspace", root)
    s = server.serve(root, port=0)
    try:
        out = browse(s, tmp_path, "views", "archived")
        v4 = matched(s, 4)
    finally:
        s.stop()
    assert out["line"] == f"{len(v4)} claims match in data version 4."
    assert sorted(out["ids"]) == sorted(v4) and set(v4) == set(v3) & set(v1)  # the later report's claims are gone
    assert ("4 claims of 2 archived documents are not in this or any view. Restore a document to include its claims."
            in out["count"])  # F7 (Q21, E6-D5): the gate fixture's own archived document and this one


# Story 6.4 B3 (AC 7, R2 questions rows): the six questions with their counts on the pinned version, each equal to what
# the records endpoint matches for its filter (metric-over-time: its number of choices); different-values opens Graphs
# with its filter; a metric-over-time choice opens Graphs in the series shape.
def test_guided_questions_in_a_headless_browser(tmp_path):
    import gate_fixture
    from test_review_api import bearer
    from test_correct import post
    s = server.serve(gate_fixture.build(tmp_path / "gws"), port=0)
    try:
        _, q = get(s, "/api/questions")
        counts = {}
        for x in q["questions"]:
            status, a = post(s, "/api/records", {"filter": x["filter"], "data_version": 1, "shape": "table", "limit": 1},
                             **bearer(s))
            assert status == 200, a
            counts[x["key"]] = a["matched"]
        out = browse(s, tmp_path, "views", "questions")
    finally:
        s.stop()
    want = []
    for x in q["questions"]:
        n = len(x["choices"]) if x["key"] == "metric-over-time" else counts[x["key"]]
        assert x["matched"] == counts[x["key"]]
        count = (f"{n} series with two or more periods" if x["key"] == "metric-over-time"
                 else f"{n} claim{'' if n == 1 else 's'} in data version 1")
        want.append({"text": x["text"], "count": count, "live": "polite"})  # review L5: the counts in the panel's region
    assert out["opened"]["questions"] == want and len(want) == 6
    assert out["opened"]["active"] == "SECTION Questions"
    assert out["escaped"] == {"open": False, "active": "BUTTON Questions"}
    d = out["different"]
    assert d["tab"] == "Graphs" and d["comparison"] == "1" and d["chip"] is None
    assert d["line"] == f"{counts['different-values']} claims match in data version 1."
    assert len(d["nodes"]) == counts["different-values"] > 0
    first = next(x for x in q["questions"] if x["key"] == "metric-over-time")["choices"][0]
    sr = out["series"]
    assert sr["choicesLive"] == "off"  # the series list a person opens is not read out as a change
    assert sr["expanded"] == "true" and len(sr["choices"]) == len(next(
        x for x in q["questions"] if x["key"] == "metric-over-time")["choices"])
    assert sr["choices"][0].startswith(f"{first['company']}: ") and sr["choices"][0].endswith(f", {first['periods']} periods")
    assert sr["chip"].startswith("Time series: ") and sr["chip"].endswith(" from Questions")
    assert sr["view"] == "Time series" and sr["series"] == "1" and sr["points"] >= 2
