"""Story 8.5: checks of the M1 acceptance harness (tests/acceptance.py). Collected by pytest; never starts a pytest
run itself (acceptance.run_suite is replaced for every test here), so the suite does not recurse."""
import fnmatch
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import acceptance
from gct.reports import export

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent


@pytest.fixture(autouse=True)
def no_suite_run(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("test_acceptance.py must never start a pytest run")

    monkeypatch.setattr(acceptance, "run_suite", refuse)


def test_harness_is_run_directly_and_not_collected():
    """AC 1: pytest's default pattern (no python_files in pyproject) does not collect acceptance.py, and this file
    starts no pytest run of its own."""
    options = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]
    assert "python_files" not in options
    assert not any(fnmatch.fnmatch("acceptance.py", p) for p in ("test_*.py", "*_test.py"))
    assert (TESTS / "acceptance.py").is_file()
    source = Path(__file__).read_text()
    assert ("pytest" + ".main") not in source and ('"-m", "pyt' + 'est"') not in source


def test_header_names_python_os_install_head_and_every_pythonpath_entry(monkeypatch):
    """AC 2."""
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(["/a/one", "/b/two"]))
    env = acceptance.environment()
    import gct

    assert env["python"] == sys.version.split()[0] and env["os"] and env["architecture"]
    assert env["gct_file"] == gct.__file__ and env["version"]
    assert env["pythonpath"] == ["/a/one", "/b/two"]
    assert len(env["head"]) == 40
    text = "\n".join(acceptance.header_lines(env))
    for value in ("/a/one", "/b/two", env["head"], gct.__file__, env["architecture"]):
        assert value in text


class FakeDist:
    def __init__(self, direct_url):
        self.direct_url = direct_url

    def read_text(self, name):
        return self.direct_url if name == "direct_url.json" else None


def test_editable_comes_from_direct_url_json():
    """AC 2: an editable install says so in direct_url.json; a wheel install has no dir_info or editable false."""
    assert acceptance.editable(FakeDist('{"url": "file:///x", "dir_info": {"editable": true}}')) is True
    assert acceptance.editable(FakeDist('{"url": "file:///x", "dir_info": {}}')) is False
    assert acceptance.editable(FakeDist(None)) is False


@pytest.mark.parametrize("var", ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"])
def test_git_variables_refuse_before_anything_is_made(tmp_path, var):
    """AC 3: the harness names the variable, exits non-zero and makes no folder (TMPDIR stays empty)."""
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in acceptance.GIT_VARS}
    r = subprocess.run([sys.executable, str(TESTS / "acceptance.py")], capture_output=True, text=True, cwd=tmp_path,
                       env={**env, var: str(tmp_path / "x"), "TMPDIR": str(tmp)})
    assert r.returncode != 0 and var in r.stdout + r.stderr
    assert list(tmp.iterdir()) == []


def fake_script(tmp_path, stdout, code):
    """A stand-in console script printing stdout and exiting with code."""
    path = tmp_path / "fake-gct"
    path.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write({stdout!r})\nsys.exit({code})\n")
    path.chmod(0o755)
    return path


def test_step_runner_checks_exit_code_and_status(tmp_path):
    """AC 4: exit 0 with a status other than ok fails, and so does status ok with a non-zero exit."""
    ws = tmp_path / "ws"
    partial = acceptance.run_step(["read"], ws, fake_script(tmp_path, '{"status": "partial"}', 0))
    assert not partial["ok"] and partial["status"] == "partial"
    nonzero = acceptance.run_step(["read"], ws, fake_script(tmp_path, '{"status": "ok"}', 1))
    assert not nonzero["ok"] and nonzero["code"] == 1
    fine = acceptance.run_step(["read"], ws, fake_script(tmp_path, '{"status": "ok"}', 0))
    assert fine["ok"] and fine["argv"][-3:] == ["--workspace", str(ws), "--json"]


