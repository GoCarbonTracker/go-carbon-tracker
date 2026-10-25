"""Tables and Graphs (story 6.1, the shared E6 contract, AD-18): one filter selects claims of one published data
version, and the table, graph and series shapes are all built from that one selection (select), so a table and a graph
of the same filter and version hold the same claims. Everything here reads one open version file: nothing is written,
no run is opened. docs/views.md describes the filter, the shapes and every key."""
import json
import re
from datetime import date

from gct.stages import adjudicate, correct, match, restate, review, sheet
from gct.workspace import published
from gct.workspace.layout import NOT_FOUND, REFUSED, USAGE, GctError

SCHEMA = 14  # the projection E6 reads; an older version file is refused
LIMIT, MAX_LIMIT, MAX_IDS, GRAPH_LIMIT = 200, 1000, 1000, 500  # E6-D3: at most 500 claims per graph
SHAPES = ("table", "graph", "series", "values")  # values: what the filter bar lists (F11 g)
KNOWN = match.KNOWN
REVIEWS = ("company-confirmation", "auditor-review", "disagreement", "flag-raised", "highlight", "needs-re-review",
           "corrected", "adjudicated")
# F1: {field: allowed values}; None for the fields that take ids or free text.
CHOICES = {
    "company": None, "document": None, "metric": (*(k for k, _, _ in match.METRICS), "unmapped"), "text": None,
    "period": None, "boundary": ("standalone", "subsidiary_set", "consolidated", "segment", "unknown"),
    "claim_state": tuple(correct.STATES), "evidence": ("matched", "cited", "unresolved", "not-checked"),
    "match": ("series", "reviewed", "uncertain", "not-matchable"), "series": None, "comparison": tuple(restate.FILTERS),
    "review": REVIEWS, "source_kind": ("table", "text"),
}
FIELDS = tuple(CHOICES)
IDS = ("company", "document")
SORTS = ("company", "document", "page", "metric", "value", "period", "boundary", "evidence", "state")
REQUEST = ("filter", "data_version", "shape", "offset", "limit", "sort", "claim_ids")
NOT_CHECKED = "not checked: run gct link"

PERIOD_KNOWN = "(c.period_state IN ('resolved', 'accepted', 'machine-inferred') AND c.period_start IS NOT NULL)"
BOUNDARY_KNOWN = "(c.boundary_state IN ('resolved', 'accepted', 'machine-inferred') AND c.reporting_boundary != 'unknown')"
# ponytail: one evidence ref per claim version (M1 stages write one), as CLAIMS_SQL in api/app.py.
REF = "LEFT JOIN evidence_ref e ON e.id = (SELECT MIN(x.id) FROM evidence_ref x WHERE x.claim_version_id = c.claim_version_id)"
IN = "(SELECT value FROM json_each(?))"
ON_VERSION = "EXISTS (SELECT 1 FROM {} r WHERE r.claim_version_id = c.claim_version_id{})"
REVIEW_SQL = {
    "company-confirmation": ON_VERSION.format("review_company", ""),
    "auditor-review": ON_VERSION.format("review_auditor", ""),
    "flag-raised": ON_VERSION.format("reviewer_flag", " AND r.latest AND r.decision = 'raised'"),
    "highlight": ON_VERSION.format("highlight", ""),
    "needs-re-review": "c.needs_re_review != '[]'",
    "corrected": "c.correction IS NOT NULL",
    "adjudicated": "EXISTS (SELECT 1 FROM adjudication a WHERE a.binds AND c.id IN (a.low_claim_id, a.high_claim_id))",
}
# Sort keys: the expressions ordered by; a claim whose first expression is null sorts last in both directions (F11 b).
ORDER = {
    "company": ("m.name", "c.company_id"), "document": ("d.logical_name", "d.version", "c.document_id"),
    "page": ("CASE WHEN e.sheet IS NULL THEN c.page_number END", "e.cell"), "metric": ("fold(c.metric_text)",),
    "value": ("c.value",), "period": (f"CASE WHEN {PERIOD_KNOWN} THEN c.period_start END", "c.period_end"),
    "boundary": (f"CASE WHEN {BOUNDARY_KNOWN} THEN c.reporting_boundary END", "c.boundary_detail"),
    "evidence": ("CASE e.source_match WHEN 'matched' THEN 0 WHEN 'cited' THEN 1 WHEN 'unresolved' THEN 2 END",
                 "e.source_match_reason"),
    "state": (f"CASE c.claim_state WHEN '{correct.CURRENT}' THEN 0 WHEN '{correct.NOT_FOUND_STATE}' THEN 1"
              f" WHEN '{correct.NOT_EXTRACTED}' THEN 2 END",),
}
ROW_SQL = f"""
SELECT c.*, m.name AS company_name, d.logical_name AS document_name, d.file_type, e.page_number AS ref_page, e.boxes,
       e.sheet, e.cell, e.source_match, e.source_match_reason
FROM claim c JOIN company m ON m.id = c.company_id JOIN document d ON d.id = c.document_id {REF}
"""


