"""The Tables-and-Graphs gate workspace (story 6.1, section G1), built in code and published. 6.2, 6.3 and 6.4 reuse
build(root) for their browser modes. Two companies; periods of kind fiscal year and as at; a subsidiary-set boundary;
two Acme reports each across two periods with a restatement and an unresolved conflict with an adjudication; a mapped
spreadsheet; both ledgers disagreeing on one claim; a flag; a highlight; a correction that needs renewed review; one
archived and one deleted document. No real report is used.

Run from the repo root to make one by hand: python -m tests.gate_fixture <folder>
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ is not a package: conftest and test_* by name

from conftest import grid, make_pdf  # noqa: E402

from gct import cli  # noqa: E402

FY = "The financial year ended March 31, 2025."
NOTE = "The figures for the previous year have been restated due to reclassification of green attributes."
QUOTE = "The figures for the previous year have been restated"
SUBSIDIARIES = "Report is prepared on a consolidated basis combining the information of Beta Power."
WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked on the page")
SCOPE_1, ENERGY = "Total Scope 1 emissions", "Total energy consumed (A+B+C) (in GJ)"
# Contributor text with a word GCT never uses in its own words (5.1 C5).
VERIFIED = "verified against the meter log"


def page(rows, periods, boundary="Reporting boundary: Report is prepared on a standalone basis.", lines=()) -> dict:
    """A BRSR-shaped page (test_restate.page_of) with period columns wide enough for an "As at" label."""
    t = grid(40, 200, [230, 50] + [130] * len(periods), [20] * (len(rows) + 1), [["Parameter", "Unit", *periods], *rows])
    return {"text": t["text"] + [(40, 80, FY), (40, 100, boundary), *lines], "lines": t["lines"]}


def gct(*argv, ok=0) -> dict:
    """Run one command with --json; its answer. Any other exit code than ok fails the build."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main([str(a) for a in argv] + ["--json"])
    assert code == ok, (argv, out.getvalue())
    return json.loads(out.getvalue())


