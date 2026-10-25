import gc
import hashlib
import json
import math
import re
import subprocess

import pytest

from conftest import make_pdf, grid
from test_json import check
from gct.measure import g2

WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "read on the page")
FY_LINES = ["The Annual Report covers the Financial Year (`FY') ended", "March 31, 2024 for the Company."]
FY = {"kind": "fiscal_year", "start": "2023-04-01", "end": "2024-03-31", "label": "FY24"}
CY = {"kind": "calendar_year", "start": "2024-01-01", "end": "2024-12-31", "label": "2024"}


def text_page(lines):
    return {"text": [(40, 80 + 20 * i, s) for i, s in enumerate(lines)]}


A = make_pdf([
    text_page(FY_LINES + ["Energy consumed FY24 4,560 MWh", "Water withdrawn FY24 120 kL", "Scope 1 emissions FY24 1,234 tCO2e"]),
    grid(72, 100, [200, 100], [20, 20, 20], [["Category", "FY24"], ["Permanent employees", "8,616"], ["Board meetings", "7"]]),
    text_page(["Energy consumed FY24 4,560 MWh"]),
    text_page(["No figures on this page."]),
])
B = make_pdf([text_page(FY_LINES + ["Energy consumed FY24 50 MWh"]), text_page(["Water withdrawn FY24 9 kL"])])


def gold_row(id_, doc, page, answer, unit, metric, period=FY, boundary="unstated", bbox=None):
    return {"id": id_, "doc": doc, "page": page, "expected_answer": answer, "unit": unit, "metric": metric,
            "aliases": [], "boundary": boundary, "period": period, "bbox": bbox, "verify_status": "VERIFIED"}


def write_gold(folder, documents, rows):
    """A gold folder whose MANIFEST.json holds the sha256 of the files as written."""
    folder.mkdir()
    (folder / "documents.json").write_text(json.dumps({"documents": documents}), encoding="utf-8")
    for kind, name in g2.GOLD_FILES.items():
        (folder / name).write_text("".join(json.dumps(r) + "\n" for r in rows.get(kind, [])), encoding="utf-8")
    sha = {n: hashlib.sha256((folder / n).read_bytes()).hexdigest() for n in ["documents.json", *g2.GOLD_FILES.values()]}
    (folder / "MANIFEST.json").write_text(json.dumps({"gold_version": "test-gold", "sha256": sha}), encoding="utf-8")
    return folder


DOCS = [
    {"doc": "a.pdf", "sha256": hashlib.sha256(A).hexdigest(), "company": "Acme Limited", "document_type": "BRSR"},
    {"doc": "b.pdf", "sha256": hashlib.sha256(B).hexdigest(), "company": "Mahi Limited",
     "document_type": "integrated annual report", "brsr_section": {"start_pdf_page": 2, "end_pdf_page": 2}},
]


def build(gct, make_file, docs=(("a.pdf", A, "Acme Limited"), ("b.pdf", B, "Mahi Limited")), publish=True):
    for _, _, company in docs:
        gct("company", "add", company)
    for name, data, company in docs:
        assert gct("doc", "add", make_file(name, data), "--company", company).code == 0
    gct("contributor", "add", "ana", "--name", "Ana")
    assert gct("read").code == 0 and gct("extract").code == 0 and gct("infer").code == 0
    if publish:
        assert gct("publish", "build").code == 0


def box(gct, claim):
    (c,) = [c for c in gct("claims", "list", "--doc", 1, "--json").data["claims"] if c["id"] == claim]
    return c["boxes"][0]


def grown(b, share):
    """A gold box holding the claim box with IoU share: the claim box extended downward."""
    bottom = b[3] + (b[3] - b[1]) * (1 / share - 1)
    while g2.iou(b, [b[0], b[1], b[2], bottom]) < share:  # float rounding: step to the box whose IoU is share
        bottom = math.nextafter(bottom, 0)
    return [b[0], b[1], b[2], bottom]


