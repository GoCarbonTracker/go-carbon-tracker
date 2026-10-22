"""Highlights (story 5.4, FR36): a contributor marks a claim version with a short note. A highlight confirms, corrects and
decides nothing: no state, count or queue reads it except its own listing, the archive count and the projection. Rows
are insert-only; binding and each contributor's latest highlight are computed on read. No run is opened."""
from gct.stages import correct, review
from gct.stages.missing import contributor
from gct.workspace import registry, store
from gct.workspace.layout import REFUSED, GctError

# Every highlight with its contributor as recorded, its claim and the two computed flags (C3, C4).
ENTRIES = """
SELECT h.*, c.name, c.organisation, v.claim_id, k.document_id AS claim_document,
       h.id = (SELECT MAX(x.id) FROM highlight x JOIN contributor_version y ON y.id = x.contributor_version_id
               WHERE x.claim_version_id = h.claim_version_id AND y.contributor_key = c.contributor_key) AS latest,
       h.claim_version_id = (SELECT MAX(id) FROM claim_version WHERE claim_id = v.claim_id) AS binds
FROM highlight h JOIN contributor_version c ON c.id = h.contributor_version_id
JOIN claim_version v ON v.id = h.claim_version_id JOIN claim k ON k.id = v.claim_id
"""


def _entry(conn, r) -> dict:
    return {"id": r["id"], "claim_version": r["claim_version_id"], "contributor": r["name"],
            "organisation": r["organisation"], "contributor_version": r["contributor_version_id"],
            "capacity": r["capacity"], "note": r["note"], "latest": bool(r["latest"]), "binds": bool(r["binds"]),
            "self_declared": True, "evidence_deleted": registry.evidence_deleted(conn, r["claim_document"]),
            "created_at": r["created_at"]}


def entries(conn, version_id: int) -> list[dict]:
    """The highlights on one claim version, oldest first."""
    return [_entry(conn, r) for r in conn.execute(ENTRIES + " WHERE h.claim_version_id = ? ORDER BY h.id", (version_id,))]


def projected(conn) -> list[tuple]:
    """The highlights whose claim's document is active, in the columns of the published table."""
    return [(r["id"], r["claim_id"], r["claim_version_id"], r["name"], r["organisation"], r["capacity"], r["note"],
             r["latest"], r["binds"], r["created_at"])
            for r in conn.execute(ENTRIES + f" WHERE {review.STATE.format('k.document_id')}"
                                  " IN ('registered', 'restored') ORDER BY h.id")]


def record(conn, claim_id: int, version: int, note, key, capacity) -> dict:
    """Record one contributor's highlight on the newest version of a current claim of an active document."""
    c = review._claim(conn, claim_id)
    registry.require_active(conn, c["document_id"])
    if version != c["version"]:
        raise GctError(REFUSED, f"Version {version} is not the newest version of claim {claim_id}; the newest is"
                                f" {c['version']}.",
                       f"See what version {c['version']} says with: gct claims history {claim_id}, then highlight"
                       f" --version {c['version']}")
    state = correct.states(conn, c["document_id"])[claim_id]
    if state != correct.CURRENT:
        raise GctError(REFUSED, f"Claim {claim_id} is {state}, so it cannot be highlighted.",
                       f"Run gct extract {c['document_id']} first, or pick a current claim: "
                       f"gct claims list --doc {c['document_id']} --state current")
    who = contributor(conn, key)
    capacity = review._given(capacity, "capacity", '--capacity "sustainability analyst"')
    note = review._given(note, "note", '--note "check this against the 2023 report"')
    with store.transaction(conn):
        hid = conn.execute("INSERT INTO highlight (claim_version_id, contributor_version_id, capacity, note, created_at)"
                           " VALUES (?, ?, ?, ?, ?)", (version, who["version"], capacity, note, store.now())).lastrowid
    return {"claim": {"id": claim_id, "document": c["document_id"], "company": c["company"], "version": version},
            "entry": _entry(conn, conn.execute(ENTRIES + " WHERE h.id = ?", (hid,)).fetchone())}


def listing(conn, claim_id: int) -> dict:
    """Every version of one claim, oldest first, with its highlights (an archived or deleted document's claim
    included)."""
    c = review._claim(conn, claim_id)
    doc = c["document_id"]
    return {"claim": {"id": claim_id, "document": doc, "document_state": registry.get_document(conn, doc)["state"],
                      "company": c["company"], "version": c["version"], "state": correct.states(conn, doc)[claim_id],
                      "evidence_deleted": registry.evidence_deleted(conn, doc)},
            "versions": [{"id": v, "binds": v == c["version"], "highlights": entries(conn, v)} for (v,) in conn.execute(
                "SELECT id FROM claim_version WHERE claim_id = ? ORDER BY id", (claim_id,)).fetchall()]}
