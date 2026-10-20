import secrets
import socket
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

import uvicorn

from gct.api.app import create_app
from gct.workspace.layout import REFUSED, GctError

HOST = "127.0.0.1"  # NFR4: a constant, never an option or an environment variable


@dataclass
class Server:
    url: str
    port: int
    token: str
    _uvicorn: uvicorn.Server = field(repr=False)
    _thread: threading.Thread = field(repr=False)
    _sock: socket.socket = field(repr=False)

    def wait(self) -> None:
        """Block until stopped. Joins in short steps so Ctrl-C reaches the main thread on Windows too."""
        while self._thread.is_alive():
            self._thread.join(0.5)

    def stop(self) -> None:
        self._uvicorn.should_exit = True
        self._thread.join()
        self._sock.close()


def _in_use(port: int) -> bool:
    try:
        socket.create_connection((HOST, port), timeout=0.5).close()
        return True
    except OSError:
        return False


def serve(root: Path, port: int = 0, open_browser: bool = False) -> Server:
    """Start the service on 127.0.0.1 in a thread and return at once."""
    token = secrets.token_urlsafe(32)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":  # allows a quick restart; on Windows the same flag would allow port sharing
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        if port and _in_use(port):  # macOS SO_REUSEADDR binds 127.0.0.1:P beside a 0.0.0.0:P listener
            raise OSError
        sock.bind((HOST, port))
    except (OSError, OverflowError):
        sock.close()
        raise GctError(REFUSED, f"Port {port} is already taken or cannot be used.",
                       "Choose another port with: gct serve --port N") from None
    sock.listen()
    port = sock.getsockname()[1]
    # Access log off: the launch URL carries the token (NFR5).
    config = uvicorn.Config(create_app(root, token), host=HOST, port=port, access_log=False, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, kwargs={"sockets": [sock]}, daemon=True, name="gct-serve")
    thread.start()
    url = f"http://{HOST}:{port}/?token={token}"
    if open_browser:
        webbrowser.open(url)
    return Server(url, port, token, srv, thread, sock)
