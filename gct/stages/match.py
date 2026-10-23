"""Cross-report matching (FR19, FR22): a canonical metric key and a unit for each claim version from a small built-in
list, then series of one metric over periods, computed on read. 4.1 links; it never says two values agree or differ."""
import json
import re

from collections import Counter

from gct.models.redact import MARK, scrub_key
from gct.stages import Stage, correct, infer, run_stage, version_of
from gct.stages.extract import WESTERN
from gct.stages.link import EXTRACT_FIRST
from gct.stages.read import ACTIVE, NOT_ACTIVE, select
from gct.workspace import registry, runs, store
from gct.workspace.layout import NOT_FOUND, REFUSED, GctError

METHOD = "match-rules"
RULES_VERSION = 2  # 2: number_of reads Indian grouping and drops trailing footnote marks (story 4.2)
METRICS_VERSION = 2  # 2: records the combined-scope list of 4.1 fix 95e3c9e; the list itself is unchanged here
UNITS_VERSION = 1
CONFIG = version_of("match", 1, RULES_VERSION, METRICS_VERSION, UNITS_VERSION)
AMBIGUOUS = "ambiguous"

# Metric list v2: absolute totals only. (key, phrases one of which must appear, phrases none of which may appear).
EXCLUDED = ("intensity", "per rupee", "per unit", " per ", "%", "percentage", "ratio", "category")
WHOLE_WORDS = ("ratio", "category")  # matched as words: "operations" and "generation" contain "ratio"
METRICS = (
    ("ghg_scope_1", ("scope 1", "scope-1", "scope i"), ("scope 2", "scope ii", "scope 3", "scope 1 and", "scope i and",
                                                         "scope 1 +", "scope 1+", "scope 1 &", "scope 1,")),
    ("ghg_scope_2", ("scope 2",), ("scope 1", "scope 3", "market", "location")),
    ("ghg_scope_1_2", ("scope 1 and scope 2", "scope 1 and 2", "scope 1+2", "scope 1 + 2", "scope 1 & 2", "scope 1 &2"),
     ("scope 3",)),
    ("ghg_scope_3", ("scope 3",), ("scope 1", "scope 2")),
    ("energy_total", ("total energy consum",), ("renewable",)),
    ("energy_renewable", ("energy consumed from renewable",), ("non-renewable", "non renewable")),
    ("energy_non_renewable", ("energy consumed from non-renewable", "energy consumed from non renewable"), ()),
    ("water_withdrawal_total", ("total volume of water withdrawal",), ()),
    ("water_consumption_total", ("total volume of water consumption",), ()),
    ("water_discharge_total", ("total water discharged",), ()),
    ("waste_total", ("total waste generated",), ()),
)

# Unit table v1: text as looked up -> (conversion family named by its base unit, factor to the base unit). Two units are
# comparable only inside one family (Codex 150); tco2 never converts to tco2e. mtco2e and ml are left out on purpose:
# megatonnes or metric tonnes, megalitres or millilitres cannot be told apart.
UNITS = {
    **dict.fromkeys(("tco2e", "tco2-e", "tco2eq", "tonnesco2e", "tonnesofco2e", "metrictonnesofco2e", "tcoe2"),
                    ("tco2e", 1.0)),
    "ktco2e": ("tco2e", 1000.0),
    **dict.fromkeys(("tco2", "tonnesofco2", "metrictonnesofco2"), ("tco2", 1.0)),
    "mj": ("gj", 0.001), "gj": ("gj", 1.0), "tj": ("gj", 1000.0), "pj": ("gj", 1e6),
    "kwh": ("gj", 0.0036), "mwh": ("gj", 3.6), "gwh": ("gj", 3600.0),
    **dict.fromkeys(("kl", "kilolitres", "kiloliters", "m3", "cubicmetres"), ("kl", 1.0)),
    "litres": ("kl", 0.001), "megalitres": ("kl", 1000.0),
    **dict.fromkeys(("t", "tonnes", "tons", "mt", "metrictonnes"), ("t", 1.0)),
    "kg": ("t", 0.001),
}
PREFIXES = {"thousand": 1e3, "'000": 1e3, "lakh": 1e5, "crore": 1e7, "million": 1e6, "billion": 1e9}
FAMILIES = ("tco2e", "tco2", "gj", "kl", "t")
LEFT_OUT = ("mtco2e", "ml")  # a printed unit left out on purpose stays unknown: no unit from the label either


