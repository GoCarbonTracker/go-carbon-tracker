"""Packages (story 7.6): a reopenable workspace folder written fresh, row by row, from the source workspace.

One writer for both modes. Which rows ship is labels.ships over labels.named, with the table name as the kind; this
module holds no document-naming map and computes no label. COLUMNS decides how a shipped row is written, never
whether it ships. gct package preview shows the plan and its token; gct package create recomputes the plan under the
workspace lock, refuses another token and writes exports/package-v<N>-<stamp>-<mode>/."""
import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from gct import __version__
from gct.models.redact import scrub, scrub_key
from gct.reports import pin as pinning
from gct.reports.export import folder as _folder
from gct.stages import deletion, match, sheet
from gct.workspace import labels, layout, published, registry, runs, store
from gct.workspace.layout import REFUSED, USAGE, GctError

ID, ID_HASH, KEEP, CONTENT, IDENTITY, TEXT, LOCAL = (
    "id", "id_hash", "keep", "content", "identity", "contributor_text", "local")


def _c(**classes) -> dict:
    return {col: cls for cls, cols in classes.items() for col in cols.split()}


# Every column of every workspace.db table, by package class (D3). tests/test_package.py fails when the schema has a
# table or column this map does not name, so a later migration classifies its own.
COLUMNS = {
    "schema_version": _c(keep="version applied_at"),
    "workspace": _c(id="id", keep="created_at gct_version"),
    "company": _c(id="id", keep="name sector_ref sector_version created_at"),
    "document": _c(id="id company_id", keep="version sha256 kind file_type privacy size_bytes created_at",
                   content="logical_name", local="source"),
    "document_state": _c(id="id document_id", keep="state at", contributor_text="note"),
    "published_version": _c(id="id", keep="version built_at history_mark companies documents gct_version"),
    "published_pointer": _c(id="id version", keep="action at"),
    "published_purge": _c(id="id version", keep="reason at"),
    "run": _c(id="id", keep="started_at command gct_version"),
    "run_event": _c(id="id run_id", keep="at kind stage method outcome cost_estimated cost_confirmed",
                    local="item message"),
    # input_version hashes claim-version ids (infer, match) or a mapping id (sheet); extract's is "page N" (ID_TEXT).
    "attempt": _c(id="id run_id", keep="stage config_version method rung outcome cost_estimated cost_confirmed at",
                  id_hash="input_version", content="item output", local="error"),
    "artifact": _c(id="id document_id", keep="sha256 kind path size_bytes created_at"),
    "page": _c(id="id document_id artifact_id",
               keep="page_number rung method config_version width height words tables flags created_at"),
    "approval": _c(id="id run_id", keep="kind provider destination amount granted created_at"),
    "claim": _c(id="id company_id document_id", keep="page_number locator sector_ref sector_version created_at"),
    "claim_version": _c(id="id claim_id run_id", keep="method config_version created_at",
                        content="metric_text value_text value unit_text period_label period_kind period_start"
                                " period_end metric_key reporting_boundary boundary_detail boundary_label"),
    "evidence_ref": _c(id="id claim_version_id document_id", keep="page_number created_at", content="boxes sheet cell"),
    "source_match": _c(id="id evidence_ref_id run_id artifact_id", keep="status config_version created_at",
                       content="reason"),
    "contributor_version": _c(id="id", keep="created_at", identity="contributor_key name organisation"),
    "expected_item": _c(id="id company_id", keep="created_at", content="metric_text period_label"),
    "expected_item_document": _c(id="expected_item_id document_id"),
    "page_acceptance": _c(id="id document_id artifact_id contributor_version_id",
                          keep="page_number content_type created_at", contributor_text="capacity rationale"),
    "gap_confirmation": _c(id="id expected_item_id contributor_version_id", keep="documents_checked created_at",
                           contributor_text="capacity rationale"),
    "basis": _c(id="id document_id run_id", keep="page_number kind config_version created_at",
                content="wording fy_end period_start period_end boundary boundary_detail"),
    "basis_scope": _c(id="id basis_id contributor_version_id", keep="first_page last_page created_at",
                      contributor_text="capacity rationale"),
    "inference": _c(id="id claim_version_id basis_id run_id", keep="field state reason config_version created_at",
                    content="period_kind period_start period_end boundary boundary_detail group_key"),
    "inference_review": _c(id="id inference_id claim_version_id contributor_version_id",
                           keep="field decision created_at",
                           content="period_kind period_start period_end boundary boundary_detail",
                           contributor_text="capacity rationale"),
    "correction": _c(id="id claim_version_id corrects_version_id contributor_version_id", keep="fields created_at",
                     contributor_text="capacity rationale"),
    "claim_seen": _c(id="id claim_version_id page_id run_id", keep="config_version created_at"),
    "metric_assignment": _c(id="id claim_version_id run_id", keep="unit_source config_version created_at",
                            content="metric_key rule unit_key unit_factor"),
    "match_review": _c(id="id claim_version_id contributor_version_id", keep="reason decision created_at",
                       content="series_key", contributor_text="capacity rationale"),
    "restatement": _c(id="id original_version_id restated_version_id evidence_document_id contributor_version_id",
                      keep="decision evidence_page created_at", content="series_key evidence_quote",
                      contributor_text="capacity rationale"),
    "document_state_change": _c(id="id document_state_id contributor_version_id", keep="created_at",
                                contributor_text="capacity rationale"),
    "sheet_mapping": _c(id="id document_id contributor_version_id", keep="position created_at",
                        content="sheet metric_col value_col unit_col period_col boundary_col company_col note_col"
                                " year_end boundary_is boundary_detail",
                        contributor_text="capacity rationale"),
    "claim_note": _c(id="id claim_version_id", keep="created_at", content="text"),
    "document_deletion": _c(id="id document_state_id", keep="plan created_at"),
    "document_deletion_step": _c(id="id deletion_id", keep="step detail created_at"),
    **dict.fromkeys(("review_company", "review_auditor"), _c(
        id="id claim_version_id contributor_version_id evidence_document_id",
        keep="reviewed_on outcome evidence_page created_at", contributor_text="capacity scope conclusion evidence_note")),
    "adjudication": _c(id="id low_version_id high_version_id counter_document_id contributor_version_id",
                       keep="state counter_page created_at",
                       contributor_text="rationale procedure counter_note follow_up closure_reason capacity"),
    "reviewer_flag": _c(id="id claim_version_id contributor_version_id", keep="decision created_at",
                        contributor_text="rationale capacity"),
    "highlight": _c(id="id claim_version_id contributor_version_id", keep="created_at",
                    contributor_text="capacity note"),
    "saved_view": _c(id="id contributor_version_id", keep="action section created_at", contributor_text="name",
                     content="filter"),
    "document_label": _c(id="id document_id contributor_version_id", keep="privacy availability created_at",
                         contributor_text="capacity rationale"),
}

