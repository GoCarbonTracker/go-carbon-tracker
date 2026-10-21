"""Contributors, expected figures and the three missing-evidence states (FR20, FR21).

A missing item is an expectation with no claim at all; a claim without a box is a source match status, never a
missing item. States are computed when asked and never stored; only a reviewer's gap confirmation is a record.
Expectation matching is literal wording (decision Q): no canonical metric, no period resolution, no unit conversion."""
import json
from collections import Counter
from pathlib import Path

from gct.stages.extract import _clean
from gct.stages.read import ACTIVE
from gct.workspace import registry, store
from gct.workspace.layout import NOT_FOUND, REFUSED, USAGE, GctError

TYPES = ("text", "tables", "figures")
INCOMPLETE = "processing incomplete or failed"
NOT_FOUND_IN = "not found in successfully processed material"
CONFIRMED = "confirmed disclosure gap"
# The quality flags that leave a page unchecked for a type. Figures have no reader under rung 1.
FLAGS = {"text": ("no_text", "fragmented_text"), "tables": ("sparse_tables",), "figures": None}
CHARTS = "charts not read"
EARLIER = "accepted on an earlier reading"
PRINTED = "wording printed but no figure extracted"
OTHER_PERIOD = "wording printed; figures found only for other or missing period labels"
LIST = "See the expectations with: gct expect list"


# Contributors (Q14): versions are insert-only; every attributed record cites the version it was made under.

def _contributor(row) -> dict:
    return {"key": row["contributor_key"], "name": row["name"], "organisation": row["organisation"],
            "version": row["id"], "created_at": row["created_at"]}


def _newest(conn, key: str):
    return conn.execute("SELECT * FROM contributor_version WHERE contributor_key = ? ORDER BY id DESC LIMIT 1",
                        (key,)).fetchone()


def contributor(conn, key: str) -> dict:
    """The newest version of a contributor. An unknown key raises with the line that adds it."""
    row = _newest(conn, key)
    if row is None:
        raise GctError(NOT_FOUND, f"There is no contributor with key {key}.",
                       f"Add one with: gct contributor add {key} --name NAME")
    return _contributor(row)


def _text(value, what: str, example: str):
    value = _clean(value)
    if not value:
        raise GctError(USAGE, f"The {what} is empty.", f"Give one, for example: {example}")
    return value


def add_contributor(conn, key: str, name: str, organisation=None) -> dict:
    key = _text(key, "contributor key", 'gct contributor add ana --name "Ana Rao"')
    name = _text(name, "name", f'gct contributor add {key} --name "Ana Rao"')
    with store.transaction(conn):
        if _newest(conn, key) is not None:
            raise GctError(REFUSED, f"Contributor {key} already exists.",
                           f"Change it with: gct contributor edit {key} --name NAME")
        conn.execute("INSERT INTO contributor_version (contributor_key, name, organisation, created_at) VALUES (?, ?, ?, ?)",
                     (key, name, _clean(organisation) or None, store.now()))
    return contributor(conn, key)


def edit_contributor(conn, key: str, name=None, organisation=None) -> dict:
    """A new version with the given fields changed. Records made before keep the version they cite."""
    old = contributor(conn, key)
    if name is None and organisation is None:
        raise GctError(USAGE, "Nothing to change.", f"Give --name or --organisation: gct contributor edit {key} --name NAME")
    name = old["name"] if name is None else _text(name, "name", f'gct contributor edit {key} --name "Ana Rao"')
    organisation = old["organisation"] if organisation is None else _clean(organisation) or None
    with store.transaction(conn):
        conn.execute("INSERT INTO contributor_version (contributor_key, name, organisation, created_at) VALUES (?, ?, ?, ?)",
                     (key, name, organisation, store.now()))
    return contributor(conn, key)


def contributors(conn) -> list[dict]:
    return [_contributor(r) for r in conn.execute(
        "SELECT * FROM contributor_version v WHERE v.id = (SELECT MAX(id) FROM contributor_version"
        " WHERE contributor_key = v.contributor_key) ORDER BY v.contributor_key")]


# Content-type readiness.

def _newest_page(conn, doc_id: int, page: int):
    return conn.execute("SELECT * FROM page WHERE document_id = ? AND page_number = ? ORDER BY id DESC LIMIT 1",
                        (doc_id, page)).fetchone()


def _failed_read(conn, doc_id: int, page: int):
    """The newest read attempt of the page when it failed, else None."""
    row = conn.execute("SELECT run_id, outcome FROM attempt WHERE stage = 'read' AND item = ? ORDER BY id DESC LIMIT 1",
                       (f"{doc_id}:{page}",)).fetchone()
    return row if row and row["outcome"] == "failed" else None


