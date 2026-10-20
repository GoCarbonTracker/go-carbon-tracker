import json
import sqlite3
import zipfile
from types import SimpleNamespace

import pytest

from gct import cli

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n"


@pytest.fixture
def gct(capsys):
    """Run the CLI in-process. Returns an object with code, out, err and (for --json) data."""

    def run(*argv):
        try:
            code = cli.main([str(a) for a in argv])
        except SystemExit as e:
            code = e.code or 0
        out, err = capsys.readouterr()
        data = None
        if "--json" in argv and out.strip():
            data = json.loads(out)
        return SimpleNamespace(code=code, out=out, err=err, data=data)

    return run


@pytest.fixture
def ws(tmp_path, gct, monkeypatch):
    """A fresh workspace, also selected through GCT_WORKSPACE so tests can omit --workspace."""
    root = tmp_path / "ws"
    assert gct("workspace", "init", root).code == 0
    monkeypatch.setenv("GCT_WORKSPACE", str(root))
    return root


@pytest.fixture
def db(ws):
    """A plain SQLite connection (no triggers bypassed, no gct code) to inspect rows."""
    conn = sqlite3.connect(ws / "workspace.db")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def make_file(tmp_path):
    def make(name, content=PDF):
        path = tmp_path / "src" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
        return path

    return make


def xlsx_bytes(tmp_path, parts=("[Content_Types].xml", "xl/workbook.xml")):
    path = tmp_path / "x.zip"
    with zipfile.ZipFile(path, "w") as z:
        for p in parts:
            z.writestr(p, "<x/>")
    return path.read_bytes()
