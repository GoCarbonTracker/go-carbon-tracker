"""Story 7.4: the PDF reports, on tests/report_fixture.py (7.1 section G). Every check opens the file write produced:
text with pdfplumber, images by their decoded pixels, fonts by name. read_back(path) and printed(value, row, key, fmt)
are the PDF format's part of the shared read-back contract (C4b, readiness resolution 3 as amended) that 7.7 calls
for every format."""
import copy
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

import report_fixture as f
from leakage import found
from test_gate_privacy_exports import build, env, w  # noqa: F401 (module fixtures: the fixture and its environment)
from test_review import WORDS
from test_sheet import HEADER, MAP, ROWS, csv_bytes, xlsx
from test_view import dump
from gct.reports import crops, dataset, export, render_pdf
from gct.stages import adjudicate
from gct.workspace import labels, layout, registry
from gct.workspace.layout import REFUSED, GctError

REPORTS = ("evidence_index", "restatement_log", "gap_report")
FILES = {r: f"{r.replace('_', '-')}.pdf" for r in REPORTS}
WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked on the page")
GUARD = re.compile(WORDS.pattern + "|contradiction", re.I)
TEXT_KINDS = {"document_text", "contributor", "credential", "path"}


def _cmaps():
    import reportlab
    from reportlab.pdfbase.ttfonts import TTFont

    folder = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    return {"Roman": TTFont("probe", os.path.join(folder, "Vera.ttf")).face.charToGlyph,
            "Bold": TTFont("probe-bold", os.path.join(folder, "VeraBd.ttf")).face.charToGlyph}


CMAPS = _cmaps()


def squeeze(s: str) -> str:
    return "".join(s.split())


# The read-back contract (C4b)

def printed(value, row, key, fmt):
    """How the PDF format prints a dataset value: render_pdf._shown, steps 0 and 1 of its text path, then white space
    removed (pdfplumber and long-word splitting break lines anywhere). fmt is "pdf" here and ignored."""
    return squeeze(render_pdf._plain(render_pdf._shown(value, row, key, dataset.words()), CMAPS["Roman"])[0])


def page_texts(path) -> list[str]:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return [p.extract_text() for p in pdf.pages]


def footer_line():
    w = dataset.words()
    fixed, sep = w["fixed"], re.escape(w["fixed"]["separator"])
    return re.compile(rf".*{sep}{re.escape(fixed['data_version'])} \d+{sep}[0-9a-f]{{12}}{sep}"
                      rf"{re.escape(fixed['pdf']['page'])} \d+ {re.escape(fixed['pdf']['of'])} \d+"
                      rf"({sep}{re.escape(w['privacy_notice'])})?$")


HANG = 36  # render_pdf's hanging indent: every line after a paragraph's first starts this far right of it
SLACK = HANG / 2  # above a sub-table's 12 pt indent step, far above pdfplumber's sub-point x jitter


def placed_lines(path) -> list[tuple[float, str]]:
    """(x0, text) of every extracted line, footers dropped."""
    import pdfplumber

    foot = footer_line()
    with pdfplumber.open(path) as pdf:
        return [(x["x0"], x["text"]) for p in pdf.pages for x in p.extract_text_lines() if not foot.fullmatch(x["text"])]


def lines_of(path) -> list[str]:
    """Every extracted line, footers dropped."""
    foot = footer_line()
    return [x for t in page_texts(path) for x in t.splitlines() if not foot.fullmatch(x)]


def read_back(path) -> dict:
    """{data_version: the identity keys the first page prints, rows: {table: [{columns key: value}]}} of one PDF:
    evidence_index, restatement_log (pair rows only) and gap_report.<section> for each section the file holds. A row
    starts at its row-key heading. Position decides, never text: a line indented by the hanging indent continues the
    value; any other line opening with one of its table's headings starts that key; a title, the appendix heading or
    the evidence-reference line ends it, and pair sides and sub-tables are not rows. Values are the printed strings
    with all white space removed."""
    w = dataset.words()
    fixed = w["fixed"]
    report = Path(path).stem.replace("-", "_")
    tables = {s: f"gap_report.{s}" for s in render_pdf.SECTIONS} if report == "gap_report" else {report: report}
    stops = set(fixed["titles"].values()) | {fixed["pdf"]["appendix"]}
    heads = {t: re.compile(re.escape(fixed["pdf"]["row"]).replace(r"\{title\}", re.escape(fixed["titles"][t]))
                           .replace(r"\{id\}", r"(\d+)")) for t in tables}
    identity = {v: k for k, v in fixed["identity"].items()}
    about = {*fixed["dataset"].values(), *identity}
    out = {"data_version": {}, "rows": {}}
    target, key, table, base = out["data_version"], None, None, None
    for x0, line in placed_lines(path):
        if base is not None and x0 > base + SLACK:  # indented: a value's next line, never a heading
            if target is not None and key is not None:
                target[key] += squeeze(line)
            continue
        base = x0
        hit = next((t for t, rx in heads.items() if rx.fullmatch(line)), None)
        if hit:
            table = hit
            row = {}
            out["rows"].setdefault(tables[hit], []).append(row)
            target, key = row, None
            continue
        if table is None and not out["data_version"] and line in stops:
            continue  # the report's title, first on the first page
        if line in stops or line.startswith(f"{fixed['pdf']['evidence']}:"):
            if line == fixed["pdf"]["appendix"]:
                break
            if line in stops:
                target = None
            key = None
            continue
        if target is None:
            continue
        labels_ = ({c["heading"]: c["key"] for c in dataset.COLUMNS[table]} if table else
                   {x: identity.get(x) for x in about})
        label = max((h for h in labels_ if line.startswith(f"{h}:")), key=len, default=None)
        key = labels_[label] if label is not None else None
        if key is not None:
            target[key] = squeeze(line[len(label) + 1:])
    return out


