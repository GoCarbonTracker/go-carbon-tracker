"""Corrections, current-claim state and claim history. A correction is a new claim version; nothing earlier changes,
and nothing recorded on an earlier version is carried to a newer one silently."""
import json

from gct.stages import version_of
from gct.stages import extract, sheet
from gct.stages.infer import _who
from gct.stages.missing import _text
from gct.stages.read import NEWEST_SQL
from gct.workspace import registry, runs, store
from gct.workspace.layout import NOT_FOUND, REFUSED, USAGE, GctError

METHOD = "correction"
CONFIG = version_of("correct", 1)
CURRENT = "current"
NOT_FOUND_STATE = "not found in the newest reading"
NOT_EXTRACTED = "page read again, not yet extracted"
STATES = {"current": CURRENT, "not-found": NOT_FOUND_STATE, "not-extracted": NOT_EXTRACTED}
# The correctable fields: (column, flag, words used in messages).
FIELDS = (("value_text", "--value", "value"), ("unit_text", "--unit", "unit"), ("metric_text", "--metric", "metric"),
          ("period_label", "--period-label", "period label"))
COPIED = ("metric_text", "value_text", "value", "unit_text", "period_label", "period_kind", "period_start", "period_end",
          "metric_key", "reporting_boundary", "boundary_detail", "boundary_label")
NEWEST = "(SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)"
CORRECTION_SQL = """
SELECT r.*, c.name, c.organisation, v.value_text, v.unit_text, v.metric_text, v.period_label
FROM correction r JOIN contributor_version c ON c.id = r.contributor_version_id
JOIN claim_version v ON v.id = r.corrects_version_id WHERE r.claim_version_id = ?
"""


def states(conn, doc_id: int) -> dict:
    """{claim id: state} for one document. Current only when the page's newest reading was extracted with the current
    extract config and that extraction found the claim."""
    if (out := sheet.states(conn, doc_id)) is not None:  # a CSV or XLSX document: its sheet stage decides (story 4.3)
        return out
    config = extract.extract_config()
    pages = {r["page_number"]: r["id"] for r in conn.execute(NEWEST_SQL, (None, None, doc_id))}
    extracted = {iv for (iv,) in conn.execute(
        "SELECT DISTINCT input_version FROM attempt WHERE stage = 'extract' AND outcome = 'ok' AND config_version = ?"
        " AND item LIKE ?", (config, f"{doc_id}:%"))}
    seen = set(map(tuple, conn.execute(
        "SELECT v.claim_id, s.page_id FROM claim_seen s JOIN claim_version v ON v.id = s.claim_version_id"
        " JOIN claim c ON c.id = v.claim_id WHERE c.document_id = ? AND s.config_version = ?", (doc_id, config))))
    out = {}
    for cid, page in conn.execute("SELECT id, page_number FROM claim WHERE document_id = ?", (doc_id,)):
        pid = pages.get(page)
        out[cid] = NOT_EXTRACTED if f"page {pid}" not in extracted else CURRENT if (cid, pid) in seen else NOT_FOUND_STATE
    return out


def re_review(conn, doc_id: int) -> dict:
    """{claim id: entries} for claims whose current version lost a record made on an earlier version: a correction, an
    accepted or resolved period or boundary review, a company confirmation or auditor review (any outcome), a reviewer
    flag its contributor still has raised there, or an adjudication of a pair that is an unreviewed candidate again
    (story 5.2, B1). An entry clears once the same kind of record is made on the current version (an adjudication: a
    binding one of the claims' pair). Nothing is copied to the current version (FR24)."""
    from gct.stages import adjudicate, review  # both import this module

    current = dict(conn.execute(f"SELECT c.id, {NEWEST} FROM claim c WHERE c.document_id = ?", (doc_id,)))
    # (kind, claim, record, version it was made on, whether it asks for renewal once that version is not current)
    records = [("correction", *r, True) for r in conn.execute(
        "SELECT v.claim_id, r.id, r.claim_version_id FROM correction r"
        " JOIN claim_version v ON v.id = r.claim_version_id JOIN claim c ON c.id = v.claim_id"
        " WHERE c.document_id = ? ORDER BY r.id", (doc_id,))]
    records += [(f"{r[0]} review", *r[1:4], r[4] in ("accepted", "resolved")) for r in conn.execute(
        "SELECT r.field, v.claim_id, r.id, r.claim_version_id, r.decision FROM inference_review r"
        " JOIN claim_version v ON v.id = r.claim_version_id JOIN claim c ON c.id = v.claim_id"
        " WHERE c.document_id = ? ORDER BY r.id", (doc_id,))]
    for table, words, _ in review.LEDGERS.values():
        records += [(words, r["claim_id"], r["id"], r["claim_version_id"], True) for r in conn.execute(
            review.ENTRIES.format(t=table) + " WHERE k.document_id = ? ORDER BY r.id", (doc_id,))]
    records += [("reviewer flag", r["claim_id"], r["id"], r["claim_version_id"], r["latest"] and r["decision"] == "raised")
                for r in conn.execute(adjudicate.FLAGS + " WHERE k.document_id = ? ORDER BY f.id", (doc_id,))]
    on_current = {(kind, cid) for kind, cid, _, cv, _ in records if cv == current[cid]}
    newest = {}
    for kind, cid, rid, cv, asks in records:
        if cv != current[cid] and (kind, cid) not in on_current and asks:
            newest[(kind, cid)] = {"kind": kind, "id": rid, "version": cv}
    newest.update(_adjudications(conn, doc_id, current))
    out = {}
    for key, entry in sorted(newest.items(), key=lambda kv: kv[1]["id"]):
        out.setdefault(key[1], []).append(entry)
    return out


