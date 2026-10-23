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
        (["match", "--doc", "99", "--workspace", ws], 3),
        (["match", "--company", "Nobody", "--workspace", ws], 3),
        (["match", "review", "--company", "Nobody", "--workspace", ws], 3),
        (["match", "status", "--company", "Nobody", "--workspace", ws], 3),
        (["match", "link", "99", "--series", "abc", *WHO, "--workspace", ws], 3),
        (["match", "unlink", "99", "--series", "abc", "--as", "bob", "--capacity", "c", "--rationale", "r",
          "--workspace", ws], 3),
        (["match", "link", "99", "--series", "abc", "--as", "ana", "--capacity", " ", "--rationale", "r",
          "--workspace", ws], 2),
        (["series", "list", "--company", "Nobody", "--workspace", ws], 3),
        (["series", "show", "abc", "--workspace", ws], 3),
        (["restate", "list", "--company", "Nobody", "--workspace", ws], 3),
        (["restate", "show", "99", "--workspace", ws], 3),
        (["review", "list", "99", "--workspace", ws], 3),
        (["review", "pending", "--doc", "99", "--workspace", ws], 3),
        (["review", "pending", "--company", "Nobody", "--workspace", ws], 3),
        (["restate", "record", "--original", "98", "--restated", "99", "--page", "1", "--quote", "q", *WHO,
          "--workspace", ws], 3),
        (["restate", "record", "--original", "98", "--restated", "99", "--page", "1", "--quote", " ", *WHO,
          "--workspace", ws], 2),
        (["restate", "record", "--original", "98", "--restated", "99", "--page", "1", "--quote", "q", "--as", "bob",
          "--capacity", "c", "--rationale", "r", "--workspace", ws], 3),
        (["restate", "withdraw", "--original", "98", "--restated", "99", *WHO, "--workspace", ws], 3),
        (["restate", "withdraw", "--original", "98", "--restated", "99", "--as", "ana", "--capacity", "c",
          "--rationale", " ", "--workspace", ws], 2),
        (["adjudicate", "list", "--company", "Nobody", "--workspace", ws], 3),
        (["adjudicate", "list", "--claim", "99", "--workspace", ws], 3),
        (["adjudicate", "status", "--company", "Nobody", "--workspace", ws], 3),
        (["adjudicate", "record", "98", "99", "--state", "evidence-not-found", "--procedure", "p", *WHO,
          "--workspace", ws], 3),
        (["adjudicate", "record", "98", "99", "--state", "evidence-not-found", "--procedure", " ", *WHO,
          "--workspace", ws], 2),
        (["adjudicate", "record", "98", "99", "--state", "maybe", "--procedure", "p", *WHO, "--workspace", ws], 2),
        (["flag", "raise", "99", "--version", "1", *WHO, "--workspace", ws], 3),
        (["flag", "withdraw", "99", "--version", "1", "--as", "bob", "--capacity", "c", "--rationale", "r",
          "--workspace", ws], 3),
        (["flag", "list", "--claim", "99", "--workspace", ws], 3),
        (["flag", "list", "--company", "Nobody", "--workspace", ws], 3),
        (["sheet", "show", "99", "--workspace", ws], 3),
        (["sheet", "map", "99", "--sheet", "s", "--metric", "M", "--value", "V", *WHO, "--workspace", ws], 3),
        (["serve", "--no-open", "--workspace", tmp_path / "nowhere"], 3),
        (["doc", "archive", "99", *WHO, "--workspace", ws], 3),
        (["doc", "archive", "99", "--plan", "--workspace", ws], 3),
        (["doc", "restore", "99", *WHO, "--workspace", ws], 3),
        (["doc", "delete", "99", "--workspace", ws], 3),
        (["doc", "delete", "99", "--confirm", "abc", *WHO, "--workspace", ws], 3),
    ]


