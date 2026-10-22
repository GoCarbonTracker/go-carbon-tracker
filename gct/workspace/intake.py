"""doc add over files, folders and URLs: plan a batch, or register it in one run with URLs through the fetch stage."""
import http.client
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from gct.stages import Result, Stage, result, run_stage, version_of
from gct.workspace import registry, runs
from gct.workspace.layout import REFUSED, USAGE, GctError

TIMEOUT = 60
MAX_BYTES = 500 * 1024 * 1024
FETCH_CONFIG = version_of("fetch", 1)
RETRY = "Check the address, then run the same command again."
FAILED_SQL = """
SELECT e.item FROM run_event e
WHERE e.run_id = ? AND e.kind = 'failure' AND e.stage IN ('fetch', 'register')
  AND NOT EXISTS (SELECT 1 FROM run_event l WHERE l.kind = 'item' AND l.stage = 'register' AND l.item = e.item
                  AND l.id > e.id)
GROUP BY e.item ORDER BY MIN(e.id)
"""


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to http(s) addresses."""

    def http_error_302(self, req, fp, code, msg, headers):
        if urlparse(headers.get("location") or headers.get("uri") or "").scheme not in ("http", "https", ""):
            raise GctError(REFUSED, "The address redirected to something that is not a web address.",
                           "Use a direct http or https link to the file.")
        return super().http_error_302(req, fp, code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


# No proxy from the environment: the request goes only to the address the user typed.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirects)


def _is_url(source: str) -> bool:
    return source.lower().startswith(("http://", "https://"))


def _name(url: str) -> str:
    parts = urlparse(url)
    return registry.logical_name(parts.path) or parts.netloc


def _download(root: Path, url: str) -> Result:
    files_dir = Path(root) / "files"
    files_dir.mkdir(exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=files_dir, prefix=".download-")
    tmp = Path(tmp)
    try:
        size = 0
        try:
            with os.fdopen(fd, "wb") as out, _OPENER.open(url, timeout=TIMEOUT) as resp:
                while chunk := resp.read(1 << 20):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise GctError(REFUSED, f"The download is larger than the limit of {MAX_BYTES:,} bytes.",
                                       "Download the file yourself and add it from disk.")
                    out.write(chunk)
        except urllib.error.HTTPError as e:
            raise GctError(REFUSED, f"The address answered with HTTP error {e.code}.", RETRY) from None
        except (OSError, http.client.HTTPException):
            raise GctError(REFUSED, "The address could not be reached.", RETRY) from None
        if registry.detect_file_type(tmp, _name(url)) is None:
            raise GctError(REFUSED, "The address did not return a PDF, XLSX or CSV file.",
                           "Use a direct link to the file itself, not to a web page.")
        # ponytail: _store_file copies the download once more; hash while downloading and rename if big links get slow.
        digest, size = registry._store_file(Path(root), tmp)
    finally:
        tmp.unlink(missing_ok=True)
    return Result(output={"sha256": digest, "size": size}, method="urllib")


def _item(source, company, action, document=None, cause=None, next_action=None, cached=False) -> dict:
    return {"source": source, "company": company, "action": action, "document": document,
            "cause": cause, "next_action": next_action, "cached": cached}


def _restore(doc) -> str | None:
    """The next step for a duplicate of an archived document, else None."""
    return registry._restore_next(doc["id"]) if doc and doc["state"] == "archived" else None


def _entries(sources, name):
    """(source, refusal) per item: URLs and files as given, folders expanded to their recognised direct children."""
    out = []
    for s in map(str, sources):
        p = Path(s)
        if _is_url(s) or not p.is_dir():
            out.append((s, None))
            continue
        found = []
        for c in sorted((c for c in p.iterdir() if c.is_file()), key=lambda c: c.name):
            try:
                if registry.detect_file_type(c):
                    found.append((str(c), None))
            except OSError:
                found.append((str(c), registry.unreadable(c)))
        out += found or [(s, GctError(
            REFUSED, f"The folder {s} holds no PDF, XLSX or CSV file.", "Add the files themselves, or a folder that holds them."
        ))]
    if name and len(out) > 1:
        raise GctError(USAGE, f"--name gives one name, but there are {len(out)} items.",
                       "Leave out --name, or add one file at a time.")
    return out


def plan(conn, sources, company, name=None) -> list[dict]:
    """What add would do with each item. Reads only; downloads nothing."""
    co = registry._find_company(conn, company)
    items, seen = [], set()
    for source, refusal in _entries(sources, name):
        if _is_url(source):
            items.append(_item(source, co["name"], "would fetch"))
            continue
        try:
            if refusal:
                raise refusal
            registry.checked_file_type(Path(source))
        except GctError as e:
            items.append(_item(source, co["name"], "refused", None, e.cause, e.next_action))
            continue
        digest = registry._hash_file(Path(source))
        dup = registry.find_duplicate(conn, co["id"], digest)
        items.append(_item(source, co["name"], "duplicate" if dup or digest in seen else "would register", dup,
                           next_action=_restore(dup)))
        seen.add(digest)
    return items


def failed(conn, run_id: int) -> list[str]:
    """The sources that failed to fetch or register in the run and were not registered (or found a duplicate) since."""
    return [item for (item,) in conn.execute(FAILED_SQL, (run_id,))]


def add(conn, root, sources, company, kind="report", privacy="private", name=None, source=None,
        notes=()) -> tuple[int, list[dict]]:
    """Register every item in one run record. A bad item is reported and the batch keeps going.
    Returns the run id and one record per item."""
    co = registry._find_company(conn, company)
    # Absolute, so a resume or retry from another folder replays the same files.
    sources = [s if _is_url(s) else str(Path(s).resolve()) for s in map(str, sources)]
    entries = _entries(sources, name)
    stage = Stage("fetch", FETCH_CONFIG, lambda url, conn: _download(root, url), version_of)
    items = []
    with runs.run(conn, "doc add") as run_id:
        runs.record(conn, run_id, {"sources": sources,"company": company, "kind": kind,
                                   "privacy": privacy, "name": name, "source": source}, notes)
        for src, refusal in entries:
            cached = False
            try:
                if refusal:
                    raise refusal
                if _is_url(src):
                    cached = run_stage(conn, run_id, stage, [src])["cached"] == 1
                    out = result(conn, "fetch", src, version_of(src), FETCH_CONFIG)
                    if out is None:  # run_stage already wrote the failed attempt and its failure event
                        (cause,) = conn.execute(
                            "SELECT error FROM attempt WHERE stage = 'fetch' AND item = ? ORDER BY id DESC LIMIT 1", (src,)
                        ).fetchone()
                        items.append(_item(src, co["name"], "failed", None, cause, RETRY))
                        continue
                    status, doc = registry.add_stored(conn, root, out["sha256"], company, name or _name(src),
                                                      kind, privacy, src, file_name=_name(src))
                else:
                    status, doc = registry.add_document(conn, root, src, company, kind, privacy, name, source)
            except GctError as e:
                runs.event(conn, run_id, "failure", stage="register", item=src, message=e.cause)
                items.append(_item(src, co["name"], "refused", None, e.cause, e.next_action))
                continue
            outcome = "ok" if status == "ok" else "duplicate"
            runs.event(conn, run_id, "item", stage="register", item=src, outcome=outcome)
            items.append(_item(src, co["name"], "registered" if status == "ok" else "duplicate", doc, cached=cached,
                               next_action=_restore(doc) if status != "ok" else None))
    return run_id, items
