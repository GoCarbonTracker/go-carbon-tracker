"""The canonical report dataset (story 7.1 part C, the shared E7 contract C1 to C8, V1 to V5): one pinned published
version, one E6 selection, the evidence index, the restatement log and the gap report as plain JSON rows with GCT's
exact words, and the local preview of what was withheld. Sanitised mode (the default) builds one reduced copy of the
pinned projection without the records that do not ship, recomputes every derived value on it (C5a, P10, P11) and
selects there, so a sanitised dataset equals the one of a workspace in which the withheld records never existed.
The builder writes nothing; the caller holds the workspace lock. Stage modules are imported inside the functions."""
import copy
import json
import math
import sqlite3

from gct import __version__
from gct.models import redact
from gct.reports import pin
from gct.workspace import labels, store
from gct.workspace.layout import USAGE, GctError

DATASET_SCHEMA = 1
MODES = ("sanitised", "complete")
INCLUDE = ("contributor_text", "flags", "identity")
BATCH = 1000  # view.MAX_LIMIT and view.MAX_IDS: one table page, one claim_ids batch
# C6: the withheld causes in counting order; whole-row causes first, then the two field causes.
CAUSES = ("private_document", "absent_from_version", "same_bytes_private", "names_private_document", "flag",
          "archived", "deleted", "selection_recomputed", "contributor_text", "identity")
LEDGER_KINDS = {"review_company": "company confirmation", "review_auditor": "auditor review",
                "reviewer_flag": "reviewer flag", "highlight": "highlight"}
# correct.re_review's build order of renewal kinds, the tie order of P11's merged list.
RENEWAL_ORDER = ("correction", "period review", "boundary review", "company confirmation", "auditor review",
                 "reviewer flag", "adjudication")

# C7: per table, the keys withheld in sanitised mode under each inclusion class, whatever the row holds.
WITHHELD = {
    "evidence_index": {"contributor_text": ("correction.contributor", "correction.organisation", "correction.capacity",
                                            "correction.rationale")},
    "records": {"identity": ("organisation", "capacity"),
                "contributor_text": ("scope", "conclusion", "evidence_note", "note", "rationale")},
    "restatements": {"identity": ("organisation", "capacity"), "contributor_text": ("rationale",)},
    "unpaired_restatements": {"identity": ("organisation", "capacity"), "contributor_text": ("rationale",)},
    "adjudications": {"identity": ("organisation", "capacity"),
                      "contributor_text": ("counter_note", "rationale", "procedure", "follow_up", "closure_reason")},
    "expectations": {"identity": ("confirmation.organisation", "confirmation.capacity"),
                     "contributor_text": ("confirmation.rationale",)},
}
WITHHELD["related_claims"] = WITHHELD["evidence_index"]

# words.fixed: every title (sheet-safe, C2a) and every column heading.
TITLES = {
    "evidence_index": "Evidence index", "related_claims": "Related claims", "pair_sides": "Pair sides",
    "restatement_log": "Restatement log", "gap_report": "Gap report", "records": "Review records",
    "disagreements": "Disagreements", "restatements": "Restatement records",
    "unpaired_restatements": "Unpaired restatements", "adjudications": "Adjudications",
    "documents": "Documents", "candidates": "Inconsistency candidates", "expectations": "Expectations",
    "reasons": "Missing reasons", "accepted": "Accepted pages", "declared": "Declared documents",
    "documents_checked": "Documents checked", "extraction_limits": "Extraction limits",
    "archived": "Archived documents", "deleted": "Deleted documents", "about": "About",
}
HEADINGS = {
    "data_version": "Data version", "label": "Label", "id": "ID", "claim_id": "Claim", "version_id": "Claim version",
    "company": "Company", "document_id": "Document", "document_name": "Document name",
    "document_version": "Document version", "page": "Page", "sheet": "Sheet", "cell": "Cell",
    "metric_text": "Metric as printed", "value_text": "Value as printed", "value": "Value",
    "unit_text": "Unit as printed", "period_label": "Period as printed", "period_start": "Period start",
    "period_end": "Period end", "period_state": "Period state", "boundary": "Boundary",
    "boundary_detail": "Boundary detail", "boundary_state": "Boundary state", "claim_state": "Claim state",
    "match_state": "Match state", "match_reason": "Match reason", "evidence_text": "Evidence",
    "review_text": "Review", "needs_renewed_review": "Needs renewed review", "correction.id": "Correction",
    "correction.corrects_version": "Corrects version", "correction.fields": "Corrected fields",
    "correction.replaced.value_text": "Replaced value", "correction.replaced.unit_text": "Replaced unit",
    "correction.replaced.metric_text": "Replaced metric", "correction.replaced.period_label": "Replaced period",
    "correction.created_at": "Corrected on", "correction.contributor": "Corrected by",
    "correction.organisation": "Corrector organisation", "correction.capacity": "Corrector capacity",
    "correction.rationale": "Correction rationale", "kind": "Kind",
    "claim_version_id": "On claim version", "binds": "Binds", "latest": "Latest position",
    "earlier": "Version note", "outcome": "Outcome", "decision": "Decision", "reviewed_on": "Reviewed on",
    "created_at": "Recorded on", "contributor": "Contributor", "organisation": "Organisation",
    "capacity": "Capacity", "scope": "Scope", "conclusion": "Conclusion", "evidence_document_id": "Evidence document",
    "evidence_page": "Evidence page", "evidence_note": "Evidence note", "evidence_state": "Evidence document state",
    "note": "Note", "rationale": "Rationale", "text": "Disagreement", "pair_id": "Pair", "series_id": "Series",
    "metric_key": "Metric key", "reporting_boundary": "Reporting boundary", "unit_family": "Unit family",
    "claim_a": "Claim A", "claim_b": "Claim B", "outside_selection.a": "Claim A selection",
    "outside_selection.b": "Claim B selection", "state": "State", "reason": "Reason",
    "shown_state": "Adjudication state", "restatement_id": "Restatement", "original_version_id": "Original version",
    "restated_version_id": "Restated version", "original_claim_id": "Original claim",
    "restated_claim_id": "Restated claim", "evidence_quote": "Quote", "adjudication_id": "Adjudication record",
    "low_version_id": "First claim version", "high_version_id": "Second claim version", "state_text": "Outcome words",
    "counter_document_id": "Counter document", "counter_page": "Counter page", "counter_note": "Counter note",
    "procedure": "Procedure", "follow_up": "Follow-up", "closure_reason": "Closure reason", "name": "Name",
    "version": "Version", "file_type": "File type", "availability": "Availability",
    "expected_item_id": "Expectation", "found": "Found", "claims": "Claims",
    "confirmation.gap_confirmation_id": "Gap confirmation", "confirmation.current": "Confirmation current",
    "confirmation.created_at": "Confirmed on", "confirmation.contributor": "Confirmed by",
    "confirmation.organisation": "Confirmer organisation", "confirmation.capacity": "Confirmer capacity",
    "confirmation.rationale": "Confirmation rationale", "type": "Content type", "count": "Count",
    "pages": "Pages", "acceptance_id": "Acceptance", "read": "Pages read", "read_failed": "Pages whose read failed",
    "not_read": "Pages not read", "limit_text": "Text not ready", "limit_tables": "Tables not ready",
    "limit_figures": "Figures not ready", "sheets_mapped": "Sheets mapped", "limit_note": "Limit",
    "archived_at": "Archived on", "deleted_at": "Deleted on",
}
_CLAIM = ("data_version", "claim_id", "version_id", "company", "document_id", "document_name", "document_version", "page",
          "sheet", "cell", "metric_text", "value_text", "value", "unit_text", "period_label", "period_start", "period_end",
          "period_state", "boundary", "boundary_detail", "boundary_state", "claim_state", "match_state", "match_reason",
          "evidence_text", "review_text", "needs_renewed_review", "correction.id", "correction.corrects_version",
          "correction.fields", "correction.replaced.value_text", "correction.replaced.unit_text",
          "correction.replaced.metric_text", "correction.replaced.period_label", "correction.created_at",
          "correction.contributor", "correction.organisation", "correction.capacity", "correction.rationale")
