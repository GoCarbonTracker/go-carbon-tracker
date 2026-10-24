"""The setup guide (story 8.2): docs/setup.md and the README Setup block are read as text and checked against the tree.
Nothing here installs or downloads anything. Each check_* takes a tree root so a copy with one change can be checked."""
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from conftest import make_pdf
from gate_fixture import SCOPE_1, page
from test_assistant_claude import REPLAY_FILES, check_code_text_quotations, mention_problems, replay_lines

ROOT = Path(__file__).resolve().parent.parent

HEADINGS = [
    "What you need",
    "Getting Python 3.11 or newer",
    "Getting the code",
    "Install (user form)",
    "Install (contributor form)",
    "Offline install from a wheelhouse (path B)",
    "What gets installed",
    "First run",
    "Using Claude",
    "What the no-model install reads",
    "Moving a workspace to another computer",
    "Windows",
    "When something fails",
]
# The only sentences that may name Node, npm, Docker or a database server.
NOT_NEEDED = "Nothing here needs Node, npm, Docker or a database server."
REBUILD = "Rebuilding the viewer, only if you change its source, needs Node: see [viewer/README.md](../viewer/README.md)."
# Absolute promises about sanitised output that the README and the guide once made (publication review, finding 1).
OLD_PROMISES = (
    "Reports will use the label to leave private content out",
    "writes a package without private content",
    "A sanitised output leaves out every row",
    "a sanitised PDF holds no private text or page image",
    "a sanitised report holds no rows from a private document",
)
ABSOLUTE = re.compile(r"\bsanitised (?:output|PDF|report|package)s? (?:holds? no|leaves? out|contains? no)\b")
# What the one recorded G2 measurement found (story 3.6, scorer version 1, gold commit 3985743).
G2_FACTS = ("170 figures", "scorer version 1", "3985743", "0 of 80", "0 of 50", "0 of 40", "90%")
# The steps of the first-run block, in order (AC 6), and the files story 8.1 ships that "Using Claude" links (AC 9).
FIRST_RUN_STEPS = ("workspace init", "company add", "doc add", "read", "extract", "publish build", "claims list",
                   "contributor add", "flag raise", "report all")
CLAUDE_FILES = ("assistants/claude/CLAUDE.md", "assistants/claude/.claude/skills/gct/SKILL.md",
                "assistants/claude/.claude/skills/gct/commands.md")


def sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## (.+)$", text, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def flat(text: str) -> str:
    return " ".join(text.split())


def guide(root: Path) -> str:
    return (root / "docs" / "setup.md").read_text()


def readme_setup(root: Path) -> str:
    return sections((root / "README.md").read_text())["Setup"]


def links(text: str) -> list[str]:
    return [t for m in re.findall(r"\]\(([^)\s]+)\)", text) if not re.match(r"[a-z]+:", m) if (t := m.split("#")[0])]


def check_headings(root):
    text = guide(root)
    assert list(sections(text)) == HEADINGS
    assert "needs a wheelhouse built once with Varun's approval" in sections(text)[HEADINGS[5]]
    assert not re.search(r"pip (?:\S+ )*download|\bcurl\b|\bwget\b", text)


def check_links(root):
    for name, text in (("docs/setup.md", guide(root)), ("README.md Setup", readme_setup(root))):
        base = root / ("docs" if name.startswith("docs") else "")
        for target in links(text):
            assert (base / target).exists(), f"{name}: {target}"


def package_names(root):
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    specs = project["dependencies"] + project["optional-dependencies"]["dev"]
    return {re.split(r"[<>=!~\[ ]", s)[0].lower() for s in specs}


def check_dependency_names(root):
    listed = re.findall(r"^- `([A-Za-z0-9_.-]+)`", sections(guide(root))["What gets installed"], flags=re.M)
    assert len(listed) == len(set(listed))
    assert {n.lower() for n in listed} == package_names(root)


def check_python_and_windows(root):
    python = tomllib.loads((root / "pyproject.toml").read_text())["project"]["requires-python"]
    assert python.startswith(">=")
    need = f"Python {python[2:]} or newer"
    text = guide(root)
    assert need in sections(text)["What you need"] and need in readme_setup(root)
    parts = sections(text)
    assert "Windows: not tested" in parts["Install (user form)"]
    assert "Windows: not tested" in parts["Windows"]


