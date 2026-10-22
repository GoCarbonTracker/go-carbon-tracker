import argparse
import json
import math
import os
import sys
import webbrowser
from collections import Counter

from gct import __version__
from gct.api import server
from gct.measure import g2
from gct.models import adapters, policy
from gct.stages import (adjudicate, archive, correct, deletion, extract, highlight, infer, link, match, missing, read,
                        restate, review, sheet)
from gct.workspace import intake, layout, lock, published, registry, runs, store
from gct.workspace.layout import GctError


def _print(args, payload: dict, text: str) -> None:
    print(json.dumps(payload) if args.json else text)


def _open(args, write=True):
    """Locate and upgrade the workspace. A writing command holds the workspace lock until main() returns;
    a read-only one takes it only for an upgrade."""
    args.root = layout.locate(args.workspace)
    conn = store.connect(args.root / layout.DB_NAME)
    if write or store.pending(conn):
        args.lock = lock.hold(args.root)
    applied = store.migrate(conn)
    if applied:
        with runs.run(conn, "workspace upgrade") as run_id:
            for version in applied:
                runs.event(conn, run_id, "note", message=f"applied migration {version}")
    if not write and getattr(args, "lock", None):
        lock.release(args.lock)
        args.lock = None
    return conn


def _doc_line(d: dict) -> str:
    return (f"{d['id']}  {d['company']}  {d['logical_name']}  v{d['version']}  {d['privacy']}  {d['state']}"
            + (f" {d['deleted_at'][:10]}" if d["deleted_at"] else ""))


def _mark(m: dict | None, made: str | None = None) -> str:
    """The marker of a record whose evidence was deleted (story 4.5, P5), after the record's own date when given."""
    if not m:
        return ""
    return (f"  made {made}" if made else "") + f"  evidence deleted (document {m['document']}, {m['at'][:10]})"


def cmd_init(args) -> None:
    status, path = layout.init_workspace(args.path)
    text = f"Created workspace at {path}" if status == "ok" else f"Already a workspace: {path}. Nothing changed."
    _print(args, {"status": status, "path": str(path)}, text)


def cmd_company_add(args) -> None:
    conn = _open(args)
    status, company = registry.add_company(conn, args.name, args.sector_ref, args.sector_version)
    verb = "Added" if status == "ok" else "Already exists:"
    _print(args, {"status": status, **company}, f"{verb} company '{company['name']}' (id {company['id']}).")


def cmd_company_list(args) -> None:
    companies = registry.list_companies(_open(args, write=False))
    text = "\n".join(f"{c['id']}  {c['name']}" for c in companies) or 'No companies yet. Add one with: gct company add "NAME"'
    _print(args, {"status": "ok", "companies": companies}, text)


def _item_line(i: dict) -> str:
    d = i["document"]
    if i["action"] == "registered":
        return f"registered {d['id']}: {d['logical_name']} (version {d['version']}, {d['privacy']})"
    if i["action"] == "duplicate":
        line = f"duplicate of {d['id']}: {i['source']}" if d else f"duplicate: {i['source']}"
        return line + (f"\nIt is archived. {i['next_action']}" if i["next_action"] else "")
    if i["cause"]:
        return f"{i['action']}: {i['source']} — {i['cause']}"
    return f"{i['action']}: {i['source']}"


def cmd_doc_add(args) -> int:
    conn = _open(args, write=not args.plan)
    if args.plan:
        return _doc_add_out(args, intake.plan(conn, args.sources, args.company, args.name), plan=True)
    _, items = intake.add(conn, args.root, args.sources, args.company, args.kind, args.privacy, args.name, args.source)
    return _doc_add_out(args, items)


def _doc_add_out(args, items, plan=False, head=None, extra=None) -> int:
    """Print doc add items. head is a first text line and extra more top-level keys (resume and retry)."""
    summary = ", ".join(f"{n} {a}" for a, n in Counter(i["action"] for i in items).items())
    text = "\n".join([*([head] if head else []), *map(_item_line, items),
                      f"{summary}. Nothing was stored." if plan else summary])
    bad = [i["source"] for i in items if i["action"] in ("refused", "failed")]
    if plan or not bad:
        _print(args, {"status": "ok", **(extra or {}), "items": items}, text)
        return 0
    cause = f"{len(bad)} of {len(items)} items were not added."
    next_action = "Check these and add them again: " + ", ".join(bad)
    _print(args, {"status": "partial", "cause": cause, "next_action": next_action, **(extra or {}), "items": items}, text)
    if not args.json:
        print(f"error: {cause}\nnext: {next_action}", file=sys.stderr)
    return layout.REFUSED


def cmd_doc_list(args) -> None:
    docs = registry.list_documents(_open(args, write=False), args.company)
    shown = [d for d in docs if d["state"] in read.ACTIVE] if args.active else docs
    hidden = Counter(d["state"] for d in docs if args.active and d["state"] not in read.ACTIVE)
    text = "\n".join(_doc_line(d) for d in shown) or "No documents yet."
    for state, n in sorted(hidden.items()):
        text += f"\n{n} {state} document{'s' * (n > 1)} hidden. Show every document with: gct doc list"
    _print(args, {"status": "ok", "documents": shown, "hidden_by_archive": hidden["archived"],
                  "hidden_deleted": hidden["deleted"]}, text)


def _change_line(c: dict) -> str:
    org = f", {c['organisation']}" if c["organisation"] else ""
    return f"{c['state']} by {c['contributor']}{org} ({c['capacity']}) at {c['at']}: {c['rationale']}"


def cmd_doc_show(args) -> None:
    conn = _open(args, write=False)
    doc = registry.show_document(conn, args.id)
    change = registry.state_change(conn, args.id)
    gone = deletion.status(conn, args.id)
    lines = [f"{k}: {v}" for k, v in doc.items()] + ([_change_line(change)] if change else [])
    if gone:
        lines.append(f"Deletion steps done: {', '.join(gone['steps'])}")
        if gone["pending"]:
            lines.append(f"Pending: {', '.join(gone['pending'])}. Finish with: gct doc delete {args.id} --confirm "
                         f"{deletion.token(doc)}")
        lines += [f"{r['kind']} #{r['id']} {r['what']} by {r['contributor']} ({r['capacity']}) at {r['created_at']}: "
                  f"{r['rationale']}{_mark(r['evidence_deleted'])}" for r in gone["records"]]
    _print(args, {"status": "ok", "document": doc, "state_change": change, "deletion": gone}, "\n".join(lines))


def _impact_lines(i: dict) -> list[str]:
    r = i["review_records"]
    lines = [f"  {i['claims']} claims, {i['evidence_refs']} evidence references"]
    lines += [f"  series {s['id']} ({s['metric_key'] or s['label']}, {s['unit_family']}, {s['reporting_boundary']}): "
              f"{s['points']} of {s['points'] + s['points_left']} points" for s in i["series"]]
    lines += [f"  same-period set in series {s['series']}, {s['period_start']}..{s['period_end']}: "
              f"{s['points']} values become {s['points_left']}" for s in i["same_period_sets"]]
    lines.append(f"  {i['uncertain_items']} uncertain items")
    if i["expected_items"]:
        lines.append("  expectations computed from it: " + ", ".join(map(str, i["expected_items"])))
    lines.append(f"  review records kept, no longer in active outputs: {r['inference_review']} inference reviews, "
                 f"{r['correction']} corrections, {r['match_review']} match reviews, {r['page_acceptance']} page "
                 f"acceptances, {r['restatement']} restatement records, {r['sheet_mapping']} sheet mappings, "
                 f"{r['review_company']} company confirmations, {r['review_auditor']} auditor reviews, "
                 f"{r['adjudication']} adjudications, {r['reviewer_flag']} reviewer flags, {r['highlight']} highlights")
    return lines


def cmd_doc_archive(args) -> None:
    conn = _open(args, write=not args.plan)
    impact = archive.impact(conn, args.id)
    doc = registry.show_document(conn, args.id)
    head = f"Archiving document {args.id} ({doc['logical_name']}) takes out of the active outputs:"
    if args.plan:
        _print(args, {"status": "ok", "document": doc, "impact": impact, "state_change": None},
               "\n".join([head, *_impact_lines(impact), "Nothing was stored."]))
        return
    missing_flags = [f for f, v in (("--as", args.as_), ("--capacity", args.capacity), ("--rationale", args.rationale)) if v is None]
    if missing_flags:
        raise GctError(layout.USAGE, f"Archiving needs {', '.join(missing_flags)}.",
                       f"Give them, for example: gct doc archive {args.id} --as KEY --capacity TEXT --rationale TEXT,"
                       f" or see the impact first with: gct doc archive {args.id} --plan")
    change = registry.archive(conn, args.id, args.as_, args.capacity, args.rationale)
    _print(args, {"status": "ok", "document": registry.show_document(conn, args.id), "impact": impact, "state_change": change},
           "\n".join([head, *_impact_lines(impact), f"Archived: {_change_line(change)}",
                      f"Its file and history are kept. Restore it with: gct doc restore {args.id}"]))


def cmd_doc_restore(args) -> None:
    conn = _open(args)
    change = registry.restore(conn, args.id, args.as_, args.capacity, args.rationale)
    _print(args, {"status": "ok", "document": registry.show_document(conn, args.id), "state_change": change},
           f"Restored document {args.id}: {_change_line(change)}")


def _plan_lines(p: dict) -> list[str]:
    doc, f, n = p["document"], p["files"], p["document"]["id"]
    lines = [f"Deleting document {n} ({doc['logical_name']}) takes it out of every active output:",
             *_impact_lines(p["impact"]),
             "Its content is cleared for good; the rows stay, so the records that cite them still resolve:",
             *(f"  {t.replace('_', ' ')}: {k} rows" for t, k in p["clears"].items()),
             "Kept: the company, contributors, expectations, other documents and everything of theirs, and every review"
             f" record above with its contributor, decision and date; its capacity and rationale read"
             f" \"{deletion.MARKER.format(n)}\".",
             "Files removed: " + ", ".join([
                 "the original file" if f["files"]["remove"] else "none of the original (another document has the same file)",
                 f"{f['artifacts']['remove']} reading files ({f['artifacts']['keep']} kept, used by another document)",
                 "its page images" if f["renders"]["remove"] else
                 "none of its page images (another document has the same file)" if f["renders"]["keep"] else
                 "no page images"]),
             "Published versions it is removed from: " + (", ".join(map(str, p["versions"])) or "none"),
             p["warning"], deletion.OWN_TEXT, f"Confirmation token: {p['token']}"]
    return lines


def cmd_doc_delete(args) -> int:
    conn = _open(args, write=args.confirm is not None)
    if args.confirm is None:
        p = deletion.plan(conn, args.root, args.id)
        cause = "Nothing was deleted: deleting needs the confirmation token."
        next_action = (f"Delete it with: gct doc delete {args.id} --confirm {p['token']} --as KEY --capacity TEXT"
                       " --rationale TEXT")
        _print(args, {"status": "plan", "cause": cause, "next_action": next_action, **p}, "\n".join(_plan_lines(p)))
        if not args.json:
            print(f"error: {cause}\nnext: {next_action}", file=sys.stderr)
        return layout.REFUSED
    gone = deletion.delete(conn, args.root, args.id, args.confirm, args.as_, args.capacity, args.rationale)
    change = registry.state_change(conn, args.id)
    _print(args, {"status": "ok", "document": registry.show_document(conn, args.id), "state_change": change,
                  "deletion": gone},
           f"Deleted document {args.id}: {_change_line(change)}\nSteps done: {', '.join(gone['steps'])}\n"
           f"{deletion.WARNING}")
    return 0


def _counts(flags: dict) -> str:
    return ", ".join(f"{code} {n}" for code, n in sorted(flags.items())) or "none"


def _read_line(d: dict) -> str:
    if d["action"] != "read":
        return f"{d['action']} {d['id']}: {d['logical_name']}: {d['cause']}"
    flagged = f"{d['flagged']} flagged" + (f" ({_counts(d['flags'])})" if d["flags"] else "")
    return (f"read {d['id']}: {d['logical_name']}: {d['pages']} pages, {d['read']} read, {d['cached']} cached, "
            f"{flagged}, {d['failed']} failed")


def cmd_read(args) -> int:
    _, docs = read.read(_open(args), args.root, args.ids, args.company)
    return _read_out(args, docs)