@pytest.fixture
def scored(ws, db, gct, make_file, tmp_path):
    build(gct, make_file, publish=False)
    claims = {c["value_text"] + "@" + str(c["page_number"]): c["id"] for c in gct("claims", "list", "--doc", 1, "--json").data["claims"]}
    energy, water, employees = claims["4,560@1"], claims["120@1"], claims["8,616@2"]
    for claim, period in ((energy, FY), (water, CY), (employees, FY)):
        assert gct("infer", "resolve", claim, "--field", "period", "--kind", period["kind"], "--start", period["start"],
                   "--end", period["end"], *WHO).code == 0
    assert gct("infer", "resolve", employees, "--field", "boundary", "--boundary", "standalone", *WHO).code == 0
    # A claim that is not current (no extraction found it) on page 3.
    db.execute("INSERT INTO claim (company_id, document_id, page_number, locator, created_at) VALUES (1, 1, 3, 'h', 't')")
    v = db.execute("INSERT INTO claim_version (claim_id, run_id, method, config_version, value_text, unit_text,"
                   " metric_text, created_at) VALUES (last_insert_rowid(), 1, 'hand', 'c', '999', 'MWh', 'Energy consumed', 't')").lastrowid
    db.execute("INSERT INTO evidence_ref (claim_version_id, document_id, page_number, created_at) VALUES (?, 1, 3, 't')", (v,))
    db.commit()
    assert gct("publish", "build").code == 0
    rows = {
        "text": [
            gold_row("acme-text-01", "a.pdf", 1, "4,560", "MWh", "energy consumed", bbox=grown(box(gct, energy), 0.5)),
            gold_row("acme-text-02", "a.pdf", 1, "120", "kL", "water withdrawn", bbox=grown(box(gct, water), 0.49)),
            gold_row("acme-text-03", "a.pdf", 1, "1234", "tonnes CO2e", "scope 1 emissions"),
            gold_row("acme-text-04", "a.pdf", 4, "4560", "MWh", "energy consumed"),
            gold_row("acme-text-05", "a.pdf", 2, "4,560", "MWh", "energy consumed"),
            gold_row("acme-text-06", "a.pdf", 1, "KPMG", None, "assurance provider"),
            gold_row("acme-text-07", "a.pdf", 1, "120", "kL", "rainwater harvested", period=CY),
            gold_row("acme-text-08", "a.pdf", 3, "999", "MWh", "energy consumed"),
        ],
        "table": [
            gold_row("acme-table-01", "a.pdf", 2, "8,616", "employees", "permanent employees", boundary="standalone"),
            gold_row("acme-table-02", "a.pdf", 2, "7", "INR crore", "board meetings"),
            gold_row("acme-table-03", "a.pdf", 2, "7", "meetings", "board meetings", boundary="consolidated"),
        ],
        "figure": [
            gold_row("mahi-figure-01", "b.pdf", 2, "9", "kL", "water withdrawn"),
            gold_row("mahi-figure-02", "b.pdf", 1, "50", "MWh", "energy consumed"),
        ],
    }
    return write_gold(tmp_path / "gold", DOCS, rows)