# Row ids inside text and JSON, with the table each points at; nothing here changes what is written (7.7 and the
# differential renumber by it). "stages" limits an attempt column to those stages; "partial" marks a column where
# only some values hold an id.
_NAMING = ("read", "extract", "sheet", "link", "infer", "match")
ID_TEXT = {
    ("attempt", "item"): {"stages": _NAMING, "pattern": r"^(\d+)(?::|$)", "table": "document"},
    ("attempt", "input_version"): {"stages": ("extract",), "pattern": r"^page (\d+)$", "table": "page"},
    ("attempt", "output"): {"stages": ("read", "infer", "sheet"),
                            "json": {"read": {"page_id": "page"}, "infer": {"bases": "basis"},
                                     "sheet": {"claims": "claim"}}},
    ("source_match", "reason"): {"pattern": r"under mapping #(\d+) ", "table": "sheet_mapping", "partial": True},
    ("basis", "wording"): {"pattern": r"^declared in sheet mapping #(\d+) by ", "table": "sheet_mapping",
                           "partial": True},
    ("gap_confirmation", "documents_checked"): {"json": {"id": "document"}, "list": True},
    # infer's group key, a JSON list: the claim's document id first and the basis id at index 8 (or "label" or null)
    ("inference", "group_key"): {"positions": {0: "document", 8: "basis"}},
    # match's series key, a JSON list: the company id first, an unmapped metric's document id inside the metric at 1
    # ("doc:N:pP:tR:label"), and for a unit as printed series the document id at 5
    **dict.fromkeys((("match_review", "series_key"), ("restatement", "series_key")),
                    {"positions": {0: "company", 1: {"pattern": r"^doc:(\d+):", "table": "document"},
                                   5: "document"}}),
}