# The fixture's PDFs, one set per mode

@pytest.fixture(scope="module")
def made(w, env, tmp_path_factory):
    """{mode: (dataset, crops, folder)}: every report written once per mode, from the real builder and crops.cut."""
    out = {}
    for mode in dataset.MODES:
        d, _ = build(w, mode=mode)
        c = crops.cut(w, d)
        folder = tmp_path_factory.mktemp(mode)
        assert render_pdf.write(d, list(REPORTS), folder, c)["files"] == list(FILES.values())
        out[mode] = (d, c, folder)
    return out


def rgb_hash(png: bytes) -> str:
    from PIL import Image

    return hashlib.sha256(Image.open(io.BytesIO(png)).convert("RGB").tobytes()).hexdigest()


def placed(path) -> list[str]:
    """The decoded-pixel sha256 of every image drawn, page by page, one per placement."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return [hashlib.sha256(i["stream"].get_data()).hexdigest() for p in pdf.pages for i in p.images]


def dotted(row, key):
    return render_pdf._dotted(row, key)


def printed_rows(d, report):
    """(table, row, printed) for every row a PDF prints, written out here: the report's own rows and their nested
    sub-tables, pair sides, unpaired restatements (restatement log) and documents (every PDF)."""
    sides = {r["claim_id"]: r for r in d["evidence_index"] + d["related_claims"]}
    out = []

    def walk(table, rows):
        for r in rows:
            out.append((table, r))
            if table in ("restatement_log", "candidates"):
                out.extend(("evidence_index", sides[r[k]]) for k in ("claim_a", "claim_b") if r[k] in sides)
            for k, v in r.items():
                if isinstance(v, dict) and "rows" in v:
                    walk(k, v["rows"])

    if report == "gap_report":
        for s in render_pdf.SECTIONS:
            walk(s, d["gap_report"][s])
    else:
        walk(report, d[report])
    if report == "restatement_log":
        walk("unpaired_restatements", d["unpaired_restatements"]["rows"])
    walk("documents", d["documents"])
    return out


def cited(d, report) -> set:
    return {i for _, r in printed_rows(d, report) for i in r["evidence"]}


def block(d, table, row) -> str:
    """A row's printed lines, white space removed."""
    return "".join(f"{squeeze(c['heading'])}:{printed(dotted(row, c['key']), row, c['key'], 'pdf')}"
                   for c in d["columns"][table])


def appendix(path) -> dict:
    """{evidence id: the entry's lines} of a PDF's appendix."""
    fixed = dataset.words()["fixed"]
    lines = lines_of(path)
    if fixed["pdf"]["appendix"] not in lines:
        return {}
    out, cur = {}, None
    for line in lines[lines.index(fixed["pdf"]["appendix"]) + 1:]:
        if m := re.fullmatch(r"E(\d+)", line):
            cur = out.setdefault(int(m[1]), [])
        elif cur is not None:
            cur.append(line)
    return out


# AC 12: the scan decodes this renderer's images (the first test)

def test_found_recovers_a_planted_crop(w, env, tmp_path):
    from PIL import Image

    d, _ = build(w, mode="sanitised")  # no marker colour on any page, so only the pixel hash can find the seed
    c = crops.cut(w, d)
    target = min(i for r in d["evidence_index"] for i in r["evidence"] if i in c)
    planted = Image.effect_noise((60, 40), 80).convert("RGB")
    data = io.BytesIO()
    planted.save(data, "PNG")
    c[target] = data.getvalue()
    render_pdf.write(d, ["evidence_index"], tmp_path, c)
    seed = {"name": "crop-E0001", "kind": "image", "expect": "complete_only", "value": rgb_hash(c[target])}
    other = {**seed, "name": "crop-E0002", "value": "0" * 64}
    result = found(tmp_path / "evidence-index.pdf", [seed, other])
    assert set(result) == {"crop-E0001"} and all("pixel hash" in p for p in result["crop-E0001"])


# AC 5: the reports and read_back

