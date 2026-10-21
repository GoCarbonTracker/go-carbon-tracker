"""Restatements (FR19, FR23, FR24, FR38): every pair of points in one same-period set of a series gets exactly one
state, computed on read from match.compute and the restatement records. Only a contributor's record that cites the
line printed on the restated figure's document establishes a restatement. The store never orders reports."""
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

from gct.stages import match
from gct.stages.infer import _who
from gct.stages.missing import _text, page_count
from gct.stages.read import NEWEST_SQL
from gct.workspace import registry, store
from gct.workspace.layout import NOT_FOUND, REFUSED, GctError

SAME, RESTATEMENT, UNRESOLVED, NOT_COMPARED = "same value", "restatement", "unresolved conflict", "not compared"
STATES = (SAME, RESTATEMENT, UNRESOLVED, NOT_COMPARED)
FILTERS = {"same": SAME, "restatement": RESTATEMENT, "unresolved": UNRESOLVED, "not-compared": NOT_COMPARED}
REVIEWED = "reviewed, not comparable"
NO_NUMBER = "no numeric value"
SAME_ROW = "same table row"
PAIRS = "See the pairs with: gct restate list"
# A row binds when both versions it names are their claims' newest versions; only then can it decide a pair.
BINDS = ("(SELECT COUNT(*) FROM claim_version v WHERE v.id IN (r.original_version_id, r.restated_version_id)"
         " AND v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = v.claim_id)) = 2")
RECORDS = f"""
SELECT r.*, c.name, c.organisation, {BINDS} AS binds FROM restatement r
JOIN contributor_version c ON c.id = r.contributor_version_id
"""
CURRENT = RECORDS + " WHERE r.id IN (SELECT MAX(id) FROM restatement GROUP BY original_version_id, restated_version_id)"


def equal(a: float, b: float) -> bool:
    """D3: equal up to float conversion error. No rounding tolerance and no triviality threshold."""
    return abs(a - b) <= 1e-9 * max(abs(a), abs(b))


def _record(r) -> dict:
    return {"id": r["id"], "original_version": r["original_version_id"], "restated_version": r["restated_version_id"],
            "decision": r["decision"], "document": r["evidence_document_id"], "page": r["evidence_page"],
            "quote": r["evidence_quote"], "contributor": r["name"], "organisation": r["organisation"],
            "capacity": r["capacity"], "rationale": r["rationale"], "created_at": r["created_at"]}


def _records(conn) -> dict:
    """{frozenset of two claim version ids: current recorded row}. A withdrawn pair has no entry."""
    return {frozenset((r["original_version_id"], r["restated_version_id"])): _record(r)
            for r in conn.execute(CURRENT) if r["decision"] == "recorded"}


def _state(s: dict, a: dict, b: dict, records: dict) -> tuple[str, str | None, dict | None]:
    """(state, reason, record) of one pair; the first not-compared reason in D1's order wins."""
    if s["unit_family"].startswith("printed:"):
        return NOT_COMPARED, match.AS_PRINTED, None
    if "reviewed" in (a["link"], b["link"]):
        return NOT_COMPARED, REVIEWED, None
    if a["number"] is None or b["number"] is None:
        return NOT_COMPARED, NO_NUMBER, None
    row = match._row(a["locator"])
    if row and (a["document_id"], a["page_number"], row) == (b["document_id"], b["page_number"], match._row(b["locator"])):
        return NOT_COMPARED, SAME_ROW, None
    if equal(a["value_base"], b["value_base"]):
        return SAME, None, None
    record = records.get(frozenset((a["claim_version_id"], b["claim_version_id"])))
    return (RESTATEMENT, None, record) if record else (UNRESOLVED, None, None)


def _pairs(s: dict, points, records: dict) -> list[dict]:
    """The pairs of every same-period set among the points, each set's points ordered by document id (display only)."""
    sets = {}
    for x in points:
        sets.setdefault((x["period_start"], x["period_end"]), []).append(x)
    out = []
    for (start, end), pts in sets.items():
        for a, b in combinations(sorted(pts, key=lambda x: (x["document_id"], x["claim_id"])), 2):
            state, reason, record = _state(s, a, b, records)
            out.append({"series_id": s["id"], "company_id": s["company_id"], "metric_key": s["metric_key"],
                        "label": s["label"], "reporting_boundary": s["reporting_boundary"],
                        "boundary_detail": s["boundary_detail"], "period_start": start, "period_end": end,
                        "state": state, "reason": reason, "restatement": record,
                        "a": {k: v for k, v in a.items() if k != "same_period"},
                        "b": {k: v for k, v in b.items() if k != "same_period"}})
    return out