def _read_out(args, docs, head=None, extra=None) -> int:
    """Print read documents. head is a first text line and extra more top-level keys (resume and retry)."""
    extra = extra or {}
    if not docs:
        _print(args, {"status": "ok", **extra, "documents": []}, "Nothing to read.")
        return 0
    total = {k: sum(d[k] for d in docs) for k in ("pages", "read", "cached", "flagged", "failed")}
    flags = sum((Counter(d["flags"]) for d in docs), Counter())
    text = "\n".join([
        *([head] if head else []),
        *map(_read_line, docs),
        f"Total: {len(docs)} documents, {total['pages']} pages, {total['read']} read, {total['cached']} cached, "
        f"{total['flagged']} flagged, {total['failed']} failed",
        f"Flagged pages: {_counts(flags)}",
        f"{flags['no_text']} pages without text",
    ])
    bad = [d for d in docs if d["action"] == "failed" or d["failed"]]
    if not bad:
        _print(args, {"status": "ok", **extra, "documents": docs}, text)
        return 0
    cause = f"{len(bad)} of {len(docs)} documents were not fully read: " + ", ".join(str(d["id"]) for d in bad)
    _print(args, {"status": "partial", "cause": cause, "next_action": read.RETRY, **extra, "documents": docs}, text)
    if not args.json:
        print(f"error: {cause}\nnext: {read.RETRY}", file=sys.stderr)
    return layout.REFUSED


def cmd_doc_pages(args) -> None:
    conn = _open(args, write=False)
    ps = read.pages(conn, args.id)
    state = registry.show_document(conn, args.id)["state"]
    head = [f"Document {args.id} is archived."] if state == "archived" else []
    if not ps:
        _print(args, {"status": "ok", "document": args.id, "document_state": state, "pages": []},
               "\n".join([*head, f"No pages read yet. Run: gct read {args.id}"]))
        return
    flags = Counter(f for p in ps for f in p["flags"])
    lines = [
        f"p{p['page_number']}  rung {p['rung']}  {p['method']}  words {p['words']}  tables {p['tables']}  "
        f"flags {', '.join(p['flags']) or 'none'}"
        for p in ps
    ]
    text = "\n".join([*head, *lines, f"Flagged pages: {_counts(flags)}", f"{flags['no_text']} pages without text"])
    _print(args, {"status": "ok", "document": args.id, "document_state": state, "pages": ps}, text)


EXTRACT_TOTALS = ("pages", "extracted", "cached", "failed", "figures", "no_box")


def _extract_line(d: dict) -> str:
    if d["action"] != "extracted":
        return f"{d['action']} {d['id']}: {d['logical_name']}: {d['cause']}" + (f" ({d['next_action']})" if d["next_action"] else "")
    return (f"extracted {d['id']}: {d['logical_name']}: {d['pages']} pages, {d['extracted']} extracted, "
            f"{d['cached']} cached, {d['failed']} failed, {d['figures']} figures, {d['no_box']} without a box"
            # A spreadsheet's notes: sheets without a confirmed mapping, rows for another company (story 4.3).
            + (f"; {d['cause']}" if d["cause"] and not d["failed"] else ""))


def cmd_extract(args) -> int:
    _, docs = extract.extract(_open(args), args.root, args.ids, args.company)
    return _extract_out(args, docs)


def _extract_out(args, docs, head=None, extra=None) -> int:
    """Print extract documents. head is a first text line and extra more top-level keys (resume and retry)."""
    extra = extra or {}
    if not docs:
        _print(args, {"status": "ok", **extra, "documents": []}, "Nothing to extract.")
        return 0
    total = {k: sum(d[k] for d in docs) for k in EXTRACT_TOTALS}
    text = "\n".join([
        *([head] if head else []),
        *map(_extract_line, docs),
        f"Total: {len(docs)} documents, {total['pages']} pages, {total['extracted']} extracted, {total['cached']} cached, "
        f"{total['failed']} failed, {total['figures']} figures, {total['no_box']} without a box",
    ])
    bad = [d for d in docs if d["failed"]]
    if not bad:
        _print(args, {"status": "ok", **extra, "documents": docs}, text)
        return 0
    cause = f"{len(bad)} of {len(docs)} documents were not fully extracted: " + ", ".join(str(d["id"]) for d in bad)
    # Only spreadsheets failed: their own retry wording (a failed spreadsheet's record carries it).
    retry = sheet.RETRY if all(d["next_action"] == sheet.RETRY for d in bad) else extract.RETRY
    _print(args, {"status": "partial", "cause": cause, "next_action": retry, **extra, "documents": docs}, text)
    if not args.json:
        print(f"error: {cause}\nnext: {retry}", file=sys.stderr)
    return layout.REFUSED


def _period_text(p: dict) -> str:
    """The effective period: dates, kind and state word, or the label and unknown with the reason."""
    if p["state"] == "extracted":
        return p["label"] or "-"
    if p["start"]:
        return (f"{p['label']} → " if p["label"] else "") + f"{p['start']}..{p['end']} {p['kind']} {p['state']}"
    return f"{p['label'] or '-'} unknown {p['state']} ({p['reason']})"


def _boundary_text(b: dict) -> str:
    if b["state"] == "extracted":
        return b["boundary"]
    if b["state"] == "unresolved":
        return f"unknown unresolved ({b['reason']})"
    return f"{b['boundary']}" + (f" ({b['detail']})" if b["detail"] else "") + f" {b['state']}"


def _where(e: dict) -> str:
    """A source location: the sheet and cell of a spreadsheet (both cleared by a deletion: ''), else the page."""
    if e["sheet"] is None:
        return f"p{e['page_number']}"
    return f"sheet {e['sheet']} cell {e['cell']}" if e["sheet"] else "sheet and cell cleared"


def _claim_line(c: dict) -> str:
    status = c["source_match"] or "not checked: gct link"
    status += f" ({c['source_match_reason']})" if c["source_match_reason"] else ""
    box = "  box " + ", ".join(f"{v:g}" for v in c["boxes"][0]) if c["boxes"] else ""
    label = f"  {c['boundary_label']}" if c["boundary_label"] else ""
    review = "".join(f"\n  needs re-review: {correct.entry_text(e)}" for e in c["needs_re_review"])
    return (f"{c['id']}  {_where(c)}  {c['claim_state']}  {c['value_text']}  {c['unit_text'] or '-'}  "
            f"{c['metric_text'] or '-'}  {_period_text(c['period'])}  {_boundary_text(c['boundary'])}{label}  "
            f"{status}{box}{review}")


def cmd_claims_list(args) -> None:
    conn = _open(args, write=False)
    cs = extract.claims(conn, args.doc)
    eff, states, reviews = (f(conn, args.doc) for f in (infer.effective, correct.states, correct.re_review))
    refs = sheet.refs(conn, [c["id"] for c in cs])
    cs = [{**c, **eff[c["id"]], **refs[c["id"]], "claim_state": states[c["id"]], "needs_re_review": reviews.get(c["id"], [])}
          for c in cs
          if args.state is None or states[c["id"]] == correct.STATES[args.state]]
    text = "\n".join(map(_claim_line, cs)) or (
        f"No {args.state} claims." if args.state else f"No claims yet. Run: gct extract {args.doc}")
    _print(args, {"status": "ok", "document": args.doc, "claims": cs}, text)


def _fields(c: dict) -> str:
    words = {col: w for col, _, w in correct.FIELDS}
    return ", ".join(words[f] for f in c["fields"])


def _version_lines(v: dict, mark: dict | None = None) -> list[str]:
    """mark: the evidence-deleted marker added to each contributor record of a deleted document's claim."""
    head = (f"version {v['id']}  {v['method']}  run {v['run_id']}  {v['created_at']}  {v['value_text']}  "
            f"{v['unit_text'] or '-'}  {v['metric_text'] or '-'}  {v['period_label'] or '-'}"
            + (f"  {v['boundary_label']}" if v["boundary_label"] else ""))
    lines = [head]
    if c := v["correction"]:
        lines.append(f"  correction #{c['id']} of version {c['corrects_version']} ({_fields(c)}) by "
                     f"{c['contributor']} ({c['capacity']}): {c['rationale']}; replaced "
                     f"{c['replaced']['value_text']}{_mark(mark, c['created_at'])}")
    for e in v["evidence_refs"]:
        matches = ", ".join(s["status"] + (f" ({s['reason']})" if s["reason"] else "") for s in e["source_match"])
        lines.append(f"  location {_where(e)}: {matches or 'not checked: gct link'}")
    lines += [f"  {i['field']} inference #{i['id']}: {i['state']}" + (f" ({i['reason']})" if i["reason"] else "")
              for i in v["inferences"]]
    lines += [f"  {r['field']} review #{r['id']}: {r['decision']} by {r['contributor']} ({r['capacity']}): {r['rationale']}"
              f"{_mark(mark, r['created_at'])}" for r in v["reviews"]]
    lines += [f"  found by extraction in run {s['run_id']} of reading {s['page_id']}" for s in v["seen"]]
    return lines


def cmd_claims_history(args) -> None:
    conn = _open(args, write=False)
    h = correct.history(conn, args.claim)
    where = sheet.cells(conn, args.claim)
    for v in h["versions"]:  # a spreadsheet location is its sheet and cell (story 4.3)
        v["evidence_refs"] = [{**e, **where[e["id"]]} for e in v["evidence_refs"]]
    c = h["claim"]
    lines = [f"claim {c['id']}  document {c['document']} ({c['document_state']})  p{c['page_number']}  {c['locator']}  "
             f"{c['state']}{_mark(c['evidence_deleted'])}",
             *(f"  needs re-review: {correct.entry_text(e)}" for e in c["needs_re_review"]),
             *(line for v in h["versions"] for line in [*_version_lines(v, c["evidence_deleted"]),
                                                       *_records_lines(v, c["evidence_deleted"])])]
    if any(_records_lines(v) for v in h["versions"]):
        lines.append(review.SELF_DECLARED)
    _print(args, {"status": "ok", **h}, "\n".join(lines))


def cmd_correct(args) -> None:
    r = correct.correct(_open(args), args.claim, args.as_, args.capacity, args.rationale, value_text=args.value,
                        unit_text=args.unit, metric_text=args.metric, period_label=args.period_label)
    c = r["correction"]
    _print(args, {"status": "ok", **r},
           f"Corrected claim {r['claim']}: version {r['version']} replaces version {c['corrects_version']} "
           f"({_fields(c)}). Earlier versions stay in its history: gct claims history {r['claim']}")


LINK_TOTALS = ("refs", "checked", "cached", "failed", "matched", "cited", "unresolved")


def _link_line(d: dict) -> str:
    if d["action"] != "checked":
        return f"{d['action']} {d['id']}: {d['logical_name']}: {d['cause']}" + (f" ({d['next_action']})" if d["next_action"] else "")
    return (f"checked {d['id']}: {d['logical_name']}: {d['refs']} locations, {d['checked']} checked, {d['cached']} cached, "
            f"{d['failed']} failed; {d['matched']} matched, {d['cited']} cited, {d['unresolved']} unresolved")


def cmd_link(args) -> int:
    _, docs = link.link(_open(args), args.root, args.ids, args.company)
    return _link_out(args, docs)


def _link_out(args, docs, head=None, extra=None) -> int:
    """Print link documents. head is a first text line and extra more top-level keys (resume and retry)."""
    extra = extra or {}
    if not docs:
        _print(args, {"status": "ok", **extra, "documents": []}, "Nothing to check.")
        return 0
    total = {k: sum(d[k] for d in docs) for k in LINK_TOTALS}
    text = "\n".join([
        *([head] if head else []),
        *map(_link_line, docs),
        f"Total: {len(docs)} documents, {total['refs']} locations, {total['checked']} checked, {total['cached']} cached, "
        f"{total['failed']} failed; {total['matched']} matched, {total['cited']} cited, {total['unresolved']} unresolved",
    ])
    bad = [d for d in docs if d["failed"]]
    if not bad:
        _print(args, {"status": "ok", **extra, "documents": docs}, text)
        return 0
    cause = f"{len(bad)} of {len(docs)} documents were not fully checked: " + ", ".join(str(d["id"]) for d in bad)
    _print(args, {"status": "partial", "cause": cause, "next_action": link.RETRY, **extra, "documents": docs}, text)
    if not args.json:
        print(f"error: {cause}\nnext: {link.RETRY}", file=sys.stderr)
    return layout.REFUSED