FROM_INIT = ("schema_version", "workspace")  # written by init in both modes
NEVER = ("approval", "published_version", "published_pointer", "published_purge")  # the package builds its own v1
COMPLETE_ONLY = ("saved_view",)
REFERENCED = ("company", "contributor_version", "run")  # sanitised: only rows a shipped row points at
# Sanitised: tables whose series_key names a series; a row ships only while shipped claims form that series.
SERIES_NAMED = ("match_review", "restatement")
# Machine text built from claim text, written with redact.scrub_key in both modes (published/v1.db's series labels,
# keys and unit families come from match.compute, which builds them that way)
KEY_TEXT = {("match_review", "series_key"), ("restatement", "series_key"), ("inference", "group_key")}
INCLUDE = ("identity", "contributor_text", "flags")
CAUSES = ("private_document", "absent_from_version", "same_bytes_private", "names_private_document", "flag",
          "archived", "deleted", "selection_recomputed", "contributor_text", "identity")
MARKER = "withheld from the sanitised package"
DECLARED = "declared in sheet mapping #{} by {}"  # sheet.declarations' wording (sheet.py), regenerated, never edited
MANIFEST = "gct-package.json"
RELABEL = ("To share a document's rows, relabel it: gct doc label ID --privacy shareable --as KEY --capacity TEXT"
           " --rationale TEXT")
EMPTY = "Every document is private, so a sanitised package would hold no documents."
# ponytail: a path is a slash, ~/ or a drive letter after a start, space or quote; a line naming one some other way
# is not counted (the count is shown, nothing is decided by it).
LOCAL_PATH = re.compile(r"""(?:^|[\s"'=(\[,])(?:/|~/|[A-Za-z]:[\\/])\w""")
TEXTS = (
    "Written by gct at {at} as a sanitised package: rows of shareable documents only; private documents and their"
    " derived rows, run log lines, approvals and saved views were not included, and contributors were shown as"
    " pseudonyms with their text withheld unless this file lists them in include. This describes data version 1"
    " (sha256 {sha}) as written; anything added to this folder later is not covered.",
    "Written by gct at {at} as a complete package, including private content authorised at that time; data version 1"
    " has sha256 {sha}.")


def parse_include(text: str | None) -> tuple:
    given = tuple(sorted({c.strip() for c in (text or "").split(",") if c.strip()}))
    if unknown := [c for c in given if c not in INCLUDE]:
        raise GctError(USAGE, f"There is no inclusion class named {unknown[0]!r}.",
                       f"Use any of: {', '.join(INCLUDE)}, for example: --include identity,flags")
    return given


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _public(identity: dict) -> dict:
    """V3's sanitised identity: no history_mark or labels_mark."""
    return {k: identity[k] for k in ("version", "built_at", "sha256", "projection_schema")}


def _refuse_stale(conn, root, version: int) -> None:
    if published.status(conn, root)["stale"]:
        raise GctError(REFUSED, f"Data version {version} is out of date.", published.BUILD_AGAIN)


def _decide(conn, root, mode: str, include: tuple):
    """({table: [shipped rows]}, Counter of withheld rows by cause, {document id: document}, effective labels,
    {stored series key: written series key} for the keys the shipped rows explain)."""
    docs = {d["id"]: d for d in registry.list_documents(conn)}
    eff = labels.effective(conn)
    keys = {t: {f["from"]: f["table"] for f in conn.execute(f"PRAGMA foreign_key_list({t})")} for t in COLUMNS}
    decided, ship, withheld = {}, {}, Counter()
    for t in COLUMNS:
        if t in FROM_INIT + NEVER:
            continue
        ship[t] = []
        for row in conn.execute(f"SELECT * FROM {t} ORDER BY rowid"):
            named = frozenset(labels.named(conn, t, row))
            if (t, named) not in decided:  # one decision per table and documents named, on one snapshot
                decided[t, named] = labels.ships(conn, None, t, named, mode, include)
            if decided[t, named]:
                ship[t].append(row)
            elif cause := _cause(conn, t, named, docs, eff):
                withheld[cause] += 1
    if mode == "sanitised":
        ship.update(dict.fromkeys(COMPLETE_ONLY, []))
        # A decision or restatement names a series by its key, which holds the boundary text and ids its claims and
        # inferences give; it ships only when the shipped rows form that series now, or provably formed it earlier
        formed = _formed(conn, ship) | history_keys(ship)
        for t in SERIES_NAMED:
            kept = [r for r in ship[t] if scrub_key(r["series_key"]) in formed]
            withheld["selection_recomputed"] += len(ship[t]) - len(kept)
            ship[t] = kept
        pointed = {t: set() for t in REFERENCED}
        for t, rows in ship.items():
            for col, target in keys[t].items():
                if target in pointed and t not in REFERENCED + ("run_event",):  # run lines follow their run
                    pointed[target] |= {r[col] for r in rows if r[col] is not None}
        for t in REFERENCED:
            ship[t] = [r for r in ship[t] if r["id"] in pointed[t]]
        ship["run_event"] = [r for r in ship["run_event"] if r["kind"] == "finished" and r["run_id"] in pointed["run"]]
    return ship, withheld, docs, eff


