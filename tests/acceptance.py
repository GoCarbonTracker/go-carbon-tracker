"""Story 8.5: the M1 acceptance harness. Run directly, never collected by pytest:

    python tests/acceptance.py [--g2-report PATH] [--json]

It refuses when GIT_DIR, GIT_WORK_TREE or GIT_INDEX_FILE is set, prints the environment, runs the shared acceptance
workflow in a new temporary folder, runs the test suite once, reads the G2 report file it is given and prints one
line per PRD gate: pass, fail, no test, outside M1, or automated part passed, hand part open. It reports what it ran
and never lowers, rewords or claims a gate; G2 and CP4 are never passed here."""
import argparse
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree

import leakage

TESTS = Path(__file__).resolve().parent
CHECKOUT = TESTS.parent
GIT_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
NO_JSON = (["--version"],)  # gct --version is text only (8.3)
NO_WORKSPACE = (["workspace", "init"], ["model", "list"])  # the replay grammar appends nothing to these (8.1)
# Story 3.6's G2 ruler. A scorer v2 changes G2_SCORER in the same commit that bumps g2.SCORER_VERSION.
G2_SCORER, G2_GOLD = "1", "3985743"
G2_RECORDED = ("recorded baseline 0/80, 0/50, 0/40 Found (text, table, figure; run 20261021T132603934294Z, gct "
               "e931eeb, scorer 1, gold 3985743), not a fresh measurement")


def git_variable(env) -> str | None:
    """The first git variable that would point git (and the suite's git tests) at another repository."""
    return next((v for v in GIT_VARS if env.get(v)), None)


def editable(dist) -> bool:
    """Whether the distribution is an editable install, from its direct_url.json (PEP 610)."""
    return bool(json.loads(dist.read_text("direct_url.json") or "{}").get("dir_info", {}).get("editable"))


def environment() -> dict:
    """What a reader needs to tell this run from a clean install: Python, OS, gct's file, install kind, HEAD and
    every PYTHONPATH entry (a run with this machine's isolated-deps rule must not read as a clean install)."""
    import gct

    dist = importlib.metadata.distribution("gct")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=CHECKOUT, capture_output=True, text=True).stdout.strip()
    return {"python": sys.version.split()[0], "executable": sys.executable, "os": platform.platform(),
            "architecture": platform.machine(), "gct_file": gct.__file__, "version": dist.version,
            "editable": editable(dist), "distribution": str(dist.locate_file("")), "head": head,
            "pythonpath": [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]}


def header_lines(env) -> list[str]:
    return [f"Python {env['python']} ({env['executable']})", f"OS {env['os']}, architecture {env['architecture']}",
            f"gct {env['version']} from {env['gct_file']}, "
            + ("an editable install" if env["editable"] else "not an editable install")
            + f" (distribution at {env['distribution']})",
            f"Checkout {CHECKOUT} at HEAD {env['head']}",
            "PYTHONPATH: " + ("; ".join(env["pythonpath"]) if env["pythonpath"] else "not set")]


def gct_script() -> Path:
    """The console script installed beside this Python."""
    return Path(sys.executable).parent / "gct"


def run_step(argv: list[str], workspace: Path, script: Path) -> dict:
    """One workflow step as a subprocess of the console script, with --workspace and --json appended except for
    gct --version, workspace init and model list. ok needs exit 0 and status ok (--version: exit 0 and text)."""
    text_only = argv in NO_JSON
    plain = text_only or any(argv[:len(p)] == p for p in NO_WORKSPACE)
    full = [str(script), *map(str, argv)] + ([] if plain else ["--workspace", str(workspace), "--json"])
    env = {**os.environ, "GCT_MODELS": str(Path(workspace).parent / "no-models.toml")}
    start = time.monotonic()
    r = subprocess.run(full, capture_output=True, text=True, env=env)
    step = {"command": " ".join(["gct", *map(str, argv)]), "argv": full, "code": r.returncode,
            "seconds": round(time.monotonic() - start, 2), "out": r.stdout, "err": r.stderr[-2000:],
            "status": None, "cause": None, "next_action": None}
    if text_only:
        step["ok"] = r.returncode == 0 and r.stdout.startswith("gct ")
        return step
    try:
        data = json.loads(r.stdout)
    except ValueError:
        data = {}
    step.update(status=data.get("status"), cause=data.get("cause"), next_action=data.get("next_action"), data=data)
    step["ok"] = r.returncode == 0 and step["status"] == "ok"
    return step


def step_lines(step) -> list[str]:
    """A step's line, and on a refusal the code's cause and next_action verbatim."""
    lines = [f"{'ok  ' if step['ok'] else 'FAIL'} {step['command']}  # => {step['code']} {step['status'] or ''}".rstrip()]
    if not step["ok"]:
        lines += [f"cause: {step['cause']}", f"next_action: {step['next_action']}"]
        if step["cause"] is None:
            lines.append(f"stderr: {step['err'].strip()}")
    return lines


def report_argv() -> list[str]:
    """The report step asks for every format export.FORMATS holds at run time."""
    from gct.reports import export

    return ["report", "all", "--format", ",".join(export.FORMATS)]


def scan(path, seeds) -> dict:
    return leakage.found(path, seeds)


def check_scan(workspace: Path, seeds: list[dict]) -> list[str]:
    """The positive control (every seed found in workspace.db), then each export folder (no seed in any). A part
    the scanner cannot read fails the check."""
    problems = []
    try:
        hits = scan(workspace / "workspace.db", seeds)
        missing = [s["name"] for s in seeds if s["name"] not in hits]
        if missing:
            problems.append(f"positive control: {', '.join(missing)} not found in workspace.db")
        folders = sorted(p for p in (workspace / "exports").iterdir() if p.is_dir())
        if not folders:
            problems.append("no export folder under exports/")
        for folder in folders:
            hits = scan(folder, seeds)
            if hits:
                problems.append(f"exports/{folder.name}: found {json.dumps(hits)}")
    except leakage.Unreadable as e:
        problems.append(str(e))
    return problems