# AC 3
def test_seeded_workspace_scores_exactly(ws, gct, scored):
    r = gct("measure", "g2", "--gold", scored, "--seed", 7, "--json")
    assert r.code == 0, r.out
    data = r.data
    rows = {x["id"]: x for x in data["rows"]}
    got = {i: (x["verdict"], x["failing"], x["reason"]) for i, x in rows.items()}
    assert got == {
        "acme-text-01": ("Found", [], None),
        "acme-text-02": ("Partial", ["period"], None),  # same year 2024, a different period end
        "acme-text-03": ("Partial", ["period"], None),  # proposed only: never read
        "acme-text-04": ("Missed", [], "page has no current claim"),
        "acme-text-05": ("Missed", [], "no value match on the page"),  # the value is printed on pages 1 and 3
        "acme-text-06": ("Missed", [], "gold value is not a figure"),
        "acme-text-07": ("Partial", ["metric"], None),
        "acme-text-08": ("Missed", [], "no value match on the page"),  # the claim of 999 on page 3 is not current
        "acme-table-01": ("Found", [], None),  # a count noun matches a claim without a unit
        "acme-table-02": ("Missed", [], "value matches, unit does not"),  # INR crore does not
        "acme-table-03": ("Partial", ["boundary", "period"], None),
        "mahi-figure-01": ("Partial", ["period"], None),
        "mahi-figure-02": ("Partial", ["period"], None),
    }
    assert (rows["acme-text-01"]["iou"], rows["acme-text-01"]["evidence_found"]) == (0.5, True)
    assert (rows["acme-text-02"]["iou"], rows["acme-text-02"]["evidence_found"]) == (0.49, False)
    assert rows["acme-text-04"]["value_elsewhere_in_document"] and rows["acme-text-05"]["value_elsewhere_in_document"]
    assert rows["acme-text-06"]["ceiling"] == ["gold value is not a figure"]
    assert rows["acme-table-02"]["ceiling"] == ["gold currency unit"]
    # The BRSR section of b.pdf reports as BRSR, read from documents.json.
    assert (rows["mahi-figure-01"]["document_type"], rows["mahi-figure-02"]["document_type"]) == (
        "BRSR", "integrated annual report")

    types = {(t["company"], t["kind"]): t for t in data["types"]}
    t = types[("Acme Limited", "text")]
    assert (t["n"], t["found"], t["partial"], t["missed"], t["found_text"], t["verdict"]) == (
        8, 1, 3, 4, "1/8 (12.5%)", "fail")
    assert t["evidence_found_among_found"] == "1/1 (100.0%)" and t["evidence_found_among_partial"] == "0/3 (0.0%)"
    assert t["value_and_unit_on_gold_page"] == "4/8 (50.0%)"
    assert types[("Acme Limited", "figure")]["verdict"] == "UNMEASURED"
    assert types[("Mahi Limited", "figure")]["found_text"] == "0/2 (0.0%)"
    assert ("Mahi Limited", "BRSR", "figure") in {(g["company"], g["document_type"], g["kind"]) for g in data["document_types"]}
    assert data["runs"] == [{"row": "rung 1", "state": "scored"}, {"row": "local escalation", "state": "not run"}]
    a = data["documents"][0]
    assert a["method_mix"] == [{"rung": 1, "method": a["method_mix"][0]["method"], "pages": 4}]
    assert a["cost"]["estimated"] is None and a["cost"]["reason"]
    assert data["adjudication"]["seed"] == 7 and sorted(data["adjudication"]["missed"]) == [
        "acme-table-02", "acme-text-04", "acme-text-05", "acme-text-06", "acme-text-08"]
    sample = {(s["company"], s["kind"]): s["ids"] for s in data["adjudication"]["found_sample"]}
    assert sample[("Acme Limited", "text")] == ["acme-text-01"] and sample[("Acme Limited", "table")] == ["acme-table-01"]
    assert list(data)[-1] == "aggregate" and data["aggregate"][-1]["kind"] == "all"
    check("measure g2", data)


# AC 2
def test_first_line_names_version_commit_and_scorer_and_report_sits_beside_the_workspace(ws, gct, scored):
    r = gct("measure", "g2", "--gold", scored, "--seed", 1)
    assert r.code == 0, r.err
    first, *rest = r.out.splitlines()
    assert re.fullmatch(r"published version 1, gct commit ([0-9a-f]{40}(-dirty)?|unknown), scorer version [12]", first)
    assert any(line.startswith("Acme Limited text: Found 1/8 (12.5%), Partial 3, Missed 4") and line.endswith("; fail")
               for line in rest)
    data = gct("measure", "g2", "--gold", scored, "--seed", 1, "--json").data
    assert list(data)[:3] == ["published_version", "gct_commit", "scorer_version"]
    reports = sorted(ws.parent.glob("g2-report-v1-*.json"))
    assert len(reports) == 2 and json.loads(reports[-1].read_text())["rows"] == data["rows"]
    # AC 8: the report never says passed.
    assert "pass" not in r.out.lower() and "pass" not in reports[-1].read_text().lower()


