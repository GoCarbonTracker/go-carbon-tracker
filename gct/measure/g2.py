"""G2 measurement: score the current published version of a workspace against a frozen gold folder (story 3.6).

The rules are frozen as SCORER_VERSION; any change to them bumps the version and re-scores the previous baseline.
Claims come only from the published version. The working database is opened read-only for the page readings
(rung and method) and the run log costs, which the projection does not carry.
"""
import hashlib
import html
import json
import math
import random
import re
import secrets
import sqlite3
import subprocess
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import gct
from gct.workspace import layout, published
from gct.workspace.layout import NOT_FOUND, REFUSED, GctError

SCORER_VERSION = "2"
KINDS = ("text", "table", "figure")
GOLD_FILES = {"text": "text.jsonl", "table": "tables.jsonl", "figure": "figures.jsonl"}
TARGET = 0.9
FIELDS = ("metric", "entity", "boundary", "period")
CURRENCY = {"inr", "usd", "gbp", "eur"}
# Gold units with any of these words are units of measure (currency and scale, %, mass, emissions, energy, power,
# volume, distance, time); any other gold unit is a count noun ("employees", "vehicles", "meetings").
MEASURE_WORDS = CURRENCY | {
    "crore", "cr", "lakh", "lakhs", "million", "mn", "billion", "bn", "thousand", "k",
    "t", "tonne", "tonnes", "kg", "kt", "mt", "tco2e", "tco2", "co2e",
    "wh", "kwh", "mwh", "gwh", "gj", "tj", "mj", "kw", "mw", "gw",
    "m3", "kl", "ml", "l", "litre", "litres", "liter", "liters",
    "m", "km", "year", "years", "month", "months", "week", "weeks", "day", "days", "hour", "hours", "minutes",
}

# normalize and number_tokens: copied verbatim from services/hypergraph-rag/scripts/core/score_ground_truth.py 1.1.0.
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# The 15 Rung-1 extractor units (from gct.stages.extract.UNITS)
EXTRACTOR_UNITS = {
    "tco2e", "tco2", "tonnes", "t", "kt", "mt", "mwh", "gwh", "kwh",
    "gj", "tj", "kl", "ml", "m3", "%", "million tonnes co2e", "ktco2e"
}

RECOGNISED_ORIGINS = {"machine-inferred", "accepted", "resolved"}
REVIEWED_ORIGINS = {"accepted", "resolved"}
UNRESOLVED_STATES = {"unresolved", "proposed", "unknown", "rejected"}


def classify_state(state: str | None) -> tuple[str, str | None]:
    """Classify state into (origin_kind, unrecognised_name).
    origin_kind is one of: 'machine-inferred', 'reviewed', 'unresolved'.
    """
    if state == "machine-inferred":
        return "machine-inferred", None
    if state in REVIEWED_ORIGINS:
        return "reviewed", None
    if state in UNRESOLVED_STATES or state is None:
        return "unresolved", None
    return "unresolved", str(state)


def is_string_answer(expected: str) -> bool:
    """True when expected answer has letters/words, meaning it's a string/word answer, not a pure numeric figure."""
    return bool(re.search(r"[a-zA-Z]", str(expected)))