INDIAN = re.compile(r"-?\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d+)?")


def number_of(text) -> float | None:
    """The number printed in a value text, for comparison only: the Western form extract accepts, or Indian grouping
    (the last group three digits, every earlier one two), after trailing footnote marks are removed. Parentheses
    never give a sign. The printed text and the claim's value are never rewritten."""
    s = str(text or "").strip().rstrip("*#†^").strip()
    return float(s.replace(",", "")) if WESTERN.fullmatch(s) or INDIAN.fullmatch(s) else None


def label_of(text) -> str:
    """A metric label as matched: lowercased, whitespace collapsed, footnote marks removed."""
    return " ".join(re.sub(r"[#*†]", " ", str(text or "")).lower().split())


def _phrase(p: str) -> str:
    """A required phrase as a pattern: one ending in a number or a one-letter word ends there ('scope 1' is not
    'scope 12', 'scope i' is not 'scope ii')."""
    return re.escape(p) + (r"(?!\w)" if re.search(r"(\d| [a-z])$", p) else "")


def _excluded(text: str) -> bool:
    return any(re.search(rf"\b{x}\b", text) if x in WHOLE_WORDS else x in f" {text} " for x in EXCLUDED)


def metric_of(text, unit_text=None) -> tuple[str | None, str | None]:
    """(metric key, rule) for a label: the one list entry it satisfies, else (None, None), or (None, 'ambiguous').
    The exclusion words are checked on the label and on the printed unit."""
    label = label_of(text)
    if not label or _excluded(label) or _excluded(label_of(unit_text)):
        return None, None
    hits = []
    for key, must, never in METRICS:
        found = next((p for p in must if re.search(_phrase(p), label)), None)
        if found and not any(n in label for n in never):
            hits.append((key, f"{key}: {found}"))
    if len(hits) == 1:
        return hits[0]
    return None, AMBIGUOUS if hits else None


def unit_text_of(text: str) -> str:
    """A unit text as looked up: lowercased, the word 'in', brackets and whitespace removed."""
    s = re.sub(r"\bin\b", " ", text.lower().replace("’", "'"))
    return re.sub(r"[\s()\[\]{}]", "", s)


def _machine(normalise, text) -> str:
    """normalise(text), or the redaction mark alone when the text holds the mark or the key rule (redact.scrub_key)
    finds a credential in the text or in its normalised value: label_of and unit_text_of drop the marks, brackets,
    spaces and words that kept a token apart from "bearer", and scrubbing either side alone can leave one. A text a
    package wrote scrubbed (holding the mark) gives the same value as its source text."""
    out = normalise(text or "")
    return MARK if MARK in (text or "") or scrub_key(text) != text or scrub_key(out) != out else out


def key_label(text) -> str:
    """An unmapped metric's label as a series key and label hold it."""
    return _machine(label_of, text)


def key_unit(text) -> str:
    """A unit as a unit as printed family holds it."""
    return _machine(unit_text_of, text)


def _lookup(text: str) -> tuple[str, float] | None:
    """(family, factor) for one unit text, normalised, with one magnitude prefix (before or after the unit)
    multiplied in."""
    s = unit_text_of(text)
    if s in UNITS:
        return UNITS[s]
    for word, n in PREFIXES.items():
        rest = s[len(word):] if s.startswith(word) else s[:-len(word)] if s.endswith(word) else None
        if rest in UNITS:
            return UNITS[rest][0], UNITS[rest][1] * n
    return None


