"""Story 7.1 part C (TASK-0218): the canonical report dataset (C1 to C8, V1 to V5) on tests/gate_fixture.py with
documents 1, 3 and 6 relabelled shareable (2 and 7 stay private, 4 is archived, 5 deleted). A W' world is the same
operations without the ones that touch a private document, applied in an order that keeps every other id equal, so
sanitised(W) must equal sanitised(W') as built (P10, K12). The report-fixture gates are in test_gate_*.py."""
import ast
import copy
import gc
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import gate_fixture
from gate_fixture import ENERGY, SCOPE_1, WHO
from test_view import dump
from gct.reports import dataset, pin
from gct.stages import review, view
from gct.workspace import labels, layout, store
from gct.workspace.layout import GctError

GCT = Path(__file__).resolve().parent.parent / "gct"
GUARD = re.compile(r"verified|assured|certified|compliant|contradiction", re.I)  # test_review.WORDS plus contradiction
SHAREABLE = (1, 3, 6)


def run(root, *argv, ok=0):
    return gate_fixture.gct(*argv, "--workspace", root, ok=ok)


def newest(root, claim):
    return run(root, "claims", "history", claim)["versions"][-1]["id"]


@pytest.fixture(scope="module")
def plain(tmp_path_factory):
    """The gate fixture as built: every document private."""
    return gate_fixture.build(tmp_path_factory.mktemp("plain") / "ws")


@pytest.fixture(scope="module")
def base(tmp_path_factory, plain):
    root = tmp_path_factory.mktemp("base") / "ws"
    shutil.copytree(plain, root)
    for d in SHAREABLE:
        run(root, "doc", "label", d, "--privacy", "shareable", "--as", "ana", "--capacity", "analyst", "--rationale",
            "a public report")
    run(root, "publish", "build")
    return root


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    """store.now fixed (G (c)), so W and W' write the same times."""
    monkeypatch.setattr(store, "now", lambda: "2026-10-23T00:00:00+00:00")


def world(base, dst, *ops, publish=True):
    shutil.copytree(base, dst)
    for op in ops:
        op(dst)
    if publish:
        run(dst, "publish", "build")
    return dst


def pair(base, tmp_path, shared, private, order):
    """(W, W'): order is the sequence of op names; W' skips the private ones."""
    ops = {**shared, **private}
    return (world(base, tmp_path / "w", *(ops[k] for k in order)),
            world(base, tmp_path / "w2", *(ops[k] for k in order if k not in private)))


def build(root, **kw):
    conn = store.connect(root / layout.DB_NAME)
    try:
        return dataset.build(conn, root, **kw)
    finally:
        conn.close()


def same(a: dict, b: dict) -> None:
    """Equal apart from the build's own identity (the version file's hash and times)."""
    a, b = (copy.deepcopy(x) for x in (a, b))
    for x in (a, b):
        x.pop("built_at")
        x.pop("data_version")
    assert diff(a, b) == []


def diff(a, b, path="") -> list[str]:
    """The paths where two JSON values differ (first ten)."""
    if type(a) is not type(b) or not isinstance(a, (dict, list)):
        return [] if a == b else [f"{path}: {a!r} != {b!r}"]
    if isinstance(a, dict):
        out = [f"{path}.{k}: only on one side" for k in set(a) ^ set(b)]
        return (out + [x for k in a if k in b for x in diff(a[k], b[k], f"{path}.{k}")])[:10]
    if len(a) != len(b):
        return [f"{path}: {len(a)} items != {len(b)}"] + [x for i, (p, q) in enumerate(zip(a, b))
                                                          for x in diff(p, q, f"{path}[{i}]")][:9]
    return [x for i, (p, q) in enumerate(zip(a, b)) for x in diff(p, q, f"{path}[{i}]")][:10]


def rows(d, table):
    """Every row of a dataset table or sub-table."""
    top = {"evidence_index": d["evidence_index"], "related_claims": d["related_claims"],
           "restatement_log": d["restatement_log"], "unpaired_restatements": d["unpaired_restatements"]["rows"],
           **d["gap_report"]}
    out = []
    for t, rs in top.items():
        for r in rs:
            if t == table:
                out.append(r)
            if table in r:
                out += r[table]["rows"]
    return out


def by_claim(d):
    return {r["claim_id"]: r for r in d["evidence_index"] + d["related_claims"]}


def review_cmd(ledger, claim, version, outcome, who, *evidence, conclusion="agrees"):
    return lambda w: run(w, "review", ledger, claim, "--version", version, "--outcome", outcome, "--scope", "Scope",
                         "--conclusion", conclusion, "--as", who, "--capacity", "analyst", *evidence)


def correct_cmd(claim, value):
    return lambda w: run(w, "correct", claim, "--value", value, *WHO)


NOTE = ("--evidence-note", "ledger")
PRIVATE_PAGE = ("--evidence-doc", 2, "--evidence-page", 1)


# AC 9: the contract's constants, without a workspace

def test_columns_words_and_titles_follow_the_contract():
    cols = dataset.COLUMNS
    assert cols["evidence_index"] == cols["related_claims"] and cols["restatement_log"] == cols["candidates"]
    assert "pair_sides" not in cols
    for t, cs in cols.items():
        headings = [c["heading"] for c in cs]
        assert len(headings) == len(set(headings)), t
        assert cs[0]["key"] == "data_version" and cs[-1] == {"key": "label", "heading": "Label", "complete_only": True}
        assert sum(c.get("complete_only", False) for c in cs) == 1
        if t in dataset.SUB_TABLES:  # C3: a parent key column, null for unpaired_restatements only
            assert dataset.SUB_TABLES[t] in [c["key"] for c in cs] or (t, dataset.SUB_TABLES[t]) == (
                "unpaired_restatements", None)
    assert [t for t, k in dataset.SUB_TABLES.items() if k is None] == ["unpaired_restatements"]
    w = dataset.words()
    titles = w["fixed"]["titles"]
    assert set(titles) >= set(cols) | {"pair_sides", "gap_report", "about"}
    for t in titles.values():
        assert len(t) <= 31 and not set(t) & set("\\*?:/[]") and t.casefold() != "history", t
    assert len({t.casefold() for t in titles.values()}) == len(titles)
    assert set(w["fixed"]["headings"].values()) >= {c["heading"] for cs in cols.values() for c in cs}
    assert "withheld" not in json.dumps(w["fixed"])  # the withheld word is words.withheld only
    assert w["self_declared"] == review.SELF_DECLARED and w["earlier_version"] == "on an earlier version"
    assert w["privacy_notice"] == "Private content is excluded from this output."

    def strings(x):
        return [x] if isinstance(x, str) else [s for v in (x.values() if isinstance(x, dict) else x) for s in strings(v)]

    assert not [s for s in strings(w) if GUARD.search(s)]
    # C7's withheld keys are exactly the labels constants' fields that each table holds.
    for t, classes in dataset.WITHHELD.items():
        keys = {c["key"] for c in cols[t]}
        assert set(classes.get("identity", ())) == labels.IDENTITY & keys, t
        assert set(classes.get("contributor_text", ())) == labels.CONTRIBUTOR_TEXT & keys, t


