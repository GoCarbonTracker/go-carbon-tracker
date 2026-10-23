"""Story 7.5: the viewer pages, on tests/report_fixture.py (7.1 section G) and a planted copy of it. Every check reads
the files write produced: html.parser for structure and rows (G 1, the authoritative row check) and headless Chrome
for what a reader sees (G 2). read_back(path) and printed(value, row, key, fmt) are the page format's part of the
shared read-back contract (C4b, readiness resolution 3 as amended) that 7.7 calls for every format."""
import ast
import copy
import csv
import gc
import hashlib
import http.server
import io
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pytest

import report_fixture as f
from gate_fixture import gct as run
from leakage import found
from test_dataset import renderer_problems
from test_gate_privacy_exports import build, env, w  # noqa: F401 (module fixtures: the fixture and its environment)
from test_json import check
from test_messages import INTERNAL_WORDS, internal_names
from test_review import WORDS
from test_view import dump
from gct.reports import crops, dataset, export, render_page
from gct.stages import adjudicate
from gct.workspace import labels, layout

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ("evidence_index", "restatement_log", "gap_report")
FILES = {r: f"{r.replace('_', '-')}.html" for r in REPORTS}
SECTIONS = ("candidates", "expectations", "documents_checked", "extraction_limits", "archived", "deleted")  # C3c
POLICY = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"  # 7.5-P6
BANNED = {"script", "iframe", "object", "embed", "link", "base"}
GUARD = re.compile(WORDS.pattern + "|contradiction", re.I)
PLANTS = ('</td><script>document.title="GCT-INJECT-01"</script>',
          '"><img src=x onerror="document.title=\'GCT-INJECT-02\'">', "</script><!--GCT-INJECT-03")
WHO = ("--as", "ana", "--capacity", "analyst")
MAPPING = ("--metric", "Metric", "--value", "Value", "--unit", "Unit", "--period", "Period", "--boundary", "Boundary",
           "--company", "Company", "--year-end", "03-31", "--boundary-is", "standalone", *WHO, "--rationale", "plants")


def collapse(s: str) -> str:
    return " ".join(s.split())


# The read-back contract (C4b)

def shown_value(value, row, key, words):
    """The test-owned page print rule, independent of renderer code."""
    if row is not None and key in row["withheld"]:
        return words["withheld"]
    if key is not None and key.startswith("outside_selection."):
        return words["outside_selection"] if value else ""
    if value is None:
        return ""
    if isinstance(value, bool):
        return words["fixed"]["booleans"]["true" if value else "false"]
    if isinstance(value, list):
        return words["fixed"]["separator"].join(str(x) for x in value)
    return str(value)


def printed(value, row, key, fmt):
    """The page print rule with HTML null replacement and collapsed white space."""
    return collapse(nul(shown_value(value, row, key, dataset.words())))


def nul(s: str) -> str:
    return s.replace("\0", "\N{REPLACEMENT CHARACTER}")