def test_restate_refusals_have_cause_next_action_and_no_internals(ws, gct, make_file):
    from test_restate import QUOTE, cp2

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    a, b, restated, original = cp2(gct, make_file)
    newer = next(c["id"] for c in gct("claims", "list", "--doc", a, "--json").data["claims"] if c["id"] != restated)
    names = internal_names(ws)
    record = ["restate", "record", "--original", original, "--restated", restated, *WHO]
    cases = [[*record, "--page", 1, "--quote", "not on the page"], [*record, "--page", 9, "--quote", QUOTE],
             ["restate", "record", "--original", original, "--restated", newer, "--page", 1, "--quote", QUOTE, *WHO],
             ["restate", "record", "--original", original, "--restated", original, "--page", 1, "--quote", QUOTE, *WHO],
             ["restate", "withdraw", "--original", original, "--restated", restated, *WHO]]
    for argv in cases:
        human, machine = gct(*argv), gct(*argv, "--json")
        assert human.code == machine.code == 4 and human.out == "", (argv, human.err)
        assert human.err.startswith("error: ") and "\nnext: " in human.err
        assert machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in [*INTERNAL_WORDS, *names]:
                assert word not in text, (argv, word)
    assert gct(*record, "--page", 1, "--quote", QUOTE).code == 0
    human = gct(*record, "--page", 1, "--quote", QUOTE)
    assert human.code == 4 and not any(w in human.err for w in [*INTERNAL_WORDS, *names])


def test_review_refusals_have_cause_next_action_and_no_internals(ws, db, gct, make_file):
    from test_review import first_claim, refusal_cases

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")
    names = internal_names(ws)
    assert "review_company" in names and "evidence_note" in names
    for argv, code in refusal_cases(gct, db, make_file, first_claim(gct, make_file)):
        human, machine = gct(*argv), gct(*argv, "--json")
        assert human.code == machine.code == code and human.out == "", (argv, human.out)
        assert human.err.startswith("error: ") and "\nnext: " in human.err, (argv, human.err)
        assert machine.data["status"] == "error" and machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in [*INTERNAL_WORDS, *names]:
                assert word not in text, (argv, word)


def test_highlight_messages_have_cause_next_action_and_no_internals(ws, db, gct, make_file):
    from test_highlight import refusals as highlight_refusals
    from test_review import first_claim

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")
    one = first_claim(gct, make_file)
    names = internal_names(ws)
    assert "highlight" not in names and "claim_version_id" in names
    for argv, code in highlight_refusals(gct, db, make_file, one):
        human, machine = gct(*argv), gct(*argv, "--json")
        assert human.code == machine.code == code and human.out == "", (argv, human.out)
        assert human.err.startswith("error: ") and "\nnext: " in human.err, (argv, human.err)
        assert machine.data["status"] == "error" and machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in [*INTERNAL_WORDS, *names]:
                assert word not in text, (argv, word)
    _, claim, version = one
    done = [gct("highlight", "add", claim, "--version", version, "--note", "n", "--as", "ana", "--capacity", "c"),
            gct("highlight", "list", claim)]
    for r in done:
        assert r.code == 0 and not any(w in r.out for w in [*INTERNAL_WORDS, *names]), r.out


def test_saved_view_messages_have_cause_next_action_and_no_internals(tmp_path, gct):
    import gate_fixture

    root = gate_fixture.build(tmp_path / "gws")
    names = internal_names(root)
    assert "saved_view" in names and "contributor_version_id" in names
    w = ["--workspace", root]
    assert gct("view", "save", "gone", "--filter", "{}", "--as", "ana", *w).code == 0
    assert gct("view", "remove", "gone", "--as", "ana", *w).code == 0
    cases = [(["save", "", "--filter", "{}", "--as", "ana"], 2), (["save", "x" * 81, "--filter", "{}", "--as", "ana"], 2),
             (["save", "a\nb", "--filter", "{}", "--as", "ana"], 2),
             (["save", "v", "--filter", "{}", "--section", "maps", "--as", "ana"], 2),
             (["save", "v", "--filter", '{"colour": [1]}', "--as", "ana"], 2),
             (["save", "v", "--filter", "{", "--as", "ana"], 2), (["save", "v", "--filter", "{}", "--as", "zed"], 3),
             (["open", "nobody"], 3), (["open", "gone"], 3), (["remove", "nobody", "--as", "ana"], 3),
             (["remove", "gone", "--as", "ana"], 3)]
    for argv, code in cases:
        human, machine = gct("view", *argv, *w), gct("view", *argv, *w, "--json")
        assert human.code == machine.code == code and human.out == "", (argv, human.out)
        assert human.err.startswith("error: ") and "\nnext: " in human.err, (argv, human.err)
        assert machine.data["status"] == "error" and machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in [*INTERNAL_WORDS, *names]:
                assert word not in text, (argv, word)
    assert gct("view", "save", "v", "--filter", "{}", "--as", "ana", *w).code == 0
    done = [gct("view", "list", *w), gct("view", "open", "v", *w), gct("view", "questions", *w),
            gct("view", "remove", "v", "--as", "ana", *w), gct("view", "list", *w)]
    for r in done:
        assert r.code == 0 and not any(word in r.out for word in [*INTERNAL_WORDS, *names]), r.out