_PAIR = ("data_version", "id", "series_id", "metric_key", "reporting_boundary", "unit_family", "period_start",
         "period_end", "claim_a", "claim_b", "outside_selection.a", "outside_selection.b", "state", "reason",
         "shown_state")
_KEYS = {
    "evidence_index": _CLAIM, "related_claims": _CLAIM,
    "records": ("data_version", "claim_id", "id", "kind", "claim_version_id", "binds", "latest", "earlier",
                "outcome", "decision", "reviewed_on", "created_at", "contributor", "organisation", "capacity", "scope",
                "conclusion", "evidence_document_id", "evidence_page", "evidence_note", "evidence_state", "note",
                "rationale"),
    "disagreements": ("data_version", "claim_id", "claim_version_id", "text"),
    "restatement_log": _PAIR, "candidates": _PAIR,
    "restatements": ("data_version", "pair_id", "restatement_id", "original_version_id", "restated_version_id",
                     "decision", "evidence_document_id", "evidence_page", "evidence_quote", "binds", "earlier",
                     "contributor", "organisation", "capacity", "rationale", "created_at"),
    "unpaired_restatements": ("data_version", "restatement_id", "original_claim_id", "restated_claim_id",
                              "original_version_id", "restated_version_id", "decision", "evidence_document_id",
                              "evidence_page", "evidence_quote", "binds", "earlier", "contributor", "organisation",
                              "capacity", "rationale", "created_at"),
    "adjudications": ("data_version", "pair_id", "adjudication_id", "low_version_id", "high_version_id", "state_text",
                      "binds", "earlier", "counter_document_id", "counter_page", "counter_note", "rationale",
                      "procedure", "follow_up", "closure_reason", "contributor", "organisation", "capacity",
                      "created_at"),
    "documents": ("data_version", "id", "company", "name", "version", "kind", "file_type", "availability", "state"),
    "expectations": ("data_version", "expected_item_id", "company", "metric_text", "period_label", "found", "claims",
                     "state", "confirmation.gap_confirmation_id", "confirmation.current", "confirmation.created_at",
                     "confirmation.contributor", "confirmation.organisation", "confirmation.capacity",
                     "confirmation.rationale"),
    "reasons": ("data_version", "expected_item_id", "type", "reason", "count", "pages"),
    "accepted": ("data_version", "expected_item_id", "type", "acceptance_id", "count"),
    "declared": ("data_version", "expected_item_id", "document_id", "state"),
    "documents_checked": ("data_version", "document_id", "pages", "read", "read_failed", "not_read", "limit_text",
                          "limit_tables", "limit_figures", "sheets_mapped", "limit_note"),
    "extraction_limits": ("data_version", "type", "reason", "count"),
    "archived": ("data_version", "document_id", "name", "archived_at", "claims"),
    "deleted": ("data_version", "document_id", "deleted_at"),
}
# C3: {table id: ordered columns}; the label column is printed in complete mode only.
COLUMNS = {t: [{"key": k, "heading": HEADINGS[k]} for k in keys] + [
    {"key": "label", "heading": HEADINGS["label"], "complete_only": True}] for t, keys in _KEYS.items()}
SUB_TABLES = {"records": "claim_id", "disagreements": "claim_id", "restatements": "pair_id",
              "adjudications": "pair_id", "reasons": "expected_item_id", "accepted": "expected_item_id",
              "declared": "expected_item_id", "unpaired_restatements": None}  # C3: the one parent_key null

EARLIER = "on an earlier version"
PRIVACY_NOTICE = "Private content is excluded from this output."
ARCHIVE_NOTICE = "Archived and permanently deleted documents are not included."
EXPECTATIONS_SCOPE = ("Expectations are selected by the filter's company and document fields only; its other fields"
                      " do not apply to them.")
SHEETS_LIMIT = "Only sheets with a confirmed column mapping are read."
NOT_OPENED = "The file could not be opened, so no page of it was read."
ALL_PRIVATE = "Every document in this selection is private, so a sanitised output holds no rows."
SOME_PRIVATE = "These documents in this selection are private, so a sanitised output leaves out their rows:"
RELABEL = ("To share a document's rows, relabel it: gct doc label ID --privacy shareable --as KEY --capacity TEXT"
           " --rationale TEXT")


def sanitised_empty(version: int) -> str:
    """DF14: one wording in sanitised mode whether rows were withheld or not."""
    return f"No shareable claims match this filter in data version {version}."


def words() -> dict:
    """C2a: GCT's fixed wording, the only text a renderer adds to the rows."""
    from gct.stages import review

    return {
        "self_declared": review.SELF_DECLARED, "privacy_notice": PRIVACY_NOTICE, "archive_notice": ARCHIVE_NOTICE,
        "earlier_version": EARLIER, "earlier_position": "an earlier position of this contributor",
        "outside_selection": "outside this selection", "withheld": "withheld",
        "needs_renewed_review": "needs renewed review",
        "fixed": {
            "titles": dict(TITLES), "headings": dict(HEADINGS), "about_csv": ["Field", "Value"], "separator": "; ",
            "identity": {"version": "Data version", "built_at": "Version built at", "sha256": "SHA-256",
                         "projection_schema": "Projection schema", "history_mark": "History mark",
                         "labels_mark": "Labels mark"},
            "dataset": {"gct_version": "GCT version", "built_at": "Dataset built at", "dataset_schema": "Dataset schema",
                        "filter": "Filter", "include": "Included classes"},
            "mode": {"sanitised": "Sanitised output: private content and contributor details are left out.",
                     "complete": "Complete output: every row of the selection, each with its label."},
            "data_version": "Data version", "label": HEADINGS["label"],
            "image_alt": "Evidence for claim {claim}, document {document}, page {page}",
            "image_cap": "The outlined area is where GCT found the figure on the page.",
            "booleans": {"true": "yes", "false": "no"}, "sheets_limit": SHEETS_LIMIT, "not_opened": NOT_OPENED,
            "expectations_scope": EXPECTATIONS_SCOPE,
            "pdf": {"appendix": "Evidence appendix", "page": "Page", "of": "of", "font_note":
                    "Some characters cannot be drawn in this font and are shown as boxes."},
        },
    }


def _finite(x):
    return x if x is None or math.isfinite(x) else None


def _scrub(x):
    """P9: every string through redact.scrub."""
    if isinstance(x, str):
        return redact.scrub(x)
    if isinstance(x, list):
        return [_scrub(v) for v in x]
    if isinstance(x, dict):
        return {k: _scrub(v) for k, v in x.items()}
    return x


def _in(ids) -> tuple[str, str]:
    return "(SELECT value FROM json_each(?))", json.dumps(sorted(ids))