VOID = {"meta", "img", "br", "hr", "input", "link", "base", "col", "wbr", "source", "area", "embed", "track"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, dict(attrs), parent, []

    def text(self, skip=lambda n: False) -> str:
        return "".join(k if isinstance(k, str) else "" if skip(k) else k.text(skip) for k in self.kids)

    def all(self, tag=None):
        for k in self.kids:
            if isinstance(k, Node):
                if tag is None or k.tag == tag:
                    yield k
                yield from k.all(tag)

    def children(self, tag, cls=None) -> list:
        return [k for k in self.kids if isinstance(k, Node) and k.tag == tag and (cls is None or k.attrs.get("class") == cls)]


class Tree(HTMLParser):
    """The element tree of one page. An end tag that closes no open element, a comment and a declaration other than
    the doctype are recorded, so a page that is not the structure it was written as cannot pass."""

    def __init__(self, data: str):
        super().__init__(convert_charrefs=True)  # entities undone once, in text and attributes
        self.root = self.cur = Node("#document", [], None)
        self.odd = []
        self.feed(data)
        self.close()

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.kids.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n.parent is not None and n.tag != tag:
            n = n.parent
        if n.parent is None:
            self.odd.append(f"</{tag}>")
        else:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.kids.append(data)

    def handle_comment(self, data):
        self.odd.append(f"<!--{data}")

    def handle_decl(self, decl):
        if decl != "DOCTYPE html":
            self.odd.append(decl)


def parse(path) -> Tree:
    return Tree(Path(path).read_bytes().decode("utf-8"))  # no newline translation: a CR stays a CR


def body(tree) -> Node:
    return next(tree.root.all("body"))


def heading(section) -> str:
    return collapse(next(k for k in section.kids if isinstance(k, Node)).text())


def grid(section) -> tuple[list, list]:
    """A section's own table: its headings and [(row tr, extras tr or None)]."""
    table = next(section.all("table"))
    heads = [collapse(th.text()) for th in table.children("thead")[0].children("tr")[0].children("th")]
    trs = table.children("tbody")[0].children("tr")
    rows = [(tr, trs[k + 1] if k + 1 < len(trs) and trs[k + 1].attrs.get("class") == "more" else None)
            for k, tr in enumerate(trs) if tr.attrs.get("class") == "row"]
    return heads, rows


def cells(tr) -> list[str]:
    """A row's cell texts; the second link of a pair side (to the evidence index page) is not part of the value."""
    return [collapse(td.text(lambda n: n.attrs.get("class") == "also")) for td in tr.children("td")]


def read_back(path) -> dict:
    """{data_version: the identity rows of the page, rows: {table: [{columns key: value}]}} of an export folder, for
    the pages it holds: evidence_index, restatement_log (pair rows only) and gap_report.<section> for every section,
    an empty one included. A table is the <section class="report"> its fixed title heads; its headings map back to
    keys through dataset.COLUMNS. Values are the printed strings (html.parser undoes entities; white space collapsed)."""
    fixed = dataset.words()["fixed"]
    identity = {v: k for k, v in fixed["identity"].items()}
    titles = {v: k for k, v in fixed["titles"].items()}
    out = {"data_version": {}, "rows": {}}
    for report in REPORTS:
        page = Path(path) / FILES[report]
        if not page.exists():
            continue
        top = body(parse(page))
        [about] = top.children("section", "identity")
        out["data_version"] = {identity[collapse(tr.children("th")[0].text())]: collapse(tr.children("td")[0].text())
                               for tr in about.all("tr") if collapse(tr.children("th")[0].text()) in identity}
        for sec in top.children("section", "report"):
            table = titles[heading(sec)]
            keys = {c["heading"]: c["key"] for c in dataset.COLUMNS[table]}
            heads, rows = grid(sec)
            out["rows"]["gap_report." + table if report == "gap_report" else table] = [
                dict(zip([keys[h] for h in heads], cells(tr))) for tr, _ in rows]
    return out


# The dataset side, written out here (Design, "Pages")

def dotted(row, key):
    value = row
    for part in key.split("."):
        if value is None:
            return None
        value = value[{"a": 0, "b": 1}[part]] if isinstance(value, list) else value[part]
    return value


def subs(table_id, row) -> list:
    """The non-empty sub-tables a page prints under a row: none under a pair side (its records are the evidence
    index's)."""
    return [] if table_id == "pair_sides" else [v for v in row.values() if isinstance(v, dict) and "rows" in v
                                                and v["rows"]]


def walk(table_id, rows):
    """Every row of a table and of the sub-tables printed under it; table_id None walks every sub-table."""
    for r in rows:
        yield r
        for v in subs(table_id, r):
            yield from walk(v["id"], v["rows"])


def sides(d, pairs) -> tuple[list, set]:
    ei = {r["id"]: r for r in d["evidence_index"]}
    rc = {r["id"]: r for r in d["related_claims"]}
    seen = {}
    for p in pairs:
        for k in ("claim_a", "claim_b"):
            if p[k] in ei or p[k] in rc:
                seen.setdefault(p[k], ei.get(p[k]) or rc[p[k]])
    return list(seen.values()), set(seen) - set(ei)


def tables_of(d, report) -> list[tuple]:
    """(table id, columns key, rows, outside side ids) of every top-level table of a page, in page order."""
    if report == "gap_report":
        out = []
        for s in SECTIONS:
            out.append((s, s, d["gap_report"][s], set()))
            if s == "candidates":
                out.append(("pair_sides", "evidence_index", *sides(d, d["gap_report"][s])))
    else:
        out = [(report, report, d[report], set())]
    if report == "restatement_log":
        out += [("pair_sides", "evidence_index", *sides(d, d["restatement_log"])),
                ("unpaired_restatements", "unpaired_restatements", d["unpaired_restatements"]["rows"], set())]
    return out + [("documents", "documents", d["documents"], set())]


def attributed(rows, columns) -> bool:
    keys = [c["key"] for c in columns if c["key"] == "contributor" or c["key"].endswith(".contributor")]
    return any(dotted(r, k) is not None for r in rows for k in keys)


def every_table(d, report):
    """(columns, rows) of every table a page prints, sub-tables included."""
    def nested(table_id, rows):
        for r in rows:
            for v in subs(table_id, r):
                yield v["columns"], v["rows"]
                yield from nested(v["id"], v["rows"])

    for t, ck, rows, _ in tables_of(d, report):
        yield d["columns"][ck], rows
        yield from nested(t, rows)


def page_entries(d) -> set:
    return {e["id"] for e in d["evidence"] if e["page"] is not None}


def is_cap(d, c) -> bool:
    return not c and bool(page_entries(d))


def drawn(d, c, reports) -> set:
    """R5.3: the page entries a binding row of a selected report cites; none at the cap."""
    if is_cap(d, c):
        return set()
    return {i for r in reports for t, _, rows, _ in tables_of(d, r) for x in walk(t, rows) if x.get("binds") is not False
            for i in x["evidence"] if i in page_entries(d)}


# G 1: the standard-library check of a written folder

def check_folder(d, c, folder, reports):
    """Every G 1 check on a folder write produced for reports. Returns {report: tree}."""
    w, version = d["words"], d["data_version"]["version"]
    fixed, sep = w["fixed"], w["fixed"]["separator"]
    shown = drawn(d, c, reports)
    names = {p.relative_to(folder).as_posix() for p in Path(folder).rglob("*") if p.is_file()}
    assert names == {FILES[r] for r in reports} | {f"crops/E{i}.png" for i in shown}
    for i in shown:
        assert hashlib.sha256((Path(folder) / "crops" / f"E{i}.png").read_bytes()).digest() == hashlib.sha256(c[i]).digest()
    ids_of = {r: {n.attrs["id"] for n in parse(Path(folder) / FILES[r]).root.all() if "id" in n.attrs} for r in reports}
    ei = {r["id"] for r in d["evidence_index"]}
    by_claim = {r["claim_id"]: r["id"] for r in d["evidence_index"]}
    evidence = {e["id"]: e for e in d["evidence"]}
    documents = {x["id"]: x for x in d["documents"]}
    trees = {}

    def where(div, i, row):
        e = evidence[i]
        name = shown_value(documents[e["document_id"]]["name"], None, None, w)
        loc = [f"E{i}", f"{fixed['headings']['document_name']}: {name}"] + (
            [f"{fixed['headings']['page']}: {e['page']}"] if e["page"] is not None else
            [f"{fixed['headings']['sheet']}: {e['sheet']}", f"{fixed['headings']['cell']}: {e['cell']}"])
        assert collapse(div.children("p")[0].text()) == collapse(nul(sep.join(loc)))
        imgs = div.children("img")
        if i in shown and row.get("binds") is not False:
            claim = row.get("claim_id")
            alt = (fixed["image_alt"].format(claim=claim, document=name, page=e["page"]) if claim is not None else
                   fixed["image_alt_entry"].format(evidence=i, document=name, page=e["page"]))
            assert [x.attrs for x in imgs] == [{"src": f"crops/E{i}.png", "alt": nul(alt)}]
            assert [collapse(p.text()) for p in div.children("p")[1:]] == ([fixed["image_cap"]] if e["boxes"] else [])
        else:
            assert imgs == [], (i, row["id"])
        tables = div.children("table", "cell")
        if e["header"] is None:
            assert tables == []
        else:
            [t] = tables
            n = max(len(e["header"]), len(e["row"]))
            for tr, tag, xs in zip(t.children("tr"), ("th", "td"), (e["header"], e["row"])):
                got = tr.children(tag)
                assert [collapse(x.text()) for x in got] == [printed(xs[k] if k < len(xs) else "", None, None, "")
                                                             for k in range(n)]
                assert [k for k, x in enumerate(got) if x.attrs.get("class") == "marked"] == [e["marked"]]
                assert all(not x.children("a") and not list(x.all()) for x in got)  # text only

    def table(sec, table_id, title, columns, rows, outside, report):
        assert heading(sec) == title
        notes = [collapse(p.text()) for p in sec.children("p")]
        assert notes == ([w["self_declared"]] if attributed(rows, columns) else []), title
        heads, trs = grid(sec)
        assert heads == [x["heading"] for x in columns], title
        assert len(trs) == len(rows), title
        for (tr, more), r in zip(trs, rows):
            cols = d["columns"]["related_claims"] if r["id"] in outside else columns
            got = cells(tr)
            assert got == [printed(dotted(r, x["key"]), r, x["key"], "page") for x in cols], (title, r["id"])
            assert got[[x["key"] for x in cols].index("data_version")] == str(version)
            assert tr.attrs.get("id") == (f"claim-{r['id']}" if table_id in ("evidence_index", "pair_sides") else None)
            tds = dict(zip([x["key"] for x in cols], tr.children("td")))
            for k in ("claim_a", "claim_b") if table_id in render_page.PAIRS else ():
                links = [a.attrs["href"] for a in tds[k].all("a")]
                n = r[k]
                want = [f"#claim-{n}"] if f"claim-{n}" in ids_of[report] else []
                want += [f"evidence-index.html#claim-{n}"] if want and "evidence_index" in reports and n in ei else []
                assert links == want, (title, r["id"], k)
            for k in ("original_claim_id", "restated_claim_id") if table_id == "unpaired_restatements" else ():
                n = r[k]
                assert [a.attrs["href"] for a in tds[k].all("a")] == (
                    [f"evidence-index.html#claim-{by_claim[n]}"] if "evidence_index" in reports and n in by_claim else [])
            parts = more.children("td")[0].kids if more is not None else []
            parts = [x for x in parts if isinstance(x, Node)]
            if r["id"] in outside:
                assert parts[0].tag == "p" and collapse(parts[0].text()) == w["outside_selection"]
                parts = parts[1:]
            divs = [x for x in parts if x.tag == "div"]
            assert [x.attrs.get("class") for x in divs] == ["evidence"] * len(r["evidence"])
            for div, i in zip(divs, r["evidence"]):
                where(div, i, r)
            details = [x for x in parts if x.tag == "details"]
            under = subs(table_id, r)
            assert len(details) == (1 if under else 0) and len(parts) == len(divs) + len(details)
            assert (more is None) == (not parts and r["id"] not in outside)
            if details:
                [summary] = details[0].children("summary")
                assert collapse(summary.text()) == sep.join(v["title"] for v in under)
                inner = details[0].children("section", "sub")
                assert len(inner) == len(under) and len(details[0].children("section")) == len(inner)
                for s, v in zip(inner, under):
                    table(s, v["id"], v["title"], v["columns"], v["rows"], set(), report)

    for report in reports:
        tree = parse(Path(folder) / FILES[report])
        trees[report] = tree
        assert tree.odd == [], (report, tree.odd)
        everything = list(tree.root.all())
        assert not {n.tag for n in everything} & BANNED
        assert not [k for n in everything for k in n.attrs if k.lower().startswith("on")]
        assert [n.attrs for n in everything if n.tag == "meta" and "http-equiv" in n.attrs] == [
            {"http-equiv": "Content-Security-Policy", "content": POLICY}]
        assert len([n for n in everything if n.tag == "style"]) == 1
        ids = [n.attrs["id"] for n in everything if "id" in n.attrs]
        assert all(re.fullmatch(r"claim-\d+", i) for i in ids) and len(ids) == len(set(ids)), report
        for a in tree.root.all("a"):
            m = re.fullmatch(r"(evidence-index\.html)?#(claim-\d+)", a.attrs["href"])
            assert m and m[2] in (ids_of["evidence_index"] if m[1] else set(ids)), a.attrs
            assert not m[1] or "evidence_index" in reports
        for img in tree.root.all("img"):
            m = re.fullmatch(r"crops/E(\d+)\.png", img.attrs["src"])
            assert m and int(m[1]) in shown and int(m[1]) in page_entries(d)
        stamp = f"{fixed['data_version']} {version}"
        title = fixed["titles"][report]
        assert collapse(next(tree.root.all("title")).text()) == f"{title}{sep}{stamp}"
        top = body(tree)
        [header], [footer] = top.children("header"), top.children("footer")
        assert collapse(header.children("h1")[0].text()) == title
        head = [collapse(p.text()) for p in header.children("p")]
        any_attributed = any(attributed(rows, cols) for cols, rows in every_table(d, report))
        assert head == [stamp, fixed["mode"][d["mode"]], *map(collapse, d["notices"]),
                        *([w["self_declared"]] if any_attributed else [])], report
        assert [collapse(p.text()) for p in top.children("p")] == ([fixed["image_limit"]] if is_cap(d, c) else [])
        assert [collapse(p.text()) for p in footer.children("p")] == [stamp]
        about, *secs = top.children("section")
        assert about.attrs["class"] == "identity" and heading(about) == fixed["data_version"]
        rows = [(collapse(tr.children("th")[0].text()), collapse(tr.children("td")[0].text())) for tr in about.all("tr")]
        assert rows == [(fixed["identity"][k], printed(v, None, k, "")) for k, v in d["data_version"].items()] + [
            (fixed["dataset"][k], printed(d[k], None, k, "")) for k in ("gct_version", "built_at", "dataset_schema")] + [
            (fixed["dataset"]["filter"], collapse(json.dumps(d["filter"], ensure_ascii=False))),
            (fixed["dataset"]["include"], printed(d["include"], None, "include", ""))]
        want = tables_of(d, report)
        assert [s.attrs["class"] for s in secs] == [
            "report" if t == report or t in SECTIONS else "table" for t, *_ in want], report
        for sec, (t, ck, rws, outside) in zip(secs, want):
            table(sec, t, fixed["titles"][t], d["columns"][ck], rws, outside, report)
    return trees


# The fixture's pages, one folder per mode

@pytest.fixture(scope="module")
def made(w, env, tmp_path_factory):
    """{mode: (dataset, crops, folder, write's answer)}: every report written once per mode, from the real builder and
    crops.cut."""
    out = {}
    for mode in dataset.MODES:
        d, _ = build(w, mode=mode)
        c = crops.cut(w, d)
        folder = tmp_path_factory.mktemp(f"page-{mode}")
        out[mode] = (d, c, folder, render_page.write(d, list(REPORTS), folder, c))
    return out


@pytest.fixture(scope="module")
def planted(w, env, tmp_path_factory):
    """G's plants on a copy of the fixture workspace, through product commands only: plant 01 as a highlight note on a
    shareable claim, 02 and 03 as metric text of a private and a shareable CSV; then a published version. {"ws": the
    workspace, mode: (dataset, crops, folder, preview)}."""
    base = tmp_path_factory.mktemp("planted")
    ws = Path(shutil.copytree(w, base / "ws"))
    at = ("--workspace", ws)
    for name, plant, extra in (("plant-private.csv", PLANTS[1], ()),
                               ("plant-shared.csv", PLANTS[2], ("--privacy", "shareable"))):
        data = io.StringIO()
        csv.writer(data, lineterminator="\n").writerows(
            [["Metric", "Value", "Unit", "Period", "Boundary", "Company"], [plant, "42", "kL", "FY 2024-25",
                                                                           "Standalone", "Acme"]])
        (base / name).write_text(data.getvalue(), encoding="utf-8")
        doc = run("doc", "add", base / name, "--company", "Acme", "--kind", "evidence", *extra, *at)
        run("sheet", "map", doc["items"][0]["document"]["id"], "--sheet", name[:-4], *MAPPING, *at)
    run("extract", *at)
    d, _ = build(ws, mode="complete")
    claim = next(r["claim_id"] for r in d["evidence_index"] if r["label"] == "shareable")
    version = run("claims", "history", claim, *at)["versions"][-1]["id"]
    run("highlight", "add", claim, "--version", version, "--note", PLANTS[0], *WHO, *at)
    run("publish", "build", *at)
    out = {"ws": ws}
    for mode in dataset.MODES:
        d, preview = build(ws, mode=mode)
        c = crops.cut(ws, d)
        folder = base / mode
        folder.mkdir()
        render_page.write(d, list(REPORTS), folder, c)
        out[mode] = (d, c, folder, preview)
    return out


# AC 1: the dataset only

def test_the_renderer_imports_the_standard_library_only_and_reads_no_workspace():
    source = (ROOT / "gct" / "reports" / "render_page.py").read_text(encoding="utf-8")
    assert renderer_problems(source) == []
    assert "sqlite3" in renderer_problems("import sqlite3\n" + source)  # the planted variant fails
    tree = ast.parse(source)
    mods = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names] + [
        n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert mods and all(m.split(".")[0] in sys.stdlib_module_names for m in mods), mods
    assert not [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) and n.col_offset]  # top only


