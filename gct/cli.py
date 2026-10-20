import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from gct.workspace import layout, published, registry, store
from gct.workspace.layout import GctError


def _print(args, payload: dict, text: str) -> None:
    print(json.dumps(payload) if args.json else text)


def _open(args):
    args.root = layout.locate(args.workspace)
    return store.connect(args.root / layout.DB_NAME)


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
    companies = registry.list_companies(_open(args))
    text = "\n".join(f"{c['id']}  {c['name']}" for c in companies) or 'No companies yet. Add one with: gct company add "NAME"'
    _print(args, {"status": "ok", "companies": companies}, text)


def cmd_doc_add(args) -> None:
    conn = _open(args)
    status, doc = registry.add_document(
        conn, args.root, args.file, args.company, args.kind, args.privacy, args.name, args.source
    )
    if status == "ok":
        text = f"Registered document {doc['id']}: {doc['logical_name']} (version {doc['version']}, {doc['privacy']})."
    else:
        text = f"Already registered as document {doc['id']}. Nothing new was added."
    _print(args, {"status": status, "document": doc}, text)


def cmd_doc_list(args) -> None:
    docs = registry.list_documents(_open(args), args.company)
    _print(args, {"status": "ok", "documents": docs}, "\n".join(_doc_line(d) for d in docs) or "No documents yet.")


def cmd_doc_show(args) -> None:
    doc = registry.show_document(_open(args), args.id)
    _print(args, {"status": "ok", "document": doc}, "\n".join(f"{k}: {v}" for k, v in doc.items()))


def _version_line(v: dict) -> str:
    return f"version {v['version']} ({v['companies']} companies, {v['documents']} documents, built {v['built_at']})"


def cmd_publish_build(args) -> None:
    v = published.build(_open(args), args.root)
    _print(args, {"status": "ok", **v}, f"Built {_version_line(v)}. It is now current.")


def cmd_publish_restore(args) -> None:
    v = published.restore(_open(args), args.root)
    _print(args, {"status": "ok", **v}, f"Went back to {_version_line(v)}. It is now current.")


def cmd_publish_status(args) -> None:
    st = published.status(_open(args), args.root)
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


def build_parser() -> argparse.ArgumentParser:
    json_flag = argparse.ArgumentParser(add_help=False)
    json_flag.add_argument("--json", action="store_true", help="print one JSON object")
    common = argparse.ArgumentParser(add_help=False, parents=[json_flag])
    common.add_argument("--workspace", metavar="PATH", help="workspace folder (default: GCT_WORKSPACE, else search upward)")

    parser = argparse.ArgumentParser(prog="gct", description="GoCarbonTracker workspace tools.")
    top = parser.add_subparsers(dest="group", required=True, metavar="{workspace,company,doc,publish}")

    def group(name, help_):
        return top.add_parser(name, help=help_).add_subparsers(dest="command", required=True)

    init = group("workspace", "create a workspace").add_parser("init", parents=[json_flag], help="create a workspace folder")
    init.add_argument("path")
    init.set_defaults(func=cmd_init)

    company = group("company", "companies")
    add = company.add_parser("add", parents=[common], help="add a company")
    add.add_argument("name")
    add.add_argument("--sector-ref")
    add.add_argument("--sector-version")
    add.set_defaults(func=cmd_company_add)
    company.add_parser("list", parents=[common], help="list companies").set_defaults(func=cmd_company_list)

    doc = group("doc", "documents")
    add = doc.add_parser("add", parents=[common], help="register a document")
    add.add_argument("file")
    add.add_argument("--company", required=True)
    add.add_argument("--kind", choices=("report", "evidence"), default="report")
    add.add_argument("--privacy", choices=("private", "shareable"), default="private")
    add.add_argument("--name", help="logical name (default: the file's base name)")
    add.add_argument("--source", help="where the file came from, free text")
    add.set_defaults(func=cmd_doc_add)
    lst = doc.add_parser("list", parents=[common], help="list documents")
    lst.add_argument("--company")
    lst.set_defaults(func=cmd_doc_list)
    show = doc.add_parser("show", parents=[common], help="show one document")
    show.add_argument("id", type=int)
    show.set_defaults(func=cmd_doc_show)

    publish = group("publish", "published data versions")
    publish.add_parser("build", parents=[common], help="build the next version and make it current").set_defaults(func=cmd_publish_build)
    publish.add_parser("restore", parents=[common], help="make the previous version current again").set_defaults(func=cmd_publish_restore)
    publish.add_parser("status", parents=[common], help="show the current version").set_defaults(func=cmd_publish_status)
    return parser


def _fail(args, cause: str, next_action: str) -> None:
    if args.json:
        print(json.dumps({"status": "error", "cause": cause, "next_action": next_action}))
    else:
        print(f"error: {cause}\nnext: {next_action}", file=sys.stderr)


def _write_log(root: Path | None) -> Path | None:
    if root is None:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / "logs" / f"error-{stamp}.log"
    path.parent.mkdir(exist_ok=True)
    path.write_text(traceback.format_exc(), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
        return 0
    except GctError as e:
        _fail(args, e.cause, e.next_action)
        return e.code
    except Exception:
        log = _write_log(getattr(args, "root", None))
        where = f"Details were written to {log}." if log else "Run it again with --workspace PATH so a log file can be written."
        _fail(args, "Something unexpected went wrong.", where)
        return 1