def _refuse(cause: str, next_action: str):
    raise GctError(USAGE, cause, next_action)


def _whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)  # true and false are not ids


def _day(value, where: str) -> str:
    try:
        ok = isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) and date.fromisoformat(value)
    except ValueError:
        ok = False
    if not ok:
        _refuse(f"The filter field period.{where} is not a date in the form YYYY-MM-DD.",
                f'Send it as "{where}": "2024-04-01".')
    return value


def normalise(flt) -> dict:
    """The filter checked for shape and allowed values only (an id need not exist) and normalised: sorted lists
    without repeats, absent fields left out. Raises GctError (exit 2, HTTP 400) naming the field and its values."""
    if not isinstance(flt, dict):
        _refuse("The filter is not a JSON object.", 'Send an object, for example {"company": [1]}, or {} for every claim.')
    unknown = sorted(set(flt) - set(FIELDS))
    if unknown:
        _refuse(f"The filter has no field {unknown[0]}.", f"Use only these fields: {', '.join(FIELDS)}.")
    out = {}
    for field in FIELDS:
        if field not in flt:
            continue
        value = flt[field]
        if field == "text":
            if not isinstance(value, str) or not 1 <= len(value) <= 200:
                _refuse("The filter field text is not text of 1 to 200 characters.",
                        'Send words of the metric wording, for example "text": "scope 1".')
            out[field] = value
        elif field == "period":
            if not isinstance(value, dict) or not value or set(value) - {"from", "to"}:
                _refuse("The filter field period is not an object with from, to or both.",
                        'Send it as "period": {"from": "2024-04-01", "to": "2025-03-31"}; either end may be left out.')
            out[field] = {k: _day(value[k], k) for k in ("from", "to") if k in value}
            if out[field].get("from", "") > out[field].get("to", "9999"):
                _refuse("The filter field period ends before it starts.", "Send a from date on or before the to date.")
        else:
            if not isinstance(value, list) or not value:
                example = "1" if field in IDS else f'"{(CHOICES[field] or ["SERIES-ID"])[0]}"'
                _refuse(f"The filter field {field} is not a list of one or more values.",
                        f'Send a list, for example "{field}": [{example}], or leave the field out.')
            for v in value:
                if field in IDS and not _whole(v):
                    _refuse(f"The filter field {field} takes ids, and {json.dumps(v)} is not one.",
                            f'Send whole numbers, for example "{field}": [1, 2].')
                if field not in IDS and not (isinstance(v, str) and v):
                    _refuse(f"The filter field {field} takes words, and {json.dumps(v)} is not one.",
                            f"Use one of: {', '.join(CHOICES[field] or ['a series id'])}.")
                if CHOICES[field] and v not in CHOICES[field]:
                    _refuse(f"{v} is not a value of the filter field {field}.", f"Use one of: {', '.join(CHOICES[field])}.")
            out[field] = sorted(set(value))
    return out


def _version(pconn) -> int:
    return int(pconn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()[0])


def pinned(conn, root, data_version=None):
    """(version, connection to its file, read-only) of the current published version: resolved once, so every query
    of one request reads one version (F2). A pin that is not the current version, no version and a file built by an
    older gct are refused (exit 4, HTTP 409)."""
    current = published.current_version(conn, root)
    if current is None:
        raise GctError(REFUSED, "There is no published data version yet.", "Create one with: gct publish build")
    version, path = current
    if data_version is not None and data_version != version:
        raise GctError(REFUSED, f"Data version {data_version} is no longer the current one; the current version is"
                                f" {version}.", f"Reload to see version {version}.")
    pconn = published.open_version(path)
    pconn.execute("BEGIN")  # one read snapshot for every query of the request, even if the file is purged meanwhile
    if int(pconn.execute("SELECT value FROM meta WHERE key = 'projection_schema'").fetchone()[0]) < SCHEMA:
        pconn.close()
        raise GctError(REFUSED, f"Data version {version} was built by an older gct and cannot be filtered.",
                       published.BUILD_AGAIN)
    return version, pconn


def _disagreeing(pconn) -> list[int]:
    """The claim versions on which both ledgers hold a position and the two sets of latest outcomes differ (5.1 L4)."""
    pos = {}
    for t, i in (("review_company", 0), ("review_auditor", 1)):
        for v, o in pconn.execute(f"SELECT claim_version_id, outcome FROM {t} WHERE latest"):
            pos.setdefault(v, (set(), set()))[i].add(o)
    return [v for v, (a, b) in pos.items() if a and b and a != b]