def _adjudications(conn, doc_id: int, current: dict) -> dict:
    """{("adjudication", claim, other claim): entry} for the claims of one document named by an adjudication row that
    no longer binds, while the two claims' current versions form an unresolved conflict that no binding row covers.
    Both claims of the pair get the entry, each naming its own version and the other side in `with`."""
    from gct.stages import adjudicate, restate  # both import this module

    rows = [r for r in conn.execute(adjudicate.ROWS + " ORDER BY a.id")
            if {r["low_claim_id"], r["high_claim_id"]} & current.keys()]
    if all(r["binds"] for r in rows):  # the pairs are computed only when a row on an earlier version exists
        return {}
    bound = {frozenset((r["low_claim_id"], r["high_claim_id"])) for r in rows if r["binds"]}
    unreviewed = {frozenset((p["a"]["claim_id"], p["b"]["claim_id"]))
                  for p in restate.compare(conn, registry.get_document(conn, doc_id)["company"])
                  if p["state"] == restate.UNRESOLVED} - bound
    out = {}
    for r in rows:
        pair = frozenset((r["low_claim_id"], r["high_claim_id"]))
        if r["binds"] or pair not in unreviewed:
            continue
        sides = {r["low_claim_id"]: r["low_version_id"], r["high_claim_id"]: r["high_version_id"]}
        for cid in pair & current.keys():
            (other,) = pair - {cid}
            out[("adjudication", cid, other)] = {"kind": "adjudication", "id": r["id"], "version": sides[cid],
                                                 "with": {"claim": other, "version": sides[other]}}
    return out


def entry_text(e: dict) -> str:
    other = f" with claim {e['with']['claim']} version {e['with']['version']}" if "with" in e else ""
    return f"{e['kind']} #{e['id']} on version {e['version']}{other}"


# The commands that make each kind of record on the current version, in the order gct review pending lists the kinds.
RENEW = {
    "correction": "gct correct {claim} --value TEXT --as KEY --capacity TEXT --rationale TEXT",
    "period review": "gct infer accept GROUP (see gct infer groups --doc {doc}) or gct infer resolve {claim} --field period"
                     " --kind KIND --start YYYY-MM-DD --end YYYY-MM-DD --as KEY --capacity TEXT --rationale TEXT",
    "boundary review": "gct infer accept GROUP (see gct infer groups --doc {doc}) or gct infer resolve {claim} --field"
                       " boundary --boundary BOUNDARY --as KEY --capacity TEXT --rationale TEXT",
    "company confirmation": "gct review company {claim} --version {version} --outcome accepted|rejected|disputed --scope TEXT"
                            " --conclusion TEXT --as KEY --capacity TEXT --evidence-note TEXT",
    "auditor review": "gct review auditor {claim} --version {version} --outcome accepted|rejected|disputed --scope TEXT"
                      " --conclusion TEXT --as KEY --capacity TEXT --evidence-note TEXT",
    "reviewer flag": "gct flag raise {claim} --version {version} --as KEY --capacity TEXT --rationale TEXT",
    "adjudication": "gct adjudicate record {claim} {other} --state STATE --procedure TEXT --as KEY --capacity TEXT"
                    " --rationale TEXT",
}
E5 = ("company confirmation", "auditor review", "reviewer flag", "adjudication")  # contributors' records (C5)


