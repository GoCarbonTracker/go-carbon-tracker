"""Period and boundary inference (FR5): fixed rules propose a claim's period and reporting boundary from source text
only, beside the claim version, for a contributor to accept, resolve or reject. Never from company identity, the
document name or a document-wide default; a boundary statement covers only the pages a contributor declares (B3)."""
import hashlib
import json
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from gct.stages import Result, Stage, run_stage, version_of
from gct.stages.extract import FAILED_PAGES_SQL, _clean
from gct.stages.link import EXTRACT_FIRST
from gct.stages.missing import _text, contributor, page_count
from gct.stages.read import ACTIVE, NEWEST_SQL, NOT_ACTIVE, select
from gct.workspace import registry, runs, store
from gct.workspace.layout import NOT_FOUND, REFUSED, USAGE, GctError

METHOD = "infer-rules"
RULES_VERSION = 1
CONFIG = version_of("infer", 1, RULES_VERSION)
KINDS = ("fiscal_year", "calendar_year", "half", "quarter", "as_at")
BOUNDARIES = ("standalone", "subsidiary_set", "consolidated")
FIELDS = ("period", "boundary")
STATES = ("resolved", "accepted", "proposed", "unresolved", "extracted")
RETRY = "Run gct infer again. Documents whose claims, readings and declared ranges have not changed are not inferred twice."
GROUPS = "See the groups with: gct infer groups"
FAILED_SQL = FAILED_PAGES_SQL.replace("a.stage = 'extract'", "a.stage = 'infer'")

NO_LABEL = "no period label"
BARE = "bare year"
PART_ONLY = "quarter or half without a year"
NOT_RECOGNISED = "label not recognised"
AMBIGUOUS = "numeric date order ambiguous"
INVALID = "date not valid"
SPAN = "span is not a year, half or quarter"
NOT_CONSECUTIVE = "label years not consecutive"
NO_FY = "no fiscal year statement in this document"
NO_SCOPE = "no boundary statement covers this page"
NO_ANSWER = "heading without a readable answer"
REJECTED = "rejected"

NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
         "november", "december")
MONTHS = {**{n: i for i, n in enumerate(NAMES, 1)}, **{n[:3]: i for i, n in enumerate(NAMES, 1)}, "sept": 9}
MON = rf"(?:{'|'.join(sorted(MONTHS, key=len, reverse=True))})\b\.?"
ORD = r"(?:st|nd|rd|th)?"
# A date as printed: 31st March, 2025 | March 31, 2024 | 31 March 2024 | 31-03-2025. No groups, so it composes.
DATE = rf"(?:\d{{1,2}}{ORD}\s+{MON},?\s+\d{{4}}|{MON}\s+\d{{1,2}}{ORD},?\s+\d{{4}}|\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{4}})"
RANGE = re.compile(rf"({DATE})\s+to\s+({DATE})", re.I)
YEAR_ENDED = re.compile(rf"year\s+ended\s+({DATE})", re.I)
AS_AT = re.compile(rf"as\s+(?:at|on)\s+({DATE})", re.I)
PART = r"[QH][1-4]"
CY = re.compile(rf"(?:(?P<p>{PART})\s*)?(?:CY\s?'?(?P<y>\d{{4}}|\d{{2}})|calendar\s+year\s+(?P<y4>\d{{4}}))(?:\s*(?P<q>{PART}))?", re.I)
FY = re.compile(rf"(?:(?P<p>{PART})\s*)?(?:FY\s?'?(?P<a>\d{{4}}|\d{{2}})(?:\s?[-–/]\s?(?P<b>\d{{4}}|\d{{2}}))?"
                rf"|(?P<c>\d{{4}})\s?[-–]\s?(?P<d>\d{{4}}|\d{{2}}))(?:\s*(?P<q>{PART}))?", re.I)
# Fiscal-year-end statements: a financial/fiscal year or FY with "ended <date>" or "<date> to <date>", in one sentence.
FY_WORD = r"(?:(?:financial|fiscal)\s+year|\bFY\b)"
FY_ENDED = re.compile(rf"{FY_WORD}[^.]{{0,40}}?\b(?:ended|ending)(?:\s+on)?\s+({DATE})", re.I)
FY_RANGE = re.compile(rf"{FY_WORD}[^.]{{0,80}}?({DATE})\s+to\s+({DATE})|({DATE})\s+to\s+({DATE})[^.]{{0,80}}?{FY_WORD}", re.I)
# Boundary statements (B1). The BRSR item-13 question names both bases, so it is removed before anything is read.
QUESTION = re.compile(r"are\s+the\s+disclosures\s+under\s+this\s+report\s+made\s+on\s+a\s+standalone\s+basis.{0,400}?"
                      r"consolidated\s+basis(?:\s*\([^)]*\))?\.?", re.I | re.S)
