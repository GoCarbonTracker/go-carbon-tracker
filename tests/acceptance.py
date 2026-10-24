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
import tempfile
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
    missing = [k for k in ("run_id", "workspace", "headline", "gct_commit", "types") if k not in report]
    if missing:
        raise Refused(f"G2 report {path} refused: it has no {', '.join(missing)}.")
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


def _row(gate, prd, milestone, tests=(), method=None, hand=None, uses=(), inherited=None):
    return {"gate": gate, "prd": prd, "milestone": milestone, "tests": list(tests), "method": method, "hand": hand,
            "uses": set(uses), "inherited": inherited}


R8 = "the test files approved in readiness resolution 8"
# Story 7.7's final review, inherited and never overridden by synthetic results (Epic 7 close, 2026-10-24).
PRIVACY_FAILED = ("FAILED: FR1 annotations, FR2 metadata, FR3 CSV/XLSX originals and FR4 fullwidth database "
                  "credentials are deferred leaks; the real-data leakage check is incomplete with 15 unread images; "
                  "scanner correction 53d8091 is excluded")
# One row per PRD gate (prd:102-120 and the Gate column of :631-656), as story 8.5 section 3 lists them. tests are
# files or node ids under the checkout; method None means no accepted method; hand is a part no script can run.
GATES = [
    _row("G1 clean install", ":102, :631", "M1",
         ["tests/test_hygiene.py", "tests/test_viewer.py::test_the_wheel_ships_the_viewer"],
         "8.2 protocol", "the second-laptop trip (D-8.5-4)", uses=("workflow", "install")),
    _row("G2 extraction quality", ":103, :632-633", "M1", ["tests/test_measure.py"],
         "story 3.6 (adjudication by hand)", uses=("g2",)),
    _row("G3 publication", ":104, :656", "publication (D-8.5-2)",
         ["tests/test_licences.py", "tests/test_hygiene.py"], "IP, SE-001 and privacy review outside code"),
    _row("Review records", ":105, :640", "M1",
         ["tests/test_review.py", "tests/test_adjudicate.py", "tests/test_renew.py"], R8),
    _row("Time series", ":106, :634", "M1", ["tests/test_match.py", "tests/test_restate.py"], R8),
    _row("Evidence upload", ":107, :643", "M1", ["tests/test_sheet.py"]),
    _row("Report formats", ":108, :646", "M1", ["tests/test_gate_report_formats.py"], "7.1 G, 7.7 B"),
    _row("Privacy in exports", ":109, :647", "M1",
         ["tests/test_gate_privacy_exports.py", "tests/test_leakage_scanner.py"],
         "7.1 G, 7.7 B and Epic 7's final privacy review", uses=("workflow",), inherited=PRIVACY_FAILED),
    _row("Calculated values", ":110, :644", "PR (prd:422)"),
    _row("Resume and cache reuse", ":111, :638", "M1",
         ["tests/test_stages.py", "tests/test_resume.py", "tests/test_reprocess.py"]),
    _row("Migration", ":112, :649", "M1",
         ["tests/test_projection16.py", "tests/test_deletion.py", "tests/test_highlight.py", "tests/test_labels.py",
          "tests/test_missing.py", "tests/test_review.py"]),  # old_code.py's users: upgrades from 1c9b602
    _row("Cross-machine handover", ":113, :650", "M1"),
    _row("Retrieval", ":114, :642", "PR (prd:421)"),
    _row("Deletion", ":115, :639", "M1", ["tests/test_deletion.py", "tests/test_archive.py"], R8),
    _row("Tables and Graphs", ":116, :641", "M1", ["tests/test_gate_tables_graphs.py"], "6.1 G (CP3)"),
    _row("Security", ":117, :653", "M1", ["tests/test_api.py", "tests/test_hygiene.py::test_no_network"]),
    _row("Accessibility", ":118, :655", "M1", ["tests/test_viewer_tables.py"]),
    _row("Performance baseline", ":119, :652", "pre-release (architecture :119)"),
    _row("Assistant interface, Claude", ":120, :648", "M1 pending E8-D27", ["tests/test_assistant_claude.py"],
         "8.1's replay test (E8-D6)", "the recorded Claude run (E8-D6)"),  # outside M1 if Varun answers otherwise
    _row("Assistant interface, Codex and agy; Platform", ":120, :651", "after M1"),
    _row("Schema", ":636", "M1", ["tests/test_documents.py::test_sector_columns_may_stay_empty"]),
    _row("Compatibility", ":654", "M1"),
    _row("Interest action; M2 acceptance", ":637, :645", "PR, M2"),
]


def _matches(node, src) -> bool:
    return node == src or node.startswith((src + "::", src + "["))