def unit_of(unit_text, metric_text) -> tuple[str | None, float | None, str | None]:
    """(unit key, factor, source) from the unit as printed, else from a unit printed in the label: a parenthesised
    group (last first), then the label's last one to five words joined, longest first. (None, None, None): unknown."""
    if unit_text and (u := _lookup(unit_text)):
        return *u, "unit"
    if unit_text and unit_text_of(unit_text) in LEFT_OUT:
        return None, None, None
    label = label_of(metric_text)
    for group in reversed(re.findall(r"\(([^()]*)\)", label)):
        if u := _lookup(group):
            return *u, "label"
    words = label.split()
    for n in range(min(5, len(words)), 0, -1):
        if u := _lookup("".join(words[-n:])):
            return *u, "label"
    return None, None, None


# The stage: one item per document, a metric_assignment row per newest claim version whose result changed.

RETRY = "Run gct match again. Documents whose claims have not changed are not matched twice."
FAILED_SQL = """
SELECT a.item FROM attempt a
WHERE a.run_id = ? AND a.stage = 'match' AND a.outcome = 'failed'
  AND a.id = (SELECT MAX(b.id) FROM attempt b WHERE b.run_id = a.run_id AND b.stage = a.stage AND b.item = a.item)
  AND NOT EXISTS (SELECT 1 FROM attempt c WHERE c.stage = a.stage AND c.item = a.item AND c.outcome = 'ok' AND c.id > a.id)
ORDER BY a.id
"""
VERSIONS_OF = """
SELECT v.id, v.metric_text, v.unit_text FROM claim c
JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)
WHERE c.document_id = ? ORDER BY c.id
"""
ASSIGNED = ("metric_key", "rule", "unit_key", "unit_factor", "unit_source", "config_version")
CURRENT_ASSIGNMENTS = """
SELECT a.* FROM metric_assignment a JOIN claim_version v ON v.id = a.claim_version_id JOIN claim c ON c.id = v.claim_id
WHERE a.id IN (SELECT MAX(id) FROM metric_assignment GROUP BY claim_version_id) AND (? IS NULL OR c.document_id = ?)
"""


class _Doc:
    def __init__(self, doc: dict, versions):
        self.doc, self.versions = doc, versions
        self.version = version_of(*(v["id"] for v in versions))

    def __str__(self) -> str:
        return str(self.doc["id"])


def assign(metric_text, unit_text) -> tuple:
    """The assignment values (metric_key, rule, unit_key, unit_factor, unit_source) of one claim version."""
    return (*metric_of(metric_text, unit_text), *unit_of(unit_text, metric_text))


def _work(run_id: int, item: _Doc, conn) -> dict:
    stamp, rows = store.now(), 0
    with store.transaction(conn):
        for v in item.versions:
            new = (*assign(v["metric_text"], v["unit_text"]), CONFIG)
            last = conn.execute(f"SELECT {', '.join(ASSIGNED)} FROM metric_assignment WHERE claim_version_id = ?"
                                " ORDER BY id DESC LIMIT 1", (v["id"],)).fetchone()
            if last is not None and tuple(last) == new:
                continue
            conn.execute(f"INSERT INTO metric_assignment (claim_version_id, {', '.join(ASSIGNED)}, run_id, created_at)"
                         f" VALUES (?, {', '.join('?' * len(ASSIGNED))}, ?, ?)", (v["id"], *new, run_id, stamp))
            rows += 1
    return {"claims": len(item.versions), "rows": rows}


def assignments(conn, doc_id=None) -> dict:
    """{claim version id: current assignment row} (of one document)."""
    return {r["claim_version_id"]: r for r in conn.execute(CURRENT_ASSIGNMENTS, (doc_id, doc_id))}


def _doc(d: dict, action: str, cause=None, next_action=None, **counts) -> dict:
    out = {"id": d["id"], "logical_name": d["logical_name"], "claims": 0, "matched": 0, "cached": 0, "failed": 0,
           "mapped": 0, "unmapped": 0, "unit_unknown": 0, "action": action, "cause": cause, "next_action": next_action}
    return {**out, **counts}