def test_report_preview_messages_have_cause_next_action_and_no_internals(tmp_path, gct):
    import shutil

    import gate_fixture
    from gct.workspace import layout, lock, store

    root = gate_fixture.build(tmp_path / "gws")
    names = internal_names(root)
    newer = tmp_path / "newer"
    shutil.copytree(root, newer)
    c = sqlite3.connect(newer / "workspace.db")
    c.execute("INSERT INTO schema_version (version, applied_at) VALUES (999, 't')")
    c.commit()
    c.close()
    older = tmp_path / "w20"  # a workspace this gct would upgrade first
    for name in layout.SUBDIRS:
        (older / name).mkdir(parents=True)
    c = store.connect(older / layout.DB_NAME)
    store.migrate(c, up_to=20)
    c.close()
    empty = tmp_path / "empty"
    gct("workspace", "init", empty)
    cases = [((root, "--filter", "{"), 2), ((root, "--filter", '{"colour": [1]}'), 2), ((root, "--include", "names"), 2),
             ((root, "--filter", f"@{tmp_path / 'none.json'}"), 3), ((root, "--data-version", 9), 4),
             ((empty,), 4), ((newer,), 4), ((older,), 4)]
    def refused(where, argv, code):
        human, machine = (gct("report", "preview", *argv, "--workspace", where, *j) for j in ((), ("--json",)))
        assert human.code == machine.code == code and human.out == "", (argv, human.out)
        assert human.err.startswith("error: ") and "\nnext: " in human.err, (argv, human.err)
        assert machine.data["status"] == "error" and machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in [*INTERNAL_WORDS, *names]:
                assert word not in text, (argv, word)
        return human.err

    for (where, *argv), code in cases:
        refused(where, argv, code)
    held = lock.hold(root)
    try:
        assert "Another gct command is using this workspace." in refused(root, [], 4)
    finally:
        lock.release(held)
    assert "needs an upgrade before a report can be built" in refused(older, [], 4)
    assert "made by a newer version of gct" in refused(newer, [], 4)
    for argv in ((), ("--complete",), ("--include", "flags,identity,contributor_text"), ("--filter", '{"document": [2]}')):
        r = gct("report", "preview", *argv, "--workspace", root)
        assert r.code == 0 and r.err == "" and not [w for w in [*INTERNAL_WORDS, *names] if w in r.out], (argv, r.out)


def test_report_export_messages_have_cause_next_action_and_no_internals(tmp_path, gct, monkeypatch):
    import shutil

    import gate_fixture
    from gct.reports import export
    from gct.workspace import lock

    class Refusal(Exception):  # a format's own refusal (story 7.2, AC 12b)
        cause = "The evidence index has a cell the format cannot hold (claim 3, column Metric as printed)."
        next_step = "Export that report as JSON instead: gct report evidence-index --format json"

    def refuses(dataset, reports, folder, crops):
        raise Refusal()

    root = gate_fixture.build(tmp_path / "gws")
    names = internal_names(root)
    empty = tmp_path / "empty"
    gct("workspace", "init", empty)
    monkeypatch.setitem(export.FORMATS, "strict", {"write": refuses, "crops": False})
    monkeypatch.setattr(export, "stamp", lambda: "20261023T000000000000Z")
    cases = [((root, "--format", "xlsx"), 2), ((root, "--format", "json", "--filter", '{"colour": [1]}'), 2),
             ((root, "--format", "json", "--include", "names"), 2),
             ((root, "--format", "json", "--filter", f"@{tmp_path / 'none.json'}"), 3),
             ((root, "--format", "json", "--data-version", 9), 4), ((empty, "--format", "json"), 4),
             ((root, "--format", "strict"), 4)]

    def refused(where, argv, code):
        human, machine = (gct("report", "all", *argv, "--workspace", where, *j) for j in ((), ("--json",)))
        assert human.code == machine.code == code and human.out == "", (argv, human.out)
        assert human.err.startswith("error: ") and "\nnext: " in human.err, (argv, human.err)
        assert machine.data["status"] == "error" and machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in [*INTERNAL_WORDS, *names]:
                assert word not in text, (argv, word)
        return human.err

    for (where, *argv), code in cases:
        refused(where, argv, code)
    assert refused(root, ["--format", "strict"], 4) == f"error: {Refusal.cause}\nnext: {Refusal.next_step}\n"
    held = lock.hold(root)
    try:
        assert "Another gct command is using this workspace." in refused(root, ["--format", "json"], 4)
    finally:
        lock.release(held)
    for argv in ((), ("--complete",), ("--include", "flags,identity,contributor_text")):
        r = gct("report", "all", "--format", "json", *argv, "--workspace", root)
        assert r.code == 0 and r.err == "", (argv, r.err)
        assert not [w for w in [*INTERNAL_WORDS, *names] if w in r.out.split(":\n", 1)[1]], (argv, r.out)
        for folder in (root / "exports").iterdir():
            shutil.rmtree(folder)
    gct("report", "all", "--format", "json", "--workspace", root)
    assert "already exists; nothing was overwritten" in refused(root, ["--format", "json"], 4)


