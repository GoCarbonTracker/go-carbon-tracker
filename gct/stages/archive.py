"""What an archive takes out of the active outputs (story 4.4, J9). Computed, never stored; 4.5 reuses it for deletion."""
from collections import Counter

from gct.stages import match
from gct.workspace import registry

NEWEST = "SELECT MAX(v.id) FROM claim c JOIN claim_version v ON v.claim_id = c.id WHERE c.document_id = ? GROUP BY c.id"
VERSIONS = "SELECT v.id FROM claim c JOIN claim_version v ON v.claim_id = c.id WHERE c.document_id = ?"
# Review records stay stored but leave the active outputs with the document.
REVIEWS = {
    "inference_review": f"SELECT COUNT(*) FROM inference_review WHERE claim_version_id IN ({VERSIONS})",
    "correction": f"SELECT COUNT(*) FROM correction WHERE claim_version_id IN ({VERSIONS})",
    "match_review": f"SELECT COUNT(*) FROM match_review WHERE claim_version_id IN ({VERSIONS})",
    "page_acceptance": "SELECT COUNT(*) FROM page_acceptance WHERE document_id = ?",
    # Gap confirmations are not here: they stay projected and only read as made on older readings (Q3 c).
    # Rows naming a version of its claims, as either side; they leave the projection with the document.
    "restatement": f"SELECT COUNT(*) FROM restatement WHERE original_version_id IN ({VERSIONS})"
                   f" OR restated_version_id IN ({VERSIONS})",
    # Every column mapping row of a spreadsheet (story 4.3); all of them are projected while it is active.
    "sheet_mapping": "SELECT COUNT(*) FROM sheet_mapping WHERE document_id = ?",
    # Company confirmations and auditor reviews on a version of its claims (story 5.1, C7); an entry that only cites
    # it as evidence stays in the outputs, with the evidence document's state.
    "review_company": f"SELECT COUNT(*) FROM review_company WHERE claim_version_id IN ({VERSIONS})",
    "review_auditor": f"SELECT COUNT(*) FROM review_auditor WHERE claim_version_id IN ({VERSIONS})",
}


def counts(conn, doc_id: int) -> dict:
    """The document's claims (newest version of each, as projected), the evidence references of those versions and
    its review records per kind."""
    return {
        "claims": conn.execute(f"SELECT COUNT(*) FROM ({NEWEST})", (doc_id,)).fetchone()[0],
        "evidence_refs": conn.execute(f"SELECT COUNT(*) FROM evidence_ref WHERE claim_version_id IN ({NEWEST})",
                                      (doc_id,)).fetchone()[0],
        "review_records": {k: conn.execute(sql, (doc_id,) * sql.count("?")).fetchone()[0]
                           for k, sql in REVIEWS.items()},
    }


def impact(conn, doc_id: int) -> dict:
    """What archiving one active document drops from the active outputs: its counts, the series it has points in
    (points it gives and points left), the same-period sets that lose a point, its uncertain items and the
    expectations whose state is computed from it."""
    doc = registry.check_archive(conn, doc_id)
    # ponytail: only the document's own points and items; another document's item whose only candidate series
    # disappears is not listed (the series shows points_left 0).
    r = match.compute(conn, doc["company"])
    series, same = [], []
    for s in r["series"].values():
        mine = Counter((p["period_start"], p["period_end"]) for p in s["points"] if p["document_id"] == doc_id)
        if not mine:
            continue
        series.append({"id": s["id"], "metric_key": s["metric_key"], "label": s["label"], "unit_family": s["unit_family"],
                       "reporting_boundary": s["reporting_boundary"], "points": sum(mine.values()),
                       "points_left": len(s["points"]) - sum(mine.values())})
        shared = Counter((p["period_start"], p["period_end"]) for p in s["points"])
        same += [{"series": s["id"], "period_start": a, "period_end": b, "points": shared[a, b],
                  "points_left": shared[a, b] - n} for (a, b), n in sorted(mine.items()) if shared[a, b] > 1]
    return {
        **counts(conn, doc_id),
        "series": sorted(series, key=lambda s: s["id"]),
        "same_period_sets": same,
        "uncertain_items": sum(len(c["items"]) for c in r["claims"] if c["document_id"] == doc_id),
        "expected_items": [i for (i,) in conn.execute(
            "SELECT expected_item_id FROM expected_item_document WHERE document_id = ? ORDER BY expected_item_id", (doc_id,))],
    }


def hidden(conn) -> list[dict]:
    """One record per archived document: what it hides from the projection (A5, Q21)."""
    out = []
    for d in registry.list_documents(conn):
        if d["state"] == "archived":
            c = counts(conn, d["id"])
            out.append({"document_id": d["id"], "logical_name": d["logical_name"],
                        "archived_at": conn.execute("SELECT at FROM document_state WHERE document_id = ? ORDER BY id DESC LIMIT 1",
                                                    (d["id"],)).fetchone()[0], "claims": c["claims"],
                        "evidence_refs": c["evidence_refs"], "review_records": sum(c["review_records"].values())})
    return out
