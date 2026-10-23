"""Regression checks for the Epic 7 privacy review."""
import json
import sqlite3
import unicodedata
from pathlib import Path

from openpyxl import load_workbook

import pytest

import report_fixture as rf
from conftest import make_pdf
from gate_fixture import SCOPE_1, WHO, gct, page
from report_fixture import ready
from test_labels import acme  # noqa: F401
from test_render_page import dotted, printed, read_back
from test_render_pdf import page_texts
from gct.models import redact
from gct.reports import dataset, package, render_page
from gct.workspace import labels, layout, published, store

KEY = "sk-EPIC7SyntheticCredential87290000"
FULLWIDTH = "ｓｋ－EPIC7PdfCredential8729000000"


@pytest.mark.parametrize("mode", dataset.MODES)
@pytest.mark.parametrize("has_shareable", [False, True])
def test_package_preview_scrubs_names_but_keeps_private_details(acme, make_file, mode, has_shareable):
    at = ("--workspace", acme)
    gct("company", "add", "Acme " + KEY, *at)
    if has_shareable:
        gct("doc", "add", make_file("shared.csv", b"Metric,Value\nWater,3\n"), "--company", "Acme",
            "--privacy", "shareable", *at)
    gct("doc", "add", make_file("source.csv", b"Metric,Value\nWater,2\n"), "--company", "Acme " + KEY,
        "--name", "private-" + KEY + ".csv", *at)
    gct("publish", "build", *at)
    conn = store.connect(acme / layout.DB_NAME)
    try:
        p = package.plan(conn, acme, mode)
        assert KEY not in json.dumps(p)
        assert "private-[redacted].csv" in "\n".join(p["lines"])
        assert "Acme" in "\n".join(p["lines"])
        assert p["token"] == package.plan(conn, acme, mode)["token"]
    finally:
        conn.close()


@pytest.mark.parametrize("privacy", ["unknown-label-8729", "", "Shareable", None])
def test_unknown_projected_label_is_private_and_spreads_to_twins(acme, db, make_file, privacy):
    gct("company", "add", "Beta", "--workspace", acme)
    for company in ("Acme", "Beta"):
        gct("doc", "add", make_file("same.pdf"), "--company", company, "--privacy", "shareable",
            "--workspace", acme)
    projection = sqlite3.connect(":memory:")
    projection.execute("CREATE TABLE document (id INTEGER, privacy TEXT)")
    projection.executemany("INSERT INTO document VALUES (?, ?)", [(1, privacy), (2, "shareable")])
    try:
        assert {i: v["label"] for i, v in labels.effective(db, projection).items()} == {1: "private", 2: "private"}
        assert not labels.ships(db, projection, "claim", [2], "sanitised")
    finally:
        projection.close()


@pytest.mark.parametrize("value", [FULLWIDTH, "ｂｅａｒｅｒ tokenwithsixteencharacters", "ｎｖａｐｉ－" + "a" * 24,
                                    "sk-abcdefghijklmnopｑｒｓｔ"])
def test_compatibility_credentials_change_only_the_credential_span(value):
    text = "ﬁ café e\u0301 | " + value + " | ① unchanged"
    assert dataset._scrub(text) == "ﬁ café e\u0301 | [redacted] | ① unchanged"
    clean = "ﬁ café e\u0301 | no credential | ① unchanged"
    assert dataset._scrub(clean) == clean


@pytest.fixture
def small(acme, make_file):
    at = ("--workspace", acme)
    doc = gct("doc", "add", make_file("clean.pdf", make_pdf([
        page([[SCOPE_1, "tCO2e", "55"]], ["FY 2024-25"])])), "--company", "Acme", "--privacy", "shareable",
        *at)["items"][0]["document"]["id"]
    ready(at)
    gct("publish", "build", *at)
    return acme, doc


