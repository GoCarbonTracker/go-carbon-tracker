"""gct troubleshoot export (story 8.3 B): one new folder under exports/ with troubleshooting.json and
troubleshooting.txt, holding versions, counts, the run log reduced to product text and the newest error logs reduced
to gct frames, with nothing that names a document, a company, a contributor, a folder or a key (NFR5, prd:648)."""
import ast
import json
import os
import re
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path, PureWindowsPath

import pytest

import report_fixture as f
from conftest import PDF
from gct import cli
from gct.models import redact
from gct.reports import export, package
from gct.workspace import layout, lock, registry, troubleshoot
from leakage import found
from test_hygiene import NO_NETWORK_SCRIPT
from test_json import check
from test_runs import old_ws  # noqa: F401 (a fixture)

ROOT = Path(__file__).resolve().parent.parent
ANYONE_HOME = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/")  # tests/test_hygiene.py:88, as text
ABSOLUTE = re.compile(r"(?:^|[\s\"'(=])/[^\s/\"]+|[A-Za-z]:\\")


def export_folder(gct, *argv):
    r = gct("troubleshoot", "export", *argv, "--json")
    assert r.code == 0, (r.out, r.err)
    return r


def files(ws):
    return sorted(p.relative_to(ws / "exports").as_posix() for p in (ws / "exports").rglob("*"))


def data_of(ws, r) -> dict:
    return json.loads((ws / r.data["folder"] / "troubleshooting.json").read_text(encoding="utf-8"))


# AC 6
def test_export_writes_one_new_folder_with_exactly_the_two_files(ws, gct):
    r = export_folder(gct)
    check("troubleshoot export", r.data)
    stem = r.data["folder"]
    assert re.fullmatch(r"exports/troubleshooting-\d{8}T\d{12}Z/", stem), stem
    assert r.data["files"] == ["troubleshooting.json", "troubleshooting.txt"]
    assert files(ws) == [stem[len("exports/"):-1], *(stem[len("exports/"):] + n for n in r.data["files"])]
    text = gct("troubleshoot", "export")
    assert text.code == 0 and text.err == ""
    first, second = text.out.splitlines()
    assert re.fullmatch(r"Wrote exports/troubleshooting-\d{8}T\d{12}Z/ \(troubleshooting.json, troubleshooting.txt\)\.",
                        first), first
    assert second == "Read both files before you send them to anyone; they hold no document, company or contributor name."