@pytest.mark.parametrize("mode", dataset.MODES)
def test_every_row_is_printed_and_read_back(made, mode):
    d, c, folder = made[mode]
    assert sorted(p.name for p in folder.iterdir()) == sorted(FILES.values())
    w = d["words"]
    kinds = set()
    for report in REPORTS:
        path = folder / FILES[report]
        back = read_back(path)
        assert back["data_version"] == {k: printed(v, None, k, "pdf") for k, v in d["data_version"].items()}
        mains = {s: d["gap_report"][s] for s in render_pdf.SECTIONS} if report == "gap_report" else {report: d[report]}
        want = {(f"gap_report.{t}" if report == "gap_report" else t): [
            {c_["key"]: printed(dotted(r, c_["key"]), r, c_["key"], "pdf") for c_ in d["columns"][t]} for r in rows]
            for t, rows in mains.items() if rows}
        assert back["rows"] == want, report
        text = squeeze("".join(lines_of(path)))
        for table, row in printed_rows(d, report):  # sub-tables, sides, unpaired restatements and documents too
            assert block(d, table, row) in text, (report, table, row["id"])
            for c_ in d["columns"][table]:
                v = dotted(row, c_["key"])
                kinds.add("withheld" if c_["key"] in row["withheld"] else "null" if v is None else
                          "bool" if isinstance(v, bool) else "number" if isinstance(v, (int, float)) else
                          "list" if isinstance(v, list) and v else "")
        foot = footer_line()
        pages = page_texts(path)
        for n, t in enumerate(pages, 1):
            last = t.splitlines()[-1]
            assert foot.fullmatch(last) and last.endswith(
                f"{w['fixed']['pdf']['page']} {n} {w['fixed']['pdf']['of']} {len(pages)}"
                + (f"{w['fixed']['separator']}{w['privacy_notice']}" if mode == "sanitised" else "")), (report, n)
            assert last.startswith(w["fixed"]["titles"][report]) and d["data_version"]["sha256"][:12] in last
        # the appendix holds exactly the evidence this PDF's rows cite, each naming its document, version and page
        entries = appendix(path)
        assert set(entries) == cited(d, report), report
        for i, lines in entries.items():
            e = next(x for x in d["evidence"] if x["id"] == i)
            doc = next(x for x in d["documents"] if x["id"] == e["document_id"])
            h = w["fixed"]["headings"]
            assert f"{h['document_name']}: {doc['name']}" in lines and f"{h['document_version']}: {doc['version']}" in lines
            assert (f"{h['page']}: {e['page']}" in lines if e["page"] is not None else
                    f"{h['sheet']}: {e['sheet']}" in lines and f"{h['cell']}: {e['cell']}" in lines)
    assert {"null", "bool", "number", "list"} <= kinds and ("withheld" in kinds) == (mode == "sanitised")


def test_a_multi_line_value_and_a_two_item_list_read_back(made, tmp_path):
    """The fixture holds no multi-line value and no list of two items."""
    d = copy.deepcopy(made["complete"][0])
    row = d["evidence_index"][0]
    row["metric_text"], row["needs_renewed_review"] = "line one\nline two", ["first entry", "second entry"]
    render_pdf.write(d, ["evidence_index"], tmp_path, made["complete"][1])
    back = read_back(tmp_path / "evidence-index.pdf")["rows"]["evidence_index"][0]
    assert back["metric_text"] == "lineonelinetwo" == printed(row["metric_text"], row, "metric_text", "pdf")
    assert back["needs_renewed_review"] == "firstentry;secondentry"


def test_the_gap_report_prints_its_six_parts_in_order(made):
    d, _, folder = made["complete"]
    titles = d["words"]["fixed"]["titles"]
    lines = lines_of(folder / FILES["gap_report"])
    at = [lines.index(titles[s]) for s in render_pdf.SECTIONS]
    assert at == sorted(at)
    checked = {next(x for x in d["documents"] if x["id"] == r["document_id"])["file_type"]
               for r in d["gap_report"]["documents_checked"]}
    assert {"pdf", "csv"} <= checked
    assert any(r["reason"] == "charts not read" for r in d["gap_report"]["extraction_limits"])
    assert all(d["gap_report"][s] for s in render_pdf.SECTIONS)  # every part holds a row in the complete fixture


def test_a_side_outside_the_selection_is_marked(w, env, tmp_path):
    d, _ = build(w, mode="complete", filter={"document": [2]})
    assert d["related_claims"]
    render_pdf.write(d, ["restatement_log"], tmp_path, crops.cut(w, d))
    lines = lines_of(tmp_path / FILES["restatement_log"])
    h, outside = d["words"]["fixed"]["headings"], d["words"]["outside_selection"]
    marked = [lines[i - 1] for i, x in enumerate(lines) if x == outside]
    want = [h[k] for p in d["restatement_log"] for k, o in zip(("claim_a", "claim_b"), p["outside_selection"]) if o]
    assert want and marked == want
    text = squeeze("".join(lines))
    for r in d["related_claims"]:
        assert block(d, "evidence_index", r) in text


def test_every_table_is_in_some_report(made):
    """B7: every columns table except related_claims (pair sides use the evidence index columns) is printed by some
    report, from the report's own nesting; documents and unpaired restatements are named."""
    d, _, folder = made["complete"]
    seen = {t for r in REPORTS for t, _ in printed_rows(d, r)}
    accepted = {"id": 1, "data_version": d["data_version"]["version"], "label": "private", "documents": [],
                "evidence": [], "withheld": [], "expected_item_id": 1, "type": "figures", "acceptance_id": 1,
                "count": 1}
    d2 = copy.deepcopy(d)
    d2["gap_report"]["expectations"][0]["accepted"]["rows"].append(accepted)  # the fixture has none
    seen |= {t for t, _ in printed_rows(d2, "gap_report")}
    assert set(d["columns"]) - seen == {"related_claims"}
    plans = {t for r in REPORTS for k, _, t, *_ in render_pdf._plan(d2, r) if k == "title"}
    assert set(d["columns"]) - plans == {"related_claims"} and "pair_sides" in plans


# AC 6: one data version

@pytest.mark.parametrize("mode", dataset.MODES)
def test_the_first_page_shows_the_modes_identity_and_the_dataset_keys(made, mode):
    d, _, folder = made[mode]
    fixed = d["words"]["fixed"]
    first = page_texts(folder / FILES["evidence_index"])[0].splitlines()
    assert set(d["data_version"]) == ({"version", "built_at", "sha256", "projection_schema"} |
                                      ({"history_mark", "labels_mark"} if mode == "complete" else set()))
    for k, v in d["data_version"].items():
        assert f"{fixed['identity'][k]}: {v}" in first
    assert f"{fixed['dataset']['gct_version']}: {d['gct_version']}" in first
    assert f"{fixed['dataset']['built_at']}: {d['built_at']}" in first
    assert f"{fixed['dataset']['dataset_schema']}: {d['dataset_schema']}" in first
    assert f"{fixed['dataset']['include']}:" in first and f"{fixed['dataset']['filter']}:" in first
    assert fixed["mode"][mode] in first and all(n in first for n in d["notices"])
    if mode == "sanitised":
        assert [x for t in page_texts(folder / FILES["evidence_index"]) for x in t.splitlines()].count(
            d["words"]["privacy_notice"]) == 1  # in notices; the footers carry it after the separator