@pytest.mark.parametrize("mode", dataset.MODES)
def test_fullwidth_credential_is_absent_from_every_final_format(small, mode):
    root, doc = small
    at = ("--workspace", root)
    claim = gct("claims", "list", "--doc", doc, *at)["claims"][0]["id"]
    gct("correct", claim, "--value", FULLWIDTH, *WHO, *at)
    gct("publish", "build", *at)
    flags = ("--complete",) if mode == "complete" else ()
    out = gct("report", "all", "--format", "json,xlsx,csv,pdf,page", *flags, *at)
    folder = Path(out["folder"])
    texts = {}
    for path in folder.rglob("*"):
        if path.suffix in (".json", ".csv", ".html"):
            texts[path.name] = path.read_text()
        elif path.suffix == ".pdf":
            texts[path.name] = "\n".join(page_texts(path))
        elif path.suffix == ".xlsx":
            book = load_workbook(path, read_only=True)
            texts[path.name] = str([r for s in book for r in s.values])
            book.close()
    assert {".json", ".csv", ".html", ".pdf", ".xlsx"} <= {p.suffix for p in folder.rglob("*")}
    for name, text in texts.items():
        assert FULLWIDTH not in text, name
        assert unicodedata.normalize("NFKC", FULLWIDTH) not in unicodedata.normalize("NFKC", text), name
    assert "[redacted]" in texts["evidence-index.pdf"]


def test_page_formats_assertion_rejects_a_formatter_seed(small, tmp_path, monkeypatch):
    root, _ = small
    conn = store.connect(root / layout.DB_NAME)
    try:
        d, _ = dataset.build(conn, root)
    finally:
        conn.close()
    original = render_page._shown
    monkeypatch.setattr(render_page, "_shown", lambda v, r, k, w:
                        original(v, r, k, w) + (rf.METRIC if k == "metric_text" else ""))
    folder = tmp_path / "mutated"
    folder.mkdir()
    render_page.write(d, ["evidence_index"], folder, {})
    back = read_back(folder)["rows"]["evidence_index"]
    expected = [{c["key"]: printed(dotted(r, c["key"]), r, c["key"], "page")
                 for c in d["columns"]["evidence_index"]} for r in d["evidence_index"]]
    assert back != expected


def test_compatibility_scrub_maps_composed_environment_credentials(monkeypatch):
    monkeypatch.setattr(redact, "_names", lambda: ("SYNTHETIC_KEY",))
    monkeypatch.setenv("SYNTHETIC_KEY", "key-é-token")
    assert dataset._scrub("ﬁ | key-e\u0301-token | ①") == "ﬁ | [redacted] | ①"


def test_raw_environment_credentials_still_scrub_beside_normalized_credentials(monkeypatch):
    monkeypatch.setattr(redact, "_names", lambda: ("SYNTHETIC_KEY",))
    monkeypatch.setenv("SYNTHETIC_KEY", "key-e\u0301-token")
    assert dataset._scrub("ﬁ | key-e\u0301-token | ①") == "ﬁ | [redacted] | ①"
    assert dataset._scrub("key-e\u0301-token | " + FULLWIDTH) == "[redacted] | [redacted]"


def test_unknown_projected_label_with_current_shareable_label_never_reaches_renderers(small):
    root, doc = small
    conn = store.connect(root / layout.DB_NAME)
    try:
        _, path = published.current_version(conn, root)
        with sqlite3.connect(path) as projection:
            projection.execute("UPDATE document SET privacy = ? WHERE id = ?", ("unknown-label-8729", doc))
            projection.execute("UPDATE claim SET metric_text = ? WHERE document_id = ?", ("UNKNOWN-ORIGIN-SEED", doc))
        pinned = published.open_version(path)
        try:
            assert labels.effective(conn, pinned)[doc]["label"] == "private"
        finally:
            pinned.close()
    finally:
        conn.close()
    out = gct("report", "all", "--format", "json,xlsx,csv,pdf,page", "--workspace", root)
    d = json.loads((Path(out["folder"]) / "dataset.json").read_text())
    assert d["evidence_index"] == []
    assert "UNKNOWN-ORIGIN-SEED" not in json.dumps(d)
