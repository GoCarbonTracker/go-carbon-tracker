import os
import sqlite3
from pathlib import Path

from gct import __version__
from gct.workspace import store
from gct.workspace.layout import REFUSED, GctError

ACTIVE = "(SELECT s.state FROM document_state s WHERE s.document_id = d.id ORDER BY s.id DESC LIMIT 1)"

# Later stories add their tables here: one CREATE and one INSERT each, filled in _read_history.
PROJECTION_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE company (id INTEGER PRIMARY KEY, name TEXT NOT NULL, sector_ref TEXT, sector_version TEXT);
CREATE TABLE document (
    id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, logical_name TEXT NOT NULL, version INTEGER NOT NULL,
    sha256 TEXT NOT NULL, kind TEXT NOT NULL, file_type TEXT NOT NULL, privacy TEXT NOT NULL, size_bytes INTEGER NOT NULL
);
"""
COMPANY_COLUMNS = "id, name, sector_ref, sector_version"
DOCUMENT_COLUMNS = "id, company_id, logical_name, version, sha256, kind, file_type, privacy, size_bytes"

BUILD_AGAIN = "Build a fresh version with: gct publish build"


def version_path(root: Path, version: int) -> Path:
    return Path(root) / "published" / f"v{version}.db"


def open_version(path: Path) -> sqlite3.Connection:
    """Open a published version read-only."""
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def history_mark(conn: sqlite3.Connection) -> str:
    return ".".join(
        str(conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {t}").fetchone()[0])
        for t in ("company", "document", "document_state")
    )


def pointers(conn: sqlite3.Connection) -> tuple[int | None, int | None]:
    """(current, previous) version numbers from the pointer rows."""
    rows = [r[0] for r in conn.execute("SELECT version FROM published_pointer ORDER BY id")]
    if not rows:
        return None, None
    current = rows[-1]
    return current, next((v for v in reversed(rows[:-1]) if v != current), None)


def current_version(conn: sqlite3.Connection, root: Path) -> tuple[int, Path] | None:
    """The current version number and its file, or None before the first build."""
    current, _ = pointers(conn)
    return None if current is None else (current, version_path(root, current))


def _info(conn: sqlite3.Connection, version: int) -> dict:
    row = conn.execute(
        "SELECT version, built_at, history_mark, companies, documents FROM published_version WHERE version = ?",
        (version,),
    ).fetchone()
    return dict(row)


def _read_history(conn: sqlite3.Connection):
    """One consistent snapshot of the history: (mark, companies, active documents)."""
    conn.execute("BEGIN")
    try:
        mark = history_mark(conn)
        companies = conn.execute(f"SELECT {COMPANY_COLUMNS} FROM company ORDER BY id").fetchall()
        docs = conn.execute(
            f"SELECT {DOCUMENT_COLUMNS} FROM document d WHERE {ACTIVE} IN ('registered', 'restored') ORDER BY id"
        ).fetchall()
    finally:
        conn.execute("COMMIT")
    return mark, companies, docs


def _write_projection(path: Path, meta: dict, companies, docs) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    out = sqlite3.connect(tmp, isolation_level=None)
    try:
        out.execute("PRAGMA journal_mode = DELETE")
        out.execute("BEGIN")
        for stmt in filter(str.strip, PROJECTION_SCHEMA.split(";")):
            out.execute(stmt)
        out.executemany("INSERT INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in meta.items()])
        out.executemany(f"INSERT INTO company VALUES ({','.join('?' * 4)})", [tuple(r) for r in companies])
        out.executemany(f"INSERT INTO document VALUES ({','.join('?' * 9)})", [tuple(r) for r in docs])
        out.execute("COMMIT")
    except BaseException:
        out.close()
        tmp.unlink(missing_ok=True)
        raise
    out.close()
    check = open_version(tmp)
    try:
        ok = (
            check.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()[0] == str(meta["version"])
            and check.execute("SELECT COUNT(*) FROM company").fetchone()[0] == len(companies)
            and check.execute("SELECT COUNT(*) FROM document").fetchone()[0] == len(docs)
        )
    finally:
        check.close()
    if not ok:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("the new published version did not verify")
    os.replace(tmp, path)


def build(conn: sqlite3.Connection, root: Path) -> dict:
    """Write the next version from current history and make it current."""
    root = Path(root)
    (root / "published").mkdir(exist_ok=True)
    version = (conn.execute("SELECT MAX(version) FROM published_version").fetchone()[0] or 0) + 1
    mark, companies, docs = _read_history(conn)
    built_at = store.now()
    meta = {
        "version": version, "built_at": built_at, "history_mark": mark,
        "gct_version": __version__, "projection_schema": 1,
    }
    _write_projection(version_path(root, version), meta, companies, docs)
    with store.transaction(conn):
        conn.execute(
            "INSERT INTO published_version (version, built_at, history_mark, companies, documents, gct_version)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (version, built_at, mark, len(companies), len(docs), __version__),
        )
        conn.execute(
            "INSERT INTO published_pointer (version, action, at) VALUES (?, 'build', ?)", (version, built_at)
        )
    _retain(conn, root)
    return _info(conn, version)


def _retain(conn: sqlite3.Connection, root: Path) -> None:
    """Keep the files of the current and previous version only. A file that cannot be removed waits."""
    keep = set(pointers(conn))
    purged = {r[0] for r in conn.execute("SELECT version FROM published_purge")}
    gone = []
    for (v,) in conn.execute("SELECT version FROM published_version ORDER BY version").fetchall():
        if v in keep or v in purged:
            continue
        try:
            version_path(root, v).unlink(missing_ok=True)
        except OSError:  # on Windows a reader may hold the file open
            continue
        gone.append(v)
    if gone:
        with store.transaction(conn):
            conn.executemany(
                "INSERT INTO published_purge (version, reason, at) VALUES (?, 'retention', ?)",
                [(v, store.now()) for v in gone],
            )


def _holds_deleted(conn: sqlite3.Connection, path: Path) -> bool:
    ver = open_version(path)
    try:
        ids = [r[0] for r in ver.execute("SELECT id FROM document")]
    finally:
        ver.close()
    return any(
        conn.execute(
            "SELECT 1 FROM document_state WHERE document_id = ? AND id = "
            "(SELECT MAX(id) FROM document_state WHERE document_id = ?) AND state = 'deleted'",
            (i, i),
        ).fetchone()
        for i in ids
    )


def restore(conn: sqlite3.Connection, root: Path) -> dict:
    """Make the previous version current again. Nothing is rebuilt and no file is touched."""
    _, previous = pointers(conn)
    if previous is None:
        raise GctError(REFUSED, "There is no earlier published version to go back to.", BUILD_AGAIN)
    path = version_path(root, previous)
    if not path.is_file():
        raise GctError(REFUSED, f"Version {previous} is no longer on disk.", BUILD_AGAIN)
    if _holds_deleted(conn, path):
        raise GctError(
            REFUSED,
            f"Version {previous} still contains a document that has since been deleted, so it cannot be made current again.",
            BUILD_AGAIN,
        )
    with store.transaction(conn):
        conn.execute(
            "INSERT INTO published_pointer (version, action, at) VALUES (?, 'restore', ?)", (previous, store.now())
        )
    return _info(conn, previous)


def status(conn: sqlite3.Connection, root: Path) -> dict:
    current, previous = pointers(conn)
    files = [
        r[0] for r in conn.execute("SELECT version FROM published_version ORDER BY version")
        if version_path(root, r[0]).is_file()
    ]
    info = _info(conn, current) if current is not None else {
        "version": None, "built_at": None, "history_mark": None, "companies": None, "documents": None,
    }
    return {
        "current_version": info["version"], "built_at": info["built_at"], "history_mark": info["history_mark"],
        "companies": info["companies"], "documents": info["documents"], "previous_version": previous,
        "stale": current is not None and info["history_mark"] != history_mark(conn), "files": files,
    }