def test_the_readme_names_the_export_and_the_troubleshooting_guide():
    """R3 (granted by E7 2026-10-23): one bullet under "What works today"."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    works = readme.split("## What works today\n", 1)[1].split("\n## ", 1)[0]
    (bullet,) = [line for line in works.splitlines() if "gct troubleshoot export" in line]
    assert bullet.startswith("- ") and "docs/troubleshooting.md" in bullet and "gct --version" in bullet


# AC 7
def test_keys_follow_the_docs_and_the_package_columns(ws, gct, make_file):
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme")
    d = data_of(ws, export_folder(gct))
    doc = (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
    assert list(d) == re.findall(r"^- `(\w+)`:", doc, re.M)
    keep = lambda table: [c for c, k in package.COLUMNS[table].items() if k == "keep"]
    assert d["runs"] and all(list(run) == [*keep("run"), "outcome", "events"] for run in d["runs"])
    assert all(list(e) == [*keep("run_event"), "message"] for run in d["runs"] for e in run["events"])


def test_text_file_holds_only_what_the_json_holds(ws, gct, make_file):
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme")
    r = export_folder(gct)
    d = data_of(ws, r)
    lines = (ws / r.data["folder"] / "troubleshooting.txt").read_text(encoding="utf-8").splitlines()
    assert lines == list(troubleshoot.lines(d)) and len(lines) > 10
    for line in lines:
        key, value = line.split(": ", 1)
        x = d
        for part in key.split("."):
            x = x[int(part)] if isinstance(x, list) else x[part]
        assert value == (x if isinstance(x, str) else json.dumps(x)), line


def test_the_module_never_collects_host_user_folder_or_environment():
    tree = ast.parse((ROOT / "gct" / "workspace" / "troubleshoot.py").read_text(encoding="utf-8"))
    used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    banned = {"node", "uname", "gethostname", "getuser", "getpass", "getlogin", "executable", "prefix", "base_prefix",
              "exec_prefix", "getcwd", "cwd", "environ", "getenv", "argv"}
    assert not used & banned, used & banned


# AC 8, 9: the leakage gate

@pytest.fixture(scope="module")
def leaky(tmp_path_factory):
    """The report fixture workspace with its key in the environment, one refused doc add whose missing file is named
    by seeds, and one unexpected error whose text carries DOC-NAME-01, PATH-01 and CRED-TEXT-01."""
    models = tmp_path_factory.mktemp("models") / "models.toml"
    models.write_text(f.MODELS)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GCT_MODELS", str(models))
        mp.setenv(f.API_KEY_ENV, f.CRED_ENV)
        redact._names.cache_clear()
        ws = f.build(tmp_path_factory.mktemp("w") / "ws")
        missing = tmp_path_factory.mktemp(f.PATH) / f"{f.NAME}.pdf"
        assert cli.main(["doc", "add", str(missing), "--company", "Acme", "--workspace", str(ws)]) == 4
        def boom(*a):
            raise RuntimeError(f"{f.NAME} in {f.PATH} with {f.CRED_TEXT}")

        mp.setattr(registry, "list_companies", boom)
        assert cli.main(["company", "list", "--workspace", str(ws)]) == 1
        mp.undo()
        yield ws, models
    redact._names.cache_clear()


@pytest.fixture
def leaky_env(leaky, monkeypatch):
    """The fixture's models file and key variable for one test (conftest's autouse fixture points GCT_MODELS away)."""
    ws, models = leaky
    monkeypatch.setenv("GCT_MODELS", str(models))
    monkeypatch.setenv(f.API_KEY_ENV, f.CRED_ENV)
    redact._names.cache_clear()
    return ws


def test_the_inputs_hold_the_seeds(leaky_env, gct):
    leaky = leaky_env
    (log,) = (leaky / "logs").glob("error-*.log")
    assert {"DOC-NAME-01", "PATH-01"} <= set(found(log, f.SEEDS))
    runs = gct("run", "list", "--workspace", leaky, "--json").data["runs"]
    shown = [gct("run", "show", r["id"], "--workspace", leaky, "--json").out for r in runs]
    assert any(f.PATH in s for s in shown) and any(f.NAME in s for s in shown)


def test_the_export_holds_no_seed_no_home_and_no_absolute_path(leaky_env, gct):
    leaky = leaky_env
    before = gct("run", "list", "--workspace", leaky, "--json").out
    r = export_folder(gct, "--workspace", leaky)
    folder = leaky / r.data["folder"]
    assert found(folder, f.SEEDS) == {}
    d = json.loads((folder / "troubleshooting.json").read_text(encoding="utf-8"))
    assert d["error_logs"] and d["error_logs"][0]["exceptions"] == ["RuntimeError"]
    assert any(fr.startswith("gct/cli.py:") for fr in d["error_logs"][0]["frames"])
    messages = [e["message"] for run in d["runs"] for e in run["events"] if e["message"]]
    assert "The file {} does not exist." in messages
    homes = {str(Path.home()), str(Path.home().resolve())}
    for name in ("troubleshooting.json", "troubleshooting.txt"):
        text = (folder / name).read_text(encoding="utf-8")
        for path in (str(leaky), str(leaky.resolve()), *homes):
            assert path not in text, (name, path)
        assert not ANYONE_HOME.search(text) and not ABSOLUTE.search(text), name
        assert os.uname().nodename not in text
    assert gct("run", "list", "--workspace", leaky, "--json").out == before


def test_the_workspace_as_named_and_resolved_and_a_symlinked_home_become_placeholders(tmp_path, monkeypatch):
    for real, link in (("ws-real", "ws-link"), ("home-real", "home-link")):
        (tmp_path / real).mkdir()
        (tmp_path / link).symlink_to(tmp_path / real)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home-link")
    real, link = (tmp_path / "ws-real").resolve(), tmp_path / "ws-link"
    text = f"{link}/a {real}/b {tmp_path}/home-link/c {(tmp_path / 'home-real').resolve()}/d"
    marks = troubleshoot.placeholders(real, [link])
    assert troubleshoot.clean(text, marks) == "<workspace>/a <workspace>/b <home>/c <home>/d"
    assert troubleshoot.clean({"x": [f"see {tmp_path}/other"]}, marks) == {"x": ["[path removed]"]}
    assert troubleshoot.clean("in C:\\Users\\ana\\x", marks) == "[path removed]"


# AC 10: failure messages

SOURCE = '''
def a(p, x, b):
    raise GctError(REFUSED, f"The file {p} does not exist.", "n")
    raise layout.GctError(REFUSED, f"{x}", "n")
    raise GctError(REFUSED, "Another gct command is using this workspace.", "n")
    raise GctError(REFUSED, "a" + b, "n")
    raise GctError(REFUSED, f"The file {p} could not be read.", "n")
    raise GctError(REFUSED, f"The {p} could not be {x}.", "n")
'''


def test_a_failure_message_becomes_its_template_a_class_name_stays_anything_else_is_withheld():
    t = troubleshoot.templates([SOURCE])
    assert [x for x, _ in t] == ["The file {} does not exist.", "Another gct command is using this workspace.",
                                 "The file {} could not be read.", "The {} could not be {}."]
    m = lambda s: troubleshoot.reduce_message(s, t)
    assert m("The file /Users/ana/Secret Client.pdf does not exist.") == "The file {} does not exist."
    assert m("Another gct command is using this workspace.") == "Another gct command is using this workspace."
    assert m("The file x could not be read.") == "The file {} could not be read."  # first match in source order
    assert m("KeyError") == "KeyError" and m("BadZipFile") == "BadZipFile"
    assert m("GCT-PRIVATE-CANARY-06") == "withheld" and m("Secret Client") == "withheld"
    assert m("Another gct command is using this workspace. Extra") == "withheld"  # anchored at both ends
    assert troubleshoot.reduce_message("The file x does not exist.", troubleshoot.templates([])) == "withheld"


def test_the_installed_sources_give_templates(ws):
    t = troubleshoot.templates(troubleshoot.sources())
    assert "Another gct command is using this workspace." in [x for x, _ in t]
    assert troubleshoot.reduce_message("There is no run with id 7.", t) == "There is no run with id {}."
    assert all(re.search(r"[A-Za-z]", x.replace("{}", "")) for x, _ in t)


# AC 11: error-log reduction

def log_text(sep, root, ext):
    return f"""Traceback (most recent call last):
  File "{root}{sep}gct{sep}cli.py", line 29, in _open
    conn = store.connect(args.root / layout.DB_NAME)
  File "{ext}{sep}sqlite3{sep}x.py", line 5, in go
    raise sqlite3.OperationalError("unable to open /Users/ana/Secret Client.pdf")