# AC 9, AC 7, C2, C3: shape, identity and every key in every row, both modes

COMMON = ("id", "data_version", "label", "documents", "evidence", "withheld")


def check_shape(d, mode):
    json.dumps(d, allow_nan=False)
    assert set(d) == {"dataset_schema", "gct_version", "built_at", "mode", "include", "data_version", "filter",
                      "words", "columns", "documents", "evidence_index", "related_claims", "restatement_log",
                      "unpaired_restatements", "gap_report", "evidence", "notices"}
    u = d["unpaired_restatements"]
    assert set(u) == {"id", "title", "rows", "parent_key", "columns"} and (u["id"], u["parent_key"]) == (
        "unpaired_restatements", None) and u["title"] == dataset.TITLES["unpaired_restatements"]
    assert set(d["gap_report"]) == {"candidates", "expectations", "documents_checked", "extraction_limits", "archived",
                                    "deleted"}
    want = {t: [c for c in cs if mode == "complete" or not c.get("complete_only")] for t, cs in dataset.COLUMNS.items()}
    assert d["columns"] == want and d["mode"] == mode and d["dataset_schema"] == 1
    ident = {"version", "built_at", "sha256", "projection_schema"}
    assert set(d["data_version"]) == (ident | {"history_mark", "labels_mark"} if mode == "complete" else ident)
    evidence = {e["id"] for e in d["evidence"]}
    tables = {**{t: d[t] for t in ("documents", "evidence_index", "related_claims", "restatement_log")},
              "unpaired_restatements": u["rows"], **d["gap_report"]}
    assert u["columns"] == d["columns"]["unpaired_restatements"]
    for t, rs in tables.items():
        for r in rs:
            check_row(d, t, r, evidence)
    for e in d["evidence"]:
        assert set(e) == {"id", "kind", "document_id", "sha256", "page", "boxes", "sheet", "cell", "header", "row",
                          "marked"} and e["kind"] in ("claim", "basis", "restatement", "review")


def printed(table):
    return {c["key"].split(".")[0] for c in dataset.COLUMNS[table]}


def check_row(d, table, r, evidence):
    assert set(COMMON) <= set(r), (table, r)
    assert r["data_version"] == d["data_version"]["version"] and r["label"] in ("shareable", "private")
    assert set(r["evidence"]) <= evidence
    subs = {k for k in dataset.SUB_TABLES if k in r}
    assert set(r) == printed(table) | set(COMMON) | subs, table  # every key always present, nothing else
    for k in subs:
        s = r[k]
        assert s["id"] == k and s["title"] == dataset.TITLES[k] and s["parent_key"] == dataset.SUB_TABLES[k]
        assert s["columns"] == d["columns"][k]
        for x in s["rows"]:
            assert x[s["parent_key"]] == r["id"]
            check_row(d, k, x, evidence)


@pytest.mark.parametrize("mode", dataset.MODES)
def test_every_row_holds_every_key_of_its_table(base, mode):
    d, p = build(base, mode=mode)
    check_shape(d, mode)
    assert d["evidence_index"] and rows(d, "records") and d["gap_report"]["documents_checked"]
    if mode == "complete":
        assert d["restatement_log"] and rows(d, "restatements") and rows(d, "adjudications")
        assert d["gap_report"]["archived"] and d["gap_report"]["deleted"]


@pytest.mark.parametrize("mode", dataset.MODES)
def test_every_sub_table_shares_its_tables_one_columns_list(base, mode):
    """AC 17 (review of c253740): one columns list per table, not a copy per row."""
    d, _ = build(base, mode=mode)
    assert {id(r["records"]["columns"]) for r in d["evidence_index"]} == {id(d["columns"]["records"])}


def test_the_identity_is_the_pinned_file_and_the_mode_decides_the_marks(base):
    conn = store.connect(base / layout.DB_NAME)
    pconn, ident = pin.pin(conn, base)
    pconn.close()
    conn.close()
    s, sp = build(base)
    c, _ = build(base, mode="complete")
    assert s["data_version"] == {k: ident[k] for k in ("version", "built_at", "sha256", "projection_schema")}
    assert c["data_version"] == ident and (sp["history_mark"], sp["labels_mark"]) == (ident["history_mark"],
                                                                                     ident["labels_mark"])
    assert ident["history_mark"] not in json.dumps(s)
    with pytest.raises(GctError) as e:
        build(base, data_version=ident["version"] - 1)
    assert e.value.cause.startswith(f"Data version {ident['version'] - 1} is no longer the current one")
    for bad in ({"mode": "public"}, {"include": ["names"]}, {"filter": {"colour": ["red"]}}):
        with pytest.raises(GctError) as e:
            build(base, **bad)
        assert e.value.code == layout.USAGE


# AC 7 (K18, V4): the evidence index ids are E6's selection, on the pin and on the reduced copy

@pytest.mark.parametrize("flt", [{}, {"company": [2]}, {"document": [3]}, {"metric": ["ghg_scope_1"]},
                                 {"text": "energy"}, {"comparison": ["restatement"]}, {"review": ["disagreement"]},
                                 {"claim_state": ["current"]}, {"document": [5]}])
def test_the_ids_are_view_select_on_the_pin_and_on_the_copy(base, flt):
    conn = store.connect(base / layout.DB_NAME)
    pconn, ident = pin.pin(conn, base)
    b = dataset._Build(conn, base, pconn, ident, view.normalise(flt), [])
    rconn = b.reduce()
    want = {"complete": view.select(pconn, flt), "sanitised": view.select(rconn, flt)}
    with pytest.raises(sqlite3.OperationalError):  # the copy refuses writes once built
        rconn.execute("DELETE FROM claim")
    assert pconn.execute("SELECT COUNT(*) FROM claim").fetchone()[0] > rconn.execute(
        "SELECT COUNT(*) FROM claim").fetchone()[0]
    rconn.close()
    pconn.close()
    conn.close()
    for mode, ids in want.items():
        d, _ = build(base, mode=mode, filter=flt)
        assert sorted(r["claim_id"] for r in d["evidence_index"]) == ids == sorted(r["id"] for r in d["evidence_index"])


def test_the_copy_is_made_from_the_pinned_bytes_without_reading_the_file_again(base, monkeypatch):
    reads = []
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: reads.append(self) or real(self))
    build(base)
    assert [p.name for p in reads if p.suffix == ".db"] == [f"v{pin_version(base)}.db"]


def pin_version(root):
    conn = store.connect(root / layout.DB_NAME)
    try:
        return pin.pin(conn, root)[1]["version"]
    finally:
        conn.close()


# AC 7 (K14, the injected build): a purge of the version file in the middle of one build changes nothing it holds

@pytest.mark.parametrize("mode", dataset.MODES)
def test_a_purge_between_two_queries_of_one_build_changes_nothing(base, tmp_path, monkeypatch, mode):
    from gct.stages import deletion
    from gct.workspace import published

    w = world(base, tmp_path / "w", publish=False)
    want = build(w, mode=mode)
    path = published.version_path(w, pin_version(w))
    before = path.read_bytes()
    real, done = view.answer, []

    def purging(*a, **k):
        if not done:
            published.purge(path, 1, [], [], [], deletion.MARKER.format(1))
            done.append(1)
        return real(*a, **k)

    monkeypatch.setattr(view, "answer", purging)
    got = build(w, mode=mode)
    assert done and path.read_bytes() != before
    same(got[0], want[0])
    assert got[0]["data_version"] == want[0]["data_version"] and got[1] == want[1]


