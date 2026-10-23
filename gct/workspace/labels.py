"""Privacy labels (story 7.1 part A, C-privacy P1 to P8, C7). A document's stored label is the newest document_label
row, else its document.privacy with availability unknown; labels.effective applies P3 on top of it. Nothing else in
gct reads document.privacy or document_label to decide what leaves the workspace. Stage modules are imported inside
the functions (published imports this module, and the stages import published)."""
import json

from gct.workspace import store
from gct.workspace.layout import REFUSED, USAGE, GctError

PRIVACY = ("private", "shareable")
AVAILABILITY = ("public", "internal", "unknown")

_NEWEST = "(SELECT l.{} FROM document_label l WHERE l.document_id = d.id ORDER BY l.id DESC LIMIT 1)"
# The stored label of document d, as SQL over a document table aliased d.
STORED_PRIVACY = f"COALESCE({_NEWEST.format('privacy')}, d.privacy)"
STORED_AVAILABILITY = f"COALESCE({_NEWEST.format('availability')}, 'unknown')"
_DELETED = "(SELECT s.state FROM document_state s WHERE s.document_id = d.id ORDER BY s.id DESC LIMIT 1) = 'deleted'"

# P4 as data, keyed by workspace table: the columns that lead to a document (through a foreign key, or the
# document's own id) and the rule for what the keys do not show. labels.named applies both.
_CV = {"claim_version_id": "claim_version"}
NAMES = {
    "schema_version": ({}, None), "workspace": ({}, None), "company": ({}, None), "contributor_version": ({}, None),
    "run": ({}, None), "approval": ({}, None),
    "published_version": ({}, None), "published_pointer": ({}, None), "published_purge": ({}, None),
    "run_event": ({}, None),
    "attempt": ({}, "the document whose id starts its item (stage items are 'N' or 'N:...'); a fetch item is an"
                    " address and names no document"),
    "document": ({"id": "document"}, None),
    "document_state": ({"document_id": "document"}, None),
    "document_state_change": ({"document_state_id": "document_state"}, None),
    "document_deletion": ({"document_state_id": "document_state"}, None),
    "document_deletion_step": ({"deletion_id": "document_deletion"}, None),
    "document_label": ({"document_id": "document"}, None),
    "artifact": ({"document_id": "document"}, None),
    "page": ({"document_id": "document", "artifact_id": "artifact"}, None),
    "claim": ({"document_id": "document"}, None),
    "claim_version": ({"claim_id": "claim"}, None),
    "evidence_ref": ({"document_id": "document", **_CV}, None),
    "source_match": ({"evidence_ref_id": "evidence_ref", "artifact_id": "artifact"}, None),
    "claim_seen": ({"page_id": "page", **_CV}, None),
    "claim_note": (_CV, None),
    "metric_assignment": (_CV, None),
    "match_review": (_CV, None),
    "correction": ({**_CV, "corrects_version_id": "claim_version"}, None),
    "basis": ({"document_id": "document"}, None),
    "basis_scope": ({"basis_id": "basis"}, None),
    "inference": ({**_CV, "basis_id": "basis"}, None),
    "inference_review": ({**_CV, "inference_id": "inference"}, None),
    "sheet_mapping": ({"document_id": "document"}, None),
    "page_acceptance": ({"document_id": "document", "artifact_id": "artifact"}, None),
    "expected_item": ({}, "every declared document (expected_item_document), archived ones included"),
    "expected_item_document": ({"document_id": "document", "expected_item_id": "expected_item"}, None),
    "gap_confirmation": ({"expected_item_id": "expected_item"}, "the ids in documents_checked"),
    "restatement": ({"original_version_id": "claim_version", "restated_version_id": "claim_version",
                     "evidence_document_id": "document"}, None),
    **dict.fromkeys(("review_company", "review_auditor"), ({**_CV, "evidence_document_id": "document"}, None)),
    "adjudication": ({"low_version_id": "claim_version", "high_version_id": "claim_version",
                      "counter_document_id": "document"}, None),
    "reviewer_flag": (_CV, None),
    "highlight": (_CV, None),
    "saved_view": ({}, "rule owned by 7.6, no documents in 7.1"),
}
# Record kinds (P4, C7) and the table that holds each. labels.ships and labels.pseudonyms take either.
KINDS = {
    "claim": "claim", "evidence ref": "evidence_ref", "source match": "source_match", "basis wording": "basis",
    "claim note": "claim_note", "sheet mapping": "sheet_mapping", "page acceptance": "page_acceptance",
    "page row": "page", "correction": "correction", "company confirmation": "review_company",
    "auditor review": "review_auditor", "highlight": "highlight", "adjudication": "adjudication",
    "reviewer flag": "reviewer_flag", "needs-re-review entry": "claim", "comparison pair": "comparison",
    "series point": "series_point", "restatement record": "restatement", "restatement": "restatement",
    "series": "series", "expected item": "expected_item", "gap confirmation": "gap_confirmation",
    "hidden-by-archive entry": "hidden_by_archive", "deleted document": "deleted_document",
    "document label change": "document_label",
}
# C7's pseudonym order; every other attributed table follows in table-name order.
ORDER = ("review_company", "review_auditor", "adjudication", "restatement", "correction", "highlight", "reviewer_flag",
         "gap_confirmation", "page_acceptance", "document_label")
