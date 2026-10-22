import hashlib
import os
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from gct.workspace import store
from gct.workspace.layout import NOT_FOUND, REFUSED, USAGE, GctError

DELIMITERS = ",;\t|"
XLSX_PARTS = {"[Content_Types].xml", "xl/workbook.xml"}

DOCUMENT_SQL = """
SELECT d.id, c.name AS company, d.logical_name, d.version, d.sha256, d.kind, d.file_type,
       d.privacy, d.size_bytes, d.source, d.created_at,
       (SELECT s.state FROM document_state s WHERE s.document_id = d.id
        ORDER BY s.id DESC LIMIT 1) AS state
FROM document d JOIN company c ON c.id = d.company_id
"""


def _company(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in ("id", "name", "sector_ref", "sector_version", "created_at")}


def _find_company(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    wanted = name.strip().casefold()
    for row in conn.execute("SELECT * FROM company ORDER BY id"):
        if row["name"].strip().casefold() == wanted:
            return row
    raise GctError(
        NOT_FOUND,
        f"There is no company named '{name.strip()}'.",
        'Add it first with: gct company add "NAME"',
    )


def add_company(conn, name, sector_ref=None, sector_version=None) -> tuple[str, dict]:
    clean = name.strip()
    if not clean:
        raise GctError(USAGE, "The company name is empty.", 'Give a name, for example: gct company add "Acme Ltd"')
    try:
        return "exists", _company(_find_company(conn, clean))
    except GctError:
        pass
    cur = conn.execute(
        "INSERT INTO company (name, sector_ref, sector_version, created_at) VALUES (?, ?, ?, ?)",
        (clean, sector_ref, sector_version, store.now()),
    )
    return "ok", _company(conn.execute("SELECT * FROM company WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_companies(conn) -> list[dict]:
    return [_company(r) for r in conn.execute("SELECT * FROM company ORDER BY id")]


def logical_name(source: str | os.PathLike) -> str:
    """Base name of a path written for any operating system (never splits on os.sep)."""
    return re.split(r"[\\/]", os.fspath(source))[-1]


def _is_csv(path: Path) -> bool:
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            found = False
            while chunk := f.read(1 << 20):
                found = found or any(c in chunk for c in DELIMITERS)
            return found
    except UnicodeDecodeError:
        return False


def detect_file_type(path: Path, name: str | None = None) -> str | None:
    """Recognise pdf, xlsx or csv from content. None when it is none of them.
    name stands in for the file name when path has none of its own (a download)."""
    with open(path, "rb") as f:
        if f.read(4) == b"%PDF":
            return "pdf"
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as z:
                return "xlsx" if XLSX_PARTS <= set(z.namelist()) else None
        except zipfile.BadZipFile:
            return None
    if Path(name or path).suffix.lower() == ".csv" and _is_csv(path):
        return "csv"
    return None


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def stored_path(root: Path, digest: str) -> Path:
    return root / "files" / digest[:2] / digest


def _store_file(root: Path, src: Path) -> tuple[str, int]:
    """Copy src into files/<xx>/<sha256>, hashing while copying, then re-hash the stored copy."""
    files_dir = root / "files"
    files_dir.mkdir(exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=files_dir, prefix=".incoming-")
    h = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as inp:
            while chunk := inp.read(1 << 20):
                h.update(chunk)
                out.write(chunk)
                size += len(chunk)
        digest = h.hexdigest()
        dest = stored_path(root, digest)
        if dest.exists():
            return digest, size
        dest.parent.mkdir(exist_ok=True)
        os.replace(tmp, dest)
    finally:
        Path(tmp).unlink(missing_ok=True)
    if _hash_file(dest) != digest:
        dest.unlink()
        raise GctError(
            REFUSED,
            "The copy stored in the workspace did not match the original file.",
            "Check the disk for errors and add the file again.",
        )
    return digest, size


def get_document(conn, doc_id: int) -> dict | None:
    row = conn.execute(DOCUMENT_SQL + " WHERE d.id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def show_document(conn, doc_id: int) -> dict:
    doc = get_document(conn, doc_id)
    if doc is None:
        raise GctError(NOT_FOUND, f"There is no document with id {doc_id}.", "List documents with: gct doc list")
    return doc


def list_documents(conn, company: str | None = None) -> list[dict]:
    if company is None:
        rows = conn.execute(DOCUMENT_SQL + " ORDER BY d.id")
    else:
        rows = conn.execute(DOCUMENT_SQL + " WHERE d.company_id = ? ORDER BY d.id", (_find_company(conn, company)["id"],))
    return [dict(r) for r in rows]


# Archive and restore (story 4.4): one document_state row and one document_state_change row naming the contributor.

def _restore_next(doc_id: int) -> str:
    return f"Restore it with: gct doc restore {doc_id}"


def require_active(conn, doc_id: int) -> dict:
    """The document, or the refusal of a write on an archived one."""
    doc = show_document(conn, doc_id)
    if doc["state"] == "archived":
        raise GctError(REFUSED, f"Document {doc_id} is archived.", _restore_next(doc_id))
    return doc


def state_change(conn, doc_id: int) -> dict | None:
    """Who made the document's newest state, when and why; None for a registration."""
    row = conn.execute(
        "SELECT s.state, s.at, c.name, c.organisation, x.capacity, x.rationale FROM document_state s"
        " JOIN document_state_change x ON x.document_state_id = s.id"
        " JOIN contributor_version c ON c.id = x.contributor_version_id"
        " WHERE s.id = (SELECT MAX(id) FROM document_state WHERE document_id = ?)", (doc_id,)).fetchone()
    return row and {"state": row["state"], "at": row["at"], "contributor": row["name"],
                    "organisation": row["organisation"], "capacity": row["capacity"], "rationale": row["rationale"]}


def check_archive(conn, doc_id: int) -> dict:
    """The document, or the refusal: only an active document can be archived."""
    doc = show_document(conn, doc_id)
    if doc["state"] == "archived":
        raise GctError(REFUSED, f"Document {doc_id} is already archived.", _restore_next(doc_id))
    if doc["state"] not in ("registered", "restored"):
        raise GctError(REFUSED, f"Document {doc_id} is {doc['state']}, so it cannot be archived.", "List documents with: gct doc list")
    return doc


def _change(conn, doc_id: int, state: str, key, capacity, rationale) -> dict:
    from gct.stages.infer import _who  # the stages import this module

    who, capacity, rationale = _who(conn, key, capacity, rationale)
    with store.transaction(conn):
        stamp = store.now()
        sid = conn.execute("INSERT INTO document_state (document_id, state, at) VALUES (?, ?, ?)",
                           (doc_id, state, stamp)).lastrowid
        conn.execute("INSERT INTO document_state_change (document_state_id, contributor_version_id, capacity, rationale,"
                     " created_at) VALUES (?, ?, ?, ?, ?)", (sid, who["version"], capacity, rationale, stamp))
    return state_change(conn, doc_id)


def archive(conn, doc_id: int, key, capacity, rationale) -> dict:
    """Mark an active document archived. Nothing else is written, moved or removed."""
    check_archive(conn, doc_id)
    return _change(conn, doc_id, "archived", key, capacity, rationale)


def restore(conn, doc_id: int, key, capacity, rationale) -> dict:
    """Make an archived document active again."""
    if show_document(conn, doc_id)["state"] != "archived":
        raise GctError(REFUSED, f"Document {doc_id} is not archived, so there is nothing to restore.",
                       "List the archived documents with: gct doc list")
    return _change(conn, doc_id, "restored", key, capacity, rationale)


def unreadable(src) -> GctError:
    return GctError(REFUSED, f"The file {src} could not be read.",
                    "Close any program that has it open, check its permissions, then add it again.")


def checked_file_type(src: Path) -> str:
    """The content type of an existing file, or the refusal the user sees."""
    if not src.is_file():
        raise GctError(NOT_FOUND, f"The file {src} does not exist.", "Check the path and try again.")
    try:
        file_type = detect_file_type(src)
    except OSError:
        raise unreadable(src) from None
    if file_type is None:
        raise GctError(
            REFUSED,
            "This file is not a PDF, XLSX or CSV file. Only those three types are accepted.",
            "Convert it to one of those types, or check that the file is not damaged.",
        )
    return file_type


def find_duplicate(conn, company_id: int, digest: str) -> dict | None:
    row = conn.execute(
        "SELECT id FROM document WHERE company_id = ? AND sha256 = ? ORDER BY id LIMIT 1", (company_id, digest)
    ).fetchone()
    return get_document(conn, row["id"]) if row else None


def _register(conn, co, digest, size, file_type, logical, kind, privacy, source):
    with store.transaction(conn):
        dup = find_duplicate(conn, co["id"], digest)
        if dup:
            return "duplicate", dup
        last = conn.execute(
            "SELECT MAX(version) FROM document WHERE company_id = ? AND logical_name = ?",
            (co["id"], logical),
        ).fetchone()[0]
        stamp = store.now()
        cur = conn.execute(
            "INSERT INTO document (company_id, logical_name, version, sha256, kind, file_type,"
            " privacy, size_bytes, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (co["id"], logical, (last or 0) + 1, digest, kind, file_type, privacy, size, source, stamp),
        )
        conn.execute(
            "INSERT INTO document_state (document_id, state, at) VALUES (?, 'registered', ?)",
            (cur.lastrowid, stamp),
        )
        doc_id = cur.lastrowid
    return "ok", get_document(conn, doc_id)


def add_document(conn, root, file, company, kind="report", privacy="private", name=None, source=None):
    """Register a file. Returns (status, document) with status 'ok' or 'duplicate'."""
    co = _find_company(conn, company)
    src = Path(file)
    file_type = checked_file_type(src)
    digest, size = _store_file(Path(root), src)
    return _register(conn, co, digest, size, file_type, name or logical_name(file), kind, privacy, source)


def add_stored(conn, root, digest, company, name, kind="report", privacy="private", source=None, file_name=None):
    """Register a file already stored under files/ (a download). Returns like add_document.
    file_name (the address's name) is used only to detect the type; it defaults to name."""
    path = stored_path(Path(root), digest)
    return _register(
        conn, _find_company(conn, company), digest, path.stat().st_size, detect_file_type(path, file_name or name),
        name, kind, privacy, source,
    )


def verify(conn, root) -> list[dict]:
    """Re-hash every stored original. Returns one entry per document that is missing or altered."""
    problems = []
    for row in conn.execute("SELECT id, sha256 FROM document ORDER BY id"):
        path = stored_path(Path(root), row["sha256"])
        if not path.is_file():
            problems.append({"document_id": row["id"], "sha256": row["sha256"], "problem": "missing"})
        elif _hash_file(path) != row["sha256"]:
            problems.append({"document_id": row["id"], "sha256": row["sha256"], "problem": "mismatch"})
    return problems