# AC 6 (P4) and AC 10 (C7): inheritance, labels, withheld fields, pseudonyms

def test_sanitised_rows_ship_only_with_every_named_document_and_complete_rows_carry_their_label(base):
    s, _ = build(base)
    c, _ = build(base, mode="complete")
    assert {r["document_id"] for r in s["evidence_index"]} == set(SHAREABLE)
    assert {d["id"] for d in s["documents"]} == set(SHAREABLE) and {d["label"] for d in s["documents"]} == {"shareable"}
    for t in ("evidence_index", "records", "restatement_log", "restatements", "adjudications", "documents_checked"):
        assert all(r["label"] == "shareable" for r in rows(s, t)), t
    labelled = {r["claim_id"]: r["label"] for r in c["evidence_index"]}
    assert {k for k, v in labelled.items() if v == "shareable"} == {r["claim_id"] for r in s["evidence_index"]}
    pairs = {(p["claim_a"], p["claim_b"]): p for p in c["restatement_log"]}
    assert {p["label"] for p in pairs.values()} == {"private"} and not s["restatement_log"]  # each names document 2
    assert {d["id"]: d["state"] for d in c["documents"]}[4] == "archived"
    assert {d["id"]: (d["state"], d["name"]) for d in c["documents"]}[5] == ("deleted", None)


def test_contributors_are_pseudonyms_and_their_text_is_withheld(base):
    s, _ = build(base)
    recs = {(r["claim_id"], r["kind"]): r for r in rows(s, "records")}
    assert recs[1, "company confirmation"]["contributor"] == "Contributor 1"  # ana, first in the C7 order
    assert recs[1, "auditor review"]["contributor"] == "Contributor 2"  # raj
    assert recs[3, "highlight"]["contributor"] == "Contributor 1"
    for r in recs.values():
        assert r["withheld"] == ["organisation", "capacity", "scope", "conclusion", "evidence_note", "note", "rationale"]
        assert all(r[k] is None for k in r["withheld"])
    corrected = by_claim(s)[14]
    assert corrected["correction"]["replaced"]["value_text"] == "1,900" and corrected["correction"]["contributor"] is None
    assert corrected["withheld"] == ["correction.contributor", "correction.organisation", "correction.capacity",
                                     "correction.rationale"]
    assert by_claim(s)[1]["withheld"] == corrected["withheld"] and by_claim(s)[1]["correction"] is None
    text = json.dumps(s)
    for leak in ("Ana", "Raj", "Acme audit", "head of sustainability", gate_fixture.VERIFIED, "checked on the page"):
        assert leak not in text, leak
    assert gate_fixture.VERIFIED in json.dumps(build(base, mode="complete")[0])  # the scan can find it


@pytest.mark.parametrize("include", [("identity",), ("contributor_text",), ("flags",),
                                     ("contributor_text", "flags", "identity")])
def test_each_inclusion_class_restores_its_own_fields_only(base, include):
    d, p = build(base, include=include)
    assert d["include"] == sorted(include)
    recs = {(r["claim_id"], r["kind"]): r for r in rows(d, "records")}
    auditor = recs[1, "auditor review"]
    assert (auditor["contributor"] == "Raj") is ("identity" in include)
    assert (recs[1, "company confirmation"]["organisation"] == "Acme audit") is ("identity" in include)
    assert (auditor["conclusion"] == f"not {gate_fixture.VERIFIED}") is ("contributor_text" in include)
    assert ((13, "reviewer flag") in recs) is ("flags" in include)
    assert ("flags raised: 1" in by_claim(d)[13]["review_text"]) is ("flags" in include)
    assert (by_claim(d)[14]["correction"]["rationale"] == "checked on the page") is ("contributor_text" in include)
    assert p["withheld"]["flag"] == (0 if "flags" in include else 1)
    assert ("identity" in include) is (p["withheld"]["identity"] == 0)
    assert ("contributor_text" in include) is (p["withheld"]["contributor_text"] == 0)


def test_pseudonyms_go_by_contributor_key_across_versions_and_skip_withheld_records(base, tmp_path):
    w = world(base, tmp_path / "w",
              lambda w: run(w, "contributor", "add", "ana2", "--name", "Ana"),  # the same name, another key
              lambda w: run(w, "contributor", "add", "zed", "--name", "Zed"),
              lambda w: run(w, "contributor", "edit", "raj", "--name", "Raj Kumar"),  # a second version of raj
              review_cmd("company", 2, 2, "accepted", "ana2", *NOTE),
              review_cmd("auditor", 2, 2, "accepted", "raj", *NOTE),
              review_cmd("auditor", 3, 3, "rejected", "zed", *PRIVATE_PAGE))  # zed only on a withheld record
    d, _ = build(w)
    recs = {(r["claim_id"], r["kind"]): r["contributor"] for r in rows(d, "records")}
    # company confirmations first (ana on 1, ana2 on 2), then auditor reviews (raj on 1, 2 and 14)
    assert recs[1, "company confirmation"] == "Contributor 1" and recs[2, "company confirmation"] == "Contributor 2"
    assert recs[1, "auditor review"] == recs[2, "auditor review"] == recs[14, "auditor review"] == "Contributor 3"
    assert (3, "auditor review") not in recs and "Contributor 4" not in json.dumps(d)


# AC 9, C3d: the evidence entries

def test_evidence_entries_are_the_shipped_rows_locations_with_cells_read_from_the_original(base):
    d, _ = build(base)
    ev = {e["id"]: e for e in d["evidence"]}
    sheet_claim = by_claim(d)[18]
    (cell,) = [ev[i] for i in sheet_claim["evidence"]]
    assert (cell["kind"], cell["sheet"], cell["cell"], cell["page"]) == ("claim", "acme-meter", "B2", None)
    assert cell["header"][:3] == ["Metric", "Value", "Unit"] and cell["row"][cell["marked"]] == "700"
    page = [ev[i] for i in by_claim(d)[1]["evidence"]]
    assert [e["kind"] for e in page] == ["claim", "basis"] and page[0]["boxes"] and page[0]["page"] == 1
    review_ev = rows(d, "records")[0]["evidence"]
    assert [ev[i]["kind"] for i in review_ev] == ["review"]
    shipped = {e["document_id"] for e in d["evidence"]}
    assert shipped <= set(SHAREABLE) and {e["sha256"] for e in d["evidence"]} <= {
        x["sha256"] for x in build(base, mode="complete")[1]["included"]["documents"]}


# AC 9, C3c, B (missing evidence): the gap report