B1 = re.compile(r"\b(?:prepared|reports?|reporting)\b[^.]{0,80}?\bon\s+an?\s+(standalone|consolidated)\s+basis"
                r"(?:\s*,?\s*i\.\s?e[.,]+\s*(?P<detail>[^.]+))?", re.I)
COMBINED = re.compile(r"combin\w*\s+the\s+information\s+of[^.]+", re.I)
HEADING = re.compile(r"reporting\s+boundary", re.I)
SHORTER = r"\b(?:half|quarter|months?)\b"  # a period shorter than a year


class Unresolved(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# Dates.

def _date(text: str) -> date:
    """One printed date. All-numeric is day first, and only when the first number is above 12."""
    nums = [int(n) for n in re.findall(r"\d+", text)]
    word = re.search(r"[A-Za-z]{3,}", text)
    if word:
        (day, year), month = nums, MONTHS[word[0].lower()]
    else:
        day, month, year = nums
        if day <= 12:
            raise Unresolved(AMBIGUOUS if month <= 12 else INVALID)
    try:
        return date(year, month, day)
    except ValueError:
        raise Unresolved(INVALID) from None


def _add_months(d: date, n: int) -> date:
    """The first day of the month n months after d's month."""
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def _span(start: date, end: date) -> tuple[str, date, date]:
    """A printed range by its dates alone: a year, a half or a quarter from the first of a month to a month end."""
    months = (end.year * 12 + end.month) - (start.year * 12 + start.month)
    size = {11: "year", 5: "half", 2: "quarter"}.get(months)
    if start.day != 1 or (end + timedelta(days=1)).day != 1 or size is None:
        raise Unresolved(SPAN)
    if size == "year":
        size = "calendar_year" if start.month == 1 else "fiscal_year"
    return size, start, end


def _year_to(end: date) -> tuple[str, date, date]:
    """The year that ends on end: calendar_year when it ends on 31 December, else fiscal_year."""
    before = date(end.year - 1, end.month, 28 if (end.month, end.day) == (2, 29) else end.day)
    return ("calendar_year" if (end.month, end.day) == (12, 31) else "fiscal_year"), before + timedelta(days=1), end


def _part(part, kind: str, start: date, end: date) -> tuple[str, date, date]:
    """The quarter or half named by part (Q1..Q4, H1..H2) of the year from start to end, or the year itself."""
    if part is None:
        return kind, start, end
    months, kind = (3, "quarter") if part[0].upper() == "Q" else (6, "half")
    n = int(part[1])
    if n > 12 // months:
        raise Unresolved(NOT_RECOGNISED)
    if start.day != 1:
        raise Unresolved("the fiscal year does not start on the first of a month")
    first = _add_months(start, (n - 1) * months)
    return kind, first, _add_months(first, months) - timedelta(days=1)


def _year(s: str) -> int:
    return int(s) if len(s) == 4 else 2000 + int(s)


# Rules: detection and resolution, one function per kind.

def period_of(label, bases) -> tuple[str, date, date, dict | None]:
    """(kind, start, end, basis) for a period label as stored; basis is None when the label is its own source (P1,
    P2c). bases are the document's fiscal-year-end statements (P2, P2b). Raises Unresolved with the reason (P3)."""
    text = _clean(label)
    if not text:
        raise Unresolved(NO_LABEL)
    if m := RANGE.search(text):
        return (*_span(_date(m[1]), _date(m[2])), None)
    if m := YEAR_ENDED.search(text):
        if re.search(SHORTER, text[:m.start()], re.I):
            raise Unresolved(NOT_RECOGNISED)  # "half year ended", "quarter and year ended": no dates of its own
        return (*_year_to(_date(m[1])), None)
    if m := AS_AT.search(text):
        d = _date(m[1])
        return "as_at", d, d, None
    if m := CY.fullmatch(text):
        if m["p"] and m["q"]:
            raise Unresolved(NOT_RECOGNISED)
        year = _year(m["y"] or m["y4"])
        return (*_part(m["p"] or m["q"], "calendar_year", date(year, 1, 1), date(year, 12, 31)), None)
    if m := FY.fullmatch(text):
        if m["p"] and m["q"]:
            raise Unresolved(NOT_RECOGNISED)
        first, second = (m["a"], m["b"]) if m["a"] else (m["c"], m["d"])
        year = _year(first)
        if second is not None:
            following = int(second) if len(second) == 4 else year + 1 if int(second) == (year + 1) % 100 else 0
            if following != year + 1:
                raise Unresolved(NOT_CONSECUTIVE)
            year = following
        basis = _fiscal_basis(bases)
        month, day = map(int, basis["fy_end"].split("-"))
        try:
            end = date(year, month, day)
        except ValueError:
            raise Unresolved(INVALID) from None
        return (*_part(m["p"] or m["q"], *_year_to(end)), basis)
    if re.fullmatch(DATE, text, re.I):
        _date(text)  # an ambiguous or impossible date says so
        raise Unresolved(NOT_RECOGNISED)
    if re.fullmatch(r"\d{4}", text):
        raise Unresolved(BARE)
    if re.fullmatch(PART, text, re.I):
        raise Unresolved(PART_ONLY)
    raise Unresolved(NOT_RECOGNISED)


def _fiscal_basis(bases) -> dict:
    """The one fiscal-year-end statement (statements agreeing on one year end count as one; the lowest id stands)."""
    if not bases:
        raise Unresolved(NO_FY)
    pages = {}
    for b in sorted(bases, key=lambda b: b["page_number"]):
        pages.setdefault(b["fy_end"], b["page_number"])
    if len(pages) > 1:
        first, second = sorted(pages.values())[:2]
        raise Unresolved(f"fiscal year end conflict: p{first} and p{second}")
    return min(bases, key=lambda b: b["id"])


def boundary_of(page: int, scoped) -> tuple[str, str | None, dict]:
    """(boundary, detail, basis) for a claim on page from the boundary statements whose declared range covers it (B3)."""
    covering = sorted((b for b in scoped if b["first_page"] <= page <= b["last_page"]), key=lambda b: b["id"])
    if not covering:
        raise Unresolved(NO_SCOPE)
    first = {}
    for b in covering:
        first.setdefault((b["boundary"], b["boundary_detail"]), b["id"])
    if len(first) > 1:
        a, b = sorted(first.values())[:2]
        raise Unresolved(f"boundary conflict: basis #{a} and #{b}")
    return covering[0]["boundary"], covering[0]["boundary_detail"], covering[0]


def bases_of(reading: dict) -> tuple[list[dict], bool]:
    """(statements, heading without a readable answer) on one page reading. Bare words never count (B2)."""
    text = _clean(reading["text"])
    found = []
    for m in FY_ENDED.finditer(text):
        if re.search(SHORTER, m[0], re.I):
            continue  # "FY 2023-24: the quarter ended June 30" states no year end
        try:
            end = _date(m[1])
        except Unresolved:
            continue
        found.append({"kind": "fiscal_year_end", "wording": _clean(m[0]), "fy_end": f"{end:%m-%d}"})
    for m in FY_RANGE.finditer(text):
        if re.search(SHORTER, m[0], re.I):
            continue
        try:
            kind, start, end = _span(_date(m[1] or m[3]), _date(m[2] or m[4]))
        except Unresolved:
            continue
        if kind in ("fiscal_year", "calendar_year"):
            found.append({"kind": "fiscal_year_end", "wording": _clean(m[0]), "fy_end": f"{end:%m-%d}",
                          "period_start": start.isoformat(), "period_end": end.isoformat()})
    answers = QUESTION.sub(" ", text)
    for m in B1.finditer(answers):
        if re.search(r"disclosures\s+under\s+this\s*$", answers[max(0, m.start() - 40):m.start()], re.I):
            continue  # the rest of a question the removal did not catch
        if re.search(r"\b(?:not|no|never)\b", answers[max(answers.rfind(s, 0, m.start()) for s in (". ", ", ", "; ")) + 1:m.start(1)], re.I):
            continue  # "not required to report on a consolidated basis" in the same clause states no boundary
        boundary, detail, wording = m[1].lower(), m["detail"] and _clean(m["detail"]).rstrip(" ,;:"), m[0]
        stop = answers.find(". ", m.end())
        sentence = answers[m.start():stop if stop >= 0 else None]
        if c := COMBINED.search(sentence):
            boundary, detail, wording = "subsidiary_set", _clean(c[0]), sentence[:c.end()]
        found.append({"kind": "reporting_boundary", "wording": _clean(wording), "boundary": boundary,
                      "boundary_detail": detail or None})
    heading = bool(HEADING.search(answers)) and not any(f["kind"] == "reporting_boundary" for f in found)
    return found, heading


# The stage: one item per document.

CLAIMS_OF = """
SELECT c.id AS claim_id, c.page_number, v.id AS claim_version_id, v.period_label
FROM claim c JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)
WHERE c.document_id = ? ORDER BY c.id
"""
COMPARED = ("state", "period_kind", "period_start", "period_end", "boundary", "boundary_detail", "basis_id", "reason",
            "group_key", "config_version")


class _Doc:
    """A stage item: one document with the newest version of its claims and the newest reading of its pages."""

    def __init__(self, doc: dict, claims, pages, version: str):
        self.doc, self.claims, self.pages, self.version = doc, claims, pages, version

    def __str__(self) -> str:
        return str(self.doc["id"])


def _input(conn, doc_id: int, claims, pages) -> str:
    scopes = [r[0] for r in conn.execute("SELECT MAX(s.id) FROM basis_scope s JOIN basis b ON b.id = s.basis_id"
                                         " WHERE b.document_id = ? GROUP BY s.basis_id ORDER BY 1", (doc_id,))]
    return version_of(*(c["claim_version_id"] for c in claims), "pages", *(p["id"] for p in pages), "scopes", *scopes)


def _basis(conn, doc_id, page, b, run_id, stamp) -> dict:
    """The basis row for a statement; a re-run that finds the same statement reuses it."""
    conn.execute("INSERT OR IGNORE INTO basis (document_id, page_number, kind, wording, fy_end, period_start, period_end,"
                 " boundary, boundary_detail, run_id, config_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (doc_id, page, b["kind"], b["wording"], b.get("fy_end"), b.get("period_start"), b.get("period_end"),
                  b.get("boundary"), b.get("boundary_detail"), run_id, CONFIG, stamp))
    return dict(conn.execute("SELECT * FROM basis WHERE document_id = ? AND page_number = ? AND kind = ? AND wording = ?",
                             (doc_id, page, b["kind"], b["wording"])).fetchone())


