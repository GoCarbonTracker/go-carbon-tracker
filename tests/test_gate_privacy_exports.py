"""The Privacy-in-exports gate, 7.1's part (story 7.1 section G (a) and (c)): on tests/report_fixture.py, the
sanitised dataset holds no seed, the complete dataset holds exactly the seeds its fields can reach, credentials and
paths are in neither, the preview's counts add up, and sanitised(W) equals sanitised(W') once ids are renumbered in
first-appearance order (K12). The fixture's environment (GCT_MODELS and the api_key_env variable holding CRED-ENV-01)
is set for every build and every output, and store.now is fixed so W and W' write the same times."""
import json
import re
import sqlite3

import pytest

import report_fixture as f
from gct.models import redact
from gct.reports import dataset
from gct.workspace import layout, store

NOW = "2026-10-23T00:00:00+00:00"
FILTERS = [{}, {"review": ["disagreement"]}, {"review": ["needs-re-review"]}, {"comparison": ["unresolved"]},
           {"comparison": ["restatement"]}]


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """Ruling 1 (CRED-ENV-01): the fixture's models file and key variable, as tests/test_report_fixture.py sets them,
    for the whole module (every build and every output)."""
    models = tmp_path_factory.mktemp("models") / "models.toml"
    models.write_text(f.MODELS)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GCT_MODELS", str(models))
        mp.setenv(f.API_KEY_ENV, f.CRED_ENV)
        mp.setattr(store, "now", lambda: NOW)
        redact._names.cache_clear()
        assert redact._names() == (f.API_KEY_ENV,)
        yield
    redact._names.cache_clear()


@pytest.fixture(scope="module")
def w(env, tmp_path_factory):
    return f.build(tmp_path_factory.mktemp("w") / "ws")


@pytest.fixture(scope="module")
def w2(env, tmp_path_factory):
    return f.build(tmp_path_factory.mktemp("w2") / "ws", without_private=True)


def build(root, **kw):
    conn = store.connect(root / layout.DB_NAME)
    try:
        return dataset.build(conn, root, **kw)
    finally:
        conn.close()


def text(d) -> str:
    return json.dumps(d, ensure_ascii=False)


def found(d) -> set:
    """The seeds a dataset holds: a text seed or a hex digest anywhere in its JSON. Image seeds match pixels only,
    and a dataset holds none (C3d)."""
    t = text(d)
    return {s["name"] for s in f.SEEDS if s["kind"] != "image" and s["value"] in t}


# (a): the scan

@pytest.mark.parametrize("include", [(), ("contributor_text", "flags", "identity")])
def test_the_sanitised_dataset_holds_no_seed(w, env, include):
    for flt in FILTERS:
        d, p = build(w, filter=flt, include=include)
        hits = found(d)
        if include:  # the classes restore contributor text and names, never document text, credentials or paths
            hits -= {s["name"] for s in f.SEEDS if s["kind"] == "contributor"}
        assert hits == set(), (flt, hits)
        assert p["history_mark"] not in text(d)  # K2 (labels_mark is a small number; data_version has neither key)
        assert set(d["data_version"]) == {"version", "built_at", "sha256", "projection_schema"}


def test_the_complete_dataset_holds_exactly_its_reachable_seeds(w, env):
    d, _ = build(w, mode="complete")
    shipped = {e["sha256"] for e in d["evidence"]}
    unreachable = {"CON-ACCEPT-01", "DOC-BASIS-01"}  # no dataset field carries them (section G (a))
    want = {s["name"] for s in f.SEEDS if s["expect"] == "complete_only" and s["kind"] in ("document_text", "contributor")
            and s["name"] not in unreachable}
    want |= {s["name"] for s in f.SEEDS if s["kind"] == "file_hash" and s["value"] in shipped}
    assert found(d) == want
    # the scan can fail: each expected kind is there, and the archived document has no evidence entry
    assert {"FILE-PDF-01", "FILE-CSV-01", "FILE-PDF-03", "FILE-PDF-04"} <= want and "FILE-PDF-02" not in want
    assert {"DOC-NAME-02", "DOC-COMPANY-01", "CON-NAME-01", "DOC-REASON-01", "DOC-CELL-02"} <= want


@pytest.mark.parametrize("mode", dataset.MODES)
def test_credentials_and_paths_are_in_neither_mode(w, env, mode):
    for flt in FILTERS:
        d, p = build(w, mode=mode, filter=flt, include=dataset.INCLUDE)
        never = {s["name"] for s in f.SEEDS if s["expect"] == "never"}
        assert not {s["name"] for s in f.SEEDS if s["name"] in never and s["value"] in text(d) + text(p)}, flt
        assert str(w) not in text(d) and "/private/" not in text(d) and "/tmp" not in text(d)


def test_the_preview_counts_match_the_hand_counts(w, env):
    for flt in FILTERS:
        assert set(build(w, mode="complete", filter=flt)[1]["withheld"].values()) == {0}, flt
    _, p = build(w)
    # hand counts (C6): two raised flags (the gate's on beta-2025.pdf, the fixture's K1 flag), two archived documents
    # (the gate's acme-old.pdf, acme-archived.pdf), one deleted document (the gate's draft); the shareable CSV twin's
    # rows, private by P3 rule 3
    assert (p["withheld"]["flag"], p["withheld"]["archived"], p["withheld"]["deleted"]) == (2, 2, 1)
    assert p["withheld"]["same_bytes_private"] >= 1