def page_ready(conn, doc_id: int, page: int, type_: str) -> tuple[bool, str | None]:
    """(ready, note) for one content type of one page. note is None when the newest reading checked it, the
    acceptance ("accepted by <name> (<capacity>)") when a reviewer accepted that reading, else why it is not ready."""
    if _failed_read(conn, doc_id, page):
        return False, "read failed"
    row = _newest_page(conn, doc_id, page)
    if row is None:
        return False, "not read"
    flags = [f for f in json.loads(row["flags"]) if f in (FLAGS[type_] or ())]
    if FLAGS[type_] is not None and not flags:
        return True, None
    accepted = conn.execute(
        "SELECT a.artifact_id, a.capacity, c.name FROM page_acceptance a JOIN contributor_version c"
        " ON c.id = a.contributor_version_id WHERE a.document_id = ? AND a.page_number = ? AND a.content_type = ?"
        " ORDER BY a.artifact_id = ? DESC, a.id DESC LIMIT 1", (doc_id, page, type_, row["artifact_id"])).fetchone()
    if accepted and accepted["artifact_id"] == row["artifact_id"]:
        return True, f"accepted by {accepted['name']} ({accepted['capacity']})"
    if accepted:  # decision T: an acceptance holds only for the reading it accepted
        return False, EARLIER
    return False, ", ".join(flags) or CHARTS


def page_count(root, doc: dict) -> tuple[int | None, str | None]:
    """(pages, None) from the stored PDF, or (None, why) when there is no page set."""
    if doc["file_type"] != "pdf":
        return None, "not a PDF"
    import pdfplumber  # 0.8 s; only commands that count pages pay for it

    try:
        with pdfplumber.open(registry.stored_path(Path(root), doc["sha256"])) as pdf:
            return len(pdf.pages), None
    except Exception:
        return None, "not opened"


def _readiness(conn, root, docs) -> tuple[list, list, list]:
    """(reasons, accepted, snapshot) over every page of the documents. reasons and accepted are counted per type;
    snapshot holds each document's id, sha256 and the newest reading artifact of every page (decision T)."""
    reasons, accepted, snapshot = Counter(), Counter(), []
    for d in docs:
        n, why = page_count(root, d)
        if n is None:
            reasons["document", why] += 1
            continue
        artifacts = []
        for page in range(1, n + 1):
            row = _newest_page(conn, d["id"], page)
            artifacts.append(row and row["artifact_id"])
            for t in TYPES:
                ready, note = page_ready(conn, d["id"], page, t)
                if not ready:
                    reasons[t, note] += 1
                elif note:
                    accepted[t, note] += 1
        snapshot.append({"id": d["id"], "sha256": d["sha256"], "artifacts": artifacts})
    return ([{"type": t, "reason": r, "count": n} for (t, r), n in reasons.items()],
            [{"type": t, "accepted": a, "count": n} for (t, a), n in accepted.items()], snapshot)


# Expectations (D1): declared by the user with literal wording and a fixed document set.

def _documents(conn, item_id: int) -> list[dict]:
    return [registry.show_document(conn, i) for (i,) in conn.execute(
        "SELECT document_id FROM expected_item_document WHERE expected_item_id = ? ORDER BY document_id", (item_id,))]


def _claims(conn, item, doc_ids) -> list[dict]:
    """The newest claim versions on the set whose metric wording contains the expectation's, any period label."""
    want = _clean(item["metric_text"]).casefold()
    rows = conn.execute(
        "SELECT c.id, c.document_id, c.page_number, v.metric_text, v.value_text, v.unit_text, v.period_label FROM claim c"
        " JOIN claim_version v ON v.id = (SELECT MAX(id) FROM claim_version WHERE claim_id = c.id)"
        f" WHERE c.document_id IN ({','.join('?' * len(doc_ids))}) ORDER BY c.id", doc_ids)
    return [dict(r) for r in rows if want in _clean(r["metric_text"]).casefold()]


def _reading_text(conn, root, artifact_id: int) -> str:
    path = conn.execute("SELECT path FROM artifact WHERE id = ?", (artifact_id,)).fetchone()[0]
    return json.loads((Path(root) / path).read_text(encoding="utf-8"))["text"]


def _item(conn, item_id: int):
    row = conn.execute("SELECT e.*, c.name AS company FROM expected_item e JOIN company c ON c.id = e.company_id"
                       " WHERE e.id = ?", (item_id,)).fetchone()
    if row is None:
        raise GctError(NOT_FOUND, f"There is no expectation with id {item_id}.", LIST)
    return row


