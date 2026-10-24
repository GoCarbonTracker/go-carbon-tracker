"""The setup guide (story 8.2): docs/setup.md and the README Setup block are read as text and checked against the tree.
Nothing here installs or downloads anything. Each check_* takes a tree root so a copy with one change can be checked."""
import re
import shlex
import shutil
import tomllib
from pathlib import Path

import pytest

from conftest import make_pdf
from gate_fixture import SCOPE_1, page

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


def sections(text: str) -> dict[str, str]:
    parts = re.split(r"^## (.+)$", text, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def guide(root: Path) -> str:
    return (root / "docs" / "setup.md").read_text()


def readme_setup(root: Path) -> str:
    return sections((root / "README.md").read_text())["Setup"]


def links(text: str) -> list[str]:
    return [m.split("#")[0] for m in re.findall(r"\]\(([^)\s]+)\)", text) if not re.match(r"[a-z]+:", m)]


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
    source = "".join(p.read_text() for p in (root / "gct").rglob("*.py"))
    quoted = re.findall(r'^\s*(?:- )?Code text: "(.+)"$', guide(root), flags=re.M)
    assert len(quoted) >= 4
    for text in quoted:
        for piece in re.split(r"\{[^}]*\}", text):
            assert piece in source, piece


@pytest.mark.parametrize("check", [check_headings, check_links, check_dependency_names, check_python_and_windows,
                                   check_no_node_or_docker, check_labels, check_readme, check_quotes])
def test_guide(check):
    check(ROOT)


# --- provisional first-run replay: dropped when story 8.1's gct-replay test takes the block over (AC 6, 9) ---

def replay_lines(text: str) -> list[tuple[str, int, str | None]]:
    out = []
    for block in re.findall(r"^```gct-replay\n(.*?)^```", text, flags=re.M | re.S):
        for line in block.splitlines():
            m = re.fullmatch(r"gct (.+?)  # => (\d+)(?: (\w+))?", line)
            assert m, line
            out.append((m[1], int(m[2]), m[3]))
    return out


def test_first_run_block_replays(tmp_path, gct):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(make_pdf([page([[SCOPE_1, "tCO2e", "100"]], ["FY 2024-25"])]))
    root = tmp_path / "ws"
    lines = replay_lines(guide(ROOT))
    assert [line[0].split()[0] for line in lines][:3] == ["workspace", "company", "doc"]
    for args, code, status in lines:
        argv = shlex.split(args.replace("<WORKSPACE>", str(root)).replace("<PDF>", str(pdf)).replace("<COMPANY>", "Acme"))
        if argv[:2] != ["workspace", "init"] and argv[:2] != ["model", "list"]:
            argv += ["--workspace", str(root), "--json"]
        r = gct(*argv)
        assert r.code == code, (args, r.out, r.err)
        if status:
            assert r.data["status"] == status, args
    for step in ("company add", "doc add", "read", "extract", "publish build", "claims list", "contributor add",
                 "flag raise", "report all"):
        assert any(line[0].startswith(step) for line in lines), step
    assert not re.search(r"--complete|doc label|--include-private|approve|--confirm", "".join(l[0] for l in lines))


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