def _counts(conn, doc_id: int, versions) -> dict:
    current = assignments(conn, doc_id)
    rows = [current[v["id"]] for v in versions if v["id"] in current]
    return {"mapped": sum(r["metric_key"] is not None for r in rows),
            "unmapped": sum(r["metric_key"] is None for r in rows),
            "unit_unknown": sum(r["unit_key"] is None for r in rows)}


def _match(conn, run_id, docs) -> list[dict]:
    stage = Stage("match", CONFIG, lambda item, conn: _work(run_id, item, conn), lambda item: item.version)
    out = []
    for d in docs:
        versions = conn.execute(VERSIONS_OF, (d["id"],)).fetchall()
        if not versions:
            runs.event(conn, run_id, "note", stage="match", item=str(d["id"]), message=EXTRACT_FIRST)
            out.append(_doc(d, "skipped", "This document has no claims yet.", EXTRACT_FIRST))
            continue
        counts = run_stage(conn, run_id, stage, [_Doc(d, versions)])
        failed = counts["failed"]
        out.append(_doc(d, "matched", "The document could not be matched." if failed else None, RETRY if failed else None,
                        claims=len(versions), matched=counts["processed"], cached=counts["cached"], failed=failed,
                        **_counts(conn, d["id"], versions)))
    return out


def match(conn, root, ids=(), company=None, notes=()) -> tuple[int | None, list[dict]]:
    """Assign metric keys and units to the newest claims of the selection in one run."""
    docs = select(conn, ids, company)
    if not docs:
        return None, []
    with runs.run(conn, "match") as run_id:
        runs.record(conn, run_id, {"ids": list(ids), "company": company}, notes)
        out = [_doc(d, "skipped", NOT_ACTIVE) for d in docs if d["state"] not in ACTIVE]
        out += _match(conn, run_id, [d for d in docs if d["state"] in ACTIVE])
    return run_id, out


def failed(conn, run_id: int) -> dict:
    """{document id: None} for the documents whose matching failed in the run and has not succeeded since."""
    return {int(item): None for (item,) in conn.execute(FAILED_SQL, (run_id,))}


def retry(conn, root, wanted: dict, notes=()) -> tuple[int, list[dict]]:
    """Match again exactly the failed documents in a new run. A document no longer active is skipped."""
    docs = [registry.show_document(conn, i) for i in wanted]
    active = [d for d in docs if d["state"] in ACTIVE]
    with runs.run(conn, "match") as run_id:
        runs.record(conn, run_id, {"ids": [d["id"] for d in active], "company": None}, notes)
        out = [_doc(d, "skipped", NOT_ACTIVE) for d in docs if d["state"] not in ACTIVE]
        out += _match(conn, run_id, active)
    return run_id, out


# Series, uncertain items and match states, computed on read from current assignments, infer.effective and claim
# states; never stored in workspace.db.

SERIES, REVIEWED, UNCERTAIN, NOT_MATCHABLE = "series", "reviewed", "uncertain", "not matchable"
STATES = (SERIES, REVIEWED, UNCERTAIN, NOT_MATCHABLE)
NOT_CURRENT = "not current"
NOT_MAPPED = "not mapped yet: gct match"
PERIOD_UNKNOWN = "period unknown"
NO_LABEL = "no metric label"
OUTSIDE_ROW = "unmapped outside a table row"
BOUNDARY_UNKNOWN = "boundary unknown"
UNIT_UNKNOWN = "unit unknown"
NOT_CONVERTIBLE = "unit not convertible"
NO_SERIES = ", no series to join"
NOT_LINKED = "not linked by review"
AS_PRINTED = "unit as printed"
KNOWN = ("resolved", "accepted")
# The conversion families each metric key accepts; an unmapped doc: label takes any family.
ACCEPTS = {**dict.fromkeys(("ghg_scope_1", "ghg_scope_2", "ghg_scope_1_2", "ghg_scope_3"), ("tco2e", "tco2")),
           **dict.fromkeys(("energy_total", "energy_renewable", "energy_non_renewable"), ("gj",)),
           **dict.fromkeys(("water_withdrawal_total", "water_consumption_total", "water_discharge_total"), ("kl",)),
           "waste_total": ("t",)}