def gate_line(row, results, workflow, env, g2) -> dict:
    """One gate's status (D-8.5-3): fail when a source failed; pass only with an accepted method and every source
    test passed, none skipped; automated part passed, hand part open for a row with a hand part; no test
    otherwise, with the reasons. Rows outside M1 never count. An inherited failed acceptance keeps the row at fail
    and the automated result is reported beside it, never in its place."""
    line = {"gate": row["gate"], "prd": row["prd"], "milestone": row["milestone"],
            "counts": row["milestone"].split()[0] == "M1"}
    if not line["counts"]:
        return {**line, "status": f"outside M1 ({row['milestone']})", "reasons": []}
    fails, opens = [], [] if row["method"] else ["no accepted method"]
    for src in row["tests"]:
        hits = {n: r for n, r in results.items() if _matches(n, src)}
        opens += [] if hits else [f"source not run: {src}"]
        fails += [f"failed: {n}" for n, (outcome, _) in sorted(hits.items()) if outcome == "failed"]
        opens += [f"skipped: {n} ({m})" for n, (outcome, m) in sorted(hits.items()) if outcome == "skipped"]
    if "workflow" in row["uses"]:
        opens += [] if workflow is not None else ["the workflow did not run"]
        fails += workflow or []
    if "g2" in row["uses"]:
        (fails if g2["status"] == "fail" else opens).append(g2["reason"])
    if "install" in row["uses"]:
        opens += ["gct is an editable install"] if env["editable"] else []
        opens += [f"PYTHONPATH is set: {'; '.join(env['pythonpath'])}"] if env["pythonpath"] else []
        if not Path(env["gct_file"]).is_relative_to(env["distribution"]):
            opens.append(f"gct is imported from {env['gct_file']}, not from its distribution")
    if fails:
        status, reasons = "fail", fails
    elif opens:
        status, reasons = "no test", opens
    elif row["hand"]:
        status, reasons = "automated part passed, hand part open", [f"hand part not recorded: {row['hand']}"]
    else:
        status, reasons = "pass", []
    if row["inherited"]:
        line["automated"] = {"status": status, "reasons": reasons}
        line["inherited"] = row["inherited"]
        status, reasons = "fail", ["inherited acceptance " + row["inherited"]]
    return {**line, "status": status, "reasons": reasons}


def cp4(lines) -> dict:
    """E8-D23: CP4 is never claimed by the harness; with every M1 line at pass it says so and leaves the decision
    to Varun."""
    rest = [x for x in lines if x["counts"] and x["status"] != "pass"]
    if rest:
        text = ("CP4: not claimed. M1 gate lines not passing: " + "; ".join(f"{x['gate']} ({x['status']})" for x in rest)
                + ". This list goes to Varun for a fix or scope decision (architecture section 7).")
    else:
        text = "Every M1 gate line passed on this machine. CP4 acceptance is Varun's decision with the hand records."
    return {"claimed": False, "not_passing": [x["gate"] for x in rest], "text": text}


def assemble(env, workflow, suite, g2) -> dict:
    """The one result object (--json); workflow is {"steps", "problems"} or None when it did not run."""
    gates = [gate_line(row, suite["results"], workflow and workflow["problems"], env, g2) for row in GATES]
    result = cp4(gates)
    return {"status": "fail" if result["not_passing"] else "ok", "environment": env,
            "workflow": workflow["steps"] if workflow else [], "suite": suite, "g2": g2, "gates": gates, "cp4": result}


def render(result) -> list[str]:
    out = ["", "Workflow:"]
    out += [x for step in result["workflow"] for x in step_lines(step)] or ["  the workflow did not run"]
    suite = result["suite"]
    out += ["", f"Suite: {suite['command']}", f"  exit {suite['code']}, {suite['seconds']} s: {suite['line']}"]
    out += ["  skipped: " + n + " (" + m + ")" for n, (o, m) in sorted(suite["results"].items()) if o == "skipped"]
    out += ["", *result["g2"]["lines"], "", "Gates (PRD line, status, reasons):"]
    for g in result["gates"]:
        note = f", {g['milestone']}" if g["counts"] and g["milestone"] != "M1" else ""
        out.append(f"{g['gate']} (prd {g['prd']}{note}): {g['status']}")
        if "automated" in g:
            a = g["automated"]
            out.append(f"  automated: {a['status']}" + (f": {'; '.join(a['reasons'])}" if a["reasons"] else ""))
            out.append(f"  inherited acceptance: {g['inherited']}")
        else:
            out += [f"  {r}" for r in g["reasons"]]
    return out + ["", result["cp4"]["text"]]


def main(argv=None) -> int:
    var = git_variable(os.environ)
    if var:
        print(f"Refused: {var} is set, so git (and the suite's git tests) would act on another repository. "
              f"Nothing was made. Unset {var} and run the harness again.")
        return 2
    parser = argparse.ArgumentParser(description="M1 acceptance harness (story 8.5)")
    parser.add_argument("--g2-report", metavar="PATH", help="a gct measure g2 report file (read only)")
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    args = parser.parse_args(argv)
    try:
        report = load_g2(args.g2_report) if args.g2_report else None
    except (Refused, OSError, ValueError) as e:
        print(f"Refused: {e} Nothing was made.")
        return 2
    env = environment()
    env["folder"] = tempfile.mkdtemp(prefix="gct-acceptance-")  # printed, never deleted
    if not args.json:
        print("\n".join(header_lines(env) + [f"Folder {env['folder']} (kept)"]), flush=True)
    try:
        workflow = None  # 8.1's workflow list is imported once 8.1 is on main (TASK-0230 worker.md)
        suite = run_suite(Path(env["folder"]))
    except KeyboardInterrupt:
        print("Interrupted: no CP4 line.")
        return 130
    result = assemble(env, workflow, suite, g2_result(report, args.g2_report, env["head"]))
    print(json.dumps(result) if args.json else "\n".join(render(result)))
    return 1 if result["cp4"]["not_passing"] else 0


if __name__ == "__main__":
    sys.exit(main())