def _fold(pconn) -> None:
    pconn.create_function("fold", 1, lambda s: None if s is None else s.casefold(), deterministic=True)


def select(pconn, flt: dict) -> list[int]:
    """The ids, ascending, of the claims of this version that a normalised filter matches. The only selection code."""
    _fold(pconn)
    where, params = [], []

    def cond(sql, *p):
        where.append(sql)
        params.extend(p)

    for field, col in (("company", "c.company_id"), ("document", "c.document_id"), ("series", "c.series_id")):
        if field in flt:
            cond(f"{col} IN {IN}", json.dumps(flt[field]))
    if "metric" in flt:
        cond(f"(c.metric_key IN {IN} OR (? AND c.metric_key IS NULL))", json.dumps(flt["metric"]),
             "unmapped" in flt["metric"])
    if "text" in flt:
        cond("instr(fold(c.metric_text), fold(?)) > 0", flt["text"])
    if "period" in flt:
        p = flt["period"]
        cond(f"{PERIOD_KNOWN} AND c.period_start >= ? AND c.period_end <= ?", p.get("from", ""), p.get("to", "9999"))
    if "boundary" in flt:
        cond(f"(({BOUNDARY_KNOWN} AND c.reporting_boundary IN {IN}) OR (? AND NOT {BOUNDARY_KNOWN}))",
             json.dumps(flt["boundary"]), "unknown" in flt["boundary"])
    if "claim_state" in flt:
        cond(f"c.claim_state IN {IN}", json.dumps([correct.STATES[s] for s in flt["claim_state"]]))
    if "evidence" in flt:
        cond(f"(e.source_match IN {IN} OR (? AND e.source_match IS NULL))", json.dumps(flt["evidence"]),
             "not-checked" in flt["evidence"])
    if "match" in flt:
        cond(f"c.match_state IN {IN}", json.dumps([s.replace("-", " ") for s in flt["match"]]))
    if "comparison" in flt:
        states = json.dumps([restate.FILTERS[s] for s in flt["comparison"]])
        cond(f"c.id IN (SELECT claim_a FROM comparison WHERE state IN {IN}"
             f" UNION SELECT claim_b FROM comparison WHERE state IN {IN})", states, states)
    if "source_kind" in flt:
        clauses = []
        if "table" in flt["source_kind"]:
            clauses.append("c.locator LIKE 't%'")
        if "text" in flt["source_kind"]:
            clauses.append("c.locator LIKE 'l%'")
        if clauses:
            cond(f"({' OR '.join(clauses)})")
        else:
            cond("0")
    if "review" in flt:
        parts = []
        for r in flt["review"]:
            if r == "disagreement":
                parts.append(f"c.claim_version_id IN {IN}")
                params.append(json.dumps(_disagreeing(pconn)))
            else:
                parts.append(REVIEW_SQL[r])
        where.append(f"({' OR '.join(parts)})")
    sql = f"SELECT c.id FROM claim c {REF}" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY c.id"
    return [r[0] for r in pconn.execute(sql, params)]


# Rows (F4), the evidence location every row, node and edge carries (FR47, NFR16), and the agreed texts (E6-D8).

def location(document, page=None, sheet_=None, cell=None, claim_id=None, unresolved=None) -> dict:
    """Where a source opens: a page of a PDF (with the claim to select, if any), a cell of a spreadsheet, or, when
    resolved is false, why it cannot be opened."""
    return {"document": document, "page": None if unresolved else page, "sheet": None if unresolved else sheet_,
            "cell": None if unresolved else cell, "claim_id": claim_id, "resolved": unresolved is None,
            "reason": unresolved}


def _claim_location(r) -> dict:
    # An unresolved source match still opens the page or cell its reference names, as the Evidence view does; its
    # evidence text says "unresolved: reason".
    if r["sheet"] is not None:
        return location(r["document_id"], sheet_=r["sheet"], cell=r["cell"], claim_id=r["id"])
    if r["ref_page"] is None:
        why = f"unresolved: {r['source_match_reason']}" if r["source_match"] == "unresolved" else "not on a page"
        return location(r["document_id"], claim_id=r["id"], unresolved=why)
    return location(r["document_id"], page=r["ref_page"], claim_id=r["id"])


def evidence_text(status, reason) -> str:
    if status is None:
        return NOT_CHECKED
    return f"{status}: {reason}" if reason else status


def review_text(rv: dict) -> str:
    parts = [f"{who} {', '.join(rv[who])}" for who in ("company", "auditor") if rv[who]]
    parts += ["disagreement"] * bool(rv["disagreement"])
    parts += [f"{words}: {rv[k]}" for k, words in (("flags_raised", "flags raised"), ("highlights", "highlights"),
                                                   ("needs_re_review", "needs renewed review")) if rv[k]]
    parts += ["corrected"] * rv["corrected"]
    parts += [f"adjudications: {len(rv['adjudications'])}"] * bool(rv["adjudications"])  # F11 h
    return "; ".join(parts) or "no review records"