NEWEST_REVIEWS = """
SELECT r.*, c.name, c.organisation FROM match_review r JOIN contributor_version c ON c.id = r.contributor_version_id
WHERE r.id IN (SELECT MAX(id) FROM match_review GROUP BY claim_version_id, series_key)
"""
CLAIMS_OF = """
SELECT c.id AS claim_id, c.company_id, c.document_id, c.page_number, c.locator, v.id AS claim_version_id, v.metric_text,
       v.value_text, v.value, v.unit_text
FROM claim c JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)
WHERE c.document_id = ? ORDER BY c.id
"""


def series_id(key: list) -> str:
    return infer.group_id(json.dumps(key, ensure_ascii=False))


def _row(locator: str) -> str | None:
    """The printed table row (tNrR) of a table cell locator tNrRcC, else None."""
    m = re.match(r"(t\d+r\d+)c\d+", locator)
    return m and m.group(1)


def _series(key: list) -> dict:
    company, metric, boundary, detail, family, doc, kind = key[:7]  # a unit as printed key adds its page and row
    unmapped = metric.startswith("doc:")
    return {"id": series_id(key), "key": json.dumps(key, ensure_ascii=False), "company_id": company,
            "metric_key": None if unmapped else metric, "label": metric.split(":", 4)[4] if unmapped else None,
            "document_id": doc, "reporting_boundary": boundary, "boundary_detail": detail, "unit_family": family,
            "period_kind": kind, "points": []}


def _point(c: dict, link: str, comparable: bool, reason=None) -> dict:
    number = c["value"] if c["value"] is not None else number_of(c["value_text"])
    base = number * c["unit_factor"] if comparable and number is not None and c["unit_factor"] else None
    return {"claim_id": c["claim_id"], "claim_version_id": c["claim_version_id"], "document_id": c["document_id"],
            "page_number": c["page_number"], "locator": c["locator"], "period_start": c["period"]["start"],
            "period_end": c["period"]["end"], "value_text": c["value_text"], "unit_text": c["unit_text"],
            "unit_key": c["unit_key"], "number": number, "value_base": base, "link": link, "comparable": comparable,
            "reason": reason, "review": c.get("review")}


def _claims(conn, docs) -> list[dict]:
    """Every newest claim version of the documents with its assignment, effective period and boundary and state."""
    current, out = assignments(conn), []
    for d in docs:
        eff, states = infer.effective(conn, d["id"]), correct.states(conn, d["id"])
        for r in conn.execute(CLAIMS_OF, (d["id"],)):
            a = current.get(r["claim_version_id"])
            out.append({**dict(r), "claim_state": states[r["claim_id"]], "period": eff[r["claim_id"]]["period"],
                        "boundary": eff[r["claim_id"]]["boundary"], "assigned": a is not None,
                        **{k: a and a[k] for k in ("metric_key", "rule", "unit_key", "unit_factor", "unit_source")},
                        "state": None, "reason": None, "series_id": None, "items": []})
    return out


def _state(c: dict, state: str, reason=None, sid=None) -> None:
    c.update(state=state, reason=reason, series_id=sid)