# AC 2: the call

def test_write_writes_each_page_and_crop_once_with_mode_x(made):
    d, c, folder, out = made["complete"]
    assert export.FORMATS["page"] == {"write": render_page.write, "crops": True}
    assert out["files"] == sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    assert [p.name for p in folder.iterdir() if p.is_dir()] == ["crops"] and out["notes"] == []
    assert {x for x in out["files"] if not x.startswith("crops/")} == set(FILES.values())
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    with pytest.raises(FileExistsError):  # mode x: a page is never overwritten
        render_page.write(d, ["evidence_index"], folder, c)
    assert {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()} == before


# G 1, AC 4, 5, 7: every page holds the dataset's rows, both modes

@pytest.mark.parametrize("mode", dataset.MODES)
def test_every_page_holds_the_datasets_rows_and_nothing_else(made, mode):
    d, c, folder, _ = made[mode]
    check_folder(d, c, folder, REPORTS)
    assert drawn(d, c, REPORTS) and all(d["gap_report"][s] or mode == "sanitised" for s in SECTIONS)


@pytest.mark.parametrize("mode", dataset.MODES)
def test_read_back_gives_the_datasets_rows_through_printed(made, mode):
    d, _, folder, _ = made[mode]
    back = read_back(folder)
    assert back["data_version"] == {k: printed(v, None, k, "page") for k, v in d["data_version"].items()}
    assert set(back["data_version"]) == ({"version", "built_at", "sha256", "projection_schema"} |
                                         ({"history_mark", "labels_mark"} if mode == "complete" else set()))
    tables = {"evidence_index": ("evidence_index", d["evidence_index"]),
              "restatement_log": ("restatement_log", d["restatement_log"]),
              **{f"gap_report.{s}": (s, d["gap_report"][s]) for s in SECTIONS}}
    assert back["rows"] == {t: [{x["key"]: printed(dotted(r, x["key"]), r, x["key"], "page") for x in d["columns"][k]}
                                for r in rows] for t, (k, rows) in tables.items()}
    labelled = [r for t in back["rows"].values() for r in t]
    assert labelled and all(("label" in r) == (mode == "complete") for r in labelled)
    one = Path(str(folder) + "-one")
    one.mkdir()
    render_page.write(d, ["restatement_log"], one, made[mode][1])
    assert set(read_back(one)["rows"]) == {"restatement_log"}  # only the pages the folder holds