def test_adjudicate_and_flag_messages_have_no_internals(ws, gct, make_file):
    from test_restate import cp2

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    gct("contributor", "add", "bob", "--name", "Bob")
    _, _, restated, original = cp2(gct, make_file)
    names = internal_names(ws)
    record = ["adjudicate", "record", original, restated, "--procedure", "compared the tables", *WHO]
    version = gct("claims", "history", restated, "--json").data["versions"][-1]["id"]
    cases = [[*record, "--state", "restatement"], ["adjudicate", "record", original, original, "--state",
                                                   "evidence-not-found", "--procedure", "p", *WHO],
             [*record, "--state", "explained-difference", "--counter-doc", 1, "--counter-page", 9],
             ["flag", "raise", restated, "--version", version - 1, *WHO],
             ["flag", "withdraw", restated, "--version", version, "--as", "bob", "--capacity", "c", "--rationale", "r"]]
    for argv in cases:
        human, machine = gct(*argv), gct(*argv, "--json")
        assert human.code == machine.code == 4 and human.out == "", (argv, human.err)
        assert human.err.startswith("error: ") and "\nnext: " in human.err
        assert machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in [*INTERNAL_WORDS, *names]:
                assert word not in text, (argv, word)
    done = [gct(*record, "--state", "extraction-error"), gct(*record, "--state", "explained-difference",
                                                             "--counter-note", "p2 note"),
            gct("flag", "raise", restated, "--version", version, *WHO), gct("adjudicate", "list"),
            gct("adjudicate", "list", "--claim", restated), gct("adjudicate", "status"), gct("flag", "list")]
    for r in done:
        assert r.code == 0 and not any(w in r.out for w in [*INTERNAL_WORDS, *names]), r.out


def test_renewed_review_messages_have_no_internals(ws, gct, make_file):
    from test_restate import cp2
    from test_review import rec

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    a, _, restated, original = cp2(gct, make_file)
    version = gct("claims", "history", restated, "--json").data["versions"][-1]["id"]
    assert rec(gct, "company", restated, version).code == 0
    assert gct("flag", "raise", restated, "--version", version, *WHO).code == 0
    assert gct("adjudicate", "record", original, restated, "--state", "extraction-error", "--procedure", "p",
               *WHO).code == 0
    assert gct("correct", restated, "--value", "1,101", *WHO).code == 0
    names = internal_names(ws)
    done = [gct("review", "pending"), gct("claims", "history", restated), gct("claims", "list", "--doc", a)]
    assert "needs re-review: company confirmation #" in done[1].out
    for r in done:
        assert r.code == 0 and not any(w in r.out for w in [*INTERNAL_WORDS, *names]), r.out
    # restate show: the lines of story 5.2 (its correction line prints the changed fields as stored, story 4.2)
    shown = [x for x in gct("restate", "show", restated).out.splitlines() if "re-review" in x or " flag #" in x
             or "adjudication #" in x or "confirmation #" in x]
    assert len(shown) >= 5 and not any(w in x for x in shown for w in [*INTERNAL_WORDS, *names]), shown
    assert gct("doc", "archive", a, *WHO).code == 0
    human, machine = gct("review", "pending", "--doc", a), gct("review", "pending", "--doc", a, "--json")
    assert human.code == machine.code == 4 and human.err.startswith("error: ") and "\nnext: " in human.err
    assert machine.data["cause"] and machine.data["next_action"]
    for text in (human.err, machine.out):
        assert not any(w in text for w in [*INTERNAL_WORDS, *names]), text