def _formed(conn, ship: dict) -> set:
    """The keys of the series the shipped rows form now: match.compute on an in-memory copy of them (the source's
    tables, no triggers, foreign keys off). Archive is a lifecycle state, so an archived document's claims count here:
    its archived document_state rows are left out of the copy (P3)."""
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    try:
        for (sql,) in conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
            mem.execute(sql)
        for t, rows in ship.items():
            rows = [r for r in rows if t != "document_state" or r["state"] != "archived"]
            if rows:
                cols = rows[0].keys()
                mem.executemany(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                [tuple(r) for r in rows])
        return {s["key"] for s in match.compute(mem)["series"].values()}
    finally:
        mem.close()


def history_keys(ship: dict) -> set:
    """The keys (as match.compute builds them, through redact.scrub_key) of the series the given rows provably formed
    at some moment. The only recorded order across tables: inference_review ids, one sequence over both fields and
    every claim; and a review comes after the start of the run of the inference it names (run ids are global). So the
    reviews are replayed in id order and, at each, a claim version's key counts only when nothing about it is
    ambiguous:
    - it is its claim's newest version (a later version or correction may have come before the moment);
    - it has exactly one metric assignment, and that assignment's run is earlier than the run of an inference some
      review at or before the moment names (so the assignment existed then);
    - each field is known by its newest review so far: resolved gives the review's values, accepted the values of the
      inference it names, if that inference is given and no newer inference of the field exists (a re-proposal ends
      an acceptance at a moment no row records); rejected or anything else leaves it unknown.
    A unit as printed key counts while two claims hold it at once.
    ponytail: everything else is withheld (sanitised) as ambiguous, since nothing orders metric_assignment,
    inference re-proposals, claim_version and correction rows against inference_review rows; runs are taken not to
    overlap; whether a claim was current (its page's reading and extraction) at the moment is not checked. A shared
    sequence column would close it (post-M1)."""
    claims = {c["id"]: c for c in ship["claim"]}
    versions = {v["id"]: v for v in ship["claim_version"] if v["claim_id"] in claims}
    newest_version = {}
    for v in versions.values():
        newest_version[v["claim_id"]] = max(newest_version.get(v["claim_id"], 0), v["id"])
    count = Counter(a["claim_version_id"] for a in ship["metric_assignment"])
    single = {a["claim_version_id"]: a for a in ship["metric_assignment"] if count[a["claim_version_id"]] == 1}
    inferences = {i["id"]: i for i in ship["inference"]}
    newest_inference = {}
    for i in inferences.values():
        k = i["claim_version_id"], i["field"]
        newest_inference[k] = max(newest_inference.get(k, 0), i["id"])
    current = _current_from(ship, claims, versions)
    state, held, holders, out, elapsed = {}, {}, Counter(), set(), 0

    def update(vid):
        v, a, s = versions[vid], single.get(vid), state[vid]
        ordinary = printed = None
        if newest_version[v["claim_id"]] == vid and a is not None and a["run_id"] < elapsed and vid in current and \
                current[vid] <= elapsed:
            ordinary, printed = _key(claims[v["claim_id"]], v, a, s.get("boundary"), s.get("period"))
        if ordinary:
            out.add(ordinary)
        holders[held.pop(vid, None)] -= 1
        if printed:
            held[vid] = printed
            holders[printed] += 1
            if holders[printed] > 1:
                out.add(printed)

    for r in ship["inference_review"]:  # in id order
        if r["claim_version_id"] not in versions:
            continue
        inf = inferences.get(r["inference_id"])
        later = inf is not None and inf["run_id"] > elapsed
        elapsed = max(elapsed, inf["run_id"]) if inf else elapsed
        if r["decision"] == "resolved":
            given = r
        elif r["decision"] == "accepted" and inf and newest_inference[inf["claim_version_id"], r["field"]] == inf["id"]:
            given = inf
        else:
            given = None
        state.setdefault(r["claim_version_id"], {})[r["field"]] = given and (
            (given["boundary"], given["boundary_detail"]) if r["field"] == "boundary" else given["period_kind"])
        for vid in (list(state) if later else [r["claim_version_id"]]):  # a later run can prove an assignment
            update(vid)
    return out


