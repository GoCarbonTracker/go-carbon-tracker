import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import PDF
from gct.workspace import lock, registry
from gct.workspace.layout import GctError
from test_messages import INTERNAL_WORDS, internal_names

ROOT = Path(__file__).resolve().parent.parent
HOLDER = "import sys, time\nfrom gct.workspace import lock\nf = lock.hold(sys.argv[1])\nprint('held', flush=True)\ntime.sleep(60)\n"
CAUSE = "Another gct command is using this workspace."


def holder(ws):
    """A child process holding the workspace lock; returns once it holds it."""
    p = subprocess.Popen([sys.executable, "-c", HOLDER, str(ws)], cwd=ROOT, stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    return p


def writers(make_file):
    good = make_file("good.pdf", PDF)
    return [["read"], ["approve", "spend", "1"], ["doc", "add", good, "--company", "Acme"]]


def test_a_second_process_cannot_write_while_the_lock_is_held(ws, gct, make_file):
    gct("company", "add", "Acme")
    names = internal_names(ws)
    p = holder(ws)
    try:
        for argv in writers(make_file):
            human = gct(*argv)
            assert human.code == 4 and human.out == "", argv
            assert human.err == f"error: {CAUSE}\nnext: Wait for it to finish, then run the command again.\n", argv
            machine = gct(*argv, "--json")
            assert machine.code == 4 and machine.data["cause"] == CAUSE and machine.data["next_action"]
            for text in (human.err, machine.out):
                assert not any(w in text for w in INTERNAL_WORDS) and not any(n in text for n in names), argv
        assert gct("run", "list").code == 0
        assert gct("doc", "list").code == 0
        assert gct("doc", "add", make_file("plan.pdf"), "--company", "Acme", "--plan").code == 0
    finally:
        p.kill()
        p.wait()
    for argv in writers(make_file):
        assert gct(*argv).code == 0, argv


@pytest.mark.skipif(os.name == "nt", reason="SIGKILL is POSIX")
def test_killing_the_holder_releases_the_lock(ws, gct, make_file):
    gct("company", "add", "Acme")
    p = holder(ws)
    assert gct("approve", "spend", "1").code == 4
    os.kill(p.pid, signal.SIGKILL)
    p.wait()
    assert gct("approve", "spend", "1").code == 0
    assert gct("doc", "add", make_file("a.pdf"), "--company", "Acme").code == 0


def test_a_second_holder_is_refused_while_held(ws):
    first = lock.hold(ws)
    try:
        with pytest.raises(GctError) as e:
            lock.hold(ws)
        assert (e.value.code, e.value.cause) == (4, CAUSE)
    finally:
        first.close()
    lock.hold(ws).close()


def test_a_command_releases_the_lock_when_it_returns_or_raises(ws, gct, monkeypatch):
    assert gct("company", "add", "Acme").code == 0
    lock.hold(ws).close()
    assert gct("company", "add", "  ").code == 2  # a refusal raised after the lock was taken
    lock.hold(ws).close()

    def boom(*a, **k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(registry, "add_company", boom)
    assert gct("company", "add", "Beta").code == 1
    lock.hold(ws).close()
