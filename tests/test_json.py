import re
from pathlib import Path

from conftest import PDF

DOC = Path(__file__).resolve().parent.parent / "docs" / "cli-json.md"


def spec():
    """{command: {where: set(keys)}} parsed from docs/cli-json.md."""
    out, section = {}, None
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = out.setdefault(line[3:].strip(), {})
        elif m := re.match(r"^- (\w+): (.+)$", line):
            section[m[1]] = set(m[2].replace(" ", "").split(","))
    return out


def check(command, data):
    expected = spec()[command]
    assert set(data) == expected["top"], command
    for where, keys in expected.items():
        if where == "top":
            continue
        nested = data[where]
        for record in nested if isinstance(nested, list) else [nested]:
            assert set(record) == keys, (command, where)


def test_every_command_matches_the_documented_keys(tmp_path, gct, make_file):
    ws = tmp_path / "ws"
    check("workspace init", gct("workspace", "init", ws, "--json").data)
    assert gct("workspace", "init", ws, "--json").data["status"] == "already_initialised"
    check("workspace init", gct("workspace", "init", ws, "--json").data)
    w = ("--workspace", ws)
    new = gct("company", "add", "Acme", *w, "--json").data
    check("company add", new)
    exists = gct("company", "add", "acme", *w, "--json").data
    assert exists["status"] == "exists"
    check("company add", exists)
    check("company list", gct("company", "list", *w, "--json").data)
    f = make_file("a.pdf", PDF)
    added = gct("doc", "add", f, "--company", "Acme", *w, "--json").data
    check("doc add", added)
    dup = gct("doc", "add", f, "--company", "Acme", *w, "--json").data
    assert dup["status"] == "duplicate"
    check("doc add", dup)
    check("doc list", gct("doc", "list", *w, "--json").data)
    check("doc show", gct("doc", "show", 1, *w, "--json").data)
    check("publish status", gct("publish", "status", *w, "--json").data)
    check("publish build", gct("publish", "build", *w, "--json").data)
    check("publish build", gct("publish", "build", *w, "--json").data)
    check("publish restore", gct("publish", "restore", *w, "--json").data)
    check("publish status", gct("publish", "status", *w, "--json").data)
    check("error", gct("doc", "show", 99, *w, "--json").data)


def test_empty_lists_still_match(tmp_path, gct):
    ws = tmp_path / "ws"
    gct("workspace", "init", ws)
    check("company list", gct("company", "list", "--workspace", ws, "--json").data)
    check("doc list", gct("doc", "list", "--workspace", ws, "--json").data)


def test_every_command_has_a_documented_section():
    assert set(spec()) == {
        "workspace init", "company add", "company list", "doc add", "doc list", "doc show",
        "publish build", "publish restore", "publish status", "error",
    }
