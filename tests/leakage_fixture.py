"""The leakage fixture (story 7.7 part B): tests/report_fixture.py's workspace plus, in code and with synthetic documents
only, what 7.1's fixture lacks: L2 (a shareable twin of the private-image PDF), L4 (replaced values of a private claim),
L5 (a source URL), L6 (a deleted private document), L7 (a file in exports/), L8 (an error log and a files/.incoming-*
file), L9 (the workspace and every source under a folder named GCT-LEAK-ROOT-01), L10 (a same-value pair across
labels), L11 ("verified" in an auditor conclusion), L12 (a contributor key typed as a seed), L14 (a shareable
workbook's neighbour cell, a positive literal) and a seed at every document-text and contributor-text field of the
dataset that 7.1's seeds do not reach (AC 13), a gap confirmation among them. build(folder, without_private=True) is
W' for the differential check: every addition that names a private document is left out (L6 too), and the rest runs
the same way. No file of 7.1's or 6.1's fixture changes.

Run from the repo root to make one by hand: python -m tests.leakage_fixture <folder> [--without-private]
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ is not a package

import report_fixture as rf  # noqa: E402
from conftest import make_pdf  # noqa: E402
from gate_fixture import ENERGY, QUOTE, SCOPE_1, SUBSIDIARIES, WHO, gct, page  # noqa: E402
from gct.workspace import layout  # noqa: E402


def leak(n: int) -> str:
    return f"GCT-LEAK-CANARY-{n:02d}"


ROOT = "GCT-LEAK-ROOT-01"  # L9: the folder holding the workspace and the sources
# Document text of private documents (complete_only).
REPLACED_VALUE, REPLACED_UNIT, REPLACED_PERIOD, VALUE, UNIT, PERIOD = (leak(n) for n in range(1, 7))
DETAIL, LEAK_QUOTE, LEAK_NAME, SHEET, HEADER, EXPECTED, EXPECTED_PERIOD, TWIN, BOARD = (leak(n) for n in range(7, 16))
# Contributor text (complete_only), typed on records of private documents, or on a shareable gap confirmation.
SCOPE, EVIDENCE_NOTE, RESTATED_WHY, PROCEDURE, COUNTER_NOTE, FOLLOW_UP, CLOSURE, ADJUDICATED_WHY, GAP_WHY = (
    leak(n) for n in range(21, 30))
# Never in a report output.
URL, GONE_NAME, GONE_METRIC, EXPORTED, LOGGED, INCOMING = (leak(n) for n in range(31, 37))
KEY = leak(38)  # LEAK-37 is ROOT
# Positive literals, never passed to found: they ship in both modes.
NEIGHBOUR = "GCT-SHARED-NEIGHBOUR-14"  # L14
VERIFIED = "figures verified by the site team"  # L11, for the wording guard
PSEUDONYM = "Contributor 1"

SEEDS = rf.SEEDS + [
    *({"name": n, "kind": "document_text", "expect": "complete_only", "value": v} for n, v in (
        ("LEAK-01", REPLACED_VALUE), ("LEAK-02", REPLACED_UNIT), ("LEAK-03", REPLACED_PERIOD), ("LEAK-04", VALUE),
        ("LEAK-05", UNIT), ("LEAK-06", PERIOD), ("LEAK-07", DETAIL), ("LEAK-08", LEAK_QUOTE), ("LEAK-09", LEAK_NAME),
        ("LEAK-10", SHEET), ("LEAK-11", HEADER), ("LEAK-12", EXPECTED), ("LEAK-13", EXPECTED_PERIOD),
        ("LEAK-14", TWIN), ("LEAK-15", BOARD))),
    *({"name": n, "kind": "contributor", "expect": "complete_only", "value": v} for n, v in (
        ("LEAK-21", SCOPE), ("LEAK-22", EVIDENCE_NOTE), ("LEAK-23", RESTATED_WHY), ("LEAK-24", PROCEDURE),
        ("LEAK-25", COUNTER_NOTE), ("LEAK-26", FOLLOW_UP), ("LEAK-27", CLOSURE), ("LEAK-28", ADJUDICATED_WHY),
        ("LEAK-29", GAP_WHY))),
    {"name": "LEAK-31", "kind": "path", "expect": "never", "value": URL},  # L5
    {"name": "LEAK-32", "kind": "document_text", "expect": "never", "value": GONE_NAME},  # L6
    {"name": "LEAK-33", "kind": "document_text", "expect": "never", "value": GONE_METRIC},  # L6
    {"name": "LEAK-34", "kind": "document_text", "expect": "never", "value": EXPORTED},  # L7
    {"name": "LEAK-35", "kind": "path", "expect": "never", "value": LOGGED},  # L8, the error log
    {"name": "LEAK-36", "kind": "document_text", "expect": "never", "value": INCOMING},  # L8, files/.incoming-*
    {"name": "LEAK-37", "kind": "path", "expect": "never", "value": ROOT},  # L9
    {"name": "LEAK-38", "kind": "contributor", "expect": "never", "value": KEY},  # L12
]
# The never seeds stored raw in the source workspace (AC 8). LEAK-32 and LEAK-33 (L6) are proven by the scan before the
# deletion (build(..., delete=False)), since a deleted document's text is gone from the workspace by design.
STORED_RAW = rf.STORED_RAW | {"LEAK-31", "LEAK-34", "LEAK-35", "LEAK-36", "LEAK-37", "LEAK-38"}

# L14: a shareable workbook in the K5 layout; its Note cell is the neighbour of the value cell.
SHARED_CSV = (b"Metric,Note,Value,Unit,Period,Boundary,Company\n"
              + f"Total water recycled,{NEIGHBOUR},55,kL,FY 2024-25,Standalone,Acme\n".encode())
# L10 and L5: a private Beta report printing the shareable beta-2025.pdf's FY 2024-25 Scope 1 figure, same boundary.
BOARD_PDF = make_pdf([page([[SCOPE_1, "tCO2e", "2,000"]], rf.BOTH[:1], boundary=f"Reporting boundary: {SUBSIDIARIES}",
                           lines=[(40, 150, "Board copy.")])])
# The third company's own report: page 1 pairs with its two reports (a restatement, an adjudication, an unpaired
# restatement) and its energy row carries the typed values; page 2 a subsidiary-set boundary.
LEAK_PDF = make_pdf([
    page([[SCOPE_1, "tCO2e", "80", "71"], [ENERGY, "", "900", "800"]], rf.BOTH,
         lines=[(40, 150, f"{QUOTE} {LEAK_QUOTE}")]),
    page([[SCOPE_1, "tCO2e", "300"]], rf.BOTH[:1], boundary=rf._boundary(DETAIL)),
])
# A private workbook whose sheet name (its file stem) and unmapped column heading are seeds.
LEAK_CSV = (f"Metric,Value,Unit,Period,Boundary,Company,{HEADER}\n".encode()
            + f"Total water recycled,40,kL,FY 2024-25,Standalone,{rf.COMPANY},x\n".encode())
# L6: a private report that is published, then deleted.
GONE_PDF = make_pdf([page([[f"{GONE_METRIC} water reused", "kL", "5", "4"]], rf.BOTH)])


def build(folder: str | Path, without_private: bool = False, delete: bool = True) -> Path:
    """Make the workspace at folder/GCT-LEAK-ROOT-01/ws on report_fixture.build, with tempfile.tempdir pointed at
    folder/GCT-LEAK-ROOT-01/tmp while it is built (so 6.1's and 7.1's sources sit under L9 too). delete=False keeps L6
    published, for the scan that proves its seeds before the deletion. Returns the workspace path."""
    base = Path(folder) / ROOT
    (base / "tmp").mkdir(parents=True)
    old, tempfile.tempdir = tempfile.tempdir, str(base / "tmp")
    try:
        root = rf.build(base / "ws", without_private)
        _extend(root, not without_private, delete)
    finally:
        tempfile.tempdir = old
    return root


def _extend(root: Path, private: bool, delete: bool) -> None:
    w = ("--workspace", root)
    kim = ("--as", "kim", "--capacity", rf.CAPACITY)
    docs = {d["logical_name"]: d["id"] for d in gct("doc", "list", *w)["documents"] if d["state"] != "deleted"}
    src = Path(tempfile.mkdtemp())

    def add(name, company, content, *extra):
        (src / name).write_bytes(content)
        docs[name] = gct("doc", "add", src / name, "--company", company, *extra, *w)["items"][0]["document"]["id"]

    add("acme-shared.csv", "Acme", SHARED_CSV, "--kind", "evidence", "--privacy", "shareable")  # L14
    if private:
        add("beta-twin.pdf", "Beta", rf.PRIVATE_PDF, "--name", TWIN, "--privacy", "shareable")  # L2
        add("beta-board.pdf", "Beta", BOARD_PDF, "--name", BOARD, "--source", f"https://example.invalid/{URL}")
        add("co3-leak.pdf", rf.COMPANY, LEAK_PDF, "--name", LEAK_NAME)
        add(f"{SHEET}.csv", rf.COMPANY, LEAK_CSV, "--kind", "evidence")
        add("co3-gone.pdf", rf.COMPANY, GONE_PDF, "--name", GONE_NAME)  # L6
    gct("contributor", "add", KEY, "--name", "Lena", *w)  # L12
    mapping = ("--metric", "Metric", "--value", "Value", "--unit", "Unit", "--period", "Period", "--boundary",
               "Boundary", "--company", "Company", "--year-end", "03-31", "--boundary-is", "standalone", *WHO, *w)
    gct("sheet", "map", docs["acme-shared.csv"], "--sheet", "acme-shared", *mapping)  # Note stays unmapped
    if private:
        gct("sheet", "map", docs[f"{SHEET}.csv"], "--sheet", SHEET, *mapping)
    rf.ready(w)
    ids = {}  # co3-leak.pdf prints Scope 1 FY 2024-25 on two pages, so the page is part of the key
    for name, d in docs.items():
        for c in gct("claims", "list", "--doc", d, *w)["claims"]:
            ids[name, c["metric_text"], c["period_label"], c["page_number"] or 1] = c["id"]

    def newest(claim):
        return gct("claims", "history", claim, *w)["versions"][-1]["id"]

    # L11 by L12: "verified" in an auditor conclusion on a shareable claim, by the contributor whose key is a seed.
    early = ids["acme-2023.pdf", SCOPE_1, rf.EARLIER[0], 1]
    gct("review", "auditor", early, "--version", newest(early), "--outcome", "accepted", "--scope", "Scope 1",
        "--conclusion", VERIFIED, "--evidence-note", "site visit", "--as", KEY, "--capacity", "auditor", *w)
    if private:  # K6: a second review of that claim citing another company's private report
        gct("review", "auditor", early, "--version", newest(early), "--outcome", "accepted", "--scope", "Scope 1",
            "--conclusion", "matches the group figures", "--evidence-doc", docs["co3-leak.pdf"], "--evidence-page", 1,
            *kim, *w)
    # Then a correction, so both reviews need renewing; the entry of the one citing a private report is withheld.
    gct("correct", early, "--value", "991", *WHO, *w)
    # A gap confirmation that ships (7.2's confirmation.* rule on real data): an expected Beta figure missing from a
    # shareable report.
    item = gct("expect", "add", "--company", "Beta", "--metric", "Total water recycled", "--doc",
               docs["beta-2025.pdf"], *w)["expectation"]["id"]
    gct("pages", "accept", "--doc", docs["beta-2025.pdf"], "--pages", 1, "--type", "figures", *WHO, *w)
    gct("gap", "confirm", item, *kim, "--rationale", GAP_WHY, *w)
    # The other two missing states on shareable reports: not found in successfully processed material (unconfirmed,
    # on the accepted pages) and processing incomplete (acme-2023.pdf's figures are not read).
    gct("expect", "add", "--company", "Beta", "--metric", "Total waste generated", "--doc", docs["beta-2025.pdf"], *w)
    gct("expect", "add", "--company", "Acme", "--metric", "Total waste generated", "--doc", docs["acme-2023.pdf"], *w)
    if private:
        leak_ = {p: ids["co3-leak.pdf", SCOPE_1, p, 1] for p in rf.BOTH}
        co3 = (ids["co3-2025.pdf", SCOPE_1, rf.BOTH[0], 1], ids["co3-2024.pdf", SCOPE_1, rf.BOTH[1], 1])
        quote = ("--page", 1, "--quote", f"{QUOTE} {LEAK_QUOTE}", *kim, "--rationale", RESTATED_WHY, *w)
        # An earlier-version restatement on a pair left unresolved, then adjudicated with every text field typed.
        gct("restate", "record", "--original", co3[0], "--restated", leak_[rf.BOTH[0]], *quote)
        gct("correct", leak_[rf.BOTH[0]], "--value", "82", *WHO, *w)
        rf.ready(w)  # the corrected version is matched before it is adjudicated
        gct("adjudicate", "record", leak_[rf.BOTH[0]], co3[0], "--state", "explained-difference", "--procedure",
            PROCEDURE, "--counter-note", COUNTER_NOTE, "--follow-up", FOLLOW_UP, "--closure-reason", CLOSURE, *kim,
            "--rationale", ADJUDICATED_WHY, *w)
        # A restatement whose pair goes once a correction moves one side to another period (unpaired).
        gct("restate", "record", "--original", co3[1], "--restated", leak_[rf.BOTH[1]], *quote)
        gct("correct", leak_[rf.BOTH[1]], "--period-label", "FY 2020-21", *WHO, *w)
        # Typed values on one private claim, and (L4) replaced values on another: corrected twice.
        energy = {p: ids["co3-leak.pdf", ENERGY, p, 1] for p in rf.BOTH}
        gct("correct", energy[rf.BOTH[0]], "--value", VALUE, "--unit", UNIT, "--period-label", PERIOD, *kim,
            "--rationale", rf.CORRECTION, *w)
        gct("correct", energy[rf.BOTH[1]], "--value", REPLACED_VALUE, "--unit", REPLACED_UNIT, "--period-label",
            REPLACED_PERIOD, *WHO, *w)
        gct("correct", energy[rf.BOTH[1]], "--value", "805", "--unit", "GJ", "--period-label", rf.BOTH[1], *WHO, *w)
        sub = ids["co3-leak.pdf", SCOPE_1, rf.BOTH[0], 2]  # the subsidiary-set claim of page 2
        gct("review", "auditor", sub, "--version", newest(sub), "--outcome", "accepted", "--scope", SCOPE,
            "--conclusion", "agrees with the subsidiary table", "--evidence-note", EVIDENCE_NOTE, *kim, *w)
        gct("expect", "add", "--company", rf.COMPANY, "--metric", EXPECTED, "--period", EXPECTED_PERIOD, "--doc",
            docs["co3-leak.pdf"], *w)
    rf.ready(w)
    gct("publish", "build", *w)
    if private and delete:  # L6: published above, deleted, published again
        token = gct("doc", "delete", docs["co3-gone.pdf"], *w, ok=4)["token"]
        gct("doc", "delete", docs["co3-gone.pdf"], "--confirm", token, *WHO, *w)
    gct("publish", "build", *w)  # W and W' build the same number of versions
    (root / "exports").mkdir(exist_ok=True)  # L7: a file the user put in exports/ before any package
    (root / "exports" / "client-notes.txt").write_text(f"sent to the client: {EXPORTED}\n", encoding="utf-8")
    try:  # L8: an error log naming a local path, and a temporary file a failed intake left in files/
        raise OSError(f"cannot read /data/{LOGGED}/report.pdf")
    except OSError:
        layout.write_error_log(root)
    (root / "files" / ".incoming-leak0001").write_text(INCOMING, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3) or sys.argv[2:] not in ([], ["--without-private"]):
        sys.exit("usage: python -m tests.leakage_fixture <folder> [--without-private]")
    print(f"Workspace ready: {build(sys.argv[1], sys.argv[2:] == ['--without-private'])}")
