import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from conftest import make_pdf

ROOT = Path(__file__).resolve().parent.parent


NO_NETWORK_SCRIPT = """
import importlib, pkgutil, socket, sys

def refuse(*a, **k):
    raise AssertionError("network access attempted")

class Refused(socket.socket):
    def __init__(self, *a, **k):
        refuse()

socket.socket = Refused
for name in ("create_connection", "getaddrinfo", "gethostbyname"):
    setattr(socket, name, refuse)

import gct
for mod in pkgutil.walk_packages(gct.__path__, "gct."):
    if mod.name != "gct.__main__":
        importlib.import_module(mod.name)
from gct import cli
for argv in (["workspace", "init", sys.argv[1]], ["company", "add", "Acme", "--workspace", sys.argv[1]],
             ["doc", "add", sys.argv[2], "--company", "Acme", "--workspace", sys.argv[1]],
             ["read", "--workspace", sys.argv[1]], ["run", "retry", "2", "--workspace", sys.argv[1]],
             ["extract", "--workspace", sys.argv[1]], ["model", "list"],
             ["approve", "spend", "1", "--workspace", sys.argv[1]]):
    assert cli.main(argv) == 0
"""


def test_no_network(tmp_path, make_file):
    r = subprocess.run(
        [sys.executable, "-c", NO_NETWORK_SCRIPT, str(tmp_path / "ws"), str(make_file("a.pdf", make_pdf([{"text": [(72, 72, "Scope 1")]}])))],
        cwd=ROOT, capture_output=True, text=True, env={**os.environ, "GCT_MODELS": str(tmp_path / "no-models.toml")},
    )
    assert r.returncode == 0, r.stderr


def test_company_list_does_not_import_pdfplumber(tmp_path):
    script = (
        "import sys\nfrom gct import cli\n"
        "assert cli.main(['workspace', 'init', sys.argv[1]]) == 0\n"
        "assert cli.main(['company', 'list', '--workspace', sys.argv[1]]) == 0\n"
        "assert not {'pdfplumber', 'reportlab', 'PIL'} & set(sys.modules), sorted(sys.modules)\n"
    )
    r = subprocess.run([sys.executable, "-c", script, str(tmp_path / "ws")], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_no_runtime_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["dependencies"] == ["fastapi>=0.115", "uvicorn>=0.30", "pdfplumber>=0.11", "pypdfium2>=5.9", "openpyxl>=3.1.5", "reportlab>=5.1", "pillow>=10"]
    assert project["requires-python"] == ">=3.11"
    assert project["optional-dependencies"]["dev"] == ["pytest", "jsonschema>=4.26"]


def test_python_dash_m_gct_help():
    r = subprocess.run([sys.executable, "-m", "gct", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "workspace" in r.stdout


def test_console_script_help():
    script = Path(sys.executable).parent / ("gct.exe" if sys.platform == "win32" else "gct")
    if not script.exists():
        pytest.skip("gct is not installed in this environment (pip install -e '.[dev]')")
    r = subprocess.run([str(script), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "workspace" in r.stdout


def test_no_home_paths_or_large_files():
    """The committed viewer build is the likeliest place for either to slip in."""
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True).stdout.split("\0")
    home = str(Path.home()).encode()
    anyone_home = re.compile(rb"/(?:Users|home)/[A-Za-z0-9._-]+/")  # also on another contributor's machine or CI
    for name in filter(None, tracked):
        path = ROOT / name
        if path.is_file():
            assert path.stat().st_size < 1_000_000, name
            data = path.read_bytes()
            assert home not in data and not anyone_home.search(data), name


ALLOWED_REMOTES = (
    "github.com/gocarbontracker/gct-release",
    "github.com/gocarbontracker/go-carbon-tracker",
)


def test_licence_files_and_remotes_limited_to_private_backup():
    assert (ROOT / "LICENSE").read_text().startswith("MIT License")
    assert "GoCarbonTracker contributors" in (ROOT / "LICENSE").read_text()
    assert (ROOT / "ORIGINS.md").exists()
    if (ROOT / ".git").exists():
        r = subprocess.run(["git", "remote", "-v"], cwd=ROOT, capture_output=True, text=True)
        for line in r.stdout.splitlines():
            url = line.split()[1].lower().removesuffix(".git")
            assert any(url.endswith(target) for target in ALLOWED_REMOTES), f"remote not allowed before gate G3: {line}"


RETIRED_NOTICE = "Private content is excluded from this output."


def test_the_retired_privacy_notice_appears_nowhere():
    """A sanitised output is designed to leave private content out and is not verified to (README, Status). Its notice
    says so, and the sentence that promised exclusion stays out of the code, the docs and the README."""
    files = [*(ROOT / "gct").rglob("*.py"), *(ROOT / "docs").rglob("*.md"), ROOT / "README.md"]
    assert [str(p.relative_to(ROOT)) for p in sorted(files) if RETIRED_NOTICE in p.read_text()] == []
