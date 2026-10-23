"""Story 6.3, the Graphs tab: the notice shipped beside the build, every built asset served, the tab's labels on the
gate fixture's real answers, the G2 browser mode on tests/gate_fixture.py, a second writer's version, and the graph
limit and cose timing on a 500-claim fixture built in code."""
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import pytest

import gate_fixture
from conftest import make_pdf
from test_correct import post
from test_review_api import bearer
from test_viewer import DIST, VIEWER, browse, png
from gct.api import server


def dump(root) -> dict:
    """Every row of every table of workspace.db (R3), run and run_event included."""
    with sqlite3.connect(root / "workspace.db") as conn:
        tables = [t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {t: sorted(map(repr, conn.execute(f"SELECT * FROM {t}"))) for t in tables}


@pytest.fixture(scope="module")
def gate(tmp_path_factory):
    return gate_fixture.build(tmp_path_factory.mktemp("gate") / "ws")


@pytest.fixture
def gws(gate, tmp_path):
    """A copy of the gate workspace for one test, so a write in one test is not seen by another."""
    return Path(shutil.copytree(gate, tmp_path / "ws"))


@pytest.fixture
def srv(gws):
    s = server.serve(gws, port=0)
    yield s
    s.stop()


def records(srv, body):
    status, answer = post(srv, "/api/records", body, **bearer(srv))
    assert status == 200, answer
    return answer


# AC 7, S9: the notice is copied into the build, ships in the wheel (test_the_wheel_ships_the_viewer compares every
# file of gct/viewer_dist) and carries Cytoscape's copyright line and MIT permission text.
def test_the_notice_ships_beside_the_build():
    notice = (VIEWER / "public" / "NOTICES.txt").read_bytes()
    assert (DIST / "NOTICES.txt").read_bytes() == notice
    licence = (VIEWER / "node_modules" / "cytoscape" / "LICENSE")
    text = notice.decode()
    assert "Copyright (c) 2016-2026, The Cytoscape Consortium." in text
    assert "Permission is hereby granted, free of charge, to any person obtaining a copy of" in text
    if licence.is_file():
        assert licence.read_text() in text
    for embedded in ("Ralf S. Engelschall", "Gaetan Renaudeau", "Koen Bok", "Event object based on jQuery events"):
        assert embedded in text
    assert "cytoscape 3.34.3" in text and "react 18.3.1" in text


# AC 6 and 8: Cytoscape is in its own chunk, imported by the Graphs chunk only; every built asset is served.
def test_every_built_asset_is_served(srv):
    assets = sorted((DIST / "assets").iterdir())
    names = [a.name for a in assets]
    assert any(n.startswith("cytoscape") for n in names) and any(n.startswith("Graphs-") for n in names)
    index = (DIST / "index.html").read_text()
    assert "cytoscape" not in index and "Graphs-" not in index
    main = next(a for a in assets if a.name.startswith("index-") and a.suffix == ".js").read_text()
    assert "cytoscape" not in main  # the main bundle imports the Graphs chunk only
    for a in assets:
        status, _, data = png(srv, f"/assets/{a.name}")
        assert status == 200 and data == a.read_bytes(), a.name


LABELS = """
import { readFileSync } from "node:fs";
import { hypergraph, neighbourhood, timeSeries } from "./src/graphs.ts";
const words = { ghg_scope_1: "Scope 1 emissions", energy_total: "total energy", waste_total: "total waste",
  water_withdrawal_total: "water withdrawal" };
const out = JSON.parse(readFileSync(process.argv[1], "utf8")).map(([shape, a]) => (shape === "series"
  ? timeSeries(a) : [...neighbourhood(a, words), ...hypergraph(a, words)]).map((i) => ({ id: i.id, kind: i.kind,
  source: i.source ?? null, target: i.target ?? null, claim: i.claim ?? null, text: [i.label, i.word, ...i.notes].join(" | ") })));
console.log(JSON.stringify(out));
"""

FILTERS = [("graph", {}), ("graph", {"document": [5]}), ("graph", {"period": {"from": "2024-04-01"}}),
           ("graph", {"metric": ["ghg_scope_1"]}), ("series", {"series": ["2b7f0c7666c0"]}),
           ("series", {"series": ["4ec43b1266be"]})]


def items_of(srv, tmp_path, cases=FILTERS):
    """The Graphs tab's element list (viewer/src/graphs.ts) for the real answers of these filters."""
    if not shutil.which("node"):
        pytest.skip("node is not on PATH; the viewer logic needs it (contributors only)")
    answers = [[shape, records(srv, {"filter": f, "shape": shape})] for shape, f in cases]
    (tmp_path / "answers.json").write_text(json.dumps(answers))
    r = subprocess.run(["node", "--input-type=module", "-e", LABELS, str(tmp_path / "answers.json")], cwd=VIEWER,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return answers, json.loads(r.stdout)


# AC 8 and the R2 label rows on the gate fixture's real answers
def test_the_tab_shows_no_internal_names_on_the_gate_fixture(srv, tmp_path):
    answers, views = items_of(srv, tmp_path)
    internal = re.compile(r"\w_\w|\b(claim|page|cell|period|boundary|series|hub|company|auditor|flag|highlight"
                          r"|adjudication):\S|ghg_|%|\bscore")
    for items in views:
        for i in items:
            assert not internal.search(i["text"]), i
            assert not re.search(r"verified|assured|certified|compliant", re.sub(r'"[^"]*"', "", i["text"]), re.I), i
    every = views[0]
    assert {i["id"] for i in every if i["kind"] == "claim"} == {n["id"] for n in answers[0][1]["nodes"] if n["kind"] == "claim"}
    auditor = next(i for i in every if i["id"] == "auditor:1")
    assert 'Raj wrote: "not verified against the meter log"' in auditor["text"]  # contributor text, quoted with its author
    cell = next(i for i in every if i["kind"] == "cell")
    assert cell["text"].startswith("sheet acme-meter cell B2 of acme-meter.csv")
    # two companies with the same metric key and period: no comparison edge between them (G1 fixture)
    company = {n["row"]["claim"]["id"]: n["row"]["claim"]["company"] for n in answers[0][1]["nodes"] if n["kind"] == "claim"}
    for e in every:
        if e["kind"] == "comparison":
            a, b = (int(x.split(":")[1]) for x in (e["source"], e["target"]))
            assert company[a] == company[b], e
    # a deleted document named in the filter: no nodes, the deletion line
    assert views[1] == [] and answers[1][1]["deleted_in_filter"][0]["text"] == "Document 5 was permanently deleted."
    # a period condition: a claim with an unknown period is not drawn, and the shell counts it as left out
    assert answers[2][1]["excluded"]["period_unknown"] >= 1
    assert "claim:17" not in {i["id"] for i in views[2]}
    # the time series: both state words on their edges (a restatement, an unresolved conflict)
    assert [i["text"].split(" | ")[0] for i in views[4] if i["kind"] == "comparison"] == ["restatement"]
    assert [i["text"].split(" | ")[0] for i in views[5] if i["kind"] == "comparison"] == ["unresolved conflict"]
    # a series answer without one series is no drawing
    assert records(srv, {"shape": "series"})["drawable"] is False


# AC 1 to 6, 9 and 10 (G2 for Graphs): the browser mode on the gate fixture; R3: nothing is written
def test_graphs_in_a_headless_browser(gws, srv, tmp_path):
    before = dump(gws)
    out = browse(srv, tmp_path, "graphs")
    assert dump(gws) == before  # no Graphs request writes anything, run and run_event included
    # the requests the page sent: reads only; Cytoscape requested only once the Graphs tab opened (GR1)
    assert all(r.startswith("GET ") or r == "POST /api/records" for r in out["requests"]), out["requests"]
    assert out["before"] == [] and out["after"] == 1
    assert out["shell"] == out["graph"] == "14 claims match in data version 1."
    # G2: the same filter shows the same count and data version in Tables (story 6.2) and in Graphs
    tables = "Claims matching the filter in published data version 1"
    assert out["tablesAll"] == {"rows": "Rows 1 to 14 of 14", "caption": tables}
    assert out["acme"] == {"shell": "9 claims match in data version 1.", "graph": "9 claims match in data version 1.",
                           "tables": {"rows": "Rows 1 to 9 of 9", "caption": tables}}
    assert out["role"] == "img"
    assert out["label"] == "Graph of 14 claims in data version 1; every node and edge is in the tables below"
    assert out["tablesMatch"] is True  # the Nodes and Edges tables list exactly the canvas's elements
    assert len(out["claimNodes"]) == 14
    assert "a hub joins one claim to the items it is linked to" in out["legend"]
    assert "2 claims of 1 archived document are not in this or any view." in out["archived"]  # F7, above the tab
    # a node and an edge by mouse: a tap selects and marks the row; a double-click opens the page with the box
    assert out["nodeTap"] == {"selected": ["claim:1"], "picked": True}
    assert out["edgeTap"] == {"selected": ["claim:1>company:1"], "picked": True}
    for opened in (out["node"], out["edge"], out["keyboard"]):
        assert opened["shown"] and opened["box"] and opened["page"] == "Page 1 of acme-2025.pdf", opened
        assert "1,234" in opened["claim"], opened
    assert out["nodeBack"]["nodes"] > 0  # the drawing is kept while the tab is hidden
    # keyboard only: Tab reaches the row with visible focus and selects its edge; Enter opens what the click opened
    assert out["focused"] == {"el": "claim:1>company:1", "visible": True, "selected": ["claim:1>company:1"]}
    assert out["keyboard"] == out["edge"]
    assert out["returned"]["el"] == "claim:1>company:1"  # back in Tables and Graphs, focus is on the row that opened it
    assert out["arrows"]["claim"] == out["keyboard"]["claim"]  # the arrows in the tables never moved Evidence's claim
    assert out["cell"] == "700"  # a spreadsheet cell opens the cell view with the cell marked
    assert out["auditor"].endswith(": no document cited") and out["stillHere"]
    assert out["seriesNode"].endswith("A series groups claims; open one of its claims to see its source.")
    assert out["sides"] == ["page 1 of acme-2025.pdf", "page 1 of acme-2024.pdf"]  # a comparison offers both sides
    hyper = out["hyper"]
    assert hyper["sameRequest"] and hyper["hubs"] == hyper["claims"] == hyper["rows"] == 14
    assert "claim:1" in hyper["member"] and "page:1:1" in hyper["member"]
    assert out["noSeries"].startswith("These claims are in no series:") and out["noCanvas"]
    s1, energy = out["scope1"], out["energy"]
    assert len(s1["points"]) == 4 and s1["nodes"] == 4
    assert s1["edges"] == [["point:2", "point:5", "restatement", False]]
    assert s1["x"]["point:2"][0] == s1["x"]["point:5"][0] and s1["x"]["point:2"][1] != s1["x"]["point:5"][1]
    assert [c.split("\t")[-1] for c in s1["comparisons"]] == ["restatement"]
    assert [e[2:] for e in energy["edges"]] == [["unresolved conflict", True]]
    assert out["newest"]["graph"] == out["newest"]["shell"] == "14 claims match in data version 1."
    shown = out["graphText"] + out["text"]
    assert not re.search(r"\w_\w|\b(claim|page|period|boundary|series|hub):\S", shown)
    assert not re.search(r"verified|assured|certified|compliant", re.sub(r'"[^"]*"', "", shown), re.I)
    assert out["grabbable"] is True  # nodes can be dragged for viewing; nothing is saved


# R2 as ruled in 6.1 F11 i1: a second writer publishes while the tab shows version 1; the Graphs tab's own next request
# is refused, the shell's notice offers version 2, the drawing on screen stays labelled with version 1 and nothing of
# version 2 is drawn until Reload.
def test_a_newer_version_is_offered_never_mixed_in(srv, tmp_path):
    out = browse(srv, tmp_path, "graphs-stale")
    assert out["second_writer"] == 200
    assert out["notice"] == "Data version 2 is available. Reload"
    assert out["kept"] == {"drawn": True, "graph": "14 claims match in data version 1.", "hint": None}
    assert out["graph"] == out["shell"] == "14 claims match in data version 2."


def big(folder: Path) -> Path:
    """One company, a 10-page report of 250 rows across two periods (500 claims) and a one-claim report (501)."""
    root = Path(folder)
    gate_fixture.gct("workspace", "init", root)
    w = ("--workspace", root)
    gate_fixture.gct("company", "add", "Big", *w)
    gate_fixture.gct("contributor", "add", "ana", "--name", "Ana", *w)
    rows = [[f"Indicator {i}", "t", f"{1000 + i}", f"{900 + i}"] for i in range(250)]
    with tempfile.TemporaryDirectory() as tmp:
        for name, pages in (("big.pdf", [gate_fixture.page(rows[k:k + 25], ("FY 2024-25", "FY 2023-24"))
                                         for k in range(0, 250, 25)]),
                            ("one.pdf", [gate_fixture.page([["Employees trained", "number", "120"]], ("FY 2024-25",))])):
            (Path(tmp) / name).write_bytes(make_pdf(pages))
            gate_fixture.gct("doc", "add", Path(tmp) / name, "--company", "Big", *w)
    gate_fixture.ready(w, 0)
    gate_fixture.gct("publish", "build", *w)
    return root


# R2 and AC 10: 501 claims answer the limit text and no canvas; 500 are drawn with cose, timed in headless Chrome.
def test_the_graph_limit_and_500_claims(tmp_path):
    s = server.serve(big(tmp_path / "big"), port=0)
    try:
        assert records(s, {"shape": "graph", "filter": {"document": [1]}})["matched"] == 500
        out = browse(s, tmp_path, "graphs-limit")
    finally:
        s.stop()
    print(json.dumps({k: out[k] for k in ("firstDraw", "cose", "hyperDraw", "neighbourhood", "hubs")}))
    assert out["limit"] == "501 claims match; a graph draws at most 500. Narrow the filter."
    assert out["limitCanvas"] is False
    assert out["neighbourhood"]["claims"] == 500 and out["hubs"] == 500
    assert out["layout"] == out["hyperLayout"] == "breadthfirst"  # above 250 nodes (docs/views.md, Graphs)
    assert out["firstDraw"] < 5000 and out["hyperDraw"] < 5000
    assert out["graph"] == out["shell"] == "500 claims match in data version 1."