def _positions(rows) -> list[str]:
    return [o for o in review.OUTCOMES if any(r["outcome"] == o for r in rows)]


def _records(pconn, claims: list, versions: list) -> dict:
    """The review records on these claim versions, and the comparison and adjudication rows naming these claims."""
    c, v = json.dumps(claims), json.dumps(versions)
    on = {t: pconn.execute(f"SELECT * FROM {t} WHERE claim_version_id IN {IN} ORDER BY id", (v,)).fetchall()
          for t in ("review_company", "review_auditor", "reviewer_flag", "highlight")}
    pairs = pconn.execute(f"SELECT * FROM comparison WHERE claim_a IN {IN} OR claim_b IN {IN}", (c, c)).fetchall()
    adj = pconn.execute(f"SELECT * FROM adjudication WHERE binds AND (low_claim_id IN {IN} OR high_claim_id IN {IN})"
                        " ORDER BY id", (c, c)).fetchall()
    return {**on, "comparison": pairs, "adjudication": adj}


def _rows(pconn, ids: list[int]) -> list[dict]:
    """The F4 row of each claim, in the order given."""
    by_id = {r["id"]: r for r in pconn.execute(f"{ROW_SQL} WHERE c.id IN {IN}", (json.dumps(ids),))}
    found = [by_id[i] for i in ids]
    rec = _records(pconn, ids, [r["claim_version_id"] for r in found])
    out = []
    for r in found:
        v = r["claim_version_id"]
        on = {t: [x for x in rec[t] if x["claim_version_id"] == v] for t in ("review_company", "review_auditor",
                                                                             "reviewer_flag", "highlight")}
        company, auditor = (_positions([x for x in on[t] if x["latest"]]) for t in ("review_company", "review_auditor"))
        rv = {"company": company, "auditor": auditor,
              "disagreement": {"company": company, "auditor": auditor} if company and auditor and company != auditor
              else None,
              "flags_raised": sum(1 for x in on["reviewer_flag"] if x["latest"] and x["decision"] == "raised"),
              "highlights": len(on["highlight"]), "needs_re_review": len(json.loads(r["needs_re_review"])),
              "corrected": r["correction"] is not None,
              "candidate_pairs": sorted(p["claim_b"] if p["claim_a"] == r["id"] else p["claim_a"]
                                        for p in rec["comparison"] if r["id"] in (p["claim_a"], p["claim_b"])
                                        and p["state"] == restate.UNRESOLVED),
              "adjudications": [{"id": a["id"], "state": adjudicate.STATES[a["state"]],
                                 "with": a["high_claim_id"] if a["low_claim_id"] == r["id"] else a["low_claim_id"]}
                                for a in rec["adjudication"] if r["id"] in (a["low_claim_id"], a["high_claim_id"])]}
        rv["text"] = review_text(rv)
        known_p = r["period_state"] in KNOWN and r["period_start"] is not None
        known_b = r["boundary_state"] in KNOWN and r["reporting_boundary"] != "unknown"
        out.append({
            "claim": {"id": r["id"], "company": r["company_id"], "document": r["document_id"],
                      "page": None if r["sheet"] else r["ref_page"], "sheet": r["sheet"], "cell": r["cell"],
                      "locator": r["locator"], "metric_text": r["metric_text"], "metric_key": r["metric_key"],
                      "value_text": r["value_text"], "value": r["value"], "unit_text": r["unit_text"],
                      "period_label": r["period_label"],
                      "period": {"kind": r["period_kind"], "start": r["period_start"], "end": r["period_end"],
                                 "state": r["period_state"], "known": known_p},
                      "boundary": {"value": r["reporting_boundary"], "detail": r["boundary_detail"],
                                   "state": r["boundary_state"], "known": known_b},
                      "claim_state": r["claim_state"], "series_id": r["series_id"], "match_state": r["match_state"],
                      "match_reason": r["match_reason"]},
            "company_name": r["company_name"], "document_name": r["document_name"],
            "evidence": {"source_match": r["source_match"], "reason": r["source_match_reason"],
                         "page": r["ref_page"], "boxes": r["boxes"] and json.loads(r["boxes"]), "sheet": r["sheet"],
                         "cell": r["cell"], "document_state": "active", "location": _claim_location(r),
                         "text": evidence_text(r["source_match"], r["source_match_reason"])},
            "review": rv,
        })
    return out


# What every shape says besides its claims (F7).

