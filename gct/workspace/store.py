import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
    # isolation_level=None: transactions are explicit (see transaction()).
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection, up_to: int | None = None) -> list[int]:
    """Apply every migration file newer than the recorded schema version. Returns the versions applied."""
    from gct.workspace.layout import REFUSED, GctError  # layout imports this module

    has_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'schema_version'"
    ).fetchone()
    current = 0
    if has_table:
        current = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
    migrations = resources.files("gct.workspace") / "migrations"
    files = sorted(
        ((int(p.name.split("_")[0]), p) for p in migrations.iterdir() if p.name.endswith(".sql")),
        key=lambda vp: vp[0],
    )
    if current > files[-1][0]:
        raise GctError(
            REFUSED,
            "This workspace was made by a newer version of gct than the one installed.",
            "Install the newer version of gct, then run the command again.",
        )
    applied = []
    for version, item in files:
        if version <= current or (up_to is not None and version > up_to):
            continue
        script = (
            "BEGIN;\n"
            + item.read_text(encoding="utf-8")
            + f"\nINSERT INTO schema_version (version, applied_at) VALUES ({version}, '{now()}');\n"
            + "COMMIT;"
        )
        try:
            conn.executescript(script)
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        applied.append(version)
    return applied