def _current_from(ship: dict, claims: dict, versions: dict) -> dict:
    """{claim version id: the run after which the version was provably current (correct.states), and stayed so}.
    The claim's page reading that is newest now is the newest at any moment, since page rows are append-only; the
    version was current at a moment once that reading had an ok extract attempt and a claim_seen row of the version,
    both under the current extract config, in runs that ended before it. A version of a spreadsheet document, or with
    no such rows, is never proven current."""
    from gct.stages import extract
    config, pdf = extract.extract_config(), {d["id"] for d in ship["document"] if d["file_type"] == "pdf"}
    newest = {}
    for p in ship["page"]:
        k = p["document_id"], p["page_number"]
        newest[k] = max(newest.get(k, 0), p["id"])
    extracted = {}
    for t in ship["attempt"]:
        if t["stage"] == "extract" and t["outcome"] == "ok" and t["config_version"] == config:
            k = t["item"].split(":", 1)[0], t["input_version"]
            extracted[k] = min(extracted.get(k, t["run_id"]), t["run_id"])
    seen = {}
    for s in ship["claim_seen"]:
        if s["config_version"] == config:
            k = s["claim_version_id"], s["page_id"]
            seen[k] = min(seen.get(k, s["run_id"]), s["run_id"])
    out = {}
    for vid, v in versions.items():
        c = claims[v["claim_id"]]
        page = newest.get((c["document_id"], c["page_number"]))
        runs_ = (extracted.get((str(c["document_id"]), f"page {page}")), seen.get((vid, page)))
        if c["document_id"] in pdf and page and None not in runs_:
            out[vid] = max(runs_)
    return out


def _key(c, v, a, boundary, kind) -> tuple:
    """(ordinary key, unit as printed key) of one claim version in one state, as JSON (match.compute, match._series),
    from claim text through redact.scrub_key, as match.compute builds it."""
    if a is None or kind is None or boundary is None or boundary[0] in (None, "unknown"):
        return None, None
    row, doc = match._row(c["locator"]), c["document_id"]
    label = match.key_label(v["metric_text"])
    if a["metric_key"] is None and not (label and row):
        return None, None
    head = [c["company_id"], a["metric_key"] or f"doc:{doc}:p{c['page_number']}:{row}:{label}", boundary[0],
            scrub_key(boundary[1]) if boundary[0] == "subsidiary_set" else None]
    family = a["unit_key"]
    if family is not None and (a["metric_key"] is None or family in match.ACCEPTS[a["metric_key"]]):
        return json.dumps(head + [family, doc if a["metric_key"] is None else None, kind], ensure_ascii=False), None
    unit = match.key_unit(v["unit_text"]) or "-"
    return None, row and json.dumps(head + [f"printed:{unit}", doc, kind, f"p{c['page_number']}:{row}"],
                                    ensure_ascii=False)


def _cause(conn, table: str, named, docs: dict, eff: dict) -> str | None:
    """The first C6 cause that applies to a withheld row; None for a fetch attempt (it names no document)."""
    if table == "document":
        (d,) = named
        return _doc_cause(conn, docs[d])[0]
    if any(eff.get(d, {"label": "private"})["label"] != "shareable" for d in named):
        return "names_private_document"
    return "flag" if table == "reviewer_flag" else None


def _doc_cause(conn, doc: dict) -> tuple[str, str]:
    """(cause, words) for a withheld document."""
    if doc["privacy"] == "private":
        return "private_document", "private label"
    if twin := labels.twins(conn, doc["sha256"], doc["privacy"], doc["id"]):
        return "same_bytes_private", f"same file as private document {twin[0]['id']}"
    return "deleted", "deleted"


def _pseudonyms(ship: dict) -> dict:
    """{contributor_key: "Contributor N"} over the shipped attributed records (labels.pseudonyms, C7)."""
    key = {r["id"]: r["contributor_key"] for r in ship["contributor_version"]}
    return labels.pseudonyms([(t, r["id"], key[r["contributor_version_id"]]) for t, rows in ship.items()
                              if rows and "contributor_version_id" in rows[0].keys() and t != "saved_view"
                              for r in rows if r["contributor_version_id"] is not None])