def test_the_filter_echo_prints_one_field_per_line(w, env, tmp_path):
    flt = {"document": [2, 11], "text": "Scope", "period": {"from": "2024-04-01"}}
    for mode in dataset.MODES:
        d, _ = build(w, mode=mode, filter=flt)
        folder = tmp_path / mode
        folder.mkdir()
        render_pdf.write(d, ["evidence_index"], folder, crops.cut(w, d))
        first = page_texts(folder / FILES["evidence_index"])[0].splitlines()
        sep = d["words"]["fixed"]["separator"]
        assert f"document: {sep.join(map(str, d['filter']['document']))}" in first
        assert "period.from: 2024-04-01" in first
        assert ("text: Scope" if mode == "complete" else f"text: {d['words']['withheld']}") in first


# AC 3 and 6: the refusals

def test_each_refusal_comes_before_any_file(made, tmp_path, gct, monkeypatch):
    d, c, _ = made["complete"]
    again = "Run the report again. If this message repeats, report it as a fault in GCT."
    pages = sorted(e["id"] for e in d["evidence"] if e["page"] is not None)
    other = copy.deepcopy(d)
    row = sorted(other["gap_report"]["documents_checked"], key=lambda r: r["id"])[2]
    row["data_version"] = 1
    cases = [
        (d, {**c, 999: b"png"}, "A page image was made for evidence E999, which this report's data does not hold.", again),
        (d, {k: v for k, v in c.items() if k != pages[3]}, f"No page image was made for evidence E{pages[3]}.", again),
        (other, c, f"Row {row['id']} of Gap report comes from data version 1, but this report is for data version"
                   f" {d['data_version']['version']}.", "Run the report again so every row comes from one data version.")]
    for data, cut, cause, step in cases:
        folder = tmp_path / "f"
        folder.mkdir()
        with pytest.raises(render_pdf.Refusal) as e:
            render_pdf.write(data, list(REPORTS), folder, cut)
        assert (e.value.cause, e.value.next_step) == (cause, step) and list(folder.iterdir()) == []
        folder.rmdir()
        monkeypatch.setattr(crops, "cut", lambda root, dataset_, cut=cut: cut)
        root = tmp_path / "root"
        root.mkdir(exist_ok=True)
        with pytest.raises(GctError) as e:
            export.write(root, data, list(REPORTS), ["pdf"], "all")
        assert (e.value.code, e.value.cause, e.value.next_action) == (REFUSED, cause, step)
        assert list((root / "exports").iterdir()) == []


# AC 3, 10: the image cap

def test_two_page_entries_and_no_crops_is_the_cap_path(made, tmp_path):
    d = copy.deepcopy(made["complete"][0])
    pages = [e for e in d["evidence"] if e["page"] is not None][:2]
    d["evidence"] = pages
    d["evidence_index"] = d["evidence_index"][:1]
    d["evidence_index"][0]["evidence"] = [e["id"] for e in pages]
    for k in ("restatement_log", "related_claims"):
        d[k] = []
    render_pdf.write(d, ["evidence_index"], tmp_path, {})
    path = tmp_path / FILES["evidence_index"]
    assert placed(path) == [] and set(appendix(path)) == {e["id"] for e in pages}
    assert squeeze(" ".join(lines_of(path))).count(squeeze(d["words"]["fixed"]["image_limit"])) == 1


def test_above_the_cap_every_location_is_text_and_narrowing_gives_images(made, w, tmp_path):
    d = copy.deepcopy(made["complete"][0])
    first = next(e for e in d["evidence"] if e["page"] is not None and e["boxes"])
    d["evidence"] = [{**first, "id": n} for n in range(1, crops.LIMIT + 2)]
    d["evidence_index"] = d["evidence_index"][:1]
    d["evidence_index"][0]["evidence"] = [e["id"] for e in d["evidence"]]
    for k in ("restatement_log", "related_claims"):
        d[k] = []
    c = crops.cut(w, d)
    assert c == {}
    render_pdf.write(d, ["evidence_index"], tmp_path, c)
    path = tmp_path / FILES["evidence_index"]
    assert placed(path) == [] and len(appendix(path)) == crops.LIMIT + 1
    assert squeeze(" ".join(lines_of(path))).count(squeeze(d["words"]["fixed"]["image_limit"])) == 1
    d["evidence"] = d["evidence"][:crops.LIMIT]
    d["evidence_index"][0]["evidence"] = d["evidence_index"][0]["evidence"][:crops.LIMIT]
    narrow = tmp_path / "narrow"
    narrow.mkdir()
    render_pdf.write(d, ["evidence_index"], narrow, crops.cut(w, d))
    assert len(placed(narrow / FILES["evidence_index"])) == crops.LIMIT


# AC 4: spreadsheet evidence