def _state_lines(name: str, counts: dict) -> list[str]:
    """'  period: 3 proposed, 9 unresolved' and one line per unresolved reason, each on its own line."""
    states = [f"{counts[s]} {s}" for s in infer.STATES if counts.get(s)]
    reasons = [f"    {k}: {n}" for k, n in counts.items() if k.startswith("unresolved: ")]
    return [f"  {name}: {', '.join(states) or 'no claims'}", *reasons]


def _infer_lines(d: dict) -> list[str]:
    if d["action"] != "inferred":
        return [f"{d['action']} {d['id']}: {d['logical_name']}: {d['cause']}" + (f" ({d['next_action']})" if d["next_action"] else "")]
    head = (f"inferred {d['id']}: {d['logical_name']}: {d['claims']} claims, {d['inferred']} inferred, {d['cached']} cached, "
            f"{d['failed']} failed; {d['bases']} statements found, {d['headings']} boundary headings without a readable answer")
    return [head, *_state_lines("period", d["period"]), *_state_lines("boundary", d["boundary"])]


def cmd_infer(args) -> int:
    _, docs = infer.infer(_open(args), args.root, [args.doc] if args.doc else [], args.company)
    return _infer_out(args, docs)


def _infer_out(args, docs, head=None, extra=None) -> int:
    """Print infer documents. head is a first text line and extra more top-level keys (resume and retry)."""
    extra = extra or {}
    if not docs:
        _print(args, {"status": "ok", **extra, "documents": []}, "Nothing to infer.")
        return 0
    text = "\n".join([*([head] if head else []), *(line for d in docs for line in _infer_lines(d)),
                      "Proposed values are not used until accepted: gct infer groups, then gct infer accept GROUP."])
    bad = [d for d in docs if d["failed"]]
    if not bad:
        _print(args, {"status": "ok", **extra, "documents": docs}, text)
        return 0
    cause = f"{len(bad)} of {len(docs)} documents were not inferred: " + ", ".join(str(d["id"]) for d in bad)
    _print(args, {"status": "partial", "cause": cause, "next_action": infer.RETRY, **extra, "documents": docs}, text)
    if not args.json:
        print(f"error: {cause}\nnext: {infer.RETRY}", file=sys.stderr)
    return layout.REFUSED


def _basis_line(b: dict) -> str:
    what = (f"fiscal year end {b['year_end']}" if b["kind"] == "fiscal_year_end"
            else b["boundary"] + (f" ({b['detail']})" if b["detail"] else ""))
    s = b["scope"]
    scope = ("" if b["kind"] == "fiscal_year_end" else
             f"  pages {s['first']}-{s['last']} declared by {s['contributor']} ({s['capacity']})" if s else
             f"  no pages declared: gct infer scope {b['id']} --pages FIRST-LAST")
    return f"#{b['id']}  document {b['document']} p{b['page']}  {what}  \"{b['wording']}\"{scope}"


def cmd_infer_bases(args) -> None:
    bs, headings = infer.bases(_open(args, write=False), args.doc)
    lines = [*map(_basis_line, bs), *(f"document {h['document']} p{h['page']}  {h['reason']}" for h in headings)]
    _print(args, {"status": "ok", "bases": bs, "headings": headings},
           "\n".join(lines) or "No statements found yet. Run: gct infer")


def cmd_infer_scope(args) -> None:
    b = infer.scope(_open(args), args.root, args.basis, args.pages, args.as_, args.capacity, args.rationale)
    _print(args, {"status": "ok", "basis": b},
           f"Declared: {_basis_line(b)}. It applies from the next run of: gct infer --doc {b['document']}")


def _values(g: dict) -> str:
    if g["field"] == "period":
        return f"{g['start']}..{g['end']} {g['kind']}" if g["start"] else "unknown"
    return (g["boundary"] + (f" ({g['detail']})" if g["detail"] else "")) if g["boundary"] else "unknown"


def _group_line(g: dict) -> str:
    source = (f"p{g['basis']['page']} \"{g['basis']['wording']}\"" if g["basis"] else
              "the label itself" if g["state"] == "proposed" else f"reason: {g['reason']}")
    reviews = ", ".join(f"{n} {k}" for k, n in g["reviews"].items() if n)
    return (f"{g['id']}  document {g['document']}  {g['field']}  {g['state']}  {_values(g)}  from {source}  "
            f"{g['claims']} claims  ({reviews})")


def cmd_infer_groups(args) -> None:
    gs = infer.groups(_open(args, write=False), args.doc, args.state)
    _print(args, {"status": "ok", "groups": gs}, "\n".join(map(_group_line, gs)) or "No groups yet. Run: gct infer")


def _decision_text(r: dict, verb: str) -> str:
    g = r["group"]
    text = f"{verb} {r[verb.lower()]} claims by {r['by']}: {_group_line(g)}"
    if r["skipped"]:
        text += "\nLeft as they were: " + ", ".join(f"{n} {k}" for k, n in r["skipped"].items()) + " (already decided)."
    if verb == "Accepted" and r["accepted"] and g["basis"] and g["basis"]["kind"] == "fiscal_year_end":
        text += (f"\nThis confirms the fiscal year end stated on page {g['basis']['page']} of document {g['document']}"
                 " for these claims.")
    return text


def cmd_infer_accept(args) -> None:
    r = infer.accept(_open(args), args.group, args.as_, args.capacity, args.rationale)
    _print(args, {"status": "ok", **r}, _decision_text(r, "Accepted"))


def _one_text(r: dict) -> str:
    rec, f = r["effective"], r["field"]
    shown = _period_text(rec) if f == "period" else _boundary_text(rec)
    rev = rec["review"]
    by = f" by {rev['contributor']} ({rev['capacity']}): {rev['rationale']}" if rev else ""
    return f"Claim {r['claim']} {f}: {shown}{by}"


def cmd_infer_resolve(args) -> None:
    r = infer.resolve(_open(args), args.claim, args.field, args.as_, args.capacity, args.rationale,
                      args.kind, args.start, args.end, args.boundary, args.detail)
    _print(args, {"status": "ok", **r}, _one_text(r))


def cmd_infer_reject(args) -> None:
    conn = _open(args)
    if (args.group is None) == (args.claim is None):
        raise GctError(layout.USAGE, "Give either a group or --claim, not both.", "For example: gct infer reject GROUP ...")
    if args.group is not None:
        r = infer.reject(conn, args.group, args.as_, args.capacity, args.rationale)
        _print(args, {"status": "ok", **r}, _decision_text(r, "Rejected"))
        return
    if args.field is None:
        raise GctError(layout.USAGE, "--claim needs --field period or --field boundary.",
                       f"For example: gct infer reject --claim {args.claim} --field period ...")
    r = infer.reject_claim(conn, args.claim, args.field, args.as_, args.capacity, args.rationale)
    _print(args, {"status": "ok", **r}, _one_text(r))


def _match_line(d: dict) -> str:
    if d["action"] != "matched":
        return f"{d['action']} {d['id']}: {d['logical_name']}: {d['cause']}" + (f" ({d['next_action']})" if d["next_action"] else "")
    return (f"matched {d['id']}: {d['logical_name']}: {d['claims']} claims, {d['matched']} matched, {d['cached']} cached, "
            f"{d['failed']} failed; {d['mapped']} mapped, {d['unmapped']} unmapped, {d['unit_unknown']} unit unknown")


def cmd_match(args) -> int:
    _, docs = match.match(_open(args), args.root, [args.doc] if args.doc else [], args.company)
    return _match_out(args, docs)


def _match_out(args, docs, head=None, extra=None) -> int:
    """Print match documents. head is a first text line and extra more top-level keys (resume and retry)."""
    extra = extra or {}
    if not docs:
        _print(args, {"status": "ok", **extra, "documents": []}, "Nothing to match.")
        return 0
    text = "\n".join([*([head] if head else []), *map(_match_line, docs),
                      "See the series with: gct series list, and the review queue with: gct match review"])
    bad = [d for d in docs if d["failed"]]
    if not bad:
        _print(args, {"status": "ok", **extra, "documents": docs}, text)
        return 0
    cause = f"{len(bad)} of {len(docs)} documents were not matched: " + ", ".join(str(d["id"]) for d in bad)
    _print(args, {"status": "partial", "cause": cause, "next_action": match.RETRY, **extra, "documents": docs}, text)
    if not args.json:
        print(f"error: {cause}\nnext: {match.RETRY}", file=sys.stderr)
    return layout.REFUSED


def cmd_match_metrics(args) -> None:
    m = match.metrics()
    lines = [f"Metric list v{m['metrics_version']}, unit table v{m['units_version']}, match rules v{m['rules_version']}",
             "A label containing any of these is unmapped: " + ", ".join(f'"{x}"' for x in m["excluded"]),
             *(f"{x['key']}: contains {' or '.join(repr(p) for p in x['must'])}"
               + (f"; not {', '.join(repr(p) for p in x['never'])}" if x["never"] else "") for x in m["metrics"]),
             "Units (text as looked up: base unit x factor):",
             *(f"  {u['text']}: {u['base']} x {u['factor']:g}" for u in m["units"]),
             "Magnitude words multiplied in: " + ", ".join(f"{p['text']} x {p['factor']:g}" for p in m["prefixes"])]
    _print(args, {"status": "ok", **m}, "\n".join(lines))


def _metric_text(s: dict) -> str:
    return s["metric_key"] or f"unmapped: {s['label']}"


def _boundary_of(s: dict) -> str:
    return s["reporting_boundary"] + (f" ({s['boundary_detail']})" if s["boundary_detail"] else "")


def _base(x: dict) -> str:
    return f"{x['value_base']:g} {x['unit_key']}" if x["value_base"] is not None else "no base value"


def _series_line(s: dict) -> str:
    latest = "; ".join(f"{x['value_text']} {x['unit_text'] or '-'}" for x in s["points"])
    return (f"{s['id']}  {s['company']}  {_metric_text(s)}  {_boundary_of(s)}  {s['unit_family']}  {s['period_kind']}  "
            f"{s['periods']} periods  latest {s['latest_period_end']}: {latest}")


def cmd_series_list(args) -> None:
    conn = _open(args, write=False)
    ss = [restate.mark(conn, s) for s in match.series_list(conn, args.company, args.metric)]
    _print(args, {"status": "ok", "series": ss},
           "\n".join(map(_series_line, ss)) or "No series yet. Run gct match, then accept or resolve periods and boundaries.")


def _pair_state(p: dict) -> str:
    """A pair state as shown: same value, restatement #id, unresolved conflict or not compared (reason)."""
    return p["state"] + (f" #{p['restatement']}" if p["restatement"] else "") + (f" ({p['reason']})" if p["reason"] else "")


def _point_line(x: dict) -> str:
    if x["link"] == "reviewed":
        r = x["review"]
        how = f"reviewed, not comparable ({x['reason']}) by {r['contributor']} ({r['capacity']}): {r['rationale']}"
    else:
        how = "rule" + (f", not comparable ({x['reason']})" if not x["comparable"] else "")
    many = len(x["pairs"]) > 1
    states = ", ".join((f"claim {p['claim']}: " if many else "") + _pair_state(p) for p in x["pairs"])
    same = f"  same period: {x['same_period']} values, {states}" if x["same_period"] > 1 else ""
    return (f"  {x['period_start']}..{x['period_end']}  {x['value_text']}  {x['unit_text'] or '-'}  {_base(x)}  "
            f"document {x['document_id']} {_where(x)}  claim {x['claim_id']}  {how}{same}")


def cmd_series_show(args) -> None:
    conn = _open(args, write=False)
    s = restate.mark(conn, match.series_show(conn, args.series, args.all))
    refs = sheet.refs(conn, [x["claim_id"] for x in s["points"]])
    s["points"] = [{**x, **refs[x["claim_id"]]} for x in s["points"]]  # a spreadsheet point names its sheet and cell
    head = (f"{s['id']}  {s['company']}  {_metric_text(s)}  {_boundary_of(s)}  {s['unit_family']}  {s['period_kind']}  "
            f"{s['periods']} periods" + ("" if args.all else f", latest period shown (all with --all)"))
    _print(args, {"status": "ok", "series": s}, "\n".join([head, *map(_point_line, s["points"])]))