def _plan(conn, root, mode: str, include: tuple):
    """D5's preview and what the writer needs. Refuses (D8 order) what pin refuses, then a stale version."""
    root = Path(root)
    pconn, source = pinning.pin(conn, root)
    pconn.close()
    _refuse_stale(conn, root, source["version"])
    ship, withheld, docs, eff = _decide(conn, root, mode, include)
    shipped = [d["id"] for d in ship["document"]]
    originals = {}
    for d in ship["document"]:
        if docs[d["id"]]["state"] != "deleted":
            originals[d["sha256"]] = d["size_bytes"]
    readings = sorted({a["path"] for a in ship["artifact"] if (root / a["path"]).is_file()})
    included = {"documents": [{"id": d["id"], "sha256": d["sha256"], "label": eff[d["id"]]["label"]}
                              for d in ship["document"]],
                "tables": {t: len(rows) for t, rows in ship.items()},
                "files": {"originals": [{"sha256": s, "bytes": originals[s]} for s in sorted(originals)],
                          "readings": len(readings)}}
    names = _pseudonyms(ship)
    if mode == "sanitised":
        if "contributor_text" not in include:
            withheld["contributor_text"] = sum(
                any(r[c] is not None for c, cls in COLUMNS[t].items() if cls == TEXT)
                for t, rows in ship.items() for r in rows)
        if "identity" not in include:
            withheld["identity"] = len(ship["contributor_version"])
    total = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("run_event", "approval", "saved_view")}
    pages = root / "artifacts" / "pages"
    out = {
        "data_version": source, "mode": mode, "include": list(include), "included": included,
        "withheld": {c: withheld[c] for c in CAUSES},
        "history_mark": source["history_mark"], "labels_mark": source["labels_mark"], "filter": {},
        "not_in_packages": {"run_log_lines": total["run_event"] - len(ship["run_event"]),
                            "approvals": total["approval"], "saved_views": total["saved_view"] - len(ship["saved_view"]),
                            "page_images": sum(p.is_file() for p in pages.rglob("*")) if pages.is_dir() else 0},
    }
    out["token"] = hashlib.sha256(json.dumps({"sha256": source["sha256"], "mode": mode, "include": sorted(include),
                                              "included": included}, sort_keys=True).encode()).hexdigest()[:12]
    paths = sum(bool(LOCAL_PATH.search(r["item"] or "") or LOCAL_PATH.search(r["message"] or ""))
                for r in ship["run_event"])
    out["lines"] = _lines(conn, out, docs, shipped, names, paths)
    files = ["workspace.db", "published/v1.db", MANIFEST, *readings,
             *(registry.stored_path(Path(), s).as_posix() for s in sorted(originals))]
    withheld_files = {d["sha256"] for d in docs.values() if d["id"] not in shipped and d["state"] != "deleted"}
    return out, {"ship": ship, "names": names, "eff": eff, "files": files, "withheld_files": withheld_files,
                 "private": [i for i in shipped if eff[i]["label"] == "private" and docs[i]["state"] != "deleted"]}


def plan(conn, root, mode: str = "sanitised", include: tuple = ()) -> dict:
    """The inclusion preview (FR70). Writes nothing; the caller holds the workspace lock (pin)."""
    return _plan(conn, root, mode, include)[0]


def _create_line(p: dict) -> str:
    flags = " --complete --include-private" if p["mode"] == "complete" else ""
    inc = f" --include {','.join(p['include'])}" if p["include"] else ""
    return f"Create it with: gct package create{flags}{inc} --confirm {p['token']}"