def test_xlsx_and_csv_claims_print_the_transposed_cell_view(ws, gct, make_file, tmp_path):
    import pdfplumber

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    sheet = [ROWS[0], ROWS[1]]
    for name, data, tab in (("b.xlsx", xlsx({"Energy": sheet}), "Energy"), ("m.csv", csv_bytes(sheet), "m")):
        gct("doc", "add", make_file(name, data), "--company", "Acme")
        doc = gct("doc", "list", "--json").data["documents"][-1]["id"]
        assert gct("sheet", "map", doc, "--sheet", tab, *MAP, *WHO).code == 0
    gct("extract")
    gct("publish", "build")
    conn = sqlite3.connect(ws / layout.DB_NAME)
    conn.row_factory = sqlite3.Row
    d, _ = dataset.build(conn, ws, mode="complete")
    conn.close()
    cells = [e for e in d["evidence"] if e["cell"] is not None]
    assert {next(x for x in d["documents"] if x["id"] == e["document_id"])["file_type"] for e in cells} == {"xlsx", "csv"}
    c = crops.cut(ws, d)
    assert c == {}
    render_pdf.write(d, ["evidence_index"], tmp_path, c)
    path = tmp_path / FILES["evidence_index"]
    entries = appendix(path)
    assert placed(path) == []
    with pdfplumber.open(path) as pdf:
        chars = [ch for p in pdf.pages for ch in p.chars]
    bold = "".join(ch["text"] for ch in chars if ch["fontname"].endswith("Bold"))
    for e in cells:
        lines = entries[e["id"]]
        for k, (h, v) in enumerate(zip(e["header"], e["row"])):
            assert any(squeeze(x) == squeeze(f"{h} {v}") for x in lines), (e["id"], h, v)
        assert squeeze(e["header"][e["marked"]] + e["row"][e["marked"]]) in squeeze(bold)
    assert squeeze(ROWS[0][0]) not in squeeze(bold)  # only the marked line is bold


# F1 (review of 7024271): no value opens a line a reader takes for a heading

def hanging(path, opening, follow) -> list[float]:
    """For each line that is exactly opening, the x0 step to the line after it, which must be follow."""
    at = placed_lines(path)
    ks = [k for k, (_, t) in enumerate(at) if t == opening]
    assert ks and all(at[k + 1][1] == follow for k in ks), [at[k:k + 2] for k in ks]
    return [at[k + 1][0] - at[k][0] for k in ks]


def margin_companies(path) -> list[int]:
    """Per evidence-index row block, how many lines start "Company:" at the block's own margin."""
    w = dataset.words()["fixed"]
    head = re.compile(re.escape(w["pdf"]["row"]).replace(r"\{title\}", re.escape(w["titles"]["evidence_index"]))
                      .replace(r"\{id\}", r"\d+"))
    stops = set(w["titles"].values()) | {w["pdf"]["appendix"]}
    out, base = [], None
    for x0, t in placed_lines(path):
        if head.fullmatch(t):
            out.append(0)
            base = x0
        elif t in stops:
            base = None
        elif base is not None and abs(x0 - base) < SLACK and t.startswith("Company:"):
            out[-1] += 1
    return out


def test_a_csv_value_and_a_document_name_with_a_heading_line_stay_in_their_values(ws, gct, make_file, tmp_path):
    import csv

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    data = io.StringIO()
    csv.writer(data, lineterminator="\n").writerows(
        [HEADER, ["Scope 1 emissions\nCompany: ForgedCo", "125", "tCO2e", "FY 2023-24", "Standalone", "Acme", ""]])
    name = "data\nCompany: SpoofCo"
    gct("doc", "add", make_file("m.csv", data.getvalue().encode()), "--company", "Acme", "--name", name)
    doc = gct("doc", "list", "--json").data["documents"][-1]["id"]
    assert gct("sheet", "map", doc, "--sheet", name, *MAP, *WHO).code == 0  # a CSV's one sheet is named as it is
    gct("extract")
    gct("publish", "build")
    conn = sqlite3.connect(ws / layout.DB_NAME)
    conn.row_factory = sqlite3.Row
    d, _ = dataset.build(conn, ws, mode="complete")
    conn.close()
    [row] = d["evidence_index"]
    assert (row["metric_text"], row["document_name"]) == ("Scope 1 emissions\nCompany: ForgedCo",
                                                          "data\nCompany: SpoofCo")
    render_pdf.write(d, ["evidence_index"], tmp_path, crops.cut(ws, d))
    path = tmp_path / FILES["evidence_index"]
    [back] = read_back(path)["rows"]["evidence_index"]
    assert (back["company"], back["metric_text"], back["document_name"]) == (
        "Acme", "Scope1emissionsCompany:ForgedCo", "dataCompany:SpoofCo")
    assert back == {c["key"]: printed(dotted(row, c["key"]), row, c["key"], "pdf") for c in d["columns"]["evidence_index"]}
    assert margin_companies(path) == [1]
    assert hanging(path, "Metric as printed: Scope 1 emissions", "Company: ForgedCo") == [pytest.approx(HANG, abs=1)]
    assert hanging(path, "Document name: data", "Company: SpoofCo") == [pytest.approx(HANG, abs=1)] * 2  # row, appendix
    assert hanging(path, "Name: data", "Company: SpoofCo") == [pytest.approx(HANG, abs=1)]  # the documents block