def _scope(conn, basis_id: int):
    return conn.execute("SELECT * FROM basis_scope WHERE basis_id = ? ORDER BY id DESC LIMIT 1", (basis_id,)).fetchone()


def _inference(doc_id: int, field: str, rule, *args) -> dict:
    """The inference row values for one field: proposed with its values, or unresolved with the reason."""
    out = dict.fromkeys(COMPARED[:-2])
    try:
        values = rule(*args)
    except Unresolved as e:
        out.update(state="unresolved", reason=e.reason)
    else:
        if field == "period":
            kind, start, end, basis = values
            out.update(period_kind=kind, period_start=start.isoformat(), period_end=end.isoformat())
        else:
            boundary, detail, basis = values
            out.update(boundary=boundary, boundary_detail=detail)
        out.update(state="proposed", basis_id=basis and basis["id"])
    source = out["basis_id"] or ("label" if out["state"] == "proposed" else None)
    out["group_key"] = json.dumps([doc_id, field, out["state"], *(out[k] for k in COMPARED[1:6]), source, out["reason"]],
                                  ensure_ascii=False)
    return out


def _record(conn, cv: int, field: str, row: dict, run_id: int, stamp: str) -> bool:
    """Insert an inference row unless the newest one for the claim version and field says the same."""
    new = tuple(row[k] for k in COMPARED[:-1]) + (CONFIG,)
    last = conn.execute(f"SELECT {', '.join(COMPARED)} FROM inference WHERE claim_version_id = ? AND field = ?"
                        " ORDER BY id DESC LIMIT 1", (cv, field)).fetchone()
    if last is not None and tuple(last) == new:
        return False
    conn.execute(f"INSERT INTO inference (claim_version_id, field, {', '.join(COMPARED)}, run_id, created_at)"
                 f" VALUES (?, ?, {', '.join('?' * len(COMPARED))}, ?, ?)", (cv, field, *new, run_id, stamp))
    return True


