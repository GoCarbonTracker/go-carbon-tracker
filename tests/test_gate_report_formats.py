"""The Report-formats gate, 7.1's part (story 7.1 section G (b)): on tests/report_fixture.py, complete-mode rows equal
their rows on the pinned projection field by field after redact.scrub; sanitised rows equal their rows on the reduced
copy with exactly the C7 replacements and withheld markers, and their derived values follow the recomputation rules;
data_version names the file read; the evidence index is E6's selection on both connections; every row carries the
top-level version; coded values are printed words; no GCT-authored string matches the wording guard.

Part B (story 7.7 AC 14): on tests/leakage_fixture.py's outputs through gct report all, per format and never one
format against another, read_back rows and identity against the exported dataset through that format's printed;
no stored code in a printed format and codes beside their words in JSON; the wording guard on each output's own
text. Cited, not repeated (the gate run includes them):
tests/test_export_json.py::test_read_back_has_the_shared_shape;
tests/test_render_sheets.py::test_read_back_has_the_shared_shape, ::test_each_value_rule_is_exercised and
::test_printed_words_never_codes_and_the_guard_passes;
tests/test_render_pdf.py::test_every_row_is_printed_and_read_back and
::test_printed_words_only_and_the_wording_guard;
tests/test_render_page.py::test_read_back_gives_the_datasets_rows_through_printed and
::test_the_wording_guard_on_every_page_with_details_open."""
import hashlib
import json
import re

import pytest

import gate_fixture
import leakage_fixture as lf
from test_gate_privacy_exports import FORMATS, back, build, env, exported, files_of, lwm, module, texts, w  # noqa: F401
from test_gate_tables_graphs import FILTERS
from gct.reports import render_sheets
from gct.models import redact
from gct.reports import dataset, pin
from gct.stages import adjudicate, correct, match, restate, review, view
from gct.workspace import labels, layout, published, store

GUARD = re.compile(r"verified|assured|certified|compliant|contradiction", re.I)
PSEUDONYM = re.compile(r"^Contributor \d+$")
LEDGERS = {v: k for k, v in dataset.LEDGER_KINDS.items()}


@pytest.fixture(scope="module")
def conns(w, env):
    """(workspace connection, pinned connection, the reduced copy, identity) of the empty filter."""
    conn = store.connect(w / layout.DB_NAME)
    pconn, ident = pin.pin(conn, w)
    rconn = dataset._Build(conn, w, pconn, ident, view.normalise({}), []).reduce()
    yield conn, pconn, rconn, ident
    for c in (rconn, pconn, conn):
        c.close()


def s(x):
    return redact.scrub(x) if isinstance(x, str) else x


def projected(c, table, i):
    return dict(c.execute(f"SELECT * FROM {table} WHERE id = ?", (i,)).fetchone())


CLAIM = {"version_id": "claim_version_id", "document_id": "document_id", "page": "page_number",
         "metric_text": "metric_text", "value_text": "value_text", "unit_text": "unit_text",
         "period_label": "period_label", "period_start": "period_start", "period_end": "period_end",
         "period_state": "period_state", "boundary": "reporting_boundary", "boundary_detail": "boundary_detail",
         "boundary_state": "boundary_state", "claim_state": "claim_state", "match_state": "match_state",
         "match_reason": "match_reason"}
RECORD = {"claim_version_id": "claim_version_id", "binds": "binds", "latest": "latest", "created_at": "created_at",
          "contributor": "contributor_name", "organisation": "contributor_organisation", "capacity": "capacity"}
LEDGER = {"outcome": "outcome", "reviewed_on": "reviewed_on", "scope": "scope", "conclusion": "conclusion",
          "evidence_document_id": "evidence_document_id", "evidence_page": "evidence_page",
          "evidence_note": "evidence_note", "evidence_state": "evidence_state"}
RESTATEMENT = {"original_version_id": "original_version_id", "restated_version_id": "restated_version_id",
               "decision": "decision", "evidence_document_id": "evidence_document_id", "evidence_page": "evidence_page",
               "evidence_quote": "evidence_quote", "binds": "binds", "contributor": "contributor_name",
               "organisation": "contributor_organisation", "capacity": "capacity", "rationale": "rationale",
               "created_at": "created_at"}
