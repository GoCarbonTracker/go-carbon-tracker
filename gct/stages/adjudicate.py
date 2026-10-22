"""Adjudication of inconsistency candidates and reviewer flags (story 5.3, FR37 to FR40, FR83). A candidate is a pair
of restate.pairs in state unresolved conflict, both documents active; it stays an unreviewed candidate until a person
records what the difference is. GCT never creates a flag and never calls a candidate a contradiction. Rows are
insert-only and written under the workspace lock with no run (as restate.record)."""
from gct.stages import correct, restate
from gct.stages.missing import contributor, page_count
from gct.workspace import registry, store
from gct.workspace.layout import REFUSED, USAGE, GctError

# C3: a row binds while both versions it names are their claims' newest versions (as restate.BINDS).
BINDS = ("(SELECT COUNT(*) FROM claim_version v WHERE v.id IN (a.low_version_id, a.high_version_id)"
         " AND v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = v.claim_id)) = 2")
FLAG_BINDS = ("f.claim_version_id = (SELECT MAX(v.id) FROM claim_version v WHERE v.claim_id ="
              " (SELECT claim_id FROM claim_version WHERE id = f.claim_version_id))")
# C4: a contributor's position on a version is their newest flag row (c is the row's contributor version).
LATEST = ("f.id = (SELECT MAX(g.id) FROM reviewer_flag g JOIN contributor_version k ON k.id = g.contributor_version_id"
          " WHERE g.claim_version_id = f.claim_version_id AND k.contributor_key = c.contributor_key)")

UNREVIEWED = "unreviewed candidate"
# {stored state: as printed}; the command line takes the printed words joined by hyphens.
STATES = {"explained_difference": "explained difference", "extraction_error": "extraction error",
          "reviewer_confirmed_issue": "reviewer-confirmed issue", "evidence_not_found": "evidence not found"}
CHOICES = {v.replace(" ", "-"): k for k, v in STATES.items()}
FILTERS = {"unreviewed": UNREVIEWED, **{k: STATES[v] for k, v in CHOICES.items()}}
RESTATE = "A restatement is recorded only with its evidence: gct restate record --original A --restated B --page N --quote TEXT"
LIST = "See the candidates with: gct adjudicate list"
ACTIVE = ("registered", "restored")

ROWS = f"""
SELECT a.*, c.name, c.organisation, lv.claim_id AS low_claim_id, hv.claim_id AS high_claim_id,
       k.company_id, {BINDS} AS binds FROM adjudication a
JOIN contributor_version c ON c.id = a.contributor_version_id
JOIN claim_version lv ON lv.id = a.low_version_id JOIN claim_version hv ON hv.id = a.high_version_id
JOIN claim k ON k.id = lv.claim_id
"""
FLAGS = f"""
SELECT f.*, v.claim_id, k.company_id, k.document_id, c.name, c.organisation, {LATEST} AS latest, {FLAG_BINDS} AS binds
FROM reviewer_flag f JOIN contributor_version c ON c.id = f.contributor_version_id
JOIN claim_version v ON v.id = f.claim_version_id JOIN claim k ON k.id = v.claim_id
"""


def _state_of(conn, doc_id: int) -> str:
    return registry.show_document(conn, doc_id)["state"]


def _record(conn, r) -> dict:
    sides = [d for (d,) in conn.execute("SELECT document_id FROM claim WHERE id IN (?, ?)",
                                        (r["low_claim_id"], r["high_claim_id"]))]
    counter = r["counter_document_id"]
    return {"id": r["id"], "low_version": r["low_version_id"], "high_version": r["high_version_id"],
            "low_claim": r["low_claim_id"], "high_claim": r["high_claim_id"], "state": r["state"],
            "rationale": r["rationale"], "procedure": r["procedure"], "counter_document": counter,
            "counter_page": r["counter_page"], "counter_note": r["counter_note"],
            "evidence_state": counter and _state_of(conn, counter),
            "counter_company": counter and registry.show_document(conn, counter)["company"],
            "follow_up": r["follow_up"], "closure_reason": r["closure_reason"], "contributor": r["name"],
            "organisation": r["organisation"], "capacity": r["capacity"], "binds": bool(r["binds"]),
            "created_at": r["created_at"], "self_declared": True,
            "evidence_deleted": next(filter(None, (registry.evidence_deleted(conn, d) for d in [*sides, counter] if d)),
                                     None)}


def _active_rows(conn) -> list[dict]:
    """Every adjudication row whose two claims' documents are active (C7), oldest first."""
    docs = {d["id"]: d["state"] for d in registry.list_documents(conn)}
    claims = dict(conn.execute("SELECT id, document_id FROM claim"))
    return [_record(conn, r) for r in conn.execute(ROWS + " ORDER BY a.id").fetchall()
            if all(docs[claims[c]] in ACTIVE for c in (r["low_claim_id"], r["high_claim_id"]))]


def _shown(rows: list[dict]) -> str:
    """A candidate's state: its newest binding row from any contributor (C4), else unreviewed."""
    binding = [r for r in rows if r["binds"]]
    return STATES[binding[-1]["state"]] if binding else UNREVIEWED


