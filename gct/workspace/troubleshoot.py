"""gct troubleshoot export (story 8.3): a folder to send to a maintainer. Versions, counts, the run log reduced to
product text and the newest error logs reduced to gct frames; never a name, an id, a path, a host, a user or an
environment variable. It reads committed rows only: no run, no lock of its own (D-8.3-3)."""
import ast
import json
import platform
import re
import sys
from collections import Counter
from importlib import metadata
from pathlib import Path, PurePosixPath, PureWindowsPath

import gct
from gct import __version__
from gct.models.redact import scrub
from gct.reports import export, package
from gct.workspace import published, registry, runs, store

# pyproject.toml dependencies, then the dev extra (tests/test_troubleshoot.py keeps the two equal).
DEPENDENCIES = ("fastapi", "uvicorn", "pdfplumber", "pypdfium2", "openpyxl", "pytest", "jsonschema")
FILES = ("troubleshooting.json", "troubleshooting.txt")
LOGS = 5  # the newest error logs carried (D-8.3-4)
WITHHELD = "withheld"
FIELD = "{}"
ABSOLUTE = re.compile(r"(?:^|[\s\"'(=])/[^\s/\"]+|[A-Za-z]:\\")
FRAME = re.compile(r'^  File "(.+)", line (\d+), in (.+)$')
EXCEPTION = re.compile(r"^([A-Za-z_][\w.]*)(?::|$)")


def sources() -> list[str]:
    """The text of every installed gct module, in path order; [] when the sources are not on disk."""
    return [p.read_text(encoding="utf-8") for p in sorted(Path(gct.__file__).parent.rglob("*.py"))]


def templates(texts) -> list[tuple[str, re.Pattern]]:
    """(template, pattern) for every GctError cause in source order (D-8.3-1): a constant matches itself, an f-string
    matches with each field as .+?, anchored at both ends. A dynamic cause, or an f-string with no constant word, gives
    none."""
    out = []
    for text in texts:
        calls = [n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Call) and len(n.args) > 1
                 and getattr(n.func, "id", getattr(n.func, "attr", None)) == "GctError"]
        for call in sorted(calls, key=lambda n: (n.lineno, n.col_offset)):
            cause = call.args[1]
            if isinstance(cause, ast.Constant) and isinstance(cause.value, str):
                parts = [cause.value]
            elif isinstance(cause, ast.JoinedStr):
                parts = [v.value if isinstance(v, ast.Constant) else None for v in cause.values]
            else:
                continue
            if not re.search(r"[A-Za-z]", "".join(p for p in parts if p)):
                continue
            out.append(("".join(FIELD if p is None else p for p in parts),
                        re.compile("".join(".+?" if p is None else re.escape(p) for p in parts), re.S)))
    return out


def _class_names() -> set[str]:
    return {c.__name__ for m in list(sys.modules.values()) for c in list(getattr(m, "__dict__", {}).values())
            if isinstance(c, type) and issubclass(c, BaseException)}


def reduce_message(message: str, known) -> str:
    """The template a stored message was made from, the exception class name it is, or WITHHELD."""
    for template, pattern in known:
        if pattern.fullmatch(message):
            return template
    return message if message in _class_names() else WITHHELD


def reduce_log(text: str, package_dir) -> dict:
    """Frames inside the gct package as gct/<path>:<line> in <function>, the count of other frames, and the exception
    class of each traceback in the chain. Source lines and exception messages are dropped."""
    frames, other, exceptions, inside = [], 0, [], False
    for line in text.splitlines():
        if line.startswith("Traceback "):
            inside = True
        elif m := FRAME.match(line):
            pure = PureWindowsPath if re.match(r"[A-Za-z]:\\", m[1]) else PurePosixPath
            try:
                rel = pure(m[1]).relative_to(pure(package_dir))
            except ValueError:
                other += 1
                continue
            frames.append(f"gct/{rel.as_posix()}:{m[2]} in {m[3]}")
        elif inside and not line.startswith(" ") and (m := EXCEPTION.match(line)):
            exceptions.append(m[1])
            inside = False
    return {"frames": frames, "other_frames": other, "exceptions": exceptions}


