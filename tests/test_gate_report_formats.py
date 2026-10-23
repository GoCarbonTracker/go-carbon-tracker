"""The Report-formats gate, 7.1's part (story 7.1 section G (b)): on tests/report_fixture.py, complete-mode rows equal
their rows on the pinned projection field by field after redact.scrub; sanitised rows equal their rows on the reduced
copy with exactly the C7 replacements and withheld markers, and their derived values follow the recomputation rules;
data_version names the file read; the evidence index is E6's selection on both connections; every row carries the
top-level version; coded values are printed words; no GCT-authored string matches the wording guard."""
import hashlib
import json
import re

import pytest

from test_gate_privacy_exports import build, env, w  # noqa: F401 (module fixtures: the fixture and its environment)
from test_gate_tables_graphs import FILTERS
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