# Dataset fields (C3 keys; dotted for a part of an object field). Part C's builder and 7.7's guards read these.
DOCUMENT_TEXT = frozenset({
    "metric_text", "value_text", "unit_text", "period_label", "boundary_detail", "evidence_text", "evidence_quote",
    "match_reason", "sheet", "header", "row", "document_name", "name", "reason", "correction.replaced"})
IDENTITY = frozenset({"organisation", "capacity", "confirmation.organisation", "confirmation.capacity"})
CONTRIBUTOR_TEXT = frozenset({
    "scope", "conclusion", "rationale", "procedure", "counter_note", "follow_up", "closure_reason", "evidence_note",
    "note", "confirmation.rationale", "correction.contributor", "correction.organisation", "correction.capacity",
    "correction.rationale"})


def default(kind: str, availability: str = "unknown", privacy: str | None = None) -> str:
    """P1: an explicit privacy wins; else shareable only for a report declared public, otherwise private."""
    if privacy is not None:
        return privacy
    return "shareable" if kind == "report" and availability == "public" else "private"


def mark(conn) -> int:
    """labels_mark (V3): the newest document_label id, 0 before any."""
    return conn.execute("SELECT COALESCE(MAX(id), 0) FROM document_label").fetchone()[0]


def intake_row(conn, doc_id: int, privacy: str, availability: str, stamp: str) -> None:
    """The registration's label row (no contributor), written in the registration transaction."""
    conn.execute("INSERT INTO document_label (document_id, privacy, availability, created_at) VALUES (?, ?, ?, ?)",
                 (doc_id, privacy, availability, stamp))


def twins(conn, digest: str, privacy: str, doc_id: int | None = None) -> list[dict]:
    """The documents not deleted, of any company, holding the same file under another stored label (P2)."""
    rows = conn.execute(
        f"SELECT d.id, c.name AS company, {STORED_PRIVACY} AS privacy FROM document d JOIN company c ON c.id = d.company_id"
        f" WHERE d.sha256 = ? AND d.id IS NOT ? AND NOT {_DELETED} ORDER BY d.id", (digest, doc_id)).fetchall()
    return [dict(r) for r in rows if r["privacy"] != privacy]


def twin_warning(found: list[dict]) -> str | None:
    if not found:
        return None
    named = "; ".join(f"document {t['id']} ({t['company']}) has the same file and is labelled {t['privacy']}"
                      for t in found)
    return f"Warning: {named}. While one of them is private, reports treat every document with this file as private."