def compute(conn, company=None) -> dict:
    """{"claims": [claim records], "series": {series id: series with its points}} for the active documents (of one
    company). Every claim ends in exactly one state: series, reviewed, uncertain or not matchable."""
    claims, series, waiting = _claims(conn, select(conn, [], company)), {}, []
    for c in claims:
        if c["claim_state"] != "current":
            _state(c, NOT_MATCHABLE, NOT_CURRENT)
            continue
        if not c["assigned"]:
            _state(c, NOT_MATCHABLE, NOT_MAPPED)
            continue
        p, b = c["period"], c["boundary"]
        if p["state"] not in KNOWN:
            _state(c, NOT_MATCHABLE, PERIOD_UNKNOWN)
            continue
        label = key_label(c["metric_text"])
        if c["metric_key"] is None and not label:
            _state(c, NOT_MATCHABLE, NO_LABEL)
            continue
        row = _row(c["locator"])
        if c["metric_key"] is None and row is None:
            _state(c, NOT_MATCHABLE, OUTSIDE_ROW)
            continue
        c["metric"] = c["metric_key"] or f"doc:{c['document_id']}:p{c['page_number']}:{row}:{label}"
        c["boundary_known"] = b["state"] in KNOWN and b["boundary"] != "unknown"
        c["detail"] = scrub_key(b["detail"]) if b["boundary"] == "subsidiary_set" else None
        family = c["unit_key"]
        c["unit_ok"] = family is not None and (c["metric_key"] is None or family in ACCEPTS[c["metric_key"]])
        head = [c["company_id"], c["metric"], b["boundary"], c["detail"]]
        if c["boundary_known"] and c["unit_ok"]:
            key = head + [family, c["document_id"] if c["metric_key"] is None else None, p["kind"]]
            series.setdefault(series_id(key), _series(key))["points"].append(_point(c, "rule", True))
            _state(c, SERIES, sid=series_id(key))
            continue
        if c["boundary_known"] and row:  # a unit not usable across documents may still join the columns of its row
            c["printed"] = head + [f"printed:{key_unit(c['unit_text']) or '-'}", c["document_id"], p["kind"],
                                   f"p{c['page_number']}:{row}"]
        waiting.append(c)
    printed = {}
    for c in waiting:
        if "printed" in c:
            printed.setdefault(series_id(c["printed"]), []).append(c)
    rest = []
    for c in waiting:
        group = printed.get(series_id(c["printed"])) if "printed" in c else None
        if group and len(group) > 1:
            s = series.setdefault(series_id(c["printed"]), _series(c["printed"]))
            s["points"].append(_point(c, "rule", False, AS_PRINTED))
            _state(c, SERIES, sid=s["id"])
        else:
            rest.append(c)
    reviews = {(r["claim_version_id"], r["series_key"]): r for r in conn.execute(NEWEST_REVIEWS)}
    for c in rest:
        reason = BOUNDARY_UNKNOWN if not c["boundary_known"] else UNIT_UNKNOWN if c["unit_key"] is None else NOT_CONVERTIBLE
        candidates = [s for s in series.values() if _candidate(c, s)]
        if not candidates:
            _state(c, NOT_MATCHABLE, reason + NO_SERIES)
            continue
        c["candidates"], c["item_reason"] = {s["id"]: s["key"] for s in candidates}, reason
        decided = {s["id"]: reviews.get((c["claim_version_id"], s["key"])) for s in candidates}
        c["decided"] = {i: r and r["decision"] for i, r in decided.items()}
        linked = next((s for s in candidates if decided[s["id"]] and decided[s["id"]]["decision"] == "linked"), None)
        if linked:
            c["review"] = _review(decided[linked["id"]])
            linked["points"].append(_point(c, "reviewed", False, reason))
            _state(c, REVIEWED, reason, linked["id"])
            continue
        c["items"] = [{"series_id": s["id"], "reason": reason} for s in candidates if not decided[s["id"]]]
        if c["items"]:
            _state(c, UNCERTAIN, reason)
        else:
            _state(c, NOT_MATCHABLE, NOT_LINKED)
    for s in series.values():
        s["points"].sort(key=lambda x: (x["period_end"], x["period_start"], x["document_id"], x["claim_id"]))
        ends = [x["period_end"] for x in s["points"]]
        spans = {(x["period_start"], x["period_end"]) for x in s["points"]}
        s.update(periods=len(spans), latest_period_end=max(ends))
    return {"claims": claims, "series": series}