def _work(root: Path, run_id: int, item: _Doc, conn) -> Result:
    doc_id, found, headings = item.doc["id"], [], []
    for p in item.pages:
        path = conn.execute("SELECT path FROM artifact WHERE id = ?", (p["artifact_id"],)).fetchone()[0]
        statements, heading = bases_of(json.loads((root / path).read_text(encoding="utf-8")))
        found += [(p["page_number"], s) for s in statements]
        headings += [p["page_number"]] * heading
    stamp, rows = store.now(), 0
    with store.transaction(conn):
        bases = list({b["id"]: b for b in (_basis(conn, doc_id, page, s, run_id, stamp) for page, s in found)}.values())
        fiscal = [b for b in bases if b["kind"] == "fiscal_year_end"]
        scoped = [{**b, "first_page": s["first_page"], "last_page": s["last_page"]}
                  for b in bases if b["kind"] == "reporting_boundary" and (s := _scope(conn, b["id"]))]
        for c in item.claims:
            for field, rule, arg in (("period", period_of, (c["period_label"], fiscal)),
                                     ("boundary", boundary_of, (c["page_number"], scoped))):
                rows += _record(conn, c["claim_version_id"], field, _inference(doc_id, field, rule, *arg), run_id, stamp)
    return Result(output={"claims": len(item.claims), "bases": [b["id"] for b in bases], "headings": headings,
                          "rows": rows}, method=METHOD)