def _lines(conn, p: dict, docs: dict, shipped: list, names: dict, paths: int) -> list[str]:
    v = p["data_version"]
    head = f"Package preview ({p['mode']}) of data version {v['version']}, built {v['built_at']}."

    def doc(d, words):
        return f"  {d['id']}  {d['company']}  {d['logical_name']}  {words}"

    held = [doc(docs[i], _doc_cause(conn, docs[i])[1]) for i in docs if i not in shipped]
    if p["mode"] == "sanitised" and not shipped:
        return [head, EMPTY, *held, RELABEL]
    lines = [head, "Included documents:", *(doc(docs[d["id"]], d["label"]) for d in p["included"]["documents"])]
    if held:
        lines += ["Withheld documents:", *held]
    tables = p["included"]["tables"]
    lines.append("Rows: " + ", ".join(f"{t.replace('_', ' ')} {n}" for t, n in tables.items() if n) + ".")
    files = p["included"]["files"]
    lines.append(f"Files: {len(files['originals'])} originals ({sum(f['bytes'] for f in files['originals'])} bytes)"
                 f" and {files['readings']} readings.")
    gone = p["not_in_packages"]
    if p["mode"] == "complete":
        private = [str(d["id"]) for d in p["included"]["documents"]
                   if d["label"] == "private" and docs[d["id"]]["state"] != "deleted"]
        lines.append(f"It carries {len(private)} private documents: {', '.join(private)}." if private
                     else "It carries no private documents.")
        lines.append(f"It also carries contributor names and text, reviewer flags, {tables['saved_view']} saved views"
                     f" and {paths} run log lines that name local paths.")
        lines.append(f"Not in the package: {gone['approvals']} approvals, {gone['page_images']} page images.")
        return [*lines, _create_line(p)]
    inc = p["include"]
    k = len(names)
    lines.append("Contributor names, organisations and keys are kept as recorded." if "identity" in inc else
                 f"{k} contributors shown as Contributor 1 to Contributor {k}; include identity to keep names." if k
                 else "No contributor is named in the package.")
    lines.append("Contributor text is kept as recorded." if "contributor_text" in inc else
                 "Contributor text is withheld; include contributor_text to keep it.")
    lines.append("Reviewer flags are kept as recorded." if "flags" in inc else
                 "Reviewer flags are withheld; include flags to keep them.")
    lines.append(f"Not in the package: {gone['run_log_lines']} run log lines (each run keeps its outcome),"
                 f" {gone['approvals']} approvals, {gone['saved_views']} saved views, {gone['page_images']} page images.")
    return [*lines, _create_line(p)]


def _failed(cause: str) -> GctError:
    return GctError(REFUSED, f"The package did not verify: {cause}.",
                    "Run the command again; if it fails again, check the disk and the workspace with gct workspace status.")


def _row(table: str, row, mode: str, include: tuple, ctx: dict) -> tuple:
    out = []
    for col in row.keys():
        v = row[col]
        v = (scrub_key if (table, col) in KEY_TEXT else scrub)(v) if isinstance(v, str) else v
        cls = COLUMNS[table][col]
        if mode == "sanitised":
            if cls == TEXT and "contributor_text" not in include:
                v = None if v is None else MARKER
            elif cls == LOCAL:
                public = table == "document" and col == "source" and ctx["eff"][row["id"]]["availability"] == "public"
                v = v if public and isinstance(v, str) and v.lower().startswith(("http://", "https://")) else None
            elif cls == IDENTITY and "identity" not in include:
                name = ctx["names"][row["contributor_key"]]
                v = {"name": name, "contributor_key": "contributor-" + name.rsplit(" ", 1)[1]}.get(col)
            elif table == "basis" and col == "wording" and "identity" not in include:
                v = _declared(row, v, ctx)
        out.append(v)
    return tuple(out)


def _declared(row, wording, ctx):
    """A spreadsheet's basis wording names the mapping's contributor (sheet.declarations): regenerated with the
    pseudonym when it is exactly that wording for one of the document's shipped mappings, else the marker (fail
    closed)."""
    if ctx["file_types"][row["document_id"]] not in sheet.TYPES:
        return wording
    for m in ctx["ship"]["sheet_mapping"]:
        who = ctx["who"][m["contributor_version_id"]]
        if m["document_id"] == row["document_id"] and wording == scrub(DECLARED.format(m["id"], who["name"])):
            return DECLARED.format(m["id"], ctx["names"][who["contributor_key"]])
    return MARKER


