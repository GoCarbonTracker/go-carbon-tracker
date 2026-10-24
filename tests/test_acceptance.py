"""Story 8.5: checks of the M1 acceptance harness (tests/acceptance.py). Collected by pytest; never starts a pytest
run itself (acceptance.run_suite is replaced for every test here), so the suite does not recurse."""
import fnmatch
import json
import os
import subprocess
import sys
import tomllib
import urllib.error
from pathlib import Path

import pytest

import acceptance
import leakage
from gct.reports import export
from test_assistant_claude import ASSISTANT, WORKFLOW, replay_lines

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


def test_harness_runs_directly(tmp_path):
    """AC 1: python tests/acceptance.py runs as a script (--help stops before anything is made)."""
    env = {k: v for k, v in os.environ.items() if k not in acceptance.GIT_VARS}
    r = subprocess.run([sys.executable, str(TESTS / "acceptance.py"), "--help"], capture_output=True, text=True,
                       cwd=tmp_path, env=env)
    assert r.returncode == 0 and "--g2-report" in r.stdout and list(tmp_path.iterdir()) == []


@pytest.fixture
def no_folder(monkeypatch):
    """Fails a test whose harness run would make its temporary folder."""
    def refuse(*a, **k):
        raise AssertionError("the harness made a folder")

    monkeypatch.setattr(acceptance.tempfile, "mkdtemp", refuse)


@pytest.mark.parametrize("var", ["GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"])
def test_git_variables_refuse_before_anything_is_made(tmp_path, monkeypatch, capsys, no_folder, var):
    """AC 3: the harness names the variable, exits non-zero and makes no folder. In process, so a broken guard
    cannot start a suite run."""
    monkeypatch.setenv(var, str(tmp_path / "x"))
    assert acceptance.main([]) == 2
    assert var in capsys.readouterr().out


def fake_script(tmp_path, stdout, code):
    """A stand-in console script printing stdout and exiting with code."""
    path = tmp_path / "fake-gct"
    path.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write({stdout!r})\nsys.exit({code})\n")
    path.chmod(0o755)
    return path


def step(command, stated, tmp_path, script):
    """One step on tmp_path/ws, as the workflow runs it."""
    return acceptance.run_step(command, stated, tmp_path / "ws", tmp_path / "report.pdf", script, dict(os.environ))


def test_step_runner_checks_the_stated_code_and_status(tmp_path):
    """AC 4: a line stating 0 ok fails on exit 0 with partial and on status ok with exit 1; a stated refusal
    (4 error) passes; --json and --workspace are appended as the 8.1 grammar says."""
    partial = step("gct read", (0, "ok"), tmp_path, fake_script(tmp_path, '{"status": "partial"}', 0))
    assert not partial["ok"] and partial["status"] == "partial"
    nonzero = step("gct read", (0, "ok"), tmp_path, fake_script(tmp_path, '{"status": "ok"}', 1))
    assert not nonzero["ok"] and nonzero["code"] == 1
    assert step("gct report preview", (4, "error"), tmp_path, fake_script(tmp_path, '{"status": "error"}', 4))["ok"]
    fine = step("gct read", (0, "ok"), tmp_path, fake_script(tmp_path, '{"status": "ok"}', 0))
    assert fine["ok"] and fine["argv"][1:] == ["read", "--workspace", str(tmp_path / "ws"), "--json"]


def test_step_runner_runs_version_as_text_and_workspace_init_without_workspace(tmp_path):
    """AC 4: gct --version is text only, exit 0, run without --json; workspace init gets no --workspace."""
    script = acceptance.gct_script()
    version = step(acceptance.VERSION, (0, None), tmp_path, script)
    assert version["ok"] and version["argv"] == [str(script), "--version"] and version["status"] is None
    init = step("gct workspace init <WORKSPACE>", (0, "ok"), tmp_path, script)
    assert init["ok"] and "--workspace" not in init["argv"]