def _doc(d: dict, action: str, cause=None, next_action=None, **counts) -> dict:
    out = {"id": d["id"], "logical_name": d["logical_name"], "claims": 0, "inferred": 0, "cached": 0, "failed": 0,
           "bases": 0, "headings": 0, "period": {}, "boundary": {}, "action": action, "cause": cause,
           "next_action": next_action}
    return {**out, **counts}


def _counts(conn, doc_id: int) -> dict:
    """{field: {state: n, ...}} with each unresolved reason counted as 'unresolved: <reason>'."""
    out = {f: Counter() for f in FIELDS}
    for e in effective(conn, doc_id).values():
        for f in FIELDS:
            out[f][e[f]["state"]] += 1
            if e[f]["state"] == "unresolved":
                out[f][f"unresolved: {e[f]['reason']}"] += 1
    return {f: dict(sorted(c.items())) for f, c in out.items()}


def _last(conn, doc_id: int) -> dict | None:
    """The output of the newest ok inference of the document, or None."""
    row = conn.execute("SELECT output FROM attempt WHERE stage = 'infer' AND item = ? AND outcome = 'ok'"
                       " ORDER BY id DESC LIMIT 1", (str(doc_id),)).fetchone()
    return row and json.loads(row[0])


def _infer(conn, root, run_id, docs) -> list[dict]:
    root = Path(root)
    stage = Stage("infer", CONFIG, lambda item, conn: _work(root, run_id, item, conn), lambda item: item.version)
    out = []
    for d in docs:
        claims = conn.execute(CLAIMS_OF, (d["id"],)).fetchall()
        if not claims:
            runs.event(conn, run_id, "note", stage="infer", item=str(d["id"]), message=EXTRACT_FIRST)
            out.append(_doc(d, "skipped", "This document has no claims yet.", EXTRACT_FIRST))
            continue
        pages = conn.execute(NEWEST_SQL, (None, None, d["id"])).fetchall()
        counts = run_stage(conn, run_id, stage, [_Doc(d, claims, pages, _input(conn, d["id"], claims, pages))])
        failed, last = counts["failed"], _last(conn, d["id"]) or {"bases": [], "headings": []}
        out.append(_doc(
            d, "inferred", "The document could not be inferred." if failed else None, RETRY if failed else None,
            claims=len(claims), inferred=counts["processed"], cached=counts["cached"], failed=failed,
            bases=len(last["bases"]), headings=len(last["headings"]), **_counts(conn, d["id"]),
        ))
    return out


def infer(conn, root, ids=(), company=None, notes=()) -> tuple[int | None, list[dict]]:
    """Find the statements and infer the newest claims of the selection in one run. Never opens a PDF."""
    docs = select(conn, ids, company)
    if not docs:
        return None, []
    with runs.run(conn, "infer") as run_id:
        runs.record(conn, run_id, {"ids": list(ids), "company": company}, notes)
        out = _infer(conn, root, run_id, docs)
    return run_id, out


def failed(conn, run_id: int) -> dict:
    """{document id: None} for the documents whose inference failed in the run and has not succeeded since."""
    return {int(item): None for (item,) in conn.execute(FAILED_SQL, (run_id,))}


def retry(conn, root, wanted: dict, notes=()) -> tuple[int, list[dict]]:
    """Infer again exactly the failed documents in a new run. A document no longer active is skipped."""
    docs = [registry.show_document(conn, i) for i in wanted]
    active = [d for d in docs if d["state"] in ACTIVE]
    with runs.run(conn, "infer") as run_id:
        runs.record(conn, run_id, {"ids": [d["id"] for d in active], "company": None}, notes)
        out = [_doc(d, "skipped", NOT_ACTIVE) for d in docs if d["state"] not in ACTIVE]
        out += _infer(conn, root, run_id, active)
    return run_id, out


# Effective values: what a claim's period and boundary are now, and why.