def test_identical_csvs_under_two_names_each_carry_their_cell_evidence(tmp_path):
    """C3d, AC 9 (review of c253740): a CSV's one sheet is named after its own document, so two shareable CSVs with the
    same bytes under different names and companies each get header, row and marked, in both modes."""
    root = tmp_path / "ws"
    gate_fixture.gct("workspace", "init", root)
    run(root, "contributor", "add", "ana", "--name", "Ana")
    for company, name in (("Alpha", "alpha.csv"), ("Beta", "beta.csv")):
        run(root, "company", "add", company)
        src = tmp_path / name
        src.write_text("Metric,Value,Unit,Period,Boundary\nTotal volume of water withdrawal,700,kL,FY 2024-25,"
                       "Standalone\n")
        doc = run(root, "doc", "add", src, "--company", company, "--kind", "evidence", "--privacy",
                  "shareable")["items"][0]["document"]["id"]
        run(root, "sheet", "map", doc, "--sheet", Path(name).stem, "--metric", "Metric", "--value", "Value", "--unit",
            "Unit", "--period", "Period", "--boundary", "Boundary", "--year-end", "03-31", "--boundary-is",
            "standalone", *WHO)
    for step in ("read", "extract", "infer", "match", "link", ("publish", "build")):
        run(root, *((step,) if isinstance(step, str) else step))
    for mode in dataset.MODES:
        cells = [e for e in build(root, mode=mode)[0]["evidence"] if e["cell"] is not None]
        assert len(cells) == 2 and len({e["sha256"] for e in cells}) == 1 and len({e["sheet"] for e in cells}) == 2
        for e in cells:
            assert e["header"] == ["Metric", "Value", "Unit", "Period", "Boundary"], (mode, e)
            assert e["row"] and e["marked"] is not None, (mode, e)


def test_the_gap_report_states_the_documents_checked_and_the_limits(base):
    d, _ = build(base)
    checked = {r["document_id"]: r for r in d["gap_report"]["documents_checked"]}
    assert set(checked) == set(SHAREABLE)
    assert (checked[1]["pages"], checked[1]["read"], checked[1]["limit_figures"]) == (1, 1, 1)
    assert checked[3]["sheets_mapped"] == [1] and checked[3]["limit_note"] == dataset.SHEETS_LIMIT
    assert [(r["type"], r["reason"], r["count"]) for r in d["gap_report"]["extraction_limits"]] == [
        ("figures", "charts not read", 2)]
    assert d["gap_report"]["archived"] == d["gap_report"]["deleted"] == []
    c, _ = build(base, mode="complete")
    assert [(r["document_id"], r["name"]) for r in c["gap_report"]["archived"]] == [(4, "acme-old.pdf")]
    assert [set(r) - set(COMMON) for r in c["gap_report"]["deleted"]] == [{"document_id", "deleted_at"}]
    assert "2 claims of 1 archived document are not in this or any view." in c["notices"][0]
    assert dataset.ARCHIVE_NOTICE in d["notices"] and dataset.PRIVACY_NOTICE in d["notices"]


def test_expectations_list_states_reasons_and_claims_and_withhold_an_archived_declared_document(base, tmp_path):
    w = world(base, tmp_path / "w",
              lambda w: run(w, "expect", "add", "--company", "Acme", "--metric", "Total Scope 1", "--doc", 1),
              lambda w: run(w, "expect", "add", "--company", "Acme", "--metric", "Total waste", "--doc", 1),
              lambda w: run(w, "doc", "restore", 4, *WHO),
              lambda w: run(w, "expect", "add", "--company", "Acme", "--metric", "Total waste", "--doc", 1, 4),
              lambda w: run(w, "doc", "archive", 4, *WHO))
    c, _ = build(w, mode="complete")
    s, _ = build(w)
    items = {r["expected_item_id"]: r for r in c["gap_report"]["expectations"]}
    assert items[1]["found"] and items[1]["claims"] == [1, 2] and items[1]["state"] is None
    assert items[2]["state"] == "processing incomplete or failed" and items[2]["reasons"]["rows"]
    assert [x["state"] for x in items[3]["declared"]["rows"]] == ["registered", "archived"]
    assert items[3]["label"] == "private" and items[1]["label"] == "shareable"
    conn = sqlite3.connect(w / "published" / f"v{pin_version(w)}.db")
    assert [len(r["claims"]) for r in items.values()] == [n for (n,) in conn.execute(
        "SELECT claims FROM expected_item ORDER BY id")]
    conn.close()
    assert [r["expected_item_id"] for r in s["gap_report"]["expectations"]] == [1, 2]
    filtered, _ = build(w, filter={"company": [1], "text": "energy"})
    assert len(filtered["gap_report"]["expectations"]) == 2 and dataset.EXPECTATIONS_SCOPE in filtered["notices"]


# AC 9 (C3a, B): the 400 nines, a non-binding record and an earlier-version restatement row

def test_a_value_of_400_nines_is_null_and_a_record_on_an_earlier_version_says_so(base, tmp_path):
    w = world(base, tmp_path / "w", correct_cmd(2, "9" * 400))
    for mode in dataset.MODES:
        d, p = build(w, mode=mode)
        json.dumps(d, allow_nan=False)
        row = by_claim(d)[2]
        assert row["value"] is None and row["value_text"] == "9" * 400
    # the raj auditor review on claim 14 stays listed on version 14, with the earlier-version words
    s, _ = build(w)
    (old,) = [r for r in rows(s, "records") if r["claim_id"] == 14]
    assert (old["claim_version_id"], old["binds"], old["earlier"]) == (14, False, "on an earlier version")


# AC 18 (P-empty): every in-scope document private, the no-claim and mixed-scope cells, then a relabel

def test_an_all_private_workspace_ships_nothing_and_the_preview_names_each_document(plain, tmp_path):
    d, p = build(plain)
    text = json.dumps(d, ensure_ascii=False)
    for t in ("evidence_index", "related_claims", "restatement_log", "documents", "evidence"):
        assert d[t] == [], t
    assert all(v == [] for v in d["gap_report"].values())
    assert d["notices"] == ["No shareable claims match this filter in data version 1.", dataset.PRIVACY_NOTICE,
                            dataset.ARCHIVE_NOTICE]
    names = ("acme-2025.pdf", "acme-2024.pdf", "acme-meter.csv", "beta-2025.pdf", "beta-balance.pdf", "acme-old.pdf")
    assert not [n for n in names if n in text] and "Acme" not in text and "Beta" not in text
    c, _ = build(plain, mode="complete")
    assert all(n in json.dumps(c, ensure_ascii=False) for n in names)
    assert p["lines"][0] == dataset.ALL_PRIVATE and p["lines"][-1] == (
        "To share a document's rows, relabel it: gct doc label ID --privacy shareable --as KEY --capacity TEXT"
        " --rationale TEXT")
    assert p["lines"][1:-1] == ["1  Acme  acme-2025.pdf  private", "2  Acme  acme-2024.pdf  private",
                                "3  Acme  acme-meter.csv  private", "6  Beta  beta-2025.pdf  private",
                                "7  Beta  beta-balance.pdf  private"]
    w = world(plain, tmp_path / "w", lambda w: run(w, "doc", "label", 6, "--privacy", "shareable", *WHO))
    d, p = build(w)
    assert {r["document_id"] for r in d["evidence_index"]} == {6} and [x["id"] for x in d["documents"]] == [6]
    assert p["lines"][0] == dataset.SOME_PRIVATE