def _hidden(pconn) -> dict:
    docs = [{"document_id": d, "name": n, "claims": c} for d, n, c in pconn.execute(
        "SELECT document_id, logical_name, claims FROM hidden_by_archive ORDER BY document_id")]
    n, m = sum(d["claims"] for d in docs), len(docs)
    text = (f"{n} claim{'s' * (n != 1)} of {m} archived document{'s' * (m != 1)} {'is' if n == 1 else 'are'} not in"
            " this or any view. Restore a document to include its claims.") if docs else None
    return {"documents": m, "claims": n, "by_document": docs, "text": text}


def _deleted(pconn, flt: dict) -> list[dict]:
    gone = {r[0] for r in pconn.execute("SELECT document_id FROM deleted_document")}
    return [{"document_id": d, "text": f"Document {d} was permanently deleted."} for d in flt.get("document", [])
            if d in gone]


def empty_text(version: int) -> str:
    return f"No claims match this filter in data version {version}."


def _checked(shape, offset, limit, sort, claim_ids) -> list:
    """The request's other fields, refused like the filter's; the sort as [(key, descending)]."""
    if shape not in SHAPES:
        _refuse(f"The shape {json.dumps(shape)} is not one of {', '.join(SHAPES)}.", "Ask for table, the default, or"
                                                                                    " another of these shapes.")
    if not _whole(offset) or offset < 0:
        _refuse("The offset is not a whole number of 0 or more.", "Start at offset 0 for the first page.")
    if not _whole(limit) or not 1 <= limit <= MAX_LIMIT:
        _refuse(f"The limit is not a whole number from 1 to {MAX_LIMIT}.", f"Ask for 1 to {MAX_LIMIT} rows; the default"
                                                                            f" is {LIMIT}.")
    if sort is not None and (not isinstance(sort, list) or len(sort) > 1):
        _refuse("The sort is not a list of at most one key.", 'Send "sort": [{"key": "value", "dir": "desc"}].')
    keys = []
    for s in sort or []:
        if not isinstance(s, dict) or set(s) - {"key", "dir"} or s.get("key") not in SORTS or s.get("dir", "asc") not in (
                "asc", "desc"):
            _refuse("A sort element is not a key with asc or desc.",
                    f"Sort by one of: {', '.join(SORTS)}, ascending or descending.")
        keys.append((s["key"], s.get("dir") == "desc"))
    if claim_ids is not None and (not isinstance(claim_ids, list) or not 1 <= len(claim_ids) <= MAX_IDS
                                  or not all(_whole(i) for i in claim_ids)):
        _refuse(f"The claim ids are not a list of 1 to {MAX_IDS} whole numbers.", "Give claim ids such as 12 and 13.")
    if claim_ids is not None and shape == "values":
        _refuse("The values shape lists the values of every claim the filter selects, so it takes no claim ids.",
                "Leave the claim ids out, or ask for another shape.")
    return keys


def values(pconn, ids: list[int]) -> dict:
    """The metric keys (with their claim counts) and the series of the selected claims (F11 g)."""
    sel = json.dumps(ids)
    keys = [{"metric_key": k or "unmapped", "claims": n} for k, n in pconn.execute(
        f"SELECT metric_key, COUNT(*) FROM claim WHERE id IN {IN} GROUP BY metric_key ORDER BY metric_key IS NULL,"
        " metric_key", (sel,))]
    series_ = [{"id": s, "metric_key": k, "company_id": c, "points": n} for s, k, c, n in pconn.execute(
        f"SELECT s.id, s.metric_key, s.company_id, COUNT(c.id) FROM series s JOIN claim c ON c.series_id = s.id"
        f" WHERE c.id IN {IN} GROUP BY s.id ORDER BY s.company_id, s.metric_key, s.id", (sel,))]
    return {"metric_keys": keys, "series": series_}