def test_every_table_is_on_some_page(made, tmp_path):
    """B7: every columns table except related_claims (pair sides use the evidence index's columns) is printed by some
    page, from the report's own nesting; documents and unpaired restatements are named."""
    d, c, _, _ = made["complete"]
    d = copy.deepcopy(d)
    d["gap_report"]["expectations"][0]["accepted"]["rows"].append(  # the fixture has none
        {"id": 1, "data_version": d["data_version"]["version"], "label": "private", "documents": [], "evidence": [],
         "withheld": [], "expected_item_id": d["gap_report"]["expectations"][0]["expected_item_id"],
         "type": "figures", "acceptance_id": 1, "count": 1})
    render_page.write(d, list(REPORTS), tmp_path, c)
    trees = check_folder(d, c, tmp_path, REPORTS)
    titles = {v: k for k, v in d["words"]["fixed"]["titles"].items()}
    seen = {titles[heading(s)] for t in trees.values() for s in t.root.all("section") if s.attrs["class"] != "identity"}
    assert seen == set(d["columns"]) - {"related_claims"} | {"pair_sides"}


def test_printed_forms():
    w = dataset.words()
    row = {"withheld": ["note"]}
    assert [printed(v, row, k, "page") for k, v in (
        ("a", True), ("a", False), ("a", 1234.0), ("a", 7), ("a", ["x", "y"]), ("a", []), ("a", None), ("note", None),
        ("outside_selection.a", True), ("outside_selection.b", False), ("a", "two\n lines\t"), ("a", "n\0l"))] == [
        "yes", "no", "1234.0", "7", f"x{w['fixed']['separator'].strip()} y", "", "", w["withheld"],
        w["outside_selection"], "", "two lines", nul("n\0l")]


# AC 4: the template names no company

def test_the_template_is_company_independent(made):
    source = (ROOT / "gct" / "reports" / "render_page.py").read_text(encoding="utf-8").casefold()
    d = made["complete"][0]
    names = {x["company"] for x in d["documents"] if x["company"]} | {f.COMPANY, "Tata", "Mahindra"}
    assert names >= {"Acme", "Beta"} and not [n for n in names if n.casefold() in source]


# AC 3: the refusals

def test_each_refusal_comes_before_any_file(made, tmp_path):
    d, c, _, _ = made["complete"]
    again = "Run the report again. If this message repeats, report it as a fault in GCT."
    pages = sorted(page_entries(d))
    other = copy.deepcopy(d)
    row = next(x for r in other["evidence_index"] for x in r["records"]["rows"])  # a sub-table row counts too
    row["data_version"] = 1
    cases = [
        (d, {**c, 999: b"png"}, ["evidence_index"],
         "A page image was made for evidence E999, which this report's data does not hold.", again),
        (d, {k: v for k, v in c.items() if k != pages[3]}, ["evidence_index"],
         f"No page image was made for evidence E{pages[3]}.", again),
        (other, c, ["restatement_log", "evidence_index"],
         f"Row {row['id']} of Evidence index comes from data version 1, but this report is for data version"
         f" {d['data_version']['version']}.", "Run the report again so every row comes from one data version."),
        (d, c, ["evidence_index", "summary"], "A viewer page was asked for a report this data does not hold.", again)]
    for data, cut, reports, cause, step in cases:
        folder = tmp_path / "f"
        folder.mkdir()
        with pytest.raises(render_page.Refusal) as e:
            render_page.write(data, reports, folder, cut)
        assert (e.value.cause, e.value.next_step) == (cause, step) and list(folder.iterdir()) == []
        assert isinstance(e.value, Exception) and all(isinstance(x, str) for x in (e.value.cause, e.value.next_step))
        folder.rmdir()