def test_a_wrapped_line_that_starts_with_a_heading_stays_in_its_value(made, tmp_path):
    from reportlab.pdfbase.pdfmetrics import stringWidth

    d0, c, _ = made["complete"]
    opening = "Metric as printed: "
    width = lambda s: stringWidth(s, render_pdf.BODY, render_pdf.SIZE)  # noqa: E731
    filler = "a" * int((480 - width(opening)) / width("a"))  # fits the first line; " Company:" after it does not
    value = f"{filler} Company: Wrapped"
    d = special(d0, [value])
    row = min(d["evidence_index"], key=lambda r: r["id"])
    render_pdf.write(d, ["evidence_index"], tmp_path, c)
    path = tmp_path / FILES["evidence_index"]
    assert hanging(path, opening + filler, "Company: Wrapped") == [pytest.approx(HANG, abs=1)]
    [back] = [b for b in read_back(path)["rows"]["evidence_index"] if b["metric_text"] == squeeze(value)]
    assert back["company"] == squeeze(row["company"]) != "Wrapped"
    assert margin_companies(path) == [1] * len(d["evidence_index"])


# AC 7: labels and wording

@pytest.mark.parametrize("mode", dataset.MODES)
def test_printed_words_only_and_the_wording_guard(made, mode, tmp_path):
    d, c, folder = made[mode]
    gone = labels.CONTRIBUTOR_TEXT | labels.DOCUMENT_TEXT

    def stripped(d_, report, path):
        text = squeeze(" ".join(lines_of(path)))
        values = sorted({printed(dotted(r, k), r, k, "pdf") for t, r in printed_rows(d_, report)
                         for k in (x["key"] for x in d_["columns"][t]) if k in gone or k.split(".")[0] in gone}
                        | {squeeze(x) for e in d_["evidence"] for x in (e["header"] or []) + (e["row"] or [])},
                        key=len, reverse=True)
        for v in values:
            text = text.replace(v, "") if v else text
        return text

    for report in REPORTS:
        text = stripped(d, report, folder / FILES[report])
        assert not GUARD.search(text), (report, GUARD.search(text))
        for code in adjudicate.STATES:
            assert code not in text, code
    planted = copy.deepcopy(d)
    row = next(r for r in planted["evidence_index"] if r["records"]["rows"])
    row["records"]["rows"][0]["scope"] = "verified by hand"
    row["records"]["rows"][0]["withheld"] = []
    render_pdf.write(planted, ["evidence_index"], tmp_path, c)
    path = tmp_path / FILES["evidence_index"]
    assert GUARD.search(squeeze(" ".join(lines_of(path)))) and not GUARD.search(stripped(planted, "evidence_index", path))


@pytest.mark.parametrize("mode", ["complete"])
def test_the_self_declared_line_once_on_the_first_page_and_under_each_attributed_title(made, mode):
    """B9: complete mode, since a sanitised dataset withholds correction.contributor."""
    d, _, folder = made[mode]
    line = d["words"]["self_declared"]
    for report in REPORTS:
        path = folder / FILES[report]
        plan = render_pdf._plan(d, report)
        captions = [t for k, _, t, *rest in plan if k == "title" and render_pdf._attributed(
            rest[0], d["columns"]["evidence_index" if t == "pair_sides" else t])]
        assert captions, report
        texts = page_texts(path)
        assert line in texts[0].split(d["words"]["fixed"]["mode"][mode], 1)[1]
        assert sum(t.count(line) for t in texts) == 1 + len(captions)


# AC 8: text safety

SPECIAL = ['<img src="file:///etc/hosts"/>', "＜img src=\"/etc/hosts\"/＞", "＆amp;", "<b>x", "a & b", "x < y",
           "T" * 2000, "".join(map(chr, range(32))), "CO₂", "₹ 1,234", "שלום עולם", "line one\nline two", "a\tb",
           "a\r\nb", "é"]


def special(d, strings):
    """A copy of d whose first evidence-index rows carry strings as metric_text, one each."""
    d = copy.deepcopy(d)
    rows = sorted(d["evidence_index"], key=lambda r: r["id"])
    for r, s in zip(rows, strings):
        r["metric_text"] = s
    return d


def test_text_is_replaced_then_escaped_and_never_read_as_markup(made, tmp_path):
    import pdfplumber

    d0, c, _ = made["complete"]
    d = special(d0, SPECIAL)
    note = d["words"]["fixed"]["pdf"]["font_note"]
    out = render_pdf.write(d, ["evidence_index"], tmp_path, c)
    path = tmp_path / FILES["evidence_index"]
    lines = lines_of(path)
    text = squeeze(" ".join(lines))
    for s in ('<img src="file:///etc/hosts"/>', '<img src="/etc/hosts"/>', "&amp;", "<b>x", "a&b", "x<y", "T" * 2000):
        assert squeeze(s) in text, s
    for s in ("CO2", "[U+20B9] 1,234", "é"):
        assert f"Metric as printed: {s}" in lines, s
    assert "Metric as printed: line one" in lines and lines[lines.index("Metric as printed: line one") + 1] == "line two"
    assert "Metric as printed: a b" in lines
    assert "Metric as printed: a" in lines and lines[lines.index("Metric as printed: a") + 1] == "b"
    for bad in ("[U+000A]", "[U+0009]", "[U+000D]", "[U+0301]", "₂", "₹"):
        assert bad not in text, bad
    assert "[U+0000]" in text and "[U+05E9]" in text
    assert text.count(squeeze(note)) == 1
    assert len(placed(path)) == len(placed(made["complete"][2] / FILES["evidence_index"]))
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            for ch in p.chars:
                cmap = CMAPS["Bold" if ch["fontname"].endswith("Bold") else "Roman"]
                assert ch["fontname"].split("+")[1].startswith("BitstreamVeraSans")
                assert all(ord(x) in cmap for x in ch["text"]), ch["text"]
    n = int(out["notes"][0].split(": ", 1)[1].split()[0])
    assert n > 0 and out["notes"] == [out["notes"][0]] and out["notes"][0].startswith("evidence-index.pdf: ")
    plain = tmp_path / "plain"
    plain.mkdir()
    out = render_pdf.write(special(d0, ["line one\nline two", "a\tb", "a\r\nb", "é"]), ["evidence_index"],
                           plain, c)
    assert squeeze(note) not in squeeze(" ".join(lines_of(plain / FILES["evidence_index"])))
    assert out["notes"][0].startswith("evidence-index.pdf: 0 ")