def run_suite(folder: Path) -> dict:
    """The suite once, cwd the temporary folder so -m pytest cannot put the checkout's gct/ ahead of the installed
    copy; JUnit XML gives each test's outcome and skip reason. No retry: a flaky failure is a failure."""
    xml = folder / "junit.xml"
    argv = [sys.executable, "-m", "pytest", str(TESTS), "-q", "-p", "no:cacheprovider", f"--junitxml={xml}",
            f"--basetemp={folder / 'pytest'}"]
    start = time.monotonic()
    r = subprocess.run(argv, cwd=folder, capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    return {"command": " ".join(argv), "code": r.returncode, "line": lines[-1] if lines else r.stderr.strip()[-500:],
            "seconds": round(time.monotonic() - start, 1), "results": read_junit(xml) if xml.exists() else {}}


def read_junit(path) -> dict:
    """{node id: (outcome, message)}, outcome passed, failed or skipped; a collection error is a failure of its file."""
    out = {}
    for case in ElementTree.parse(path).iter("testcase"):
        parts = (case.get("classname") or case.get("name")).split(".")
        k = next((i for i, p in enumerate(parts) if p[:1].isupper()), len(parts))  # a Test class starts the node
        node = "/".join(parts[:k]) + ".py"
        if case.get("classname"):
            node = "::".join([node, *parts[k:], case.get("name")])
        bad = case.find("failure") if case.find("failure") is not None else case.find("error")
        skip = case.find("skipped")
        if bad is not None:
            out[node] = ("failed", bad.get("message") or "")
        elif skip is not None:
            out[node] = ("skipped", skip.get("message") or "")
        else:
            out[node] = ("passed", "")
    return out


class Refused(Exception):
    """An input the harness will not read; nothing has been made when it is raised."""


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The Wilson score interval for k of n at 95%."""
    p, q = k / n, z * z / n
    centre, half = p + q / 2, z * math.sqrt(p * (1 - p) / n + q / (4 * n))
    return max(0.0, (centre - half) / (1 + q)), min(1.0, (centre + half) / (1 + q))  # no -0.000 at k = 0


def load_g2(path) -> dict:
    """The gct measure g2 report at path, refused unless its scorer and gold are the story's expected values."""
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    scorer, gold = str(report.get("scorer_version")), str((report.get("gold") or {}).get("commit"))
    if scorer != G2_SCORER or not gold.startswith(G2_GOLD):
        raise Refused(f"G2 report {path} refused: scorer_version {scorer} (expected {G2_SCORER}), gold.commit {gold} "
                      f"(expected {G2_GOLD}). The harness reads only a report of the story's scorer and gold.")
    return report


def _counts(found, n, verdict) -> str:
    low, high = wilson(found, n)
    return f"{found}/{n}, Wilson 95% {low:.3f} to {high:.3f}, {verdict}"


def g2_result(report, path, head) -> dict:
    """The G2 row from a report: fail when any cell fails (measured, not passed); no test when none does (before
    adjudication) or when no report was given. Never pass."""
    if report is None:
        return {"status": "no test", "reason": "no G2 report given; input not available: " + G2_RECORDED,
                "lines": ["G2: no report given (--g2-report PATH); " + G2_RECORDED]}
    from gct.measure import g2

    workspace = report["workspace"]
    row = "review-assisted" if "review-assisted" in workspace else "automatic"
    lines = [f"G2 report {path}", f"scorer_version {report['scorer_version']} (expected {G2_SCORER}); "
             f"gold.commit {report['gold']['commit']} (expected {G2_GOLD})",
             f"{row} run {report['run_id']}, workspace {workspace}"]
    lines += [f"{t['company']} {t['kind']}: {_counts(t['found'], t['n'], t['verdict'])}" for t in report["types"]]
    per_type = []
    for kind in g2.KINDS:
        found = sum(t["found"] for t in report["types"] if t["kind"] == kind)
        n = sum(t["n"] for t in report["types"] if t["kind"] == kind)
        verdict = "fail" if found / n < g2.TARGET else "at or above 90% before adjudication"
        lines.append(f"{kind}: {_counts(found, n, verdict)} (the {sum(t['kind'] == kind for t in report['types'])} "
                     f"company cells summed)")
        per_type.append(f"{kind} {found}/{n} ({_counts(found, n, verdict)})")
    lines += [f"headline: {report['headline']}", f"gct_commit {report['gct_commit']} beside HEAD {head}",
              "measured, not passed"]
    if any(t["verdict"] == "fail" for t in report["types"]):
        return {"status": "fail", "reason": "measured, not passed: " + "; ".join(per_type), "lines": lines,
                "run_id": report["run_id"], "row": row}
    return {"status": "no test", "lines": lines, "run_id": report["run_id"], "row": row,
            "reason": "no cell below 90%: at or above 90% before adjudication; adjudication is story 3.6's hand method"}


def main(argv=None) -> int:
    var = git_variable(os.environ)
    if var:
        print(f"Refused: {var} is set, so git (and the suite's git tests) would act on another repository. "
              f"Nothing was made. Unset {var} and run the harness again.")
        return 2
    parser = argparse.ArgumentParser(description="M1 acceptance harness (story 8.5)")
    parser.add_argument("--g2-report", metavar="PATH")
    parser.add_argument("--json", action="store_true")
    parser.parse_args(argv)
    return 1


if __name__ == "__main__":
    sys.exit(main())