def listed(conn, company=None, state=None, claim=None) -> dict:
    """The candidates (of one company, in one shown state, naming one claim), each with every adjudication row on any
    version of its two claims; the rows on active documents whose two claims are not a candidate now, each with the
    state of the claims' pair now (None when they form none); and how many candidates the state filter hid."""
    if claim is not None:
        registry.require_active(conn, restate._claim(conn, claim)["document_id"])
    every = restate.compare(conn, company)
    rows = _active_rows(conn)
    by = {}
    for r in rows:
        by.setdefault(frozenset((r["low_claim"], r["high_claim"])), []).append(r)
    candidates, others = [], {}
    for p in every:
        key = frozenset((p["a"]["claim_id"], p["b"]["claim_id"]))
        if p["state"] == restate.UNRESOLVED:
            mine = by.pop(key, [])
            candidates.append({**p, "adjudications": mine, "adjudication_state": _shown(mine)})
        else:
            others[key] = p["state"]
    if company is not None:
        cid = registry._find_company(conn, company)["id"]
        by = {k: v for k, v in by.items() if v[0]["company_id"] == cid}
    if claim is not None:
        candidates = [c for c in candidates if claim in (c["a"]["claim_id"], c["b"]["claim_id"])]
        by = {k: v for k, v in by.items() if claim in k}
    shown = [c for c in candidates if state is None or c["adjudication_state"] == FILTERS[state]]
    earlier = sorted(({**r, "pair_state": others.get(k)} for k, v in by.items() for r in v), key=lambda r: r["id"])
    return {"candidates": shown, "hidden": len(candidates) - len(shown), "earlier": earlier}


def status(conn, company=None) -> list[dict]:
    """Per company with candidates: how many, and how many in each shown state. Only binding rows count (J7)."""
    out = {}
    for c in listed(conn, company)["candidates"]:
        n = out.setdefault(c["company"], {"company": c["company"], "candidates": 0, "unreviewed": 0,
                                          **dict.fromkeys(STATES, 0)})
        n["candidates"] += 1
        n[next((k for k, v in STATES.items() if v == c["adjudication_state"]), "unreviewed")] += 1
    return list(out.values())


def _given(value, what: str, example: str) -> str:
    """The text exactly as typed; only an empty or whitespace-only one is refused."""
    if value is None or not value.strip():
        raise GctError(USAGE, f"The {what} is empty.", f"Give one, for example: {example}")
    return value


def _optional(value, what: str, example: str):
    return None if value is None else _given(value, what, example)


def _who(conn, key, capacity, rationale) -> tuple[dict, str, str]:
    return (contributor(conn, key), _given(capacity, "capacity", '--capacity "sustainability analyst"'),
            _given(rationale, "rationale", '--rationale "checked on the page"'))


def _counter(conn, root, doc_id, page, note) -> None:
    """The C6 checks of a counter-evidence document and page, as story 5.1 L2."""
    if page is not None and doc_id is None:
        raise GctError(USAGE, "A counter-evidence page needs its document.", "Give it with: --counter-doc ID --counter-page N")
    if doc_id is None:
        return
    doc = registry.require_active(conn, doc_id)
    if page is None:
        return
    if doc["file_type"] in ("csv", "xlsx"):
        raise GctError(REFUSED, "A spreadsheet has no pages; give the sheet and cell with --counter-note.",
                       f'For example: --counter-doc {doc_id} --counter-note "Sheet1 D7"')
    n, why = page_count(root, doc)
    if n is None or not 1 <= page <= n:
        raise GctError(REFUSED, f"Page {page} is not in document {doc_id}" + (f", which has {n} pages." if n else f" ({why})."),
                       f"Give a page from 1 to {n} of document {doc_id}." if n else "Cite a page of a PDF document.")


