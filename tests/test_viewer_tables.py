"""Story 6.2: the Tables tab in a headless Chrome (G2 Tables part, NFR23 Tables part) on 6.1's gate workspace, and
paging on a workspace of three pages of rows. The pure rules are viewer/test/tables.test.ts."""
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

import gate_fixture
from conftest import grid, make_pdf
from test_view import dump, records
from test_viewer import browse, get, srv, vws  # noqa: F401  (srv and vws: the viewer fixture's server)
from gct.api import app as app_module
from gct.api import server
from gct.api.app import BACK
from gct.stages import view

OWN_WORDS = re.compile(r"_|verified|assured|certified|compliant", re.I)
HEADERS = ["col ", "col Company", "col Document", "col Location", "col Metric wording", "col Value", "col Period",
           "col Boundary", "col Evidence", "col Review", "col Claim state"]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return gate_fixture.build(tmp_path_factory.mktemp("gate") / "ws")


def table_ids(root, *argv) -> list[int]:
    out = gate_fixture.gct("view", "records", "--workspace", root, *argv)
    return [r["claim"]["id"] for r in out["rows"]]


def test_the_tables_tab_on_the_gate_workspace(built, tmp_path):
    root = tmp_path / "gws"
    shutil.copytree(built, root)
    before = dump(root)
    s = server.serve(root, port=0)
    try:
        out = browse(s, tmp_path, "tables")
        answer = records(s, {"filter": {}, "shape": "table"})[1]
        health = get(s, "/api/health")[1]
    finally:
        s.stop()
    assert dump(root) == before  # the Tables tab reads only (R3)
    version = health["data_version"]
    assert answer["data_version"] == version == 1

    # The same count and version as the endpoint; a real table with labelled controls; one row a Tab stop
    assert out["countLine"] == f"{answer['matched']} claims match in data version {version}."
    assert out["caption"] == f"Claims matching the filter in published data version {version}"
    assert out["paging"] == "Rows 1 to 14 of 14" and out["disabled"] == ["First", "Previous", "Next", "Last"]
    assert out["ids"] == [r["claim"]["id"] for r in answer["rows"]] == table_ids(root)
    assert out["headers"] == HEADERS and out["selectHeader"] == "Select all rows on this page"
    assert out["sortsBefore"] == [] and out["reviewButton"] is False
    assert sorted(out["companies"]) == ["Acme", "Beta"]
    assert out["rowTabStops"] == [0] + [-1] * 13 and set(out["inRowTabStops"]) == {-1}
    assert all(re.fullmatch(r"Select claim \d+: .+", x) for x in out["labels"])
    assert "Select claim 17: Employees trained" in out["labels"]

    # GCT's own words: stored words spaced, no underscore, none of the words GCT never uses; contributor text absent
    assert not OWN_WORDS.search(out["own"]), out["own"]
    assert "fiscal year (accepted)" in out["own"] and "subsidiary set: combining the information of Beta Power" in out["own"]
    assert "as at (accepted)" in out["own"] and "unknown (unresolved)" in out["own"]
    assert "company accepted; auditor disputed; disagreement" in out["own"] and "adjudications: 1" in out["own"]
    assert gate_fixture.VERIFIED not in out["tableText"] and "verified" not in out["tableText"].lower()

    # Value sorted as gct view records sorts it, by Enter, Space and a click
    by_value = table_ids(root, "--sort", "value")
    assert out["valueAsc"] == {"sorts": ["Value ascending"], "ids": by_value}
    assert out["valueDesc"] == {"sorts": ["Value descending"], "ids": table_ids(root, "--sort", "value:desc")}
    assert out["valueAgain"] == out["valueAsc"]

    # Keyboard: Tab passes the header controls into one row; the arrows move between rows; Space checks without scrolling
    assert out["tabStops"][-1] == f"row {by_value[0]}"
    assert all(not t.startswith("row") for t in out["tabStops"][:-1])
    assert out["afterDown"] == f"row {by_value[1]}"
    assert out["afterSpace"] == {"count": "1 selected", "checked": [by_value[1]], "scroll": out["scrollBefore"],
                                 "active": f"row {by_value[1]}"}
    assert out["afterUp"] == f"row {by_value[0]}"
    assert out["afterClick"]["count"] == "2 selected" and sorted(out["afterClick"]["companies"]) == ["Acme", "Beta"]
    assert out["evidenceAfterKeys"] == out["evidenceBefore"]  # the Evidence selection behind the table is unchanged

    # Enter on a row with a box: its page in the Evidence section, that claim selected, its box drawn as selected
    assert out["opened"]["doc"] == "beta-2025.pdf" and out["opened"]["selected"].startswith("2,000")
    assert out["opened"]["boxes"] >= 1 and out["opened"]["recordsHidden"] is True
    assert out["back"] == {"sorts": ["Value ascending"], "ids": by_value, "checked": sorted(out["afterClick"]["checked"],
                                                                                            key=by_value.index),
                           "count": "2 selected"}

    # The spreadsheet row: the cell view, no page read; Escape gives focus back to the row
    assert out["cellRow"] == "row 18"
    assert out["cell"]["heading"] == "acme-meter.csv, sheet acme-meter, cell B2" and out["cell"]["marked"] == "700"
    assert "/api/documents/3/cells" in out["cell"]["reads"]
    assert [p for p in out["cell"]["reads"] if p.startswith("/api/documents/") and not p.endswith("/cells")] == []
    assert out["afterEscape"] == {"open": False, "active": "row 18"}

    # A filter change clears the checks with the line and keeps the sort
    assert out["cleared"] == {"cleared": "Selection cleared: the filter changed.", "count": "0 selected",
                              "sorts": ["Value ascending"], "companies": ["Acme"]}

    # Only the records endpoint, the cells endpoint and the Evidence reads, all same-origin
    host = urlparse(s.url).netloc
    paths = [urlparse(u).path for u in out["requests"] if urlparse(u).netloc == host]
    assert len(paths) == len(out["requests"])
    allowed = r"/api/(records|health|companies(/\d+/documents)?|documents/\d+(/claims|/cells|/pages/\d+\.png)?|claims/\d+/history)|/assets/.*|/favicon\.ico"
    assert [p for p in paths if not re.fullmatch(allowed, p)] == []
    assert "/api/records" in paths