def _item_text(i: dict) -> str:
    target = (i["metric_key"] or f"unmapped: {i['label']}") + "  " + i["reporting_boundary"] + (
        f" ({i['boundary_detail']})" if i["boundary_detail"] else "")
    return (f"claim {i['claim']}  document {i['document']} p{i['page_number']}  {i['metric_text'] or '-'}  "
            f"{i['value_text']} {i['unit_text'] or '-'}  {i['reason']}  could join series {i['series']}  {target}")


def cmd_match_review(args) -> None:
    items = match.queue(_open(args, write=False), args.company, args.reason)
    _print(args, {"status": "ok", "items": items}, "\n".join(map(_item_text, items)) or "No uncertain items.")


def _decision_line(r: dict, verb: str) -> str:
    b = r["by"]
    return (f"{verb} claim {r['claim']} (version {r['version']}) and series {r['series']} by {b['contributor']} "
            f"({b['capacity']}): {b['rationale']}. Claim is now {r['match_state']}"
            + (f" ({r['match_reason']})" if r["match_reason"] else "") + ".")


def cmd_match_link(args) -> None:
    r = match.link_claim(_open(args), args.claim, args.series, args.as_, args.capacity, args.rationale)
    _print(args, {"status": "ok", **r}, _decision_line(r, "Linked")
           + " A reviewed link is not comparable: the boundary or unit stays unknown.")


def cmd_match_unlink(args) -> None:
    r = match.unlink_claim(_open(args), args.claim, args.series, args.as_, args.capacity, args.rationale)
    _print(args, {"status": "ok", **r}, _decision_line(r, "Not linked:"))


def _status_lines(s: dict) -> list[str]:
    mapped = ", ".join(f"{k} {n}" for k, n in s["mapped"].items()) or "none"
    return [f"{s['company']}: {s['claims']} claims; mapped {sum(s['mapped'].values())} ({mapped}), {s['unmapped']} unmapped, "
            f"{s['unit_unknown']} unit unknown, {s['not_mapped_yet']} not mapped yet",
            f"  {s['series']} series, {s['same_period_sets']} same-period sets, {s['uncertain_items']} uncertain items",
            "  claims by state: " + (", ".join(f"{n} {k}" for k, n in s["states"].items()) or "none"),
            *(f"  not matchable: {k}: {n}" for k, n in s["not_matchable"].items()),
            "  pairs by state: " + (", ".join(f"{n} {k}" for k, n in s["pairs"].items()) or "none")]


def cmd_match_status(args) -> None:
    conn = _open(args, write=False)
    pairs = restate.counts(conn, args.company)
    st = [{**s, "pairs": pairs.get(s["company"], {})} for s in match.status(conn, args.company)]
    _print(args, {"status": "ok", "companies": st},
           "\n".join(line for s in st for line in _status_lines(s)) or "No claims yet.")


def _side(x: dict) -> str:
    return f"{x['value_text']} {x['unit_text'] or '-'} (document {x['document_id']} {_where(x)}, claim {x['claim_id']})"


def _located(conn, pairs) -> list[dict]:
    """The pairs for the text, each side with its claim's sheet and cell so _side prints a spreadsheet location."""
    refs = sheet.refs(conn, [x["claim_id"] for p in pairs for x in (p["a"], p["b"])])
    return [{**p, "a": {**p["a"], **refs[p["a"]["claim_id"]]}, "b": {**p["b"], **refs[p["b"]["claim_id"]]}}
            for p in pairs]


def _restate_line(p: dict) -> str:
    what = (p["metric_key"] or f"unmapped: {p['label']}") + "  " + _boundary_of(p)
    why = f" #{p['restatement']['id']}" if p["restatement"] else f" ({p['reason']})" if p["reason"] else ""
    return (f"{p['series_id']}  {p['company']}  {what}  {p['period_start']}..{p['period_end']}  {_side(p['a'])}  "
            f"{_side(p['b'])}  {p['state']}{why}")


def cmd_restate_list(args) -> None:
    conn = _open(args, write=False)
    shown, hidden = restate.listed(conn, args.company, args.state)
    lines = list(map(_restate_line, _located(conn, shown))) or ["No pairs" + (" in this state." if args.state else " yet.")]
    if args.state:
        lines.append(f"{hidden} pairs in other states hidden by --state {args.state}.")
    _print(args, {"status": "ok", "pairs": shown, "hidden": hidden}, "\n".join(lines))


def _record_text(r: dict) -> str:
    where = f" citing document {r['document']} p{r['page']}: \"{r['quote']}\"" if r["decision"] == "recorded" else ""
    return (f"restatement #{r['id']} {r['decision']}: version {r['original_version']} original, version "
            f"{r['restated_version']} restated{where}, by {r['contributor']} ({r['capacity']}): {r['rationale']}")


def _review_lines(v: dict, cells: dict) -> list[str]:
    """cells: the sheet and cell of each evidence reference of the claim (sheet.cells)."""
    r, m = v["reviews"], v["evidence_deleted"]
    return [f"  claim {v['claim']} version {v['id']}:{_mark(m)}",
            *(f"    {x['field']} review #{x['id']} {x['decision']} by {x['contributor']} ({x['capacity']}): {x['rationale']}"
              f"{_mark(m, x['created_at'])}" for x in r["inference_reviews"]),
            *(f"    correction #{x['id']} {x['role']} ({', '.join(x['fields'])}) by {x['contributor']} ({x['capacity']}):"
              f" {x['rationale']}{_mark(m, x['created_at'])}" for x in r["corrections"]),
            *(f"    match review #{x['id']} {x['decision']} series {x['series'] or '-'} by {x['contributor']}"
              f" ({x['capacity']}): {x['rationale']}{_mark(m, x['created_at'])}" for x in r["match_reviews"]),
            *(f"    location {_where({**x, **cells[x['evidence_ref']]})}: {x['status'] or 'not checked: gct link'}"
              + (f" ({x['reason']})" if x["reason"] else "") for x in r["source_match"]),
            *(f"    {_record_text(x)}" + ("" if x["current"] else " (superseded)")
              + ("" if x["binds"] else " (on an earlier version)") + _mark(x["evidence_deleted"], x["created_at"])
              for x in r["restatements"]),
            *_records_lines({**r, "id": v["id"]}, m, "    ")]


def cmd_restate_show(args) -> None:
    conn = _open(args, write=False)
    r = restate.show(conn, args.claim)
    c = r["claim"]
    cells = {k: x for v in r["versions"] for k, x in sheet.cells(conn, v["claim"]).items()}
    # Only a claim of an archived or deleted document has no match state.
    why = (c["match_state"] + (f" ({c['match_reason']})" if c["match_reason"] else "") if c["match_state"]
           else f"Document {c['document']} was deleted." if c["evidence_deleted"] else f"Document {c['document']} is archived.")
    head = (f"claim {c['id']}  document {c['document']} {_where({**c, **sheet.refs(conn, [c['id']])[c['id']]})}  "
            f"version {c['version']}  {why}")
    none = "No pairs: the claim shares no period." if c["series_id"] else (
        f"No pairs: the claim is in no series: {why}." if c["match_state"] else "No pairs.")
    lines = [head, *map(_restate_line, _located(conn, r["pairs"]))] if r["pairs"] else [head, none]
    needs = [f"needs re-review: {correct.entry_text(e)}" for e in c["needs_re_review"]]
    self_declared = [review.SELF_DECLARED] * any(_records_lines({**v["reviews"], "id": v["id"]}) for v in r["versions"])
    _print(args, {"status": "ok", **r}, "\n".join([*lines, *needs, "Records:", *(x for v in r["versions"] for x in _review_lines(v, cells)),
                                                   *self_declared]))


def _decided(r: dict) -> str:
    p = r["pair"]
    return _record_text(r["restatement"]) + "." + (
        f" The pair is now {_pair_state({**p, 'restatement': p['restatement'] and p['restatement']['id']})}." if p else "")


def cmd_restate_record(args) -> None:
    r = restate.record(_open(args), args.root, args.original, args.restated, args.page, args.quote, args.as_,
                       args.capacity, args.rationale)
    _print(args, {"status": "ok", **r}, _decided(r))


def cmd_restate_withdraw(args) -> None:
    r = restate.withdraw(_open(args), args.original, args.restated, args.as_, args.capacity, args.rationale)
    _print(args, {"status": "ok", **r}, _decided(r))


def _entry_line(e: dict) -> str:
    """One ledger entry, the contributor's words quoted and attributed (C5)."""
    where = []
    if e["evidence_document"]:
        state = "" if e["evidence_state"] in ("registered", "restored") else f", {e['evidence_state']}"
        where.append(f"document {e['evidence_document']}" + (f" p{e['evidence_page']}" if e["evidence_page"] else "")
                     + f" ({e['evidence_company']}{state})")
    if e["evidence_note"] is not None:
        where.append(f"note \"{e['evidence_note']}\"")
    org = f" ({e['organisation']})" if e["organisation"] else ""
    return (f"{review.LEDGERS[e['ledger']][1]} #{e['id']} {e['outcome']} on {e['reviewed_on']} by {e['contributor']}"
            f"{org}, capacity \"{e['capacity']}\", scope \"{e['scope']}\": \"{e['conclusion']}\"; evidence "
            + ", ".join(where) + ("" if e["latest"] else " (an earlier position of this contributor)")
            + ("" if e["binds"] else " (on an earlier version)") + _mark(e["evidence_deleted"], e["created_at"]))


def _disagreement_line(version: int, d: dict) -> str:
    return (f"company confirmation and auditor review disagree on version {version}: company "
            f"{', '.join(d['company'])}; auditor {', '.join(d['auditor'])}")


def _ledger_lines(v: dict, indent: str = "  ") -> list[str]:
    """Both ledgers of one version as two lists, then their disagreement."""
    lines = []
    for _, words, key in review.LEDGERS.values():
        lines.append(f"{indent}{words}s:" + ("" if v[key] else " none"))
        lines += [f"{indent}  {_entry_line(e)}" for e in v[key]]
    if v["disagreement"]:
        lines.append(indent + _disagreement_line(v["id"], v["disagreement"]))
    return lines


def _records_lines(v: dict, mark: dict | None = None, indent: str = "  ") -> list[str]:
    """The contributors' records of one version (correct.records_on): both ledgers when either has an entry, then the
    reviewer flags and the adjudications naming it. mark: the evidence-deleted marker of the version's document."""
    ledgers = _ledger_lines(v, indent) if any(v[k] for _, _, k in review.LEDGERS.values()) else []
    return [*ledgers, *(f"{indent}{_flag_text(f)}{_mark(mark, f['created_at'])}" for f in v["reviewer_flags"]),
            *(f"{indent}{_adjudication_text(a)}" for a in v["adjudications"])]


def cmd_review_record(args) -> None:
    r = review.record(_open(args), args.root, args.ledger, args.claim, args.version, args.outcome, args.scope,
                      args.conclusion, args.as_, args.capacity, args.evidence_doc, args.evidence_page,
                      args.evidence_note, args.date)
    c, e = r["claim"], r["entry"]
    lines = [f"Recorded {review.LEDGERS[e['ledger']][1]} #{e['id']} on version {c['version']} of claim {c['id']}"
             f" (document {c['document']}, company {c['company']}):", f"  {_entry_line(e)}"]
    if r["disagreement"]:
        lines.append("  " + _disagreement_line(c["version"], r["disagreement"]))
    _print(args, {"status": "ok", **r}, "\n".join([*lines, review.SELF_DECLARED]))


def cmd_review_list(args) -> None:
    r = review.listing(_open(args, write=False), args.claim)
    c = r["claim"]
    lines = [f"claim {c['id']}  document {c['document']} ({c['document_state']})  company {c['company']}  newest version"
             f" {c['version']}  {c['state']}{_mark(c['evidence_deleted'])}"]
    for v in r["versions"]:
        lines += [f"version {v['id']}" + ("" if v["binds"] else " (an earlier version: its entries do not bind)"),
                  *_ledger_lines(v)]
    _print(args, {"status": "ok", **r}, "\n".join([*lines, review.SELF_DECLARED]))


def cmd_review_pending(args) -> None:
    kinds = correct.pending(_open(args, write=False), args.company, args.doc)
    lines = [x for k in kinds for x in (f"{k['kind']}:", *(
        f"  claim {e['claim']} (document {e['document']}, {e['company']}) version {e['version']}: "
        f"{correct.entry_text(e['entry'])}\n    renew: {e['renew']}" for e in k["entries"]))]
    if any(k["kind"] in correct.E5 for k in kinds):
        lines.append(review.SELF_DECLARED)
    _print(args, {"status": "ok", "kinds": kinds}, "\n".join(lines) or "No claim needs renewed review.")