def pending(conn, company=None, doc=None) -> list[dict]:
    """The re_review entries of every claim of the active documents (of one company, of one document), grouped by kind,
    each with the claim's current version and the command that renews it (story 5.2, B3)."""
    if doc is not None:
        registry.require_active(conn, doc)
    out = {kind: [] for kind in RENEW}
    for d in registry.list_documents(conn, company):
        if d["state"] not in ("registered", "restored") or doc not in (None, d["id"]):
            continue
        current = dict(conn.execute(f"SELECT c.id, {NEWEST} FROM claim c WHERE c.document_id = ?", (d["id"],)))
        for cid, entries in re_review(conn, d["id"]).items():
            for e in entries:
                renew = RENEW[e["kind"]].format(claim=cid, version=current[cid], doc=d["id"],
                                                other=e.get("with", {}).get("claim"))
                out[e["kind"]].append({"claim": cid, "document": d["id"], "company": d["company"],
                                       "version": current[cid], "entry": e, "renew": renew})
    return [{"kind": k, "entries": sorted(v, key=lambda x: (x["claim"], x["entry"]["id"]))} for k, v in out.items() if v]


def correction_of(conn, version_id: int) -> dict | None:
    """The correction that made this version, with the values of the version it replaced; None for an extracted one."""
    r = conn.execute(CORRECTION_SQL, (version_id,)).fetchone()
    return r and {"id": r["id"], "corrects_version": r["corrects_version_id"], "fields": json.loads(r["fields"]),
                  "replaced": {k: r[k] for k in ("value_text", "unit_text", "metric_text", "period_label")},
                  "contributor": r["name"], "organisation": r["organisation"], "capacity": r["capacity"],
                  "rationale": r["rationale"], "created_at": r["created_at"]}


def _claim(conn, claim_id: int):
    row = conn.execute("SELECT * FROM claim WHERE id = ?", (claim_id,)).fetchone()
    if row is None:
        raise GctError(NOT_FOUND, f"There is no claim {claim_id}.", "See the claims with: gct claims list --doc ID")
    return row