def _write(root: Path, folder: Path, p: dict, w: dict) -> dict:
    """Write the package into folder (empty), check it against the plan and write the manifest."""
    mode, include, ship = p["mode"], tuple(p["include"]), w["ship"]
    layout.init_workspace(folder)
    ctx = {"eff": w["eff"], "names": w["names"], "ship": ship, "who": {r["id"]: r for r in ship["contributor_version"]},
           "file_types": {d["id"]: d["file_type"] for d in ship["document"]}}
    pk = store.connect(folder / layout.DB_NAME)
    try:
        pk.execute("PRAGMA foreign_keys = OFF")  # outside a transaction, or it is ignored
        with store.transaction(pk):
            for t, rows in ship.items():
                if rows:
                    cols = rows[0].keys()
                    pk.executemany(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                   [_row(t, r, mode, include, ctx) for r in rows])
        if pk.execute("PRAGMA foreign_key_check").fetchall():
            raise _failed("a row points at a row that was left out")
        pk.execute("PRAGMA foreign_keys = ON")
        for path in w["files"]:
            src = root / path
            if path.startswith(("files/", "artifacts/")):
                (folder / path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, folder / path)
        if registry.verify(pk, folder):
            raise _failed("an original file does not match its document")
        published.build(pk, folder)
        pconn, own = pinning.pin(pk, folder)
        pconn.close()
        if {t: pk.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ship} != p["included"]["tables"]:
            raise _failed("the rows written differ from the preview")
        if [list(r) for r in pk.execute("SELECT id, sha256 FROM document ORDER BY id")] != [
                [d["id"], d["sha256"]] for d in p["included"]["documents"]]:
            raise _failed("the documents written differ from the preview")
        pk.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        pk.close()
    held = {f.relative_to(folder).as_posix() for f in folder.rglob("*") if f.is_file()}
    if held != set(w["files"]) - {MANIFEST}:
        raise _failed("the files written differ from the preview")
    if mode == "sanitised" and any(f.name in w["withheld_files"] for f in (folder / "files").rglob("*")):
        raise _failed("a withheld document's file is in the package")
    own = _public(own) if mode == "sanitised" else own
    source = _public(p["data_version"]) if mode == "sanitised" else p["data_version"]
    at = store.now()
    manifest = {"package_schema": 1, "mode": mode, "include": list(include), "created_at": at,
                "gct_version": __version__, "data_version": own, "source_data_version": source,
                "text": TEXTS[mode == "complete"].format(at=at, sha=own["sha256"])}
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def create(conn, root, mode: str, include: tuple, token: str, include_private: bool = False) -> dict:
    """gct package create. The caller holds the workspace lock. Refusals write nothing and open no run."""
    root = Path(root)
    if mode == "complete" and not include_private:
        private = [i for i, v in labels.effective(conn).items()
                   if v["label"] == "private" and registry.show_document(conn, i)["state"] != "deleted"]
        what = f"private content: {len(private)} private documents, contributor" if private else "contributor"
        raise GctError(REFUSED, f"A complete package includes {what} names and text, and run log lines that name local"
                                " paths.",
                       f"If you mean to include them: gct package create --complete --include-private --confirm {token}")
    if include_private and mode != "complete":
        raise GctError(USAGE, "--include-private applies only with --complete.",
                       "Add --complete, or leave out --include-private.")
    # One snapshot: the plan and the copy read the same rows, and the create run below is not in it.
    snap = sqlite3.connect(f"{(root / layout.DB_NAME).resolve().as_uri()}?mode=ro", uri=True, isolation_level=None)
    snap.row_factory = sqlite3.Row
    try:
        snap.execute("BEGIN")
        snap.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        p, w = _plan(snap, root, mode, include)
        if token != p["token"]:
            raise GctError(REFUSED, "What the package would hold has changed since that preview, or the preview was for"
                                    " another mode or inclusion.", "Preview it again with: gct package preview"
                                    + (" --complete" if mode == "complete" else "")
                                    + (f" --include {','.join(include)}" if include else ""))
        if mode == "sanitised" and not p["included"]["documents"]:
            raise GctError(REFUSED, EMPTY, RELABEL)
        stem = f"package-v{p['data_version']['version']}-{_stamp()}-{mode}"
        if (root / "exports" / stem).exists():
            raise GctError(REFUSED, f"A package named {stem} already exists; nothing was overwritten.",
                           "Run the command again.")
        folder = f"exports/{stem}"
        with runs.run(conn, "package create") as run_id:
            notes = [f"private content authorised: documents {', '.join(map(str, w['private']))}" if w["private"]
                     else "private content authorised: no private documents"] if mode == "complete" else []
            runs.record(conn, run_id, {"mode": mode, "include": list(include), "token": token, "folder": folder}, notes)
            with _folder(root, stem, w["files"]) as tmp:
                manifest = _write(root, tmp, p, w)
            runs.event(conn, run_id, "output", stage="package", item=folder)
    finally:
        snap.close()
    v, own = p["data_version"], manifest["data_version"]
    kind = "a sanitised package" if mode == "sanitised" else "a complete package, including private content,"
    return {"folder": folder, "mode": mode, "include": list(include), "token": token, "run_id": run_id,
            "source_data_version": manifest["source_data_version"], "data_version": own,
            "lines": [f"Wrote {kind} to {folder} from data version {v['version']} (built {v['built_at']}).",
                      f"The package holds its own data version 1 (built {own['built_at']}).", deletion.WARNING]}