def _quoted(label: str, text) -> str:
    return f'; {label} "{text}"' if text is not None else ""


def _who_text(r: dict) -> str:
    return r["contributor"] + (f" ({r['organisation']})" if r["organisation"] else "")


def _adjudication_text(r: dict) -> str:
    """One adjudication row, its contributor text quoted and attributed (C5)."""
    counter = (f"; counter-evidence document {r['counter_document']}" + (f" p{r['counter_page']}" if r["counter_page"] else "")
               + f" ({r['counter_company']}, {r['evidence_state']})" if r["counter_document"] else "")
    return (f"adjudication #{r['id']} {adjudicate.STATES[r['state']]} on versions {r['low_version']} and {r['high_version']}"
            f" by {_who_text(r)}, capacity \"{r['capacity']}\": \"{r['rationale']}\"{_quoted('procedure', r['procedure'])}"
            f"{counter}{_quoted('counter-evidence note', r['counter_note'])}{_quoted('follow-up', r['follow_up'])}"
            f"{_quoted('closure reason', r['closure_reason'])}" + ("" if r["binds"] else " (on an earlier version)")
            + (f"; other document {r['other_document_state']}"
               if r.get("other_document_state", "registered") not in adjudicate.ACTIVE else "")
            + _mark(r["evidence_deleted"], r["created_at"]))


def _candidate_line(p: dict) -> str:
    what = (p["metric_key"] or f"unmapped: {p['label']}") + "  " + _boundary_of(p)
    return (f"{p['series_id']}  {p['company']}  {what}  {p['period_start']}..{p['period_end']}  {_side(p['a'])}  "
            f"{_side(p['b'])}  {p['adjudication_state']}")


def cmd_adjudicate_list(args) -> None:
    conn = _open(args, write=False)
    r = adjudicate.listed(conn, args.company, args.state, args.claim)
    lines = [x for p in _located(conn, r["candidates"])
             for x in (_candidate_line(p), *(f"  {_adjudication_text(a)}" for a in p["adjudications"]))]
    lines = lines or ["No candidates" + (" in this state." if args.state else " yet.")]
    if args.state:
        lines.append(f"{r['hidden']} candidates in other states hidden by --state {args.state}.")
    if r["earlier"]:
        lines.append("Adjudications of claims that are not a candidate now:")
        lines += [f"  claims {a['low_claim']} and {a['high_claim']}, now {a['pair_state'] or 'in no pair'}: "
                  f"{_adjudication_text(a)}" for a in r["earlier"]]
    _print(args, {"status": "ok", **r}, "\n".join([*lines, review.SELF_DECLARED]))


def cmd_adjudicate_record(args) -> None:
    r = adjudicate.record(_open(args), args.root, args.first, args.second, args.state, args.rationale, args.procedure,
                          args.as_, args.capacity, args.counter_doc, args.counter_page, args.counter_note, args.follow_up,
                          args.closure_reason)
    _print(args, {"status": "ok", **r}, "\n".join(
        [f"Recorded {_adjudication_text(r['adjudication'])}. The candidate is now {r['adjudication_state']}.",
         *([r["next"]] if r["next"] else []), review.SELF_DECLARED]))


def cmd_adjudicate_status(args) -> None:
    cs = adjudicate.status(_open(args, write=False), args.company)
    _print(args, {"status": "ok", "companies": cs}, "\n".join(
        f"{c['company']}: {c['candidates']} candidates, of which {c['unreviewed']} unreviewed, "
        + ", ".join(f"{c[k]} {v}" for k, v in adjudicate.STATES.items()) for c in cs) or "No candidates yet.")


def _flag_text(f: dict) -> str:
    return (f"reviewer flag #{f['id']} on claim {f['claim']} version {f['version']}: potential greenwashing concern "
            f"{f['decision']} by {_who_text(f)} (self-declared), capacity \"{f['capacity']}\": \"{f['rationale']}\""
            + ("" if f["latest"] else " (an earlier position)") + ("" if f["binds"] else " (on an earlier version)"))


def cmd_flag_raise(args) -> None:
    f = adjudicate.raise_flag(_open(args), args.claim, args.version, args.rationale, args.as_, args.capacity)
    _print(args, {"status": "ok", "flag": f}, f"Recorded {_flag_text(f)}.\n{review.SELF_DECLARED}")


def cmd_flag_withdraw(args) -> None:
    f = adjudicate.withdraw_flag(_open(args), args.claim, args.version, args.rationale, args.as_, args.capacity)
    _print(args, {"status": "ok", "flag": f}, f"Recorded {_flag_text(f)}.\n{review.SELF_DECLARED}")


def cmd_flag_list(args) -> None:
    fs = adjudicate.flags(_open(args, write=False), args.company, args.claim)
    _print(args, {"status": "ok", "flags": fs},
           "\n".join([*map(_flag_text, fs), review.SELF_DECLARED] if fs else ["No reviewer flags.", review.SELF_DECLARED]))


def _highlight_text(h: dict) -> str:
    """One highlight, the contributor's words quoted and attributed (C5); it is never a review outcome."""
    return (f"highlight #{h['id']} on version {h['claim_version']} by {_who_text(h)} (self-declared), capacity"
            f" \"{h['capacity']}\": \"{h['note']}\"" + ("" if h["latest"] else " (an earlier highlight of this contributor)")
            + ("" if h["binds"] else " (on an earlier version)") + _mark(h["evidence_deleted"], h["created_at"]))


def cmd_highlight_add(args) -> None:
    r = highlight.record(_open(args), args.claim, args.version, args.note, args.as_, args.capacity)
    c = r["claim"]
    _print(args, {"status": "ok", **r}, "\n".join(
        [f"Recorded {_highlight_text(r['entry'])} of claim {c['id']} (document {c['document']}, company {c['company']}).",
         review.SELF_DECLARED]))


def cmd_highlight_list(args) -> None:
    r = highlight.listing(_open(args, write=False), args.claim)
    c = r["claim"]
    lines = [f"claim {c['id']}  document {c['document']} ({c['document_state']})  company {c['company']}  newest version"
             f" {c['version']}  {c['state']}{_mark(c['evidence_deleted'])}"]
    for v in r["versions"]:
        lines += [f"version {v['id']}" + ("" if v["binds"] else " (an earlier version)") + ("" if v["highlights"] else
                                                                                           ": no highlights"),
                  *(f"  {_highlight_text(h)}" for h in v["highlights"])]
    _print(args, {"status": "ok", **r}, "\n".join([*lines, review.SELF_DECLARED]))


def _mapping_text(m: dict) -> str:
    cols = ", ".join(f"{r} {m[r]}" for r in sheet.ROLES if m[r])
    declared = [f"year end {m['year_end']}"] * bool(m["year_end"]) + [
        f"boundary {m['boundary_is']}" + (f" ({m['boundary_detail']})" if m["boundary_detail"] else "")] * bool(m["boundary_is"])
    return (f"mapping #{m['id']} by {m['contributor']} ({m['capacity']}): {cols}"
            + (f"; declared {', '.join(declared)} (proposals until gct infer accept)" if declared else ""))


def cmd_sheet_show(args) -> None:
    conn = _open(args, write=False)
    if registry.evidence_deleted(conn, args.doc):  # its file and mappings were cleared (story 4.5)
        raise registry.was_deleted(args.doc)
    ss = sheet.show(conn, args.root, args.doc)
    lines = []
    for s in ss:
        lines += [f"sheet {s['position']} {s['name']}: " + (_mapping_text(s["mapping"]) if s["mapping"] else sheet.NO_MAPPING),
                  "  row 1: " + " | ".join(s["header"]), *(f"  row {r['row']}: " + " | ".join(r["cells"]) for r in s["rows"])]
    _print(args, {"status": "ok", "document": args.doc, "sheets": ss}, "\n".join(lines) or "This document has no sheets.")


def cmd_sheet_map(args) -> None:
    cols = {r: getattr(args, r) for r in sheet.ROLES}
    m = sheet.map_sheet(_open(args), args.root, args.doc, args.sheet, cols, args.year_end, args.boundary_is,
                        args.boundary_detail, args.as_, args.capacity, args.rationale)
    _print(args, {"status": "ok", "mapping": m},
           f"Mapped sheet {m['sheet']} of document {m['document']}: {_mapping_text(m)}. "
           f"It applies from the next run of: gct extract {m['document']}")


def _contributor_line(c: dict) -> str:
    return f"{c['key']}  {c['name']}  {c['organisation'] or '-'}  version {c['version']}"


def cmd_contributor_add(args) -> None:
    c = missing.add_contributor(_open(args), args.key, args.name, args.organisation)
    _print(args, {"status": "ok", "contributor": c}, f"Added contributor {_contributor_line(c)}.")


def cmd_contributor_edit(args) -> None:
    c = missing.edit_contributor(_open(args), args.key, args.name, args.organisation)
    _print(args, {"status": "ok", "contributor": c}, f"Contributor is now {_contributor_line(c)}. Earlier records keep their version.")


def cmd_contributor_list(args) -> None:
    cs = missing.contributors(_open(args, write=False))
    _print(args, {"status": "ok", "contributors": cs},
           "\n".join(map(_contributor_line, cs)) or "No contributors yet. Add one with: gct contributor add KEY --name NAME")


def _reason_line(r: dict) -> str:
    if r["reason"] == missing.NO_ACTIVE:
        return f"  {r['type']}: {r['reason']} ({r['count']} declared)"
    return (f"  {r['type']}: {r['count']} {'documents' if r['type'] == 'document' else 'pages'}, {r['reason']}"
            + (f" ({', '.join(r['pages'])})" if "pages" in r else ""))


def _expect_lines(e: dict, declared=()) -> list[str]:
    """declared: (id, state) of the declared documents, given when none of them is active."""
    by = {}
    for i, state in declared:
        by.setdefault(state, []).append(str(i))
    docs = ", ".join(map(str, e["documents"])) if e["documents"] or not declared else (
        "none active (" + "; ".join(f"{s}: {', '.join(ids)}" for s, ids in by.items()) + ")")
    head = f"{e['id']}  {e['company']}  \"{e['metric_text']}\"  {e['period_label'] or '-'}  documents {docs}"
    if e["found"]:
        lines = [f"{head}  found: {len(e['claims'])} claims"]
    else:
        lines = [f"{head}  {e['state']}"]
        lines += [_reason_line(r) for r in e["reasons"] if r["type"] != "confirmation"]
        lines += [f"  {a['type']}: {a['count']} pages {a['accepted']}" for a in e["accepted"]]
    c = e["confirmation"]
    if c:
        why = next((r["reason"] for r in e["reasons"] if r["type"] == "confirmation"), "the figure is found now")
        lines.append(f"  gap confirmation #{c['id']} by {c['contributor']} ({c['capacity']}): "
                     + (c["rationale"] if c["current"] else f"{why}, not current")
                     + _mark(c["evidence_deleted"], c["created_at"]))
    return lines


def cmd_expect_add(args) -> None:
    e = missing.add_expectation(_open(args), args.root, args.company, args.metric, args.period, args.doc)
    _print(args, {"status": "ok", "expectation": e}, "\n".join(["Added expectation:", *_expect_lines(e)]))


LITERAL = ("Matching uses the literal wording, so the same figure under different wording can still exist. A gap"
           " confirmation is the contributor's own judgment, not a conclusion GCT draws from absent wording.")


def cmd_expect_list(args) -> None:
    conn = _open(args, write=False)
    es = missing.expectations(conn, args.root, args.company)
    text = "\n".join([*(line for e in es for line in _expect_lines(
        e, () if e["documents"] else [(i, registry.show_document(conn, i)["state"])
                                      for i in missing.declared(conn, e["id"])])), LITERAL] if es else [])
    _print(args, {"status": "ok", "expectations": es},
           text or 'No expectations yet. Add one with: gct expect add --company NAME --metric "WORDING"')


def cmd_pages_accept(args) -> None:
    a = missing.accept_pages(_open(args), args.root, args.doc, args.pages, args.type, args.as_, args.capacity, args.rationale)
    _print(args, {"status": "ok", **a}, f"Document {a['document']}, {a['type']}: pages {', '.join(map(str, a['pages']))} "
                                         f"{a['accepted']}. This is an acceptance, not a check.")