def test_the_p_empty_scope_cells(base):
    # no claim matches, a shareable document in scope: rows [], its documents_checked row
    d, p = build(base, filter={"document": [3], "text": "no such wording"})
    assert d["evidence_index"] == [] and [r["document_id"] for r in d["gap_report"]["documents_checked"]] == [3]
    assert d["notices"][0] == dataset.sanitised_empty(pin_version(base)) and p["lines"] == []
    # mixed scope: one private matched claim's document and one shareable document without matching claims
    d, p = build(base, filter={"document": [2, 3], "metric": ["ghg_scope_1"]})
    assert d["evidence_index"] == [] and [r["document_id"] for r in d["gap_report"]["documents_checked"]] == [3]
    assert p["lines"][0] == dataset.SOME_PRIVATE and p["lines"][1].startswith("2  Acme  acme-2024.pdf")
    # the whole scope private
    d, p = build(base, filter={"document": [2, 7]})
    assert d["gap_report"]["documents_checked"] == [] and d["documents"] == [] and p["lines"][0] == dataset.ALL_PRIVATE


def test_the_sanitised_filter_echo_names_only_what_ships(base):
    d, _ = build(base, filter={"document": [1, 2], "company": [1, 2], "text": "Total", "series": ["2b7f0c7666c0"]})
    assert d["filter"] == {"company": [1], "document": [1], "series": ["2b7f0c7666c0"], "text": None,
                           "withheld": ["text"]}
    c, p = build(base, mode="complete", filter={"document": [1, 2], "text": "Total"})
    assert c["filter"] == p["filter"] == {"document": [1, 2], "text": "Total"}


# AC 6 and AC 20 (P10, C5a): computed values come from the shipped records only; W equals W'

def test_a_private_dispute_changes_no_sanitised_value_and_no_selection(base, tmp_path):
    w, w2 = pair(base, tmp_path, {
        "zed": lambda w: run(w, "contributor", "add", "zed", "--name", "Zed", "--organisation", "Zed audit"),
        "raj_old": review_cmd("auditor", 3, 3, "accepted", "raj", *NOTE),
        "ana": review_cmd("company", 3, 3, "accepted", "ana", "--evidence-doc", 1, "--evidence-page", 1)}, {
        "raj_new": review_cmd("auditor", 3, 3, "disputed", "raj", *PRIVATE_PAGE),
        "zed_k1": review_cmd("auditor", 1, 1, "rejected", "zed", *PRIVATE_PAGE)},
        ["zed", "raj_old", "ana", "raj_new", "zed_k1"])
    for flt in ({}, {"review": ["disagreement"]}, {"review": ["company-confirmation", "auditor-review"]}):
        same(build(w, filter=flt)[0], build(w2, filter=flt)[0])
    c, _ = build(w, mode="complete", filter={"review": ["disagreement"]})
    s, p = build(w, filter={"review": ["disagreement"]})
    assert [r["claim_id"] for r in c["evidence_index"]] == [1, 3] and [r["claim_id"] for r in s["evidence_index"]] == [1]
    # claim 3's own row, its highlight, raj's older and ana's rows would have shipped: selection_recomputed
    assert p["withheld"]["selection_recomputed"] == 4
    row = by_claim(build(w)[0])[3]
    assert row["review_text"] == "company accepted; auditor accepted; highlights: 1" and not row["disagreements"]["rows"]
    raj = [r for r in row["records"]["rows"] if r["kind"] == "auditor review"]
    assert [(r["outcome"], r["latest"]) for r in raj] == [("accepted", True)]  # latest on the copy
    k1 = by_claim(build(w)[0])[1]
    assert k1["review_text"] == "company accepted; auditor disputed; disagreement" and "withheld" not in k1["review_text"]
    assert by_claim(c)[3]["review_text"] == "company accepted; auditor disputed; disagreement; highlights: 1"


def test_the_sanitised_review_text_is_view_review_text_of_the_shipped_records(base, tmp_path):
    w = world(base, tmp_path / "w", review_cmd("company", 2, 2, "accepted", "ana", *NOTE),
              review_cmd("auditor", 4, 4, "rejected", "raj", *NOTE))
    d, _ = build(w)
    for cid, r in by_claim(d).items():
        on = [x for x in r["records"]["rows"] if x["claim_version_id"] == r["version_id"]]
        pos = {k: [o for o in review.OUTCOMES if any(x["latest"] and x["kind"] == k and x["outcome"] == o for x in on)]
               for k in ("company confirmation", "auditor review")}
        company, auditor = pos["company confirmation"], pos["auditor review"]
        rv = {"company": company, "auditor": auditor,
              "disagreement": {"company": company, "auditor": auditor} if company and auditor and company != auditor
              else None, "flags_raised": 0, "highlights": sum(x["kind"] == "highlight" for x in on),
              "needs_re_review": len(r["needs_renewed_review"]), "corrected": r["correction"] is not None,
              "adjudications": []}
        assert r["review_text"] == view.review_text(rv), cid
    assert by_claim(d)[2]["review_text"] == "company accepted" and by_claim(d)[4]["review_text"] == "auditor rejected"


def test_a_withheld_restatement_record_leaves_the_pair_unresolved_on_the_copy(base, tmp_path):
    def restated(w):  # a recorded restatement citing private document 7 (a direct row: the CLI cites the restated page)
        conn = sqlite3.connect(w / layout.DB_NAME)
        conn.execute("INSERT INTO restatement (original_version_id, restated_version_id, series_key, decision,"
                     " evidence_document_id, evidence_page, evidence_quote, contributor_version_id, capacity, rationale,"
                     " created_at) VALUES (7, 4, 'k', 'recorded', 7, 1, 'quote', 1, 'analyst', 'r', '2026-10-23')")
        conn.commit()
        conn.close()

    share2 = lambda w: run(w, "doc", "label", 2, "--privacy", "shareable", *WHO)
    w, w2 = pair(base, tmp_path, {"share2": share2}, {"restated": restated}, ["share2", "restated"])
    flt = {"comparison": ["unresolved"]}
    c, _ = build(w, mode="complete", filter=flt)
    s, p = build(w, filter=flt)
    assert c["evidence_index"] == [] and [r["claim_id"] for r in s["evidence_index"]] == [7, 4]
    same(s, build(w2, filter=flt)[0])
    same(build(w)[0], build(w2)[0])
    (unresolved,) = [x for x in build(w)[0]["restatement_log"] if x["claim_a"] in (4, 7)]
    assert (unresolved["state"], unresolved["shown_state"]) == ("unresolved conflict", "explained difference")


# AC 9, AC 20 (P11): needs renewed review per entry kind, each case equal to W'