def answer(pconn, flt, shape="table", offset=0, limit=LIMIT, sort=None, claim_ids=None) -> dict:
    """Any shape (F3) of one version's claims a filter selects, limited to claim_ids when given (F11 a)."""
    flt = normalise(flt)
    keys = _checked(shape, offset, limit, sort, claim_ids)
    version = _version(pconn)
    ids = select(pconn, flt)
    if shape == "values":
        return {"status": "ok", "data_version": version, "filter": flt, "matched": len(ids), **values(pconn, ids)}
    not_found = []
    if claim_ids is not None:
        chosen = set(claim_ids)
        not_found = [{"claim_id": i, "reason": f"not in data version {version} or not matched by this filter"}
                     for i in sorted(chosen - set(ids))]
        ids = [i for i in ids if i in chosen]
    unknown = 0
    if "period" in flt:  # claims every other condition matches whose period is not known (F1)
        others = set(select(pconn, {k: v for k, v in flt.items() if k != "period"}))
        if claim_ids is not None:
            others &= set(claim_ids)
        unknown = pconn.execute(f"SELECT COUNT(*) FROM claim c WHERE c.id IN {IN} AND NOT {PERIOD_KNOWN}",
                                (json.dumps(sorted(others)),)).fetchone()[0]
    head = {"status": "ok", "data_version": version, "filter": flt, "matched": len(ids)}
    tail = {"excluded": {"period_unknown": unknown}, "hidden_by_archive": _hidden(pconn),
            "deleted_in_filter": _deleted(pconn, flt), "not_found": not_found}
    if shape == "table":
        page = _ordered(pconn, ids, keys, offset, limit)
        return {**head, "total": pconn.execute("SELECT COUNT(*) FROM claim").fetchone()[0], "offset": offset,
                "limit": limit, "rows": _rows(pconn, page), "empty": None if ids else empty_text(version), **tail}
    why = empty_text(version) if not ids else None
    if shape == "graph":
        if ids and len(ids) > GRAPH_LIMIT:
            why = f"{len(ids)} claims match; a graph draws at most {GRAPH_LIMIT}. Narrow the filter."
        g = {"nodes": [], "hyperedges": [], "edges": []} if why else graph(pconn, _rows(pconn, ids))
        return {**head, "graph_limit": GRAPH_LIMIT, "drawable": why is None, "reason": why, **g, **tail}
    s = {"series": None, "points": [], "comparisons": []}
    if not why:
        s, why = series(pconn, _rows(pconn, ids))
    return {**head, "drawable": why is None, "reason": why, **s, **tail}


def _ordered(pconn, ids: list[int], keys: list, offset: int, limit: int) -> list[int]:
    """One page of ids in table order (F11 b): the sort key with nulls last either way, else company, document and
    page; always ending with claim id ascending."""
    _fold(pconn)
    if keys:
        (key, desc), = keys
        first, *rest = ORDER[key]
        order = [f"({first}) IS NULL", *(f"{x} {'DESC' if desc else 'ASC'}" for x in (first, *rest))]
    else:
        order = [*ORDER["company"], *ORDER["document"], "c.page_number"]
    sql = (f"SELECT c.id FROM claim c JOIN company m ON m.id = c.company_id JOIN document d ON d.id = c.document_id"
           f" {REF} WHERE c.id IN {IN} ORDER BY {', '.join(order)}, c.id LIMIT ? OFFSET ?")
    return [r[0] for r in pconn.execute(sql, (json.dumps(ids), limit, offset))]


# The graph (F5, Q20): built only from the selected claims; claim nodes are exactly the selected set.

def _basis(row: dict, raw, own: dict) -> dict:
    """Where a known period or boundary was read: its basis page, the claim's own figure when the label is its own
    source, or unresolved for a spreadsheet's declared mapping (it has no page)."""
    if raw is None:
        return own
    b = json.loads(raw)
    if row["claim"]["sheet"] is not None or b["page"] is None:
        return location(row["claim"]["document"], unresolved=f"no page: {b['wording']}")
    return location(row["claim"]["document"], page=b["page"])


def _cited(docs: dict, document, page, state) -> dict:
    """A review record's cited document and page."""
    if document is None:
        return location(None, unresolved="no document cited")
    if document not in docs:
        return location(document, unresolved=f"document {state or 'not active'}")
    if docs[document] != "pdf":
        return location(document, unresolved="a spreadsheet cited without a cell")
    return location(document, page=page or 1)