class _Build:
    """One build: the pin, the label lookup, the inclusion decisions and the contributor keys, shared by the
    complete rows (on the pin) and the sanitised rows (on the reduced copy)."""

    def __init__(self, conn, root, pconn, ident, flt, include):
        self.conn, self.root, self.pconn, self.ident, self.flt, self.include = conn, root, pconn, ident, flt, include
        self.version = ident["version"]
        self.p16 = ident["projection_schema"] >= 16  # ponytail: goes with sides()' fallback at the C-projection merge
        self.eff = labels.effective(conn, pconn)  # P3, read once
        self._ships, self._keys, self._books = {}, {}, {}

    # P6: labels.ships decides; asked once per kind and document set.
    def ships(self, kind, docs) -> bool:
        key = (kind, frozenset(docs))
        if key not in self._ships:
            self._ships[key] = labels.ships(self.conn, self.pconn, kind, sorted(docs), "sanitised", self.include)
        return self._ships[key]

    def label(self, docs) -> str:
        return "private" if any(self.eff.get(d, {"label": "private"})["label"] == "private" for d in docs) \
            else "shareable"

    def keys(self, table, ids) -> dict:
        """{record id: contributor_key} (C7), from contributor_version by record id (V2)."""
        want = set(ids) - set(self._keys.get(table, {}))
        if want:
            sql, p = _in(want)
            if table in ("review_company", "review_auditor"):  # the projection carries the contributor version
                rows = self.pconn.execute(f"SELECT id, contributor_version FROM {table} WHERE id IN {sql}", (p,))
                cv = dict(rows.fetchall())
                found = dict(self.conn.execute(
                    f"SELECT id, contributor_key FROM contributor_version WHERE id IN {_in(cv.values())[0]}",
                    (_in(cv.values())[1],)).fetchall())
                got = {i: found[v] for i, v in cv.items()}
            else:
                got = dict(self.conn.execute(
                    f"SELECT r.id, c.contributor_key FROM {table} r JOIN contributor_version c"
                    f" ON c.id = r.contributor_version_id WHERE r.id IN {sql}", (p,)).fetchall())
            self._keys.setdefault(table, {}).update(got)
        return {i: self._keys[table][i] for i in ids if i in self._keys.get(table, {})}

    def book(self, doc) -> dict:
        """The workbook of a spreadsheet, read once per build (one sheet.read_book per stored file)."""
        from gct.stages import sheet

        if doc["sha256"] not in self._books:
            self._books[doc["sha256"]] = dict(sheet._book(self.root, dict(doc)))
        return self._books[doc["sha256"]]

    # C5a: the reduced copy.
    def reduce(self) -> sqlite3.Connection:
        rconn = sqlite3.connect(":memory:")
        rconn.deserialize(self.pconn.serialize())  # no second file read (V2)
        rconn.row_factory = sqlite3.Row
        claim_doc = dict(rconn.execute("SELECT id, document_id FROM claim").fetchall())
        docs = {d for (d,) in rconn.execute("SELECT id FROM document")}
        # P-match: the claims that wait with candidates, taken before any removal (the triggers drop their rows).
        waiting = {c for (c,) in rconn.execute("SELECT DISTINCT claim_id FROM match_candidate")} if self.p16 else set()

        def drop(table, kind, named, key="rowid"):
            gone = [r[key] for r in rconn.execute(f"SELECT {key} AS {key}, * FROM {table}").fetchall()
                    if None in (n := named(r)) or not self.ships(kind, n)]
            if gone:
                sql, p = _in(gone)
                rconn.execute(f"DELETE FROM {table} WHERE {key} IN {sql}", (p,))
            return set(gone)

        def of_claims(*cols):
            return lambda r: {claim_doc.get(r[c]) for c in cols}

        drop("document", "document", lambda r: {r["id"]})
        drop("claim", "claim", lambda r: {r["document_id"]})
        drop("evidence_ref", "evidence ref", lambda r: {r["document_id"]})
        drop("series_point", "series point", of_claims("claim_id"))
        # P4 and P4a: a restatement row names both claims' documents and its evidence document; a side the version
        # cannot trace is withheld.
        sides = self.sides(rconn)
        drop("restatement", "restatement record", lambda r: {claim_doc.get(c) for c in sides(r)} | {
            r["evidence_document_id"]})
        for t in ("review_company", "review_auditor"):
            drop(t, LEDGER_KINDS[t], lambda r: of_claims("claim_id")(r) | (
                {r["evidence_document_id"]} if r["evidence_document_id"] is not None else set()))
        drop("highlight", "highlight", of_claims("claim_id"))
        drop("reviewer_flag", "reviewer flag", of_claims("claim_id"))
        drop("adjudication", "adjudication", lambda r: of_claims("low_claim_id", "high_claim_id")(r) | (
            {r["counter_document_id"]} if r["counter_document_id"] is not None else set()))
        gone = drop("expected_item", "expected item", lambda r: self.item_docs(rconn, r["id"]), key="id")
        if gone:
            sql, p = _in(gone)
            for t in ("expected_item_document", "gap_confirmation"):
                rconn.execute(f"DELETE FROM {t} WHERE expected_item_id IN {sql}", (p,))
        for t, kind in (("page", "page row"), ("page_acceptance", "page acceptance"), ("sheet_mapping", "sheet mapping")):
            drop(t, kind, lambda r: {r["document_id"]})
        for t in ("hidden_by_archive", "deleted_document"):  # P8: never named or counted in sanitised mode
            drop(t, t, lambda r: set())
        assert docs >= {d for (d,) in rconn.execute("SELECT id FROM document")}

        self._latest(rconn)
        self._match(rconn, waiting)
        self._renewals(rconn)  # after 3.5, which finishes the comparison states 3.3's adjudication rule reads
        rconn.commit()
        rconn.execute("PRAGMA query_only = 1")
        return rconn

    def item_docs(self, c, item_id) -> set:
        """P4: an expected item names every declared document, archived ones included, and the ids its gap
        confirmation looked in."""
        out = {d for (d,) in c.execute("SELECT document_id FROM expected_item_document WHERE expected_item_id = ?",
                                       (item_id,))}
        for (checked,) in c.execute("SELECT documents_checked FROM gap_confirmation WHERE expected_item_id = ?",
                                    (item_id,)):
            out |= {x["id"] for x in json.loads(checked)}
        return out

    def _latest(self, rconn):
        """C5a 3.1: latest per contributor key and claim version over the remaining ledger rows (review.py:25-26)."""
        for t in ("review_company", "review_auditor"):
            rows = rconn.execute(f"SELECT id, claim_version_id FROM {t} ORDER BY id").fetchall()
            keys = self.keys(t, [r["id"] for r in rows])
            newest = {}
            for r in rows:
                newest[(keys[r["id"]], r["claim_version_id"])] = r["id"]
            sql, p = _in(newest.values())
            rconn.execute(f"UPDATE {t} SET latest = id IN {sql}", (p,))

    def sides(self, work):
        """The two claim ids of a restatement row (projection 16's columns). ponytail: below 16 only current version
        ids resolve (None otherwise); this fallback goes when the C-projection branch merges and pin requires 16."""
        if self.p16:
            return lambda r: (r["original_claim_id"], r["restated_claim_id"])
        version_claim = dict(work.execute("SELECT claim_version_id, id FROM claim").fetchall())
        return lambda r: (version_claim.get(r["original_version_id"]), version_claim.get(r["restated_version_id"]))

    def _match(self, rconn, waiting):
        """C5a 3.4 and 3.5 (P-match steps 2 to 7): series by their remaining rule points; each waiting claim's match
        state by match.compute's rule over its remaining candidates in the reduced creation order; its reviewed point
        removed or constructed (match._point); then every comparison pair rebuilt by restate._pairs over the
        resulting points and the remaining restatement rows, and the series aggregates."""
        from gct.stages import match, restate

        rconn.execute("DELETE FROM series WHERE id NOT IN (SELECT series_id FROM series_point WHERE link = 'rule')")
        rconn.execute("DELETE FROM series_point WHERE series_id NOT IN (SELECT id FROM series)")
        if self.p16:
            rconn.execute("DELETE FROM match_candidate WHERE series_id NOT IN (SELECT id FROM series)"
                          " OR claim_id NOT IN (SELECT id FROM claim)")
            # match.compute makes ordinary series in its first pass and as-printed ones in its second, each at its
            # first rule point in document then claim order.
            order = {}
            for r in rconn.execute("SELECT p.series_id, p.comparable, c.document_id, c.id FROM series_point p"
                                   " JOIN claim c ON c.id = p.claim_id WHERE p.link = 'rule'"):
                k = (0 if r["comparable"] else 1, r["document_id"], r["id"])
                order[r["series_id"]] = min(order.get(r["series_id"], k), k)
            candidates = {}
            for r in rconn.execute("SELECT claim_id, series_id, decision FROM match_candidate"):
                candidates.setdefault(r["claim_id"], []).append(r)
            claims = {r["id"]: r for r in rconn.execute("SELECT * FROM claim")}
            for cid in sorted(waiting & set(claims)):
                c = claims[cid]
                known = c["boundary_state"] in match.KNOWN and c["reporting_boundary"] != "unknown"
                reason = match.BOUNDARY_UNKNOWN if not known else match.UNIT_UNKNOWN if c["unit_key"] is None \
                    else match.NOT_CONVERTIBLE
                rows = sorted(candidates.get(cid, []), key=lambda r: order[r["series_id"]])
                linked = next((r["series_id"] for r in rows if r["decision"] == "linked"), None)
                state = (match.NOT_MATCHABLE, reason + match.NO_SERIES, None) if not rows else (
                    match.REVIEWED, reason, linked) if linked else (match.UNCERTAIN, reason, None) if any(
                    r["decision"] is None for r in rows) else (match.NOT_MATCHABLE, match.NOT_LINKED, None)
                rconn.execute("UPDATE claim SET match_state = ?, match_reason = ?, series_id = ? WHERE id = ?",
                              (*state, cid))
                rconn.execute("DELETE FROM series_point WHERE claim_id = ? AND link = 'reviewed' AND series_id IS NOT ?",
                              (cid, linked))
                if linked and not rconn.execute("SELECT 1 FROM series_point WHERE claim_id = ? AND series_id = ?",
                                                (cid, linked)).fetchone():
                    p = match._point({**dict(c), "claim_id": cid, "period": {"start": c["period_start"],
                                                                             "end": c["period_end"]}},
                                     "reviewed", False, reason)
                    rconn.execute("INSERT INTO series_point (series_id, claim_id, claim_version_id, period_start,"
                                  " period_end, value_text, unit_text, unit_key, number, value_base, link, comparable,"
                                  " reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                  (linked, cid, p["claim_version_id"], p["period_start"], p["period_end"],
                                   p["value_text"], p["unit_text"], p["unit_key"], p["number"], p["value_base"],
                                   p["link"], 0, p["reason"]))
        rconn.execute("UPDATE series SET periods = (SELECT COUNT(*) FROM (SELECT DISTINCT period_start, period_end"
                      " FROM series_point p WHERE p.series_id = series.id)),"
                      " latest_period_end = (SELECT MAX(period_end) FROM series_point p WHERE p.series_id = series.id)")
        # restate._records over the remaining rows: the newest row per version pair, kept when recorded.
        newest = {}
        for r in rconn.execute("SELECT id, original_version_id, restated_version_id, decision FROM restatement"
                               " ORDER BY id"):
            newest[(r["original_version_id"], r["restated_version_id"])] = r
        records = {frozenset(k): {"id": r["id"]} for k, r in sorted(newest.items(), key=lambda kv: kv[1]["id"])
                   if r["decision"] == "recorded"}
        points = {}
        for r in rconn.execute("SELECT p.*, c.document_id, c.page_number, c.locator FROM series_point p"
                               " JOIN claim c ON c.id = p.claim_id ORDER BY p.rowid"):
            points.setdefault(r["series_id"], []).append(dict(r))
        pairs = [p for s in rconn.execute("SELECT * FROM series").fetchall()
                 for p in restate._pairs(dict(s), points.get(s["id"], []), records)]
        pairs.sort(key=lambda p: (p["company_id"], p["series_id"], p["period_end"], p["period_start"],
                                  p["a"]["claim_id"], p["b"]["claim_id"]))
        rconn.execute("DELETE FROM comparison")
        rconn.executemany("INSERT INTO comparison (series_id, period_start, period_end, claim_a, version_a, claim_b,"
                          " version_b, state, reason, restatement_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          [(p["series_id"], p["period_start"], p["period_end"], p["a"]["claim_id"],
                            p["a"]["claim_version_id"], p["b"]["claim_id"], p["b"]["claim_version_id"], p["state"],
                            p["reason"], p["restatement"] and p["restatement"]["id"]) for p in pairs])

    def _renewals(self, rconn):
        """C5a 3.3, P11: each claim's needs_re_review on the remaining records. Correction, period and boundary
        reviews kept as projected; reviewer flags kept only with the flags inclusion; both ledgers and adjudications
        recomputed by correct.re_review's rules (correct.py:52-111) on the copy's rows."""
        from gct.stages import restate

        claims = rconn.execute("SELECT id, claim_version_id, needs_re_review FROM claim").fetchall()
        ledgers = {}
        for t in ("review_company", "review_auditor"):
            for r in rconn.execute(f"SELECT id, claim_id, claim_version_id FROM {t} ORDER BY id"):
                ledgers.setdefault((LEDGER_KINDS[t], r["claim_id"]), []).append(r)
        adj = {}
        for a in rconn.execute("SELECT * FROM adjudication ORDER BY id"):
            for cid in {a["low_claim_id"], a["high_claim_id"]}:
                adj.setdefault(cid, []).append(a)
        unresolved = {frozenset((p["claim_a"], p["claim_b"])) for p in rconn.execute(
            "SELECT claim_a, claim_b FROM comparison WHERE state = ?", (restate.UNRESOLVED,))}
        kept = {"correction", "period review", "boundary review"} | ({"reviewer flag"} if "flags" in self.include else set())
        for c in claims:
            out = [e for e in json.loads(c["needs_re_review"]) if e["kind"] in kept]
            for kind in ("company confirmation", "auditor review"):
                rows = ledgers.get((kind, c["id"]), [])
                if rows and not any(r["claim_version_id"] == c["claim_version_id"] for r in rows):
                    r = rows[-1]
                    out.append({"kind": kind, "id": r["id"], "version": r["claim_version_id"]})
            rows = adj.get(c["id"], [])
            bound = {frozenset((a["low_claim_id"], a["high_claim_id"])) for a in rows if a["binds"]}
            newest = {}
            for a in rows:
                pair = frozenset((a["low_claim_id"], a["high_claim_id"]))
                if a["binds"] or pair not in unresolved - bound:
                    continue
                sides = {a["low_claim_id"]: a["low_version_id"], a["high_claim_id"]: a["high_version_id"]}
                (other,) = pair - {c["id"]}
                newest[other] = {"kind": "adjudication", "id": a["id"], "version": sides[c["id"]],
                                 "with": {"claim": other, "version": sides[other]}}
            out += newest.values()
            out.sort(key=lambda e: (e["id"], RENEWAL_ORDER.index(e["kind"])))
            rconn.execute("UPDATE claim SET needs_re_review = ? WHERE id = ?", (json.dumps(out), c["id"]))

    # The rows of one connection (the pin in complete mode, the copy in sanitised mode).
    def rows(self, work, mode) -> dict:
        return _Rows(self, work, mode).tables()