ADJUDICATION = {"low_version_id": "low_version_id", "high_version_id": "high_version_id", "binds": "binds",
                "counter_document_id": "counter_document_id", "counter_page": "counter_page",
                "counter_note": "counter_note", "rationale": "rationale", "procedure": "procedure",
                "follow_up": "follow_up", "closure_reason": "closure_reason", "contributor": "contributor_name",
                "organisation": "contributor_organisation", "capacity": "capacity", "created_at": "created_at"}


def check(row, src, fields, sanitised):
    """Each field equals its projected column after scrub; in sanitised mode a withheld field is null and named, and
    a contributor is a pseudonym."""
    if sanitised:  # C7: every identity and contributor-text field of the row is withheld (no inclusion class given)
        assert {k for k in fields if k in labels.CONTRIBUTOR_TEXT | labels.IDENTITY} <= set(row["withheld"]), row
    for key, col in fields.items():
        want = src[col]
        want = bool(want) if key in ("binds", "latest") else s(want)
        if sanitised and key in row["withheld"]:
            assert row[key] is None, key
        elif sanitised and key == "contributor":
            assert PSEUDONYM.match(row[key]), row[key]
        else:
            assert row[key] == want, (key, row[key], want)


def rows_of(d):
    for r in d["evidence_index"] + d["related_claims"]:
        yield "claim", r
        for x in r["records"]["rows"]:
            yield "record", x
    for p in d["restatement_log"] + d["gap_report"]["candidates"]:
        for x in p["restatements"]["rows"]:
            yield "restatement", x
        for x in p["adjudications"]["rows"]:
            yield "adjudication", x
    for x in d["unpaired_restatements"]["rows"]:
        yield "restatement", x


@pytest.mark.parametrize("mode", dataset.MODES)
def test_every_row_equals_its_projected_row(w, env, conns, mode):
    """Complete: the pinned projection. Sanitised: the reduced copy (C5a, P11)."""
    _, pconn, rconn, _ = conns
    src = pconn if mode == "complete" else rconn
    d, _ = build(w, mode=mode)
    seen = set()
    for kind, r in rows_of(d):
        seen.add(kind)
        if kind == "claim":
            c = projected(src, "claim", r["claim_id"])
            check(r, c, {k: v for k, v in CLAIM.items() if k != "page" or r["sheet"] is None}, mode == "sanitised")
            assert r["sheet"] is None or r["page"] is None  # C3a: one of the two forms
            assert r["value"] == (c["value"] if c["value"] is None or abs(c["value"]) != float("inf") else None)
            assert r["needs_renewed_review"] == [correct.entry_text(e) for e in json.loads(c["needs_re_review"])]
        elif kind == "record":
            t = LEDGERS[r["kind"]]
            x = projected(src, t, r["id"])
            extra = LEDGER if t.startswith("review_") else {"note": "note"} if t == "highlight" else {
                "decision": "decision", "rationale": "rationale"}
            check(r, x, {**RECORD, **extra}, mode == "sanitised")
        elif kind == "restatement":
            check(r, projected(src, "restatement", r["restatement_id"]), RESTATEMENT, mode == "sanitised")
        else:
            x = projected(src, "adjudication", r["adjudication_id"])
            check(r, x, ADJUDICATION, mode == "sanitised")
            assert r["state_text"] == adjudicate.STATES[x["state"]]
    assert seen == {"claim", "record", "restatement", "adjudication"}
    for doc in d["documents"]:
        if doc["state"] == "active":
            x = projected(src, "document", doc["id"])
            assert (doc["name"], doc["version"], doc["kind"], doc["file_type"]) == (
                s(x["logical_name"]), x["version"], x["kind"], x["file_type"])