def test_archive_refusals_have_cause_next_action_and_no_internals(ws, gct, make_file):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    gct("doc", "add", make_file("a.pdf", PDF), "--company", "Acme")
    gct("doc", "add", make_file("b.pdf", PDF + b"b"), "--company", "Acme")
    assert gct("doc", "archive", "1", *WHO).code == 0
    names = internal_names(ws)
    for argv, code in ((["doc", "archive", "1", *WHO], 4), (["doc", "archive", "1", "--plan"], 4),
                       (["doc", "restore", "2", *WHO], 4), (["doc", "archive", "2"], 2),
                       (["doc", "archive", "2", "--as", "bob", "--capacity", "c", "--rationale", "r"], 3),
                       (["pages", "accept", "--doc", "1", "--pages", "1", "--type", "figures", *WHO], 4)):
        human = gct(*argv)
        assert human.code == code and human.out == "", argv
        assert human.err.startswith("error: ") and "\nnext: " in human.err, (argv, human.err)
        machine = gct(*argv, "--json")
        assert machine.code == code and machine.data["status"] == "error"
        assert machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in INTERNAL_WORDS:
                assert word not in text, (argv, word)
            for name in names:
                assert name not in text, (argv, name)


def test_doc_label_messages_have_cause_next_action_and_no_internals(ws, db, gct, make_file):
    gct("company", "add", "Acme")
    gct("company", "add", "Beta")
    gct("contributor", "add", "ana", "--name", "Ana")
    a = make_file("a.pdf", PDF)
    gct("doc", "add", a, "--company", "Acme")
    gct("doc", "add", make_file("b.pdf", PDF + b"b"), "--company", "Acme")
    sha = db.execute("SELECT sha256 FROM document WHERE id = 2").fetchone()[0]
    assert gct("doc", "delete", "2", "--confirm", sha[:12], *WHO).code == 0
    names = internal_names(ws)
    for argv, code in ((["doc", "label", "1", "--privacy", "private", *WHO], 4), (["doc", "label", "1", *WHO], 2),
                       (["doc", "label", "2", "--privacy", "shareable", *WHO], 4),
                       (["doc", "label", "99", "--privacy", "shareable", *WHO], 3),
                       (["doc", "label", "1", "--privacy", "shareable", "--as", "bob", "--capacity", "c",
                         "--rationale", "r"], 3)):
        human = gct(*argv)
        assert human.code == code and human.out == "", argv
        assert human.err.startswith("error: ") and "\nnext: " in human.err, (argv, human.err)
        machine = gct(*argv, "--json")
        assert machine.code == code and machine.data["status"] == "error"
        assert machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in INTERNAL_WORDS:
                assert word not in text, (argv, word)
            for name in names:
                assert name not in text, (argv, name)
    # the P2 lines of doc add and the doc label success lines name no internals either
    outs = [gct("doc", "add", a, "--company", "Acme", "--privacy", "shareable").out,
            gct("doc", "add", a, "--company", "Beta", "--privacy", "shareable").out,
            gct("doc", "label", "1", "--availability", "public", *WHO).out]
    assert "was not applied" in outs[0] and "Warning: document 1 (Acme)" in outs[1] and "it is now" in outs[2]
    for text in outs:
        for word in INTERNAL_WORDS:
            assert word not in text, word
        for name in names:
            assert name not in text, name


def test_delete_refusals_have_cause_next_action_and_no_internals(ws, gct, make_file):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    gct("doc", "add", make_file("a.pdf", PDF), "--company", "Acme")
    gct("doc", "add", make_file("b.pdf", PDF + b"b"), "--company", "Acme")
    conn = sqlite3.connect(ws / "workspace.db")
    first, token = (s[:12] for (s,) in conn.execute("SELECT sha256 FROM document ORDER BY id"))
    conn.close()
    assert gct("doc", "delete", "1", "--confirm", first, *WHO).code == 0
    names = internal_names(ws)
    for argv, code in ((["doc", "delete", "2", "--confirm", "000000000000", *WHO], 4),
                       (["doc", "delete", "2", "--confirm", token, "--as", "ana"], 2),
                       (["doc", "delete", "2", "--confirm", token, "--as", "bob", "--capacity", "c", "--rationale", "r"], 3),
                       (["doc", "delete", "1"], 4), (["doc", "delete", "1", "--confirm", first, *WHO], 4),
                       (["doc", "restore", "1", *WHO], 4), (["doc", "archive", "1", *WHO], 4),
                       (["pages", "accept", "--doc", "1", "--pages", "1", "--type", "figures", *WHO], 4)):
        human = gct(*argv)
        assert human.code == code and human.out == "", (argv, human.out)
        assert human.err.startswith("error: ") and "\nnext: " in human.err, (argv, human.err)
        machine = gct(*argv, "--json")
        assert machine.code == code and machine.data["status"] == "error"
        assert machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in [*INTERNAL_WORDS, *names]:
                assert word not in text, (argv, word)
    plan = gct("doc", "delete", "2")  # the plan is printed, then the refusal says nothing was deleted
    assert plan.code == 4 and plan.err.startswith("error: Nothing was deleted") and "\nnext: " in plan.err
    assert gct("doc", "delete", "2", "--json").data["status"] == "plan"