class _Rows:
    def __init__(self, b: _Build, work, mode):
        from gct.stages import view

        self.b, self.work, self.mode, self.view = b, work, mode, view
        self.v = b.version
        self.docs = {r["id"]: r for r in work.execute(
            "SELECT d.*, m.name AS company_name FROM document d JOIN company m ON m.id = d.company_id")}
        self.claims = {r["id"]: r for r in work.execute(
            "SELECT id, document_id, company_id, claim_version_id, correction, needs_re_review, period_basis,"
            " boundary_basis, series_id FROM claim")}
        self.version_claim = {r["claim_version_id"]: i for i, r in self.claims.items()}
        self.records = {}
        for t in LEDGER_KINDS:
            for r in work.execute(f"SELECT * FROM {t} ORDER BY id"):
                self.records.setdefault(r["claim_id"], []).append((t, r))
        self.evidence, self._evidence_ids = [], {}

    def ships(self, kind, docs) -> bool:
        return self.mode == "complete" or self.b.ships(kind, docs)

    def common(self, rid, docs, evidence=(), untraceable=False) -> dict:
        """C3-common keys. An untraceable document (a record the version does not hold) makes the row private."""
        return {"id": rid, "data_version": self.v, "label": "private" if untraceable else self.b.label(docs),
                "documents": sorted(docs), "evidence": list(evidence), "withheld": [], "_docs": set(docs),
                "_untraceable": untraceable}

    def location(self, kind, doc_id, page=None, boxes=None, sheet_name=None, cell=None):
        """C3d: an evidence entry of a document in the version, or None."""
        from gct.stages import sheet

        d = self.docs.get(doc_id)
        if d is None or (page is None and cell is None):
            return None
        key = (kind, doc_id, page, json.dumps(boxes), sheet_name, cell)
        if key not in self._evidence_ids:
            e = {"id": len(self.evidence) + 1, "kind": kind, "document_id": doc_id, "sha256": d["sha256"], "page": page,
                 "boxes": boxes, "sheet": sheet_name, "cell": cell, "header": None, "row": None, "marked": None}
            rows = self.b.book(d).get(sheet_name) if cell is not None else None
            if rows:
                letters = cell.rstrip("0123456789")
                n, col = int(cell[len(letters):]), sheet._index(letters)
                e.update(header=list(rows[0]), row=list(rows[n - 1]) if n <= len(rows) else [], marked=col)
            self.evidence.append(e)
            self._evidence_ids[key] = e["id"]
        return self._evidence_ids[key]

    def cited(self, kind, doc_id, page):
        d = self.docs.get(doc_id)
        if d is None or d["file_type"] != "pdf" or page is None:
            return None
        return self.location(kind, doc_id, page=page)

    # Claims (C3a).
    def answer_rows(self, flt, claim_ids=None) -> list[dict]:
        out, offset = [], 0
        while True:
            page = self.view.answer(self.work, flt, "table", offset, BATCH, claim_ids=claim_ids)
            out += page["rows"]
            if claim_ids is not None or len(page["rows"]) < BATCH:
                return out
            offset += BATCH

    def renewal_docs(self, cid, entries) -> set:
        """P4: an entry names the documents of the record it points to and the with claim's document."""
        own = self.claims[cid]["document_id"]
        out = set()
        for e in entries:
            out.add(own)
            if e["kind"] in ("company confirmation", "auditor review"):
                t = "review_company" if e["kind"] == "company confirmation" else "review_auditor"
                r = next((r for tt, r in self.records.get(cid, []) if tt == t and r["id"] == e["id"]), None)
                if r is None or r["evidence_document_id"] is not None:
                    out.add(None if r is None else r["evidence_document_id"])
            elif e["kind"] == "adjudication":
                a = self.work.execute("SELECT counter_document_id FROM adjudication WHERE id = ?", (e["id"],)).fetchone()
                out.add(self.claims.get(e["with"]["claim"], {"document_id": None})["document_id"])
                if a is None or a["counter_document_id"] is not None:
                    out.add(None if a is None else a["counter_document_id"])
        return out

    def claim_row(self, r) -> dict | None:
        from gct.stages import correct

        c, x = r["claim"], self.claims[r["claim"]["id"]]
        entries = json.loads(x["needs_re_review"])
        docs = {c["document"]} | self.renewal_docs(c["id"], entries)
        untraceable = None in docs  # a renewal entry whose record the version does not hold (complete mode only)
        docs.discard(None)
        if not self.ships("claim", docs) or (untraceable and self.mode != "complete"):
            return None
        ev = []
        if c["sheet"] is not None:
            ev.append(self.location("claim", c["document"], sheet_name=c["sheet"], cell=c["cell"]))
        elif r["evidence"]["page"] is not None:
            ev.append(self.location("claim", c["document"], page=r["evidence"]["page"], boxes=r["evidence"]["boxes"]))
        if self.docs[c["document"]]["file_type"] == "pdf":
            for raw in (x["period_basis"], x["boundary_basis"]):
                if raw and (p := json.loads(raw)["page"]) is not None:
                    ev.append(self.location("basis", c["document"], page=p))
        made = x["correction"] and json.loads(x["correction"])
        d = self.docs[c["document"]]
        row = {**self.common(c["id"], docs, [e for e in dict.fromkeys(ev) if e is not None], untraceable),
               "claim_id": c["id"], "version_id": x["claim_version_id"], "company": r["company_name"],
               "document_id": c["document"], "document_name": r["document_name"], "document_version": d["version"],
               "page": c["page"], "sheet": c["sheet"], "cell": c["cell"], "metric_text": c["metric_text"],
               "value_text": c["value_text"], "value": _finite(c["value"]), "unit_text": c["unit_text"],
               "period_label": c["period_label"], "period_start": c["period"]["start"],
               "period_end": c["period"]["end"], "period_state": c["period"]["state"],
               "boundary": c["boundary"]["value"], "boundary_detail": c["boundary"]["detail"],
               "boundary_state": c["boundary"]["state"], "claim_state": c["claim_state"],
               "match_state": c["match_state"], "match_reason": c["match_reason"],
               "evidence_text": r["evidence"]["text"], "review_text": r["review"]["text"],
               "needs_renewed_review": [correct.entry_text(e) for e in entries],
               "correction": made and {"id": made["id"], "corrects_version": made["corrects_version"],
                                       "fields": made["fields"], "replaced": made["replaced"],
                                       "created_at": made["created_at"], "contributor": made["contributor"],
                                       "organisation": made["organisation"], "capacity": made["capacity"],
                                       "rationale": made["rationale"]},
               "_who": [("correction", made["id"])] if made else [], "_own": {c["document"]}}
        row["records"], row["disagreements"] = self.records_of(c["id"], x["document_id"])
        return row

    def records_of(self, cid, own) -> tuple[dict, dict]:
        from gct.stages import review

        recs, latest = [], {}
        for t, r in self.records.get(cid, []):
            docs = {own} | ({r["evidence_document_id"]} if t in ("review_company", "review_auditor")
                            and r["evidence_document_id"] is not None else set())
            if not self.ships(LEDGER_KINDS[t], docs):
                continue
            ledger = t in ("review_company", "review_auditor")
            ev = self.cited("review", r["evidence_document_id"], r["evidence_page"]) if ledger else None
            recs.append({**self.common(r["id"], docs, [ev] if ev else []), "claim_id": cid,
                         "kind": LEDGER_KINDS[t], "claim_version_id": r["claim_version_id"], "binds": bool(r["binds"]),
                         "latest": bool(r["latest"]), "earlier": None if r["binds"] else EARLIER,
                         "outcome": r["outcome"] if ledger else None,
                         "decision": r["decision"] if t == "reviewer_flag" else None,
                         "reviewed_on": r["reviewed_on"] if ledger else None, "created_at": r["created_at"],
                         "contributor": r["contributor_name"], "organisation": r["contributor_organisation"],
                         "capacity": r["capacity"], "scope": r["scope"] if ledger else None,
                         "conclusion": r["conclusion"] if ledger else None,
                         "evidence_document_id": r["evidence_document_id"] if ledger else None,
                         "evidence_page": r["evidence_page"] if ledger else None,
                         "evidence_note": r["evidence_note"] if ledger else None,
                         "evidence_state": r["evidence_state"] if ledger else None,
                         "note": r["note"] if t == "highlight" else None,
                         "rationale": r["rationale"] if t == "reviewer_flag" else None,
                         "_who": [(t, r["id"])], "_own": {own}, "_flag": t == "reviewer_flag",
                         "_key": ("records", t, r["id"])})
            if ledger and r["latest"]:
                latest.setdefault(r["claim_version_id"], {}).setdefault(t, []).append(r)
        dis = []
        for v in sorted(latest):
            pos = {t: [o for o in review.OUTCOMES if any(r["outcome"] == o for r in latest[v].get(t, []))]
                   for t in ("review_company", "review_auditor")}
            company, auditor = pos["review_company"], pos["review_auditor"]
            if company and auditor and company != auditor:
                docs = {own} | {r["evidence_document_id"] for rs in latest[v].values() for r in rs
                                if r["evidence_document_id"] is not None}
                dis.append({**self.common(v, docs), "claim_id": cid, "claim_version_id": v,
                            "text": review.disagreement_line(v, {"company": company, "auditor": auditor}),
                            "_own": {own}, "_key": ("disagreements", v)})
        return self.sub("records", recs), self.sub("disagreements", dis)

    @staticmethod
    def sub(table, rows) -> dict:
        return {"id": table, "title": TITLES[table], "rows": rows, "parent_key": SUB_TABLES[table],
                "columns": None}  # columns filled per mode in _finish

    # Pairs (C3b).
    def pair_rows(self, selected) -> tuple[list, list]:
        from gct.stages import adjudicate, restate

        rest = {r["id"]: r for r in self.work.execute("SELECT * FROM restatement ORDER BY id")}
        sides = self.b.sides(self.work)
        by_claims = {}  # P-match: a restatement row attaches to the pair of its two claims, on any version
        for r in rest.values():
            if None not in (s := sides(r)):
                by_claims.setdefault(frozenset(s), []).append(r)
        adjs = self.work.execute("SELECT * FROM adjudication ORDER BY id").fetchall()
        comparisons = self.work.execute("SELECT * FROM comparison ORDER BY rowid").fetchall()
        out = []
        for p in comparisons:
            a, b = p["claim_a"], p["claim_b"]
            if a not in selected and b not in selected:
                continue
            own = {self.claims[a]["document_id"], self.claims[b]["document_id"]}
            docs = own | ({rest[p["restatement_id"]]["evidence_document_id"]} if p["restatement_id"] else set())
            if not self.ships("comparison pair", docs):
                continue
            pid = len(out) + 1
            subs = [x for r in by_claims.get(frozenset((a, b)), []) if (x := self.restatement(r, own, pair_id=pid))]
            ads = []
            for x in adjs:
                if frozenset((x["low_claim_id"], x["high_claim_id"])) != frozenset((a, b)):
                    continue
                adocs = own | ({x["counter_document_id"]} if x["counter_document_id"] is not None else set())
                if not self.ships("adjudication", adocs):
                    continue
                ev = self.cited("review", x["counter_document_id"], x["counter_page"])
                ads.append({**self.common(x["id"], adocs, [ev] if ev else []), "pair_id": pid,
                            "adjudication_id": x["id"], "low_version_id": x["low_version_id"],
                            "high_version_id": x["high_version_id"], "state_text": adjudicate.STATES[x["state"]],
                            "binds": bool(x["binds"]), "earlier": None if x["binds"] else EARLIER,
                            "counter_document_id": x["counter_document_id"], "counter_page": x["counter_page"],
                            "counter_note": x["counter_note"], "rationale": x["rationale"],
                            "procedure": x["procedure"], "follow_up": x["follow_up"],
                            "closure_reason": x["closure_reason"], "contributor": x["contributor_name"],
                            "organisation": x["contributor_organisation"], "capacity": x["capacity"],
                            "created_at": x["created_at"], "_who": [("adjudication", x["id"])], "_own": own,
                            "_key": ("adjudications", x["id"])})
            s = self.work.execute("SELECT * FROM series WHERE id = ?", (p["series_id"],)).fetchone()
            out.append({**self.common(pid, docs), "series_id": p["series_id"], "metric_key": s["metric_key"],
                        "reporting_boundary": s["reporting_boundary"], "unit_family": s["unit_family"],
                        "period_start": p["period_start"], "period_end": p["period_end"], "claim_a": a, "claim_b": b,
                        "outside_selection": [a not in selected, b not in selected], "state": p["state"],
                        "reason": p["reason"],
                        "shown_state": adjudicate._shown([{"binds": x["binds"], "state": self._state_of(x, adjs)}
                                                          for x in ads]) if p["state"] == restate.UNRESOLVED else None,
                        "restatements": self.sub("restatements", subs), "adjudications": self.sub("adjudications", ads),
                        "_own": own, "_key": ("pair", p["series_id"], p["period_start"], p["period_end"], a, b)})
        # C3b: the rows whose two claims form no pair in this version, in the selection when either claim is.
        paired = {frozenset((p["claim_a"], p["claim_b"])) for p in comparisons}
        unpaired = [x for k, rs in by_claims.items() if k not in paired and k & set(selected) for r in rs
                    if (x := self.restatement(r, {self.claims[c]["document_id"] for c in k}, claims=sides(r)))]
        unpaired.sort(key=lambda x: x["id"])
        return out, [p for p in out if p["state"] == restate.UNRESOLVED], unpaired

    def restatement(self, r, own, pair_id=None, claims=None) -> dict | None:
        """A restatement row (C3b): under its pair (pair_id) or unpaired (its two claim ids)."""
        docs = own | {r["evidence_document_id"]}
        if not self.ships("restatement record", docs):
            return None
        ev = self.cited("restatement", r["evidence_document_id"], r["evidence_page"])
        head = {"pair_id": pair_id} if claims is None else {"original_claim_id": claims[0],
                                                            "restated_claim_id": claims[1]}
        table = "restatements" if claims is None else "unpaired_restatements"
        return {**self.common(r["id"], docs, [ev] if ev else []), **head, "restatement_id": r["id"],
                "original_version_id": r["original_version_id"], "restated_version_id": r["restated_version_id"],
                "decision": r["decision"], "evidence_document_id": r["evidence_document_id"],
                "evidence_page": r["evidence_page"], "evidence_quote": r["evidence_quote"], "binds": bool(r["binds"]),
                "earlier": None if r["binds"] else EARLIER, "contributor": r["contributor_name"],
                "organisation": r["contributor_organisation"], "capacity": r["capacity"], "rationale": r["rationale"],
                "created_at": r["created_at"], "_who": [("restatement", r["id"])], "_own": own,
                "_key": (table, r["id"])}

    @staticmethod
    def _state_of(row, adjs):
        return next(x["state"] for x in adjs if x["id"] == row["adjudication_id"])

    # The gap report (C3c).
    def expectations(self) -> list[dict]:
        from gct.stages import correct, missing

        f, out = self.b.flt, []
        names = dict(self.work.execute("SELECT id, name FROM company").fetchall())
        for e in self.work.execute("SELECT * FROM expected_item ORDER BY id").fetchall():
            links = self.work.execute("SELECT document_id, state FROM expected_item_document WHERE expected_item_id = ?"
                                      " ORDER BY document_id", (e["id"],)).fetchall()
            if "company" in f and e["company_id"] not in f["company"]:
                continue
            if "document" in f and not {x["document_id"] for x in links} & set(f["document"]):
                continue
            docs = self.b.item_docs(self.work, e["id"])
            if not self.ships("expected item", docs):
                continue
            active = [x["document_id"] for x in links if x["state"] != "archived" and x["document_id"] in self.docs]
            want = missing._clean(e["metric_text"]).casefold()
            sql, p = _in(active)
            claims = [r["id"] for r in self.work.execute(
                f"SELECT id, metric_text, period_label, claim_state FROM claim WHERE document_id IN {sql} ORDER BY id",
                (p,)) if r["claim_state"] == correct.CURRENT and want in missing._clean(r["metric_text"] or "").casefold()
                and (e["period_label"] is None or r["period_label"] == e["period_label"])]
            g = self.work.execute("SELECT * FROM gap_confirmation WHERE expected_item_id = ? ORDER BY id DESC LIMIT 1",
                                  (e["id"],)).fetchone()
            base = {"expected_item_id": e["id"], "_own": docs}
            reasons = [{**self.common(i, docs), **base, "type": x["type"], "reason": x["reason"], "count": x["count"],
                        "pages": x.get("pages"), "_key": ("reasons", e["id"], i)}
                       for i, x in enumerate(json.loads(e["reasons"]), 1)]
            accepted = [{**self.common(x["acceptance_id"], docs), **base, "type": x["type"],
                         "acceptance_id": x["acceptance_id"], "count": x["count"],
                         "_key": ("accepted", e["id"], x["acceptance_id"], x["type"])}
                        for x in json.loads(e["accepted"])]
            declared = [{**self.common(x["document_id"], {x["document_id"]}), **base, "document_id": x["document_id"],
                         "state": x["state"], "_key": ("declared", e["id"], x["document_id"])} for x in links]
            out.append({**self.common(e["id"], docs), "expected_item_id": e["id"], "company": names[e["company_id"]],
                        "metric_text": e["metric_text"], "period_label": e["period_label"], "found": bool(e["found"]),
                        "claims": claims, "state": e["state"],
                        "confirmation": g and {"gap_confirmation_id": g["id"], "current": bool(g["current"]),
                                               "created_at": g["created_at"], "contributor": g["contributor_name"],
                                               "organisation": g["contributor_organisation"], "capacity": g["capacity"],
                                               "rationale": g["rationale"]},
                        "reasons": self.sub("reasons", reasons), "accepted": self.sub("accepted", accepted),
                        "declared": self.sub("declared", declared),
                        "_who": [("gap_confirmation", g["id"])] if g else [], "_own": docs,
                        "_key": ("expectations", e["id"])})
        return out

    def checked(self) -> tuple[list, list]:
        """documents_checked and extraction_limits over the documents of the gap-document scope that ship (K9)."""
        from gct.stages import missing

        rows, limits = [], {}
        for i in _scope(self.b.flt, self.docs):
            if not self.ships("document", {i}):
                continue
            d = self.docs[i]
            base = {**self.common(i, {i}), "document_id": i, "pages": None, "read": None, "read_failed": None,
                    "not_read": None, "limit_text": None, "limit_tables": None, "limit_figures": None,
                    "sheets_mapped": None, "limit_note": None, "_own": {i}, "_key": ("documents_checked", i)}
            if d["file_type"] != "pdf":
                base.update(sheets_mapped=[p for (p,) in self.work.execute(
                    "SELECT DISTINCT position FROM sheet_mapping WHERE document_id = ? ORDER BY position", (i,))],
                            limit_note=SHEETS_LIMIT)
                rows.append(base)
                continue
            pages = self.work.execute("SELECT * FROM page WHERE document_id = ? ORDER BY page_number", (i,)).fetchall()
            states = [p["read_state"] for p in pages]
            base.update(pages=len(pages), read=states.count("read"), read_failed=states.count("read failed"),
                        not_read=states.count("not read"), limit_note=None if pages else NOT_OPENED)
            for t in missing.TYPES:
                # A page not ready for a type; an accepted page (accepted #ID) is not a limit.
                notes = [p[f"limit_{t}"] for p in pages if p[f"limit_{t}"] and not p[f"limit_{t}"].startswith("accepted #")]
                base[f"limit_{t}"] = len(notes)
                for n in notes:
                    limits.setdefault((t, n), []).append(i)
            rows.append(base)
        if rows:
            limits.setdefault(("figures", missing.CHARTS), [])  # the fixed rung-1 limit (missing.py:21)
        out = []
        for (t, n), pages in sorted(limits.items(), key=lambda kv: (missing.TYPES.index(kv[0][0]), kv[0][1])):
            out.append({**self.common(len(out) + 1, set(pages)), "type": t, "reason": n, "count": len(pages),
                        "_own": set(pages), "_key": ("extraction_limits", t, n)})
        return rows, out

    def archive_rows(self) -> tuple[list, list]:
        """P8: complete mode only (the copy holds neither table)."""
        arch = [{**self.common(r["document_id"], {r["document_id"]}), "document_id": r["document_id"],
                 "name": r["logical_name"], "archived_at": r["archived_at"], "claims": r["claims"], "_own": set(),
                 "_key": ("archived", r["document_id"])}
                for r in self.work.execute("SELECT * FROM hidden_by_archive ORDER BY document_id")]
        gone = [{**self.common(r["document_id"], {r["document_id"]}), "document_id": r["document_id"],
                 "deleted_at": r["deleted_at"], "_own": set(), "_key": ("deleted", r["document_id"])}
                for r in self.work.execute("SELECT * FROM deleted_document ORDER BY document_id")]
        return arch, gone

    def tables(self) -> dict:
        flt = self.b.flt
        selected = self.view.select(self.work, flt)
        sel = set(selected)
        first = self.view.answer(self.work, flt, "table", 0, 1)
        index = [x for r in self.answer_rows(flt) if (x := self.claim_row(r))]
        pairs, candidates, unpaired = self.pair_rows(sel)
        candidates = copy.deepcopy(candidates)  # the same pairs, rows of their own
        sides = sorted({c for p in pairs for c in (p["claim_a"], p["claim_b"])} - sel)
        related = []
        for i in range(0, len(sides), BATCH):
            related += [x for r in self.answer_rows({}, sides[i:i + BATCH]) if (x := self.claim_row(r))]
        for t, rows in (("evidence_index", index), ("related_claims", related)):
            for r in rows:
                r["_key"] = (t, r["claim_id"])
        checked, limits = self.checked()
        arch, gone = self.archive_rows() if self.mode == "complete" else ([], [])
        return {"selected": selected, "answer": first, "evidence_index": index, "related_claims": related,
                "restatement_log": pairs, "unpaired_restatements": unpaired, "candidates": candidates,
                "expectations": self.expectations(),
                "documents_checked": checked, "extraction_limits": limits, "archived": arch, "deleted": gone,
                "evidence": self.evidence, "docs": self.docs, "claims": self.claims}


