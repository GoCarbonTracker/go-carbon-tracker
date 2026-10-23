"""One published version per report build (story 7.1, C-version V1 to V3). The caller holds the workspace lock."""
import hashlib
import sqlite3

from gct.workspace import labels, published
from gct.workspace.layout import REFUSED, GctError

SCHEMA = 16  # the projection a report reads (part C's match candidates); an older version file is refused


def pin(conn, root, data_version=None) -> tuple[sqlite3.Connection, dict]:
    """(read-only connection to the current version's bytes, their identity). Refuses while a deletion is
    unfinished, a version that still holds a deleted document, no version, a pin that is not current, a missing file
    and a file of an older projection. The file is read once; every query of the build runs on that copy, so a purge
    of the file meanwhile changes nothing the build reads. The causes and next steps are those of view.pinned."""
    from gct.stages import deletion  # the stages import this package
    from gct.workspace import registry

    for (d,) in conn.execute("SELECT DISTINCT document_id FROM document_state WHERE state = 'deleted' ORDER BY 1"):
        if (gone := deletion.status(conn, d)) and gone["pending"]:
            raise GctError(REFUSED, f"Document {d} was deleted but its removal did not finish.",
                           deletion._was_deleted(conn, registry.show_document(conn, d)).next_action)
    current = published.current_version(conn, root)
    if current is None:
        raise GctError(REFUSED, "There is no published data version yet.", "Create one with: gct publish build")
    version, path = current
    if data_version is not None and data_version != version:
        raise GctError(REFUSED, f"Data version {data_version} is no longer the current one; the current version is"
                                f" {version}.", f"Reload to see version {version}.")
    if not path.is_file():
        raise GctError(REFUSED, f"Version {version} is no longer on disk.", published.BUILD_AGAIN)
    if published._holds_deleted(conn, path):
        raise GctError(REFUSED, f"Version {version} still contains a document that has since been deleted.",
                       published.BUILD_AGAIN)
    data = path.read_bytes()
    pconn = sqlite3.connect(":memory:")
    pconn.deserialize(data)
    pconn.execute("PRAGMA query_only = 1")
    pconn.row_factory = sqlite3.Row
    meta = dict(pconn.execute("SELECT key, value FROM meta").fetchall())
    if int(meta.get("projection_schema", 0)) < SCHEMA:
        pconn.close()
        raise GctError(REFUSED, f"Data version {version} was built by an older gct and cannot be filtered.",
                       published.BUILD_AGAIN)
    # A sanitised output shows the first four only (V3); history_mark and labels_mark are for complete mode.
    return pconn, {"version": version, "built_at": meta["built_at"], "sha256": hashlib.sha256(data).hexdigest(),
                   "projection_schema": int(meta["projection_schema"]), "history_mark": meta["history_mark"],
                   "labels_mark": labels.mark(conn)}