def graph(pconn, rows: list[dict]) -> dict:
    """Claim, location, period, boundary, series, review and adjudication nodes; one hyperedge per claim; the
    neighbourhood graph's member and comparison edges. Every node and edge carries evidence (a list of locations)."""
    ids = {r["claim"]["id"] for r in rows}
    extra = {r["id"]: r for r in pconn.execute(f"SELECT id, claim_version_id, period_basis, boundary_basis FROM claim"
                                               f" WHERE id IN {IN}", (json.dumps(sorted(ids)),))}
    docs = dict(pconn.execute("SELECT id, file_type FROM document").fetchall())
    labels = {s: lab or key for s, lab, key in pconn.execute("SELECT id, label, metric_key FROM series")}
    rec = _records(pconn, sorted(ids), [x["claim_version_id"] for x in extra.values()])
    nodes, hyperedges, edges = {}, [], []

    def node(nid, kind, label, evidence, **attrs):
        n = nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label, "evidence": [], **attrs})
        n["evidence"] += [e for e in evidence if e not in n["evidence"]]
        return nid

    by_claim = {r["claim"]["id"]: r for r in rows}
    for r in rows:
        c, cid = r["claim"], f"claim:{r['claim']['id']}"
        own = r["evidence"]["location"]
        pairs = [p for p in rec["comparison"] if c["id"] in (p["claim_a"], p["claim_b"])]
        partners = [p["claim_b"] if p["claim_a"] == c["id"] else p["claim_a"] for p in pairs]
        outside = sum(1 for o in partners if o not in ids)
        node(cid, "claim", f"{c['value_text']}{' ' + c['unit_text'] if c['unit_text'] else ''} · "
             f"{c['metric_text'] or '(no wording)'}", [own], row=r, outside=outside,
             outside_text=f"{outside} related claim{'s' * (outside != 1)} outside this selection" if outside else None)
        members = []
        if own["resolved"]:
            if c["sheet"] is not None:
                members.append(node(f"cell:{c['document']}:{c['sheet']}!{c['cell']}", "cell",
                                    f"{r['document_name']} {c['sheet']}!{c['cell']}",
                                    [location(c["document"], sheet_=c["sheet"], cell=c["cell"])]))
            else:
                members.append(node(f"page:{c['document']}:{own['page']}", "page",
                                    f"{r['document_name']} p{own['page']}", [location(c["document"], page=own["page"])]))
        p, b = c["period"], c["boundary"]
        if p["known"]:
            members.append(node(f"period:{p['start']}..{p['end']}", "period", f"{p['start']}..{p['end']}",
                                [_basis(r, extra[c["id"]]["period_basis"], own)]))
        if b["known"]:
            tail = f":{b['detail']}" if b["detail"] else ""
            members.append(node(f"boundary:{b['value']}{tail}", "boundary",
                                b["value"] + (f": {b['detail']}" if b["detail"] else ""),
                                [_basis(r, extra[c["id"]]["boundary_basis"], own)]))
        if c["series_id"]:
            members.append(node(f"series:{c['series_id']}", "series", labels.get(c["series_id"]) or c["series_id"], []))
        v = extra[c["id"]]["claim_version_id"]
        for t, kind, words in (("review_company", "company", "company confirmation"),
                               ("review_auditor", "auditor", "auditor review")):
            for x in rec[t]:
                if x["claim_version_id"] == v:
                    members.append(node(f"{kind}:{x['id']}", kind, f"{words}: {x['outcome']}",
                                        [_cited(docs, x["evidence_document_id"], x["evidence_page"],
                                                x["evidence_state"])], **_who(x), outcome=x["outcome"],
                                        text=x["conclusion"], evidence_note=x["evidence_note"]))
        for x in rec["reviewer_flag"]:
            if x["claim_version_id"] == v:
                members.append(node(f"flag:{x['id']}", "flag", f"flag: {x['decision']}", [own], **_who(x),
                                    outcome=x["decision"], text=x["rationale"], evidence_note=None))
        for x in rec["highlight"]:
            if x["claim_version_id"] == v:
                members.append(node(f"highlight:{x['id']}", "highlight", "highlight", [own], **_who(x), outcome=None,
                                    text=x["note"], evidence_note=None))
        for a in rec["adjudication"]:
            if c["id"] in (a["low_claim_id"], a["high_claim_id"]):
                counter = [_cited(docs, a["counter_document_id"], a["counter_page"], None)] if a[
                    "counter_document_id"] else []
                members.append(node(f"adjudication:{a['id']}", "adjudication",
                                    f"adjudication: {adjudicate.STATES[a['state']]}", counter, **_who(a),
                                    outcome=adjudicate.STATES[a["state"]], text=a["rationale"],
                                    evidence_note=a["counter_note"]))
        members += [f"claim:{o}" for o in sorted(set(partners) & ids)]
        hyperedges.append({"id": f"hyperedge:{c['id']}", "claim": cid, "members": members})
        edges += [{"id": f"{cid}>{m}", "kind": "member", "source": cid, "target": m, "state": None, "reason": None,
                   "restatement": None, "evidence": [own]} for m in members if not m.startswith("claim:")]
    for p in rec["comparison"]:
        a, b = p["claim_a"], p["claim_b"]
        if a in ids and b in ids:
            edges.append({"id": f"comparison:{a}:{b}", "kind": "comparison", "source": f"claim:{a}",
                          "target": f"claim:{b}", "state": p["state"], "reason": p["reason"],
                          "restatement": p["restatement_id"],
                          "evidence": [by_claim[a]["evidence"]["location"], by_claim[b]["evidence"]["location"]]})
    return {"nodes": list(nodes.values()), "hyperedges": hyperedges, "edges": edges}


def _who(x) -> dict:
    """A record's contributor as declared (self-declared, never checked by GCT)."""
    return {"contributor": x["contributor_name"], "organisation": x["contributor_organisation"],
            "capacity": x["capacity"], "self_declared": True}