def test_a_refusal_through_gct_report_leaves_no_folder(w, env, gct, tmp_path, monkeypatch):
    ws = Path(shutil.copytree(w, tmp_path / "ws"))
    real = crops.cut
    monkeypatch.setattr(crops, "cut", lambda root, d: {**real(root, d), 999: b"png"})
    names = internal_names(ws)
    human = gct("report", "evidence-index", "--format", "page", "--workspace", ws)
    machine = gct("report", "evidence-index", "--format", "page", "--workspace", ws, "--json")
    assert human.code == machine.code == layout.REFUSED and human.out == ""
    assert machine.data["cause"] == "A page image was made for evidence E999, which this report's data does not hold."
    assert machine.data["next_action"] == "Run the report again. If this message repeats, report it as a fault in GCT."
    assert human.err.startswith("error: ") and "\nnext: " in human.err
    for text in (human.err, machine.out):
        assert not [x for x in [*INTERNAL_WORDS, *names] if x in text]
    assert list((ws / "exports").iterdir()) == []


# AC 6: records per version and the self-declared line

def test_records_are_listed_under_their_version_and_a_non_binding_one_shows_no_image(made):
    d, c, folder, _ = made["complete"]
    trees = check_folder(d, c, folder, REPORTS)
    earlier = [r for t, _, rows, _ in tables_of(d, "restatement_log") for r in walk(t, rows) if r.get("binds") is False]
    assert earlier and all(r["earlier"] == d["words"]["earlier_version"] for r in earlier)
    assert [r for r in earlier if r["evidence"] and set(r["evidence"]) & page_entries(d)]  # check_folder: no img
    sub = {heading(s): s for s in trees["evidence_index"].root.all("section") if s.attrs.get("class") == "sub"}
    text = d["words"]["fixed"]["titles"]["disagreements"]
    said = [x["text"] for r in d["evidence_index"] for x in r["disagreements"]["rows"]]
    assert said and text in sub
    got = [cells(tr)[[k["key"] for k in d["columns"]["disagreements"]].index("text")]
           for s in trees["evidence_index"].root.all("section") if s.attrs.get("class") == "sub" and heading(s) == text
           for tr, _ in grid(s)[1]]
    assert got == [collapse(x) for x in said]


def strip_contributors(d):
    """A copy with no attributed row: every contributor, correction and confirmation null."""
    d = copy.deepcopy(d)
    for t in (d["evidence_index"], d["related_claims"], d["restatement_log"], d["unpaired_restatements"]["rows"],
              *(d["gap_report"][s] for s in SECTIONS)):
        for r in walk(None, t):
            for k in ("contributor", "correction", "confirmation"):
                if k in r:
                    r[k] = None
    return d


def test_the_self_declared_line_follows_the_one_rule(made, tmp_path):
    d, c, _, _ = made["complete"]
    line = d["words"]["self_declared"]
    none = strip_contributors(d)
    render_page.write(none, list(REPORTS), tmp_path, c)
    for report in REPORTS:
        assert line not in (tmp_path / FILES[report]).read_text(encoding="utf-8")
    check_folder(none, c, tmp_path, REPORTS)
    one = copy.deepcopy(none)
    target = next(r for r in one["evidence_index"] if not subs("evidence_index", r))
    target["correction"] = next(r["correction"] for r in d["evidence_index"] if r["correction"])
    folder = tmp_path / "one"
    folder.mkdir()
    render_page.write(one, ["evidence_index"], folder, c)
    check_folder(one, c, folder, ["evidence_index"])
    top = body(parse(folder / FILES["evidence_index"]))
    assert line in [collapse(p.text()) for p in top.children("header")[0].children("p")]
    assert [collapse(p.text()) for p in top.all("p")].count(line) == 2  # the head and the table
    seen = [heading(s) for s in top.all("section") if line in [collapse(p.text()) for p in s.children("p")]]
    assert seen == [d["words"]["fixed"]["titles"]["evidence_index"]]


# AC 7: evidence, the cap and links

def test_spreadsheet_evidence_is_a_text_table_with_the_cited_cell_marked(made):
    d, c, folder, _ = made["complete"]
    cells_ = [e for e in d["evidence"] if e["header"] is not None]
    assert cells_ and not [e for e in cells_ if e["id"] in c]
    page = parse(folder / FILES["evidence_index"])
    marked = sorted(collapse(x.text()) for x in page.root.all() if x.attrs.get("class") == "marked")
    evidence = {e["id"]: e for e in d["evidence"]}
    cited = [evidence[i] for r in walk("evidence_index", d["evidence_index"]) for i in r["evidence"]]
    assert [e for e in cited if e["header"] is not None]  # every printed row's citations, sub-tables included
    assert marked == sorted(collapse(e[part][e["marked"]]) for e in cited if e["header"] is not None
                            for part in ("header", "row"))  # each cell table in check_folder marks its own cell


def test_the_cap_writes_no_image_and_says_so_once_per_page(made, tmp_path):
    d, _, _, _ = made["complete"]
    out = render_page.write(d, list(REPORTS), tmp_path, {})
    assert not (tmp_path / "crops").exists() and out["notes"] == [d["words"]["fixed"]["image_limit"]]
    assert out["files"] == sorted(FILES.values())
    check_folder(d, {}, tmp_path, REPORTS)  # the sentence is the one paragraph under each header, and no img
    for report in REPORTS:
        assert "<img" not in (tmp_path / FILES[report]).read_text(encoding="utf-8")  # nowhere in the file
    assert not re.search(r"\d", d["words"]["fixed"]["image_limit"])
    cells_only = copy.deepcopy(d)  # no page entry: no images and no sentence
    cells_only["evidence"] = [e for e in d["evidence"] if e["page"] is None]
    keep = {e["id"] for e in cells_only["evidence"]}
    for t in (cells_only["evidence_index"], cells_only["related_claims"], cells_only["restatement_log"],
              cells_only["unpaired_restatements"]["rows"], *(cells_only["gap_report"][s] for s in SECTIONS)):
        for r in walk(None, t):
            r["evidence"] = [i for i in r["evidence"] if i in keep]
    plain = tmp_path / "plain"
    plain.mkdir()
    assert render_page.write(cells_only, list(REPORTS), plain, {})["notes"] == []
    check_folder(cells_only, {}, plain, REPORTS)
    assert d["words"]["fixed"]["image_limit"] not in (plain / FILES["evidence_index"]).read_text(encoding="utf-8")


def test_pair_sides_are_printed_once_and_link_only_to_written_pages(w, env, tmp_path):
    d, _ = build(w, mode="complete", filter={"document": [2]})
    c = crops.cut(w, d)
    assert d["related_claims"] and d["restatement_log"]
    alone = tmp_path / "alone"
    alone.mkdir()
    render_page.write(d, ["restatement_log"], alone, c)
    check_folder(d, c, alone, ["restatement_log"])
    assert "evidence-index.html" not in (alone / FILES["restatement_log"]).read_text(encoding="utf-8")
    rows, outside = sides(d, d["restatement_log"])
    pairs = [p[k] for p in d["restatement_log"] for k in ("claim_a", "claim_b")]
    assert len(rows) == len(set(pairs)) < len(pairs) and outside  # a side in two pairs is one row
    both = tmp_path / "both"
    both.mkdir()
    render_page.write(d, list(REPORTS), both, c)
    check_folder(d, c, both, REPORTS)  # each pair cell holds exactly its expected links
    also = [a for a in parse(both / FILES["restatement_log"]).root.all("a") if a.attrs.get("class") == "also"]
    assert also and all(a.attrs["href"].startswith("evidence-index.html#claim-") for a in also)