def state(conn, root, item_id: int, confirmed=True) -> dict:
    """An expectation with its claims, or, when it has none, its missing state with the reasons counted per type.
    'confirmed disclosure gap' only from a confirmation on the current readings; confirmed=False leaves it out."""
    item = _item(conn, item_id)
    docs = _documents(conn, item_id)
    worded = _claims(conn, item, [d["id"] for d in docs])
    claims = [c for c in worded if item["period_label"] is None or c["period_label"] == item["period_label"]]
    out = {"id": item["id"], "company": item["company"], "metric_text": item["metric_text"],
           "period_label": item["period_label"], "documents": [d["id"] for d in docs], "found": bool(claims),
           "claims": claims, "state": None, "reasons": [], "accepted": [], "confirmation": None}
    gap = confirmed and conn.execute(
        "SELECT g.*, c.name, c.organisation FROM gap_confirmation g JOIN contributor_version c"
        " ON c.id = g.contributor_version_id WHERE g.expected_item_id = ? ORDER BY g.id DESC LIMIT 1", (item_id,)).fetchone()
    if gap:
        out["confirmation"] = {"id": gap["id"], "contributor": gap["name"], "organisation": gap["organisation"],
                               "capacity": gap["capacity"], "rationale": gap["rationale"],
                               "created_at": gap["created_at"], "current": False}
    if claims:
        return out
    reasons, accepted, snapshot = _readiness(conn, root, docs)
    # Decision U: printed wording is never "not found". The guard checks the wording only, never the period, so
    # a page whose claims carry the wording under other or no period labels gets its own reason.
    want = _clean(item["metric_text"]).casefold()
    other = {f"{c['document_id']}:{c['page_number']}" for c in worded}
    printed = [f"{d['id']}:{n}" for d in snapshot for n, a in enumerate(d["artifacts"], 1)
               if a is not None and want in _clean(_reading_text(conn, root, a)).casefold()]
    for reason, pages in ((PRINTED, [p for p in printed if p not in other]),
                          (OTHER_PERIOD, [p for p in printed if p in other])):
        if pages:
            reasons.append({"type": "text", "reason": reason, "count": len(pages), "pages": pages})
    out.update(state=INCOMPLETE if reasons else NOT_FOUND_IN, reasons=reasons, accepted=accepted, snapshot=snapshot)
    if gap:
        older = json.loads(gap["documents_checked"]) != snapshot
        if out["state"] == NOT_FOUND_IN and not older:
            out["state"], out["confirmation"]["current"] = CONFIRMED, True
        else:
            why = "was made on older readings" if older else "no longer holds: processing incomplete"
            reasons.append({"type": "confirmation", "count": 1, "reason": f"earlier gap confirmation #{gap['id']} {why}"})
    return out


def describe(conn, root, item_id: int) -> dict:
    out = state(conn, root, item_id)
    out.pop("snapshot", None)
    return out


def add_expectation(conn, root, company: str, metric: str, period=None, doc_ids=()) -> dict:
    co = registry._find_company(conn, company)
    metric = _text(metric, "metric wording", f'gct expect add --company "{co["name"]}" --metric "scope 1 emissions"')
    if doc_ids:
        docs = [registry.show_document(conn, i) for i in dict.fromkeys(doc_ids)]
        other = [d["id"] for d in docs if d["company"] != co["name"]]
        if other:
            raise GctError(REFUSED, f"Document {other[0]} belongs to another company.",
                           f"List {co['name']}'s documents with: gct doc list --company \"{co['name']}\"")
    else:
        docs = [d for d in registry.list_documents(conn, co["name"]) if d["kind"] == "report" and d["state"] in ACTIVE]
        if not docs:
            raise GctError(REFUSED, f"{co['name']} has no active report documents to look in.",
                           f"Add one with: gct doc add FILE --company \"{co['name']}\"")
    with store.transaction(conn):
        item_id = conn.execute("INSERT INTO expected_item (company_id, metric_text, period_label, created_at)"
                               " VALUES (?, ?, ?, ?)", (co["id"], metric, _clean(period) or None, store.now())).lastrowid
        conn.executemany("INSERT INTO expected_item_document (expected_item_id, document_id) VALUES (?, ?)",
                         [(item_id, d["id"]) for d in docs])
    return describe(conn, root, item_id)


def expectations(conn, root, company=None) -> list[dict]:
    if company is None:
        ids = conn.execute("SELECT id FROM expected_item ORDER BY id")
    else:
        ids = conn.execute("SELECT id FROM expected_item WHERE company_id = ? ORDER BY id",
                           (registry._find_company(conn, company)["id"],))
    return [describe(conn, root, i) for (i,) in ids.fetchall()]


# Reviewer records: page acceptance and gap confirmation, each with contributor version, capacity and rationale.

def _pages(spec: str, n: int) -> list[int]:
    """Page numbers from '3', '1-4' or '1,3-5'; each must lie in 1..n."""
    out = []
    try:
        for part in spec.split(","):
            a, _, b = part.strip().partition("-")
            out += range(int(a), int(b or a) + 1)
    except ValueError:
        raise GctError(USAGE, f"{spec} is not a page list.", "Give pages like 3, 1-4 or 1,3-5.") from None
    bad = [p for p in out if not 1 <= p <= n]
    if bad or not out:
        raise GctError(REFUSED, f"Page {bad[0] if bad else spec} is not in this document, which has {n} pages.",
                       f"Give pages from 1 to {n}.")
    return sorted(set(out))