def _version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def collect(conn, root: Path) -> dict:
    keep = {t: [c for c, k in package.COLUMNS[t].items() if k == "keep"] for t in ("run", "run_event")}
    known = templates(sources())
    events = f"SELECT {', '.join(keep['run_event'])}, message FROM run_event WHERE run_id = ? ORDER BY id"
    run_list = []
    for r in reversed(runs.list_runs(conn)):
        evs = [dict(e) for e in conn.execute(events, (r["id"],))]
        for e in evs:
            failed = e["kind"] == "failure" or (e["kind"] == "finished" and e["outcome"] == "failed")
            e["message"] = reduce_message(e["message"], known) if failed and e["message"] else None
        run_list.append({**{c: r[c] for c in keep["run"]}, "outcome": r["outcome"], "events": evs})
    current = published.current_version(conn, root)
    created = conn.execute("SELECT created_at, gct_version FROM workspace").fetchone()
    package_dir = Path(gct.__file__).parent
    logs = sorted((root / "logs").glob("error-*.log"), reverse=True)[:LOGS]
    return {
        "created_at": store.now(),
        "gct": {"version": __version__, "installed": _version("gct")},
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation()},
        "os": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
               "platform": platform.platform()},
        "dependencies": {name: _version(name) for name in DEPENDENCIES},
        "workspace": {
            "schema_version": conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0],
            "migrations": [dict(m) for m in conn.execute("SELECT version, applied_at FROM schema_version ORDER BY version")],
            "created_at": created["created_at"], "created_by_gct": created["gct_version"],
            "published_version": current[0] if current else None},
        "counts": {
            "companies": conn.execute("SELECT COUNT(*) FROM company").fetchone()[0],
            "documents": dict(sorted(Counter(d["state"] for d in registry.list_documents(conn)).items())),
            "pages": {str(rung): n for rung, n in conn.execute("SELECT rung, COUNT(*) FROM page GROUP BY rung ORDER BY rung")},
            "claims": conn.execute("SELECT COUNT(*) FROM claim").fetchone()[0]},
        "runs": run_list,
        "error_logs": [{"file": p.name, **reduce_log(p.read_text(encoding="utf-8", errors="replace"), package_dir)}
                       for p in logs],
    }


def clean(x, folders):
    """The last step (E8-D15): scrub, the given folders to their placeholders (longest first), then any string still
    holding an absolute path becomes "[path removed]"."""
    if isinstance(x, dict):
        return {k: clean(v, folders) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v, folders) for v in x]
    if not isinstance(x, str):
        return x
    x = scrub(x)
    for path, mark in folders:
        x = x.replace(path, mark)
    return "[path removed]" if ABSOLUTE.search(x) else x


def lines(d, head=""):
    """The JSON as key.path: value lines (strings as they are, anything else as JSON); nothing the JSON lacks."""
    items = d.items() if isinstance(d, dict) else enumerate(d)
    for k, v in items:
        key = f"{head}{k}"
        if isinstance(v, (dict, list)) and v:
            yield from lines(v, key + ".")
        else:
            yield f"{key}: {v if isinstance(v, str) else json.dumps(v)}"


def write(conn, root: Path, given: list[Path]) -> dict:
    """Writes exports/troubleshooting-<stamp>/ with FILES. given: the workspace folder as the user named it."""
    folders = {str(p): "<workspace>" for g in [root, *given] for p in (g, g.resolve())}
    folders |= {str(p): "<home>" for p in (Path.home(), Path.home().resolve())}
    d = clean(collect(conn, root), sorted(folders.items(), key=lambda kv: -len(kv[0])))
    stem = f"troubleshooting-{export.stamp()}"
    with export.folder(root, stem, FILES) as tmp:
        with open(tmp / FILES[0], "x", encoding="utf-8") as out:
            json.dump(d, out, indent=1, ensure_ascii=False)
        with open(tmp / FILES[1], "x", encoding="utf-8") as out:
            out.write("\n".join(lines(d)) + "\n")
    return {"folder": f"exports/{stem}/", "files": list(FILES)}
