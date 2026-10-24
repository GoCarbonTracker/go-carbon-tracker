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
    assert "recorded baseline 0/80, 0/50, 0/40 Found" in g2["reason"] and "not a fresh measurement" in g2["reason"]


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
    assert missing <= {"tests/test_assistant_claude.py"}  # 8.1's file; empty once 8.1 is imported (worker.md)


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


def line(results, **row):
    """A synthetic GATES row run through the status rule."""
    base = {"gate": "X", "prd": ":1", "milestone": "M1", "tests": ["tests/test_a.py"], "method": "m", "hand": None,
            "uses": set(), "inherited": None}
    return acceptance.gate_line({**base, **row}, results, row.pop("workflow", []), row.pop("env", ENV), NO_G2)


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
    got = line(PASSED, uses={"workflow"}, workflow=["gct read: refused: cause"])
    assert got["status"] == "fail" and got["reasons"] == ["gct read: refused: cause"]
    assert line(PASSED, uses={"workflow"}, workflow=None)["reasons"] == ["the workflow did not run"]


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
        assert acceptance.gate_line(row, results, [], ENV, g2)["status"] == status


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


def test_json_prints_one_object_and_never_claims_cp4(tmp_path, monkeypatch, capsys):
    """AC 13: status, environment, workflow, suite, g2, gates, cp4 (claimed false); exit 1 while CP4 is open."""
    monkeypatch.setattr(acceptance.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(acceptance, "run_suite", fake_suite({"tests/test_review.py::test_x": ("passed", "")}))
    path = g2_report(tmp_path)
    assert acceptance.main(["--json", "--g2-report", str(path)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"status", "environment", "workflow", "suite", "g2", "gates", "cp4"}
    assert out["status"] == "fail" and out["cp4"]["claimed"] is False and out["g2"]["status"] == "fail"
    assert [g["gate"] for g in out["gates"]] == GATE_NAMES
    assert Path(out["environment"]["folder"]).parent == tmp_path


def test_text_output_ends_with_the_cp4_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(acceptance.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(acceptance, "run_suite", fake_suite({}))
    assert acceptance.main([]) == 1
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1].startswith("CP4: not claimed. M1 gate lines not passing: G1 clean install (no test)")
    assert any(x.startswith("Privacy in exports (prd :109, :647): fail") for x in out)
    assert "  inherited acceptance: " + acceptance.PRIVACY_FAILED in out
    assert "Assistant interface, Claude (prd :120, :648, M1 pending E8-D27): no test" in out


def test_g2_refusal_comes_before_the_folder(tmp_path, capsys, no_folder):
    """Section 5 probe 2: scorer "2" is refused and nothing is made."""
    assert acceptance.main(["--g2-report", str(g2_report(tmp_path, scorer="2"))]) == 2
    assert "scorer_version 2 (expected 1)" in capsys.readouterr().out


def test_interrupted_run_prints_no_cp4_line(tmp_path, monkeypatch, capsys):
    """Section 4: Ctrl-C gives a non-zero exit and no CP4 line."""
    def interrupt(folder):
        raise KeyboardInterrupt

    monkeypatch.setattr(acceptance.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(acceptance, "run_suite", interrupt)
    assert acceptance.main([]) != 0
    out = capsys.readouterr().out
    assert "CP4: not claimed" not in out and "Every M1 gate line" not in out and "Interrupted" in out