def test_step_runner_special_cases_version_and_workspace_init(tmp_path):
    """AC 4: gct --version is text only, exit 0, run without --json; workspace init gets no --workspace."""
    script = acceptance.gct_script()
    version = acceptance.run_step(["--version"], tmp_path / "ws", script)
    assert version["ok"] and version["argv"] == [str(script), "--version"]
    assert version["out"].startswith("gct ")
    init = acceptance.run_step(["workspace", "init", str(tmp_path / "ws"), "--json"], tmp_path / "ws", script)
    assert init["ok"] and "--workspace" not in init["argv"]


def test_step_runner_reports_a_refusal_verbatim(tmp_path, gct):
    """AC 4: report before publish build refuses; the step carries the code's cause and next_action unchanged."""
    ws = tmp_path / "ws"
    script = acceptance.gct_script()
    assert acceptance.run_step(["workspace", "init", str(ws), "--json"], ws, script)["ok"]
    step = acceptance.run_step(["report", "all", "--format", "json"], ws, script)
    direct = gct("report", "all", "--format", "json", "--workspace", ws, "--json")
    assert direct.code != 0 and direct.data["status"] == "error"
    assert not step["ok"] and step["code"] == direct.code
    assert (step["cause"], step["next_action"]) == (direct.data["cause"], direct.data["next_action"])
    lines = acceptance.step_lines(step)
    assert f"cause: {direct.data['cause']}" in lines and f"next_action: {direct.data['next_action']}" in lines


def test_report_step_takes_every_format_from_export_formats(monkeypatch):
    """AC 5: no format list in the harness; a format added to export.FORMATS is asked for."""
    monkeypatch.setitem(export.FORMATS, "fake", {"write": None, "crops": False})
    argv = acceptance.report_argv()
    assert argv[:3] == ["report", "all", "--format"] and argv[3].split(",") == list(export.FORMATS)
    assert "fake" in argv[3].split(",")


SEEDS = [{"kind": "path", "name": "path seed", "value": "ZqAccPathSeed"},
         {"kind": "contributor", "name": "contributor seed", "value": "ZqAccContribSeed"}]


def scan_tree(tmp_path, db=b"ZqAccPathSeed ZqAccContribSeed", export_text=b"nothing private here"):
    ws = tmp_path / "ws"
    (ws / "exports" / "one").mkdir(parents=True)
    (ws / "workspace.db").write_bytes(db)
    (ws / "exports" / "one" / "dataset.json").write_bytes(export_text)
    return ws


def test_scan_finds_both_seeds_in_the_database_and_none_in_exports(tmp_path):
    """AC 6: the positive control and the clean exports."""
    assert acceptance.check_scan(scan_tree(tmp_path), SEEDS) == []


def test_scan_fails_when_the_positive_control_misses_a_seed(tmp_path):
    problems = acceptance.check_scan(scan_tree(tmp_path, db=b"ZqAccPathSeed only"), SEEDS)
    assert problems and "contributor seed" in problems[0] and "workspace.db" in problems[0]


def test_scan_fails_when_a_seed_is_in_an_export(tmp_path):
    problems = acceptance.check_scan(scan_tree(tmp_path, export_text=b"by ZqAccContribSeed"), SEEDS)
    assert problems and "one" in problems[0] and "contributor seed" in problems[0]


def test_scan_fails_on_a_part_it_cannot_read(tmp_path):
    """AC 6: leakage.Unreadable fails the line, it is never swallowed."""
    ws = scan_tree(tmp_path)
    (ws / "exports" / "one" / "broken.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 40)
    problems = acceptance.check_scan(ws, SEEDS)
    assert problems and "could not read" in problems[0] and "broken.png" in problems[0]


def test_scan_fails_with_no_export_folder(tmp_path):
    ws = scan_tree(tmp_path)
    (ws / "exports" / "one" / "dataset.json").unlink()
    (ws / "exports" / "one").rmdir()
    assert acceptance.check_scan(ws, SEEDS) == ["no export folder under exports/"]