def correct(conn, claim_id: int, key, capacity, rationale, **given) -> dict:
    """Record a contributor's correction of the current version of one claim as a new version citing it."""
    given = {col: v for col, _, _ in FIELDS if (v := given.get(col)) is not None}
    if not given:
        raise GctError(USAGE, "Nothing to correct was given.",
                       f'Give at least one of --value, --unit, --metric or --period-label, for example: '
                       f'gct correct {claim_id} --value "1,234" --as KEY --capacity TEXT --rationale TEXT')
    c = _claim(conn, claim_id)
    registry.require_active(conn, c["document_id"])
    for col, flag, words in FIELDS:
        if col in given:
            given[col] = _text(given[col], words, f'{flag} "the {words} as printed"')
    who, capacity, rationale = _who(conn, key, capacity, rationale)
    state = states(conn, c["document_id"])[claim_id]
    if state != CURRENT:
        raise GctError(REFUSED, f"Claim {claim_id} is {state}, so it cannot be corrected.",
                       f"Run gct extract {c['document_id']} first, or pick a current claim: "
                       f"gct claims list --doc {c['document_id']} --state current")
    v = conn.execute("SELECT * FROM claim_version WHERE id = (SELECT MAX(id) FROM claim_version WHERE claim_id = ?)",
                     (claim_id,)).fetchone()
    changed = [col for col, x in given.items() if v[col] != x]
    if not changed:
        raise GctError(REFUSED, f"Claim {claim_id} already has those values, so there is nothing to correct.",
                       f"See its history with: gct claims history {claim_id}")
    values = {**{k: v[k] for k in COPIED}, **given}
    if "value_text" in changed:
        values["value"] = extract._value(values["value_text"])
    ref = conn.execute("SELECT * FROM evidence_ref WHERE claim_version_id = ? ORDER BY id LIMIT 1", (v["id"],)).fetchone()
    with runs.run(conn, "correct") as run_id:
        stamp = store.now()
        with store.transaction(conn):
            new = conn.execute(
                f"INSERT INTO claim_version (claim_id, run_id, method, config_version, {', '.join(COPIED)}, created_at)"
                f" VALUES (?, ?, ?, ?, {', '.join('?' * len(COPIED))}, ?)",
                (claim_id, run_id, METHOD, CONFIG, *(values[k] for k in COPIED), stamp)).lastrowid
            if ref is not None:  # same page and boxes: gct link checks the corrected figure against the page
                conn.execute("INSERT INTO evidence_ref (claim_version_id, document_id, page_number, boxes, sheet, cell,"
                             " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (new, ref["document_id"], ref["page_number"], ref["boxes"], ref["sheet"], ref["cell"], stamp))
            conn.execute("INSERT INTO correction (claim_version_id, corrects_version_id, fields, contributor_version_id,"
                         " capacity, rationale, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (new, v["id"], json.dumps(changed), who["version"], capacity, rationale, stamp))
        runs.event(conn, run_id, "output", stage="correct", item=str(claim_id))
    return {"claim": claim_id, "version": new, "correction": correction_of(conn, new)}


def records_on(conn, version_id: int) -> dict:
    """The contributors' records naming one claim version, oldest first: both ledgers with their disagreement (story
    5.1), the reviewer flags on it and the adjudications naming it on either side (story 5.3)."""
    from gct.stages import adjudicate, review  # both import this module

    return {**review.entries(conn, version_id),
            "reviewer_flags": [adjudicate._flag(r) for r in conn.execute(
                adjudicate.FLAGS + " WHERE f.claim_version_id = ? ORDER BY f.id", (version_id,))],
            "adjudications": [adjudicate._record(conn, r) for r in conn.execute(
                adjudicate.ROWS + " WHERE ? IN (a.low_version_id, a.high_version_id) ORDER BY a.id", (version_id,))]}


def history(conn, claim_id: int) -> dict:
    """Every version of one claim with its evidence refs and their source-match rows, its inferences and reviews,
    the correction that made it, the readings that found it and the contributors' records on it (records_on)."""
    c = _claim(conn, claim_id)
    doc = c["document_id"]
    versions = []
    for v in conn.execute("SELECT * FROM claim_version WHERE claim_id = ? ORDER BY id", (claim_id,)).fetchall():
        refs = [{"id": e["id"], "page_number": e["page_number"], "boxes": e["boxes"] and json.loads(e["boxes"]),
                 "source_match": [dict(s) for s in conn.execute(
                     "SELECT id, status, reason, run_id, created_at FROM source_match WHERE evidence_ref_id = ?"
                     " ORDER BY id", (e["id"],))]}
                for e in conn.execute("SELECT * FROM evidence_ref WHERE claim_version_id = ? ORDER BY id", (v["id"],))]
        versions.append({
            "id": v["id"], "method": v["method"], "config_version": v["config_version"], "run_id": v["run_id"],
            "created_at": v["created_at"],
            **{k: v[k] for k in ("metric_text", "value_text", "value", "unit_text", "period_label", "boundary_label")},
            "evidence_refs": refs,
            "inferences": [dict(r) for r in conn.execute(
                "SELECT id, field, state, period_kind, period_start, period_end, boundary, boundary_detail, reason,"
                " run_id, created_at FROM inference WHERE claim_version_id = ? ORDER BY id", (v["id"],))],
            "reviews": [dict(r) for r in conn.execute(
                "SELECT r.id, r.field, r.decision, r.period_kind, r.period_start, r.period_end, r.boundary,"
                " r.boundary_detail, c.name AS contributor, c.organisation, r.capacity, r.rationale, r.created_at"
                " FROM inference_review r JOIN contributor_version c ON c.id = r.contributor_version_id"
                " WHERE r.claim_version_id = ? ORDER BY r.id", (v["id"],))],
            "correction": correction_of(conn, v["id"]),
            "seen": [dict(r) for r in conn.execute(
                "SELECT page_id, config_version, run_id, created_at FROM claim_seen WHERE claim_version_id = ?"
                " ORDER BY id", (v["id"],))],
            **records_on(conn, v["id"]),
        })
    return {"claim": {"id": claim_id, "document": doc, "document_state": registry.get_document(conn, doc)["state"],
                      "page_number": c["page_number"], "locator": c["locator"],
                      "state": states(conn, doc)[claim_id], "needs_re_review": re_review(conn, doc).get(claim_id, []),
                      "evidence_deleted": registry.evidence_deleted(conn, doc)},
            "versions": versions}