def _candidate(c: dict, s: dict) -> bool:
    """A series the claim could join after review: same company, metric and period kind, and, when the claim's own
    boundary is known, the same boundary (and detail); when its unit is known and accepted, the same family (never a
    unit as printed series). Only rule points make a series exist."""
    key = json.loads(s["key"])
    if (key[0], key[1], key[6]) != (c["company_id"], c["metric"], c["period"]["kind"]):
        return False
    if c["unit_ok"] and key[4] != c["unit_key"]:
        return False
    return not c["boundary_known"] or (key[2], key[3]) == (c["boundary"]["boundary"], c["detail"])


def _review(r) -> dict:
    return {"decision": r["decision"], "contributor": r["name"], "organisation": r["organisation"],
            "capacity": r["capacity"], "rationale": r["rationale"], "created_at": r["created_at"]}


# Reading the result: series, the review queue, counts.

REVIEW = "See the review queue with: gct match review"


def _named(conn, s: dict, points=None) -> dict:
    """A series record for output: its fields, company name, and points (default: all), each with how many points
    share its period."""
    shared = Counter((x["period_start"], x["period_end"]) for x in s["points"])
    pts = [{**x, "same_period": shared[(x["period_start"], x["period_end"])]} for x in (s["points"] if points is None else points)]
    name = conn.execute("SELECT name FROM company WHERE id = ?", (s["company_id"],)).fetchone()[0]
    return {**{k: v for k, v in s.items() if k not in ("key", "points")}, "company": name, "points": pts,
            "same_period_sets": sum(n > 1 for n in shared.values())}


def _latest(s: dict) -> list[dict]:
    return [x for x in s["points"] if x["period_end"] == s["latest_period_end"]]


def series_list(conn, company=None, metric=None) -> list[dict]:
    """One record per series, with the points of its latest period (the newest period end)."""
    out = [_named(conn, s, _latest(s)) for s in compute(conn, company)["series"].values()
           if metric is None or s["metric_key"] == metric]
    return sorted(out, key=lambda s: (s["company_id"], s["metric_key"] or "~", s["label"] or "", s["reporting_boundary"],
                                      s["unit_family"], s["period_kind"], s["id"]))


def series_show(conn, sid: str, every=False) -> dict:
    """One series: the latest period's points, or every period oldest first."""
    s = compute(conn)["series"].get(sid)
    if s is None:
        raise GctError(NOT_FOUND, f"There is no series {sid}.", "See the series with: gct series list")
    return _named(conn, s, None if every else _latest(s))


def queue(conn, company=None, reason=None) -> list[dict]:
    """The uncertain items: one per claim version and candidate series."""
    r = compute(conn, company)
    return [{"claim": c["claim_id"], "version": c["claim_version_id"], "document": c["document_id"],
             "page_number": c["page_number"], "metric_text": c["metric_text"], "value_text": c["value_text"],
             "unit_text": c["unit_text"], "reason": i["reason"], "series": i["series_id"],
             "metric_key": r["series"][i["series_id"]]["metric_key"], "label": r["series"][i["series_id"]]["label"],
             "reporting_boundary": r["series"][i["series_id"]]["reporting_boundary"],
             "boundary_detail": r["series"][i["series_id"]]["boundary_detail"]}
            for c in r["claims"] for i in c["items"] if reason is None or i["reason"] == reason]