def pairs(conn, matched: dict) -> list[dict]:
    """Every pair of every same-period set of a match.compute result, with its state."""
    records = _records(conn)
    names = dict(conn.execute("SELECT id, name FROM company"))
    out = [p for s in matched["series"].values() for p in _pairs(s, s["points"], records)]
    for p in out:
        p["company"] = names[p["company_id"]]
    return sorted(out, key=lambda p: (p["company_id"], p["series_id"], p["period_end"], p["period_start"],
                                      p["a"]["claim_id"], p["b"]["claim_id"]))


def compare(conn, company=None) -> list[dict]:
    """The pairs of the active documents (of one company)."""
    return pairs(conn, match.compute(conn, company))


def listed(conn, company=None, state=None) -> tuple[list[dict], int]:
    """(pairs shown, pairs hidden by the state filter). A filter hides rows; it never drops a record."""
    every = compare(conn, company)
    shown = [p for p in every if state is None or p["state"] == FILTERS[state]]
    return shown, len(every) - len(shown)


def counts(conn, company=None) -> dict:
    """{company name: {state: pairs}}."""
    out = {}
    for p in compare(conn, company):
        out.setdefault(p["company"], Counter())[p["state"]] += 1
    return {k: dict(sorted(v.items())) for k, v in out.items()}


def mark(conn, s: dict) -> dict:
    """A series record of match._named with each point given its pairs among the shown points."""
    by = {}
    for p in _pairs(s, s["points"], _records(conn)):
        for x, y in ((p["a"], p["b"]), (p["b"], p["a"])):
            by.setdefault(x["claim_id"], []).append({"claim": y["claim_id"], "state": p["state"], "reason": p["reason"],
                                                     "restatement": p["restatement"] and p["restatement"]["id"]})
    return {**s, "points": [{**x, "pairs": by.get(x["claim_id"], [])} for x in s["points"]]}


# Records: record and withdraw, both under the workspace lock, rows only.

def _claim(conn, claim_id: int):
    row = conn.execute("SELECT c.*, m.name AS company, (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id) AS version"
                       " FROM claim c JOIN company m ON m.id = c.company_id WHERE c.id = ?", (claim_id,)).fetchone()
    if row is None:
        raise GctError(NOT_FOUND, f"There is no claim {claim_id}.", "See the claims with: gct claims list --doc ID")
    return row


def _pair(conn, first: int, second: int) -> dict:
    """The pair of the two claims' newest versions, with the refusals of D4 when there is none."""
    one, two = _claim(conn, first), _claim(conn, second)
    if first == second:
        raise GctError(REFUSED, f"The original and the restated claim are both claim {first}.",
                       "Name two claims of one same-period set. " + PAIRS)
    if one["company"] != two["company"]:
        raise GctError(REFUSED, f"Claims {first} and {second} belong to different companies, so they are in no"
                                " same-period set together.", PAIRS)
    matched = match.compute(conn, one["company"])
    claims = {c["claim_id"]: c for c in matched["claims"]}
    for row in (one, two):
        c = claims.get(row["id"])
        if c is None:
            raise GctError(REFUSED, f"Claim {row['id']} is in document {row['document_id']}, which is not active.", PAIRS)
        if c["claim_state"] != "current":
            raise GctError(REFUSED, f"Claim {row['id']} is {c['claim_state']}, so it is in no series.",
                           f"Run gct extract {row['document_id']} first, or pick a current claim: "
                           f"gct claims list --doc {row['document_id']} --state current")
        if c["reason"] == match.NOT_MAPPED:
            raise GctError(REFUSED, f"Claim {row['id']}'s newest version {row['version']} has not been matched yet.",
                           "Run gct match first.")
    found = next((p for p in pairs(conn, matched) if {p["a"]["claim_id"], p["b"]["claim_id"]} == {first, second}), None)
    if found is None:
        raise GctError(REFUSED, f"Claims {first} and {second} are not in one same-period set of one series.", PAIRS)
    return {**found, "series_key": matched["series"][found["series_id"]]["key"]}