@pytest.mark.parametrize("ledger,kind", [("company", "company confirmation"), ("auditor", "auditor review")])
def test_ledger_renewal_ships_is_withheld_and_appears_when_a_withheld_newer_row_suppressed_it(base, tmp_path, ledger,
                                                                                               kind):
    shared = {"a": review_cmd(ledger, 2, 2, "accepted", "ana", *NOTE),  # ships
              "c": review_cmd(ledger, 4, 4, "accepted", "ana", *NOTE),  # suppressed by a withheld newer row
              "fix_a": correct_cmd(2, "1,101"), "fix_b": correct_cmd(3, "5,001"), "fix_c": correct_cmd(4, "4,801")}
    private = {"b": review_cmd(ledger, 3, 3, "accepted", "ana", *PRIVATE_PAGE),  # its target is withheld
               "c_new": lambda w: review_cmd(ledger, 4, newest(w, 4), "accepted", "ana", *PRIVATE_PAGE)(w)}
    w, w2 = pair(base, tmp_path, shared, private, ["a", "c", "b", "fix_a", "fix_b", "fix_c", "c_new"])
    s, s2 = build(w)[0], build(w2)[0]
    same(s, s2)
    c = build(w, mode="complete")[0]
    sanitised = {cid: [e for e in by_claim(s)[cid]["needs_renewed_review"] if e.startswith(kind)] for cid in (2, 3, 4)}
    complete = {cid: [e for e in by_claim(c)[cid]["needs_renewed_review"] if e.startswith(kind)] for cid in (2, 3, 4)}
    assert len(sanitised[2]) == len(complete[2]) == 1  # ships
    assert sanitised[3] == [] and len(complete[3]) == 1  # the withheld target: no entry
    assert len(sanitised[4]) == 1 and complete[4] == []  # the older renewal appears
    # the period and boundary reviews of the corrected claims are kept as projected
    assert any(e.startswith("period review #") for e in by_claim(s)[2]["needs_renewed_review"])
    assert any(e.startswith("boundary review #") for e in by_claim(s)[2]["needs_renewed_review"])


def test_correction_and_flag_renewals_are_kept_as_projected_and_flags_need_their_inclusion(base, tmp_path):
    def reread(w):  # a newer version not made by a correction (as a re-extraction makes), so the correction renews
        conn = sqlite3.connect(w / layout.DB_NAME)
        cols = ", ".join(r[1] for r in conn.execute("PRAGMA table_info(claim_version)") if r[1] != "id")
        conn.execute(f"INSERT INTO claim_version ({cols}) SELECT {cols} FROM claim_version WHERE claim_id = 1"
                     " ORDER BY id DESC LIMIT 1")
        conn.commit()
        conn.close()

    w = world(base, tmp_path / "w", lambda w: run(w, "flag", "raise", 1, "--version", 1, *WHO),
              correct_cmd(1, "1,235"), reread)
    c = by_claim(build(w, mode="complete")[0])[1]["needs_renewed_review"]
    assert {e.split(" #")[0] for e in c} == {"correction", "period review", "boundary review", "company confirmation",
                                             "auditor review", "reviewer flag"} and len(c) == 6
    s = by_claim(build(w)[0])[1]["needs_renewed_review"]
    assert s == [e for e in c if not e.startswith("reviewer flag")]
    assert by_claim(build(w, include=["flags"])[0])[1]["needs_renewed_review"] == c


def test_the_kept_renewal_kinds_name_no_document_but_the_claims(tmp_path):
    """P11's third case cannot be built for these kinds: their tables reach a document only through the claim."""
    conn = store.connect(tmp_path / "w.db")
    store.migrate(conn)
    for t in ("correction", "inference_review", "reviewer_flag"):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
        assert not [c for c in cols if "document" in c], (t, cols)
        assert "claim_version_id" in cols
    conn.close()


def test_adjudication_renewal_ships_and_appears_when_a_withheld_binding_row_suppressed_it(base, tmp_path):
    share2 = lambda w: run(w, "doc", "label", 2, "--privacy", "shareable", *WHO)
    fix7 = lambda w: (correct_cmd(7, "4,910")(w), gate_fixture.ready(("--workspace", w), 3))
    binding = lambda w: run(w, "adjudicate", "record", 4, 7, "--state", "extraction-error", "--counter-doc", 7,
                            "--counter-page", 1, "--procedure", "compared", *WHO)
    w, w2 = pair(base, tmp_path, {"share2": share2, "fix7": fix7}, {"binding": binding}, ["share2", "fix7", "binding"])
    s, s2 = build(w)[0], build(w2)[0]
    same(s, s2)
    c = build(w, mode="complete")[0]
    adj = {d: [e for e in by_claim(x)[4]["needs_renewed_review"] if e.startswith("adjudication")]
           for d, x in (("s", s), ("c", c))}
    assert adj["c"] == [] and adj["s"] == ["adjudication #1 on version 4 with claim 7 version 7"]
    (cand,) = s["gap_report"]["candidates"]
    assert cand["shown_state"] == "unreviewed candidate" and [x["binds"] for x in cand["adjudications"]["rows"]] == [False]


def test_an_adjudication_renewal_whose_other_side_is_private_is_withheld(base, tmp_path):
    w = world(base, tmp_path / "w", correct_cmd(4, "4,810"), lambda w: gate_fixture.ready(("--workspace", w), 3))
    c = by_claim(build(w, mode="complete")[0])[4]
    s = by_claim(build(w)[0])[4]
    assert any(e.startswith("adjudication #1") for e in c["needs_renewed_review"]) and c["label"] == "private"
    assert not any(e.startswith("adjudication") for e in s["needs_renewed_review"]) and s["label"] == "shareable"


# C3b, 7.1-P6: pairs and their sides

def test_pairs_with_one_side_outside_the_selection_list_it_once_in_related_claims(base, tmp_path, monkeypatch):
    w = world(base, tmp_path / "w", lambda w: run(w, "doc", "label", 2, "--privacy", "shareable", *WHO))
    d, _ = build(w, filter={"document": [1]})
    sides = {r["claim_id"] for r in d["related_claims"]}
    assert sides == {5, 7} and {r["claim_id"] for r in d["evidence_index"]} & sides == set()
    log = {(p["claim_a"], p["claim_b"]): p["outside_selection"] for p in d["restatement_log"]}
    assert log == {(2, 5): [False, True], (4, 7): [False, True]}
    both, _ = build(w)
    assert both["related_claims"] == [] and all(p["outside_selection"] == [False, False] for p in both["restatement_log"])
    # claim_ids go to view.answer in batches of at most BATCH, each side once
    calls = []
    real = view.answer
    monkeypatch.setattr(dataset, "BATCH", 1)
    monkeypatch.setattr(view, "answer", lambda *a, **k: calls.append(k.get("claim_ids")) or real(*a, **k))
    again, _ = build(w, filter={"document": [1]})
    # once on the pin (for the preview's counts) and once on the copy, each side once per connection
    assert sorted(c for x in calls if x for c in x) == [5, 5, 7, 7] and all(len(x) == 1 for x in calls if x)
    assert again["related_claims"] == d["related_claims"]