# (c): the differential check (K12)

ID_KEYS = {
    **dict.fromkeys(("documents", "document_id", "evidence_document_id", "counter_document_id", "document"), "document"),
    **dict.fromkeys(("claim_id", "claim_a", "claim_b", "claims", "original_claim_id", "restated_claim_id"), "claim"),
    **dict.fromkeys(("version_id", "claim_version_id", "original_version_id", "restated_version_id", "low_version_id",
                     "high_version_id", "corrects_version"), "version"),
    **dict.fromkeys(("series_id", "series"), "series"),
    "restatement_id": "restatement", "adjudication_id": "adjudication", "expected_item_id": "expected item",
    "acceptance_id": "acceptance", "gap_confirmation_id": "gap confirmation", "pair_id": "pair",
}
ROW_IDS = {"documents": "document", "evidence_index": "claim", "related_claims": "claim", "restatement_log": "pair",
           "candidates": "pair", "evidence": "evidence", "disagreements": "version", "restatements": "restatement",
           "unpaired_restatements": "restatement", "adjudications": "adjudication", "expectations": "expected item",
           "declared": "document", "documents_checked": "document", "archived": "document", "deleted": "document",
           "accepted": "acceptance", "correction": "correction", "confirmation": "gap confirmation"}
ENTRY = re.compile(r"^(.+?) #(\d+) on version (\d+)(?: with claim (\d+) version (\d+))?$")


def renumber(d: dict) -> dict:
    """The dataset with every id (C3 id fields, and the ids GCT's own sentences carry) replaced by its rank of first
    appearance within its kind, and without data_version and built_at."""
    ranks = {}

    def n(kind, v):
        if v is None:
            return None
        r = ranks.setdefault(kind, {})
        return r.setdefault(v, len(r) + 1)

    def entry(s):
        m = ENTRY.match(s)
        if not m:
            return s
        kind, i, v, c, cv = m.groups()
        ns = kind if kind in ("correction", "adjudication") else ("record", kind)
        out = f"{kind} #{n(ns, int(i))} on version {n('version', int(v))}"
        return out + (f" with claim {n('claim', int(c))} version {n('version', int(cv))}" if c else "")

    def walk(x, table=None):
        if isinstance(x, list):
            return [walk(y, table) for y in x]
        if not isinstance(x, dict):
            return x
        if set(x) == {"id", "title", "rows", "parent_key", "columns"}:  # a sub-table
            return {**x, "rows": [walk(r, x["id"]) for r in x["rows"]]}
        out = {}
        for k, v in x.items():
            if k == "id" and isinstance(v, int):
                kind = ("record", x["kind"]) if table == "records" else ROW_IDS.get(table)
                out[k] = n(kind, v) if kind else v
            elif k in ID_KEYS and not (isinstance(v, (dict, str)) or isinstance(v, list) and v and isinstance(
                    v[0], dict)) or k in ("series_id", "series") and not isinstance(v, (dict, list)) or (
                    k == "series" and isinstance(v, list)):
                out[k] = [n(ID_KEYS[k], i) for i in v] if isinstance(v, list) else n(ID_KEYS[k], v)
            elif k == "evidence" and isinstance(v, list) and all(isinstance(i, int) for i in v):
                out[k] = [n("evidence", i) for i in v]
            elif k == "needs_renewed_review":
                out[k] = [entry(e) for e in v]
            elif k == "text" and table == "disagreements":
                out[k] = re.sub(r"on version (\d+)", lambda m: f"on version {n('version', int(m[1]))}", v)
            elif k == "evidence_text" and isinstance(v, str):
                out[k] = re.sub(r"mapping #(\d+)", lambda m: f"mapping #{n('mapping', int(m[1]))}", v)
            elif k in ("data_version", "built_at") and table is None:
                continue
            else:
                out[k] = walk(v, k if isinstance(v, (list, dict)) else table)
        return out

    return walk(d)


def diff(a, b, path="") -> list[str]:
    if type(a) is not type(b) or not isinstance(a, (dict, list)):
        return [] if a == b else [f"{path}: {a!r} != {b!r}"]
    if isinstance(a, dict):
        return ([f"{path}.{k}: on one side only" for k in sorted(set(a) ^ set(b), key=str)]
                + [x for k in a if k in b for x in diff(a[k], b[k], f"{path}.{k}")])
    if len(a) != len(b):
        return [f"{path}: {len(a)} items != {len(b)}"]
    return [x for i, (p, q) in enumerate(zip(a, b)) for x in diff(p, q, f"{path}[{i}]")]


@pytest.mark.parametrize("flt", FILTERS, ids=[json.dumps(x) for x in FILTERS])
def test_sanitised_w_equals_sanitised_w_prime(w, w2, env, flt):
    a, b = renumber(build(w, filter=flt)[0]), renumber(build(w2, filter=flt)[0])
    assert diff(a, b)[:40] == []