# AC 8: HTML safety

SPECIAL = ['<img src="file:///etc/hosts"/>', "</td><td>forged", "&amp;", "a & b", "x < y", '"quoted" \'single\'',
           "data\nCompany: ForgedCo", "T" * 2000, "".join(map(chr, range(1, 32))), "n\0l", "CO₂", "שלום", "a\r\nb",
           "<!--", "]]>", "<details open><summary>x</summary>", "&#x3C;script&#x3E;"]


def test_hostile_text_stays_text_in_its_own_cell(made, tmp_path):
    d, c, _, _ = made["complete"]
    d = copy.deepcopy(d)
    rows = sorted(d["evidence_index"], key=lambda r: r["id"])[:len(SPECIAL)]
    for r, s in zip(rows, SPECIAL):
        r["metric_text"] = s
    d["documents"][0]["name"] = 'doc"><img src=x onerror=alert(1)>\nCompany: SpoofCo'
    render_page.write(d, list(REPORTS), tmp_path, c)
    trees = check_folder(d, c, tmp_path, REPORTS)
    keys = [x["key"] for x in d["columns"]["evidence_index"]]
    for r, s in zip(rows, SPECIAL):
        [tr] = [n for n in trees["evidence_index"].root.all("tr") if n.attrs.get("id") == f"claim-{r['id']}"]
        tds = tr.children("td")
        assert len(tds) == len(keys) and tds[keys.index("metric_text")].text() == nul(s), s
        assert not list(tds[keys.index("metric_text")].all())  # no element inside the cell
    back = {b["claim_id"]: b["metric_text"] for b in read_back(tmp_path)["rows"]["evidence_index"]}
    assert [back[str(r["claim_id"])] for r in rows] == [printed(s, None, None, "page") for s in SPECIAL]


@pytest.mark.parametrize("mode", dataset.MODES)
def test_the_plants_are_text_on_the_planted_pages(planted, mode):
    d, c, folder, _ = planted[mode]
    trees = check_folder(d, c, folder, REPORTS)
    found_ = set()
    for tree in trees.values():
        for cell in tree.root.all():  # a row's cells and a spreadsheet row's cells (the rest only contain them)
            if cell.tag in ("td", "th") and "GCT-INJECT" in cell.text() and (
                    cell.parent.attrs.get("class") == "row" or cell.parent.parent.attrs.get("class") == "cell"):
                assert cell.text() in PLANTS and not list(cell.all()), cell.text()
                found_.add(cell.text())
    assert found_ == (set(PLANTS) if mode == "complete" else {PLANTS[2]})


# G 2: the browser check