def cmd_gap_confirm(args) -> None:
    e = missing.confirm_gap(_open(args), args.root, args.item, args.as_, args.capacity, args.rationale)
    _print(args, {"status": "ok", "expectation": e}, "\n".join(["Recorded the gap confirmation:", *_expect_lines(e), (
        f"GCT looked only for the exact wording \"{e['metric_text']}\" on the pages. A reworded or abbreviated label"
        " (for example \"Scope-1\" for \"scope 1 emissions\") is not caught, so check the pages yourself.")]))


def _version_line(v: dict) -> str:
    return f"version {v['version']} ({v['companies']} companies, {v['documents']} documents, built {v['built_at']})"


def _publish(args, command: str, action) -> dict:
    conn = _open(args)
    with runs.run(conn, command) as run_id:
        v = action(conn, args.root)
        runs.event(conn, run_id, "output", stage="publish", item=str(v["version"]))
    return v


def cmd_publish_build(args) -> None:
    v = _publish(args, "publish build", published.build)
    _print(args, {"status": "ok", **v}, f"Built {_version_line(v)}. It is now current.")


def cmd_publish_restore(args) -> None:
    v = _publish(args, "publish restore", published.restore)
    _print(args, {"status": "ok", **v}, f"Went back to {_version_line(v)}. It is now current.")


def cmd_publish_status(args) -> None:
    st = published.status(_open(args, write=False), args.root)
    if st["current_version"] is None:
        text = "No published version yet. Create one with: gct publish build"
    else:
        text = (
            f"Current: version {st['current_version']} ({st['companies']} companies, {st['documents']} documents, "
            f"built {st['built_at']}, history mark {st['history_mark']})\n"
            f"Previous: {st['previous_version'] or 'none'}\n"
            f"Out of date: {'yes, run gct publish build' if st['stale'] else 'no'}\n"
            f"Versions on disk: {', '.join(map(str, st['files'])) or 'none'}"
        )
    _print(args, {"status": "ok", **st}, text)


def _run_line(r: dict) -> str:
    return f"{r['id']}  {r['started_at']}  {r['command']}  {r['outcome']}"


def cmd_run_list(args) -> None:
    rs = runs.list_runs(_open(args, write=False))
    _print(args, {"status": "ok", "runs": rs}, "\n".join(_run_line(r) for r in rs) or "No runs yet.")


def cmd_run_show(args) -> None:
    r = runs.show_run(_open(args, write=False), args.id)
    lines = [
        f"Run {r['id']}: {r['command']} (gct {r['gct_version']})",
        f"Started: {r['started_at']}",
        f"Finished: {r['finished_at'] or 'not finished'}",
        f"Outcome: {r['outcome']}",
        f"Methods: {', '.join(r['methods']) or 'none'}",
        f"Failures: {r['failures']}",
        f"Retries: {r['retries']}",
        f"Estimated cost: {r['cost_estimated']}",
        f"Confirmed cost: {r['cost_confirmed']}",
        f"Outputs: {', '.join(r['outputs']) or 'none'}",
        "Events:",
    ]
    for e in r["events"]:
        detail = "  ".join(f"{k.replace('_', ' ')}: {e[k]}" for k in runs.EVENT_COLUMNS[3:] if e[k] is not None)
        lines.append(f"  {e['at']}  {e['kind']}  {detail}".rstrip())
    _print(args, {"status": "ok", **r}, "\n".join(lines))


AGAIN = {"read": "Run gct read again with the same documents.",
         "extract": "Run gct extract again with the same documents.",
         "link": "Run gct link again with the same documents.",
         "infer": "Run gct infer again with the same documents.",
         "match": "Run gct match again with the same documents.",
         "sheet": "Run gct extract again with the same documents.",
         "doc add": "Run gct doc add again with the same files."}
STAGES = {"read": (read, _read_out), "extract": (extract, _extract_out), "link": (link, _link_out),
          "infer": (infer, _infer_out), "match": (match, _match_out), "sheet": (sheet, _extract_out)}


def _of_run(conn, n: int, verb: str) -> dict:
    """Run n, which must be a read, extract, link, infer, match, sheet or doc add run."""
    r = runs.show_run(conn, n)
    if r["command"] not in AGAIN:
        raise GctError(layout.REFUSED, f"Run {n} was a {r['command']} run. Only read, extract, link, infer, match, sheet and doc add runs can be {verb}.",
                       "See the runs with: gct run list")
    return r


def _selection(conn, r: dict) -> dict:
    sel = runs.selection(conn, r["id"])
    if sel is None:
        raise GctError(layout.REFUSED, f"Run {r['id']} has no record of what it was given, so it cannot be replayed.",
                       AGAIN[r["command"]])
    return sel


def _replay(args, conn, r: dict, sel: dict, note: str, head: str) -> int:
    """Run the recorded selection of a read, extract, link, infer or doc add run again in a new run."""
    if r["command"] in STAGES:
        stage, out = STAGES[r["command"]]
        run_id, docs = getattr(stage, r["command"])(conn, args.root, sel["ids"], sel["company"], [note])
        return out(args, docs, head.format(run_id), {"run_id": run_id, "of_run": r["id"]})
    run_id, items = intake.add(conn, args.root, notes=[note], **sel)
    return _doc_add_out(args, items, head=head.format(run_id), extra={"run_id": run_id, "of_run": r["id"]})


def cmd_run_resume(args) -> int:
    conn = _open(args)
    r = _of_run(conn, args.id, "resumed")
    if r["outcome"] == "ok":
        raise GctError(layout.REFUSED, f"Run {args.id} finished; nothing to resume.",
                       f"Retry its failed items, if any, with: gct run retry {args.id}")
    return _replay(args, conn, r, _selection(conn, r), f"resumes run {args.id}", f"Run {{}} resumes run {args.id}.")


def cmd_run_retry(args) -> int:
    conn = _open(args)
    r = _of_run(conn, args.id, "retried")
    note, head = f"retries failed items of run {args.id}", f"Run {{}} retries the failed items of run {args.id}."
    stage, out = STAGES.get(r["command"], (intake, None))
    wanted = stage.failed(conn, args.id)
    if not wanted:
        key = "documents" if out else "items"
        _print(args, {"status": "ok", "run_id": None, "of_run": args.id, key: []}, f"Run {args.id} has no failed items.")
        return 0
    if out:
        run_id, docs = stage.retry(conn, args.root, wanted, [note])
        return out(args, docs, head.format(run_id), {"run_id": run_id, "of_run": args.id})
    return _replay(args, conn, r, {**_selection(conn, r), "sources": wanted}, note, head)


def cmd_approve_spend(args) -> None:
    conn = _open(args)
    policy.set_cap(conn, args.amount)
    spent = policy.spent(conn)
    _print(args, {"status": "ok", "cap": args.amount, "spent": spent},
           f"Estimated spending limit set to {policy.money(args.amount)} (estimated spend so far {policy.money(spent)}).")


def cmd_approve_transfer(args) -> None:
    conn = _open(args)
    adapter = adapters.get(args.name)
    granted = not args.revoke
    policy.set_transfer(conn, adapter, granted)
    may = "may" if granted else "may no longer"
    _print(args, {"status": "ok", "provider": args.name, "granted": granted}, f"{args.name} {may} receive private content.")


def cmd_approve_list(args) -> None:
    conn = _open(args, write=False)
    cap, spent = policy.cap(conn), policy.spent(conn)
    states = {a.name: (a, policy.transfer_state(conn, a)) for a in adapters.load().values()}
    rows = [{"name": a.name, "external": a.external, "paid": a.paid, "transfer_granted": st == "granted"}
            for a, st in states.values()]
    head = ("No estimated spending limit. Paid work is off." if cap is None
            else f"Estimated spending limit {policy.money(cap)}, estimated spend {policy.money(spent)}")
    lines = [f"{r['name']}  {'external' if r['external'] else 'local'}  {'paid' if r['paid'] else 'free'}  "
             f"transfer {TRANSFER[states[r['name']][1]]}" for r in rows]
    _print(args, {"status": "ok", "cap": cap, "spent": spent, "adapters": rows}, "\n".join([head, *lines]))


def cmd_model_list(args) -> None:
    path = adapters.path()
    rows = [{"name": a.name, "provider": a.provider, "model": a.model, "base_url": a.base_url, "external": a.external,
             "paid": a.paid, "price_in": a.price_in, "price_out": a.price_out, "api_key_env": a.api_key_env,
             "key_set": bool(a.api_key_env and os.environ.get(a.api_key_env))} for a in adapters.load().values()]

    def key(r):
        return f"key {r['api_key_env']} {'set' if r['key_set'] else 'not set'}" if r["api_key_env"] else "no key"

    text = "\n".join(
        f"{r['name']}  {r['provider']}  {r['model']}  {r['base_url']}  {'external' if r['external'] else 'local'}  "
        f"{'paid' if r['paid'] else 'free'}  {key(r)}" for r in rows
    ) or f"No model adapters configured (looked for {path}). Rung 1 reading needs none."
    _print(args, {"status": "ok", "path": str(path), "adapters": rows}, text)


TRANSFER = {"granted": "granted", "not granted": "not granted",
            "elsewhere": "granted for a different endpoint or model, approve it again"}


def money(value: str) -> float:
    try:
        amount = float(value)
    except ValueError:
        amount = -1.0
    if not math.isfinite(amount) or amount < 0:
        raise argparse.ArgumentTypeError(f"{value} is not an amount in USD of 0 or more")
    return amount


def cmd_workspace_status(args) -> None:
    conn = _open(args, write=False)
    current = published.current_version(conn, args.root)
    rs = runs.list_runs(conn)
    st = {
        "schema_version": conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0],
        "gct_version": __version__,
        "companies": len(registry.list_companies(conn)),
        "documents": len(registry.list_documents(conn)),
        "published_version": current[0] if current else None,
        "runs": len(rs),
        "latest_run_outcome": rs[0]["outcome"] if rs else None,
    }
    text = (
        f"Schema version: {st['schema_version']}\n"
        f"gct version: {st['gct_version']}\n"
        f"Companies: {st['companies']}\n"
        f"Documents: {st['documents']}\n"
        f"Published version: {st['published_version'] or 'none'}\n"
        f"Runs: {st['runs']}\n"
        f"Latest run: {st['latest_run_outcome'] or 'none'}"
    )
    _print(args, {"status": "ok", **st}, text)


def _measure_line(t: dict) -> str:
    where = " ".join(str(t[k]) for k in ("company", "document_type", "kind") if k in t)
    return (f"{where}: Found {t['found_text']}, Partial {t['partial']}, Missed {t['missed']}, "
            f"value and unit on the gold page {t['value_and_unit_on_gold_page']}, cannot be Found under rule 1 "
            f"{t['ceiling']['rows']}/{t['ceiling']['of']}; {t['verdict']}" + ("; re-adjudicate" if t["re_adjudicate"] else ""))


def cmd_measure_g2(args) -> None:
    r = g2.measure(args.workspace, args.gold, args.seed, args.against)
    d, delta = r["delta"], []
    if d:
        p = d["previous"]
        delta = [f"{d['attributed_to'].capitalize()} delta from run {p['run_id']} (scorer version {p['scorer_version']}, "
                 f"published version {p['published_version']}): "
                 + "; ".join(f"{t['company']} {t['kind']} Found {t['before']} -> {t['after']} ({t['found_change']:+d})"
                             for t in d["types"])]
    lines = [f"published version {r['published_version']}, gct commit {r['gct_commit']}, scorer version {r['scorer_version']}",
             *delta,
             f"Gold {r['gold']['version']} commit {r['gold']['commit']}. {r['headline']}.",
             *map(_measure_line, r["types"]),
             *(f"{x['row']}: {x['state']}" for x in r["runs"]),
             f"Adjudication seed {r['adjudication']['seed']}: {len(r['adjudication']['missed'])} Missed rows, "
             f"{sum(len(s['ids']) for s in r['adjudication']['found_sample'])} sampled Found rows.",
             *(_measure_line(a) for a in r["aggregate"]),
             f"Report: {r['report_path']}"]
    _print(args, r, "\n".join(lines))


def cmd_serve(args) -> None:
    _open(args, write=False).close()  # locate and upgrade the workspace like every other command
    srv = server.serve(args.root, args.port)
    _print(args, {"status": "ok", "url": srv.url, "port": srv.port},
           f"Serving {args.root} at {srv.url}\nOnly this computer can reach it. Press Ctrl-C to stop.")
    sys.stdout.flush()
    if not args.no_open:
        webbrowser.open(srv.url)
    try:
        srv.wait()
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()