def test_package_messages_have_cause_next_action_and_no_internals(ws, gct, make_file, monkeypatch):
    from gct.reports import package
    from gct.workspace import registry as reg

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    gct("doc", "add", make_file("a.pdf", PDF), "--company", "Acme")
    cases = [(["package", "preview"], 4), (["package", "preview", "--include", "names"], 2)]
    gct("publish", "build")
    token = gct("package", "preview", "--json").data["token"]
    cases += [(["package", "create", "--confirm", token], 4),  # every document private
              (["package", "create", "--complete", "--confirm", token], 4),
              (["package", "create", "--include-private", "--confirm", token], 2),
              (["package", "create", "--complete", "--include-private", "--confirm", "000000000000"], 4)]
    gct("doc", "label", "1", "--privacy", "shareable", *WHO)
    cases.append((["package", "preview"], 4))  # out of date
    names = internal_names(ws)

    def check(argv, code):
        human = gct(*argv)
        assert human.code == code and human.out == "", (argv, human.out)
        assert human.err.startswith("error: ") and "\nnext: " in human.err, (argv, human.err)
        machine = gct(*argv, "--json")
        assert machine.code == code and machine.data["status"] == "error"
        assert machine.data["cause"] and machine.data["next_action"]
        for text in (human.err, machine.out):
            for word in [*INTERNAL_WORDS, *names]:
                assert word not in text, (argv, word)

    for argv, code in cases:
        check(argv, code)
    gct("publish", "build")
    token = gct("package", "preview", "--json").data["token"]
    shown = [gct("package", "preview").out, gct("package", "preview", "--complete").out]
    monkeypatch.setattr(reg, "verify", lambda conn, root: [{"problem": "missing"}])
    check(["package", "create", "--confirm", token], 4)  # the package did not verify
    monkeypatch.undo()
    monkeypatch.setenv("GCT_WORKSPACE", str(ws))
    monkeypatch.setattr(package, "_stamp", lambda: "20261023T000000000000Z")
    shown.append(gct("package", "create", "--confirm", token).out)
    check(["package", "create", "--confirm", token], 4)  # the folder name exists
    for text in shown:
        assert text
        for word in [*INTERNAL_WORDS, *names]:
            assert word not in text, word


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


def test_sheet_refusals_have_cause_next_action_and_no_internals(ws, gct, make_file):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    gct("doc", "add", make_file("m.csv", b"Metric,Value,Value\nScope 1,1,2\n"), "--company", "Acme")
    gct("doc", "add", make_file("r.pdf", PDF), "--company", "Acme")
    names = internal_names(ws)
    base = ["sheet", "map", "1", "--sheet", "m", "--metric", "Metric"]
    for argv, code in [(["sheet", "show", "2"], 4), (["sheet", "map", "2", "--sheet", "m", "--metric", "M", "--value", "V", *WHO], 4),
                       ([*base[:4], "x", *base[5:], "--value", "Metric", *WHO], 3), ([*base, "--value", "Unit", *WHO], 4),
                       ([*base, "--value", "Value", *WHO], 4), ([*base, *WHO], 2),
                       ([*base, "--value", "Metric", "--year-end", "31-03", *WHO], 2),
                       ([*base, "--value", "Metric", "--boundary-detail", "plants", *WHO], 2)]:
        human = gct(*argv)
        assert human.code == code and human.out == "", argv
        assert human.err.startswith("error: ") and "\nnext: " in human.err, (argv, human.err)
        machine = gct(*argv, "--json")
        assert machine.code == code and machine.data["cause"] and machine.data["next_action"]
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
