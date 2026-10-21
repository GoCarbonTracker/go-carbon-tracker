import argparse
import json
import math
import os
import sys
import webbrowser
from collections import Counter

from gct import __version__
from gct.api import server
from gct.models import adapters, policy
from gct.stages import extract, read
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
    return f"{d['id']}  {d['company']}  {d['logical_name']}  v{d['version']}  {d['privacy']}  {d['state']}"


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
        return f"duplicate of {d['id']}: {i['source']}" if d else f"duplicate: {i['source']}"
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
    _print(args, {"status": "ok", "documents": docs}, "\n".join(_doc_line(d) for d in docs) or "No documents yet.")


def cmd_doc_show(args) -> None:
    doc = registry.show_document(_open(args, write=False), args.id)
    _print(args, {"status": "ok", "document": doc}, "\n".join(f"{k}: {v}" for k, v in doc.items()))


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
    ps = read.pages(_open(args, write=False), args.id)
    if not ps:
        _print(args, {"status": "ok", "document": args.id, "pages": []}, f"No pages read yet. Run: gct read {args.id}")
        return
    flags = Counter(f for p in ps for f in p["flags"])
    lines = [
        f"p{p['page_number']}  rung {p['rung']}  {p['method']}  words {p['words']}  tables {p['tables']}  "
        f"flags {', '.join(p['flags']) or 'none'}"
        for p in ps
    ]
    text = "\n".join([*lines, f"Flagged pages: {_counts(flags)}", f"{flags['no_text']} pages without text"])
    _print(args, {"status": "ok", "document": args.id, "pages": ps}, text)


EXTRACT_TOTALS = ("pages", "extracted", "cached", "failed", "figures", "unresolved")


def _extract_line(d: dict) -> str:
    if d["action"] != "extracted":
        return f"{d['action']} {d['id']}: {d['logical_name']}: {d['cause']}" + (f" ({d['next_action']})" if d["next_action"] else "")
    return (f"extracted {d['id']}: {d['logical_name']}: {d['pages']} pages, {d['extracted']} extracted, "
            f"{d['cached']} cached, {d['failed']} failed, {d['figures']} figures, {d['unresolved']} unresolved boxes")


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
        f"{total['failed']} failed, {total['figures']} figures, {total['unresolved']} unresolved boxes",
    ])
    bad = [d for d in docs if d["failed"]]
    if not bad:
        _print(args, {"status": "ok", **extra, "documents": docs}, text)
        return 0
    cause = f"{len(bad)} of {len(docs)} documents were not fully extracted: " + ", ".join(str(d["id"]) for d in bad)
    _print(args, {"status": "partial", "cause": cause, "next_action": extract.RETRY, **extra, "documents": docs}, text)
    if not args.json:
        print(f"error: {cause}\nnext: {extract.RETRY}", file=sys.stderr)
    return layout.REFUSED


def _claim_line(c: dict) -> str:
    box = "box " + ", ".join(f"{v:g}" for v in c["boxes"][0]) if c["boxes"] else "location unresolved"
    return (f"p{c['page_number']}  {c['value_text']}  {c['unit_text'] or '-'}  {c['metric_text'] or '-'}  "
            f"{c['period_label'] or '-'}  {c['reporting_boundary']}  {box}")


def cmd_claims_list(args) -> None:
    cs = extract.claims(_open(args, write=False), args.doc)
    text = "\n".join(map(_claim_line, cs)) or f"No claims yet. Run: gct extract {args.doc}"
    _print(args, {"status": "ok", "document": args.doc, "claims": cs}, text)


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
         "doc add": "Run gct doc add again with the same files."}
STAGES = {"read": (read, _read_out), "extract": (extract, _extract_out)}


def _of_run(conn, n: int, verb: str) -> dict:
    """Run n, which must be a read, extract or doc add run."""
    r = runs.show_run(conn, n)
    if r["command"] not in AGAIN:
        raise GctError(layout.REFUSED, f"Run {n} was a {r['command']} run. Only read, extract and doc add runs can be {verb}.",
                       "See the runs with: gct run list")
    return r


def _selection(conn, r: dict) -> dict:
    sel = runs.selection(conn, r["id"])
    if sel is None:
        raise GctError(layout.REFUSED, f"Run {r['id']} has no record of what it was given, so it cannot be replayed.",
                       AGAIN[r["command"]])
    return sel


def _replay(args, conn, r: dict, sel: dict, note: str, head: str) -> int:
    """Run the recorded selection of a read, extract or doc add run again in a new run."""
    if r["command"] == "read":
        run_id, docs = read.read(conn, args.root, sel["ids"], sel["company"], [note])
        return _read_out(args, docs, head.format(run_id), {"run_id": run_id, "of_run": r["id"]})
    if r["command"] == "extract":
        run_id, docs = extract.extract(conn, args.root, sel["ids"], sel["company"], [note])
        return _extract_out(args, docs, head.format(run_id), {"run_id": run_id, "of_run": r["id"]})
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
    top = parser.add_subparsers(dest="group", required=True, metavar="{workspace,company,doc,read,extract,claims,publish,run,approve,model,serve}")

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
    lst.set_defaults(func=cmd_doc_list)
    show = doc.add_parser("show", parents=[common], help="show one document")
    show.add_argument("id", type=int)
    show.set_defaults(func=cmd_doc_show)
    pages = doc.add_parser("pages", parents=[common], help="show how each page of one document was read")
    pages.add_argument("id", type=int)
    pages.set_defaults(func=cmd_doc_pages)

    rd = top.add_parser("read", parents=[common], help="read every page of PDF documents (text, words, tables)")
    rd.add_argument("ids", nargs="*", type=int, metavar="ID", help="documents to read (default: every active document)")
    rd.add_argument("--company", help="only this company's documents")
    rd.set_defaults(func=cmd_read)

    ex = top.add_parser("extract", parents=[common], help="list the figures on read pages with fixed rules (no model)")
    ex.add_argument("ids", nargs="*", type=int, metavar="ID", help="documents to extract (default: every active document)")
    ex.add_argument("--company", help="only this company's documents")
    ex.set_defaults(func=cmd_extract)

    claims = group("claims", "figures extracted from documents")
    lst = claims.add_parser("list", parents=[common], help="list one document's claims with their source location")
    lst.add_argument("--doc", type=int, required=True, metavar="ID")
    lst.set_defaults(func=cmd_claims_list)

    publish = group("publish", "published data versions")
    publish.add_parser("build", parents=[common], help="build the next version and make it current").set_defaults(func=cmd_publish_build)
    publish.add_parser("restore", parents=[common], help="make the previous version current again").set_defaults(func=cmd_publish_restore)
    publish.add_parser("status", parents=[common], help="show the current version").set_defaults(func=cmd_publish_status)

    run = group("run", "the run log")
    run.add_parser("list", parents=[common], help="list runs, newest first").set_defaults(func=cmd_run_list)
    show = run.add_parser("show", parents=[common], help="show one run with its totals and events")
    show.add_argument("id", type=int)
    show.set_defaults(func=cmd_run_show)
    resume = run.add_parser("resume", parents=[common], help="finish an interrupted or failed read, extract or doc add run")
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
