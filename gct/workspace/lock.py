"""One writing gct command per workspace at a time: an OS file lock, released by the OS when the process ends."""
import os
from pathlib import Path

from gct.workspace.layout import REFUSED, GctError

NAME = "workspace.lock"


def hold(root):
    """Lock <root>/workspace.lock without waiting. Returns the open file; release() frees the lock."""
    f = open(Path(root) / NAME, "a+b")
    try:
        if os.name == "nt":
            # ponytail: Windows branch untested until the NFR19 acceptance pass.
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        raise GctError(REFUSED, "Another gct command is using this workspace.",
                       "Wait for it to finish, then run the command again.") from None
    return f


def release(f):
    """Unlock and close a file returned by hold(). Windows asks for the unlock before the close."""
    if os.name == "nt":
        import msvcrt

        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    f.close()