def test_a_review_citing_an_archived_document_is_withheld_and_listed_with_its_state(base, tmp_path):
    w = world(base, tmp_path / "w", lambda w: run(w, "doc", "restore", 4, *WHO),
              review_cmd("company", 2, 2, "accepted", "ana", "--evidence-doc", 4, "--evidence-page", 1),
              lambda w: run(w, "doc", "archive", 4, *WHO))
    c, _ = build(w, mode="complete")
    s, p = build(w)
    (row,) = [r for r in rows(c, "records") if r["claim_id"] == 2]
    assert (row["evidence_state"], row["label"], row["evidence"]) == ("archived", "private", [])
    assert not [r for r in rows(s, "records") if r["claim_id"] == 2]
    assert p["withheld"]["absent_from_version"] == 1


def test_a_shareable_twin_of_a_private_file_is_withheld_as_same_bytes(base, tmp_path):
    def twin(w):
        conn = store.connect(w / layout.DB_NAME)
        sha = conn.execute("SELECT sha256 FROM document WHERE id = 3").fetchone()[0]
        conn.close()
        src = tmp_path / "beta-meter.csv"
        src.write_bytes((w / "files" / sha[:2] / sha).read_bytes())
        run(w, "doc", "add", src, "--company", "Beta", "--kind", "evidence", "--privacy", "private")

    w = world(base, tmp_path / "w", twin)
    s, p = build(w)
    assert 3 not in {r["document_id"] for r in s["evidence_index"]} and p["withheld"]["same_bytes_private"] >= 1
    assert 3 not in [x["document_id"] for x in s["gap_report"]["documents_checked"]]


def test_a_twin_private_only_by_absence_from_the_version_still_withholds(base, tmp_path):
    """Moka's Q1 ruling: _twins names only the cause; labels.effective decides. A shareable twin added after the build
    is private by rule 1, so document 3 is private by rule 3 and withheld, whatever cause the preview names."""
    w = world(base, tmp_path / "w")
    assert 3 in {r["document_id"] for r in build(w)[0]["evidence_index"]}  # it ships without the twin
    conn = store.connect(w / layout.DB_NAME)
    sha = conn.execute("SELECT sha256 FROM document WHERE id = 3").fetchone()[0]
    conn.close()
    src = tmp_path / "beta-meter.csv"
    src.write_bytes((w / "files" / sha[:2] / sha).read_bytes())
    run(w, "doc", "add", src, "--company", "Beta", "--kind", "evidence", "--privacy", "shareable")
    s, p = build(w)
    assert 3 not in {r["document_id"] for r in s["evidence_index"]}
    assert 3 not in [x["document_id"] for x in s["gap_report"]["documents_checked"]]
    assert p["withheld"]["same_bytes_private"] >= 1  # document 3's stored label is shareable; its twin is private


# C6: the preview's counts equal the hand counts

def test_the_preview_counts_each_withheld_row_once_under_its_first_cause(base):
    _, p = build(base)
    # complete holds 7 claims of documents 2 and 7, both pairs, their restatement and adjudication rows (the pair
    # 4-7 twice: log and candidates), the candidate and two documents_checked rows: 15; the flag on claim 13; one
    # archived and one deleted document. Field causes: the 7 shipped claims (correction fields) and 4 shipped
    # records carry contributor text; the 4 records carry identity.
    assert p["withheld"] == {"private_document": 15, "absent_from_version": 0, "same_bytes_private": 0,
                             "names_private_document": 0, "flag": 1, "archived": 1, "deleted": 1,
                             "selection_recomputed": 0, "contributor_text": 11, "identity": 4}
    assert p["included"]["rows"] == {"evidence_index": 7, "records": 4, "disagreements": 1, "documents_checked": 3,
                                     "extraction_limits": 1}
    assert [x["id"] for x in p["included"]["documents"]] == list(SHAREABLE)
    assert set(p) == {"included", "withheld", "history_mark", "labels_mark", "filter", "lines", "answer"}
    _, cp = build(base, mode="complete")
    assert set(cp["withheld"].values()) == {0} and cp["lines"] == []


# AC 14 (P9): credentials never leave, in either mode

def test_a_credential_in_contributor_text_is_scrubbed_in_both_modes(base, tmp_path):
    key = "sk-" + "A1b2C3d4E5f6G7h8I9j0"
    w = world(base, tmp_path / "w", review_cmd("company", 2, 2, "accepted", "ana", *NOTE, conclusion=f"key {key}"))
    for mode in dataset.MODES:
        d, p = build(w, mode=mode, include=["contributor_text"])
        assert key not in json.dumps(d) and key not in json.dumps(p)
    assert "key [redacted]" in json.dumps(build(w, mode="complete")[0])


# AC 19 and preservation (R3): the build writes nothing, on success and on refusal

def test_the_build_leaves_the_workspace_and_every_version_file_unchanged(base, tmp_path):
    w = world(base, tmp_path / "w", publish=False)
    files = {p.name: p.read_bytes() for p in (w / "published").glob("*.db")}
    before = dump(w)
    for kw in ({}, {"mode": "complete"}, {"include": ["flags"]}, {"filter": {"review": ["disagreement"]}}):
        build(w, **kw)
    for kw in ({"data_version": 1}, {"mode": "x"}, {"filter": {"text": ""}}):
        with pytest.raises(GctError):
            build(w, **kw)
    assert dump(w) == before
    assert {p.name: p.read_bytes() for p in (w / "published").glob("*.db")} == files