def test_step_runner_reports_a_refusal_verbatim(tmp_path, gct):
    """AC 4: a step that does not give its stated result carries the code's cause and next_action unchanged."""
    script = acceptance.gct_script()
    assert step("gct workspace init <WORKSPACE>", (0, "ok"), tmp_path, script)["ok"]
    got = step("gct report all --format json", (0, "ok"), tmp_path, script)
    direct = gct("report", "all", "--format", "json", "--workspace", tmp_path / "ws", "--json")
    assert direct.code != 0 and direct.data["status"] == "error"
    assert not got["ok"] and (got["code"], got["status"]) == (direct.code, "error")
    assert (got["cause"], got["next_action"]) == (direct.data["cause"], direct.data["next_action"])
    lines = acceptance.step_lines(got)
    assert f"  cause: {direct.data['cause']}" in lines and f"  next_action: {direct.data['next_action']}" in lines


def test_serve_is_stopped_when_the_run_is_interrupted(tmp_path, monkeypatch):
    """Section 4: gct serve on a workspace with no document answers page 1 with an error (the step fails), and a
    Ctrl-C while the page is fetched still stops the server."""
    script, env = acceptance.gct_script(), dict(os.environ)
    assert step("gct workspace init <WORKSPACE>", (0, "ok"), tmp_path, script)["ok"]
    missing = acceptance.serve_page(acceptance.SERVE, (0, "ok"), tmp_path / "ws", tmp_path / "x.pdf", script, env)
    assert missing["status"] == "ok" and not missing["ok"] and not missing["page"].startswith("HTTP 200")
    started, real = [], subprocess.Popen
    monkeypatch.setattr(acceptance.subprocess, "Popen", lambda *a, **k: started.append(real(*a, **k)) or started[-1])

    class NoAnswer:
        def open(self, *a, **k):
            raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(acceptance.urllib.request, "build_opener", lambda *a: NoAnswer())
    silent = acceptance.serve_page(acceptance.SERVE, (0, "ok"), tmp_path / "ws", tmp_path / "x.pdf", script, env)
    assert not silent["ok"] and silent["cause"] == "no answer from the page: <urlopen error connection refused>"
    assert len(started) == 1 and started[0].poll() is not None

    def interrupt(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(acceptance.urllib.request, "build_opener", interrupt)
    with pytest.raises(KeyboardInterrupt):
        acceptance.serve_page(acceptance.SERVE, (0, "ok"), tmp_path / "ws", tmp_path / "x.pdf", script, env)
    assert len(started) == 2 and started[1].poll() is not None


def test_report_step_takes_every_format_from_export_formats(monkeypatch):
    """AC 5: no format list in the harness; a format added to export.FORMATS is asked for."""
    monkeypatch.setitem(export.FORMATS, "fake", {"write": None, "crops": False})
    assert acceptance.report_command() == "gct report all --format " + ",".join(export.FORMATS)
    assert "fake" in acceptance.report_command().split()[-1].split(",")
    assert acceptance.plan()[-1] == (acceptance.report_command(), 0, "ok")


def test_the_workflow_runs_end_to_end_in_a_fresh_folder(tmp_path):
    """AC 7, the end-to-end test the suite lacked (AC 4 to 6 on the console script): gct --version, 8.1's WORKFLOW,
    the page PNG through gct serve and report all in every format each give their stated result; both seeds are in
    workspace.db and in no export; the folder holds only what the run made."""
    got = acceptance.run_workflow(tmp_path, acceptance.gct_script())
    assert [s for s in got["steps"] if not s["ok"]] == [] and got["problems"] == [] and got["scan"] == []
    assert [s["command"].split(";")[0] for s in got["steps"]] == [c for c, _, _ in acceptance.plan()]
    assert [c for c, _, _ in acceptance.plan()][1:-2] == [c.replace("<NAME>", acceptance.NAME_SEED)
                                                          for c, _, _ in WORKFLOW]
    page = next(s["page"] for s in got["steps"] if s["command"].startswith(acceptance.SERVE))
    assert page.startswith("HTTP 200, image/png")
    assert len([p for p in (tmp_path / "ws" / "exports").iterdir() if p.is_dir()]) == 2  # json,csv and every format
    assert set(leakage.found(tmp_path / "ws" / "workspace.db", acceptance.SEEDS)) == {"path seed", "contributor seed"}
    assert {p.name for p in tmp_path.iterdir()} == {acceptance.PATH_SEED, "ws"}


def test_a_step_that_does_not_give_its_stated_result_stops_the_workflow(tmp_path):
    """Section 4: the first step off its stated result stops the run, named with the code's cause and next_action
    verbatim; nothing after it runs and the scan does not run."""
    script = tmp_path / "fake-gct"
    script.write_text(f"#!{sys.executable}\nimport json, sys\nif sys.argv[1:] == ['--version']:\n    print('gct 0')\n"
                      "    sys.exit(0)\nprint(json.dumps({'status': 'error', 'cause': 'Cause one.', 'next_action': "
                      "'Do two.'}))\nsys.exit(2)\n")
    script.chmod(0o755)
    got = acceptance.run_workflow(tmp_path / "run", script)
    assert [s["ok"] for s in got["steps"]] == [True, False] and got["scan"] is None
    assert got["problems"] == ["gct workspace init <WORKSPACE> stopped the workflow (2 error, the workflow states 0 "
                               "ok); cause: Cause one.; next_action: Do two."]


def test_every_command_path_but_serve_and_version_is_in_a_replay_block():
    """AC 8: each step's command path (argv words up to the first option), except gct serve and gct --version, is in
    a gct-replay block under assistants/claude/; serve is never replayed (8.1's test checks it is documented only as
    gct serve --no-open --json)."""
    replayed = {acceptance.command_path(c) for p in sorted(ASSISTANT.rglob("*.md")) for c, _, _ in replay_lines(p)}
    paths = [acceptance.command_path(c) for c, _, _ in acceptance.plan() if c not in acceptance.NOT_REPLAYED]
    assert [p for p in paths if p not in replayed] == []
    assert {acceptance.VERSION, acceptance.SERVE} <= {c for c, _, _ in acceptance.plan()}
    assert [p for p in replayed if p.split()[:1] == ["serve"]] == []
    assert acceptance.command_path("gct report all --format json,csv") == "report all"


def scan_tree(tmp_path, db=f"{acceptance.PATH_SEED} {acceptance.NAME_SEED}".encode(), export_text=b"nothing here"):
    ws = tmp_path / "ws"
    (ws / "exports" / "one").mkdir(parents=True)
    (ws / "workspace.db").write_bytes(db)
    (ws / "exports" / "one" / "dataset.json").write_bytes(export_text)
    return ws


SEEDS = acceptance.SEEDS


def test_scan_finds_both_seeds_in_the_database_and_none_in_exports(tmp_path):
    """AC 6: the positive control and the clean exports."""
    assert acceptance.check_scan(scan_tree(tmp_path), SEEDS) == []


def test_scan_fails_when_the_positive_control_misses_a_seed(tmp_path):
    problems = acceptance.check_scan(scan_tree(tmp_path, db=acceptance.PATH_SEED.encode()), SEEDS)
    assert problems and "contributor seed" in problems[0] and "workspace.db" in problems[0]


def test_scan_fails_when_a_seed_is_in_an_export(tmp_path):
    problems = acceptance.check_scan(scan_tree(tmp_path, export_text=b"by " + acceptance.NAME_SEED.encode()), SEEDS)
    assert problems and "one" in problems[0] and "contributor seed" in problems[0]
    ws = scan_tree(tmp_path / "file")  # a file beside the export folders is scanned too
    (ws / "exports" / "stray.txt").write_text(acceptance.PATH_SEED)
    assert acceptance.check_scan(ws, SEEDS)[0].startswith("exports/stray.txt: found")


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


# The six company-by-kind cells of the recorded baseline (TASK-0230 prep.md section 3), with their n.
CELLS = [("Tata Motors Limited", "text", 60), ("Tata Motors Limited", "table", 40), ("Tata Motors Limited", "figure", 30),
         ("Mahindra & Mahindra Limited", "text", 20), ("Mahindra & Mahindra Limited", "table", 10),
         ("Mahindra & Mahindra Limited", "figure", 10)]
GOLD = "3985743f8891a8fb06d3ebfd62c7f020ef847f12"


def g2_report(tmp_path, found=lambda n: 0, scorer="1", gold=GOLD, workspace="/runs/automatic-75fba9a/ws"):
    """A synthetic gct measure g2 report with the recorded key shape; found(n) gives each cell's Found count."""
    types = [{"company": c, "kind": k, "n": n, "found": found(n), "partial": 0, "missed": n - found(n),
              "found_text": f"{found(n)}/{n}", "verdict": "fail" if found(n) / n < 0.9 else
              "at or above 90% before adjudication"} for c, k, n in CELLS]
    report = {"published_version": 1, "gct_commit": "e931eeb34ebaed81acd15e4527291141455b99f4", "scorer_version": scorer,
              "status": "ok", "run_id": "20261021T132603934294Z", "report_path": "/runs/g2-report-v1.json",
              "workspace": workspace, "gold": {"version": "g2-gold-v2", "commit": gold},
              "headline": "Tata Motors Limited only: the second-company validation is not complete",
              "target": "90% Found per content type", "delta": None, "rows": [], "types": types,
              "document_types": [], "documents": [], "runs": [{"row": "rung 1", "state": "scored"}],
              "adjudication": {}, "aggregate": []}
    path = tmp_path / "g2-report-v1-synthetic.json"
    path.write_text(json.dumps(report))
    return path


def test_wilson_interval_at_95_percent():
    """AC 11: z = 1.96."""
    assert [round(x, 3) for x in acceptance.wilson(0, 170)] == [0.0, 0.022]
    assert [round(x, 3) for x in acceptance.wilson(5, 10)] == [0.237, 0.763]


def test_g2_failing_cells_give_fail_measured_not_passed(tmp_path):
    """AC 11: identity beside the expected values, the row's label, each cell with its interval, the per-type
    aggregate of the six cells, gct_commit beside HEAD, and fail."""
    path = g2_report(tmp_path)
    g2 = acceptance.g2_result(acceptance.load_g2(path), path, "a" * 40)
    assert g2["status"] == "fail" and "measured, not passed" in g2["reason"]
    text = "\n".join(g2["lines"])
    assert "scorer_version 1 (expected 1)" in text and f"gold.commit {GOLD} (expected 3985743)" in text
    assert "automatic run 20261021T132603934294Z, workspace /runs/automatic-75fba9a/ws" in text
    uppers = ["0.060", "0.088", "0.114", "0.161", "0.278", "0.278"]
    for (company, kind, n), upper in zip(CELLS, uppers):
        assert f"{company} {kind}: 0/{n}, Wilson 95% 0.000 to {upper}, fail" in text
    for kind, n in (("text", 80), ("table", 50), ("figure", 40)):
        assert f"{kind}: 0/{n}, Wilson 95% 0.000 to" in text
        assert f"{kind} 0/{n}" in g2["reason"]
    assert f"gct_commit e931eeb34ebaed81acd15e4527291141455b99f4 beside HEAD {'a' * 40}" in text
    assert "measured, not passed" in text


def test_g2_review_assisted_row_is_labelled(tmp_path):
    path = g2_report(tmp_path, workspace="/runs/review-assisted-75fba9a/ws")
    assert "review-assisted run" in "\n".join(acceptance.g2_result(acceptance.load_g2(path), path, "h")["lines"])


def test_g2_all_cells_at_or_above_90_percent_is_no_test_before_adjudication(tmp_path):
    """AC 11: never pass; adjudication is story 3.6's hand method."""
    path = g2_report(tmp_path, found=lambda n: round(0.95 * n))
    g2 = acceptance.g2_result(acceptance.load_g2(path), path, "h")
    assert g2["status"] == "no test"
    assert "at or above 90% before adjudication" in g2["reason"] and "story 3.6" in g2["reason"]


@pytest.mark.parametrize("field", ["scorer", "gold"])
def test_g2_report_with_another_scorer_or_gold_is_refused(tmp_path, field):
    """AC 11: only the story's scorer "1" and gold 3985743 are read."""
    path = g2_report(tmp_path, **({"scorer": "2"} if field == "scorer" else {"gold": "0" * 40}))
    with pytest.raises(acceptance.Refused) as e:
        acceptance.load_g2(path)
    assert ("scorer_version 2 (expected 1)" if field == "scorer" else f"gold.commit {'0' * 40} (expected 3985743)") in str(e.value)


def test_g2_without_a_report_is_no_test_naming_the_recorded_baseline():
    """AC 11: no file, no fresh measurement; the recorded baseline is named as recorded evidence."""
    g2 = acceptance.g2_result(None, None, "h")
    assert g2["status"] == "no test" and "no G2 report given" in g2["reason"]
    assert ("input not available: recorded baseline text 0/80, table 0/50, figure 0/40 Found, scorer 1, gold 3985743, "
            "target 90% per type") in g2["reason"]
    assert "recorded evidence, not a fresh measurement" in g2["reason"]


# Story 8.5 section 3's gate table, row by row; the reviewer checks it against prd:102-120 and :631-656 by hand.
GATE_NAMES = ["G1 clean install", "G2 extraction quality", "G3 publication", "Review records", "Time series",
              "Evidence upload", "Report formats", "Privacy in exports", "Calculated values", "Resume and cache reuse",
              "Migration", "Cross-machine handover", "Retrieval", "Deletion", "Tables and Graphs", "Security",
              "Accessibility", "Performance baseline", "Assistant interface, Claude",
              "Assistant interface, Codex and agy; Platform", "Schema", "Compatibility",
              "Interest action; M2 acceptance"]
OUTSIDE = {"G3 publication", "Calculated values", "Retrieval", "Performance baseline",
           "Assistant interface, Codex and agy; Platform", "Interest action; M2 acceptance"}
WITH_METHOD = {"G1 clean install", "G2 extraction quality", "G3 publication", "Review records", "Time series",
               "Report formats", "Privacy in exports", "Deletion", "Tables and Graphs", "Assistant interface, Claude"}


def test_gates_hold_each_row_of_the_story_table_once_with_present_sources():
    """AC 9: every row once, in order; M1 or outside as D-8.5-2 says; methods only where the story names one;
    every source file present under tests/."""
    assert [g["gate"] for g in acceptance.GATES] == GATE_NAMES
    assert {g["gate"] for g in acceptance.GATES if not g["milestone"].startswith("M1")} == OUTSIDE
    assert {g["gate"]: g["milestone"] for g in acceptance.GATES if g["milestone"].startswith("M1 ")} == {
        "Assistant interface, Claude": "M1 pending E8-D27"}
    assert {g["gate"] for g in acceptance.GATES if g["method"]} == WITH_METHOD
    assert {g["gate"] for g in acceptance.GATES if g["hand"]} == {"G1 clean install", "Assistant interface, Claude"}
    missing = {src.split("::")[0] for g in acceptance.GATES for src in g["tests"]
               if not (ROOT / src.split("::")[0]).is_file()}
    assert missing == set()


JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">
<testcase classname="tests.test_a" name="test_one" />
<testcase classname="tests.test_a" name="test_two[x-1]" />
<testcase classname="tests.test_b.TestGroup" name="test_three" />
<testcase classname="tests.test_c" name="test_skip"><skipped type="pytest.skip" message="no node here" /></testcase>
<testcase classname="tests.test_d" name="test_bad"><failure message="assert 1 == 2" /></testcase>
<testcase classname="" name="tests.test_e"><error message="collection failure" /></testcase>
</testsuite></testsuites>"""


def test_junit_gives_node_ids_outcomes_and_skip_reasons(tmp_path):
    (tmp_path / "j.xml").write_text(JUNIT)
    assert acceptance.read_junit(tmp_path / "j.xml") == {
        "tests/test_a.py::test_one": ("passed", ""), "tests/test_a.py::test_two[x-1]": ("passed", ""),
        "tests/test_b.py::TestGroup::test_three": ("passed", ""),
        "tests/test_c.py::test_skip": ("skipped", "no node here"),
        "tests/test_d.py::test_bad": ("failed", "assert 1 == 2"), "tests/test_e.py": ("failed", "collection failure")}


ENV = {"editable": False, "pythonpath": [], "gct_file": "/venv/site/gct/__init__.py", "distribution": "/venv/site"}
NO_G2 = {"status": "no test", "reason": "no G2 report given"}
WORKFLOW_OK = {"steps": [], "problems": [], "scan": []}


def line(results, workflow=WORKFLOW_OK, env=ENV, **row):
    """A synthetic GATES row run through the status rule."""
    base = {"gate": "X", "prd": ":1", "milestone": "M1", "tests": ["tests/test_a.py"], "method": "m", "hand": None,
            "uses": set(), "inherited": None}
    return acceptance.gate_line({**base, **row}, results, workflow, env, NO_G2)


PASSED = {"tests/test_a.py::test_one": ("passed", ""), "tests/test_a.py::test_two[1]": ("passed", "")}


def test_status_pass_needs_a_method_and_every_source_passed():
    """AC 10."""
    assert line(PASSED)["status"] == "pass"


def test_status_skipped_source_is_no_test_with_the_reason():
    got = line({**PASSED, "tests/test_a.py::test_three": ("skipped", "no setuptools")})
    assert got["status"] == "no test" and got["reasons"] == ["skipped: tests/test_a.py::test_three (no setuptools)"]


def test_status_failed_source_is_fail_with_the_node_id():
    got = line({**PASSED, "tests/test_a.py::test_two[1]": ("failed", "boom")})
    assert got["status"] == "fail" and got["reasons"] == ["failed: tests/test_a.py::test_two[1]"]


def test_status_without_a_method_is_no_test_even_when_every_related_test_passed():
    got = line(PASSED, method=None)
    assert got["status"] == "no test" and got["reasons"] == ["no accepted method"]


def test_status_names_a_source_that_did_not_run():
    got = line(PASSED, tests=["tests/test_a.py", "tests/test_absent.py"])
    assert got["status"] == "no test" and got["reasons"] == ["source not run: tests/test_absent.py"]


def test_status_hand_part_open_when_the_automated_part_passed():
    """AC 12: G1 and the Claude row stay open until their hand records exist."""
    assert line(PASSED, hand="a trip")["status"] == "automated part passed, hand part open"


def test_inherited_failed_privacy_acceptance_stays_fail_beside_passing_tests():
    """AC 10: passing synthetic sources cannot override Epic 7's failed acceptance; both are reported."""
    got = line(PASSED, inherited=acceptance.PRIVACY_FAILED)
    assert got["status"] == "fail" and got["automated"] == {"status": "pass", "reasons": []}
    assert got["inherited"] == acceptance.PRIVACY_FAILED
    for part in ("FR1", "FR2", "FR3", "FR4", "15 unread images", "53d8091"):
        assert part in got["inherited"]
    privacy = next(g for g in acceptance.GATES if g["gate"] == "Privacy in exports")
    assert privacy["inherited"] == acceptance.PRIVACY_FAILED


def test_workflow_problem_fails_the_rows_that_read_it():
    """A stopped workflow fails G1 and Privacy with the step and its cause; a seed found in an export fails only
    the rows that read the scan (Privacy), not G1."""
    stopped = {"steps": [], "problems": ["gct read stopped the workflow; cause: c; next_action: n"], "scan": None}
    for uses in ({"workflow"}, {"workflow", "scan"}):
        got = line(PASSED, uses=uses, workflow=stopped)
        assert got["status"] == "fail" and got["reasons"] == stopped["problems"]
    leak = {"steps": [], "problems": [], "scan": ['exports/x: found {"path seed": ["a.csv: text"]}']}
    got = line(PASSED, uses={"workflow", "scan"}, workflow=leak)
    assert got["status"] == "fail" and got["reasons"] == ['seed scan: exports/x: found {"path seed": ["a.csv: text"]}']
    assert line(PASSED, uses={"workflow"}, workflow=leak)["status"] == "pass"
    assert {g["gate"]: g["uses"] for g in acceptance.GATES if g["uses"] & {"workflow", "scan"}} == {
        "G1 clean install": {"workflow", "install"}, "Privacy in exports": {"workflow", "scan"}}


def test_install_row_is_no_test_for_an_editable_install_or_a_pythonpath_tree():
    """G1 here: an editable install, a PYTHONPATH tree, gct imported from outside its distribution."""
    here = {"editable": True, "pythonpath": ["/wt", "/deps"], "gct_file": "/wt/gct/__init__.py",
            "distribution": "/venv/site"}
    got = line(PASSED, uses={"install"}, hand="a trip", env=here)
    assert got["status"] == "no test" and got["reasons"] == [
        "gct is an editable install", "PYTHONPATH is set: /wt; /deps",
        "gct is imported from /wt/gct/__init__.py, not from its distribution"]
    assert line(PASSED, uses={"install"}, hand="a trip")["status"] == "automated part passed, hand part open"


def test_g2_row_follows_the_report_and_is_never_pass():
    row = {**acceptance.GATES[1]}
    results = {"tests/test_measure.py::test_x": ("passed", "")}
    for g2, status in (({"status": "fail", "reason": "measured, not passed"}, "fail"), (NO_G2, "no test")):
        assert acceptance.gate_line(row, results, WORKFLOW_OK, ENV, g2)["status"] == status


def test_outside_m1_rows_never_count_even_when_a_source_fails():
    """AC 10: an outside-M1 row never enters the CP4 list."""
    got = line({"tests/test_a.py::test_one": ("failed", "x")}, milestone="PR (prd:421)")
    assert got["status"] == "outside M1 (PR (prd:421))" and not got["counts"]
    assert acceptance.cp4([got])["not_passing"] == []


def test_cp4_is_not_claimed_while_any_m1_line_is_not_pass():
    """AC 12: the not-claimed branch lists every M1 line not at pass and sends it to Varun."""
    lines = [line(PASSED), line(PASSED, gate="Y", hand="a trip")]
    got = acceptance.cp4(lines)
    assert got["claimed"] is False and got["not_passing"] == ["Y"]
    assert got["text"] == ("CP4: not claimed. M1 gate lines not passing: Y (automated part passed, hand part open). "
                           "This list goes to Varun for a fix or scope decision (architecture section 7).")


def test_cp4_all_pass_branch_leaves_the_decision_to_varun():
    """AC 12: only a synthetic table reaches it on this machine."""
    got = acceptance.cp4([line(PASSED), line(PASSED, gate="Y")])
    assert got["claimed"] is False and got["not_passing"] == []
    assert got["text"] == ("Every M1 gate line passed on this machine. CP4 acceptance is Varun's decision with the "
                           "hand records.")


def test_harness_never_writes_a_claim_or_a_g2_pass():
    """AC 12."""
    source = (TESTS / "acceptance.py").read_text()
    for s in ("CP4 " + "passed", "CP4: " + "claimed", "G2 " + "passed"):
        assert s not in source


def fake_suite(results):
    return lambda folder: {"command": "pytest", "code": 0, "line": "n passed", "seconds": 1.0, "results": results}


@pytest.fixture
def fake_run(tmp_path, monkeypatch):
    """main on tmp_path with the workflow and the suite replaced (the end-to-end test runs the real workflow)."""
    monkeypatch.setattr(acceptance.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(acceptance, "run_workflow", lambda folder, script: WORKFLOW_OK)


def test_json_prints_one_object_and_never_claims_cp4(tmp_path, monkeypatch, capsys, fake_run):
    """AC 13: status, environment, workflow, scan, suite, g2, gates, cp4 (claimed false); exit 1 while CP4 is open."""
    monkeypatch.setattr(acceptance, "run_suite", fake_suite({"tests/test_review.py::test_x": ("passed", "")}))
    path = g2_report(tmp_path)
    assert acceptance.main(["--json", "--g2-report", str(path)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"status", "environment", "workflow", "scan", "suite", "g2", "gates", "cp4"}
    assert out["status"] == "fail" and out["cp4"]["claimed"] is False and out["g2"]["status"] == "fail"
    assert [g["gate"] for g in out["gates"]] == GATE_NAMES
    assert Path(out["environment"]["folder"]).parent == tmp_path


def test_text_output_ends_with_the_cp4_line(monkeypatch, capsys, fake_run):
    """Every failed test is printed under the suite, even one no gate row reads (section 3.4: no retry)."""
    monkeypatch.setattr(acceptance, "run_suite", fake_suite({"tests/test_zz.py::test_flaky": ("failed", "timed out\nx")}))
    assert acceptance.main([]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert "  failed: tests/test_zz.py::test_flaky (timed out)" in out
    assert out[-1].startswith("CP4: not claimed. M1 gate lines not passing: G1 clean install (no test)")
    assert "Seed scan: both seeds found in workspace.db (the positive control), none under exports/" in out
    assert any(x.startswith("Privacy in exports (prd :109, :647): fail") for x in out)
    assert "  inherited acceptance: " + acceptance.PRIVACY_FAILED in out
    assert "Assistant interface, Claude (prd :120, :648, M1 pending E8-D27): no test" in out


def test_printed_text_and_json_carry_no_home_folder(tmp_path, monkeypatch, capsys, fake_run):
    """No output names the home folder (so no user name): with HOME at the folder's parent, the folder reads ~/."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(acceptance, "run_suite", fake_suite({}))
    assert acceptance.main([]) == 1
    text = capsys.readouterr().out
    assert str(tmp_path) + os.sep not in text and "\nFolder ~/gct-acceptance-" in text
    assert acceptance.main(["--json"]) == 1
    raw = capsys.readouterr().out
    assert str(tmp_path) + os.sep not in raw
    assert json.loads(raw)["environment"]["folder"].startswith("~/gct-acceptance-")


def test_g2_refusal_comes_before_the_folder(tmp_path, capsys, no_folder):
    """Section 5 probe 2: scorer "2" is refused and nothing is made."""
    assert acceptance.main(["--g2-report", str(g2_report(tmp_path, scorer="2"))]) == 2
    assert "scorer_version 2 (expected 1)" in capsys.readouterr().out


def test_a_g2_report_the_row_cannot_be_read_from_is_refused_before_the_folder(tmp_path, capsys, no_folder):
    """The whole G2 row is read before the run starts: a cell without its found count is refused, nothing made."""
    path = g2_report(tmp_path)
    report = json.loads(path.read_text())
    del report["types"][2]["found"]
    path.write_text(json.dumps(report))
    assert acceptance.main(["--g2-report", str(path)]) == 2
    assert f"Refused: the G2 report {path} could not be read (KeyError: 'found')" in capsys.readouterr().out


def test_g2_unmeasured_cells_print_without_an_interval(tmp_path):
    """g2.summarise gives UNMEASURED to a cell with no gold rows; the row prints 0/0 and stays no test."""
    path = g2_report(tmp_path, found=lambda n: round(0.95 * n))
    report = json.loads(path.read_text())
    for t in report["types"]:
        if t["kind"] == "figure":
            t.update(n=0, found=0, missed=0, verdict="UNMEASURED")
    path.write_text(json.dumps(report))
    g2 = acceptance.g2_result(acceptance.load_g2(path), path, "h")
    assert g2["status"] == "no test" and "figure 0/0 (0/0, UNMEASURED)" in g2["reason"]
    assert "Tata Motors Limited figure: 0/0, UNMEASURED" in g2["lines"]


def test_interrupted_run_prints_no_cp4_line(monkeypatch, capsys, fake_run):
    """Section 4: Ctrl-C gives a non-zero exit and no CP4 line."""
    def interrupt(folder):
        raise KeyboardInterrupt

    monkeypatch.setattr(acceptance, "run_suite", interrupt)
    assert acceptance.main([]) != 0
    out = capsys.readouterr().out
    assert "CP4: not claimed" not in out and "Every M1 gate line" not in out and "Interrupted" in out