def accept_pages(conn, root, doc_id: int, spec: str, type_: str, key: str, capacity: str, rationale: str) -> dict:
    """Record that a reviewer accepts the newest reading of each page for one content type. Only a flagged type or
    figures on a read page can be accepted; a page not read, or whose read failed, must be read first."""
    who = contributor(conn, key)
    capacity = _text(capacity, "capacity", '--capacity "sustainability analyst"')
    rationale = _text(rationale, "rationale", '--rationale "page checked by eye: no chart holds the figure"')
    doc = registry.show_document(conn, doc_id)
    n, why = page_count(root, doc)
    if n is None:
        raise GctError(REFUSED, f"Document {doc_id} has no pages to accept ({why}).", "Only PDF documents that open have pages.")
    rows = []
    for page in _pages(spec, n):
        failed = _failed_read(conn, doc_id, page)
        if failed:
            raise GctError(REFUSED, f"Page {page} could not be read, so it cannot be accepted.",
                           f"Read it again with: gct run retry {failed['run_id']}")
        ready, note = page_ready(conn, doc_id, page, type_)
        if note == "not read":
            raise GctError(REFUSED, f"Page {page} has not been read, so it cannot be accepted.", f"Read it first: gct read {doc_id}")
        if ready and note is None:
            raise GctError(REFUSED, f"Page {page} is already checked for {type_}; there is nothing to accept.",
                           "Accept only pages with a quality flag for that type, or figures.")
        rows.append((doc_id, page, type_, _newest_page(conn, doc_id, page)["artifact_id"], who["version"], capacity,
                     rationale, store.now()))
    with store.transaction(conn):
        conn.executemany("INSERT INTO page_acceptance (document_id, page_number, content_type, artifact_id,"
                         " contributor_version_id, capacity, rationale, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return {"document": doc_id, "type": type_, "pages": [r[1] for r in rows],
            "accepted": f"accepted by {who['name']} ({capacity})"}


def _where(pages: list[str]) -> str:
    """'document 2 pages 33, 36 and 45' from ['2:33', '2:36', '2:45'], per document, joined by '; '."""
    by_doc = {}
    for p in pages:
        d, n = p.split(":")
        by_doc.setdefault(d, []).append(n)
    return "; ".join(f"document {d} page{'s' * (len(ns) > 1)} "
                     + (f"{', '.join(ns[:-1])} and {ns[-1]}" if len(ns) > 1 else ns[0]) for d, ns in by_doc.items())


def confirm_gap(conn, root, item_id: int, key: str, capacity: str, rationale: str) -> dict:
    """Record a reviewer's confirmation that the figure is not disclosed. Refused unless the computed state is
    'not found in successfully processed material': an extraction failure is never confirmed as a gap."""
    who = contributor(conn, key)
    capacity = _text(capacity, "capacity", '--capacity "sustainability analyst"')
    rationale = _text(rationale, "rationale", '--rationale "searched the report; the figure is not given"')
    s = state(conn, root, item_id, confirmed=False)
    if s["found"]:
        raise GctError(REFUSED, f"Expectation {item_id} is found in {len(s['claims'])} claims, so it is not missing.", LIST)
    printed = {r["reason"]: _where(r["pages"]) for r in s["reasons"] if "pages" in r}
    if printed:  # reading, retrying or accepting cannot clear these, so the hint does not suggest it
        why = [f"the wording is printed on {printed[PRINTED]} but no figure carrying it was extracted, so this is an"
               " extraction gap, not a disclosure gap"] if PRINTED in printed else []
        why += [f"the wording is printed on {printed[OTHER_PERIOD]}, but the figures found there carry a period label"
                f" other than {s['period_label']}, or none"] if OTHER_PERIOD in printed else []
        raise GctError(REFUSED, f"Expectation {item_id} cannot be confirmed as a gap: {'; '.join(why)}.",
                       "Check those pages; a correction step comes in a later version. " + LIST)
    if s["state"] != NOT_FOUND_IN:
        types = sorted({r["type"] for r in s["reasons"]})
        raise GctError(REFUSED, f"Expectation {item_id} cannot be confirmed as a gap: processing is incomplete for "
                                f"{', '.join(types)}.", "Read, retry or accept those pages first. " + LIST)
    with store.transaction(conn):
        conn.execute("INSERT INTO gap_confirmation (expected_item_id, contributor_version_id, capacity, rationale,"
                     " documents_checked, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (item_id, who["version"], capacity, rationale, json.dumps(s["snapshot"]), store.now()))
    return describe(conn, root, item_id)
