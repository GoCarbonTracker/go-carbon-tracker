import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from conftest import PDF

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
             ["doc", "add", sys.argv[2], "--company", "Acme", "--workspace", sys.argv[1]]):
    assert cli.main(argv) == 0
"""


def test_no_network(tmp_path, make_file):
    r = subprocess.run(
        [sys.executable, "-c", NO_NETWORK_SCRIPT, str(tmp_path / "ws"), str(make_file("a.pdf", PDF))],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_no_runtime_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["dependencies"] == ["fastapi>=0.115", "uvicorn>=0.30"]
    assert project["requires-python"] == ">=3.11"
    assert project["optional-dependencies"]["dev"] == ["pytest"]


def test_python_dash_m_gct_help():
    r = subprocess.run([sys.executable, "-m", "gct", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "workspace" in r.stdout


def test_console_script_help():
    script = Path(sys.executable).parent / ("gct.exe" if sys.platform == "win32" else "gct")
    if not script.exists():
        pytest.skip("gct is not installed in this environment (pip install -e '.[dev]')")
    r = subprocess.run([str(script), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "workspace" in r.stdout


PRIVATE_BACKUP = "github.com/gocarbontracker/gct-release"


def test_licence_files_and_remotes_limited_to_private_backup():
    assert (ROOT / "LICENSE").read_text().startswith("MIT License")
    assert "GoCarbonTracker contributors" in (ROOT / "LICENSE").read_text()
    assert (ROOT / "ORIGINS.md").exists()
    if (ROOT / ".git").exists():
        r = subprocess.run(["git", "remote", "-v"], cwd=ROOT, capture_output=True, text=True)
        # Public publication stays blocked (gate G3): the only allowed remote is the private backup.
        for line in r.stdout.splitlines():
            url = line.split()[1].lower().removesuffix(".git")
            assert url.endswith(PRIVATE_BACKUP), f"remote not allowed before gate G3: {line}"
