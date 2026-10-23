"""Self-checks of tests/report_fixture.py (story 7.1, section G "Fixture"): the seed shape, where each seed is placed,
which seeds the workspace holds raw, W' (one construction, nothing private) and the private image."""
import ast
import hashlib
import io
import itertools
import json
import re
import sqlite3
from pathlib import Path

import pytest

import report_fixture as f
from gate_fixture import ENERGY, SCOPE_1
from gct.models import redact
from gct.stages import adjudicate, correct, match, restate
from gct.workspace import labels, published, registry

TOKENS = ("document_text", "contributor", "credential", "path", "image", "file_hash")
BOTH, EARLIER = f.BOTH, f.EARLIER


def _build(tmp_path_factory, name, without_private):
    """Build with CRED-ENV-01 set as the value of a configured api_key_env variable for the whole build."""
    tmp = tmp_path_factory.mktemp(name)
    models = tmp / "models.toml"
    models.write_text(f.MODELS)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GCT_MODELS", str(models))
        mp.setenv(f.API_KEY_ENV, f.CRED_ENV)
        redact._names.cache_clear()
        assert redact._names() == (f.API_KEY_ENV,)  # the variable is configured, so scrub reads it live
        root = f.build(tmp / "ws", without_private=without_private)
    redact._names.cache_clear()
    return root


@pytest.fixture(scope="module")
def w(tmp_path_factory):
    return _build(tmp_path_factory, "w", False)


@pytest.fixture(scope="module")
def w2(tmp_path_factory):
    return _build(tmp_path_factory, "w2", True)


def _conn(root):
    conn = sqlite3.connect(root / "workspace.db")
    conn.row_factory = sqlite3.Row
    return conn


def _docs(conn) -> dict:
    """{logical name: document row with its stored privacy and state} (the gate's deleted document left out)."""
    return {d["logical_name"]: d for d in registry.list_documents(conn) if d["state"] != "deleted"}


def _claim(conn, doc_id, metric, period) -> int:
    return conn.execute("SELECT c.id FROM claim c JOIN claim_version v ON v.claim_id = c.id WHERE c.document_id = ?"
                        " AND v.metric_text = ? AND v.period_label = ? ORDER BY v.id LIMIT 1",
                        (doc_id, metric, period)).fetchone()[0]


def _newest(conn, claim) -> int:
    return conn.execute("SELECT MAX(id) FROM claim_version WHERE claim_id = ?", (claim,)).fetchone()[0]


def _bytes(root) -> bytes:
    """Every file of the workspace folder, concatenated (workspace.db and its WAL, originals, readings, versions)."""
    return b"\n".join(p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file())


def test_seeds_have_the_story_shape():
    assert all(set(s) == {"name", "kind", "expect", "value"} for s in f.SEEDS)
    assert {s["kind"] for s in f.SEEDS} == set(TOKENS)
    for s in f.SEEDS:
        assert s["expect"] == ("never" if s["kind"] in ("credential", "path") else "complete_only"), s
    images = [s for s in f.SEEDS if s["kind"] == "image"]
    assert [(s["name"], s["expect"]) for s in images] == [("IMG-PAGE-01", "complete_only"),
                                                          ("IMG-MARKER-01", "complete_only")]
    assert re.fullmatch(r"[0-9a-f]{64}", images[0]["value"]) and images[1]["value"] is None
    assert [s["name"] for s in f.SEEDS if s["value"] is None] == ["IMG-MARKER-01"]
    assert {s["name"] for s in f.SEEDS if s["expect"] == "never"} == {"CRED-ENV-01", "CRED-RUN-01", "CRED-TEXT-01",
                                                                       "PATH-01"}
    assert f.STORED_RAW == frozenset({"CRED-TEXT-01", "PATH-01"})
    for s in f.SEEDS:
        if s["kind"] == "credential":
            assert re.fullmatch(r"sk-[A-Za-z0-9]{20}", s["value"]) and redact.scrub(s["value"]) == redact.MARK
        elif s["kind"] in ("document_text", "contributor"):
            assert re.fullmatch(r"GCT-PRIVATE-CANARY-\d\d", s["value"])
        elif s["kind"] == "file_hash":
            assert re.fullmatch(r"[0-9a-f]{64}", s["value"])
    assert next(s for s in f.SEEDS if s["name"] == "PATH-01")["value"] == f.PATH