# AC 6
def test_delta_is_attributed_to_the_scorer_or_the_extraction_never_both(ws, gct, scored, monkeypatch):
    first = gct("measure", "g2", "--gold", scored, "--seed", 1, "--json").data
    assert first["delta"] is None
    monkeypatch.setattr(g2, "SCORER_VERSION", "3")
    r = gct("measure", "g2", "--gold", scored, "--seed", 1, "--against", first["report_path"])
    assert r.code == 0, r.err
    line = r.out.splitlines()[1]
    assert line.startswith(f"Scorer delta from run {first['run_id']} (scorer version 2, published version 1): ")
    assert "Acme Limited text Found 1/8 (12.5%) -> 1/8 (12.5%) (+0)" in line
    monkeypatch.setattr(g2, "SCORER_VERSION", "2")
    scope = next(c["id"] for c in gct("claims", "list", "--doc", 1, "--json").data["claims"] if c["value_text"] == "1,234")
    gct("infer", "resolve", scope, "--field", "period", "--kind", "fiscal_year", "--start", "2023-04-01",
        "--end", "2024-03-31", *WHO)
    gct("publish", "build")
    d = gct("measure", "g2", "--gold", scored, "--seed", 1, "--against", first["report_path"], "--json").data["delta"]
    text = next(t for t in d["types"] if (t["company"], t["kind"]) == ("Acme Limited", "text"))
    assert (d["attributed_to"], text["after"], text["found_change"], text["partial_change"]) == (
        "extraction", "2/8 (25.0%)", 1, -1)
    monkeypatch.setattr(g2, "SCORER_VERSION", "3")
    before = set(ws.parent.glob("g2-report-*"))
    r = gct("measure", "g2", "--gold", scored, "--against", first["report_path"], "--json")
    assert r.code == 4 and "both changed" in r.data["cause"] and set(ws.parent.glob("g2-report-*")) == before


# AC 6: version 1 of another workspace is another version.
def test_against_compares_the_version_identity_not_its_number(ws, gct, make_file, scored, tmp_path, monkeypatch):
    first = gct("measure", "g2", "--gold", scored, "--seed", 1, "--json").data
    assert first["published"] == {
        "workspace": str(ws.resolve()), "built_at": first["published"]["built_at"],
        "history_mark": first["published"]["history_mark"],
        "sha256": hashlib.sha256((ws / "published" / "v1.db").read_bytes()).hexdigest()}
    other = tmp_path / "ws2"
    assert gct("workspace", "init", other).code == 0
    monkeypatch.setenv("GCT_WORKSPACE", str(other))
    build(gct, make_file)  # the same documents, published as its own version 1
    monkeypatch.setattr(g2, "SCORER_VERSION", "3")
    r = gct("measure", "g2", "--gold", scored, "--against", first["report_path"], "--json")
    assert r.code == 4 and "both changed" in r.data["cause"] and len(list(tmp_path.glob("g2-report-*"))) == 1


def no_report(ws):
    return not list(ws.parent.glob("g2-report-*"))


# AC 2
def test_refuses_without_a_published_version(ws, gct, make_file, tmp_path):
    build(gct, make_file, publish=False)
    r = gct("measure", "g2", "--gold", write_gold(tmp_path / "gold", DOCS, {}), "--json")
    assert (r.code, r.data["status"]) == (4, "error") and "no published version" in r.data["cause"]
    assert no_report(ws)