def change(conn, doc_id: int, privacy=None, availability=None, key=None, capacity=None, rationale=None) -> dict:
    """P2: one insert-only document_label row with the contributor, capacity and rationale. No run is opened."""
    from gct.stages import deletion
    from gct.stages.infer import _who
    from gct.workspace import registry

    doc = registry.show_document(conn, doc_id)
    if doc["state"] == "deleted":
        raise deletion._was_deleted(conn, doc)
    if privacy is None and availability is None:
        raise GctError(USAGE, "Nothing to change was given.",
                       f"Give --privacy or --availability, for example: gct doc label {doc_id} --privacy shareable"
                       " --as KEY --capacity TEXT --rationale TEXT")
    who, capacity, rationale = _who(conn, key, capacity, rationale)
    old = {"privacy": doc["privacy"], "availability": doc["availability"]}
    new = {"privacy": privacy or old["privacy"], "availability": availability or old["availability"]}
    if new == old:
        raise GctError(REFUSED, f"Document {doc_id} is already {old['privacy']}, availability {old['availability']}."
                                " Nothing was stored.",
                       f"Give a label it does not have yet; see it with: gct doc show {doc_id}")
    stamp = store.now()
    with store.transaction(conn):
        row_id = conn.execute(
            "INSERT INTO document_label (document_id, privacy, availability, contributor_version_id, capacity, rationale,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (doc_id, new["privacy"], new["availability"], who["version"], capacity, rationale, stamp)).lastrowid
    return {"document": registry.show_document(conn, doc_id), "old": old, "new": new,
            "change": {"id": row_id, "contributor": who["name"], "organisation": who["organisation"],
                       "capacity": capacity, "rationale": rationale, "created_at": stamp}}


def effective(conn, version_conn=None) -> dict:
    """P3, {document id: {"label", "availability"}} for every document of the workspace, the most restrictive rule
    winning. With a version connection: (1) a document absent from the version is private; (2) a document is private
    when the version projected it private or its stored label is private now. In both forms (3) a document is private
    when a document not deleted with the same file is private by rule 1 or 2 (or its stored label), and a deleted
    document is private. availability is the stored one."""
    rows = conn.execute(f"SELECT d.id, d.sha256, {STORED_PRIVACY} AS privacy, {STORED_AVAILABILITY} AS availability,"
                        f" {_DELETED} AS deleted FROM document d ORDER BY d.id").fetchall()
    projected = None if version_conn is None else dict(version_conn.execute("SELECT id, privacy FROM document"))
    own = {r["id"]: "private" if projected is not None and projected.get(r["id"], "private") == "private"
           else r["privacy"] for r in rows}  # rules 1 and 2 first, so rule 3 spreads them across the sha
    private = {r["sha256"] for r in rows if not r["deleted"] and own[r["id"]] == "private"}
    return {r["id"]: {"label": "private" if r["deleted"] or r["sha256"] in private else own[r["id"]],
                      "availability": r["availability"]} for r in rows}


def _table(kind: str) -> str:
    if kind in KINDS:
        return KINDS[kind]
    if kind in NAMES or kind in KINDS.values():
        return kind
    raise ValueError(f"unknown record kind {kind!r}")


def ships(conn, version_conn, kind: str, doc_ids, mode: str, include=()) -> bool:
    """P6: whether a row of this kind naming these documents leaves in this mode. Complete mode keeps every row.
    Sanitised mode ships a row only when every document it names is shareable (labels.effective); never an archive or
    deletion entry (P8) and a reviewer flag only with the flags inclusion; in the workspace-only form never a fetch
    attempt (it names no document) and never a row naming a deleted document (effective makes it private)."""
    table = _table(kind)
    if mode == "complete":
        return True
    if mode != "sanitised":
        raise ValueError(f"unknown mode {mode!r}")
    if table in ("hidden_by_archive", "deleted_document") or (table == "reviewer_flag" and "flags" not in include):
        return False
    if version_conn is None and table == "attempt" and not doc_ids:
        return False
    # ponytail: effective is read per call; pass the map in if a large package makes this slow.
    labels = effective(conn, version_conn)
    return all(labels.get(d, {"label": "private"})["label"] == "shareable" for d in doc_ids)


def pseudonyms(records) -> dict:
    """C7: {contributor_key: "Contributor N"} over (kind, id, contributor_key) triples of shipped records, numbered in
    the fixed kind order, then table name, then record id."""
    def position(r):
        return (ORDER.index(r[0]) if r[0] in ORDER else len(ORDER), r[0], r[1])

    out = {}
    for _, _, key in sorted(((_table(kind), i, key) for kind, i, key in records), key=position):
        out.setdefault(key, f"Contributor {len(out) + 1}")
    return out


def named(conn, table: str, row) -> set[int]:
    """P4 for a workspace row: the documents it names through the columns of labels.NAMES (foreign keys walked) and
    the table's rule."""
    columns, _ = NAMES[table]
    out = set()
    for col, target in columns.items():
        if row[col] is None:
            continue
        if target == "document":
            out.add(row[col])
        elif parent := conn.execute(f"SELECT * FROM {target} WHERE id = ?", (row[col],)).fetchone():
            out |= named(conn, target, parent)
    if table == "attempt" and row["stage"] != "fetch" and (head := str(row["item"]).split(":")[0]).isdigit():
        out.add(int(head))
    elif table == "gap_confirmation":
        out |= {x["id"] for x in json.loads(row["documents_checked"])}
    elif table == "expected_item":
        out |= {d for (d,) in conn.execute("SELECT document_id FROM expected_item_document WHERE expected_item_id = ?",
                                            (row["id"],))}
    return out
