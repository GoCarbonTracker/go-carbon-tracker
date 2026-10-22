import json

import pytest

from conftest import PDF, make_pdf
from gct.stages import read
from gct.workspace import runs, store
from test_messages import INTERNAL_WORDS, internal_names

FIVE = make_pdf([{"text": [(72, 72, f"Page {n}")]} for n in range(1, 6)])


@pytest.fixture
def five(gct, make_file):
    gct("company", "add", "Acme")
    assert gct("doc", "add", make_file("five.pdf", FIVE), "--company", "Acme").code == 0
    return 1


def failing(monkeypatch, numbers, error=ValueError):
    real = read.read_page

    def flaky(page):
        if page.page_number in numbers:
            raise error("boom")
        return real(page)

    monkeypatch.setattr(read, "read_page", flaky)
    return real


def rows(db, run_id):
    return ([tuple(r) for r in db.execute("SELECT * FROM attempt WHERE run_id = ? ORDER BY id", (run_id,))],
            [tuple(r) for r in db.execute("SELECT * FROM run_event WHERE run_id = ? ORDER BY id", (run_id,))])


def newest_run(db):
    return db.execute("SELECT MAX(id) FROM run").fetchone()[0]


def test_every_read_and_doc_add_run_records_its_selection(ws, db, gct, five, make_file):
    gct("read", 1, "--company", "Acme")
    assert runs.selection(db, newest_run(db)) == {"ids": [1], "company": "Acme"}
    f = make_file("b.pdf", PDF + b"b")
    gct("doc", "add", f, "--company", "Acme", "--privacy", "shareable")
    assert runs.selection(db, newest_run(db)) == {"sources": [str(f)], "company": "Acme", "kind": "report",
                                                  "privacy": "shareable", "name": None, "source": None}
    (note,) = [m for (m,) in db.execute("SELECT message FROM run_event WHERE run_id = ? AND kind = 'note'", (newest_run(db),))]
    assert note.startswith("selection: {") and json.loads(note[len("selection: "):])["privacy"] == "shareable"