# AC 9: determinism

def test_two_renders_are_byte_identical_and_the_info_says_nothing_of_the_workspace(made, tmp_path, monkeypatch):
    import getpass

    import pdfplumber
    from reportlab import rl_config
    from reportlab.pdfbase import pdfmetrics

    d, c, _ = made["complete"]
    invariant = rl_config.invariant
    for epoch in (None, "1700000000"):
        if epoch is None:
            monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
        else:
            monkeypatch.setenv("SOURCE_DATE_EPOCH", epoch)
        got = []
        for n in (1, 2):
            folder = tmp_path / f"{epoch}-{n}"
            folder.mkdir()
            render_pdf.write(d, list(REPORTS), folder, c)
            got.append({p.name: p.read_bytes() for p in folder.iterdir()})
        assert got[0] == got[1], epoch
    assert rl_config.invariant == invariant
    assert not [n for n in pdfmetrics.getRegisteredFontNames() if n.startswith("DarkGarden")]
    with pdfplumber.open(tmp_path / "None-1" / FILES["evidence_index"]) as pdf:
        info = pdf.metadata
    assert {k: info[k] for k in ("Title", "Author", "Creator", "Subject")} == {
        "Title": "Evidence index", "Author": "GCT", "Creator": "GCT", "Subject": d["gct_version"]}
    assert info["CreationDate"].startswith("D:20000101000000")
    blob = json.dumps(info, default=str)
    for bad in (getpass.getuser(), str(tmp_path), "/Users/", "/home/", f.NAME, "Acme"):
        assert bad not in blob, bad


# AC 10: behaviour

def test_archived_and_deleted_documents_have_no_entry_and_their_parts_print(made):
    d, _, folder = made["complete"]
    gone = {r["document_id"] for r in d["gap_report"]["archived"] + d["gap_report"]["deleted"]}
    assert gone and not [e for e in d["evidence"] if e["document_id"] in gone]
    text = " ".join(lines_of(folder / FILES["gap_report"]))
    for r in d["gap_report"]["archived"]:
        assert r["name"] in text
    review = next(r for x in d["evidence_index"] for r in x["records"]["rows"] if r["evidence_state"] == "archived")
    assert block(d, "records", review) in squeeze(" ".join(lines_of(folder / FILES["evidence_index"])))
    s, _, sfolder = made["sanitised"]
    assert s["gap_report"]["archived"] == s["gap_report"]["deleted"] == []
    for report in REPORTS:
        assert s["words"]["archive_notice"] in page_texts(sfolder / FILES[report])[0]


def test_missing_states_and_non_binding_records_show_no_image(made):
    d, c, folder = made["complete"]
    text = " ".join(lines_of(folder / FILES["gap_report"]))
    for r in d["gap_report"]["expectations"]:
        assert r["state"] in text
    h = d["words"]["fixed"]["headings"]
    for report in REPORTS:
        path = folder / FILES[report]
        entries = appendix(path)
        must = drawn_ids(d, c, report)
        drawn = []
        for i in entries:
            e = next(x for x in d["evidence"] if x["id"] == i)
            image = i in must
            alts = [x for x in entries[i] if x.startswith(("Evidence for claim", "Evidence E"))]
            assert bool(alts) == image, (report, i)
            if image:
                drawn.append(rgb_hash(c[i]))
            elif e["page"] is not None:  # R5.5: the location as text
                assert f"{h['page']}: {e['page']}" in entries[i]
        assert placed(path) == drawn, report
    nonbinding = [r for _, r in printed_rows(d, "restatement_log") if r.get("binds") is False and r["evidence"]]
    assert nonbinding  # the fixture's earlier-version restatement and adjudication


def test_a_no_box_ref_is_a_whole_page_entry_and_every_page_entry_is_the_viewer_render(made, w):
    d, c, _ = made["complete"]
    from gct.evidence.pages import _render

    for e in d["evidence"]:
        if e["page"] is not None and e["boxes"] is None:
            assert c[e["id"]] == _render(registry.stored_path(w, e["sha256"]), e["page"], 1.5)
    assert {e["kind"] for e in d["evidence"] if e["page"] is not None and e["boxes"] is None} >= {
        "basis", "review", "restatement"}


def test_every_document_private_renders_only_the_first_page_text(w, env, gct, tmp_path):
    ws = Path(shutil.copytree(w, tmp_path / "ws"))
    for x in gct("doc", "list", "--workspace", ws, "--json").data["documents"]:
        if x["state"] != "deleted" and x["privacy"] == "shareable":
            assert gct("doc", "label", x["id"], "--privacy", "private", *WHO, "--workspace", ws).code == 0
    assert gct("publish", "build", "--workspace", ws).code == 0
    d, _ = build(ws, mode="sanitised")
    assert d["evidence"] == [] and d["documents"] == []
    render_pdf.write(d, list(REPORTS), tmp_path, crops.cut(ws, d))
    names = [x["logical_name"] for x in gct("doc", "list", "--workspace", ws, "--json").data["documents"]]
    for report in REPORTS:
        path = tmp_path / FILES[report]
        text = " ".join(lines_of(path))
        assert placed(path) == [] and not appendix(path) and read_back(path)["rows"] == {}
        assert all(n in text for n in d["notices"]) and d["words"]["privacy_notice"] in text
        assert not [n for n in names if n and n in text]


