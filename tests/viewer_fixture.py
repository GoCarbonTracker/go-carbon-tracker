"""A workspace for the evidence viewer, with published claims of all four kinds:
matched with a box, cited with no box, unresolved on a page the document does not have, and not checked.

Run from the repo root to make one by hand: python -m tests.viewer_fixture <folder>
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ is not a package: conftest and test_* by name

from conftest import grid, make_pdf  # noqa: E402
from test_extract import PAGE  # noqa: E402
from test_link import hand_claim  # noqa: E402

from gct import cli  # noqa: E402

WATER = grid(72, 200, [200, 80], [20, 20], [["Metric", "FY2023-24"], ["Water withdrawn (kL)", "9,876"]])
PAGES = [PAGE, {"text": [(72, 72, "Our approach to climate"), (72, 100, "This page has no figures.")]},
         {"text": WATER["text"], "lines": WATER["lines"]}]


def gct(*argv) -> None:
    assert cli.main([str(a) for a in argv]) == 0, argv


def claim_without_box(db, doc, page, locator):
    """hand_claim from test_link.py with no box: on a page that was read, gct link makes it cited, no box."""
    claim = db.execute("INSERT INTO claim (company_id, document_id, page_number, locator, created_at)"
                       " VALUES (1, ?, ?, ?, 't')", (doc, page, locator)).lastrowid
    version = db.execute("INSERT INTO claim_version (claim_id, run_id, method, config_version, metric_text, value_text,"
                         " unit_text, created_at) VALUES (?, 1, 'hand', 'c', 'Renewable share', '42', '%', 't')",
                         (claim,)).lastrowid
    db.execute("INSERT INTO evidence_ref (claim_version_id, document_id, page_number, boxes, created_at)"
               " VALUES (?, ?, ?, NULL, 't')", (version, doc, page))
    db.commit()


def build(folder: str | Path) -> Path:
    """Make the workspace at folder (new or empty) and publish it. Returns its path."""
    root = Path(folder)
    gct("workspace", "init", root)
    w = ("--workspace", root)
    gct("company", "add", "Acme", *w)
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "acme-report.pdf"
        pdf.write_bytes(make_pdf(PAGES))
        gct("doc", "add", pdf, "--company", "Acme", *w)
    gct("read", *w)
    gct("extract", *w)
    db = sqlite3.connect(root / "workspace.db")
    try:
        claim_without_box(db, 1, 2, "no-box")  # becomes cited: no box
        hand_claim(db, 1, 999, "unknown-page")  # becomes unresolved: page not read
        gct("link", *w)
        hand_claim(db, 1, 2, "not-checked")  # added after the link run: no source-match row
    finally:
        db.close()
    gct("publish", "build", *w)
    return root


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m tests.viewer_fixture <folder>")
    print(f"Workspace ready: {build(sys.argv[1])}\nStart the viewer with: gct serve --workspace {sys.argv[1]}")
