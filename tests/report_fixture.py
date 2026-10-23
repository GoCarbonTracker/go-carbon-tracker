"""The report fixture (story 7.1, section G "Fixture"): 6.1's gate workspace (tests/gate_fixture.build) with every
document relabelled shareable, plus private documents, records naming them and the seeds the Privacy-in-exports gate
scans for. build(root, without_private=True) is W' for the differential check: the same operations, minus every
private document, every document P3 rule 3 makes private (the shareable CSV twin) and every record naming one.
No real report is used.

Run from the repo root to make one by hand: python -m tests.report_fixture <folder> [--without-private]
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ is not a package

import gate_fixture  # noqa: E402
from conftest import _esc, make_pdf  # noqa: E402
from gate_fixture import ENERGY, NOTE, QUOTE, SCOPE_1, WHO, gct, page  # noqa: E402


def canary(n: int) -> str:
    return f"GCT-PRIVATE-CANARY-{n:02d}"


METRIC, CELL, RESTATED, NEIGHBOUR, BASIS, NAME = (canary(n) for n in range(1, 7))
PERSON, ORG_1, ORG_2, ACCEPTOR, CELL_TEXT, ARCHIVED, COMPANY = (canary(n) for n in range(7, 14))
CONCLUSION, CAPACITY, HIGHLIGHT, FLAG, CORRECTION = (canary(n) for n in range(14, 19))
PATH = "GCT-PATH-CANARY"
CRED_ENV, CRED_RUN, CRED_TEXT = (f"sk-GCTFAKEKEY{w}0000001" for w in ("ENV", "RUN", "TXT"))
# CRED-ENV-01 is the value of this api_key_env variable; a test sets both with monkeypatch (build never does).
API_KEY_ENV = "GCT_FIXTURE_API_KEY"
MODELS = ('[adapters.fixture]\nprovider = "openai_chat"\nbase_url = "http://127.0.0.1:9/v1"\nmodel = "none"\n'
          f'external = false\npaid = false\napi_key_env = "{API_KEY_ENV}"\n')
VIEW = "private filter"  # the saved view (K11): the private PDF's id and the METRIC text

# The private image: a rectangle in the marker colour behind the private PDF's page 1 Scope 1 FY 2024-25 value, inside
# its evidence box (that claim's box is [324.0, 224.48, 354.02, 236.48]); (x0, top, x1, bottom) from the top-left.
MARKER, OUTLINE = (0, 200, 120), (220, 0, 0)
MARK_BOX = (326, 226, 352, 235)
BOTH, EARLIER = ("FY 2024-25", "FY 2023-24"), ("FY 2022-23", "FY 2021-22")
STANDALONE = "Reporting boundary: Report is prepared on a standalone basis."


def _boundary(detail: str) -> str:
    return f"Reporting boundary: Report is prepared on a consolidated basis combining the information of {detail}."


def _pdf(pages, size=(612, 792)) -> bytes:
    """conftest.make_pdf with one more page key, 'fills' [(x0, top, x1, bottom, (r, g, b))], drawn before the text."""
    w, h = size
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for p in pages:
        ops = [f"q {' '.join(f'{c / 255:.7f}' for c in rgb)} rg {x0} {h - y1} {x1 - x0} {y1 - y0} re f Q"
               for x0, y0, x1, y1, rgb in p.get("fills", [])]
        ops += [f"BT /F1 12 Tf 1 0 0 1 {x} {h - top} Tm ({_esc(s)}) Tj ET" for x, top, s in p.get("text", [])]
        ops += [f"{x0} {h - t0} m {x1} {h - t1} l S" for x0, t0, x1, t1 in p.get("lines", [])]
        stream = "\n".join(ops).encode("latin-1")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Resources << /Font << /F1 3 0 R >> >>"
                    f" /Contents {len(objs)} 0 R >>".encode())
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


# The private PDF (Acme). Page 1 is the private-image page: the canary metric, the restatement line, the basis wording
# canary and the marker; its Scope 1 rows join the shareable standalone series. Pages 2 and 3 make the two
# subsidiary-set series that only private claims make exist, page 4 the first rule point of the Acme Works series,
# which a later shareable report keeps (P-match candidates).
PRIVATE_PDF = _pdf([
    {**page([[SCOPE_1, "tCO2e", "1,240", "1,120"], [f"{METRIC} water reused", "kL", "42", "40"]], BOTH,
            boundary=f"Reporting boundary {BASIS}: Report is prepared on a standalone basis.",
            lines=[(40, 150, f"{QUOTE} {RESTATED}")]),
     "fills": [(*MARK_BOX, MARKER)]},
    page([[SCOPE_1, "tCO2e", "300"]], BOTH[:1], boundary=_boundary("Acme Labs")),
    page([[SCOPE_1, "tCO2e", "200"]], BOTH[:1], boundary=_boundary("Acme Tools")),
    page([[SCOPE_1, "tCO2e", "250"]], BOTH[:1], boundary=_boundary("Acme Works")),
])
IMAGE_PAGE = 1
# Cell C2, the value column, holds a canary; the claim is corrected, so its source check quotes the cell (K5).
PRIVATE_CSV = (b"Metric,Note,Value,Unit,Period,Boundary,Company\n"
               + f"{CELL},{NEIGHBOUR},{CELL_TEXT},kL,FY 2024-25,Standalone,Acme\n".encode())
ARCHIVED_PDF = make_pdf([{"text": [(40, 80, gate_fixture.FY), (40, 120, "Notes to the sustainability statement.")]}])
# The third company: two reports whose FY 2023-24 figures a restatement cites, until a correction moves one side.
COMPANY_PDF = make_pdf([page([[SCOPE_1, "tCO2e", "77", "70"]], BOTH, lines=[(40, 150, NOTE)])])
COMPANY_OLD_PDF = make_pdf([page([[SCOPE_1, "tCO2e", "72"]], BOTH[1:])])
# Shareable: a consolidated series; a report with no boundary statement (its Scope 1 claims wait for review); an
# earlier report whose figures two restatements cite; a sheet with a value of 400 nines; a report printing an unknown
# unit (page 1: an as-printed series, page 2: a claim that waits for review); a later Acme Works report.
GROUP_PDF = make_pdf([page([[SCOPE_1, "tCO2e", "1,500"]], BOTH[:1],
                           boundary="Reporting boundary: Report is prepared on a consolidated basis.")])
REVIEW_PDF = make_pdf([page([[SCOPE_1, "tCO2e", "1,260", "1,130"]], BOTH, boundary=""),
                       page([[SCOPE_1, "tCO2e", "1,050"]], EARLIER[:1], boundary="")])
EARLY_PDF = make_pdf([page([[SCOPE_1, "tCO2e", "990", "900"], [ENERGY, "", "4,400", ""]], EARLIER,
                           lines=[(40, 150, NOTE)])])
PRINTED_PDF = make_pdf([page([[SCOPE_1, "tons eq", "410", "380"]], BOTH, boundary=_boundary("Acme Works")),
                        page([[SCOPE_1, "tons eq", "395"]], EARLIER[:1], boundary=_boundary("Acme Works"))])
WORKS_PDF = make_pdf([page([[SCOPE_1, "tCO2e", "260"]], BOTH[:1], boundary=_boundary("Acme Works"))])
NINES_CSV = (b"Metric,Value,Unit,Period,Boundary,Company\n"
             + b"Total volume of water withdrawal," + b"9" * 400 + b",kL,FY 2024-25,Standalone,Beta\n")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


SEEDS = [
    *({"name": n, "kind": "document_text", "expect": "complete_only", "value": v} for n, v in (
        ("DOC-METRIC-01", METRIC), ("DOC-CELL-01", CELL), ("DOC-QUOTE-01", RESTATED), ("DOC-CELL-02", NEIGHBOUR),
        ("DOC-BASIS-01", BASIS), ("DOC-NAME-01", NAME), ("DOC-REASON-01", CELL_TEXT), ("DOC-NAME-02", ARCHIVED),
        ("DOC-COMPANY-01", COMPANY))),
    *({"name": n, "kind": "contributor", "expect": "complete_only", "value": v} for n, v in (
        ("CON-NAME-01", PERSON), ("CON-ORG-01", ORG_1), ("CON-ORG-02", ORG_2), ("CON-ACCEPT-01", ACCEPTOR),
        ("CON-CONCLUSION-01", CONCLUSION), ("CON-CAPACITY-01", CAPACITY), ("CON-NOTE-01", HIGHLIGHT),
        ("CON-RATIONALE-01", FLAG), ("CON-CORRECTION-01", CORRECTION))),
    {"name": "CRED-ENV-01", "kind": "credential", "expect": "never", "value": CRED_ENV},
    {"name": "CRED-RUN-01", "kind": "credential", "expect": "never", "value": CRED_RUN},
    {"name": "CRED-TEXT-01", "kind": "credential", "expect": "never", "value": CRED_TEXT},
    {"name": "PATH-01", "kind": "path", "expect": "never", "value": PATH},
    # sha256 of the decoded RGB pixels of PRIVATE_PDF page IMAGE_PAGE as gct.api.app._render(original, page, 1.5) draws
    {"name": "IMG-PAGE-01", "kind": "image", "expect": "complete_only",
     "value": "1e8ae69a23a8e44f9c9effbdc5dd2057e67ff743dc3fbeb411b849fb7b1d12ce"},
    {"name": "IMG-MARKER-01", "kind": "image", "expect": "complete_only", "value": None},
    *({"name": n, "kind": "file_hash", "expect": "complete_only", "value": _sha(b)} for n, b in (
        ("FILE-PDF-01", PRIVATE_PDF), ("FILE-CSV-01", PRIVATE_CSV), ("FILE-PDF-02", ARCHIVED_PDF),
        ("FILE-PDF-03", COMPANY_PDF), ("FILE-PDF-04", COMPANY_OLD_PDF))),
]
# The never seeds stored raw in the fixture workspace (7.7 AC 8): CRED-TEXT-01 in a contributor text, PATH-01 in the
# run lines and the selection note. CRED-ENV-01 (environment only) and CRED-RUN-01 (scrubbed when written) never are.
STORED_RAW = frozenset({"CRED-TEXT-01", "PATH-01"})


def ready(w) -> None:
    """gate_fixture.ready for any number of documents: each PDF boundary statement not scoped yet covers its page."""
    for step in ("read", "extract", "infer"):
        gct(step, *w)
    pdfs = {d["id"] for d in gct("doc", "list", *w)["documents"] if d["file_type"] == "pdf"}
    for b in gct("infer", "bases", *w)["bases"]:
        if b["kind"] == "reporting_boundary" and b["document"] in pdfs and b["scope"] is None:
            gct("infer", "scope", b["id"], "--pages", b["page"], *WHO, *w)
    gct("infer", *w)
    for g in gct("infer", "groups", "--state", "proposed", *w)["groups"]:
        gct("infer", "accept", g["id"], *WHO, *w)
    gct("match", *w)


def build(folder: str | Path, without_private: bool = False) -> Path:
    """Make the workspace at folder (new or empty) on gate_fixture.build and publish it. Returns its path."""
    private = not without_private
    root = gate_fixture.build(folder)
    w = ("--workspace", root)
    why = ("--as", "ana", "--capacity", "analyst")
    docs = {}
    for d in gct("doc", "list", *w)["documents"]:
        if d["state"] != "deleted":
            docs[d["logical_name"]] = d["id"]
            gct("doc", "label", d["id"], "--privacy", "shareable", *why, "--rationale", "published report", *w)
    gct("contributor", "add", "kim", "--name", PERSON, "--organisation", ORG_1, *w)
    gct("contributor", "add", "lee", "--name", ACCEPTOR, *w)
    gct("company", "add", COMPANY, *w)  # names no document, so W' has it too (with no document)
    with tempfile.TemporaryDirectory() as tmp:
        def add(name, company, content, *extra, folder=None):
            path = Path(tmp, folder or "", name)
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(content)
            out = gct("doc", "add", path.parent if folder else path, "--company", company, *extra, *w)
            docs[name] = out["items"][0]["document"]["id"]

        share = ("--privacy", "shareable")
        if private:  # added first: its series come before the shareable consolidated one among the candidates
            add("acme-private.pdf", "Acme", PRIVATE_PDF, "--name", NAME, folder=PATH)
        add("acme-group.pdf", "Acme", GROUP_PDF, *share)
        add("acme-review.pdf", "Acme", REVIEW_PDF, *share)
        add("acme-2023.pdf", "Acme", EARLY_PDF, *share)
        add("beta-meter.csv", "Beta", NINES_CSV, "--kind", "evidence", *share)
        add("acme-printed.pdf", "Acme", PRINTED_PDF, *share)
        add("acme-works.pdf", "Acme", WORKS_PDF, *share)  # after acme-printed.pdf and acme-group.pdf
        if private:
            add("acme-private.csv", "Acme", PRIVATE_CSV, "--kind", "evidence")
            add("beta-twin.csv", "Beta", PRIVATE_CSV, "--kind", "evidence", *share)
            add("acme-archived.pdf", "Acme", ARCHIVED_PDF, "--name", ARCHIVED)
            add("co3-2025.pdf", COMPANY, COMPANY_PDF)
            add("co3-2024.pdf", COMPANY, COMPANY_OLD_PDF)
        # A duplicate add: its free-text source reaches only the selection note, which scrub cleans (CRED-RUN-01).
        gct("doc", "add", Path(tmp, "acme-group.pdf"), "--company", "Acme", *share, "--source",
            f"copied from {CRED_RUN}", *w)
    mapping = ("--metric", "Metric", "--value", "Value", "--unit", "Unit", "--period", "Period", "--boundary",
               "Boundary", "--company", "Company", "--year-end", "03-31", "--boundary-is", "standalone", *WHO, *w)
    gct("sheet", "map", docs["beta-meter.csv"], "--sheet", "beta-meter", *mapping)
    if private:
        gct("sheet", "map", docs["acme-private.csv"], "--sheet", "acme-private", *mapping)  # Note stays unmapped
    ready(w)
    ids = {}
    for name, d in docs.items():
        for c in gct("claims", "list", "--doc", d, *w)["claims"]:
            ids[name, c["metric_text"], c["period_label"]] = c["id"]

    def newest(claim):
        return gct("claims", "history", claim, *w)["versions"][-1]["id"]

    def decide(verb, claim, series):
        gct("match", verb, claim, "--series", series, *why, "--rationale", f"{verb} after reading both tables", *w)

    # P-match. Acme's Scope 1 candidate series, in match.compute's creation order in W: standalone (shareable), the
    # subsidiary sets Acme Labs and Acme Tools (private rule points only), Acme Works (first rule point private, kept by
    # acme-works.pdf), consolidated (shareable), and the as-printed Acme Works series of acme-printed.pdf. Without the
    # private PDF, Acme Works comes after consolidated. A claim reviewed into one series cannot be linked to another,
    # so each second link is recorded while the series linked first is archived away.
    # - A (acme-review.pdf, FY 2024-25; boundary unknown): linked to Labs and consolidated, so reviewed into Labs in W
    #   and, with the selected series gone, into consolidated without it.
    # - B (FY 2023-24): not linked to every candidate but Tools, so uncertain in W and not linked without it.
    # - C (FY 2022-23): linked to Works and consolidated, so reviewed into Works in W and, the survivors reordered,
    #   into consolidated without it.
    # - D (acme-printed.pdf page 2; unit unknown, so only Acme Works candidates): linked to the ordinary Works series
    #   and to the as-printed one; ordinary series come first whatever their documents' ids, so D is in Works in both.
    series = {(s["boundary_detail"] or s["reporting_boundary"], s["unit_family"]): s["id"] for s in
              gct("series", "list", "--company", "Acme", "--metric", "ghg_scope_1", *w)["series"]}
    detail = "combining the information of Acme {}".format
    labs, tools, works = (series.get((detail(x), "tco2e")) for x in ("Labs", "Tools", "Works"))  # W' has no Labs, Tools
    standalone, consolidated = series["standalone", "tco2e"], series["consolidated", "tco2e"]
    printed = series[detail("Works"), "printed:tonseq"]
    a, b, c = (ids["acme-review.pdf", SCOPE_1, p] for p in (*BOTH, EARLIER[0]))
    d = ids["acme-printed.pdf", SCOPE_1, EARLIER[0]]
    archive = ("--as", "ana", "--rationale", "taken out for a re-check", *why[2:], *w)
    if private:
        decide("link", a, labs)
        decide("unlink", a, tools)
        decide("unlink", b, labs)
    decide("link", c, works)
    decide("link", d, works)
    if private:
        gct("doc", "archive", docs["acme-private.pdf"], *archive)
    gct("doc", "archive", docs["acme-works.pdf"], *archive)
    decide("link", a, consolidated)
    decide("unlink", a, standalone)
    decide("link", c, consolidated)
    decide("link", d, printed)
    decide("unlink", b, standalone)
    decide("unlink", b, consolidated)
    gct("doc", "restore", docs["acme-works.pdf"], *archive)
    if private:
        gct("doc", "restore", docs["acme-private.pdf"], *archive)
    decide("unlink", b, works)

    # Restatements: one cited from the private PDF (its quote holds a canary); scenario 2, whose original side is
    # corrected afterwards, so the row names an earlier version of the original claim; and two whose claims form no
    # pair once a correction moves one side to another period (unpaired_restatements), one citing a private document.
    if private:
        gct("restate", "record", "--original", ids["acme-2025.pdf", SCOPE_1, BOTH[1]],
            "--restated", ids["acme-private.pdf", SCOPE_1, BOTH[1]], "--page", 1, "--quote", f"{QUOTE} {RESTATED}",
            *WHO, *w)
    early = ids["acme-2024.pdf", SCOPE_1, EARLIER[0]]
    gct("restate", "record", "--original", early, "--restated", ids["acme-2023.pdf", SCOPE_1, EARLIER[0]],
        "--page", 1, "--quote", QUOTE, *WHO, *w)
    gct("correct", early, "--value", "1,005", *why, "--rationale", CORRECTION, *w)
    moved = [(ids["acme-2024.pdf", ENERGY, EARLIER[0]], ids["acme-2023.pdf", ENERGY, EARLIER[0]])]
    if private:
        moved.append((ids["co3-2024.pdf", SCOPE_1, BOTH[1]], ids["co3-2025.pdf", SCOPE_1, BOTH[1]]))
    for original, restated in moved:
        gct("restate", "record", "--original", original, "--restated", restated, "--page", 1, "--quote", QUOTE,
            *WHO, *w)
        gct("correct", restated, "--period-label", EARLIER[1], *WHO, *w)
    # P11 case 2, first half: the gate's adjudication stops binding when one side is corrected.
    gct("correct", ids["acme-2024.pdf", ENERGY, BOTH[1]], "--value", "4,510", *WHO, *w)

    # K1 on a shareable Beta claim: the company accepts, the auditor disputes citing the other company's private PDF,
    # and a flag is raised. The company confirmation carries contributor-text canaries and a fake key (stored raw).
    k1 = ids["beta-balance.pdf", "Total waste generated (A+B+C)", "As at March 31, 2025"]
    review = ("--version", newest(k1), "--date", "2025-06-30")
    gct("review", "company", k1, "--outcome", "accepted", "--scope", f"waste at year end, key {CRED_TEXT}",
        "--conclusion", CONCLUSION, "--as", "kim", "--capacity", "head of sustainability",
        "--evidence-note", "waste register, row 4", *review, *w)
    if private:
        gct("review", "auditor", k1, "--outcome", "disputed", "--scope", "waste at year end", "--conclusion",
            "the group report prints another figure", "--as", "raj", "--capacity", "auditor",
            "--evidence-doc", docs["acme-private.pdf"], "--evidence-page", 1, *review, *w)
    gct("flag", "raise", k1, "--version", newest(k1), "--as", "raj", "--capacity", "auditor", "--rationale", FLAG, *w)
    # A second contributor version of kim, who then highlights a claim.
    gct("contributor", "edit", "kim", "--organisation", ORG_2, *w)
    group = ids["acme-group.pdf", SCOPE_1, BOTH[0]]
    gct("highlight", "add", group, "--version", newest(group), "--note", HIGHLIGHT, "--as", "kim",
        "--capacity", CAPACITY, *w)
    # A page acceptance whose contributor's name is a canary (K7).
    gct("pages", "accept", "--doc", docs["beta-balance.pdf"], "--pages", 1, "--type", "figures", "--as", "lee",
        "--capacity", "analyst", "--rationale", "figures checked by eye", *w)

    if private:
        # The private sheet claim corrected, so its source check quotes cell C2.
        gct("correct", ids["acme-private.csv", CELL, BOTH[0]], "--value", "700", *WHO, *w)
        gct("link", docs["acme-private.csv"], *w)
        # P11 case 1: the gate's corrected claim asks for a renewed auditor review; a review of its newest version that
        # cites the private PDF suppresses that request in W.
        corrected = ids["beta-2025.pdf", SCOPE_1, BOTH[1]]
        gct("review", "auditor", corrected, "--version", newest(corrected), "--outcome", "accepted", "--scope",
            "Scope 1", "--conclusion", "agrees with the group figure", "--as", "raj", "--capacity", "auditor",
            "--evidence-doc", docs["acme-private.pdf"], "--evidence-page", 2, *w)
        # An expected item declaring the archived private document, and a review citing it, both before it is archived.
        gct("expect", "add", "--company", "Acme", "--metric", "Total waste generated",
            "--doc", docs["acme-archived.pdf"], *w)
        energy = ids["acme-2025.pdf", ENERGY, BOTH[0]]
        gct("review", "company", energy, "--version", newest(energy), "--outcome", "accepted", "--scope", "energy",
            "--conclusion", "agrees with the notes", "--as", "ana", "--capacity", "analyst",
            "--evidence-doc", docs["acme-archived.pdf"], "--evidence-page", 1, *w)
        gct("doc", "archive", docs["acme-archived.pdf"], *WHO, *w)
    ready(w)  # the corrected versions are inferred and matched again
    if private:
        # P11 case 2, second half: a binding adjudication with a private counter document over the older one.
        gct("adjudicate", "record", ids["acme-2025.pdf", ENERGY, BOTH[1]], ids["acme-2024.pdf", ENERGY, BOTH[1]],
            "--state", "explained-difference", "--counter-doc", docs["acme-private.pdf"], "--counter-page", 1,
            "--procedure", "compared with the group table", *WHO, *w)
        gct("view", "save", VIEW, "--filter", json.dumps({"document": [docs["acme-private.pdf"]], "text": METRIC}),
            "--as", "ana", *w)
    gct("publish", "build", *w)
    return root



if __name__ == "__main__":
    if len(sys.argv) not in (2, 3) or sys.argv[2:] not in ([], ["--without-private"]):
        sys.exit("usage: python -m tests.report_fixture <folder> [--without-private]")
    print(f"Workspace ready: {build(sys.argv[1], sys.argv[2:] == ['--without-private'])}")