def build(folder: str | Path) -> Path:
    """Make the workspace at folder (new or empty) and publish it. Returns its path."""
    root = Path(folder)
    gct("workspace", "init", root)
    w = ("--workspace", root)
    for name in ("Acme", "Beta"):
        gct("company", "add", name, *w)
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit", *w)
    gct("contributor", "add", "raj", "--name", "Raj", *w)
    docs = {}
    with tempfile.TemporaryDirectory() as tmp:
        def add(name, company, content, *extra):
            path = Path(tmp) / name
            path.write_bytes(content)
            docs[name] = gct("doc", "add", path, "--company", company, *extra, *w)["items"][0]["document"]["id"]

        both, earlier = ("FY 2024-25", "FY 2023-24"), ("FY 2023-24", "FY 2022-23")
        add("acme-2025.pdf", "Acme", make_pdf([page([[SCOPE_1, "tCO2e", "1,234", "1,100"],
                                                      [ENERGY, "", "5,000", "4,800"]], both, lines=[(40, 150, NOTE)])]))
        add("acme-2024.pdf", "Acme", make_pdf([page([[SCOPE_1, "tCO2e", "1,150", "1,000"],
                                                      [ENERGY, "", "4,900", "4,500"]], earlier)]))
        add("acme-meter.csv", "Acme", b"Metric,Value,Unit,Period,Boundary,Company,Note\n"
                                      b"Total volume of water withdrawal,700,kL,FY 2024-25,Standalone,Acme,\n",
            "--kind", "evidence")
        add("acme-old.pdf", "Acme", make_pdf([page([["Total waste generated (A+B+C)", "t", "300", "250"]], both)]))
        add("acme-draft.pdf", "Acme", make_pdf([page([["Total waste generated (A+B+C)", "t", "310", "260"]], both)]))
        add("beta-2025.pdf", "Beta", make_pdf([page([[SCOPE_1, "tCO2e", "2,000", "1,900"]], both,
                                                    boundary=f"Reporting boundary: {SUBSIDIARIES}")]))
        # Page 2: no metric key, a bare year (period unknown) and no boundary statement covering it.
        add("beta-balance.pdf", "Beta", make_pdf([page([["Total waste generated (A+B+C)", "t", "40", "35"]],
                                                       ("As at March 31, 2025", "As at March 31, 2024")),
                                                  page([["Employees trained", "number", "120"]], ("2025",),
                                                       boundary="")]))
    gct("sheet", "map", docs["acme-meter.csv"], "--sheet", "acme-meter", "--metric", "Metric", "--value", "Value",
        "--unit", "Unit", "--period", "Period", "--boundary", "Boundary", "--company", "Company", "--note", "Note",
        "--year-end", "03-31", "--boundary-is", "standalone", *WHO, *w)
    ready(w, docs["acme-meter.csv"])
    ids = {}
    for name, d in docs.items():
        for c in gct("claims", "list", "--doc", d, *w)["claims"]:
            ids[name, c["metric_text"], c["period_label"]] = c["id"]

    def newest(claim):
        return gct("claims", "history", claim, *w)["versions"][-1]["id"]

    restated, original = ids["acme-2025.pdf", SCOPE_1, "FY 2023-24"], ids["acme-2024.pdf", SCOPE_1, "FY 2023-24"]
    gct("restate", "record", "--original", original, "--restated", restated, "--page", 1, "--quote", QUOTE, *WHO, *w)
    gct("adjudicate", "record", ids["acme-2025.pdf", ENERGY, "FY 2023-24"], ids["acme-2024.pdf", ENERGY, "FY 2023-24"],
        "--state", "explained-difference", "--counter-doc", docs["acme-2024.pdf"], "--counter-page", 1,
        "--procedure", "compared both tables", *WHO, *w)
    s1 = ids["acme-2025.pdf", SCOPE_1, "FY 2024-25"]
    review = ("--scope", "Scope 1, FY 2024-25", "--capacity", "head of sustainability", "--version", newest(s1))
    gct("review", "company", s1, "--outcome", "accepted", "--conclusion", "agrees with our records", "--as", "ana",
        "--evidence-doc", docs["acme-2025.pdf"], "--evidence-page", 1, *review, *w)
    gct("review", "auditor", s1, "--outcome", "disputed", "--conclusion", f"not {VERIFIED}", "--as", "raj",
        "--evidence-note", "meter log, sheet acme-meter, cell B2", *review, *w)
    beta = ids["beta-2025.pdf", SCOPE_1, "FY 2024-25"]
    gct("flag", "raise", beta, "--version", newest(beta), *WHO, *w)
    energy = ids["acme-2025.pdf", ENERGY, "FY 2024-25"]
    gct("highlight", "add", energy, "--version", newest(energy), "--note", "largest energy figure", "--as", "ana",
        "--capacity", "analyst", *w)
    corrected = ids["beta-2025.pdf", SCOPE_1, "FY 2023-24"]
    gct("review", "auditor", corrected, "--version", newest(corrected), "--outcome", "accepted", "--scope", "Scope 1",
        "--conclusion", "agrees", "--as", "raj", "--capacity", "auditor", "--evidence-note", "ledger", *w)
    gct("correct", corrected, "--value", "1,950", *WHO, *w)
    ready(w, docs["acme-meter.csv"])  # the corrected version's period is accepted again (its acceptance was bound to the old version)
    gct("doc", "archive", docs["acme-old.pdf"], *WHO, *w)
    token = gct("doc", "delete", docs["acme-draft.pdf"], *w, ok=4)["token"]
    gct("doc", "delete", docs["acme-draft.pdf"], "--confirm", token, *WHO, *w)
    gct("publish", "build", *w)
    return root


def ready(w, sheet):
    """test_match.ready on this workspace: read, extract, infer, declare page 1 for each boundary statement of a PDF,
    accept every proposed group and match."""
    for step in ("read", "extract", "infer"):
        gct(step, *w)
    for b in gct("infer", "bases", *w)["bases"]:
        if b["kind"] == "reporting_boundary" and b["document"] != sheet:
            gct("infer", "scope", b["id"], "--pages", "1", *WHO, *w)
    gct("infer", *w)
    for g in gct("infer", "groups", "--state", "proposed", *w)["groups"]:
        gct("infer", "accept", g["id"], *WHO, *w)
    gct("match", *w)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m tests.gate_fixture <folder>")
    print(f"Workspace ready: {build(sys.argv[1])}\nStart the viewer with: gct serve --workspace {sys.argv[1]}")