def build_parser() -> argparse.ArgumentParser:
    json_flag = argparse.ArgumentParser(add_help=False)
    json_flag.add_argument("--json", action="store_true", help="print one JSON object")
    common = argparse.ArgumentParser(add_help=False, parents=[json_flag])
    common.add_argument("--workspace", metavar="PATH", help="workspace folder (default: GCT_WORKSPACE, else search upward)")

    parser = argparse.ArgumentParser(prog="gct", description="GoCarbonTracker workspace tools.")
    top = parser.add_subparsers(dest="group", required=True, metavar="{workspace,company,doc,read,extract,link,infer,match,series,restate,review,adjudicate,flag,claims,sheet,correct,contributor,expect,pages,gap,publish,run,approve,model,measure,serve}")

    def group(name, help_):
        return top.add_parser(name, help=help_).add_subparsers(dest="command", required=True)

    workspace = group("workspace", "the workspace folder")
    init = workspace.add_parser("init", parents=[json_flag], help="create a workspace folder")
    init.add_argument("path")
    init.set_defaults(func=cmd_init)
    workspace.add_parser("status", parents=[common], help="show what the workspace holds").set_defaults(func=cmd_workspace_status)

    company = group("company", "companies")
    add = company.add_parser("add", parents=[common], help="add a company")
    add.add_argument("name")
    add.add_argument("--sector-ref")
    add.add_argument("--sector-version")
    add.set_defaults(func=cmd_company_add)
    company.add_parser("list", parents=[common], help="list companies").set_defaults(func=cmd_company_list)

    doc = group("doc", "documents")
    add = doc.add_parser("add", parents=[common], help="register documents from files, folders or URLs")
    add.add_argument("sources", nargs="+", metavar="SOURCE", help="a file, a folder (its direct children) or an http(s) URL")
    add.add_argument("--company", required=True)
    add.add_argument("--kind", choices=("report", "evidence"), default="report")
    add.add_argument("--privacy", choices=("private", "shareable"), default="private")
    add.add_argument("--name", help="logical name (default: the file's base name)")
    add.add_argument("--source", help="where the file came from, free text (a URL stores the URL)")
    add.add_argument("--plan", action="store_true", help="show what would happen to each item and store nothing")
    add.set_defaults(func=cmd_doc_add)
    lst = doc.add_parser("list", parents=[common], help="list documents")
    lst.add_argument("--company")
    lst.add_argument("--active", action="store_true", help="hide archived documents and say how many were hidden")
    lst.set_defaults(func=cmd_doc_list)
    show = doc.add_parser("show", parents=[common], help="show one document")
    show.add_argument("id", type=int)
    show.set_defaults(func=cmd_doc_show)
    pages = doc.add_parser("pages", parents=[common], help="show how each page of one document was read")
    pages.add_argument("id", type=int)
    pages.set_defaults(func=cmd_doc_pages)
    arc = doc.add_parser("archive", parents=[common], help="take a document out of every active output; its file and history are kept")
    arc.add_argument("id", type=int)
    arc.add_argument("--plan", action="store_true", help="show what would drop out of the active outputs and store nothing")
    arc.add_argument("--as", dest="as_", metavar="KEY", help="the contributor making this record (needed without --plan)")
    arc.add_argument("--capacity", help="the capacity you act in, as you describe it (needed without --plan)")
    arc.add_argument("--rationale", help="why (needed without --plan)")
    arc.set_defaults(func=cmd_doc_archive)
    rst = doc.add_parser("restore", parents=[common], help="bring an archived document back into the active outputs")
    rst.add_argument("id", type=int)
    rst.add_argument("--as", dest="as_", required=True, metavar="KEY", help="the contributor making this record")
    rst.add_argument("--capacity", required=True, help="the capacity you act in, as you describe it")
    rst.add_argument("--rationale", required=True, help="why")
    rst.set_defaults(func=cmd_doc_restore)
    dele = doc.add_parser("delete", parents=[common],
                          help="remove a document's content for good; without --confirm, show what goes and what stays")
    dele.add_argument("id", type=int)
    dele.add_argument("--confirm", metavar="TOKEN", help="the confirmation token the plan prints")
    dele.add_argument("--as", dest="as_", metavar="KEY", help="the contributor making this record (needed with --confirm)")
    dele.add_argument("--capacity", help="the capacity you act in (needed with --confirm); do not quote the document")
    dele.add_argument("--rationale", help="why (needed with --confirm); do not quote the document")
    dele.set_defaults(func=cmd_doc_delete)

    rd = top.add_parser("read", parents=[common], help="read every page of PDF documents (text, words, tables)")
    rd.add_argument("ids", nargs="*", type=int, metavar="ID", help="documents to read (default: every active document)")
    rd.add_argument("--company", help="only this company's documents")
    rd.set_defaults(func=cmd_read)

    ex = top.add_parser("extract", parents=[common], help="list the figures on read pages with fixed rules (no model)")
    ex.add_argument("ids", nargs="*", type=int, metavar="ID", help="documents to extract (default: every active document)")
    ex.add_argument("--company", help="only this company's documents")
    ex.set_defaults(func=cmd_extract)

    ln = top.add_parser("link", parents=[common], help="check again whether each claim's source location reproduces its figure")
    ln.add_argument("ids", nargs="*", type=int, metavar="ID", help="documents to check (default: every active document)")
    ln.add_argument("--company", help="only this company's documents")
    ln.set_defaults(func=cmd_link)

    def attributed(p):
        p.add_argument("--as", dest="as_", required=True, metavar="KEY", help="the contributor making this record")
        p.add_argument("--capacity", required=True, help="the capacity you act in, as you describe it")
        p.add_argument("--rationale", required=True, help="why")

    inf = top.add_parser("infer", parents=[common], help="propose each claim's period and boundary from the report's own wording")
    inf.add_argument("--doc", type=int, metavar="ID", help="only this document (default: every active document)")
    inf.add_argument("--company", help="only this company's documents")
    inf.set_defaults(func=cmd_infer)
    sub = inf.add_subparsers(dest="command", metavar="{bases,scope,groups,accept,resolve,reject}")
    bases = sub.add_parser("bases", parents=[common], help="list the period and boundary statements found")
    bases.add_argument("--doc", type=int, metavar="ID")
    bases.set_defaults(func=cmd_infer_bases)
    scope = sub.add_parser("scope", parents=[common], help="declare the pages a boundary statement covers")
    scope.add_argument("basis", type=int, metavar="BASIS")
    scope.add_argument("--pages", required=True, metavar="FIRST-LAST")
    groups = sub.add_parser("groups", parents=[common], help="list claims inferred the same way to the same result")
    groups.add_argument("--doc", type=int, metavar="ID")
    groups.add_argument("--state", choices=("proposed", "unresolved"))
    groups.set_defaults(func=cmd_infer_groups)
    accept = sub.add_parser("accept", parents=[common], help="accept every proposed inference of one group")
    accept.add_argument("group", metavar="GROUP")
    resolve = sub.add_parser("resolve", parents=[common], help="set one claim's period or boundary yourself")
    resolve.add_argument("claim", type=int, metavar="CLAIM")
    resolve.add_argument("--field", required=True, choices=infer.FIELDS)
    resolve.add_argument("--kind", choices=infer.KINDS)
    resolve.add_argument("--start", metavar="YYYY-MM-DD")
    resolve.add_argument("--end", metavar="YYYY-MM-DD")
    resolve.add_argument("--boundary", choices=infer.BOUNDARIES)
    resolve.add_argument("--detail", metavar="TEXT", help="the entity wording")
    reject = sub.add_parser("reject", parents=[common], help="reject a group's or one claim's proposal; it stays unknown")
    reject.add_argument("group", nargs="?", metavar="GROUP")
    reject.add_argument("--claim", type=int, metavar="CLAIM")
    reject.add_argument("--field", choices=infer.FIELDS)
    for p, func in ((scope, cmd_infer_scope), (accept, cmd_infer_accept), (resolve, cmd_infer_resolve),
                    (reject, cmd_infer_reject)):
        attributed(p)
        p.set_defaults(func=func)

    mt = top.add_parser("match", parents=[common], help="give each claim a metric key and unit, then link it across periods and reports")
    mt.add_argument("--doc", type=int, metavar="ID", help="only this document (default: every active document)")
    mt.add_argument("--company", help="only this company's documents")
    mt.set_defaults(func=cmd_match)
    sub = mt.add_subparsers(dest="command", metavar="{metrics,review,link,unlink,status}")
    sub.add_parser("metrics", parents=[common], help="print the metric list and unit table with their versions").set_defaults(func=cmd_match_metrics)
    review = sub.add_parser("review", parents=[common], help="list the uncertain items: claims that could join a series after review")
    review.add_argument("--company")
    review.add_argument("--reason", choices=(match.BOUNDARY_UNKNOWN, match.UNIT_UNKNOWN, match.NOT_CONVERTIBLE))
    review.set_defaults(func=cmd_match_review)
    for name, help_, func in (("link", "put an uncertain claim in a candidate series (reviewed, not comparable)", cmd_match_link),
                              ("unlink", "take a candidate series off a claim's review queue", cmd_match_unlink)):
        p = sub.add_parser(name, parents=[common], help=help_)
        p.add_argument("claim", type=int, metavar="CLAIM")
        p.add_argument("--series", required=True, metavar="SERIES")
        attributed(p)
        p.set_defaults(func=func)
    st = sub.add_parser("status", parents=[common], help="counts per company: mapped, series, same-period sets, uncertain, not matchable")
    st.add_argument("--company")
    st.set_defaults(func=cmd_match_status)

    series = group("series", "a metric over reporting periods")
    lst = series.add_parser("list", parents=[common], help="one line per series with its latest period")
    lst.add_argument("--company")
    lst.add_argument("--metric", metavar="KEY", help="only this metric key (see gct match metrics)")
    lst.set_defaults(func=cmd_series_list)
    show = series.add_parser("show", parents=[common], help="the latest period of one series, or every period with --all")
    show.add_argument("series", metavar="SERIES")
    show.add_argument("--all", action="store_true", help="every period, oldest first")
    show.set_defaults(func=cmd_series_show)

    rs = group("restate", "pairs of figures for one metric, period and boundary: same value, restatement or conflict")
    lst = rs.add_parser("list", parents=[common], help="one line per pair of a same-period set, with its state")
    lst.add_argument("--company")
    lst.add_argument("--state", choices=tuple(restate.FILTERS), help="only pairs in this state (the rest are counted)")
    lst.set_defaults(func=cmd_restate_list)
    show = rs.add_parser("show", parents=[common], help="the pairs of one claim and every record on both versions")
    show.add_argument("claim", type=int, metavar="CLAIM")
    show.set_defaults(func=cmd_restate_show)
    for name, help_, func in (("record", "record a restatement cited from the restated figure's document", cmd_restate_record),
                              ("withdraw", "withdraw the current restatement record of a pair", cmd_restate_withdraw)):
        p = rs.add_parser(name, parents=[common], help=help_)
        p.add_argument("--original", type=int, required=True, metavar="CLAIM")
        p.add_argument("--restated", type=int, required=True, metavar="CLAIM")
        if name == "record":
            p.add_argument("--page", type=int, required=True, metavar="N", help="page of the restated figure's document")
            p.add_argument("--quote", required=True, metavar="TEXT", help="the line exactly as printed on that page")
        attributed(p)
        p.set_defaults(func=func)

    rv = group("review", "company confirmations and auditor reviews of a claim version (self-declared, never GCT's own)")
    for ledger, help_ in (("company", "record a company confirmation on a current claim's newest version"),
                          ("auditor", "record an auditor review on a current claim's newest version")):
        p = rv.add_parser(ledger, parents=[common], help=help_)
        p.add_argument("claim", type=int, metavar="CLAIM")
        p.add_argument("--version", type=int, required=True, metavar="V", help="the claim's newest version, as you saw it")
        p.add_argument("--outcome", required=True, metavar="accepted|rejected|disputed")
        p.add_argument("--scope", required=True, metavar="TEXT", help="what you looked at, in your words")
        p.add_argument("--conclusion", required=True, metavar="TEXT", help="your conclusion, in your words")
        p.add_argument("--as", dest="as_", required=True, metavar="KEY", help="the contributor making this record")
        p.add_argument("--capacity", required=True, help="the capacity you act in, as you describe it")
        p.add_argument("--evidence-doc", type=int, metavar="ID", help="a workspace document you relied on")
        p.add_argument("--evidence-page", type=int, metavar="N", help="its page (PDF only)")
        p.add_argument("--evidence-note", metavar="TEXT", help="evidence outside the workspace, or a sheet and cell")
        p.add_argument("--date", metavar="YYYY-MM-DD", help="the day of your review (default: today)")
        p.set_defaults(func=cmd_review_record, ledger=ledger)
    lst = rv.add_parser("list", parents=[common], help="every version of one claim with both ledgers' entries")
    lst.add_argument("claim", type=int, metavar="CLAIM")
    lst.set_defaults(func=cmd_review_list)
    pend = rv.add_parser("pending", parents=[common],
                         help="claims whose newest version lost a record made on an earlier one, and how to renew it")
    pend.add_argument("--company")
    pend.add_argument("--doc", type=int, metavar="ID")
    pend.set_defaults(func=cmd_review_pending)
    adj = group("adjudicate", "inconsistency candidates (unresolved conflicts) and what a reviewer recorded about them")
    lst = adj.add_parser("list", parents=[common], help="each candidate with its state and every adjudication of its claims")
    lst.add_argument("--company")
    lst.add_argument("--state", choices=tuple(adjudicate.FILTERS), help="only candidates in this state (the rest are counted)")
    lst.add_argument("--claim", type=int, metavar="CLAIM", help="only candidates and adjudications naming this claim")
    lst.set_defaults(func=cmd_adjudicate_list)
    rec = adj.add_parser("record", parents=[common], help="record what the difference between the two figures is")
    rec.add_argument("first", type=int, metavar="A", help="a claim of the candidate")
    rec.add_argument("second", type=int, metavar="B", help="the other claim")
    rec.add_argument("--state", required=True, metavar="STATE",
                     help=f"one of {', '.join(adjudicate.CHOICES)}; a restatement is recorded with gct restate record")
    rec.add_argument("--procedure", required=True, metavar="TEXT", help="how you checked")
    rec.add_argument("--counter-doc", type=int, metavar="ID", help="a document holding the counter-evidence")
    rec.add_argument("--counter-page", type=int, metavar="N", help="its page")
    rec.add_argument("--counter-note", metavar="TEXT", help="where the counter-evidence is, when not a page")
    rec.add_argument("--follow-up", metavar="TEXT")
    rec.add_argument("--closure-reason", metavar="TEXT")
    attributed(rec)
    rec.set_defaults(func=cmd_adjudicate_record)
    st = adj.add_parser("status", parents=[common], help="candidates per company and how many are in each state")
    st.add_argument("--company")
    st.set_defaults(func=cmd_adjudicate_status)

    flag = group("flag", "reviewer flags: a potential greenwashing concern a reviewer raised on one claim version")
    for name, help_, func in (("raise", "raise a potential greenwashing concern on a claim's newest version", cmd_flag_raise),
                              ("withdraw", "withdraw your flag on a claim's newest version", cmd_flag_withdraw)):
        p = flag.add_parser(name, parents=[common], help=help_)
        p.add_argument("claim", type=int, metavar="CLAIM")
        p.add_argument("--version", type=int, required=True, metavar="V", help="the claim's newest version, as you saw it")
        attributed(p)
        p.set_defaults(func=func)
    lst = flag.add_parser("list", parents=[common], help="every reviewer flag, oldest first")
    which = lst.add_mutually_exclusive_group()
    which.add_argument("--company")
    which.add_argument("--claim", type=int, metavar="CLAIM")
    lst.set_defaults(func=cmd_flag_list)

    hl = group("highlight", "highlights: a contributor's note on a claim version (never a confirmation or review outcome)")
    add = hl.add_parser("add", parents=[common], help="highlight a current claim's newest version with a short note")
    add.add_argument("claim", type=int, metavar="CLAIM")
    add.add_argument("--version", type=int, required=True, metavar="V", help="the claim's newest version, as you saw it")
    add.add_argument("--note", required=True, metavar="TEXT", help="why you highlight it, in your words")
    add.add_argument("--as", dest="as_", required=True, metavar="KEY", help="the contributor making this record")
    add.add_argument("--capacity", required=True, help="the capacity you act in, as you describe it")
    add.set_defaults(func=cmd_highlight_add)
    lst = hl.add_parser("list", parents=[common], help="every version of one claim with its highlights")
    lst.add_argument("claim", type=int, metavar="CLAIM")
    lst.set_defaults(func=cmd_highlight_list)

    claims = group("claims", "figures extracted from documents")
    lst = claims.add_parser("list", parents=[common], help="list one document's claims with their source location")
    lst.add_argument("--doc", type=int, required=True, metavar="ID")
    lst.add_argument("--state", choices=tuple(correct.STATES), help="only claims in this state")
    lst.set_defaults(func=cmd_claims_list)
    hist = claims.add_parser("history", parents=[common], help="every version of one claim and what was recorded on it")
    hist.add_argument("claim", type=int, metavar="CLAIM")
    hist.set_defaults(func=cmd_claims_history)

    sheets = group("sheet", "internal-evidence spreadsheets (CSV, XLSX): sheets and column mappings")
    show = sheets.add_parser("show", parents=[common], help="each sheet's header row, first rows and current mapping")
    show.add_argument("doc", type=int, metavar="DOC")
    show.set_defaults(func=cmd_sheet_show)
    mp = sheets.add_parser("map", parents=[common], help="say once which column of a sheet holds what (confirms no value)")
    mp.add_argument("doc", type=int, metavar="DOC")
    mp.add_argument("--sheet", required=True, metavar="NAME", help="the sheet name as gct sheet show prints it")
    mp.add_argument("--metric", required=True, metavar="COL", help="a header exactly as printed in row 1")
    mp.add_argument("--value", metavar="COL", help="the column holding the figures (required)")
    for role in sheet.ROLES[2:]:
        mp.add_argument(f"--{role}", metavar="COL")
    mp.add_argument("--year-end", metavar="MM-DD", help="the fiscal year end the period column uses (a proposal)")
    mp.add_argument("--boundary-is", choices=infer.BOUNDARIES, help="the reporting boundary of this sheet (a proposal)")
    mp.add_argument("--boundary-detail", metavar="TEXT")
    attributed(mp)
    mp.set_defaults(func=cmd_sheet_map)

    cor = top.add_parser("correct", parents=[common], help="correct a current claim's figure (a new version; earlier ones stay)")
    cor.add_argument("claim", type=int, metavar="CLAIM")
    cor.add_argument("--value", metavar="TEXT", help="the figure as printed")
    cor.add_argument("--unit", metavar="TEXT")
    cor.add_argument("--metric", metavar="TEXT", help="the metric wording")
    cor.add_argument("--period-label", metavar="TEXT", help="the period label as printed")
    attributed(cor)
    cor.set_defaults(func=cmd_correct)

    contrib = group("contributor", "people who make review records")
    add = contrib.add_parser("add", parents=[common], help="add a contributor")
    add.add_argument("key")
    add.add_argument("--name", required=True)
    add.add_argument("--organisation")
    add.set_defaults(func=cmd_contributor_add)
    edit = contrib.add_parser("edit", parents=[common], help="change a contributor (a new version; earlier records keep theirs)")
    edit.add_argument("key")
    edit.add_argument("--name")
    edit.add_argument("--organisation")
    edit.set_defaults(func=cmd_contributor_edit)
    contrib.add_parser("list", parents=[common], help="list contributors").set_defaults(func=cmd_contributor_list)

    expect = group("expect", "figures you expect a company to report")
    add = expect.add_parser("add", parents=[common], help="declare an expected figure by its wording")
    add.add_argument("--company", required=True)
    add.add_argument("--metric", required=True, metavar="TEXT", help="wording a claim's metric must contain")
    add.add_argument("--period", metavar="LABEL", help="period label exactly as printed")
    add.add_argument("--doc", type=int, nargs="+", default=[], metavar="ID", help="documents to look in (default: the company's active reports)")
    add.set_defaults(func=cmd_expect_add)
    lst = expect.add_parser("list", parents=[common], help="list expectations: found, or why missing")
    lst.add_argument("--company")
    lst.set_defaults(func=cmd_expect_list)

    pages_ = group("pages", "page review")
    accept = pages_.add_parser("accept", parents=[common], help="accept pages for a content type that no check covers")
    accept.add_argument("--doc", type=int, required=True, metavar="ID")
    accept.add_argument("--pages", required=True, metavar="SPEC", help="for example 3, 1-4 or 1,3-5")
    accept.add_argument("--type", required=True, choices=missing.TYPES)
    attributed(accept)
    accept.set_defaults(func=cmd_pages_accept)

    gap = group("gap", "disclosure gaps")
    confirm = gap.add_parser("confirm", parents=[common], help="confirm an expected figure is not disclosed")
    confirm.add_argument("item", type=int, metavar="ITEM")
    attributed(confirm)
    confirm.set_defaults(func=cmd_gap_confirm)

    publish = group("publish", "published data versions")
    publish.add_parser("build", parents=[common], help="build the next version and make it current").set_defaults(func=cmd_publish_build)
    publish.add_parser("restore", parents=[common], help="make the previous version current again").set_defaults(func=cmd_publish_restore)
    publish.add_parser("status", parents=[common], help="show the current version").set_defaults(func=cmd_publish_status)

    run = group("run", "the run log")
    run.add_parser("list", parents=[common], help="list runs, newest first").set_defaults(func=cmd_run_list)
    show = run.add_parser("show", parents=[common], help="show one run with its totals and events")
    show.add_argument("id", type=int)
    show.set_defaults(func=cmd_run_show)
    resume = run.add_parser("resume", parents=[common], help="finish an interrupted or failed read, extract, link, infer or doc add run")
    resume.add_argument("id", type=int)
    resume.set_defaults(func=cmd_run_resume)
    retry = run.add_parser("retry", parents=[common], help="process again only the items that failed in one run")
    retry.add_argument("id", type=int)
    retry.set_defaults(func=cmd_run_retry)

    approve = group("approve", "spend and data-transfer approvals")
    spend = approve.add_parser("spend", parents=[common], help="set the workspace spend cap in USD (0: no paid work)")
    spend.add_argument("amount", type=money, metavar="AMOUNT")
    spend.set_defaults(func=cmd_approve_spend)
    transfer = approve.add_parser("transfer", parents=[common], help="let an external model adapter receive private content")
    transfer.add_argument("name", metavar="NAME")
    transfer.add_argument("--revoke", action="store_true", help="withdraw the approval")
    transfer.set_defaults(func=cmd_approve_transfer)
    approve.add_parser("list", parents=[common], help="show the spend cap, spent so far and each adapter's approval").set_defaults(func=cmd_approve_list)

    model = group("model", "model adapters (configured in models.toml)")
    model.add_parser("list", parents=[json_flag], help="list the configured model adapters").set_defaults(func=cmd_model_list)

    measure = group("measure", "measurement against a gold set")
    g2_ = measure.add_parser("g2", parents=[common], help="score the current published version against the G2 gold set")
    g2_.add_argument("--gold", required=True, metavar="FOLDER", help="gold folder with MANIFEST.json and the jsonl files")
    g2_.add_argument("--seed", type=int, help="seed of the adjudication sample (default: drawn and printed)")
    g2_.add_argument("--against", metavar="REPORT", help="a previous report: print the scorer or extraction delta")
    g2_.set_defaults(func=cmd_measure_g2)

    serve = top.add_parser("serve", parents=[common], help="start the local service and open it in the browser")
    serve.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default: 8765)")
    serve.add_argument("--no-open", action="store_true", help="do not open the browser")
    serve.set_defaults(func=cmd_serve)
    return parser


def _fail(args, cause: str, next_action: str) -> None:
    if args.json:
        print(json.dumps({"status": "error", "cause": cause, "next_action": next_action}))
    else:
        print(f"error: {cause}\nnext: {next_action}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except GctError as e:
        _fail(args, e.cause, e.next_action)
        return e.code
    except Exception:
        log = layout.write_error_log(getattr(args, "root", None))
        where = f"Details were written to {log}." if log else "Run it again with --workspace PATH so a log file can be written."
        _fail(args, "Something unexpected went wrong.", where)
        return 1
    finally:
        if getattr(args, "lock", None):
            lock.release(args.lock)