def test_the_differential_filters_depend_on_withheld_records(w, env):
    """B1: each review filter's and the unresolved filter's complete answer differs from its sanitised one (ruling 2:
    the fixture's nearest case for unresolved; the restatement filter's answer depends on no withheld record here)."""
    for flt in FILTERS[1:4]:
        c = {r["claim_id"] for r in build(w, mode="complete", filter=flt)[0]["evidence_index"] if r["label"] == "shareable"}
        s = {r["claim_id"] for r in build(w, filter=flt)[0]["evidence_index"]}
        assert c != s, flt


def test_the_third_company_and_its_canary_are_absent_from_both_sanitised_outputs(w, w2, env):
    """Ruling 3: W' keeps the third company (it names no document); neither sanitised output names it."""
    for root in (w, w2):
        d, _ = build(root)
        assert f.COMPANY not in text(d)
        assert not [x for x in d["documents"] if x["company"] == f.COMPANY]


def p_match_rows(d) -> dict:
    """{(document name, period label): (match state, match reason)} of acme-review.pdf and
    acme-printed.pdf's Scope 1 claims."""
    return {(r["document_name"], r["period_label"]): (r["match_state"], r["match_reason"]) for r in d["evidence_index"]
            if r["document_name"] in ("acme-review.pdf", "acme-printed.pdf") and r["metric_text"] == f.SCOPE_1}


def test_the_p_match_cells_are_recomputed_on_the_copy(w, w2, env):
    """Fixture cells A to D (worker-c-fixture.md): A reviewed into the consolidated series once the selected one is
    gone, B not linked once its only undecided candidate is gone, C into consolidated once the survivors reorder,
    D in the ordinary Works series by phase; each equal to W'."""
    s, s2 = (p_match_rows(build(r)[0]) for r in (w, w2))
    assert s == s2
    assert s["acme-review.pdf", f.BOTH[0]][0] == "reviewed" and s["acme-review.pdf", f.BOTH[1]] == (
        "not matchable", "not linked by review")
    assert s["acme-review.pdf", f.EARLIER[0]][0] == "reviewed" and s["acme-printed.pdf", f.EARLIER[0]][0] == "reviewed"
    c = p_match_rows(build(w, mode="complete")[0])
    assert c["acme-review.pdf", f.BOTH[1]][0] == "uncertain"  # W itself differs: the copy recomputed it


def test_the_reduced_copy_keeps_the_candidate_triggers_and_they_fire(w, env):
    """Moka: projection 16's three triggers survive deserialize on the copy, and dropping a withheld claim's rows
    there removes its candidate rows (and a removed series' rows)."""
    from gct.reports import pin
    from gct.stages import view

    conn = store.connect(w / layout.DB_NAME)
    pconn, ident = pin.pin(conn, w)
    rconn = dataset._Build(conn, w, pconn, ident, view.normalise({}), []).reduce()
    try:
        names = {n for (n,) in rconn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
        assert {"match_candidate_claim", "match_candidate_series", "match_candidate_rule"} <= names
        claims = {c for (c,) in rconn.execute("SELECT id FROM claim")}
        series = {s for (s,) in rconn.execute("SELECT id FROM series")}
        before = pconn.execute("SELECT claim_id, series_id FROM match_candidate").fetchall()
        gone = [r for r in before if r["claim_id"] not in claims or r["series_id"] not in series]
        assert gone  # the fixture's candidates of removed series (cells A to C); no waiting claim is withheld itself
        after = {tuple(r) for r in rconn.execute("SELECT claim_id, series_id FROM match_candidate")}
        assert after == {tuple(r) for r in before} - {tuple(r) for r in gone}
        # The claim trigger on a copy made the same way (C5a step 1), since the fixture withholds no waiting claim.
        copy = sqlite3.connect(":memory:")
        copy.deserialize(pconn.serialize())
        (cid,) = copy.execute("SELECT claim_id FROM match_candidate LIMIT 1").fetchone()
        copy.execute("DELETE FROM claim WHERE id = ?", (cid,))
        assert copy.execute("SELECT COUNT(*) FROM match_candidate WHERE claim_id = ?", (cid,)).fetchone()[0] == 0
        assert copy.execute("SELECT COUNT(*) FROM match_candidate").fetchone()[0] > 0
        copy.close()
    finally:
        for c in (rconn, pconn, conn):
            c.close()


def test_restatement_rows_attach_through_their_claims_in_both_modes(w, w2, env):
    """Scenario 2 (an earlier version, still paired) and the two unpaired rows (one citing a private document)."""
    for mode in dataset.MODES:
        d, _ = build(w, mode=mode)
        earlier = [r for p in d["restatement_log"] for r in p["restatements"]["rows"] if not r["binds"]]
        assert earlier and all(r["earlier"] == dataset.EARLIER for r in earlier), mode
        unpaired = d["unpaired_restatements"]["rows"]
        assert len(unpaired) == (2 if mode == "complete" else 1), mode
    a, b = (renumber(build(r)[0])["unpaired_restatements"] for r in (w, w2))
    assert a == b