def normalize(text: str) -> str:
    """Lowercase, NFKC, HTML-entity decode, keep [a-z0-9%.] word chars."""
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^a-z0-9%.]+", " ", text)
    # detach sentence-final periods so they don't glue words to numbers,
    # while keeping decimal points inside number tokens intact
    text = re.sub(r"\.(?!\d)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def number_tokens(text: str) -> set[str]:
    """Number tokens with thousand separators stripped, decimals preserved."""
    return {m.group(0).replace(",", "") for m in _NUMBER_RE.finditer(text)}


def unit_key(unit: str) -> str:
    """normalize plus the listed table: ₹, rs, inr to inr; tco2e, tco2 e, tonnes co2e to tco2e; m³ to m3; percent to %."""
    words = ["inr" if w == "rs" else "%" if w == "percent" else w for w in normalize(unit.replace("₹", " inr ")).split()]
    return re.sub(r"\b(?:t co2e|tco2 e|tonnes co2e)\b", "tco2e", " ".join(words))


def is_measure(unit: str) -> bool:
    key = unit_key(unit)
    return "%" in key or bool(set(key.split()) & MEASURE_WORDS)


def value_match(value_text: str, expected: str) -> bool:
    expected_str = str(expected)
    if is_string_answer(expected_str):
        # S-4: whole normalised string matching for word or string answers.
        # Digit-bearing strings are never compared by numeric equality.
        norm_expected = normalize(expected_str)
        return bool(norm_expected) and normalize(value_text) == norm_expected
    gold = number_tokens(expected_str)
    if not gold:
        word = normalize(expected_str)
        return bool(word) and normalize(value_text) == word
    return number_tokens(value_text) == gold


def unit_match(claim_unit: str | None, gold_unit: str | None, metric_text: str | None = None) -> bool:
    if gold_unit is None:
        return claim_unit is None
    if claim_unit is None:
        return not is_measure(gold_unit)
    # S-2: gold unit "% of <group>" matches claim unit "%" only when the group
    # words appear as a whole phrase, in order, in the claim's metric text.
    gold_norm = normalize(gold_unit)
    if gold_norm.startswith("% of "):
        group = gold_norm[5:].strip()  # everything after "% of "
        if unit_key(claim_unit) != "%":
            return False
        if not group or metric_text is None:
            return False
        metric_norm = f" {normalize(metric_text)} "
        return f" {group} " in metric_norm
    return unit_key(claim_unit) == unit_key(gold_unit)


def metric_match(metric_text: str | None, row: dict) -> bool:
    if metric_text is None:
        return False
    text = f" {normalize(metric_text)} "
    names = [normalize(n) for n in [row["metric"], *(row.get("aliases") or [])] if n]
    return any(n and f" {n} " in text for n in names)


def iou(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    inter = max(w, 0) * max(h, 0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head(folder: Path) -> str:
    """HEAD of the checkout holding folder, with -dirty when a tracked file differs from it."""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=folder, capture_output=True, text=True, timeout=10)
        if r.returncode != 0 or not r.stdout.strip():
            return "unknown"
        st = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=folder, capture_output=True,
                            text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return r.stdout.strip() + ("-dirty" if st.returncode != 0 or st.stdout.strip() else "")


def load_gold(folder: Path) -> tuple[dict, dict, list[dict]]:
    """(manifest, documents by file name, rows) after checking every scored file against MANIFEST.json."""
    folder = Path(folder).expanduser()
    names = ["documents.json", *GOLD_FILES.values()]
    for name in ["MANIFEST.json", *names]:
        if not (folder / name).is_file():
            raise GctError(NOT_FOUND, f"The gold folder {folder} has no {name}.",
                           "Point --gold at a folder with MANIFEST.json, documents.json, text.jsonl, tables.jsonl"
                           " and figures.jsonl.")
    manifest = json.loads((folder / "MANIFEST.json").read_text(encoding="utf-8"))
    listed = manifest.get("sha256", {})
    for name in dict.fromkeys([*names, *listed]):
        if not (folder / name).is_file() or listed.get(name) != _sha256(folder / name):
            raise GctError(REFUSED, f"The gold file {name} differs from its sha256 in MANIFEST.json.",
                           "A changed gold file is a new gold version: freeze it with a new MANIFEST.json first.")
    docs = {d["doc"]: d for d in json.loads((folder / "documents.json").read_text(encoding="utf-8"))["documents"]}
    rows = []
    for kind, name in GOLD_FILES.items():
        for line in (folder / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append({**json.loads(line), "kind": kind})
    for r in rows:
        if r["doc"] not in docs:
            raise GctError(REFUSED, f"Gold row {r['id']} cites {r['doc']}, which documents.json does not list.",
                           "Fix the gold folder (a new gold version).")
    return manifest, docs, rows


def document_type(doc: dict, page: int) -> str:
    """The gold document's type; a page inside its brsr_section reports as BRSR."""
    s = doc.get("brsr_section")
    return "BRSR" if s and s["start_pdf_page"] <= page <= s["end_pdf_page"] else doc["document_type"]


def ceiling(row: dict) -> list[str]:
    """Why a row cannot be Found under rule 1 whatever the reading does (empty when it can)."""
    out = []
    if row["boundary"] == "segment":
        out.append("gold boundary segment")
    if row["unit"] and set(unit_key(row["unit"]).split()) & CURRENCY:
        out.append("gold currency unit")
    if not number_tokens(str(row["expected_answer"])):
        out.append("gold value is not a figure")
    # S-6: Two new named ceiling reasons:
    # 1. "unit not in the extractor's vocabulary"
    if row.get("unit") and is_measure(row["unit"]):
        uk = unit_key(row["unit"])
        if not (set(uk.split()) & CURRENCY) and uk not in EXTRACTOR_UNITS:
            out.append("unit not in the extractor's vocabulary")
    # 2. "string answer"
    if number_tokens(str(row["expected_answer"])) and is_string_answer(str(row["expected_answer"])):
        out.append("string answer")
    return out


def _evidence_box(refs: list[dict], page: int):
    """The smallest box enclosing the stored boxes of the refs on the page, or None."""
    boxes = [b for r in refs if r["page_number"] == page and r["boxes"] for b in json.loads(r["boxes"])]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _judge(c: dict, row: dict, company: str, refs: list[dict]) -> dict:
    value = value_match(c["value_text"], str(row["expected_answer"]))
    unit = unit_match(c["unit_text"], row["unit"], c.get("metric_text"))
    p = row["period"] or {}

    # S-5: origin classification
    period_origin, unrec_p = (
        classify_state(c["period_state"]) if "period_state" in c else ("machine-inferred", None)
    )
    boundary_origin, unrec_b = (
        classify_state(c["boundary_state"]) if "boundary_state" in c else ("machine-inferred", None)
    )

    # S-1: segment is an accepted gold boundary when the claim carries a printed segment name.
    boundary_ok = False
    if row["boundary"] == "unstated":
        boundary_ok = True
    elif row["boundary"] in ("standalone", "consolidated"):
        boundary_ok = (c["reporting_boundary"] == row["boundary"]
                       and boundary_origin in ("machine-inferred", "reviewed"))
    elif row["boundary"] == "segment":
        boundary_ok = (c["reporting_boundary"] == "segment"
                       and bool(c.get("boundary_detail"))
                       and boundary_origin in ("machine-inferred", "reviewed"))

    period_ok = (period_origin in ("machine-inferred", "reviewed")
                 and c["period_start"] is not None and c["period_end"] is not None
                 and (c["period_start"], c["period_end"]) == (p.get("start"), p.get("end")))

    ok = {
        "metric": metric_match(c["metric_text"], row),
        "entity": c["company"] == company,
        "boundary": boundary_ok,
        "period": period_ok,
    }
    failing = [f for f in FIELDS if not ok[f]]
    verdict = "Missed" if not (value and unit) else "Partial" if failing else "Found"
    box = _evidence_box(refs, row["page"])
    overlap = iou(box, row["bbox"]) if box and row.get("bbox") else 0.0

    # S-5: record origin of dependent fields for Found rows.
    # Dependent fields: period is always dependent; boundary is dependent when gold states one.
    row_origin = None
    if verdict == "Found":
        dependent_origins = [period_origin]
        if row["boundary"] != "unstated":
            dependent_origins.append(boundary_origin)
        if all(o == "machine-inferred" for o in dependent_origins):
            row_origin = "machine-inferred"
        elif any(o == "reviewed" for o in dependent_origins):
            row_origin = "review-assisted"
        else:
            row_origin = "unresolved"

    return {
        "claim": c, "verdict": verdict, "failing": failing if verdict == "Partial" else [],
        "value": value, "iou": overlap,
        "period_origin": period_origin, "boundary_origin": boundary_origin,
        "origin": row_origin,
        "unrecognised_states": [s for s in (unrec_p, unrec_b) if s is not None],
    }


RANK = {"Found": 0, "Partial": 1, "Missed": 2}


def score_row(row: dict, doc: dict, ws_doc: dict, claims: list[dict], refs: dict) -> dict:
    company = doc["company"]
    on_page = [c for c in claims if c["document_id"] == ws_doc["id"] and c["page_number"] == row["page"]]
    judged = [_judge(c, row, company, refs.get(c["claim_version_id"], [])) for c in on_page]
    best = min(judged, key=lambda j: (RANK[j["verdict"]], len(j["failing"]), -j["iou"], j["claim"]["id"]), default=None)
    verdict = best["verdict"] if best else "Missed"
    reason = None
    if verdict == "Missed":
        reason = ("gold value is not a figure" if not number_tokens(str(row["expected_answer"]))
                  else "page has no current claim" if not on_page
                  else "value matches, unit does not" if any(j["value"] for j in judged) else "no value match on the page")
    chosen = best if verdict != "Missed" else None
    elsewhere = None
    if verdict != "Found":
        elsewhere = any(c["document_id"] == ws_doc["id"] and c["page_number"] != row["page"]
                        and value_match(c["value_text"], str(row["expected_answer"])) for c in claims)
    c = chosen and chosen["claim"]
    return {
        "id": row["id"], "kind": row["kind"], "company": company, "doc": row["doc"],
        "document_type": document_type(doc, row["page"]), "page": row["page"], "verdict": verdict,
        "failing": chosen["failing"] if chosen else [], "reason": reason,
        "claim": c and c["id"], "value_text": c and c["value_text"], "unit_text": c and c["unit_text"],
        "metric_text": c and c["metric_text"], "iou": chosen and round(chosen["iou"], 4),
        "evidence_found": bool(chosen) and chosen["iou"] >= 0.5,
        "value_elsewhere_in_document": elsewhere, "ceiling": ceiling(row),
        "period_origin": chosen and chosen.get("period_origin"),
        "boundary_origin": chosen and chosen.get("boundary_origin"),
        "origin": chosen and chosen.get("origin"),
        "boundary_detail": c and c.get("boundary_detail"),
    }


def _pct(k: int, n: int) -> str:
    return f"{k}/{n} ({100 * k / n:.1f}%)" if n else f"{k}/0"


def summarise(rows: list[dict], review_assisted: bool = False) -> dict:
    """Counts with every percentage beside its count. Found never includes Partial."""
    n = len(rows)
    v = Counter(r["verdict"] for r in rows)
    found_total = v["Found"]
    partial = v["Partial"]
    found_auto = sum(1 for r in rows if r["verdict"] == "Found" and r.get("origin") == "machine-inferred")
    found_reviewed = sum(1 for r in rows if r["verdict"] == "Found" and r.get("origin") == "review-assisted")

    # Gate calculation: in automatic runs, gate counts only all-machine-inferred Found;
    # in review-assisted runs, it counts all Found rows.
    gate_found = found_total if review_assisted else found_auto
    share = gate_found / n if n else None
    verdict = ("UNMEASURED" if not n else "fail" if share < TARGET
               else "at or above 90% before adjudication")
    stuck = [r for r in rows if r["ceiling"]]
    return {
        "n": n, "found": found_total, "partial": partial, "missed": v["Missed"], "found_text": _pct(found_total, n),
        "verdict": verdict, "re_adjudicate": share is not None and share > 0.95,
        "found_automatic": found_auto, "found_automatic_text": _pct(found_auto, n),
        "found_review_assisted": found_reviewed, "found_review_assisted_text": _pct(found_reviewed, n),
        "found_total": found_total,
        "evidence_found_among_found": _pct(sum(r["evidence_found"] for r in rows if r["verdict"] == "Found"), found_total),
        "evidence_found_among_partial": _pct(sum(r["evidence_found"] for r in rows if r["verdict"] == "Partial"), partial),
        "value_and_unit_on_gold_page": _pct(found_total + partial, n),
        "partial_failing": dict(Counter(f for r in rows if r["verdict"] == "Partial" for f in r["failing"])),
        "missed_reasons": dict(Counter(r["reason"] for r in rows if r["verdict"] == "Missed")),
        "value_elsewhere_in_document": sum(bool(r["value_elsewhere_in_document"]) for r in rows),
        "ceiling": {"rows": len(stuck), "of": n,
                    "reasons": dict(Counter(x for r in stuck for x in r["ceiling"]))},
    }


def _sample(rows: list[dict], companies: list[str], seed: int) -> list[dict]:
    """10% of Found per company and type, at least 10 (all when fewer), drawn over sorted gold ids."""
    rng, out = random.Random(seed), []
    for company in companies:
        for kind in KINDS:
            ids = sorted(r["id"] for r in rows if r["company"] == company and r["kind"] == kind and r["verdict"] == "Found")
            k = min(len(ids), max(10, math.ceil(0.1 * len(ids))))
            out.append({"company": company, "kind": kind, "found": len(ids), "ids": sorted(rng.sample(ids, k))})
    return out


def _method_mix(work: sqlite3.Connection, doc_id: int) -> list[dict]:
    rows = work.execute(
        "SELECT p.rung, p.method, COUNT(*) FROM page p WHERE p.document_id = ? AND p.id = (SELECT MAX(id) FROM page q"
        " WHERE q.document_id = p.document_id AND q.page_number = p.page_number) GROUP BY p.rung, p.method"
        " ORDER BY p.rung, p.method", (doc_id,)).fetchall()
    return [{"rung": r[0], "method": r[1], "pages": r[2]} for r in rows]


def _cost(work: sqlite3.Connection, doc_id: int) -> dict:
    est, conf, events = work.execute(
        "SELECT SUM(cost_estimated), SUM(cost_confirmed), COUNT(*) FROM run_event WHERE kind = 'cost'"
        " AND (item = ? OR item LIKE ?)", (str(doc_id), f"{doc_id}:%")).fetchone()
    reason = None if events else "no cost event in the run log for this document (no step called a model)"
    return {"estimated": est, "confirmed": conf, "reason": reason}


def _previous(path: str | None, manifest: dict) -> dict | None:
    if path is None:
        return None
    p = Path(path).expanduser()
    if not p.is_file():
        raise GctError(NOT_FOUND, f"There is no report at {p}.", "Give the JSON report of the previous run.")
    prev = json.loads(p.read_text(encoding="utf-8"))
    if prev["gold"]["sha256"] != manifest.get("sha256", {}):
        raise GctError(REFUSED, "The previous report scored a different gold version, so there is no delta.",
                       "A new gold version is a new baseline: score without --against.")
    return {**prev, "path": str(p)}


def delta(prev: dict, identity: dict, types: list[dict]) -> dict:
    """The change from a previous report, attributed to the scorer (same published version, new scorer version) or to
    the extraction (same scorer version, new published version), never to both at once. Versions are the same only
    when their identity (workspace, built_at, history_mark, sha256 of the file) is; a version number alone is not."""
    same_scorer, same_version = prev["scorer_version"] == SCORER_VERSION, prev.get("published") == identity
    if not same_scorer and not same_version:
        raise GctError(REFUSED, f"The previous report used scorer version {prev['scorer_version']} on published version"
                                f" {prev['published_version']}; both changed, so the delta cannot be attributed.",
                       f"First re-score published version {prev['published_version']} with scorer version "
                       f"{SCORER_VERSION} (gct publish restore makes it current), then compare against that report.")
    before = {(t["company"], t["kind"]): t for t in prev["types"]}
    return {
        "attributed_to": "extraction" if same_scorer else "scorer",
        "previous": {"report": prev["path"], "run_id": prev["run_id"], "published_version": prev["published_version"],
                     "scorer_version": prev["scorer_version"]},
        "types": [{"company": t["company"], "kind": t["kind"], "before": before[k]["found_text"],
                   "after": t["found_text"], "found_change": t["found"] - before[k]["found"],
                   "partial_change": t["partial"] - before[k]["partial"]}
                  for t in types if (k := (t["company"], t["kind"])) in before],
    }


def build_change_ledger(prev: dict | None, rows: list[dict], report_path: Path) -> list[dict]:
    """Every row whose verdict, failing list or ceiling differs between v1 and v2 appears in the change ledger."""
    if not prev or "rows" not in prev:
        return []
    prev_rows = {r["id"]: r for r in prev["rows"]}
    ledger = []
    for curr in rows:
        p = prev_rows.get(curr["id"])
        if not p:
            continue
        v_diff = p.get("verdict") != curr.get("verdict")
        f_diff = p.get("failing") != curr.get("failing")
        c_diff = p.get("ceiling") != curr.get("ceiling")
        if not (v_diff or f_diff or c_diff):
            continue

        # S-6: Attribute change to scorer:S-1 through scorer:S-6, or none
        rule = "none"
        if not v_diff and not f_diff and c_diff:
            rule = "scorer:S-6"
        elif curr.get("boundary") == "segment" or "segment" in str(curr.get("ceiling", [])):
            rule = "scorer:S-1"
        elif "% of" in str(curr.get("unit_text") or "") or "% of" in str(curr.get("metric_text") or ""):
            rule = "scorer:S-2"
        elif "tco2e" in str(curr.get("unit_text") or "").lower():
            rule = "scorer:S-3"
        elif is_string_answer(curr.get("value_text") or ""):
            rule = "scorer:S-4"
        elif curr.get("origin") != p.get("origin") or curr.get("period_origin") or curr.get("boundary_origin"):
            rule = "scorer:S-5"
        else:
            rule = "scorer:S-6"

        entry = {
            "id": curr["id"],
            "v1_verdict": p.get("verdict"),
            "v1_failing": p.get("failing", []),
            "v1_ceiling": p.get("ceiling", []),
            "v2_verdict": curr.get("verdict"),
            "v2_failing": curr.get("failing", []),
            "v2_ceiling": curr.get("ceiling", []),
            "attributed_to": rule,
            "claim_id": curr.get("claim"),
            "value_text": curr.get("value_text"),
            "unit_text": curr.get("unit_text"),
            "page": curr.get("page"),
            "doc": curr.get("doc"),
            "company": curr.get("company"),
        }
        if rule == "scorer:S-1":
            entry["segment_name"] = curr.get("boundary_detail") or curr.get("boundary_origin")
        ledger.append(entry)

    if ledger:
        ledger_path = report_path.with_name(
            report_path.name.replace("g2-report-", "g2-ledger-").replace(".json", ".jsonl")
        )
        ledger_path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in ledger), encoding="utf-8")
    return ledger


def measure(workspace: str | None, gold: str, seed: int | None = None, against: str | None = None) -> dict:
    """Score the current published version. Refuses (nothing written) before any result exists."""
    root = layout.locate(workspace)
    manifest, docs, gold_rows = load_gold(Path(gold).expanduser())
    prev = _previous(against, manifest)
    work = published.open_version(root / layout.DB_NAME)  # read-only, like a published version
    try:
        try:
            current = published.current_version(work, root)
        except sqlite3.OperationalError:
            raise GctError(REFUSED, f"The working database in {root} cannot be read: SQLite adds its -wal and -shm"
                                    " files beside it to read it, and that folder is read-only.",
                           "Make the folder writable, or score a writable copy of the workspace.") from None
        if current is None or not current[1].is_file():
            raise GctError(REFUSED, "The workspace has no published version to score.",
                           "Build one with: gct publish build")
        version, path = current
        built_at, mark = work.execute("SELECT built_at, history_mark FROM published_version WHERE version = ?",
                                      (version,)).fetchone()
        identity = {"workspace": str(root), "built_at": built_at, "history_mark": mark, "sha256": _sha256(path)}
        proj = published.open_version(path)
        try:
            names = dict(proj.execute("SELECT id, name FROM company"))
            ws_docs = {r["sha256"]: dict(r) for r in proj.execute("SELECT id, company_id, logical_name, sha256 FROM document")}
            claims = [{**dict(r), "company": names[r["company_id"]]} for r in proj.execute(
                "SELECT id, company_id, document_id, page_number, claim_version_id, metric_text, value_text, unit_text,"
                " period_start, period_end, reporting_boundary, boundary_detail, period_state, boundary_state"
                " FROM claim WHERE claim_state = 'current' ORDER BY id")]
            refs = {}
            for r in proj.execute("SELECT claim_version_id, document_id, page_number, boxes FROM evidence_ref ORDER BY id"):
                refs.setdefault(r["claim_version_id"], []).append(dict(r))
        finally:
            proj.close()
        joined = {}
        for name, d in docs.items():
            if d["sha256"] in ws_docs:
                joined[name] = ws_docs[d["sha256"]]
                continue
            if any(w["logical_name"] == name for w in ws_docs.values()):
                raise GctError(REFUSED, f"The gold document {name} differs from the workspace document of that name"
                                        " (sha256).", "Score a workspace built from the gold documents' files.")
            raise GctError(REFUSED, f"The gold document {name} has no document row in published version {version}.",
                           "Add it with gct doc add, run the stages, then: gct publish build")
        companies = list(dict.fromkeys(d["company"] for d in docs.values()))
        for company in companies:
            if not any(c["company"] == company for c in claims):
                raise GctError(REFUSED, f"Published version {version} has no current claims for {company}.",
                               "Read and extract its documents, then: gct publish build")
        rows = [score_row(r, docs[r["doc"]], joined[r["doc"]], claims, refs)
                for r in sorted(gold_rows, key=lambda r: r["id"])]
        seed = secrets.randbelow(2 ** 31) if seed is None else seed
        is_review_assisted = "review-assisted" in str(root)
        documents = []
        for name, d in docs.items():
            mine = [r for r in rows if r["doc"] == name]
            mix = _method_mix(work, joined[name]["id"])
            documents.append({"doc": name, "company": d["company"], "document_type": d["document_type"],
                              "document_id": joined[name]["id"], **summarise(mine, review_assisted=is_review_assisted),
                              "method_mix": mix, "cost": _cost(work, joined[name]["id"])})
        above = sum(m["pages"] for d in documents for m in d["method_mix"] if m["rung"] > 1)
    finally:
        work.close()

    def group(keys):
        out = []
        for k in sorted({tuple(r[x] for x in keys) for r in rows}, key=lambda k: tuple(
                companies.index(v) if x == "company" else KINDS.index(v) if x == "kind" else v
                for x, v in zip(keys, k))):
            out.append({**dict(zip(keys, k)), **summarise([r for r in rows if tuple(r[x] for x in keys) == k], review_assisted=is_review_assisted)})
        return out

    types = [{"company": c, "kind": k, **summarise([r for r in rows if r["company"] == c and r["kind"] == k], review_assisted=is_review_assisted)}
             for c in companies for k in KINDS]
    change = prev and delta(prev, identity, types)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report_path = root.parent / f"g2-report-v{version}-{run_id}.json"
    ledger = build_change_ledger(prev, rows, report_path)
    if change and ledger:
        change["ledger"] = ledger
        change["ledger_file"] = str(report_path.with_name(report_path.name.replace("g2-report-", "g2-ledger-").replace(".json", ".jsonl")))
    report = {
        "published_version": version, "gct_commit": _git_head(Path(gct.__file__).parent),
        "scorer_version": SCORER_VERSION, "status": "ok", "run_id": run_id, "report_path": str(report_path),
        "workspace": str(root), "published": identity,
        "gold": {"folder": str(Path(gold).expanduser().resolve()), "version": manifest.get("gold_version"),
                 "commit": _git_head(Path(gold).expanduser()), "sha256": manifest.get("sha256", {})},
        "headline": f"{companies[0]} only: the second-company validation is not complete",
        "target": "90% Found per content type, each separately; a type below it is a fail for that type",
        "delta": change, "rows": rows, "types": types, "document_types": group(("company", "document_type", "kind")),
        "documents": documents,
        "runs": [{"row": "rung 1", "state": "scored"},
                 {"row": "local escalation",
                  "state": "not run" if not above else f"{above} pages read above rung 1, not scored separately"}],
        "adjudication": {"seed": seed, "missed": [r["id"] for r in rows if r["verdict"] == "Missed"],
                         "found_sample": _sample(rows, companies, seed)},
        "aggregate": [*({"kind": k, **summarise([r for r in rows if r["kind"] == k], review_assisted=is_review_assisted)} for k in KINDS),
                      {"kind": "all", **summarise(rows, review_assisted=is_review_assisted)}],
    }
    report_path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report