NEWEST_CV = """
SELECT v.id FROM claim c JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)
WHERE ? IS NULL OR c.document_id = ?
"""
CURRENT_CLAIMS = """
SELECT c.id AS claim_id, c.document_id, c.page_number, v.id AS claim_version_id, v.period_label, v.period_kind,
       v.period_start, v.period_end, v.reporting_boundary AS boundary, v.boundary_detail
FROM claim c JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)
WHERE ? IS NULL OR c.document_id = ? ORDER BY c.id
"""
CURRENT_INFERENCES = f"""
SELECT i.*, b.page_number AS basis_page, b.wording AS basis_wording, b.kind AS basis_kind
FROM inference i LEFT JOIN basis b ON b.id = i.basis_id
WHERE i.id IN (SELECT MAX(id) FROM inference WHERE claim_version_id IN ({NEWEST_CV}) GROUP BY claim_version_id, field)
"""
NEWEST_REVIEWS = f"""
SELECT r.*, c.name, c.organisation FROM inference_review r JOIN contributor_version c ON c.id = r.contributor_version_id
WHERE r.id IN (SELECT MAX(id) FROM inference_review WHERE claim_version_id IN ({NEWEST_CV})
               GROUP BY claim_version_id, field)
"""
VALUES = {"period": ("period_kind", "period_start", "period_end"), "boundary": ("boundary", "boundary_detail")}
KEYS = {"period": ("kind", "start", "end"), "boundary": ("boundary", "detail")}


def _current(conn, doc_id=None):
    """(claim row, field, current inference or None, newest review that applies or None) per newest claim version.
    A resolution always applies; an acceptance or rejection only to the inference it was given on."""
    infs = {(r["claim_version_id"], r["field"]): r for r in conn.execute(CURRENT_INFERENCES, (doc_id, doc_id))}
    revs = {(r["claim_version_id"], r["field"]): r for r in conn.execute(NEWEST_REVIEWS, (doc_id, doc_id))}
    for c in conn.execute(CURRENT_CLAIMS, (doc_id, doc_id)).fetchall():
        for f in FIELDS:
            inf, rev = infs.get((c["claim_version_id"], f)), revs.get((c["claim_version_id"], f))
            if rev and rev["decision"] != "resolved" and (inf is None or rev["inference_id"] != inf["id"]):
                rev = None
            yield c, f, inf, rev


def group_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _review(rev) -> dict | None:
    return rev and {"decision": rev["decision"], "contributor": rev["name"], "organisation": rev["organisation"],
                    "capacity": rev["capacity"], "rationale": rev["rationale"], "created_at": rev["created_at"]}


def _field(c, f: str, inf, rev) -> dict:
    """The effective record of one field of one claim."""
    own, reason = [c[k] for k in VALUES[f]], None
    if rev and rev["decision"] == "resolved":
        state, values = "resolved", [rev[k] for k in VALUES[f]]
    elif inf is None:
        state, values = "extracted", own
    elif rev and rev["decision"] == "accepted":
        state, values = "accepted", [inf[k] for k in VALUES[f]]
    elif rev:  # rejected: the claim stays unknown
        state, values, reason = "unresolved", own, REJECTED
    else:
        state, reason = inf["state"], inf["reason"]
        values = [inf[k] for k in VALUES[f]] if state == "proposed" else own
    basis = inf and inf["basis_id"] and state in ("proposed", "accepted") and {
        "id": inf["basis_id"], "page": inf["basis_page"], "wording": inf["basis_wording"]}
    out = {"state": state, **dict(zip(KEYS[f], values))}
    if f == "period":
        out["label"] = c["period_label"]
    return {**out, "reason": reason, "basis": basis or None, "group": inf and group_id(inf["group_key"]),
            "review": _review(rev)}


def effective(conn, doc_id=None) -> dict:
    """{claim id: {"period": record, "boundary": record}} for the newest version of each claim (of one document)."""
    out = {}
    for c, f, inf, rev in _current(conn, doc_id):
        out.setdefault(c["claim_id"], {})[f] = _field(c, f, inf, rev)
    return out


# Review: page ranges, groups, accept, resolve, reject.

def _who(conn, key, capacity, rationale) -> tuple[dict, str, str]:
    return (contributor(conn, key), _text(capacity, "capacity", '--capacity "sustainability analyst"'),
            _text(rationale, "rationale", '--rationale "checked on the page"'))


def _basis_record(conn, b) -> dict:
    s = conn.execute("SELECT s.*, c.name FROM basis_scope s JOIN contributor_version c ON c.id = s.contributor_version_id"
                     " WHERE s.basis_id = ? ORDER BY s.id DESC LIMIT 1", (b["id"],)).fetchone()
    return {"id": b["id"], "document": b["document_id"], "page": b["page_number"], "kind": b["kind"],
            "wording": b["wording"], "year_end": b["fy_end"], "start": b["period_start"], "end": b["period_end"],
            "boundary": b["boundary"], "detail": b["boundary_detail"],
            "scope": s and {"first": s["first_page"], "last": s["last_page"], "contributor": s["name"],
                            "capacity": s["capacity"], "rationale": s["rationale"], "created_at": s["created_at"]}}