def test_resume_an_interrupted_read(ws, db, gct, five, monkeypatch):
    real = failing(monkeypatch, {3}, KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        gct("read")
    n = newest_run(db)
    assert gct("run", "list", "--json").data["runs"][0]["outcome"] == "interrupted"
    before = rows(db, n)
    monkeypatch.setattr(read, "read_page", real)
    r = gct("run", "resume", n, "--json")
    assert r.code == 0 and (r.data["run_id"], r.data["of_run"]) == (n + 1, n)
    (d,) = r.data["documents"]
    assert (d["pages"], d["read"], d["cached"], d["failed"]) == (5, 3, 2, 0)
    assert [i for (i,) in db.execute("SELECT item FROM attempt WHERE run_id = ?", (n + 1,))] == ["1:3", "1:4", "1:5"]
    assert rows(db, n) == before
    notes = [e["message"] for e in runs.show_run(db, n + 1)["events"] if e["kind"] == "note"]
    assert notes[0] == f"resumes run {n}" and runs.selection(db, n + 1) == runs.selection(db, n)
    text = gct("run", "show", n + 1).out
    assert f"note  message: resumes run {n}" in text
    assert gct("run", "resume", n + 1).code == 4  # it finished


def test_resume_text_follows_read(ws, db, gct, five, monkeypatch):
    real = failing(monkeypatch, {3}, KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        gct("read")
    monkeypatch.setattr(read, "read_page", real)
    lines = gct("run", "resume", 2).out.splitlines()
    assert lines[0] == "Run 3 resumes run 2."
    assert lines[1] == "read 1: five.pdf: 5 pages, 3 read, 2 cached, 0 flagged, 0 failed"
    assert lines[2].startswith("Total: 1 documents, 5 pages, 3 read, 2 cached")


def test_retry_only_the_failed_pages(ws, db, gct, five, monkeypatch):
    real = failing(monkeypatch, {2, 4})
    assert gct("read").code == 4
    n = newest_run(db)
    monkeypatch.setattr(read, "read_page", real)
    r = gct("run", "retry", n, "--json")
    assert r.code == 0 and (r.data["run_id"], r.data["of_run"]) == (n + 1, n)
    (d,) = r.data["documents"]
    assert (d["read"], d["cached"], d["failed"]) == (2, 0, 0)
    attempts = db.execute("SELECT item, outcome FROM attempt WHERE run_id = ? ORDER BY id", (n + 1,)).fetchall()
    assert [tuple(a) for a in attempts] == [("1:2", "ok"), ("1:4", "ok")]
    assert runs.show_run(db, n + 1)["events"][0]["message"] == f"retries failed items of run {n}"
    assert gct("run", "retry", n).out == f"Run {n} has no failed items.\n"
    again = gct("run", "retry", n, "--json")
    assert again.code == 0 and again.data == {"status": "ok", "run_id": None, "of_run": n, "documents": []}
    assert newest_run(db) == n + 1  # no run for nothing to do


def test_retry_that_still_fails_refuses(ws, db, gct, five, monkeypatch):
    real = failing(monkeypatch, {2, 4})
    gct("read")
    monkeypatch.setattr(read, "read_page", real)
    failing(monkeypatch, {4})
    r = gct("run", "retry", 2, "--json")
    assert r.code == 4 and r.data["status"] == "partial" and r.data["documents"][0]["failed"] == 1
    assert gct("run", "retry", 2, "--json").data["documents"][0]["read"] == 0  # 1:4 still failed, retried again
    assert gct("run", "retry", 3, "--json").code == 4


def test_retry_reads_a_document_that_could_not_be_opened_again_in_full(ws, db, gct, five, make_file, monkeypatch):
    gct("doc", "add", make_file("bad.pdf", PDF), "--company", "Acme")
    assert gct("read").code == 4
    n = newest_run(db)
    r = gct("run", "retry", n, "--json")  # only the PDF that could not be opened; it still cannot be
    assert r.code == 4 and [(d["id"], d["action"]) for d in r.data["documents"]] == [(2, "failed")]
    failures = db.execute("SELECT item FROM run_event WHERE run_id = ? AND kind = 'failure'", (n + 1,)).fetchall()
    assert [f[0] for f in failures] == ["2"]
    assert runs.selection(db, n + 1) == {"ids": [2], "company": None}


def test_retry_skips_a_document_no_longer_active(ws, db, gct, five, monkeypatch):
    real = failing(monkeypatch, {2})
    gct("read")
    monkeypatch.setattr(read, "read_page", real)
    db.execute("INSERT INTO document_state (document_id, state, at) VALUES (1, 'archived', ?)", (store.now(),))
    db.commit()
    r = gct("run", "retry", 2, "--json")
    assert r.code == 0
    (d,) = r.data["documents"]
    assert (d["action"], d["cause"]) == ("skipped", read.NOT_ACTIVE)
    assert db.execute("SELECT COUNT(*) FROM attempt WHERE run_id = 3").fetchone()[0] == 0


def test_doc_add_with_one_unreadable_file(ws, db, gct, make_file, tmp_path):
    gct("company", "add", "Acme")
    good, later = make_file("good.pdf"), tmp_path / "src" / "later.pdf"
    assert gct("doc", "add", good, later, "--company", "Acme").code == 4
    n = newest_run(db)
    later.write_bytes(PDF + b"later")
    r = gct("run", "retry", n, "--json")
    assert r.code == 0 and (r.data["run_id"], r.data["of_run"]) == (n + 1, n)
    assert [(i["source"], i["action"]) for i in r.data["items"]] == [(str(later), "registered")]
    assert runs.selection(db, n + 1)["sources"] == [str(later)]
    assert gct("run", "retry", n).out == f"Run {n} has no failed items.\n"
    assert gct("run", "retry", n, "--json").data == {"status": "ok", "run_id": None, "of_run": n, "items": []}
    lines = gct("doc", "list").out.splitlines()
    assert len(lines) == 2


def test_resume_an_interrupted_doc_add(ws, db, gct, make_file, monkeypatch):
    from gct.workspace import registry

    gct("company", "add", "Acme")
    a, b = make_file("a.pdf"), make_file("b.pdf", PDF + b"b")
    real = registry.add_document

    def stop(conn, root, src, *rest):
        if src.endswith("b.pdf"):
            raise KeyboardInterrupt
        return real(conn, root, src, *rest)

    monkeypatch.setattr(registry, "add_document", stop)
    with pytest.raises(KeyboardInterrupt):
        gct("doc", "add", a, b, "--company", "Acme")
    monkeypatch.setattr(registry, "add_document", real)
    r = gct("run", "resume", 1, "--json")
    assert r.code == 0 and r.data["of_run"] == 1
    assert [i["action"] for i in r.data["items"]] == ["duplicate", "registered"]
    assert gct("run", "resume", 1).out.splitlines()[0] == "Run 3 resumes run 1."


def interrupted_doc_add(gct, monkeypatch, sources, stop_at):
    """doc add of sources, interrupted on the source ending in stop_at; returns the interrupted run's id."""
    from gct.workspace import registry

    gct("company", "add", "Acme")
    real = registry.add_document

    def stop(conn, root, src, *rest):
        if src.endswith(stop_at):
            raise KeyboardInterrupt
        return real(conn, root, src, *rest)

    monkeypatch.setattr(registry, "add_document", stop)
    with pytest.raises(KeyboardInterrupt):
        gct("doc", "add", *sources, "--company", "Acme")
    monkeypatch.setattr(registry, "add_document", real)
    return 1


def test_resume_from_another_folder_registers_the_original_file(ws, db, gct, tmp_path, monkeypatch):
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(), b.mkdir()
    (a / "stop.pdf").write_bytes(PDF + b"stop")
    (a / "rep.pdf").write_bytes(PDF + b"A")
    (b / "rep.pdf").write_bytes(PDF + b"B")
    monkeypatch.chdir(a)
    n = interrupted_doc_add(gct, monkeypatch, ["rep.pdf", "stop.pdf"], "stop.pdf")
    monkeypatch.chdir(b)
    r = gct("run", "resume", n, "--json")
    assert r.code == 0
    assert [(i["source"], i["action"]) for i in r.data["items"]] == [
        (str(a / "rep.pdf"), "duplicate"), (str(a / "stop.pdf"), "registered")]
    assert db.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 2  # B/rep.pdf was never registered


def test_resume_of_a_file_name_that_looks_like_a_key_prefix(ws, db, gct, make_file, monkeypatch):
    f = make_file("climate-risk-assessment-report.pdf")
    n = interrupted_doc_add(gct, monkeypatch, [f], "report.pdf")
    assert runs.selection(db, n)["sources"] == [str(f)]
    r = gct("run", "resume", n, "--json")
    assert r.code == 0 and [(i["source"], i["action"]) for i in r.data["items"]] == [(str(f), "registered")]


def test_retry_after_a_reader_config_change_reads_the_failed_page(ws, db, gct, five, monkeypatch):
    real = failing(monkeypatch, {2})
    assert gct("read").code == 4
    n = newest_run(db)
    monkeypatch.setattr(read, "read_page", real)
    monkeypatch.setattr(read, "read_config", lambda: "changed")
    r = gct("run", "retry", n, "--json")
    assert r.code == 0 and r.data["documents"][0]["read"] == 1
    assert [i for (i,) in db.execute("SELECT item FROM attempt WHERE run_id = ?", (n + 1,))] == ["1:2"]


def test_resume_refusals(ws, db, gct, five, tmp_path, make_file):
    gct("read")
    gct("publish", "build")
    conn = store.connect(ws / "workspace.db")
    old = runs.start(conn, "read")  # interrupted, made before runs recorded their selection
    conn.close()
    names = internal_names(ws)
    cases = [(["run", "resume", 2], 4, "Run 2 finished; nothing to resume."),
             (["run", "resume", 99], 3, "There is no run with id 99."),
             (["run", "resume", old], 4, f"Run {old} has no record of what it was given, so it cannot be replayed."),
             (["run", "resume", 3], 4, "Run 3 was a publish build run. Only read, extract, link, infer, match, sheet and doc add runs can be resumed."),
             (["run", "retry", 3], 4, "Run 3 was a publish build run. Only read, extract, link, infer, match, sheet and doc add runs can be retried."),
             (["run", "retry", 99], 3, "There is no run with id 99.")]
    for argv, code, cause in cases:
        human = gct(*argv)
        assert human.code == code and human.out == "", argv
        assert human.err.startswith(f"error: {cause}\nnext: "), (argv, human.err)
        assert human.err.count("\n") == 2, argv  # one next action
        machine = gct(*argv, "--json")
        assert machine.code == code and machine.data["cause"] == cause and machine.data["next_action"]
        for text in (human.err, machine.out):
            assert not any(w in text for w in INTERNAL_WORDS) and not any(nm in text for nm in names), (argv, text)
    assert gct("run", "resume", old, "--json").data["next_action"] == "Run gct read again with the same documents."