def _scope(flt, docs) -> list[int]:
    """The gap-document scope: the active documents the filter's company and document fields name (7.1-P7)."""
    return sorted(i for i, d in docs.items() if ("company" not in flt or d["company_id"] in flt["company"])
                  and ("document" not in flt or i in flt["document"]))


def _flat(tables) -> list[tuple[str, dict]]:
    """(table, row) of every report and sub-table row, related claims included (C6's counting unit)."""
    out = []
    for t in ("evidence_index", "related_claims", "restatement_log", "unpaired_restatements", "candidates",
              "expectations", "documents_checked", "extraction_limits", "archived", "deleted"):
        for r in tables[t]:
            out.append((t, r))
            for k in SUB_TABLES:
                if k in r:
                    out += [(k, x) for x in r[k]["rows"]]
    return out


def build(conn, root, *, filter=None, mode="sanitised", include=(), data_version=None) -> tuple[dict, dict]:
    """(dataset, preview) of the current published version (C1). The caller holds the workspace lock. Refusals:
    an unknown mode or inclusion class (exit 2), the filter's own (view.normalise, exit 2) and pin's (exit 4)."""
    from gct.stages import view

    if mode not in MODES:
        raise GctError(USAGE, f"The mode {mode} is not sanitised or complete.", "Leave it out for a sanitised output.")
    include = sorted(set(include))
    if unknown := [x for x in include if x not in INCLUDE]:
        raise GctError(USAGE, f"{unknown[0]} is not an inclusion class.", f"Include any of: {', '.join(INCLUDE)}.")
    flt = view.normalise({} if filter is None else filter)
    pconn, ident = pin.pin(conn, root, data_version)
    try:
        b = _Build(conn, root, pconn, ident, flt, include)
        full = b.rows(pconn, "complete")
        if mode == "complete":
            mine = full
        else:
            rconn = b.reduce()
            try:
                mine = b.rows(rconn, "sanitised")
            finally:
                rconn.close()
        return _finish(b, mode, full, mine)
    finally:
        pconn.close()