def bases(conn, doc_id=None) -> tuple[list[dict], list[dict]]:
    """(statements, pages with a boundary heading but no readable answer) found by the newest gct infer of each
    active document (or of one document)."""
    out, headings = [], []
    for d in select(conn, [doc_id] if doc_id else [], None):
        last = _last(conn, d["id"])
        if last is None:
            continue
        out += [_basis_record(conn, conn.execute("SELECT * FROM basis WHERE id = ?", (i,)).fetchone()) for i in last["bases"]]
        headings += [{"document": d["id"], "page": p, "reason": NO_ANSWER} for p in last["headings"]]
    return out, headings


def scope(conn, root, basis_id: int, pages: str, key: str, capacity: str, rationale: str) -> dict:
    """Declare the pages a boundary statement covers. Takes effect at the next gct infer."""
    who, capacity, rationale = _who(conn, key, capacity, rationale)
    b = conn.execute("SELECT * FROM basis WHERE id = ?", (basis_id,)).fetchone()
    if b is None:
        raise GctError(NOT_FOUND, f"There is no statement #{basis_id}.", "See the statements with: gct infer bases")
    if b["kind"] != "reporting_boundary":
        raise GctError(REFUSED, f"Statement #{basis_id} is a fiscal year end. Only a boundary statement covers a page range.",
                       "See the boundary statements with: gct infer bases")
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", pages)
    if not m:
        raise GctError(USAGE, f"{pages} is not a page range.", "Give pages like 167-262, or one page like 4.")
    first, last = int(m[1]), int(m[2] or m[1])
    n, why = page_count(root, registry.show_document(conn, b["document_id"]))
    if n is None or not 1 <= first <= last <= n:
        raise GctError(REFUSED, f"Pages {pages} are not a range in document {b['document_id']}"
                                + (f", which has {n} pages." if n else f" ({why})."),
                       f"Give a first page no larger than the last, from 1 to {n}." if n else "Only PDF documents have pages.")
    with store.transaction(conn):
        conn.execute("INSERT INTO basis_scope (basis_id, first_page, last_page, contributor_version_id, capacity, rationale,"
                     " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (basis_id, first, last, who["version"], capacity, rationale, store.now()))
    return _basis_record(conn, b)


def _group(d: int, f: str, inf) -> dict:
    return {"id": group_id(inf["group_key"]), "document": d, "field": f, "state": inf["state"],
            "kind": inf["period_kind"], "start": inf["period_start"], "end": inf["period_end"],
            "boundary": inf["boundary"], "detail": inf["boundary_detail"], "reason": inf["reason"],
            "basis": inf["basis_id"] and {"id": inf["basis_id"], "page": inf["basis_page"], "wording": inf["basis_wording"],
                                          "kind": inf["basis_kind"]},
            "claims": 0, "reviews": {"accepted": 0, "resolved": 0, "rejected": 0, "open": 0}}


def _members(conn, doc_id=None):
    """(document id, claim row, field, inference, review) for the current inferences of active documents."""
    active = {d["id"] for d in select(conn, [doc_id] if doc_id else [], None) if d["state"] in ACTIVE}
    for c, f, inf, rev in _current(conn, doc_id):
        if inf is not None and c["document_id"] in active:
            yield c["document_id"], c, f, inf, rev


def groups(conn, doc_id=None, state=None) -> list[dict]:
    """One record per group: claims whose current inference was derived the same way to the same result."""
    out = {}
    for d, c, f, inf, rev in _members(conn, doc_id):
        if state and inf["state"] != state:
            continue
        g = out.setdefault(inf["group_key"], _group(d, f, inf))
        g["claims"] += 1
        g["reviews"][rev["decision"] if rev else "open"] += 1
    return sorted(out.values(), key=lambda g: (g["document"], g["field"], g["state"], -g["claims"], g["id"]))


def _in_group(conn, gid: str):
    rows = [(d, c, f, inf, rev) for d, c, f, inf, rev in _members(conn) if group_id(inf["group_key"]) == gid]
    if not rows:
        raise GctError(NOT_FOUND, f"There is no group {gid}.", GROUPS)
    return rows


def _review_rows(conn, rows, decision: str, who, capacity, rationale) -> None:
    stamp = store.now()
    with store.transaction(conn):
        conn.executemany("INSERT INTO inference_review (inference_id, claim_version_id, field, decision,"
                         " contributor_version_id, capacity, rationale, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         [(inf["id"], c["claim_version_id"], f, decision, who["version"], capacity, rationale, stamp)
                          for _, c, f, inf, _ in rows])