# AC 11: privacy in the PDF

def drawn_ids(d, c, report) -> list[int]:
    """The evidence ids whose crop a PDF must draw, from the dataset: the page entries its rows cite with at least one
    binding citing row (R5.5), unless the crops map is empty (the cap)."""
    rows = [r for _, r in printed_rows(d, report)]
    return [e["id"] for e in d["evidence"] if e["id"] in cited(d, report) and e["page"] is not None and c
            and any(r.get("binds") is not False for r in rows if e["id"] in r["evidence"])]


def expected_hits(d, c, report, seeds):
    """{seed name: how} the scan must report for one complete PDF, from what it prints and the crops it must draw."""
    w = d["words"]
    strings = [printed(dotted(r, k["key"]), r, k["key"], "pdf") for t, r in printed_rows(d, report)
               for k in d["columns"][t]]
    for e in (x for x in d["evidence"] if x["id"] in cited(d, report)):
        doc = next(x for x in d["documents"] if x["id"] == e["document_id"])
        strings += [squeeze(str(doc["name"])), *(squeeze(x) for x in (e["header"] or []) + (e["row"] or []))]
    strings += [squeeze(x) for x in d["notices"]] + [squeeze(str(v)) for v in d["data_version"].values()]
    strings += [squeeze(w["fixed"]["image_alt"])]
    hay = "\n".join(strings).casefold()
    out = {s["name"]: "text" for s in seeds if s["kind"] in TEXT_KINDS and s["expect"] == "complete_only"
           and s["value"].casefold() in hay}
    embeds = drawn_ids(d, c, report)
    drawn = {rgb_hash(c[i]) for i in embeds}
    out.update({s["name"]: "pixel hash" for s in seeds if s["kind"] == "image" and s["value"] in drawn})
    private = next(s["value"] for s in seeds if s["name"] == "FILE-PDF-01")
    if any(e["sha256"] == private and e["page"] == f.IMAGE_PAGE for e in d["evidence"] if e["id"] in embeds):
        out.update({s["name"]: "marker colour" for s in seeds if s["kind"] == "image"})  # leakage._match reports
        # every image seed on a marker hit, IMG-MARKER-01 (value None) among them
    return out


def test_the_scan_finds_exactly_what_each_complete_pdf_prints_and_nothing_in_a_sanitised_one(made):
    d, c, folder = made["complete"]
    private = {x["id"] for x in d["documents"] if x["label"] == "private"}
    seeds = copy.deepcopy(f.SEEDS)
    for e in d["evidence"]:  # one image seed per private page entry; equal pixels (IMG-PAGE-01 too) keep the first
        if e["page"] is not None and e["document_id"] in private and rgb_hash(c[e["id"]]) not in {
                s["value"] for s in seeds}:
            seeds.append({"name": f"crop-E{e['id']:04d}", "kind": "image", "expect": "complete_only",
                          "value": rgb_hash(c[e["id"]])})
    seen = {}
    for report in REPORTS:
        path = folder / FILES[report]
        got = found(path, seeds)
        want = expected_hits(d, c, report, seeds)
        assert set(got) == set(want), (report, sorted(set(got) ^ set(want)))
        for name, how in want.items():
            assert any(how == "text" or how in p for p in got[name]), (report, name, got[name])
        assert not [s for s in got if next(x for x in seeds if x["name"] == s)["expect"] == "never"]
        seen.update({n: next(x for x in seeds if x["name"] == n)["kind"] for n in got})
    assert {"document_text", "contributor", "image"} <= set(seen.values())
    s, sc, sfolder = made["sanitised"]
    for report in REPORTS:
        path = sfolder / FILES[report]
        assert found(path, seeds) == {}, report
        allowed = {rgb_hash(sc[i]) for i in cited(s, report) if i in sc}
        assert set(placed(path)) <= allowed, report  # the closed list: only crops this PDF's rows cite


# AC 1, 3, 5, 15: the command

def test_gct_report_writes_one_pdf_per_report_and_changes_nothing_else(w, env, gct, tmp_path):
    ws = Path(shutil.copytree(w, tmp_path / "ws"))

    def state():
        return {p.relative_to(ws).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for top in ("files", "artifacts", "published") for p in (ws / top).rglob("*") if p.is_file()}

    before, rows = state(), dump(ws)
    r = gct("report", "all", "--format", "pdf", "--workspace", ws, "--json")
    assert r.code == 0, r.out
    folder = Path(r.data["folder"])
    assert sorted(p.name for p in folder.iterdir()) == sorted(FILES.values())
    assert r.data["outputs"][0]["format"] == "pdf" and r.data["outputs"][0]["files"] == list(FILES.values())
    assert len(r.data["outputs"][0]["notes"]) == 3
    assert state() == before
    after = dump(ws)
    assert {t for t in after if after[t] != rows[t]} == {"run", "run_event"}
    r = gct("report", "gap-report", "--format", "pdf,json", "--workspace", ws, "--json")
    assert r.code == 0 and sorted(p.name for p in Path(r.data["folder"]).iterdir()) == [
        "dataset-1.schema.json", "dataset.json", "gap-report.pdf"]
    assert state() == before