def test_refuses_a_changed_gold_file(ws, gct, make_file, tmp_path):
    build(gct, make_file)
    gold = write_gold(tmp_path / "gold", DOCS, {"text": [gold_row("x", "a.pdf", 1, "1", None, "m")]})
    (gold / "text.jsonl").write_text("", encoding="utf-8")
    r = gct("measure", "g2", "--gold", gold, "--json")
    assert r.code == 4 and "text.jsonl differs" in r.data["cause"] and no_report(ws)
    gold = write_gold(tmp_path / "gold2", DOCS, {})
    (gold / "SAMPLING.md").write_text("drawn", encoding="utf-8")
    manifest = json.loads((gold / "MANIFEST.json").read_text())
    manifest["sha256"]["SAMPLING.md"] = "0" * 64
    (gold / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    r = gct("measure", "g2", "--gold", gold, "--json")
    assert r.code == 4 and "SAMPLING.md differs" in r.data["cause"] and no_report(ws)


def test_refuses_a_gold_document_missing_or_with_another_sha256(ws, gct, make_file, tmp_path):
    build(gct, make_file)
    other = [{**DOCS[0], "sha256": "0" * 64}, DOCS[1]]
    r = gct("measure", "g2", "--gold", write_gold(tmp_path / "g1", other, {}), "--json")
    assert r.code == 4 and "differs from the workspace document" in r.data["cause"]
    missing = [*DOCS, {**DOCS[0], "doc": "c.pdf", "sha256": "1" * 64}]
    r = gct("measure", "g2", "--gold", write_gold(tmp_path / "g2", missing, {}), "--json")
    assert r.code == 4 and "c.pdf has no document row" in r.data["cause"] and no_report(ws)


def test_refuses_a_company_with_no_current_claims(ws, gct, make_file, tmp_path):
    empty = make_pdf([text_page(["No figures here."])])
    build(gct, make_file, docs=(("a.pdf", A, "Acme Limited"), ("b.pdf", empty, "Mahi Limited")))
    docs = [DOCS[0], {**DOCS[1], "sha256": hashlib.sha256(empty).hexdigest()}]
    r = gct("measure", "g2", "--gold", write_gold(tmp_path / "gold", docs, {}), "--json")
    assert r.code == 4 and "no current claims for Mahi Limited" in r.data["cause"] and no_report(ws)


def test_refuses_a_read_only_workspace_folder_and_changes_nothing_in_it(ws, gct, make_file, tmp_path):
    build(gct, make_file)
    gold = write_gold(tmp_path / "gold", DOCS, {})
    gc.collect()  # close the in-process CLI's connections, so SQLite removes -wal and -shm as when gct exits
    assert not (ws / "workspace.db-wal").exists()
    files = lambda: {p.name: p.read_bytes() for p in ws.iterdir() if p.is_file()}
    before = files()
    ws.chmod(0o555)
    try:
        try:
            (ws / "probe").touch()
        except PermissionError:
            r = gct("measure", "g2", "--gold", gold, "--json")
        else:
            pytest.skip("this user can write into a read-only folder")
    finally:
        ws.chmod(0o755)
    assert r.code == 4 and str(ws.resolve()) in r.data["cause"] and no_report(ws) and files() == before


def test_units_and_sample_size():
    assert g2.unit_match(None, "employees") and not g2.unit_match(None, "INR crore") and not g2.unit_match(None, "%")
    assert g2.unit_match("₹ crore", "Rs. crore") and g2.unit_match("tCO2 e", "tCO2e") and g2.unit_match("m³", "m3")
    assert not g2.unit_match("%", None) and g2.unit_match("percent", "%")
    # Two empty word answers never match, also when punctuation normalizes to nothing.
    assert not g2.value_match("", "") and not g2.value_match("—", "-") and g2.value_match("KPMG.", "kpmg")
    rows = [{"id": f"r{i:03}", "company": "C", "kind": "text", "verdict": "Found"} for i in range(150)]
    (text, *_) = g2._sample(rows, ["C"], 3)
    assert len(text["ids"]) == 15 and text["ids"] == g2._sample(rows, ["C"], 3)[0]["ids"]
    assert len(g2._sample(rows[:40], ["C"], 3)[0]["ids"]) == 10


def test_tie_break_and_exact_half_iou():
    """Found first, then fewer failing fields, then the larger IoU, then the lowest id; IoU of exactly 0.5 is
    Evidence Found."""
    row = {**gold_row("r", "a.pdf", 1, "10", "MWh", "energy consumed", bbox=[0, 0, 10, 20]), "kind": "text"}

    def claim(id_, metric="Energy consumed", start=FY["start"], box=None):
        c = {"id": id_, "company": "Acme Limited", "document_id": 1, "page_number": 1, "claim_version_id": id_,
             "metric_text": metric, "value_text": "10", "unit_text": "MWh", "period_start": start,
             "period_end": FY["end"], "reporting_boundary": "standalone"}
        return c, [{"page_number": 1, "boxes": json.dumps([box])}] if box else []

    def pick(*claims):
        r = g2.score_row(row, {"company": "Acme Limited", "document_type": "BRSR"}, {"id": 1}, [c for c, _ in claims],
                         {c["claim_version_id"]: refs for c, refs in claims})
        return r["claim"], r["verdict"], r["iou"], r["evidence_found"]

    full, tenth, half = [0, 0, 10, 20], [0, 0, 10, 1], [0, 0, 10, 10]
    assert g2.iou(half, full) == 0.5
    assert pick(claim(1, start=None, box=full), claim(5)) == (5, "Found", 0.0, False)
    assert pick(claim(1, metric="Water", start=None, box=full), claim(2, start=None, box=tenth)) == (
        2, "Partial", 0.05, False)
    assert pick(claim(1, start=None, box=tenth), claim(2, start=None, box=half)) == (2, "Partial", 0.5, True)
    assert pick(claim(3, start=None), claim(2, start=None)) == (2, "Partial", 0.0, False)


def scrub_git_env(monkeypatch):
    # a GIT_DIR or GIT_INDEX_FILE exported by the caller would redirect git commands into the caller's repository
    for var in subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True,
                              check=True).stdout.split():
        monkeypatch.delenv(var, raising=False)