def files(root) -> dict:
    """Every file's bytes but SQLite's own -wal and -shm beside workspace.db (a reader may create them; the rows they
    could carry are in dump) and the empty workspace.lock (lock.hold creates it when missing, C-version V2)."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and p.name not in ("workspace.db-wal", "workspace.db-shm", "workspace.lock")}


def unchanged(gct, root, *argv, code=0):
    """gct report preview ARGV on root exits with code and leaves every table row and every file as it was."""
    before = dump(root)
    gc.collect()  # dump's connection is not closed by its with block; its close checkpoints the WAL
    bytes_before = files(root)
    r = gct("report", "preview", *argv, "--workspace", root)
    assert r.code == code, (argv, r.out, r.err)
    assert files(root) == bytes_before, argv
    assert dump(root) == before, argv
    return r


def newer_workspace(base, tmp_path, gct, monkeypatch):
    w = world(base, tmp_path / "newer", publish=False)
    c = sqlite3.connect(w / layout.DB_NAME)
    c.execute("INSERT INTO schema_version (version, applied_at) VALUES (999, 't')")
    c.commit()
    c.close()
    return w


def schema_20(base, tmp_path, gct, monkeypatch):
    w = tmp_path / "w20"  # schema 20 under this code: the upgrade is pending
    for name in layout.SUBDIRS:
        (w / name).mkdir(parents=True)
    c = store.connect(w / layout.DB_NAME)
    store.migrate(c, up_to=20)
    c.close()
    (w / "workspace.lock").touch()
    return w


def no_version(base, tmp_path, gct, monkeypatch):
    gct("workspace", "init", tmp_path / "empty")
    return tmp_path / "empty"


def unfinished_deletion(base, tmp_path, gct, monkeypatch):
    from gct.stages import deletion

    w = world(base, tmp_path / "gone", publish=False)
    real = deletion.WORK["published"]
    monkeypatch.setitem(deletion.WORK, "published", lambda *a: (_ for _ in ()).throw(OSError("held open")))
    conn = store.connect(w / layout.DB_NAME)
    sha = conn.execute("SELECT sha256 FROM document WHERE id = 2").fetchone()[0]
    conn.close()
    assert gct("doc", "delete", 2, "--confirm", sha[:12], *WHO, "--workspace", w).code == 4
    monkeypatch.setitem(deletion.WORK, "published", real)
    return w


def current(base, tmp_path, gct, monkeypatch):
    return world(base, tmp_path / "w", publish=False)


UPGRADE = ("error: This workspace needs an upgrade before a report can be built.\nnext: Run a command that writes, for"
           " example gct publish build: it upgrades the workspace first and records the upgrade in the run log.\n")


@pytest.mark.parametrize("make,argv,code,text", [
    (current, (), 0, None), (current, ("--complete",), 0, None), (current, ("--include", "flags"), 0, None),
    (current, ("--filter", '{"review": ["disagreement"]}'), 0, None),
    (current, ("--data-version", 1), 4, "is no longer the current one"),
    (no_version, (), 4, "no published data version"), (newer_workspace, (), 4, "made by a newer version of gct"),
    (schema_20, (), 4, UPGRADE), (unfinished_deletion, (), 4, "removal did not finish")],
    ids=["sanitised", "complete", "include", "filter", "stale", "no-version", "newer", "schema-20", "deletion"])
def test_report_preview_writes_nothing(base, tmp_path, gct, monkeypatch, make, argv, code, text):
    r = unchanged(gct, make(base, tmp_path, gct, monkeypatch), *argv, code=code)
    assert text is None or (r.err == text if text == UPGRADE else text in r.err)


# AC 13 (AD-19): renderers never read the workspace

FORBIDDEN = ("sqlite3", "gct.workspace", "gct.stages", "gct.evidence", "gct.reports.crops")


def renderer_problems(source: str) -> list[str]:
    out = []
    for n in ast.walk(ast.parse(source)):
        mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""] if isinstance(
            n, ast.ImportFrom) else []
        out += [m for m in mods if any(m == f or m.startswith(f + ".") for f in FORBIDDEN)]
        if isinstance(n, ast.ImportFrom) and n.module in ("gct", "gct.reports"):
            out += [a.name for a in n.names if a.name in ("workspace", "stages", "evidence", "crops")]
        if isinstance(n, ast.Call):
            f = n.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            if name in ("read_bytes", "read_text", "connect", "open_version", "iterdir", "glob", "rglob"):
                out.append(name)
            if name == "open" and not any(isinstance(k.value, ast.Constant) and k.value.value in ("x", "xb")
                                          for k in n.keywords if k.arg == "mode") and not (
                    len(n.args) > 1 and isinstance(n.args[1], ast.Constant) and str(n.args[1].value).startswith("x")):
                out.append("open")
    return out


def test_the_cli_loads_the_web_server_only_for_serve():
    """AC 17 (Moka's re-run of 472434b): FastAPI and uvicorn add about 30 MB to gct report preview's memory."""
    code = "import sys, gct.cli; print(sorted(m for m in ('fastapi', 'uvicorn', 'gct.api.server') if m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={**os.environ, "PYTHONPATH": str(GCT.parent)}).stdout
    assert out.strip() == "[]"


def test_no_renderer_imports_the_workspace_or_reads_a_file():
    for p in sorted((GCT / "reports").glob("render_*.py")):
        assert renderer_problems(p.read_text(encoding="utf-8")) == [], p
    planted = ("import sqlite3\nfrom gct.workspace import store\nfrom gct.reports import crops\n"
               "def write(dataset, reports, folder, crops_):\n    open(folder / 'a.json').read()\n"
               "    (folder / 'b').read_bytes()\n    open(folder / 'ok.json', 'x').write('{}')\n")
    assert sorted(renderer_problems(planted)) == ["crops", "gct.workspace", "open", "read_bytes", "sqlite3"]


# P4: run.command is a fixed vocabulary (a 7.1 AST guard)

def command_problems(sources: dict) -> list[str]:
    """Every runs.run and runs.start call passes a string literal as the command, or a parameter of its function
    whose every call site does (followed through any number of such functions)."""
    funcs, calls = {}, []  # funcs: name -> parameter names; calls: (file, innermost function, callee, owner, Call)

    def visit(path, node, where):
        for n in ast.iter_child_nodes(node):
            if isinstance(n, ast.FunctionDef):
                funcs.setdefault(n.name, [a.arg for a in n.args.args])
                visit(path, n, n.name)
                continue
            if isinstance(n, ast.Call):
                f = n.func
                callee = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else None
                calls.append((path, where, callee, owner, n))
            visit(path, n, where)

    for path, source in sources.items():
        visit(path, ast.parse(source), None)

    def arg(call, fn, i):
        if i < len(call.args):
            return call.args[i]
        return next((k.value for k in call.keywords if k.arg == funcs[fn][i]), None)

    problems, seen = [], set()

    def check(fn, i):
        if (fn, i) in seen:
            return
        seen.add((fn, i))
        for path, where, callee, owner, call in calls:
            runs_call = owner == "runs" or (path.endswith("workspace/runs.py") and owner is None)
            if callee != fn or (fn in ("run", "start") and not runs_call):
                continue
            a = arg(call, fn, i)
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                continue
            if isinstance(a, ast.Name) and where and a.id in funcs.get(where, []):
                check(where, funcs[where].index(a.id))
            else:
                problems.append(f"{path}: {ast.unparse(call)}")

    check("run", 1)
    check("start", 1)
    return problems


def test_every_run_command_is_a_fixed_string():
    sources = {p.relative_to(GCT.parent).as_posix(): p.read_text(encoding="utf-8") for p in sorted(GCT.rglob("*.py"))}
    assert command_problems(sources) == []
    planted = {**sources, "gct/stages/planted.py": "from gct.workspace import runs\n"
                                                    "def go(conn, name):\n    runs.run(conn, f'add {name}')\n"}
    assert command_problems(planted) == ["gct/stages/planted.py: runs.run(conn, f'add {name}')"]


# M1 story 7.6 series-key round 2: a synthetic credential typed into a metric, a unit and a boundary statement
# reaches no report in any format or mode. Before match.py scrubbed ahead of match.unit_text_of, the restatement
# log's unit_family held the unit's token lowercased with its space removed ("printed:bearer<token>").
def test_a_credential_in_a_claim_text_reaches_no_report(tmp_path):
    import leakage
    from test_package import SEEDS, credential_workspace
    from gct.reports import export
    root = tmp_path / "w" / "ws"
    g = credential_workspace(root)
    g("publish", "build")
    for flags in ((), ("--complete",)):
        folder = Path(g("report", "all", "--format", ",".join(sorted(export.FORMATS)), *flags)["folder"])
        assert {p.suffix for p in folder.rglob("*") if p.is_file()} >= {".json", ".xlsx", ".csv", ".pdf"}, flags
        log = json.loads(next(folder.rglob("dataset.json")).read_text(encoding="utf-8"))["restatement_log"]
        assert "printed:redacted" in {r["unit_family"] for r in log}, flags
        assert leakage.found(folder, SEEDS) == {}, flags
