import json
import socket
import sqlite3

import pytest

from conftest import PDF
from gct.workspace import registry

INTERNAL_WORDS = ["Traceback", "sqlite", "sha256", "schema_version"]
WHO = ["--as", "ana", "--capacity", "analyst", "--rationale", "checked by eye"]


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
    good = make_file("good.pdf", PDF)
    return [
        (["workspace", "init", tmp_path / "full"], 4),
        (["workspace", "init", good], 4),
        (["company", "list", "--workspace", tmp_path / "nowhere"], 3),
        (["doc", "add", good, "--company", "Nobody", "--workspace", ws], 3),
        (["doc", "show", "99", "--workspace", ws], 3),
        (["doc", "list", "--company", "Nobody", "--workspace", ws], 3),
        (["company", "add", "  ", "--workspace", ws], 2),
        (["publish", "restore", "--workspace", ws], 4),
        (["publish", "build", "--workspace", tmp_path / "nowhere"], 3),
        (["run", "show", "99", "--workspace", ws], 3),
        (["extract", "99", "--workspace", ws], 3),
        (["extract", "--company", "Nobody", "--workspace", ws], 3),
        (["claims", "list", "--doc", "99", "--workspace", ws], 3),
        (["link", "99", "--workspace", ws], 3),
        (["link", "--company", "Nobody", "--workspace", ws], 3),
        (["contributor", "add", "ana", "--name", "Ana", "--workspace", ws], 4),
        (["contributor", "add", " ", "--name", "Ana", "--workspace", ws], 2),
        (["contributor", "edit", "bob", "--name", "Bob", "--workspace", ws], 3),
        (["contributor", "edit", "ana", "--workspace", ws], 2),
        (["expect", "add", "--company", "Nobody", "--metric", "x", "--workspace", ws], 3),
        (["expect", "add", "--company", "Acme", "--metric", "x", "--workspace", ws], 4),
        (["expect", "add", "--company", "Acme", "--metric", "x", "--doc", "99", "--workspace", ws], 3),
        (["expect", "list", "--company", "Nobody", "--workspace", ws], 3),
        (["infer", "--doc", "99", "--workspace", ws], 3),
        (["infer", "--company", "Nobody", "--workspace", ws], 3),
        (["infer", "bases", "--doc", "99", "--workspace", ws], 3),
        (["infer", "groups", "--doc", "99", "--workspace", ws], 3),
        (["infer", "scope", "99", "--pages", "1-2", *WHO, "--workspace", ws], 3),
        (["infer", "accept", "abc", *WHO, "--workspace", ws], 3),
        (["infer", "accept", "abc", "--as", "bob", "--capacity", "c", "--rationale", "r", "--workspace", ws], 3),
        (["infer", "resolve", "99", "--field", "period", "--kind", "fiscal_year", "--start", "2024-04-01",
          "--end", "2023-03-31", *WHO, "--workspace", ws], 2),
        (["infer", "resolve", "99", "--field", "period", "--kind", "fiscal_year", "--start", "2024-04", "--end",
          "2025-03-31", *WHO, "--workspace", ws], 2),
        (["infer", "resolve", "99", "--field", "period", "--boundary", "standalone", *WHO, "--workspace", ws], 2),
        (["infer", "resolve", "99", "--field", "boundary", "--boundary", "standalone", *WHO, "--workspace", ws], 3),
        (["infer", "reject", "abc", *WHO, "--workspace", ws], 3),
        (["infer", "reject", *WHO, "--workspace", ws], 2),
        (["infer", "reject", "--claim", "99", *WHO, "--workspace", ws], 2),
        (["infer", "reject", "--claim", "99", "--field", "period", *WHO, "--workspace", ws], 3),
        (["pages", "accept", "--doc", "99", "--pages", "1", "--type", "figures", *WHO, "--workspace", ws], 3),
        (["pages", "accept", "--doc", "1", "--pages", "1", "--type", "figures", "--as", "bob", "--capacity", "c",
          "--rationale", "r", "--workspace", ws], 3),
        (["gap", "confirm", "99", *WHO, "--workspace", ws], 3),
        (["correct", "99", "--value", "1", *WHO, "--workspace", ws], 3),
        (["correct", "99", *WHO, "--workspace", ws], 2),
        (["correct", "99", "--value", " ", *WHO, "--workspace", ws], 3),
        (["claims", "history", "99", "--workspace", ws], 3),
        (["serve", "--no-open", "--workspace", tmp_path / "nowhere"], 3),
    ]


def test_every_refusal_has_cause_next_action_and_no_internals(ws, gct, tmp_path, make_file):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
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


def test_doc_add_item_refusals_have_cause_next_action_and_no_internals(ws, gct, tmp_path, make_file):
    # A doc add batch reports a bad item and keeps going, so these are item refusals with exit 4, not command errors.
    gct("company", "add", "Acme")
    names = internal_names(ws)
    for source in (tmp_path / "missing.pdf", make_file("bad.pdf", b"not a pdf"), make_file("empty.csv", b"")):
        argv = ["doc", "add", source, "--company", "Acme", "--workspace", ws]
        human = gct(*argv)
        assert human.code == 4, argv
        assert human.out.startswith(f"refused: {source} — ") and human.out.rstrip().endswith("1 refused"), human.out
        assert human.err.startswith("error: ") and "\nnext: " in human.err and str(source) in human.err, human.err
        machine = gct(*argv, "--json")
        assert machine.code == 4 and machine.data["status"] == "partial"
        assert machine.data["cause"] and str(source) in machine.data["next_action"]
        (item,) = machine.data["items"]
        assert item["action"] == "refused" and item["cause"] and item["next_action"] and item["document"] is None
        for text in (human.out, human.err, machine.out):
            for word in INTERNAL_WORDS:
                assert word not in text, (argv, word)
            for name in names:
                assert name not in text, (argv, name)


def test_no_workspace_refusal(tmp_path, gct, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GCT_WORKSPACE", raising=False)
    r = gct("doc", "list", "--json")
    assert r.code == 3 and r.data["cause"] and r.data["next_action"]
    r = gct("serve", "--no-open", "--json")
    assert r.code == 3 and r.data["cause"] and r.data["next_action"]


def test_serve_port_in_use_refusal(ws, gct):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        human = gct("serve", "--port", port, "--no-open")
        machine = gct("serve", "--port", port, "--no-open", "--json")
    assert human.code == 4 and human.err.startswith("error: ") and "\nnext: " in human.err
    assert "--port" in human.err and "Traceback" not in human.err
    assert machine.code == 4 and str(port) in machine.data["cause"] and "--port" in machine.data["next_action"]


def test_serve_port_held_on_all_interfaces_refusal(ws, gct):
    with socket.socket() as taken:
        taken.bind(("0.0.0.0", 0))
        taken.listen()
        port = taken.getsockname()[1]
        r = gct("serve", "--port", port, "--no-open")
    assert r.code == 4 and "--port" in r.err.split("\nnext: ", 1)[1]


@pytest.mark.parametrize("argv", [[], ["doc"], ["doc", "add"], ["doc", "show", "abc"], ["nonsense"],
                                  ["serve", "--host", "0.0.0.0"]])
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