def test_seed_names_and_values_have_a_fixed_width_and_none_is_inside_another():
    names = [s["name"] for s in f.SEEDS]
    assert len(set(names)) == len(names) and all(re.fullmatch(r"[A-Z]+(-[A-Z]+)*-\d\d", n) for n in names)
    values = [s["value"] for s in f.SEEDS if s["value"] is not None]
    assert len(set(values)) == len(values)
    for s in values:  # hex digests are exempt from the character rule
        assert re.fullmatch(r"[A-Za-z0-9-]+", s)
    for a, b in itertools.permutations(names, 2):
        assert a not in b, (a, b)
    for a, b in itertools.permutations(values, 2):
        assert a not in b, (a, b)


def test_the_fixture_does_not_import_the_dataset_builder():
    tree = ast.parse(Path(f.__file__).read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {f"{n.module}.{a.name}" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not [m for m in imported if m.startswith(("gct.reports", "gct.reports.dataset"))]


def test_only_stored_raw_and_the_stored_kinds_are_found_raw_in_the_workspace(w):
    blob = _bytes(w)
    for s in f.SEEDS:
        if s["value"] is None:
            continue
        stored = s["name"] in f.STORED_RAW or s["kind"] in ("document_text", "contributor", "file_hash")
        assert (s["value"].encode() in blob) == stored, s["name"]


def test_each_document_seed_is_placed_where_the_story_says(w):
    conn = _conn(w)
    docs, eff = _docs(conn), labels.effective(conn)
    pdf, csv, arch, twin = docs[f.NAME], docs["acme-private.csv"], docs[f.ARCHIVED], docs["beta-twin.csv"]
    assert (pdf["company"], pdf["privacy"], pdf["file_type"]) == ("Acme", "private", "pdf")
    assert (csv["company"], csv["privacy"], csv["file_type"]) == ("Acme", "private", "csv")
    # The private PDF's printed metric text, its basis wording and a restatement quote from it.
    assert [r[0] for r in conn.execute("SELECT DISTINCT v.metric_text FROM claim_version v JOIN claim c ON"
                                       " c.id = v.claim_id WHERE c.document_id = ? AND v.metric_text LIKE ?",
                                       (pdf["id"], f"%{f.METRIC}%"))] == [f"{f.METRIC} water reused"]
    (wording, boundary, detail), = conn.execute("SELECT wording, boundary, boundary_detail FROM basis WHERE"
                                                " document_id = ? AND wording LIKE ?", (pdf["id"], f"%{f.BASIS}%"))
    assert (boundary, detail) == ("standalone", None) and wording.startswith("Reporting boundary")
    (doc, quote, binds), = conn.execute(f"SELECT evidence_document_id, evidence_quote, binds FROM ({restate.RECORDS})"
                                        " WHERE evidence_quote LIKE ?", (f"%{f.RESTATED}%",))
    assert doc == pdf["id"] and quote.endswith(f.RESTATED) and binds
    # The private sheet: the metric cell A2, its neighbour B2 (no mapped column) and the value cell C2, which the
    # corrected claim's source check quotes.
    rows = registry.stored_path(w, csv["sha256"]).read_text().splitlines()
    assert rows[1].split(",")[:3] == [f.CELL, f.NEIGHBOUR, f.CELL_TEXT]
    claim = _claim(conn, csv["id"], f.CELL, BOTH[0])
    (reason,), = conn.execute("SELECT s.reason FROM source_match s JOIN evidence_ref e ON e.id = s.evidence_ref_id"
                              " WHERE e.claim_version_id = ? ORDER BY s.id DESC LIMIT 1", (_newest(conn, claim),))
    assert re.fullmatch(rf"cell C2 under mapping #\d+ reads {f.CELL_TEXT}, not the claim's value", reason)
    assert not conn.execute("SELECT 1 FROM claim_note WHERE text LIKE ?", (f"%{f.NEIGHBOUR}%",)).fetchall()
    # The shareable twin: the same bytes under Beta, stored shareable and private by P3 rule 3.
    assert (twin["company"], twin["privacy"], twin["sha256"]) == ("Beta", "shareable", csv["sha256"])
    assert eff[twin["id"]]["label"] == "private"
    # The archived private document: named by a canary, declared by an expected item and cited by a review.
    assert (arch["state"], arch["privacy"]) == ("archived", "private")
    assert conn.execute("SELECT 1 FROM expected_item_document WHERE document_id = ?", (arch["id"],)).fetchall()
    assert conn.execute("SELECT 1 FROM review_company WHERE evidence_document_id = ?", (arch["id"],)).fetchall()
    # The third company: its name a canary, every document private.
    third = [d for d in docs.values() if d["company"] == f.COMPANY]
    assert [d["logical_name"] for d in third] == ["co3-2025.pdf", "co3-2024.pdf"]
    assert all(eff[d["id"]]["label"] == "private" for d in third)
    # File hashes are the stored documents' sha256.
    hashes = {s["name"]: s["value"] for s in f.SEEDS if s["kind"] == "file_hash"}
    assert hashes == {"FILE-PDF-01": pdf["sha256"], "FILE-CSV-01": csv["sha256"], "FILE-PDF-02": arch["sha256"],
                      "FILE-PDF-03": third[0]["sha256"], "FILE-PDF-04": third[1]["sha256"]}
    # The private filter (K11), saved as a view.
    (flt,), = conn.execute("SELECT filter FROM saved_view WHERE name = ?", (f.VIEW,))
    assert json.loads(flt) == {"document": [pdf["id"]], "text": f.METRIC}
    # A shareable claim whose value text is 400 nines (stored value inf).
    (value, text), = conn.execute("SELECT v.value, v.value_text FROM claim_version v JOIN claim c ON c.id = v.claim_id"
                                  " WHERE c.document_id = ?", (docs["beta-meter.csv"]["id"],))
    assert value == float("inf") and text == "9" * 400 and eff[docs["beta-meter.csv"]["id"]]["label"] == "shareable"


def test_each_contributor_and_never_seed_is_placed_where_the_story_says(w):
    conn = _conn(w)
    docs, eff = _docs(conn), labels.effective(conn)
    pdf = docs[f.NAME]
    # kim: name and organisation canaries, two versions, one record on each.
    versions = conn.execute("SELECT id, name, organisation FROM contributor_version WHERE contributor_key = 'kim'"
                            " ORDER BY id").fetchall()
    assert [tuple(v)[1:] for v in versions] == [(f.PERSON, f.ORG_1), (f.PERSON, f.ORG_2)]
    # K1: on a shareable claim the company accepts (conclusion canary, a fake key in its scope), the auditor disputes
    # citing the other company's private PDF, and a flag is raised (rationale canary).
    (cv, scope, conclusion, by), = conn.execute(
        "SELECT claim_version_id, scope, conclusion, contributor_version_id FROM review_company WHERE outcome ="
        " 'accepted' AND conclusion = ?", (f.CONCLUSION,))
    assert f.CRED_TEXT in scope and by == versions[0]["id"]
    claim_doc = conn.execute("SELECT c.document_id, c.company_id FROM claim c JOIN claim_version v ON"
                             " v.claim_id = c.id WHERE v.id = ?", (cv,)).fetchone()
    assert eff[claim_doc[0]]["label"] == "shareable" and docs["beta-balance.pdf"]["id"] == claim_doc[0]
    assert [tuple(r) for r in conn.execute("SELECT outcome, evidence_document_id FROM review_auditor WHERE"
                                           " claim_version_id = ?", (cv,))] == [("disputed", pdf["id"])]
    assert [tuple(r) for r in conn.execute("SELECT decision, rationale FROM reviewer_flag WHERE claim_version_id = ?",
                                           (cv,))] == [("raised", f.FLAG)]
    assert [tuple(r) for r in conn.execute("SELECT note, capacity, contributor_version_id FROM highlight WHERE"
                                           " note = ?", (f.HIGHLIGHT,))] == [
        (f.HIGHLIGHT, f.CAPACITY, versions[1]["id"])]
    assert conn.execute("SELECT COUNT(*) FROM correction WHERE rationale = ?", (f.CORRECTION,)).fetchone()[0] == 1
    # The page-acceptance contributor (K7).
    assert conn.execute("SELECT 1 FROM page_acceptance a JOIN contributor_version c ON c.id = a.contributor_version_id"
                        " WHERE c.name = ?", (f.ACCEPTOR,)).fetchall()
    # PATH-01: the absolute path of the folder add, in the run lines and the selection note.
    (note,), = conn.execute("SELECT message FROM run_event WHERE kind = 'note' AND message LIKE ?", (f"%/{f.PATH}%",))
    (folder,) = json.loads(note.removeprefix("selection: "))["sources"]
    assert folder.startswith("/") and folder.endswith(f"/{f.PATH}")
    assert conn.execute("SELECT 1 FROM run_event WHERE kind = 'item' AND item = ?",
                        (f"{folder}/acme-private.pdf",)).fetchall()
    # CRED-RUN-01: the free-text source of a duplicate add reached the selection note as scrub left it.
    assert conn.execute("SELECT 1 FROM run_event WHERE kind = 'note' AND message LIKE ?",
                        (f'%"source":"copied from {redact.MARK}"%',)).fetchall()


def test_the_p11_records_name_the_private_pdf_and_suppress_a_renewal_in_w(w, w2):
    renewals = {}
    for root in (w, w2):
        conn = _conn(root)
        docs = _docs(conn)
        corrected = _claim(conn, docs["beta-2025.pdf"]["id"], SCOPE_1, BOTH[1])
        energy = _claim(conn, docs["acme-2024.pdf"]["id"], ENERGY, BOTH[1])
        entries = {**correct.re_review(conn, docs["beta-2025.pdf"]["id"]),
                   **correct.re_review(conn, docs["acme-2024.pdf"]["id"])}
        renewals[root] = sorted((c, e["kind"]) for c in (corrected, energy) for e in entries.get(c, []))
    conn = _conn(w)
    pdf = _docs(conn)[f.NAME]["id"]
    assert conn.execute("SELECT 1 FROM review_auditor WHERE evidence_document_id = ? AND evidence_page = 2",
                        (pdf,)).fetchall()
    gate = _docs(conn)["acme-2024.pdf"]["id"]
    assert [tuple(r) for r in conn.execute(f"SELECT a.counter_document_id, {adjudicate.BINDS} FROM adjudication a"
                                           " ORDER BY a.id")] == [(gate, 0), (pdf, 1)]
    assert renewals[w] == []  # suppressed by the records citing the private PDF
    assert [k for _, k in renewals[w2]] == ["adjudication", "auditor review"]


def _waiting(root):
    """{claim name: (state, selected series, [(candidate, decision)] in match.compute's order)} for the four claims
    that wait for review, and {series name: whether a shareable rule point makes it exist}, series named by boundary."""
    conn = _conn(root)
    docs, eff = _docs(conn), labels.effective(conn)
    computed = match.compute(conn, "Acme")
    named = {s["id"]: (s["boundary_detail"] or s["reporting_boundary"]).removeprefix("combining the information of ")
             + (" as printed" if s["unit_family"].startswith("printed:") else "")
             for s in computed["series"].values() if s["metric_key"] == "ghg_scope_1"}
    claims = {"A": ("acme-review.pdf", BOTH[0]), "B": ("acme-review.pdf", BOTH[1]),
              "C": ("acme-review.pdf", EARLIER[0]), "D": ("acme-printed.pdf", EARLIER[0])}
    out = {}
    for key, (name, period) in claims.items():
        c = next(c for c in computed["claims"] if c["claim_id"] == _claim(conn, docs[name]["id"], SCOPE_1, period))
        out[key] = (c["state"], named.get(c["series_id"]), [(named[s], c["decided"][s]) for s in c["candidates"]])
    rule = {named[s["id"]]: any(p["link"] == "rule" and eff[p["document_id"]]["label"] == "shareable"
                                for p in s["points"]) for s in computed["series"].values() if s["id"] in named}
    return out, rule


def test_p_match_waiting_claims_with_private_and_shareable_candidates(w, w2):
    """P-match cells: the selected series removed exposing another linked one (A), a candidate lost leaving no undecided
    one (B), two linked survivors reordered once a private rule point goes (C), ordinary before as-printed (D)."""
    L, N = "linked", "not_linked"
    waiting, rule = _waiting(w)
    assert rule == {"standalone": True, "Acme Labs": False, "Acme Tools": False, "Acme Works": True,
                    "consolidated": True, "Acme Works as printed": True}
    assert waiting == {
        "A": (match.REVIEWED, "Acme Labs", [("standalone", N), ("Acme Labs", L), ("Acme Tools", N),
                                            ("Acme Works", None), ("consolidated", L)]),
        "B": (match.UNCERTAIN, None, [("standalone", N), ("Acme Labs", N), ("Acme Tools", None), ("Acme Works", N),
                                      ("consolidated", N)]),
        "C": (match.REVIEWED, "Acme Works", [("standalone", None), ("Acme Labs", None), ("Acme Tools", None),
                                             ("Acme Works", L), ("consolidated", L)]),
        "D": (match.REVIEWED, "Acme Works", [("Acme Works", L), ("Acme Works as printed", L)])}
    # Acme Works keeps one private and one shareable rule point (the candidate-row rule), and the as-printed series'
    # document comes before the shareable Acme Works report, so only the phase puts the ordinary series first.
    conn = _conn(w)
    docs = _docs(conn)
    works = next(s for s in match.compute(conn, "Acme")["series"].values() if s["boundary_detail"]
                 == "combining the information of Acme Works" and s["unit_family"] == "tco2e")
    assert sorted(p["document_id"] for p in works["points"] if p["link"] == "rule") == [
        docs[f.NAME]["id"], docs["acme-works.pdf"]["id"]]
    assert docs[f.NAME]["id"] < docs["acme-group.pdf"]["id"] < docs["acme-printed.pdf"]["id"] < docs[
        "acme-works.pdf"]["id"]
    # W': without the private PDF, A is reviewed into consolidated, B is not linked, C's survivors are reordered.
    waiting, rule = _waiting(w2)
    assert rule == {"standalone": True, "consolidated": True, "Acme Works": True, "Acme Works as printed": True}
    assert waiting == {
        "A": (match.REVIEWED, "consolidated", [("standalone", N), ("consolidated", L), ("Acme Works", None)]),
        "B": (match.NOT_MATCHABLE, None, [("standalone", N), ("consolidated", N), ("Acme Works", N)]),
        "C": (match.REVIEWED, "consolidated", [("standalone", None), ("consolidated", L), ("Acme Works", L)]),
        "D": (match.REVIEWED, "Acme Works", [("Acme Works", L), ("Acme Works as printed", L)])}


def test_restatement_rows_whose_claims_form_no_pair(w, w2):
    """unpaired_restatements: a shareable row (W and W') and one citing a private document (W only)."""
    for root, expected in ((w, [("acme-2023.pdf", "shareable"), ("co3-2025.pdf", "private")]),
                           (w2, [("acme-2023.pdf", "shareable")])):
        conn = _conn(root)
        eff = labels.effective(conn)
        name = {d["id"]: d["logical_name"] for d in registry.list_documents(conn)}
        of = dict(conn.execute("SELECT id, claim_id FROM claim_version"))
        pairs = {frozenset((p["a"]["claim_id"], p["b"]["claim_id"])) for p in restate.compare(conn)}
        unpaired = [(name[r["evidence_document_id"]], eff[r["evidence_document_id"]]["label"])
                    for r in conn.execute("SELECT * FROM restatement ORDER BY id")
                    if frozenset((of[r["original_version_id"]], of[r["restated_version_id"]])) not in pairs]
        assert unpaired == expected


def test_scenario_2_a_restatement_naming_an_earlier_version_of_its_original(w, w2):
    for root in (w, w2):
        conn = _conn(root)
        docs = _docs(conn)
        original = _claim(conn, docs["acme-2024.pdf"]["id"], SCOPE_1, EARLIER[0])
        restated = _claim(conn, docs["acme-2023.pdf"]["id"], SCOPE_1, EARLIER[0])
        (v1, v2, quote), = conn.execute(
            "SELECT original_version_id, restated_version_id, evidence_quote FROM restatement WHERE"
            " original_version_id IN (SELECT id FROM claim_version WHERE claim_id = ?)", (original,))
        assert v1 != _newest(conn, original) and v2 == _newest(conn, restated) and quote
        assert [r[0] for r in conn.execute("SELECT rationale FROM correction WHERE corrects_version_id = ?",
                                           (v1,))] == [f.CORRECTION]
        assert all(labels.effective(conn)[d]["label"] == "shareable"
                   for d in (docs["acme-2024.pdf"]["id"], docs["acme-2023.pdf"]["id"]))


def test_w_prime_holds_no_private_document_and_no_record_naming_one(w, w2):
    conn2 = _conn(w2)
    eff2 = labels.effective(conn2)
    deleted = {d["id"] for d in registry.list_documents(conn2) if d["state"] == "deleted"}
    shareable = {d for d, e in eff2.items() if e["label"] == "shareable"}
    assert set(eff2) == shareable | deleted and len(deleted) == 1  # the gate's deleted draft, alike in W
    for table in labels.NAMES:
        for row in conn2.execute(f"SELECT * FROM {table}"):
            assert labels.named(conn2, table, row) <= shareable | deleted, (table, dict(row))
    # The third company names no document, so W' keeps it, with no document; every other document seed is absent.
    blob = _bytes(w2)
    assert [s["name"] for s in f.SEEDS if s["kind"] in ("document_text", "file_hash")
            and s["value"].encode() in blob] == ["DOC-COMPANY-01"]
    assert [d["company"] for d in registry.list_documents(conn2) if d["company"] == f.COMPANY] == []
    # One construction: W' holds exactly W's documents that are shareable (P3 workspace-only form), file for file.
    conn = _conn(w)
    eff = labels.effective(conn)

    def held(c, e):
        return sorted((d["company"], d["logical_name"], d["sha256"], d["state"]) for d in registry.list_documents(c)
                      if e[d["id"]]["label"] == "shareable")
    assert held(conn, eff) == held(conn2, eff2)
    # The same with the published version (P3 rules 1 and 2 first, then the same-file rule): the twin is private in W,
    # and no shareable document of W' shares a file with one absent from the version.
    versions = [published.open_version(published.current_version(c, r)[1]) for c, r in ((conn, w), (conn2, w2))]
    assert held(conn, labels.effective(conn, versions[0])) == held(conn2, labels.effective(conn2, versions[1]))
    assert labels.effective(conn, versions[0])[_docs(conn)["beta-twin.csv"]["id"]]["label"] == "private"
    assert {d["logical_name"] for d in _docs(conn).values()} - {d["logical_name"] for d in _docs(conn2).values()} == {
        f.NAME, "acme-private.csv", "beta-twin.csv", f.ARCHIVED, "co3-2025.pdf", "co3-2024.pdf"}


def _pages(path):
    import pypdfium2
    pdf = pypdfium2.PdfDocument(path)
    try:
        return len(pdf)
    finally:
        pdf.close()


def test_the_marker_colour_is_only_on_the_private_image_page_and_its_hash_is_the_seed(w):
    from PIL import Image

    from gct.api.app import _render

    conn = _conn(w)
    pdf = _docs(conn)[f.NAME]
    # The marker lies inside the evidence box of the claim it is drawn behind.
    claim = _claim(conn, pdf["id"], SCOPE_1, BOTH[0])
    (page, boxes), = conn.execute("SELECT page_number, boxes FROM evidence_ref WHERE claim_version_id = ?",
                                  (_newest(conn, claim),))
    (x0, top, x1, bottom), = json.loads(boxes)
    mx0, mtop, mx1, mbottom = f.MARK_BOX
    assert page == f.IMAGE_PAGE and x0 < mx0 < mx1 < x1 and top < mtop < mbottom < bottom
    seed = next(s for s in f.SEEDS if s["name"] == "IMG-PAGE-01")["value"]
    found = []
    for d in registry.list_documents(conn):
        if d["file_type"] != "pdf" or d["state"] == "deleted":
            continue
        original = registry.stored_path(w, d["sha256"])
        for n in range(1, _pages(original) + 1):
            image = Image.open(io.BytesIO(_render(original, n, 1.5))).convert("RGB")
            colours = {c for _, c in image.getcolors(maxcolors=1 << 24)}
            if any(not r == g == b for r, g, b in colours):
                found.append((d["id"], n, f.MARKER in colours, f.OUTLINE in colours))
            if (d["id"], n) == (pdf["id"], f.IMAGE_PAGE):
                assert hashlib.sha256(image.tobytes()).hexdigest() == seed
    assert found == [(pdf["id"], f.IMAGE_PAGE, True, False)]
