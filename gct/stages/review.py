"""Company confirmations and auditor reviews (story 5.1, FR33 to FR35, FR40, FR83, FR84): two insert-only ledgers of
contributors' conclusions on one claim version. A record writes one row in one table; nothing reads one ledger to
decide the other. Binding, each contributor's latest position and a disagreement between the ledgers are computed on
read, never stored. Identities are self-declared and GCT adopts no conclusion as its own."""
import re
from datetime import date

from gct.stages import correct
from gct.stages.missing import contributor, page_count
from gct.workspace import registry, store
from gct.workspace.layout import NOT_FOUND, REFUSED, USAGE, GctError

# {ledger: (table, the words used for one entry, the JSON key of its list)}
LEDGERS = {"company": ("review_company", "company confirmation", "company_confirmations"),
           "auditor": ("review_auditor", "auditor review", "auditor_reviews")}
OUTCOMES = ("accepted", "rejected", "disputed")
SELF_DECLARED = ("Identities and capacities are self-declared. GCT does not check them and does not adopt any"
                 " conclusion as its own.")
SPREADSHEET = "A spreadsheet has no pages; give the sheet and cell with --evidence-note."
STATE = "(SELECT s.state FROM document_state s WHERE s.document_id = {} ORDER BY s.id DESC LIMIT 1)"
# Every entry of one ledger with its contributor as recorded, its claim, its evidence document's company and state, and
# the two computed flags: latest (the contributor key's newest row on that version, C4) and binds (C3).
ENTRIES = f"""
SELECT r.*, c.name, c.organisation, v.claim_id, k.document_id AS claim_document,
       r.id = (SELECT MAX(x.id) FROM {{t}} x JOIN contributor_version y ON y.id = x.contributor_version_id
               WHERE x.claim_version_id = r.claim_version_id AND y.contributor_key = c.contributor_key) AS latest,
       r.claim_version_id = (SELECT MAX(id) FROM claim_version WHERE claim_id = v.claim_id) AS binds,
       {STATE.format('r.evidence_document_id')} AS evidence_state,
       (SELECT m.name FROM document e JOIN company m ON m.id = e.company_id WHERE e.id = r.evidence_document_id)
           AS evidence_company
FROM {{t}} r JOIN contributor_version c ON c.id = r.contributor_version_id
JOIN claim_version v ON v.id = r.claim_version_id JOIN claim k ON k.id = v.claim_id
"""


def _entry(conn, ledger: str, r) -> dict:
    marks = (registry.evidence_deleted(conn, d) for d in (r["claim_document"], r["evidence_document_id"]) if d)
    return {"id": r["id"], "ledger": ledger, "claim_version": r["claim_version_id"], "contributor": r["name"],
            "organisation": r["organisation"], "contributor_version": r["contributor_version_id"],
            "capacity": r["capacity"], "scope": r["scope"], "reviewed_on": r["reviewed_on"],
            "conclusion": r["conclusion"], "outcome": r["outcome"], "evidence_document": r["evidence_document_id"],
            "evidence_company": r["evidence_company"], "evidence_page": r["evidence_page"],
            "evidence_note": r["evidence_note"], "evidence_state": r["evidence_state"], "latest": bool(r["latest"]),
            "binds": bool(r["binds"]), "self_declared": True, "evidence_deleted": next(filter(None, marks), None),
            "created_at": r["created_at"]}


def _position(entries: list[dict]) -> list[str]:
    return [o for o in OUTCOMES if any(e["latest"] and e["outcome"] == o for e in entries)]


def entries(conn, version_id: int) -> dict:
    """Both ledgers' entries on one claim version, oldest first, and the disagreement between them (L4): null unless
    both ledgers hold a position and the two sets of latest outcomes differ."""
    out = {key: [_entry(conn, ledger, r) for r in conn.execute(
        ENTRIES.format(t=table) + " WHERE r.claim_version_id = ? ORDER BY r.id", (version_id,))]
        for ledger, (table, _, key) in LEDGERS.items()}
    company, auditor = (_position(out[LEDGERS[x][2]]) for x in LEDGERS)
    return {**out, "disagreement": {"company": company, "auditor": auditor} if company and auditor
            and company != auditor else None}


def projected(conn, ledger: str) -> list[tuple]:
    """The rows of one ledger whose claim's document is active, in the columns of the published table (L7)."""
    return [(r["id"], r["claim_id"], r["claim_version_id"], r["name"], r["organisation"], r["contributor_version_id"],
             r["capacity"], r["scope"], r["reviewed_on"], r["conclusion"], r["outcome"], r["evidence_document_id"],
             r["evidence_page"], r["evidence_note"], r["evidence_state"], r["latest"], r["binds"], r["created_at"])
            for r in conn.execute(ENTRIES.format(t=LEDGERS[ledger][0]) + f" WHERE {STATE.format('k.document_id')}"
                                  " IN ('registered', 'restored') ORDER BY r.id")]


def _claim(conn, claim_id: int):
    row = conn.execute("SELECT c.*, m.name AS company, (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)"
                       " AS version FROM claim c JOIN company m ON m.id = c.company_id WHERE c.id = ?",
                       (claim_id,)).fetchone()
    if row is None:
        raise GctError(NOT_FOUND, f"There is no claim {claim_id}.", "See the claims with: gct claims list --doc ID")
    return row