def series(pconn, rows: list[dict]) -> tuple[dict, str | None]:
    """(the series' points by period with the comparisons among them, None) when every selected claim is a point of
    one series, else (empty, the reason)."""
    empty = {"series": None, "points": [], "comparisons": []}
    none = [r for r in rows if not r["claim"]["series_id"]]
    if none:
        why = sorted({r["claim"]["match_reason"] or r["claim"]["match_state"] for r in none})
        return empty, f"These claims are in no series: {'; '.join(why)}."
    found = sorted({r["claim"]["series_id"] for r in rows})
    if len(found) > 1:
        return empty, f"These claims are in {len(found)} series; pick one."
    sid = found[0]
    s = pconn.execute("SELECT s.*, m.name AS company_name FROM series s JOIN company m ON m.id = s.company_id"
                      " WHERE s.id = ?", (sid,)).fetchone()
    by_claim = {r["claim"]["id"]: r for r in rows}
    points = pconn.execute(
        f"SELECT p.* FROM series_point p JOIN claim c ON c.id = p.claim_id AND c.claim_version_id = p.claim_version_id"
        f" WHERE p.series_id = ? AND p.claim_id IN {IN} ORDER BY p.period_end, p.period_start, p.claim_id",
        (sid, json.dumps(sorted(by_claim)))).fetchall()
    periods = sorted({(p["period_end"], p["period_start"]) for p in points})
    out = [{**by_claim[p["claim_id"]], "period_order": periods.index((p["period_end"], p["period_start"])),
            "period_start": p["period_start"], "period_end": p["period_end"], "value_base": p["value_base"],
            "comparable": bool(p["comparable"]), "not_comparable_reason": p["reason"]} for p in points]
    pairs = [{"claim_a": p["claim_a"], "claim_b": p["claim_b"], "period_start": p["period_start"],
              "period_end": p["period_end"], "state": p["state"], "reason": p["reason"],
              "restatement": p["restatement_id"],
              "evidence": [by_claim[p["claim_a"]]["evidence"]["location"], by_claim[p["claim_b"]]["evidence"]["location"]]}
             for p in pconn.execute("SELECT * FROM comparison WHERE series_id = ? ORDER BY period_end, claim_a, claim_b",
                                    (sid,)) if p["claim_a"] in by_claim and p["claim_b"] in by_claim]
    return {"series": {"id": s["id"], "company": s["company_id"], "company_name": s["company_name"],
                       "metric_key": s["metric_key"], "label": s["label"], "reporting_boundary": s["reporting_boundary"],
                       "boundary_detail": s["boundary_detail"], "unit_family": s["unit_family"],
                       "period_kind": s["period_kind"]}, "points": out, "comparisons": pairs}, None


# A spreadsheet claim's evidence (F10, E6-D4).

def _letters(i: int) -> str:
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def cells(pconn, root, doc_id: int, sheet_name, cell) -> dict:
    """The sheet's header row and the cell's row, with the cell's column marked, read from the stored file."""
    version = _version(pconn)
    doc = pconn.execute("SELECT * FROM document WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        if pconn.execute("SELECT 1 FROM deleted_document WHERE document_id = ?", (doc_id,)).fetchone():
            raise GctError(REFUSED, f"Document {doc_id} was permanently deleted.", "Its cells cannot be shown any more.")
        if pconn.execute("SELECT 1 FROM hidden_by_archive WHERE document_id = ?", (doc_id,)).fetchone():
            raise GctError(REFUSED, f"Document {doc_id} is archived.",
                           f"Restore it with: gct doc restore {doc_id} --as KEY --capacity TEXT --rationale TEXT")
        raise GctError(NOT_FOUND, f"There is no document {doc_id} in data version {version}.",
                       "See the documents with: gct doc list")
    if doc["file_type"] == "pdf":
        raise GctError(REFUSED, f"Document {doc_id} is a PDF, so it has pages, not cells.",
                       "Open its page in the Evidence section.")
    if not sheet_name or not cell:
        _refuse("Give the sheet and the cell.", f"Ask for /api/documents/{doc_id}/cells?sheet=NAME&cell=C7.")
    book = dict(sheet._book(root, dict(doc)))
    if sheet_name not in book:
        raise GctError(NOT_FOUND, f"Document {doc_id} has no sheet {sheet_name}.", f"Its sheets are: {', '.join(book)}.")
    m = re.fullmatch(r"([A-Z]+)([1-9]\d*)", cell)
    if not m:
        _refuse(f"{cell} is not a cell such as C7.", "Give the column letters and the row number, for example C7.")
    rows, col, row = book[sheet_name], sheet._index(m[1]), int(m[2])
    width = len(rows[0]) if rows else 0
    if row > len(rows) or col >= width:
        last = f"{_letters(width - 1)}{len(rows)}" if rows else "none"
        raise GctError(NOT_FOUND, f"Cell {cell} is outside sheet {sheet_name}.", f"Its cells run from A1 to {last}.")
    return {"status": "ok", "data_version": version, "document": doc_id, "name": doc["logical_name"],
            "sheet": sheet_name, "cell": cell, "columns": [_letters(i) for i in range(width)], "header": rows[0],
            "row": row, "cells": rows[row - 1], "column": col}