def _decide(conn, gid: str, decision: str, key, capacity, rationale) -> dict:
    who, capacity, rationale = _who(conn, key, capacity, rationale)
    rows = _in_group(conn, gid)
    d, _, f, inf, _ = rows[0]
    if inf["state"] != "proposed":
        raise GctError(REFUSED, f"Group {gid} is unresolved, so there is nothing to {decision[:-2]}.",
                       "Resolve its claims one by one with: gct infer resolve CLAIM --field " + f)
    # A group decision never overrides a claim's own resolution or rejection: accept acts only on members still
    # proposed; reject also turns down members accepted with the group.
    acts = ("open",) if decision == "accepted" else ("open", "accepted")
    open_ = [r for r in rows if (r[4]["decision"] if r[4] else "open") in acts]
    skipped = Counter(r[4]["decision"] for r in rows if r not in open_)
    _review_rows(conn, open_, decision, who, capacity, rationale)
    g = _group(d, f, inf)
    g.update(claims=len(rows), reviews=next(x for x in groups(conn, d) if x["id"] == gid)["reviews"])
    return {"group": g, decision: len(open_), "skipped": dict(sorted(skipped.items())), "by": f"{who['name']} ({capacity})"}


def accept(conn, gid: str, key, capacity, rationale) -> dict:
    """Accept every current proposed inference of the group, in one transaction."""
    return _decide(conn, gid, "accepted", key, capacity, rationale)


def reject(conn, gid: str, key, capacity, rationale) -> dict:
    return _decide(conn, gid, "rejected", key, capacity, rationale)


def _claim(conn, claim_id: int, f: str):
    """(claim row, field, inference, review) of the newest version of one claim."""
    row = conn.execute("SELECT document_id FROM claim WHERE id = ?", (claim_id,)).fetchone()
    if row is None:
        raise GctError(NOT_FOUND, f"There is no claim {claim_id}.", "See the claims with: gct claims list --doc ID")
    return next((c, x, inf, rev) for c, x, inf, rev in _current(conn, row[0]) if c["claim_id"] == claim_id and x == f)


def reject_claim(conn, claim_id: int, f: str, key, capacity, rationale) -> dict:
    who, capacity, rationale = _who(conn, key, capacity, rationale)
    c, _, inf, rev = _claim(conn, claim_id, f)
    # A deliberate claim-by-claim rejection may follow an acceptance or a resolution; rejecting twice adds nothing.
    if inf is None or inf["state"] != "proposed" or (rev and rev["decision"] == "rejected"):
        raise GctError(REFUSED, f"Claim {claim_id} has no proposed {f} to reject.",
                       f"See its {f} with: gct claims list --doc {c['document_id']}")
    _review_rows(conn, [(None, c, f, inf, rev)], "rejected", who, capacity, rationale)
    return {"claim": claim_id, "field": f, "effective": _field(*_claim(conn, claim_id, f))}


def _iso(value: str, what: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise GctError(USAGE, f"The {what} date {value} is not a date like 2024-03-31.", f"Give --{what} as YYYY-MM-DD.") from None


def resolve(conn, claim_id: int, f: str, key, capacity, rationale, kind=None, start=None, end=None,
            boundary=None, detail=None) -> dict:
    """Record a contributor's own period or boundary for the newest version of one claim."""
    if f == "period":
        if kind is None or start is None or end is None or boundary or detail:
            raise GctError(USAGE, "A period is resolved with --kind, --start and --end only.",
                           f"For example: gct infer resolve {claim_id} --field period --kind fiscal_year"
                           " --start 2023-04-01 --end 2024-03-31")
        first, last = _iso(start, "start"), _iso(end, "end")
        if first > last:
            raise GctError(USAGE, f"The start {start} is after the end {end}.", "Give a start on or before the end.")
        values = (kind, first.isoformat(), last.isoformat(), None, None)
    else:
        if boundary is None or kind or start or end:
            raise GctError(USAGE, "A boundary is resolved with --boundary and, optionally, --detail only.",
                           f"For example: gct infer resolve {claim_id} --field boundary --boundary standalone")
        values = (None, None, None, boundary, _clean(detail) or None)
    who, capacity, rationale = _who(conn, key, capacity, rationale)
    c, _, inf, _ = _claim(conn, claim_id, f)
    with store.transaction(conn):
        conn.execute("INSERT INTO inference_review (inference_id, claim_version_id, field, decision, period_kind,"
                     " period_start, period_end, boundary, boundary_detail, contributor_version_id, capacity, rationale,"
                     " created_at) VALUES (?, ?, ?, 'resolved', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (inf and inf["id"], c["claim_version_id"], f, *values, who["version"], capacity, rationale, store.now()))
    return {"claim": claim_id, "field": f, "effective": _field(*_claim(conn, claim_id, f))}