def _given(value, what: str, example: str) -> str:
    """Contributor text, kept exactly as typed; only an empty one is refused."""
    if value is None or not value.strip():
        raise GctError(USAGE, f"The {what} is empty.", f"Give one, for example: {example}")
    return value


def _date(given) -> str:
    today = date.today()  # the contributor's own calendar day
    if given is None:
        return today.isoformat()
    try:
        day = date.fromisoformat(given) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", given) else None
    except ValueError:
        day = None
    if day is None:
        raise GctError(USAGE, f"The date {given} is not a date in the form YYYY-MM-DD.",
                       "Give the day of your review, for example: --date 2025-06-30")
    if day > today:
        raise GctError(USAGE, f"The date {given} is in the future.",
                       f"Give the day of your review, today ({today.isoformat()}) or earlier.")
    return given


def record(conn, root, ledger: str, claim_id: int, version: int, outcome, scope, conclusion, key, capacity,
           evidence_doc=None, evidence_page=None, evidence_note=None, reviewed_on=None) -> dict:
    """Record one contributor's conclusion on the newest version of a current claim of an active document, in one
    ledger. No run is opened and no run-log line is written."""
    table, words, _ = LEDGERS[ledger]
    c = _claim(conn, claim_id)
    registry.require_active(conn, c["document_id"])
    if version != c["version"]:
        raise GctError(REFUSED, f"Version {version} is not the newest version of claim {claim_id}; the newest is"
                                f" {c['version']}.",
                       f"See what version {c['version']} says with: gct claims history {claim_id}, then record on"
                       f" --version {c['version']}")
    state = correct.states(conn, c["document_id"])[claim_id]
    if state != correct.CURRENT:
        raise GctError(REFUSED, f"Claim {claim_id} is {state}, so it cannot be reviewed.",
                       f"Run gct extract {c['document_id']} first, or pick a current claim: "
                       f"gct claims list --doc {c['document_id']} --state current")
    who = contributor(conn, key)
    capacity = _given(capacity, "capacity", '--capacity "head of sustainability"')
    scope = _given(scope, "scope", '--scope "Scope 1 emissions, FY 2024-25, standalone"')
    conclusion = _given(conclusion, "conclusion", '--conclusion "the figure agrees with our records"')
    if outcome not in OUTCOMES:
        raise GctError(USAGE, f"The outcome {outcome} is not one of accepted, rejected or disputed.",
                       "Give --outcome accepted, --outcome rejected or --outcome disputed; your own words go in"
                       " --conclusion.")
    reviewed_on = _date(reviewed_on)
    if evidence_note is not None:
        evidence_note = _given(evidence_note, "evidence note", '--evidence-note "meter log, sheet Plant 2, cell C7"')
    if evidence_doc is None and evidence_note is None:
        raise GctError(USAGE, f"A {words} needs its evidence.",
                       "Give --evidence-doc ID (with --evidence-page N for a page of a PDF), --evidence-note TEXT,"
                       " or both.")
    if evidence_page is not None and evidence_doc is None:
        raise GctError(USAGE, "A page was given without its document.",
                       f"Give the document too: --evidence-doc ID --evidence-page {evidence_page}")
    if evidence_doc is not None:
        doc = registry.require_active(conn, evidence_doc)
        if evidence_page is not None:
            if doc["file_type"] != "pdf":
                raise GctError(REFUSED, f"Document {evidence_doc} is a spreadsheet, so page {evidence_page} cannot"
                                        " be cited.", SPREADSHEET)
            n, why = page_count(root, doc)
            if n is None or not 1 <= evidence_page <= n:
                raise GctError(REFUSED, f"Page {evidence_page} is not in document {evidence_doc}"
                                        + (f", which has {n} pages." if n else f" ({why})."),
                               f"Give a page from 1 to {n}." if n else "Cite the document without a page, or add a note.")
    with store.transaction(conn):
        rid = conn.execute(
            f"INSERT INTO {table} (claim_version_id, contributor_version_id, capacity, scope, reviewed_on, conclusion,"
            " outcome, evidence_document_id, evidence_page, evidence_note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (version, who["version"], capacity, scope, reviewed_on, conclusion, outcome, evidence_doc, evidence_page,
             evidence_note, store.now())).lastrowid
    entry = _entry(conn, ledger, conn.execute(ENTRIES.format(t=table) + " WHERE r.id = ?", (rid,)).fetchone())
    return {"claim": {"id": claim_id, "document": c["document_id"], "company": c["company"], "version": version},
            "entry": entry, "disagreement": entries(conn, version)["disagreement"]}


def listing(conn, claim_id: int) -> dict:
    """Every version of one claim, oldest first, with both ledgers and their disagreement (an archived or deleted
    document's claim included: its entries stay listed)."""
    c = _claim(conn, claim_id)
    doc = c["document_id"]
    return {"claim": {"id": claim_id, "document": doc, "document_state": registry.get_document(conn, doc)["state"],
                      "company": c["company"], "version": c["version"], "state": correct.states(conn, doc)[claim_id],
                      "evidence_deleted": registry.evidence_deleted(conn, doc)},
            "versions": [{"id": v, "binds": v == c["version"], **entries(conn, v)} for (v,) in conn.execute(
                "SELECT id FROM claim_version WHERE claim_id = ? ORDER BY id", (claim_id,)).fetchall()]}