def check_no_node_or_docker(root):
    for text in (guide(root), readme_setup(root)):
        rest = text.replace(NOT_NEEDED, "").replace(REBUILD, "")
        assert not re.search(r"\b(?:Node|npm|Docker|database)\b", rest, flags=re.I)
    assert NOT_NEEDED in guide(root) and REBUILD in guide(root)
    assert REBUILD in sections(guide(root))["Install (contributor form)"]


def check_labels(root):
    parts = sections(guide(root))
    assert "Path A" in parts["Install (user form)"] and "networked" in parts["Install (user form)"]
    assert "pip install 'setuptools>=77'" in parts["Install (contributor form)"]
    assert sum(v.count("pip install 'setuptools>=77'") for v in parts.values()) == 1


def check_readme(root):
    setup = readme_setup(root)
    assert "docs/setup.md" in setup and "User form" in setup and "Contributor form" in setup
    if ".venv/bin" in setup:
        assert "Windows" in setup


def check_quotes(root):
    assert len(check_code_text_quotations(root, root / "docs" / "setup.md")) >= 4


def check_privacy_status(root):
    """Publication review, finding 1: no absolute promise about sanitised output; the status is stated up front."""
    readme = (root / "README.md").read_text()
    for name, text in (("README", readme), ("guide", guide(root))):
        t = flat(text)
        assert re.search(r"privacy acceptance[^.]*\bFAILED\b", t), name
        assert re.search(r"final acceptance[^.]*\bINCOMPLETE\b", t), name
        assert re.search(r"15 images[^.]*\bunread\b", t), name
        assert not ABSOLUTE.search(t), name
        for old in OLD_PROMISES:
            assert old not in t, (name, old)
    status = sections(readme)["Status"]
    assert readme.index("## Status") < readme.index("anitised")
    for path in ("annotation", "metadata", "CSV", "XLSX", "fullwidth"):
        assert path in status, path
    assert "before you share it" in status
    assert readme.count("](#status)") >= 4  # the labels sentence, packages, report preview and the PDF format
    assert "](../README.md#status)" in sections(guide(root))["First run"]


def check_measured_g2(root):
    """Publication review, finding 6: the recorded G2 result replaces "not measured yet"."""
    readme = (root / "README.md").read_text()
    assert "not measured yet" not in readme
    for name, text in (("README", sections(readme)["Claims"]), ("guide", guide(root))):
        for fact in G2_FACTS:
            assert fact in flat(text), (name, fact)


def check_python_command(root):
    """Publication review, finding 2: python3 / py -3, not a pinned 3.13, and what has been run."""
    user, setup = sections(guide(root))["Install (user form)"], readme_setup(root)
    for name, text in (("README", setup), ("guide", user)):
        assert "python3 -m venv .venv" in text and "python3 --version" in text, name
        assert "Apple Silicon macOS is the only combination that has been run" in flat(text), name
    assert "py -3 -m venv .venv" in user
    for text in (setup, guide(root)):
        assert "3.13 -m venv" not in text


def check_synthetic_sample(root):
    first_run = sections(guide(root))["First run"]
    assert "python -m tests.gate_fixture" in first_run and "no real report" in first_run
    assert sample_command(first_run)


def check_claude_files_linked(root):
    """AC 9: "Using Claude" links the three files story 8.1 ships (check_links makes sure each one exists)."""
    linked = links(sections(guide(root))["Using Claude"])
    for name in CLAUDE_FILES:
        assert f"../{name}" in linked, name


def check_mentions(root):
    """AC 9, 8.1's check (c) read over the guide: every `gct ...` it names is a command that exists, with options it has."""
    assert not mention_problems(guide(root))


def check_replay_block(root):
    """AC 6 and 9: the first-run block holds the steps in order, and nothing the user has to decide or that does not
    return. Story 8.1's replay test runs the lines (test_assistant_claude.py, the setup.md case)."""
    commands = [c for c, _, _ in replay_lines(root / "docs" / "setup.md")]
    at = 0
    for step in FIRST_RUN_STEPS:
        found = [i for i in range(at, len(commands)) if (commands[i] + " ").startswith(f"gct {step} ")]
        assert found, f"the first-run block has no {step!r} after step {at}"
        at = found[0] + 1
    assert not re.search(r"--complete|doc label|--include-private|approve|doc delete|--confirm|\bserve\b",
                         " ".join(commands))