def _finish(b: _Build, mode, full, mine) -> tuple[dict, dict]:
    from gct.stages import view

    sanitised, flt, v = mode == "sanitised", b.flt, b.version
    restore = {c for c in ("identity", "contributor_text") if c in b.include}
    rows = _flat(mine)
    # C7: pseudonyms over the shipped records, in the fixed order.
    if sanitised and "identity" not in b.include:
        refs = [ref for _, r in rows for ref in r.get("_who", [])]
        by_table = {}
        for t, i in refs:
            by_table.setdefault(t, set()).add(i)
        keys = {(t, i): k for t, ids in by_table.items() for i, k in b.keys(t, ids).items()}
        names = labels.pseudonyms([(t, i, keys[(t, i)]) for t, i in dict.fromkeys(refs)])
        for _, r in rows:
            for t, i in r.get("_who", []):
                target = r["confirmation"] if t == "gap_confirmation" else r
                if t != "correction" and target is not None:
                    target["contributor"] = names[keys[(t, i)]]
    for t, r in rows if sanitised else ():
        for cls, fields in WITHHELD.get(t, {}).items():
            if cls in restore:
                continue
            for f in fields:
                r["withheld"].append(f)
                head, _, part = f.partition(".")
                if part:
                    if r[head] is not None:
                        r[head][part] = None
                else:
                    r[f] = None
    # Field causes (C6) and the complete rows not shipped (whole-row causes).
    withheld = dict.fromkeys(CAUSES, 0)
    for t, r in rows:
        for cls in ("contributor_text", "identity"):
            if set(r["withheld"]) & set(WITHHELD.get(t, {}).get(cls, ())):
                withheld[cls] += 1
    if sanitised:
        shipped = {(t, r["_key"]) for t, r in rows}
        present = set(full["docs"])
        twins = _twins(b, present)
        for t, r in _flat(full):
            if (t, r["_key"]) not in shipped:
                withheld[_cause(b, t, r, present, twins)] += 1
    # Documents (C2): every document the rows name, plus the gap report's documents that ship.
    named = sorted({d for _, r in rows for d in r["_docs"]} | {r["document_id"] for r in mine["documents_checked"]})
    hidden = {r["document_id"]: r for r in b.pconn.execute("SELECT * FROM hidden_by_archive")}
    gone = {r["document_id"] for r in b.pconn.execute("SELECT document_id FROM deleted_document")}
    documents = []
    for i in named:
        d, e = mine["docs"].get(i), b.eff.get(i, {"label": "private", "availability": "unknown"})
        state = "active" if d else "archived" if i in hidden else "deleted" if i in gone else "not in this version"
        documents.append({"id": i, "data_version": v, "label": e["label"], "documents": [i], "evidence": [],
                          "withheld": [], "company": d and d["company_name"],
                          "name": d["logical_name"] if d else hidden[i]["logical_name"] if i in hidden else None,
                          "version": d and d["version"], "kind": d and d["kind"], "file_type": d and d["file_type"],
                          "availability": e["availability"], "state": state, "_company": d and d["company_id"]})
    empty = not mine["evidence_index"]
    notices = []
    if sanitised:
        notices += [sanitised_empty(v)] * empty + [PRIVACY_NOTICE, ARCHIVE_NOTICE]
    else:
        a = full["answer"]
        notices += [view.empty_text(v)] * empty + [x for x in [a["hidden_by_archive"]["text"]] if x]
        notices += [x["text"] for x in a["deleted_in_filter"]]
    if set(flt) - {"company", "document"}:
        notices.append(EXPECTATIONS_SCOPE)
    echo = dict(flt)
    if sanitised:
        companies = {d["_company"] for d in documents}
        series = {mine["claims"][r["claim_id"]]["series_id"] for t, r in rows if t in ("evidence_index", "related_claims")}
        series |= {r["series_id"] for r in mine["restatement_log"]}
        for k, keep in (("company", companies), ("document", {d["id"] for d in documents}), ("series", series)):
            if k in echo:
                echo[k] = [x for x in echo[k] if x in keep]
        if "text" in echo:
            echo["text"], echo["withheld"] = None, ["text"]
    columns = {t: [dict(c) for c in cols if not (sanitised and c.get("complete_only"))] for t, cols in COLUMNS.items()}
    for t, r in rows:
        for k in SUB_TABLES:
            if k in r:
                r[k]["columns"] = columns[k]
    ident = {k: b.ident[k] for k in ("version", "built_at", "sha256", "projection_schema")}
    if not sanitised:
        ident.update(history_mark=b.ident["history_mark"], labels_mark=b.ident["labels_mark"])

    def clean(x):
        if isinstance(x, list):
            return [clean(y) for y in x]
        if isinstance(x, dict):
            return {k: clean(y) for k, y in x.items() if not k.startswith("_")}
        return x

    dataset = _scrub(clean({
        "dataset_schema": DATASET_SCHEMA, "gct_version": __version__, "built_at": store.now(), "mode": mode,
        "include": b.include, "data_version": ident, "filter": echo, "words": words(), "columns": columns,
        "documents": documents, "evidence_index": mine["evidence_index"], "related_claims": mine["related_claims"],
        "restatement_log": mine["restatement_log"],
        "unpaired_restatements": {**_Rows.sub("unpaired_restatements", mine["unpaired_restatements"]),
                                  "columns": columns["unpaired_restatements"]},
        "gap_report": {k: mine[k] for k in ("candidates", "expectations", "documents_checked", "extraction_limits",
                                            "archived", "deleted")},
        "evidence": mine["evidence"], "notices": notices}))
    counts = {}
    for t, _ in rows:
        counts[t] = counts.get(t, 0) + 1
    preview = _scrub({
        "included": {"documents": [{"id": d["id"], "sha256": mine["docs"][d["id"]]["sha256"] if d["id"] in mine["docs"]
                                    else None, "label": d["label"]} for d in documents], "rows": counts},
        "withheld": withheld, "history_mark": b.ident["history_mark"], "labels_mark": b.ident["labels_mark"],
        "filter": flt, "lines": _lines(b, full) if sanitised else [],
        "answer": {k: full["answer"][k] for k in ("matched", "total", "excluded")}
        | {"hidden_by_archive": {k: full["answer"]["hidden_by_archive"][k] for k in ("documents", "claims")},
           "deleted_in_filter": len(full["answer"]["deleted_in_filter"])}})
    return dataset, preview