@pytest.mark.parametrize("flt", [{}, {"document": [1]}], ids=["all", "document 1"])
@pytest.mark.parametrize("mode", dataset.MODES)
def test_every_pair_row_equals_its_projected_comparison_and_series(w, env, mode, flt):
    """C3b source fields of every restatement_log and gap_report.candidates row against the comparison and series rows
    (the pin in complete mode, the reduced copy in sanitised mode), both period dates included; every comparison of
    the source with a selected side is a pair row, and the candidates are the unresolved pairs. Document 1's pairs
    have sides outside the selection."""
    conn = store.connect(w / layout.DB_NAME)
    pconn, ident = pin.pin(conn, w)
    src = pconn if mode == "complete" else dataset._Build(conn, w, pconn, ident, view.normalise(flt), []).reduce()
    d, _ = build(w, mode=mode, filter=flt)
    selected = {r["claim_id"] for r in d["evidence_index"]}
    comparisons = {}
    for x in src.execute("SELECT * FROM comparison"):
        if {x["claim_a"], x["claim_b"]} & selected:
            comparisons.setdefault((x["series_id"], x["claim_a"], x["claim_b"]), []).append(dict(x))
    series = {s["id"]: dict(s) for s in src.execute("SELECT * FROM series")}
    for c in {src, pconn, conn}:
        c.close()
    assert all(len(v) == 1 for v in comparisons.values())
    sides = selected | {r["claim_id"] for r in d["related_claims"]}
    log = d["restatement_log"]
    assert len(log) == len(comparisons) and log
    assert any(any(p["outside_selection"]) for p in log) == bool(flt)
    for p in log + d["gap_report"]["candidates"]:
        (x,) = comparisons[p["series_id"], p["claim_a"], p["claim_b"]]
        s = series[x["series_id"]]
        assert (p["period_start"], p["period_end"], p["state"], p["reason"]) == (
            x["period_start"], x["period_end"], x["state"], x["reason"]), p["id"]
        assert (p["metric_key"], p["reporting_boundary"], p["unit_family"]) == (
            s["metric_key"], s["reporting_boundary"], s["unit_family"]), p["id"]
        assert {p["claim_a"], p["claim_b"]} <= sides
        assert p["outside_selection"] == [p["claim_a"] not in selected, p["claim_b"] not in selected]
    key = lambda p: {k: v for k, v in p.items() if k != "id"}  # noqa: E731 (candidates are rows of their own)
    assert [key(p) for p in d["gap_report"]["candidates"]] == [key(p) for p in log if p["state"] == restate.UNRESOLVED]


def test_sanitised_derived_values_follow_their_rules(w, env, conns):
    """review_text, the disagreement and latest from the shipped records; pair state, reason and shown_state from the
    copy's comparison rows and shipped adjudications (C5a, P10)."""
    _, _, rconn, _ = conns
    d, _ = build(w)
    for r in d["evidence_index"] + d["related_claims"]:
        recs = r["records"]["rows"]
        on = [x for x in recs if x["claim_version_id"] == r["version_id"]]
        pos = {k: [o for o in review.OUTCOMES if any(x["latest"] and x["kind"] == k and x["outcome"] == o for x in on)]
               for k in ("company confirmation", "auditor review")}
        co, au = pos["company confirmation"], pos["auditor review"]
        rv = {"company": co, "auditor": au, "disagreement": {"company": co, "auditor": au} if co and au and co != au
              else None, "flags_raised": 0, "highlights": sum(x["kind"] == "highlight" for x in on),
              "needs_re_review": len(r["needs_renewed_review"]), "corrected": r["correction"] is not None,
              "adjudications": []}
        assert r["review_text"] == view.review_text(rv), r["claim_id"]
        for x in recs:  # latest: the newest shipped row per contributor and claim version, on the copy
            assert x["latest"] == bool(projected(rconn, LEDGERS[x["kind"]], x["id"])["latest"])
        want = [review.disagreement_line(v, {"company": c, "auditor": a}) for v in sorted({x["claim_version_id"] for x in recs})
                for c, a in [[[o for o in review.OUTCOMES if any(x["latest"] and x["kind"] == k and x["outcome"] == o
                                                                  and x["claim_version_id"] == v for x in recs)]
                              for k in ("company confirmation", "auditor review")]] if c and a and c != a]
        assert [x["text"] for x in r["disagreements"]["rows"]] == want
    pairs = {(p["series_id"], p["claim_a"], p["claim_b"]): p for p in rconn.execute("SELECT * FROM comparison")}
    for p in d["restatement_log"]:
        x = pairs[p["series_id"], p["claim_a"], p["claim_b"]]
        assert (p["state"], p["reason"]) == (x["state"], x["reason"])
        ads = [{"binds": a["binds"], "state": projected(rconn, "adjudication", a["adjudication_id"])["state"]}
               for a in p["adjudications"]["rows"]]
        assert p["shown_state"] == (adjudicate._shown(ads) if p["state"] == restate.UNRESOLVED else None)