sqlite3.OperationalError: unable to open /Users/ana/Secret Client.pdf

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "{root}{sep}gct{sep}stages{sep}sheet.py", line 137, in _book
    raise GctError(REFUSED, cause)
    ~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^
gct.workspace.layout.GctError: Document GCT-PRIVATE-CANARY-06 could not be read
"""


@pytest.mark.parametrize("sep, root, ext, package_dir", [
    ("/", "/Users/ana/src/gct-release", "/opt/python/lib", Path("/Users/ana/src/gct-release/gct")),
    ("\\", "C:\\Users\\ana\\src", "C:\\Python313\\Lib", PureWindowsPath("C:\\Users\\ana\\src\\gct"))])
def test_an_error_log_keeps_gct_frames_counts_the_rest_and_drops_text(sep, root, ext, package_dir):
    r = troubleshoot.reduce_log(log_text(sep, root, ext), package_dir)
    assert r == {"frames": ["gct/cli.py:29 in _open", "gct/stages/sheet.py:137 in _book"], "other_frames": 1,
                 "exceptions": ["sqlite3.OperationalError", "gct.workspace.layout.GctError"]}


def test_error_logs_are_the_newest_five(ws, gct, monkeypatch):
    monkeypatch.setattr(registry, "list_companies", lambda *a: 1 / 0)
    for _ in range(7):
        assert gct("company", "list").code == 1
    monkeypatch.undo()
    monkeypatch.setenv("GCT_WORKSPACE", str(ws))
    logs = sorted(p.name for p in (ws / "logs").glob("error-*.log"))
    d = data_of(ws, export_folder(gct))
    assert [x["file"] for x in d["error_logs"]] == logs[::-1][:5]
    assert all(x["exceptions"] == ["ZeroDivisionError"] for x in d["error_logs"])


# AC 12

def test_dependencies_are_the_declared_runtime_and_dev_libraries(ws, gct):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = [re.match(r"[A-Za-z0-9_.-]+", x)[0] for x in project["dependencies"] + project["optional-dependencies"]["dev"]]
    assert list(troubleshoot.DEPENDENCIES) == names
    d = data_of(ws, export_folder(gct))
    assert list(d["dependencies"]) == names and d["dependencies"]["pytest"] == __import__("pytest").__version__


# AC 13

def test_the_export_takes_no_lock_and_records_no_run(ws, gct, make_file, monkeypatch):
    gct("company", "add", "Acme")
    a, b = make_file("a.pdf"), make_file("b.pdf", PDF + b"b")
    real = registry.add_document

    def stop(conn, root, src, *rest):
        if src.endswith("b.pdf"):
            raise KeyboardInterrupt
        return real(conn, root, src, *rest)

    monkeypatch.setattr(registry, "add_document", stop)
    with pytest.raises(KeyboardInterrupt):
        gct("doc", "add", a, b, "--company", "Acme")
    monkeypatch.setattr(registry, "add_document", real)
    dump = lambda: list(sqlite3.connect(ws / "workspace.db").iterdump())
    before, listed = dump(), gct("run", "list", "--json").out
    held = lock.hold(ws)
    try:
        export_folder(gct)
    finally:
        lock.release(held)
    assert dump() == before and gct("run", "list", "--json").out == listed
    r = gct("run", "resume", 1, "--json")
    assert r.code == 0 and [i["action"] for i in r.data["items"]] == ["duplicate", "registered"]


def test_an_older_workspace_is_upgraded_under_the_lock_like_run_list(old_ws, gct):  # noqa: F811
    held = lock.hold(old_ws)
    try:
        r = gct("troubleshoot", "export", "--workspace", old_ws, "--json")
    finally:
        lock.release(held)
    assert r.code == 4 and r.data["cause"] == "Another gct command is using this workspace."
    assert not list((old_ws / "exports").iterdir())
    d = data_of(old_ws, export_folder(gct, "--workspace", old_ws))
    assert [m["version"] for m in d["workspace"]["migrations"]] == list(range(1, d["workspace"]["schema_version"] + 1))
    assert [r["command"] for r in d["runs"]] == ["workspace upgrade"]
    assert d["workspace"]["created_by_gct"] == "0.0.0" and d["counts"]["companies"] == 1


# AC 14

def test_a_writer_failure_leaves_no_folder_and_two_exports_give_two_folders(ws, gct, monkeypatch):
    monkeypatch.setattr(troubleshoot, "lines", lambda d: 1 / 0)
    assert gct("troubleshoot", "export").code == 1
    assert [p.name for p in (ws / "exports").iterdir()] == []
    monkeypatch.undo()
    monkeypatch.setenv("GCT_WORKSPACE", str(ws))
    monkeypatch.setattr(export, "stamp", lambda: "20261023T000000000000Z")
    export_folder(gct)
    r = gct("troubleshoot", "export", "--json")
    assert r.code == 4 and "already exists" in r.data["cause"]
    monkeypatch.undo()
    monkeypatch.setenv("GCT_WORKSPACE", str(ws))
    export_folder(gct)
    export_folder(gct)
    assert len([p for p in (ws / "exports").iterdir() if p.name.startswith("troubleshooting-")]) == 3
    assert not [p for p in (ws / "exports").iterdir() if p.name.startswith(".incoming-")]


# AC 15

def test_an_empty_workspace(ws, gct):
    d = data_of(ws, export_folder(gct))
    assert d["runs"] == [] and d["error_logs"] == []
    assert d["counts"] == {"companies": 0, "documents": {}, "pages": {}, "claims": 0}
    assert d["workspace"]["published_version"] is None and d["gct"]["version"] == cli.__version__


def test_a_malformed_models_file_does_not_stop_the_export(ws, gct, tmp_path, monkeypatch):
    bad = tmp_path / "models.toml"
    bad.write_text("[adapters.x\n")
    monkeypatch.setenv("GCT_MODELS", str(bad))
    redact._names.cache_clear()
    export_folder(gct)


def test_the_export_runs_with_sockets_banned(tmp_path):
    ban = NO_NETWORK_SCRIPT.split("import gct\n")[0]
    script = ban + ("from gct import cli\n"
                    "assert cli.main(['workspace', 'init', sys.argv[1]]) == 0\n"
                    "assert cli.main(['troubleshoot', 'export', '--workspace', sys.argv[1]]) == 0\n")
    r = subprocess.run([sys.executable, "-c", script, str(tmp_path / "ws")], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "GCT_MODELS": str(tmp_path / "no-models.toml")})
    assert r.returncode == 0, r.stderr