def test_a_page_outside_its_document_or_a_gone_document_opens_nothing(srv, tmp_path, monkeypatch):
    # 6.1 F11 i3: the page count comes from GET /api/documents/{id}; page 999 of a three-page report opens nothing;
    # when that read fails (the document gone after the first read), its cause shows in the Tables alert line
    query, reads = app_module._query, []

    def gone_after_one_read(root, sql, *params):
        if sql.startswith("SELECT id, company_id, logical_name, version, sha256, file_type FROM document"):
            reads.append(params)
            if len(reads) > 1:
                return []
        return query(root, sql, *params)

    monkeypatch.setattr(app_module, "_query", gone_after_one_read)
    out = browse(srv, tmp_path, "tables", "nolocation")
    assert out["said"] == "This claim has no source location to open."
    assert out["evidenceHidden"] is True and out["cell"] is False
    assert out["reads"] == ["/api/documents/1"]
    assert out["gone"] == {"alert": "There is no document 1 in the published data. " + BACK, "evidenceHidden": True,
                           "rows": out["gone"]["rows"], "active": True}
    assert out["gone"]["rows"] > 0


def paging_workspace(root: Path) -> Path:
    """One company, one report of three pages of 70 rows with two years each: 420 claims, 200 a page."""
    gate_fixture.gct("workspace", "init", root)
    w = ("--workspace", root)
    gate_fixture.gct("company", "add", "Acme", *w)
    gate_fixture.gct("contributor", "add", "ana", "--name", "Ana", *w)  # the second writer
    pages = []
    for p in range(3):
        rows = [[f"Measure {p * 70 + i}", "t", f"{p * 70 + i + 1:,}", f"{i + 7}"] for i in range(70)]
        t = grid(40, 140, [230, 50, 100, 100], [20] * 71, [["Parameter", "Unit", "FY 2024-25", "FY 2023-24"], *rows])
        pages.append({"text": t["text"] + [(40, 80, gate_fixture.FY)], "lines": t["lines"]})
    pdf = root.parent / "acme-long.pdf"
    pdf.write_bytes(make_pdf(pages, size=(612, 1600)))
    gate_fixture.gct("doc", "add", pdf, "--company", "Acme", *w)
    gate_fixture.gct("read", *w)
    gate_fixture.gct("extract", *w)
    gate_fixture.gct("publish", "build", *w)
    return root


def test_paging_checks_late_pages_and_a_newer_version(tmp_path, monkeypatch):
    root = paging_workspace(tmp_path / "pws")
    answer = view.answer

    def slow_second_page(pconn, flt, shape="table", offset=0, *a, **kw):  # a page asked for and overtaken
        if shape == "table" and offset == 200:
            time.sleep(1.5)
        return answer(pconn, flt, shape, offset, *a, **kw)

    monkeypatch.setattr(view, "answer", slow_second_page)
    s = server.serve(root, port=0)
    try:
        out = browse(s, tmp_path, "tables", "paging")
    finally:
        s.stop()
    assert out["first"]["paging"] == "Rows 1 to 200 of 420" and out["first"]["disabled"] == ["First", "Previous"]
    assert out["first"]["caption"].endswith("data version 1") and out["first"]["count"] == "1 selected"
    assert out["second"]["disabled"] == [] and out["second"]["count"] == "2 selected"
    assert out["last"]["disabled"] == ["Next", "Last"] and out["last"]["count"] == "3 selected"
    assert out["backFirst"]["count"] == "3 selected" and len(out["backFirst"]["checked"]) == 1  # checks kept
    assert out["keyboardEnd"] == {"active": "BUTTON Previous", "disabled": ["Next", "Last"]}
    assert out["late"] == {"paging": "Rows 401 to 420 of 420", "busy": "false"}  # the late page 2 was dropped
    assert out["filtered"] == {"paging": "Rows 1 to 200 of 222", "cleared": "Selection cleared: the filter changed.",
                               "count": "0 selected", "checked": []}
    assert out["nothing"]["table"] is False and out["nothing"]["paging"] is False
    assert "No claims match this filter in data version 1." in out["nothing"]["count"]

    # Another writer publishes: Next is refused, the shell offers the new version, the rows on screen keep theirs
    assert out["second_writer"] == 200
    assert out["notice"] == "Data version 2 is available. Reload"
    assert out["stale"] == {"paging": "Rows 1 to 200 of 420", "caption": out["beforeWriter"]["caption"],
                            "checked": out["beforeWriter"]["checked"], "alert": None}
    assert out["reloaded"] == {"paging": "Rows 1 to 200 of 420",
                               "caption": "Claims matching the filter in published data version 2",
                               "cleared": "Selection cleared: data version 2 is now shown.", "count": "0 selected",
                               "countLine": "420 claims match in data version 2."}
