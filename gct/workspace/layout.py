import os
from pathlib import Path

from gct import __version__
from gct.workspace import store

DB_NAME = "workspace.db"
SUBDIRS = ("files", "artifacts", "published", "exports", "logs")

# Exit codes (see the CLI section of the story).
USAGE, NOT_FOUND, REFUSED = 2, 3, 4


class GctError(Exception):
    """A refusal the user can act on: exit code, cause, one next action."""

    def __init__(self, code: int, cause: str, next_action: str):
        super().__init__(cause)
        self.code = code
        self.cause = cause
        self.next_action = next_action


def is_workspace(path: Path) -> bool:
    return (path / DB_NAME).is_file()


def locate(explicit: str | None = None) -> Path:
    """--workspace, else GCT_WORKSPACE, else the current directory or nearest parent."""
    for source, value in (("--workspace", explicit), ("GCT_WORKSPACE", os.environ.get("GCT_WORKSPACE"))):
        if value:
            path = Path(value).expanduser()
            if is_workspace(path):
                return path.resolve()
            raise GctError(
                NOT_FOUND,
                f"There is no workspace at {path} (given by {source}).",
                "Check the path, or create a workspace with: gct workspace init PATH",
            )
    here = Path.cwd().resolve()
    for folder in (here, *here.parents):
        if is_workspace(folder):
            return folder
    raise GctError(
        NOT_FOUND,
        "No workspace found.",
        "Point at one with --workspace PATH, set the GCT_WORKSPACE environment variable, "
        "or run the command from inside a workspace folder. "
        "To create one: gct workspace init PATH",
    )


def init_workspace(path: str | Path) -> tuple[str, Path]:
    path = Path(path).expanduser()
    if path.is_file():
        raise GctError(REFUSED, f"{path} is a file, not a folder.", "Choose a new or empty folder.")
    if is_workspace(path):
        return "already_initialised", path.resolve()
    if path.exists() and any(path.iterdir()):
        raise GctError(
            REFUSED,
            f"{path} is not empty and is not a workspace.",
            "Choose a new or empty folder, or point at an existing workspace.",
        )
    path.mkdir(parents=True, exist_ok=True)
    for name in SUBDIRS:
        (path / name).mkdir()
    conn = store.connect(path / DB_NAME)
    try:
        store.migrate(conn)
        conn.execute(
            "INSERT INTO workspace (id, created_at, gct_version) VALUES (1, ?, ?)",
            (store.now(), __version__),
        )
    finally:
        conn.close()
    return "ok", path.resolve()