@pytest.mark.parametrize("check", [check_headings, check_links, check_dependency_names, check_python_and_windows,
                                   check_no_node_or_docker, check_labels, check_readme, check_quotes,
                                   check_privacy_status, check_measured_g2, check_python_command,
                                   check_synthetic_sample, check_claude_files_linked, check_mentions,
                                   check_replay_block])
def test_guide(check):
    check(ROOT)


def test_the_quotation_check_rejects_an_inline_refusal(tmp_path):
    root = tmp_path / "tree"
    shutil.copytree(ROOT / "gct", root / "gct")
    shutil.copytree(ROOT / "docs", root / "docs")
    path = root / "docs" / "setup.md"
    with path.open("a", encoding="utf-8") as file:
        file.write('\nAnother refusal is Code text: "This workspace is safe to publish."\n')
    check_quotes(ROOT)
    with pytest.raises(AssertionError, match="This workspace is safe to publish"):
        check_quotes(root)


def sample_command(first_run: str) -> str | None:
    """The guide's python -c line that writes a synthetic report, as Python source."""
    m = re.search(r'^python -c "(.+)"$', first_run, flags=re.M)
    return m[1] if m else None


def test_the_sample_pdf_command_makes_a_readable_report(tmp_path, gct):
    code = sample_command(sections(guide(ROOT))["First run"])
    # the guide runs it from the code folder; here the tests folder is put on the path instead of changing folder
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "tests"), str(ROOT), os.environ.get("PYTHONPATH", "")])}
    done = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    pdf = tmp_path / "test-workspaces" / "sample.pdf"
    assert pdf.read_bytes().startswith(b"%PDF")
    w = ("--workspace", tmp_path / "test-workspaces" / "first", "--json")
    assert gct("workspace", "init", tmp_path / "test-workspaces" / "first").code == 0
    for args in (("company", "add", "Acme"), ("doc", "add", pdf, "--company", "Acme"), ("read",), ("extract",)):
        assert gct(*args, *w).code == 0, args
    assert gct("claims", "list", "--doc", 1, *w).data["claims"]


# --- AC 6 and 9: story 8.1's replay test runs the first-run block ---

def test_the_guide_is_in_the_assistant_replay_list():
    """8.1's replay test is parametrized over the files in REPLAY_FILES that exist and hold a gct-replay block, so a guide
    taken out of the list is dropped from that test without a failure. This is the failure."""
    assert ROOT / "docs" / "setup.md" in REPLAY_FILES


# --- AC 7: a workspace folder moves ---

def state(gct, root):
    w = ("--workspace", root, "--json")
    return (gct("workspace", "status", *w).data, gct("run", "list", *w).data, gct("claims", "list", "--doc", 1, *w).data)


def test_a_copied_workspace_reads_the_same(tmp_path, gct):
    first = tmp_path / "first" / "ws"
    pdf = tmp_path / "one.pdf"
    pdf.write_bytes(make_pdf([page([[SCOPE_1, "tCO2e", "100"]], ["FY 2024-25"])]))
    assert gct("workspace", "init", first).code == 0
    w = ("--workspace", first, "--json")
    assert gct("company", "add", "Acme", *w).code == 0
    assert gct("doc", "add", pdf, "--company", "Acme", *w).code == 0
    for step in ("read", "extract", "publish build"):
        assert gct(*step.split(), *w).code == 0
    before = state(gct, first)
    assert before[0]["published_version"] == 1 and before[2]["claims"]

    second = tmp_path / "elsewhere" / "ws"
    second.parent.mkdir()
    shutil.copytree(first, second)
    shutil.rmtree(first.parent)
    assert state(gct, second) == before

    w = ("--workspace", second, "--json")
    read = gct("read", *w)
    assert read.code == 0 and (read.data["documents"][0]["read"], read.data["documents"][0]["cached"]) == (0, 1)
    other = tmp_path / "two.pdf"
    other.write_bytes(make_pdf([page([[SCOPE_1, "tCO2e", "250"]], ["FY 2023-24"])]))
    assert gct("doc", "add", other, "--company", "Acme", *w).code == 0
    for step in ("read", "extract"):
        assert gct(step, *w).code == 0
    assert len(gct("claims", "list", "--doc", 2, *w).data["claims"]) >= 1
