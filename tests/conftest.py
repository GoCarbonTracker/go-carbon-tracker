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


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages, size=(612, 792)) -> bytes:
    """A valid PDF (xref offsets computed): one dict per page with 'text' [(x, baseline from top, string)]
    in 12 pt Helvetica and 'lines' [(x0, top0, x1, top1)] stroked, all in points from the top-left."""
    w, h = size
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for p in pages:
        ops = [f"BT /F1 12 Tf 1 0 0 1 {x} {h - top} Tm ({_esc(s)}) Tj ET" for x, top, s in p.get("text", [])]
        ops += [f"{x0} {h - t0} m {x1} {h - t1} l S" for x0, t0, x1, t1 in p.get("lines", [])]
        stream = "\n".join(ops).encode("latin-1")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Resources << /Font << /F1 3 0 R >> >>"
                    f" /Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + (body if isinstance(body, bytes) else body.encode("latin-1")) + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def grid(x, top, cols, rows, cells):
    """A ruled table: column widths and row heights in points, cells row by row ('' leaves a cell empty)."""
    xs = [x + sum(cols[:i]) for i in range(len(cols) + 1)]
    ys = [top + sum(rows[:i]) for i in range(len(rows) + 1)]
    lines = [(xs[0], y, xs[-1], y) for y in ys] + [(cx, ys[0], cx, ys[-1]) for cx in xs]
    text = [(xs[c] + 4, ys[r] + rows[r] - 6, s) for r, row in enumerate(cells) for c, s in enumerate(row) if s]
    return {"text": text, "lines": lines}
