import json
import sqlite3

import pytest

from conftest import PDF
from gct.workspace import registry

INTERNAL_WORDS = ["Traceback", "sqlite", "sha256", "schema_version"]


def internal_names(ws):
    conn = sqlite3.connect(ws / "workspace.db")
    names = set()
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
        names.add(table)
        names.update(r[1] for r in conn.execute(f"PRAGMA table_info({table})"))
    conn.close()
    return {n for n in names if "_" in n or n == "sha256"}  # plain words such as 'company' are fine


def refusals(ws, tmp_path, make_file):
    """(argv, expected exit code) for every refusal path."""
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "x.txt").write_text("x")
    bad = make_file("bad.pdf", b"not a pdf")
    empty = make_file("empty.csv", b"")
    good = make_file("good.pdf", PDF)
    return [
        (["workspace", "init", tmp_path / "full"], 4),
        (["workspace", "init", good], 4),
        (["company", "list", "--workspace", tmp_path / "nowhere"], 3),
        (["doc", "add", good, "--company", "Nobody", "--workspace", ws], 3),
        (["doc", "add", tmp_path / "missing.pdf", "--company", "Acme", "--workspace", ws], 3),
        (["doc", "add", bad, "--company", "Acme", "--workspace", ws], 4),
        (["doc", "add", empty, "--company", "Acme", "--workspace", ws], 4),
        (["doc", "show", "99", "--workspace", ws], 3),
        (["doc", "list", "--company", "Nobody", "--workspace", ws], 3),
        (["company", "add", "  ", "--workspace", ws], 2),
        (["publish", "restore", "--workspace", ws], 4),
        (["publish", "build", "--workspace", tmp_path / "nowhere"], 3),
    ]


def test_every_refusal_has_cause_next_action_and_no_internals(ws, gct, tmp_path, make_file):
    gct("company", "add", "Acme")
    names = internal_names(ws)
    for argv, code in refusals(ws, tmp_path, make_file):
        human = gct(*argv)
        assert human.code == code, argv
        assert human.out == "", argv
        assert human.err.startswith("error: ") and "\nnext: " in human.err, (argv, human.err)
        machine = gct(*argv, "--json")
        assert machine.code == code and machine.data["status"] == "error"
        assert machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in INTERNAL_WORDS:
                assert word not in text, (argv, word)
            for name in names:
                assert name not in text, (argv, name)


def test_no_workspace_refusal(tmp_path, gct, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GCT_WORKSPACE", raising=False)
    r = gct("doc", "list", "--json")
    assert r.code == 3 and r.data["cause"] and r.data["next_action"]


@pytest.mark.parametrize("argv", [[], ["doc"], ["doc", "add"], ["doc", "show", "abc"], ["nonsense"]])
def test_usage_errors_exit_2_without_traceback(gct, argv):
    r = gct(*argv)
    assert r.code == 2 and "Traceback" not in r.err


def test_unexpected_exception_prints_short_message_and_log_path(ws, gct, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret detail in document_state")

    monkeypatch.setattr(registry, "list_companies", boom)
    r = gct("company", "list", "--workspace", ws)
    assert r.code == 1
    assert "Traceback" not in r.err and "secret detail" not in r.err and "document_state" not in r.err
    logs = list((ws / "logs").glob("error-*.log"))
    assert len(logs) == 1 and str(logs[0]) in r.err
    assert "secret detail" in logs[0].read_text()
    j = gct("company", "list", "--workspace", ws, "--json")
    assert json.loads(j.out)["status"] == "error"