def test_the_version_is_the_file_read_and_every_row_carries_it(w, env):
    for mode in dataset.MODES:
        d, _ = build(w, mode=mode)
        path = published.version_path(w, d["data_version"]["version"])
        assert d["data_version"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        v = d["data_version"]["version"]

        def walk(x):
            if isinstance(x, dict):
                if "label" in x and "withheld" in x:
                    assert x["data_version"] == v
                for y in x.values():
                    walk(y)
            elif isinstance(x, list):
                for y in x:
                    walk(y)

        walk({k: d[k] for k in ("documents", "evidence_index", "related_claims", "restatement_log",
                                "unpaired_restatements", "gap_report")})


@pytest.mark.parametrize("flt", FILTERS, ids=[json.dumps(x) for x in FILTERS])
def test_the_evidence_index_is_e6s_selection_on_each_connection(w, env, flt):
    conn = store.connect(w / layout.DB_NAME)
    pconn, ident = pin.pin(conn, w)
    rconn = dataset._Build(conn, w, pconn, ident, view.normalise(flt), []).reduce()
    want = {"complete": view.select(pconn, flt), "sanitised": view.select(rconn, flt)}
    for c in (rconn, pconn, conn):
        c.close()
    for mode, ids in want.items():
        assert sorted(r["claim_id"] for r in build(w, mode=mode, filter=flt)[0]["evidence_index"]) == ids, mode


CODED = {"kind": set(dataset.LEDGER_KINDS.values()), "claim_state": set(correct.STATES.values()),
         "match_state": set(match.STATES), "state_text": set(adjudicate.STATES.values())}


@pytest.mark.parametrize("mode", dataset.MODES)
def test_coded_values_are_words_and_no_gct_string_matches_the_wording_guard(w, env, mode):
    d, _ = build(w, mode=mode, include=dataset.INCLUDE)
    contributed = labels.CONTRIBUTOR_TEXT | labels.IDENTITY | {"contributor"}
    hits = []

    def walk(x, key=None):
        if isinstance(x, dict):
            for k, y in x.items():
                # kind is a record kind on a records row only (documents and evidence entries have their own kinds)
                if k in CODED and y is not None and key not in ("headings", "columns") and (k != "kind" or "latest" in x):
                    assert y in CODED[k], (k, y)
                if k not in contributed and not (key and f"{key}.{k}" in contributed):
                    walk(y, k)
        elif isinstance(x, list):
            for y in x:
                walk(y, key)
        elif isinstance(x, str) and GUARD.search(x):
            hits.append((key, x))

    walk(d)
    for p in d["restatement_log"]:
        assert p["state"] in restate.STATES
    assert hits == []


# Part B (story 7.7 AC 14): each format's output of tests/leakage_fixture.py read back against its own dataset, never
# one format against another (lwm: both modes through gct report all, and the dataset each export holds)

def source_rows(d, table) -> list:
    t = table.split(".")[-1]
    return d[t] if t in d else d["gap_report"][t]


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("mode", dataset.MODES)
def test_each_format_reads_back_its_datasets_rows_and_identity(lwm, mode, fmt):
    """Per format: read_back rows equal the dataset's rows mapped through that format's printed (JSON's the
    identity), every table the format holds (PDF leaves an empty one out); every file's identity is the mode's full
    identity (V3: sanitised {version, built_at, sha256, projection_schema}, complete adding history_mark and
    labels_mark, K2, K13) as the format prints it; every row's data version is a column (K15)."""
    d, m = exported(lwm, mode), module(fmt)
    dotted = getattr(m, "dotted", render_sheets.dotted)
    got = back(fmt, lwm[mode])
    keys = {"version", "built_at", "sha256", "projection_schema"} | (
        {"history_mark", "labels_mark"} if mode == "complete" else set())
    assert set(d["data_version"]) == keys
    for ident in got["data_version"]:
        assert ident == {k: m.printed(v, {"withheld": []}, k, fmt) for k, v in d["data_version"].items()}, fmt
    tables = ["evidence_index", "restatement_log", *(f"gap_report.{s}" for s in d["gap_report"])]
    assert list(got["rows"]) == [t for t in tables if fmt != "pdf" or source_rows(d, t)]
    for t, rows in got["rows"].items():
        cols = d["columns"][t.split(".")[-1]]
        assert "data_version" in {c["key"] for c in cols}
        assert rows == [{c["key"]: m.printed(dotted(r, c["key"]), r, c["key"], fmt) for c in cols}
                        for r in source_rows(d, t)], (fmt, t)


CODES = {k: v for k, v in {**adjudicate.STATES, **dataset.LEDGER_KINDS}.items() if k != v}  # stored code: words


@pytest.mark.parametrize("mode", dataset.MODES)
def test_printed_formats_show_no_stored_code_and_json_holds_codes_beside_their_words(lwm, mode):
    """Codes and words (C3): the adjudication and ledger states are held as their words (state_text, kind), never
    as a stored code, in the JSON export outside words and columns, and in the text of every printed format; their
    words print in each (the check can fail: the fixture holds an explained-difference adjudication and every
    ledger kind)."""
    d = exported(lwm, mode)
    body = {k: v for k, v in d.items() if k not in ("words", "columns")}
    values = {v for _, v in walk_items(body) if isinstance(v, str)}
    assert not values & set(CODES), (mode, values & set(CODES))
    shown = {v for k, v in walk_items(body) if k in ("state_text", "kind") and v in CODES.values()}
    assert len(shown) > 2 and (mode == "sanitised" or adjudicate.STATES["explained_difference"] in shown), shown
    for fmt in FORMATS[1:]:
        t = texts(files_of(lwm[mode], fmt))
        assert not [c for c in CODES if c in t], (mode, fmt)
        assert all("".join(x.split()) in t for x in shown), (mode, fmt)


def walk_items(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, v
            yield from walk_items(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk_items(v)


def contributed(d) -> list[str]:
    """Every string under a labels.DOCUMENT_TEXT, IDENTITY or CONTRIBUTOR_TEXT field (or a contributor name) of a
    dataset, longest first."""
    fields = labels.DOCUMENT_TEXT | labels.IDENTITY | labels.CONTRIBUTOR_TEXT | {"contributor"}
    out = []

    def strings(x):
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            for v in x.values():
                strings(v)
        elif isinstance(x, list):
            for v in x:
                strings(v)

    def walk(x, parent=None):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in fields or f"{parent}.{k}" in fields:
                    strings(v)
                elif k not in ("words", "columns"):
                    walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, parent)

    walk(d)
    return sorted({"".join(s.split()) for s in out if s.strip()}, key=len, reverse=True)


@pytest.mark.parametrize("mode", dataset.MODES)
def test_the_wording_guard_finds_nothing_in_gcts_own_text_of_any_output(lwm, mode):
    """The wording guard (test_review.WORDS plus "contradiction") on each output's text once every DOCUMENT_TEXT,
    IDENTITY and CONTRIBUTOR_TEXT value of its dataset is removed: nothing, in both modes; before removal it finds
    6.1's gate_fixture.VERIFIED and L11's "verified" in every complete output that prints records."""
    d = exported(lwm, mode)
    gone = contributed(d)
    for fmt in FORMATS:
        t = texts(files_of(lwm[mode], fmt))
        if mode == "complete":
            for x in (gate_fixture.VERIFIED, lf.VERIFIED):
                assert "".join(x.split()) in t, (fmt, x)
        for s in gone:
            t = t.replace(s, "")
        assert not GUARD.findall(t), (mode, fmt, sorted({t[max(0, i.start() - 30):i.end() + 30]
                                                         for i in GUARD.finditer(t)})[:5])