def _current_row(conn, original_version: int, restated_version: int):
    return conn.execute(RECORDS + " WHERE r.original_version_id = ? AND r.restated_version_id = ? ORDER BY r.id DESC"
                                  " LIMIT 1", (original_version, restated_version)).fetchone()


def _words(conn, root, doc_id: int, page: int) -> str:
    """The newest reading of one page as one line: its words in reading order joined by single spaces."""
    row = next((p for p in conn.execute(NEWEST_SQL, (None, None, doc_id)) if p["page_number"] == page), None)
    if row is None:
        raise GctError(REFUSED, f"Page {page} of document {doc_id} has not been read.", f"Read it with: gct read {doc_id}")
    path = conn.execute("SELECT path FROM artifact WHERE id = ?", (row["artifact_id"],)).fetchone()[0]
    reading = json.loads((Path(root) / path).read_text(encoding="utf-8"))
    return " ".join(" ".join(w["text"] for w in reading["words"]).split())


def record(conn, root, original: int, restated: int, page: int, quote, key, capacity, rationale) -> dict:
    """Record that the restated claim's figure restates the original's, citing a line printed on a page of the
    document that prints the restated figure. Only for a pair that is an unresolved conflict now."""
    who, capacity, rationale = _who(conn, key, capacity, rationale)
    quote = " ".join(_text(quote, "quote", '--quote "the line exactly as printed"').split())
    p = _pair(conn, original, restated)
    if p["state"] != UNRESOLVED:
        what = p["state"] + (f" ({p['reason']})" if p["reason"] else "")
        raise GctError(REFUSED, f"Claims {original} and {restated} are {what}, not an unresolved conflict, so there is"
                                " no restatement to record.", PAIRS)
    points = {p["a"]["claim_id"]: p["a"], p["b"]["claim_id"]: p["b"]}
    doc_id = points[restated]["document_id"]
    n, why = page_count(root, registry.show_document(conn, doc_id))
    if n is None or not 1 <= page <= n:
        raise GctError(REFUSED, f"Page {page} is not in document {doc_id}, which prints the restated figure"
                                + (f" and has {n} pages." if n else f" ({why})."),
                       f"Give a page from 1 to {n} of document {doc_id}." if n else "Cite a page of a PDF document.")
    if quote not in _words(conn, root, doc_id, page):
        raise GctError(REFUSED, f"The quote is not printed on page {page} of document {doc_id} as read.",
                       "Copy the line exactly as printed on that page (spacing may differ, case may not).")
    with store.transaction(conn):
        rid = conn.execute(
            "INSERT INTO restatement (original_version_id, restated_version_id, series_key, decision,"
            " evidence_document_id, evidence_page, evidence_quote, contributor_version_id, capacity, rationale,"
            " created_at) VALUES (?, ?, ?, 'recorded', ?, ?, ?, ?, ?, ?, ?)",
            (points[original]["claim_version_id"], points[restated]["claim_version_id"],
             p["series_key"], doc_id, page, quote, who["version"], capacity, rationale, store.now())).lastrowid
    return _done(conn, rid, original, restated)


def _done(conn, rid: int, original: int, restated: int) -> dict:
    """The new row and the pair as computed now (None when the claims no longer form one)."""
    try:
        p = _pair(conn, original, restated)
        p.pop("series_key")
    except GctError:
        p = None
    return {"restatement": _record(conn.execute(RECORDS + " WHERE r.id = ?", (rid,)).fetchone()), "pair": p}


def withdraw(conn, original: int, restated: int, key, capacity, rationale) -> dict:
    """Withdraw the current record naming the two claims' newest versions; the pair is computed again."""
    who, capacity, rationale = _who(conn, key, capacity, rationale)
    one, two = _claim(conn, original), _claim(conn, restated)
    row = _current_row(conn, one["version"], two["version"])
    if row is None or row["decision"] != "recorded":
        raise GctError(REFUSED, f"No current restatement record names claim {original} as original and claim {restated}"
                                " as restated in their newest versions, so there is nothing to withdraw.",
                       f"See the records with: gct restate show {restated}")
    with store.transaction(conn):
        rid = conn.execute(
            "INSERT INTO restatement (original_version_id, restated_version_id, series_key, decision,"
            " evidence_document_id, contributor_version_id, capacity, rationale, created_at)"
            " VALUES (?, ?, ?, 'withdrawn', ?, ?, ?, ?, ?)",
            (row["original_version_id"], row["restated_version_id"], row["series_key"], row["evidence_document_id"],
             who["version"], capacity, rationale, store.now())).lastrowid
    return _done(conn, rid, original, restated)