def test_gct_commit_is_marked_dirty_by_a_changed_tracked_file_only(tmp_path, monkeypatch):
    scrub_git_env(monkeypatch)

    def git(*argv):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *argv],
                       cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "f").write_text("a")
    git("add", "f")
    git("commit", "-qm", "c")
    head = g2._git_head(tmp_path)
    assert re.fullmatch(r"[0-9a-f]{40}", head)
    (tmp_path / "untracked").write_text("x")
    assert g2._git_head(tmp_path) == head
    (tmp_path / "f").write_text("b")
    assert g2._git_head(tmp_path) == head + "-dirty"


@pytest.mark.parametrize("with_index_file", [False, True])
def test_dirty_marking_test_leaves_a_repository_named_by_the_callers_git_env_alone(tmp_path, monkeypatch,
                                                                                    with_index_file):
    scrub_git_env(monkeypatch)  # before any git call, so a GIT_DIR already exported cannot hit the caller's repository
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=decoy, check=True, capture_output=True)
    index = decoy / ".git" / "index"

    def state():
        refs = subprocess.run(["git", "--git-dir", str(decoy / ".git"), "for-each-ref",
                               "--format=%(refname) %(objectname)"], capture_output=True, text=True,
                              check=True).stdout
        files = sorted(p.relative_to(decoy).as_posix() for p in (decoy / ".git").rglob("*") if p.is_file())
        return refs, files, index.read_bytes() if index.exists() else None

    before = state()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    if with_index_file:
        monkeypatch.setenv("GIT_INDEX_FILE", str(index))
    test_gct_commit_is_marked_dirty_by_a_changed_tracked_file_only(work, monkeypatch)
    assert state() == before
    assert not (decoy / "f").exists()