def _cause(b: _Build, table, r, present: set, twins: set) -> str:
    """C6: the first whole-row cause, in list order, of a complete row that sanitised mode does not hold. present:
    the documents of the version; twins: those private only by P3 rule 3."""
    if table in ("archived", "deleted"):
        return table
    own, named = r["_own"], r["_docs"]
    absent = named - present
    private = {d for d in named & present if b.eff[d]["label"] == "private"}
    if (private - twins) & own:
        return "private_document"
    if absent or r["_untraceable"]:
        return "absent_from_version"
    if private & twins & own:
        return "same_bytes_private"
    if private:
        return "names_private_document"
    if r.get("_flag"):
        return "flag"
    return "selection_recomputed"


def _twins(b: _Build, present: set) -> set:
    """The documents of the version that are private only because a document not deleted holds the same file under a
    private label (P3 rule 3): stored label shareable (registry, the display reader of the stored label), and a
    private twin. A cause name for preview only; labels.effective made the label."""
    from gct.workspace import registry

    docs = registry.list_documents(b.conn)
    private_sha = {d["sha256"]: [] for d in docs}
    for d in docs:
        if d["state"] != "deleted" and b.eff[d["id"]]["label"] == "private":
            private_sha[d["sha256"]].append(d["id"])
    return {d["id"] for d in docs if d["id"] in present and d["privacy"] == "shareable"
            and b.eff[d["id"]]["label"] == "private" and set(private_sha[d["sha256"]]) - {d["id"]}}


def _lines(b: _Build, full) -> list[str]:
    """P-empty's fixed text (preview only): the private documents of the scope and the relabel command."""
    scope = sorted({full["claims"][c]["document_id"] for c in full["selected"]} | set(_scope(b.flt, full["docs"])))
    private = [i for i in scope if b.eff[i]["label"] == "private"]
    if not private:
        return []
    docs = full["docs"]
    lines = [f"{i}  {docs[i]['company_name']}  {docs[i]['logical_name']}  private" for i in private]
    return [ALL_PRIVATE if len(private) == len(scope) else SOME_PRIVATE, *lines, RELABEL]
