"""Run gct commands with the code of commit BASE, product main just before projection schema 15 (story 7.1 part B;
workspace schema 20, projection 14): B8 builds a projection-14 file with it and B9 compares its outputs. BASE must
know the workspace schema the current code writes, so it moves when main gains a migration before part B lands. The
code comes from `git archive`, so the tests that use it skip outside a git checkout that holds BASE."""
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

BASE = "1c9b602"
NOW = "2026-10-23T09:00:00+00:00"
# One process for all commands. The working directory is the old tree, so it comes first on sys.path and shadows the
# gct the venv points at; the caller checks gct.__file__.
RUN = """
import contextlib, io, json, sys
from gct.workspace import store
if sys.argv[1]:
    store.now = lambda: sys.argv[1]
import gct
from gct import cli
results = []
for argv in json.loads(sys.argv[2]):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    results.append({"code": code, "out": out.getvalue(), "err": err.getvalue()})
print(json.dumps({"gct": gct.__file__, "results": results}))
"""


@pytest.fixture(scope="session")
def old_tree(tmp_path_factory) -> Path:
    try:
        data = subprocess.run(["git", "archive", BASE, "gct"], cwd=Path(__file__).resolve().parent.parent,
                              capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip(f"needs a git checkout containing {BASE}")
    tree = tmp_path_factory.mktemp("old-code")
    with tarfile.open(fileobj=io.BytesIO(data)) as t:  # extraction filters arrived in Python 3.11.4
        t.extractall(tree, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    return tree


def run_old(tree: Path, root: Path, *commands, now: str | None = None) -> list[dict]:
    """[{code, out, err}] of each command (a tuple of arguments) run by the old code on the workspace at root. now
    fixes store.now, so outputs that carry a date can be compared byte for byte."""
    argv = [[*map(str, c), "--workspace", str(root)] for c in commands]
    p = subprocess.run([sys.executable, "-c", RUN, now or "", json.dumps(argv)], cwd=tree, capture_output=True,
                       text=True, env={**os.environ, "PYTHONPATH": str(tree)})
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert Path(out["gct"]).resolve().is_relative_to(tree.resolve()), out["gct"]
    return out["results"]