# Reviews: every record attached to a claim version today (FR23).

def reviews(conn, version_id: int) -> dict:
    """The period and boundary reviews, corrections (making or replacing this version), match reviews, the newest
    source match of each evidence ref and the restatement rows naming the version, each oldest first."""
    who = "c.name AS contributor, c.organisation, r.capacity, r.rationale, r.created_at"
    join = "JOIN contributor_version c ON c.id = r.contributor_version_id"
    current = {r["id"] for r in conn.execute(CURRENT)}
    return {
        "inference_reviews": [dict(r) for r in conn.execute(
            f"SELECT r.id, r.field, r.decision, r.period_kind, r.period_start, r.period_end, r.boundary,"
            f" r.boundary_detail, {who} FROM inference_review r {join} WHERE r.claim_version_id = ? ORDER BY r.id",
            (version_id,))],
        "corrections": [{**dict(r), "fields": json.loads(r["fields"]),
                         "role": "made this version" if r["version"] == version_id else "replaced this version"}
                        for r in conn.execute(
            f"SELECT r.id, r.claim_version_id AS version, r.corrects_version_id AS corrects_version, r.fields, {who}"
            f" FROM correction r {join} WHERE ? IN (r.claim_version_id, r.corrects_version_id) ORDER BY r.id",
            (version_id,))],
        "match_reviews": [{**{k: r[k] for k in r.keys() if k != "series_key"},
                           "series": match.series_id(json.loads(r["series_key"]))} for r in conn.execute(
            f"SELECT r.id, r.series_key, r.reason, r.decision, {who} FROM match_review r {join}"
            " WHERE r.claim_version_id = ? ORDER BY r.id", (version_id,))],
        "source_match": [dict(r) for r in conn.execute(
            "SELECT e.id AS evidence_ref, e.page_number, s.status, s.reason, s.created_at FROM evidence_ref e"
            " LEFT JOIN source_match s ON s.id = (SELECT MAX(id) FROM source_match WHERE evidence_ref_id = e.id)"
            " WHERE e.claim_version_id = ? ORDER BY e.id", (version_id,))],
        "restatements": [{**_record(r), "role": "original" if r["original_version_id"] == version_id else "restated",
                          "current": r["id"] in current, "binds": bool(r["binds"])} for r in conn.execute(
            RECORDS + " WHERE ? IN (r.original_version_id, r.restated_version_id) ORDER BY r.id", (version_id,))],
    }


def show(conn, claim_id: int) -> dict:
    """Every pair the claim's newest version is in, and the reviews of every version of the claim, of the other
    version of each pair and of the other version named by each restatement row on the claim's versions."""
    c = _claim(conn, claim_id)
    matched = match.compute(conn, c["company"])
    mine = [p for p in pairs(conn, matched) if claim_id in (p["a"]["claim_id"], p["b"]["claim_id"])]
    m = next((x for x in matched["claims"] if x["claim_id"] == claim_id), None)
    own = [(claim_id, v) for (v,) in conn.execute("SELECT id FROM claim_version WHERE claim_id = ? ORDER BY id", (claim_id,))]
    others = {(x["claim_id"], x["claim_version_id"]) for p in mine for x in (p["a"], p["b"]) if x["claim_id"] != claim_id}
    others |= {(cid, v) for cid, v in conn.execute(
        "SELECT DISTINCT v.claim_id, v.id FROM restatement r"
        " JOIN claim_version o ON o.id IN (r.original_version_id, r.restated_version_id)"
        " JOIN claim_version v ON v.id IN (r.original_version_id, r.restated_version_id)"
        " WHERE o.claim_id = ? AND v.claim_id != ?", (claim_id, claim_id))}
    return {"claim": {"id": claim_id, "document": c["document_id"], "page_number": c["page_number"],
                      "version": c["version"], "match_state": m and m["state"], "match_reason": m and m["reason"],
                      "series_id": m and m["series_id"]},
            "pairs": mine,
            "versions": [{"claim": cid, "id": v, "reviews": reviews(conn, v)} for cid, v in own + sorted(others)]}