def status(conn, company=None) -> list[dict]:
    """Counts per company of the active documents' newest claims."""
    r, out = compute(conn, company), {}
    names = dict(conn.execute("SELECT id, name FROM company"))
    for c in r["claims"]:
        s = out.setdefault(c["company_id"], {
            "company": names[c["company_id"]], "claims": 0, "mapped": Counter(), "unmapped": 0, "unit_unknown": 0,
            "not_mapped_yet": 0, "series": 0, "same_period_sets": 0, "uncertain_items": 0,
            "states": Counter(), "not_matchable": Counter()})
        s["claims"] += 1
        if not c["assigned"]:
            s["not_mapped_yet"] += 1
        elif c["metric_key"]:
            s["mapped"][c["metric_key"]] += 1
        else:
            s["unmapped"] += 1
        s["unit_unknown"] += c["assigned"] and c["unit_key"] is None
        s["uncertain_items"] += len(c["items"])
        s["states"][c["state"]] += 1
        if c["state"] == NOT_MATCHABLE:
            s["not_matchable"][c["reason"]] += 1
    for x in r["series"].values():
        s = out[x["company_id"]]
        s["series"] += 1
        s["same_period_sets"] += _named(conn, x)["same_period_sets"]
    return [{**s, **{k: dict(sorted(s[k].items())) for k in ("mapped", "states", "not_matchable")}}
            for _, s in sorted(out.items())]


def _decide(conn, claim_id: int, sid: str, decision: str, key, capacity, rationale) -> dict:
    who, capacity, rationale = infer._who(conn, key, capacity, rationale)
    row = conn.execute("SELECT c.company_id, m.name FROM claim c JOIN company m ON m.id = c.company_id WHERE c.id = ?",
                       (claim_id,)).fetchone()
    if row is None:
        raise GctError(NOT_FOUND, f"There is no claim {claim_id}.", "See the claims with: gct claims list --doc ID")

    def claim():
        return next((c for c in compute(conn, row["name"])["claims"] if c["claim_id"] == claim_id), None)

    c = claim()
    if c is None or sid not in c.get("candidates", {}):
        raise GctError(REFUSED, f"Claim {claim_id} has no uncertain item for series {sid}.", REVIEW)
    verb = "link" if decision == "linked" else "unlink"
    if decision == "linked" and c["state"] == REVIEWED and c["series_id"] != sid:
        raise GctError(REFUSED, f"Claim {claim_id} is already linked to series {c['series_id']}; a claim is in one series"
                                " at most.", f"Unlink it first: gct match unlink {claim_id} --series {c['series_id']}"
                                             " --as KEY --capacity TEXT --rationale TEXT")
    if c["decided"][sid] == decision:
        raise GctError(REFUSED, f"Claim {claim_id} is already {decision.replace('_', ' ')} for series {sid}, so there is"
                                f" nothing to {verb}.", REVIEW)
    reason = c["item_reason"]
    with store.transaction(conn):
        conn.execute("INSERT INTO match_review (claim_version_id, series_key, reason, decision, contributor_version_id,"
                     " capacity, rationale, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (c["claim_version_id"], c["candidates"][sid], reason, decision, who["version"], capacity, rationale,
                      store.now()))
    c = claim()
    return {"claim": claim_id, "version": c["claim_version_id"], "series": sid, "decision": decision,
            "match_state": c["state"], "match_reason": c["reason"], "series_id": c["series_id"],
            "by": {"contributor": who["name"], "organisation": who["organisation"], "capacity": capacity,
                   "rationale": rationale}}


def link_claim(conn, claim_id: int, sid: str, key, capacity, rationale) -> dict:
    """Put an uncertain claim in a candidate series as a reviewed, not comparable point."""
    return _decide(conn, claim_id, sid, "linked", key, capacity, rationale)


def unlink_claim(conn, claim_id: int, sid: str, key, capacity, rationale) -> dict:
    """Take a candidate series off a claim's review queue (or undo a link to it)."""
    return _decide(conn, claim_id, sid, "not_linked", key, capacity, rationale)


def metrics() -> dict:
    """The metric list and unit table with their versions (gct match metrics)."""
    return {"rules_version": RULES_VERSION, "metrics_version": METRICS_VERSION, "units_version": UNITS_VERSION,
            "excluded": list(EXCLUDED),
            "metrics": [{"key": k, "must": list(must), "never": list(never)} for k, must, never in METRICS],
            "units": [{"text": t, "base": f, "factor": n} for t, (f, n) in UNITS.items()],
            "prefixes": [{"text": t, "factor": n} for t, n in PREFIXES.items()]}