def record(conn, root, first: int, second: int, state: str, rationale, procedure, key, capacity, counter_doc=None,
           counter_page=None, counter_note=None, follow_up=None, closure_reason=None) -> dict:
    """Record a reviewer's adjudication of the candidate the two claims' newest versions form now."""
    if state in ("restatement", "restated"):
        raise GctError(REFUSED, "Adjudication has no restatement state.", RESTATE)
    if state not in CHOICES:
        raise GctError(USAGE, f"There is no adjudication state {state}.",
                       f"Give one of: {', '.join(CHOICES)}. {RESTATE}")
    code = CHOICES[state]
    who, capacity, rationale = _who(conn, key, capacity, rationale)
    procedure = _given(procedure,"procedure", '--procedure "compared both printed tables"')
    counter_note = _optional(counter_note, "counter-evidence note", '--counter-note "scope note on p12"')
    follow_up = _optional(follow_up, "follow-up", '--follow-up "ask the company for the basis"')
    closure_reason = _optional(closure_reason, "closure reason", '--closure-reason "explained in the later report"')
    if code == "explained_difference" and counter_doc is None and counter_note is None:
        raise GctError(USAGE, "An explained difference needs its counter-evidence.",
                       'Give --counter-doc ID [--counter-page N] or --counter-note "where the explanation is printed"')
    if first == second:
        raise GctError(REFUSED, f"Both sides are claim {first}.", "Name the two claims of one candidate. " + LIST)
    for cid in (first, second):
        registry.require_active(conn, restate._claim(conn, cid)["document_id"])
    _counter(conn, root, counter_doc, counter_page, counter_note)
    p = restate._pair(conn, first, second)
    if p["state"] != restate.UNRESOLVED:
        what = p["state"] + (f" ({p['reason']})" if p["reason"] else "")
        raise GctError(REFUSED, f"Claims {first} and {second} are {what}, so they are not an inconsistency candidate.",
                       restate.PAIRS)
    low, high = sorted((p["a"]["claim_version_id"], p["b"]["claim_version_id"]))
    with store.transaction(conn):
        rid = conn.execute(
            "INSERT INTO adjudication (low_version_id, high_version_id, state, rationale, procedure, counter_document_id,"
            " counter_page, counter_note, follow_up, closure_reason, contributor_version_id, capacity, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (low, high, code, rationale, procedure, counter_doc, counter_page, counter_note, follow_up, closure_reason,
             who["version"], capacity, store.now())).lastrowid
    a, b = sorted((first, second))
    nxt = (f"An extraction error does not change the claim. If a figure was misread, correct it with: gct correct {a}"
           f" --value TEXT --as KEY --capacity TEXT --rationale TEXT (or gct correct {b} ...)"
           if code == "extraction_error" else None)
    return {"adjudication": _record(conn, conn.execute(ROWS + " WHERE a.id = ?", (rid,)).fetchone()),
            "adjudication_state": STATES[code], "next": nxt}


# Reviewer flags (J6): on the newest version of a current claim of an active document, by one contributor.

def _flag(r) -> dict:
    return {"id": r["id"], "claim": r["claim_id"], "version": r["claim_version_id"], "decision": r["decision"],
            "rationale": r["rationale"], "contributor": r["name"], "organisation": r["organisation"],
            "capacity": r["capacity"], "latest": bool(r["latest"]), "binds": bool(r["binds"]),
            "created_at": r["created_at"], "self_declared": True}


def _flaggable(conn, claim: int, version: int):
    c = restate._claim(conn, claim)
    registry.require_active(conn, c["document_id"])
    history = f"See its versions with: gct claims history {claim}"
    if version != c["version"]:
        raise GctError(REFUSED, f"Version {version} is not claim {claim}'s newest version ({c['version']}).", history)
    s = correct.states(conn, c["document_id"])[claim]
    if s != "current":
        raise GctError(REFUSED, f"Claim {claim} is {s}, so it cannot be flagged.",
                       f"Run gct extract {c['document_id']} first, or pick a current claim: "
                       f"gct claims list --doc {c['document_id']} --state current")
    return c


def _write_flag(conn, version: int, decision: str, who: dict, capacity: str, rationale: str) -> dict:
    with store.transaction(conn):
        fid = conn.execute("INSERT INTO reviewer_flag (claim_version_id, decision, rationale, contributor_version_id,"
                           " capacity, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                           (version, decision, rationale, who["version"], capacity, store.now())).lastrowid
    return _flag(conn.execute(FLAGS + " WHERE f.id = ?", (fid,)).fetchone())


def raise_flag(conn, claim: int, version: int, rationale, key, capacity) -> dict:
    who, capacity, rationale = _who(conn, key, capacity, rationale)
    _flaggable(conn, claim, version)
    return _write_flag(conn, version, "raised", who, capacity, rationale)


def withdraw_flag(conn, claim: int, version: int, rationale, key, capacity) -> dict:
    who, capacity, rationale = _who(conn, key, capacity, rationale)
    _flaggable(conn, claim, version)
    row = conn.execute("SELECT f.decision FROM reviewer_flag f JOIN contributor_version c ON c.id = f.contributor_version_id"
                       " WHERE f.claim_version_id = ? AND c.contributor_key = ? ORDER BY f.id DESC LIMIT 1",
                       (version, who["key"])).fetchone()
    if row is None or row["decision"] != "raised":
        raise GctError(REFUSED, f"{who['name']} has no reviewer flag raised on version {version} of claim {claim}, so"
                                " there is nothing to withdraw.", f"See the flags with: gct flag list --claim {claim}")
    return _write_flag(conn, version, "withdrawn", who, capacity, rationale)


def flags(conn, company=None, claim=None) -> list[dict]:
    """Every flag row on a claim of an active document (of one company, or one claim), oldest first."""
    where, params = [], []
    if claim is not None:
        registry.require_active(conn, restate._claim(conn, claim)["document_id"])
        where.append("v.claim_id = ?")
        params.append(claim)
    if company is not None:
        where.append("k.company_id = ?")
        params.append(registry._find_company(conn, company)["id"])
    rows = conn.execute(FLAGS + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY f.id", params).fetchall()
    docs = {d["id"]: d["state"] for d in registry.list_documents(conn)}
    return [_flag(r) for r in rows if docs[r["document_id"]] in ACTIVE]