def chrome():
    path = shutil.which("google-chrome") or shutil.which("chromium") or next(
        (p for p in ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"] if Path(p).exists()), None)
    if not path or not shutil.which("node"):
        pytest.skip("headless Chrome or node is not installed")
    return path


def browse(tmp_path, *urls) -> dict:
    """Run tests/report_page_browser.mjs on the pages in a headless Chrome (the recipe of test_viewer.browse); its JSON
    output."""
    path = chrome()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    browser = subprocess.Popen([path, "--headless=new", f"--remote-debugging-port={port}",
                                f"--user-data-dir={tmp_path / 'chrome'}", "--no-first-run", "--disable-gpu",
                                "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        r = subprocess.run(["node", str(ROOT / "tests" / "report_page_browser.mjs"), str(port), *urls],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
    finally:
        browser.terminate()
        browser.wait(timeout=10)
    return json.loads(r.stdout)


def test_the_pages_in_a_browser(planted, tmp_path):
    urls = {(mode, r): (planted[mode][2] / FILES[r]).as_uri() for mode in dataset.MODES for r in REPORTS}
    out = browse(tmp_path, *urls.values())
    assert [p["url"] for p in out["pages"]] == list(urls.values())
    allowed = {u for u in urls.values()} | {(planted[m][2] / "crops" / f"E{i}.png").as_uri()
                                             for m in dataset.MODES for i in drawn(planted[m][0], planted[m][1], REPORTS)}
    assert out["requests"] and set(out["requests"]) <= allowed  # K22: no API route, nothing off the folder
    seen = {m: set() for m in dataset.MODES}
    for ((mode, report), url), page in zip(urls.items(), out["pages"]):
        d = planted[mode][0]
        fixed = d["words"]["fixed"]
        stamp = f"{fixed['data_version']} {d['data_version']['version']}"
        assert page["title"] == f"{fixed['titles'][report]}{fixed['separator']}{stamp}" and "GCT-INJECT" not in page["title"]
        assert page["scripts"] == 0
        assert page["images"] and all(i["complete"] and i["width"] > 0 for i in page["images"])
        assert sorted(i["src"] for i in page["images"]) == sorted(
            f"crops/E{i}" + ".png" for t, _, rows, _ in tables_of(d, report) for r in walk(t, rows)
            if r.get("binds") is not False for i in r["evidence"] if i in drawn(d, planted[mode][1], [report]))
        text = collapse(page["text"])
        assert text.count(stamp) >= 3  # header, identity block (version row), footer
        for cols, rows in every_table(d, report):
            for r in rows:
                for x in cols:
                    assert printed(dotted(r, x["key"]), r, x["key"], "page") in text, (report, r["id"], x["key"])
        for cell in page["inject"]:
            assert cell["text"] in PLANTS and cell["children"] == 0, cell
            seen[mode].add(cell["text"])
    assert seen == {"complete": set(PLANTS), "sanitised": {PLANTS[2]}}
    # G 5: the innerText of each mode's pages, scanned as a file with the same seeds
    texts = {m: "\n".join(p["text"] for (mode, _), p in zip(urls, out["pages"]) if mode == m) for m in dataset.MODES}
    for m in dataset.MODES:
        (tmp_path / f"{m}.txt").write_text(texts[m], encoding="utf-8")
    d, c, folder, _ = planted["complete"]
    seeds = seeds_of(d, c)
    assert set(found(tmp_path / "complete.txt", seeds)) == {n for n, how in expected_hits(d, c, seeds).items()
                                                            if how == "text"}
    assert found(tmp_path / "sanitised.txt", seeds) == {}


def test_the_policy_stops_an_outside_image(tmp_path):
    chrome()
    hits = []

    class Listener(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Listener)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/x"
        meta = f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">'
        for name, head in (("open.html", ""), ("guarded.html", meta)):
            (tmp_path / name).write_text(f'<!DOCTYPE html><html><head><meta charset="utf-8">{head}</head>'
                                         f'<body><img src="{url}"></body></html>', encoding="utf-8")
        out = browse(tmp_path, (tmp_path / "open.html").as_uri())
        assert hits == ["/x"]  # without the policy the image is requested
        hits.clear()
        out = browse(tmp_path / "second", (tmp_path / "guarded.html").as_uri())
        assert hits == []
        assert any("Content Security Policy" in x for x in out["log"]), out["log"]
    finally:
        server.shutdown()
        server.server_close()


# AC 9: behaviour

def test_archive_deletion_and_notices(made, w, env):
    d, _, folder, _ = made["complete"]
    s, _, sfolder, _ = made["sanitised"]
    back = read_back(folder)["rows"]
    assert [r["name"] for r in back["gap_report.archived"]] == [printed(r["name"], r, "name", "") for r in
                                                               d["gap_report"]["archived"]]
    assert [r["document_id"] for r in back["gap_report.deleted"]] == [str(r["document_id"]) for r in
                                                                     d["gap_report"]["deleted"]]
    assert read_back(sfolder)["rows"]["gap_report.archived"] == read_back(sfolder)["rows"]["gap_report.deleted"] == []
    assert s["words"]["archive_notice"] in s["notices"] and s["words"]["privacy_notice"] in s["notices"]
    gone = [x for x in run("doc", "list", "--workspace", w)["documents"] if x["state"] == "deleted"]
    assert gone
    for f_ in (folder, sfolder):
        for p in f_.glob("*.html"):
            text = p.read_text(encoding="utf-8")
            assert not [x for x in gone if x["sha256"] in text or x["logical_name"] in text]
    review = next(r for x in d["evidence_index"] for r in x["records"]["rows"] if r["evidence_state"] == "archived")
    assert review  # printed with its state in complete mode (check_folder)


def test_missing_states_limits_and_renewed_review(made, tmp_path):
    d, c, folder, _ = made["complete"]
    back = read_back(folder)["rows"]
    assert [r["state"] for r in back["gap_report.expectations"]] == [r["state"] for r in d["gap_report"]["expectations"]]
    assert "processing incomplete or failed" in [r["state"] for r in back["gap_report.expectations"]]
    assert "charts not read" in [r["reason"] for r in back["gap_report.extraction_limits"]]
    assert back["gap_report.documents_checked"]
    renewed = copy.deepcopy(d)
    renewed["evidence_index"][0]["needs_renewed_review"] = ["correction on version 3", "auditor review on version 2"]
    render_page.write(renewed, ["evidence_index"], tmp_path, c)
    heads, rows = grid(body(parse(tmp_path / FILES["evidence_index"])).children("section", "report")[0])
    assert d["words"]["fixed"]["headings"]["needs_renewed_review"] in heads
    [row] = [r for r in read_back(tmp_path)["rows"]["evidence_index"] if r["claim_id"] == str(
        renewed["evidence_index"][0]["claim_id"])]
    assert row["needs_renewed_review"] == "correction on version 3; auditor review on version 2"


@pytest.mark.parametrize("mode", dataset.MODES)
def test_an_empty_selection_writes_every_page(w, env, tmp_path, mode):
    d, _ = build(w, mode=mode, filter={"text": "GCT-NO-SUCH-METRIC"})
    assert d["evidence_index"] == [] and d["restatement_log"] == []
    c = crops.cut(w, d)
    render_page.write(d, list(REPORTS), tmp_path, c)
    check_folder(d, c, tmp_path, REPORTS)
    assert any("No " in n or "no " in n for n in d["notices"])  # the empty-result line, printed by check_folder


def test_every_document_private_prints_the_notices_and_nothing_of_a_document(w, env, tmp_path):
    ws = Path(shutil.copytree(w, tmp_path / "ws"))
    at = ("--workspace", ws)
    docs = run("doc", "list", *at)["documents"]
    for x in docs:
        if x["state"] != "deleted" and x["privacy"] == "shareable":
            run("doc", "label", x["id"], "--privacy", "private", *WHO, "--rationale", "all private", *at)
    run("publish", "build", *at)
    d, _ = build(ws, mode="sanitised")
    assert d["documents"] == [] and d["evidence"] == []
    folder = tmp_path / "out"
    folder.mkdir()
    render_page.write(d, list(REPORTS), folder, crops.cut(ws, d))
    check_folder(d, {}, folder, REPORTS)
    assert not (folder / "crops").exists()
    for p in folder.iterdir():
        text = body(parse(p)).text()
        assert not [x for x in docs if x["logical_name"] and x["logical_name"] in text]
        assert not [x for x in docs if x["sha256"] in text]


def test_withheld_and_never_recorded_print_differently(made):
    d, _, folder, _ = made["sanitised"]
    back = read_back(folder)["rows"]["evidence_index"]
    w = d["words"]["withheld"]
    pairs = [(b[k], k in r["withheld"]) for b, r in zip(back, d["evidence_index"]) for k in b
             if dotted(r, k) is None]
    assert (w, True) in pairs and ("", False) in pairs and (w, False) not in pairs and ("", True) not in pairs


# AC 10: the wording guard

def sentinel(d, value="ZQXSENTINEL"):
    """A copy with every DOCUMENT_TEXT, IDENTITY and CONTRIBUTOR_TEXT field (labels.py) replaced by value."""
    names = labels.DOCUMENT_TEXT | labels.IDENTITY | labels.CONTRIBUTOR_TEXT
    d = copy.deepcopy(d)

    def fill(x):
        return value if isinstance(x, str) else [fill(v) for v in x] if isinstance(x, list) else (
            {k: fill(v) for k, v in x.items()} if isinstance(x, dict) else x)

    def go(x, parent=None):
        if isinstance(x, list):
            for v in x:
                go(v, parent)
        elif isinstance(x, dict):
            for k, v in x.items():
                if k in names or f"{parent}.{k}" in names:
                    x[k] = fill(v)
                elif not (parent is None and k in ("words", "columns", "notices")):
                    go(v, k)

    go(d)
    return d


@pytest.mark.parametrize("mode", dataset.MODES)
def test_the_wording_guard_on_every_page_with_details_open(made, mode, tmp_path):
    d, c, folder, _ = made[mode]
    s = sentinel(d)
    render_page.write(s, list(REPORTS), tmp_path, c)
    for report in REPORTS:
        text = body(parse(tmp_path / FILES[report])).text().replace("ZQXSENTINEL", "")
        assert not GUARD.search(text), (report, GUARD.search(text))
        real = body(parse(folder / FILES[report])).text()
        own = {v for _, rows in every_table(d, report) for r in rows for k, v in r.items()
               if k in labels.CONTRIBUTOR_TEXT and isinstance(v, str)}  # contributor text may say anything
        for v in sorted(own, key=len, reverse=True):
            real = real.replace(v, "")
        for code in adjudicate.STATES:
            assert code not in real, (report, code)
    planted = copy.deepcopy(s)
    planted["evidence_index"][0]["metric_text"] = "verified by hand"
    other = tmp_path / "x"
    other.mkdir()
    render_page.write(planted, ["evidence_index"], other, c)
    assert GUARD.search(body(parse(other / FILES["evidence_index"])).text())  # the guard can fail


# AC 11: leakage

def seeds_of(d, c) -> list:
    """report_fixture.SEEDS, the two plant tokens and one image seed per private page entry's crop (G 5)."""
    seeds = copy.deepcopy(f.SEEDS) + [
        {"name": "GCT-INJECT-01", "kind": "contributor", "expect": "complete_only", "value": "GCT-INJECT-01"},
        {"name": "GCT-INJECT-02", "kind": "document_text", "expect": "complete_only", "value": "GCT-INJECT-02"}]
    private = {x["id"] for x in d["documents"] if x["label"] == "private"}
    for e in d["evidence"]:
        if e["page"] is not None and e["document_id"] in private and rgb_hash(c[e["id"]]) not in {
                s["value"] for s in seeds}:
            seeds.append({"name": f"crop-E{e['id']:04d}", "kind": "image", "expect": "complete_only",
                          "value": rgb_hash(c[e["id"]])})
    return seeds


def rgb_hash(png: bytes) -> str:
    from PIL import Image

    return hashlib.sha256(Image.open(io.BytesIO(png)).convert("RGB").tobytes()).hexdigest()


def expected_hits(d, c, seeds) -> dict:
    """{seed name: how} found must report on a complete folder of all three pages, computed from the fields the pages
    print (resolution 12) and the crops they hold."""
    w = d["words"]
    strings = [*d["notices"], json.dumps(d["filter"], ensure_ascii=False), *map(str, d["data_version"].values())]
    for report in REPORTS:
        for cols, rows in every_table(d, report):
            strings += [printed(dotted(r, x["key"]), r, x["key"], "page") for r in rows for x in cols]
    documents = {x["id"]: x for x in d["documents"]}
    cited = {i for r in REPORTS for t, _, rows, _ in tables_of(d, r) for x in walk(t, rows) for i in x["evidence"]}
    for e in (x for x in d["evidence"] if x["id"] in cited):
        strings += [str(documents[e["document_id"]]["name"]), *(e["header"] or []), *(e["row"] or [])]
    strings.append(w["fixed"]["image_alt"])
    hay = "".join("\n".join(strings).casefold().split())
    out = {s["name"]: "text" for s in seeds if s["kind"] in ("document_text", "contributor", "credential", "path")
           and s["expect"] == "complete_only" and s["value"].casefold() in hay}
    shown = drawn(d, c, REPORTS)
    hashes = {rgb_hash(c[i]) for i in shown}
    out.update({s["name"]: "pixel hash" for s in seeds if s["kind"] == "image" and s["value"] in hashes})
    private = next(s["value"] for s in seeds if s["name"] == "FILE-PDF-01")
    if any(e["sha256"] == private and e["page"] == f.IMAGE_PAGE for e in d["evidence"] if e["id"] in shown):
        out["IMG-MARKER-01"] = "marker colour"  # found reports a marker hit under the value-None seed only (7.1 G)
    return out


def test_the_scan_finds_exactly_what_the_complete_pages_print_and_nothing_in_the_sanitised(planted):
    d, c, folder, _ = planted["complete"]
    seeds = seeds_of(d, c)
    never = [s for s in seeds if s["expect"] == "never"]
    gc.collect()  # closes in-process SQLite connections: their -shm and -wal files settle before found lists them
    assert set(found(planted["ws"], [s for s in never if s["name"] in f.STORED_RAW])) == set(f.STORED_RAW)
    got, want = found(folder, seeds), expected_hits(d, c, seeds)
    assert set(got) == set(want), sorted(set(got) ^ set(want))
    for name, how in want.items():
        assert any(how == "text" or how in p for p in got[name]), (name, got[name])
    assert {"GCT-INJECT-01", "GCT-INJECT-02", "IMG-MARKER-01"} <= set(want)
    assert {"document_text", "contributor", "image"} <= {next(s["kind"] for s in seeds if s["name"] == n) for n in want}
    s, sc, sfolder, preview = planted["sanitised"]
    assert found(sfolder, seeds) == {}
    text = "\n".join(p.read_text(encoding="utf-8") for p in sfolder.glob("*.html"))
    assert preview["lines"] and not [x for x in preview["lines"] if x in text]  # no preview text


# AC 12: preservation and determinism

def test_write_changes_nothing_outside_its_folder_and_two_renders_are_identical(w, env, tmp_path):
    ws = Path(shutil.copytree(w, tmp_path / "ws"))

    def state():  # SQLite's -wal and -shm come and go with any reader's connection; dump compares the rows
        return {p.relative_to(ws).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in ws.rglob("*") if p.is_file() and not p.name.endswith(("-wal", "-shm"))}

    d, _ = build(ws, mode="complete")
    c = crops.cut(ws, d)
    before, rows = state(), dump(ws)
    got, out = [], tmp_path / "out"
    for n in (1, 2):
        folder = out / f"r{n}"
        folder.mkdir(parents=True)
        render_page.write(d, list(REPORTS), folder, c)
        got.append({p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()})
    assert got[0] == got[1] and state() == before and dump(ws) == rows
    assert sorted(p.name for p in out.iterdir()) == ["r1", "r2"]  # nothing beside the folders


# AC 13: the command

def test_gct_report_format_page_writes_the_pages_under_the_run(w, env, gct, tmp_path):
    ws = Path(shutil.copytree(w, tmp_path / "ws"))

    def state():
        return {p.relative_to(ws).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for top in ("files", "artifacts", "published") for p in (ws / top).rglob("*") if p.is_file()}

    before, rows = state(), dump(ws)
    r = gct("report", "evidence-index", "--format", "page", "--workspace", ws, "--json")
    assert r.code == 0, r.out
    check("report evidence-index", r.data)
    folder = Path(r.data["folder"])
    listed = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    assert r.data["files"] == r.data["outputs"][0]["files"] == listed and r.data["outputs"][0]["format"] == "page"
    assert FILES["evidence_index"] in listed and any(x.startswith("crops/E") for x in listed)
    d, _ = build(ws, mode="sanitised")
    check_folder(d, crops.cut(ws, d), folder, ["evidence_index"])
    first = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    assert state() == before
    after = dump(ws)
    assert {t for t in after if after[t] != rows[t]} == {"run", "run_event"}
    r = gct("report", "all", "--format", "page,json", "--workspace", ws, "--json", "--complete")
    assert r.code == 0 and {x["format"] for x in r.data["outputs"]} == {"page", "json"}
    names = {p.relative_to(r.data["folder"]).as_posix() for p in Path(r.data["folder"]).rglob("*") if p.is_file()}
    assert set(FILES.values()) | {"dataset.json", "dataset-1.schema.json"} <= names
    assert {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()} == first  # an earlier export is unchanged
    assert state() == before
