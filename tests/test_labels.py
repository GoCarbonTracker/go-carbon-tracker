"""Story 7.1 part A (TASK-0218): privacy labels, gct doc add --availability, gct doc label and the label primitives
(C-privacy P1 to P8, C7). The pin is in test_pin.py."""
import ast
import json
import re
import sqlite3
from pathlib import Path

import pytest

from conftest import PDF
from old_code import old_tree, run_old  # noqa: F401 (old_tree is a fixture)
from gct.stages import deletion
from gct.workspace import labels, layout, lock, published, runs, store

WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked the company website")
GCT = Path(__file__).resolve().parent.parent / "gct"
WARN = "While one of them is private, reports treat every document with this file as private."


def dump(path) -> dict:
    """Every row of every table, in order."""
    conn = sqlite3.connect(path)
    try:
        return {t: conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
                for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall()}
    finally:
        conn.close()


@pytest.fixture
def acme(ws, gct):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme Audit")
    return ws


def label_rows(db):
    return [tuple(r) for r in db.execute("SELECT document_id, privacy, availability, contributor_version_id, capacity,"
                                         " rationale FROM document_label ORDER BY id")]


# AC 1: the table is insert-only and its contributor fields are all null (intake) or all set (a change)
def test_document_label_is_insert_only_and_a_change_row_is_whole(acme, gct, db, make_file):
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme")
    for stmt in ("UPDATE document_label SET privacy = 'shareable'", "DELETE FROM document_label"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
            db.execute(stmt)
    for values in ("1, NULL, NULL", "NULL, 'c', NULL", "1, 'c', NULL"):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO document_label (document_id, privacy, availability, contributor_version_id, capacity,"
                       f" rationale, created_at) VALUES (1, 'private', 'unknown', {values}, 't')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO document_label (document_id, privacy, availability, created_at)"
                   " VALUES (1, 'private', 'secret', 't')")
    assert sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'"
                                           " AND tbl_name = 'document_label'")) == ["document_label_no_delete",
                                                                                    "document_label_no_update"]


# Correction 6: labels.py imports only gct.workspace modules at module level (the stages import it)
def test_labels_imports_only_workspace_modules_at_module_level():
    tree = ast.parse((GCT / "workspace" / "labels.py").read_text(encoding="utf-8"))
    mods = [a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names]
    mods += [n.module for n in tree.body if isinstance(n, ast.ImportFrom)]
    assert all(m == "gct.workspace" or m.startswith("gct.workspace.") or not m.startswith("gct") for m in mods), mods


# AC 2 (P1): every kind, availability and privacy pair; the label is printed; one intake row
@pytest.mark.parametrize("kind", ["report", "evidence"])
@pytest.mark.parametrize("availability", [None, "public", "internal", "unknown"])
@pytest.mark.parametrize("privacy", [None, "private", "shareable"])
def test_the_intake_label_follows_p1(acme, gct, db, make_file, kind, availability, privacy):
    flags = [*(("--availability", availability) if availability else ()), *(("--privacy", privacy) if privacy else ())]
    r = gct("doc", "add", make_file("x.pdf"), "--company", "Acme", "--kind", kind, *flags)
    av = availability or "unknown"
    want = privacy or ("shareable" if kind == "report" and av == "public" else "private")
    assert r.code == 0 and r.out.splitlines()[0] == f"registered 1: x.pdf (version 1, {want}, availability {av})"
    assert label_rows(db) == [(1, want, av, None, None, None)]
    assert db.execute("SELECT privacy FROM document").fetchone()[0] == want
    d = gct("doc", "show", 1, "--json").data["document"]
    assert (d["privacy"], d["availability"]) == (want, av)


def test_an_explicit_privacy_overrides_a_public_report(acme, gct, make_file):
    r = gct("doc", "add", make_file("a.pdf"), "--company", "Acme", "--kind", "report", "--availability", "public",
            "--privacy", "private", "--json")
    assert r.data["label"] == {"privacy": "private", "availability": "public"}
    assert r.data["items"][0]["document"]["privacy"] == "private"


def test_a_name_folder_or_type_never_sets_the_label(acme, gct, make_file, tmp_path):
    folder = tmp_path / "public shareable reports"
    folder.mkdir()
    (folder / "public-annual-report-shareable.pdf").write_bytes(PDF + b"1")
    (folder / "public.csv").write_bytes(b"a,b\n1,2\n")
    r = gct("doc", "add", folder, make_file("annual-report.pdf", PDF + b"2"), "--company", "Acme", "--json")
    assert [(i["document"]["privacy"], i["document"]["availability"]) for i in r.data["items"]] == [
        ("private", "unknown")] * 3
    r = gct("doc", "add", make_file("x.pdf", PDF + b"3"), "--company", "Acme", "--name", "public shareable", "--json")
    assert (r.data["items"][0]["document"]["privacy"], r.data["items"][0]["document"]["availability"]) == (
        "private", "unknown")


# AC 2: --plan shows both and the P2 lines; it stores nothing (no label row, no note, no run)
def test_plan_shows_the_label_and_the_p2_lines_and_stores_nothing(acme, gct, make_file):
    gct("company", "add", "Beta")
    a, b = make_file("a.pdf"), make_file("b.pdf", PDF + b"b")
    gct("doc", "add", a, "--company", "Acme", "--availability", "public")  # 1: shareable, public
    before = dump(acme / layout.DB_NAME)
    r = gct("doc", "add", a, b, "--company", "Acme", "--plan")
    assert r.code == 0 and r.out.splitlines() == [
        f"duplicate of 1: {a}",
        "The requested label (private, availability unknown) was not applied: document 1 keeps shareable, availability"
        " public. Change it with: gct doc label 1 --privacy private --availability unknown --as KEY --capacity TEXT"
        " --rationale TEXT",
        f"would register: {b} (private, availability unknown)",
        "1 duplicate, 1 would register. Nothing was stored."]
    r = gct("doc", "add", a, "--company", "Beta", "--plan", "--json")
    (item,) = r.data["items"]
    assert item["action"] == "would register" and item["cause"] == (
        f"Warning: document 1 (Acme) has the same file and is labelled shareable. {WARN}")
    assert dump(acme / layout.DB_NAME) == before


# AC 2 (correction 3): the note records the privacy asked for (None when not given) and the availability
def test_the_selection_note_records_the_requested_privacy_and_availability(acme, gct, db, make_file):
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme", "--availability", "public")
    sel = runs.selection(db, db.execute("SELECT MAX(id) FROM run").fetchone()[0])
    assert (sel["kind"], sel["privacy"], sel["availability"]) == ("report", None, "public")


def test_a_retry_of_a_new_note_resolves_p1_again(acme, gct, make_file, tmp_path):
    later = tmp_path / "src" / "later.pdf"
    r = gct("doc", "add", make_file("a.pdf"), later, "--company", "Acme", "--availability", "public")
    assert r.code == 4
    later.write_bytes(PDF + b"later")
    r = gct("run", "retry", 1, "--json")
    assert r.code == 0 and r.data["label"] == {"privacy": "shareable", "availability": "public"}
    d = r.data["items"][0]["document"]
    assert (d["logical_name"], d["privacy"], d["availability"]) == ("later.pdf", "shareable", "public")


# R3: a doc add recorded by the code before part A (BASE, schema 20) replays after the upgrade with the same labels
def test_a_doc_add_note_of_the_older_code_replays_with_the_same_labels(tmp_path, gct, make_file, old_tree):
    root, a, later = tmp_path / "old", make_file("a.pdf"), tmp_path / "src" / "later.pdf"
    made = run_old(old_tree, root, ("workspace", "init", root), ("company", "add", "Acme"),
                   ("doc", "add", a, later, "--company", "Acme", "--kind", "evidence", "--privacy", "shareable"))
    assert [m["code"] for m in made] == [0, 0, 4]
    conn = sqlite3.connect(root / layout.DB_NAME)
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 20
    (note,) = [json.loads(m[len(runs.SELECTION):]) for (m,) in conn.execute(
        "SELECT message FROM run_event WHERE kind = 'note' AND message LIKE 'selection: %'")]
    conn.close()
    assert "availability" not in note and note["privacy"] == "shareable"
    later.write_bytes(PDF + b"later")
    r = gct("run", "retry", 1, "--workspace", root, "--json")
    assert r.code == 0 and r.data["label"] == {"privacy": "shareable", "availability": "unknown"}
    docs = gct("doc", "list", "--workspace", root, "--json").data["documents"]
    assert [(d["logical_name"], d["kind"], d["privacy"], d["availability"]) for d in docs] == [
        ("a.pdf", "evidence", "shareable", "unknown"), ("later.pdf", "evidence", "shareable", "unknown")]


# AC 1, R3 (preservation): the upgrade from 20 writes no label row and changes no existing row
def test_the_upgrade_from_20_keeps_every_row_and_every_label(tmp_path, gct, make_file, old_tree):
    root = tmp_path / "old"
    made = run_old(old_tree, root, ("workspace", "init", root), ("company", "add", "Acme"),
                   ("doc", "add", make_file("a.pdf"), "--company", "Acme"),
                   ("doc", "add", make_file("b.pdf", PDF + b"b"), "--company", "Acme", "--privacy", "shareable"),
                   ("publish", "build"))
    assert [m["code"] for m in made] == [0] * 5
    before = dump(root / layout.DB_NAME)
    r = gct("doc", "list", "--workspace", root)
    assert r.out.splitlines() == ["1  Acme  a.pdf  v1  private  unknown  registered",
                                  "2  Acme  b.pdf  v1  shareable  unknown  registered"]
    after = dump(root / layout.DB_NAME)
    assert set(after) - set(before) == {"document_label"} and after["document_label"] == []
    assert {t for t in before if after[t] != before[t]} == {"schema_version", "run", "run_event"}
    for t in ("schema_version", "run", "run_event"):
        assert after[t][:len(before[t])] == before[t]
    assert [r[0] for r in after["schema_version"][len(before["schema_version"]):]] == [21]
    assert gct("publish", "status", "--workspace", root, "--json").data["stale"]  # the mark gained a position
    again = dump(root / layout.DB_NAME)
    assert again["schema_version"] == after["schema_version"]  # a second open applies nothing


def test_a_schema_19_workspace_upgrades_through_20_and_21_once(tmp_path, gct):
    root = tmp_path / "w19"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    assert store.migrate(c, up_to=19) == list(range(1, 20))
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.close()
    assert gct("doc", "list", "--workspace", root).code == 0
    assert gct("doc", "list", "--workspace", root).code == 0
    c = store.connect(root / layout.DB_NAME)
    (run,) = runs.list_runs(c)
    assert [e["message"] for e in runs.show_run(c, run["id"])["events"] if e["message"]] == ["applied migration 20",
                                                                                             "applied migration 21"]
    assert c.execute("SELECT COUNT(*) FROM document_label").fetchone()[0] == 0
    c.close()


# AC 3 (P2): one row with every field, old and new printed, doc list and doc show
def test_doc_label_writes_one_row_and_prints_old_and_new(acme, gct, db, make_file):
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme")
    r = gct("doc", "label", 1, "--privacy", "shareable", "--availability", "public", *WHO)
    assert r.code == 0
    out = r.out.splitlines()
    assert out[0] == "Document 1 (a.pdf) was private, availability unknown; it is now shareable, availability public."
    assert re.fullmatch(r"label change by Ana, Acme Audit \(analyst\) at \S+: checked the company website", out[1])
    assert label_rows(db) == [(1, "private", "unknown", None, None, None),
                              (1, "shareable", "public", 1, "analyst", "checked the company website")]
    assert gct("doc", "list").out.splitlines() == ["1  Acme  a.pdf  v1  shareable  public  registered"]
    assert "availability: public" in gct("doc", "show", 1).out.splitlines()
    r = gct("doc", "label", 1, "--availability", "internal", *WHO, "--json")
    assert (r.data["old"], r.data["new"]) == ({"privacy": "shareable", "availability": "public"},
                                              {"privacy": "shareable", "availability": "internal"})
    assert r.data["change"]["id"] == 3 and r.data["document"]["availability"] == "internal"
    assert db.execute("SELECT COUNT(*) FROM run").fetchone()[0] == 1  # the doc add only: no run is opened


def test_doc_label_refusals_write_nothing(acme, gct, make_file):
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme")
    before = dump(acme / layout.DB_NAME)
    cases = [((1, *WHO), 2, "Nothing to change was given."),
             ((1, "--privacy", "private", *WHO), 4, "Document 1 is already private, availability unknown."),
             ((1, "--privacy", "private", "--availability", "unknown", *WHO), 4, "Document 1 is already private"),
             ((99, "--privacy", "shareable", *WHO), 3, "There is no document with id 99."),
             ((1, "--privacy", "shareable", "--as", "zed", "--capacity", "c", "--rationale", "r"), 3,
              "There is no contributor with key zed."),
             ((1, "--privacy", "shareable", "--as", "ana", "--capacity", " ", "--rationale", "r"), 2,
              "The capacity is empty."),
             ((1, "--privacy", "shareable", "--as", "ana", "--capacity", "c", "--rationale", ""), 2,
              "The rationale is empty.")]
    for argv, code, cause in cases:
        r = gct("doc", "label", *argv)
        assert r.code == code and r.err.startswith(f"error: {cause}") and "\nnext: " in r.err, (argv, r.err)
    assert dump(acme / layout.DB_NAME) == before


def test_doc_label_is_refused_while_another_command_holds_the_lock(acme, gct, make_file):
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme")
    before = dump(acme / layout.DB_NAME)
    held = lock.hold(acme)
    try:
        r = gct("doc", "label", 1, "--privacy", "shareable", *WHO)
    finally:
        held.close()
    assert r.code == 4 and r.err.startswith("error: Another gct command is using this workspace.")
    assert dump(acme / layout.DB_NAME) == before


def test_doc_label_allows_an_archived_document_and_refuses_a_deleted_one(acme, gct, db, make_file, monkeypatch):
    for n in "abc":
        gct("doc", "add", make_file(f"{n}.pdf", PDF + n.encode()), "--company", "Acme")
    assert gct("doc", "archive", 1, *WHO).code == 0
    assert gct("doc", "label", 1, "--privacy", "shareable", *WHO).code == 0
    token = lambda d: db.execute("SELECT sha256 FROM document WHERE id = ?", (d,)).fetchone()[0][:12]  # noqa: E731
    assert gct("doc", "delete", 2, "--confirm", token(2), *WHO).code == 0
    r = gct("doc", "label", 2, "--privacy", "shareable", *WHO)
    assert r.code == 4 and r.err.startswith("error: Document 2 was deleted on ")
    assert "next: Deletion cannot be undone." in r.err

    def boom(*a):
        raise OSError("held open")

    monkeypatch.setitem(deletion.WORK, "published", boom)
    assert gct("doc", "delete", 3, "--confirm", token(3), *WHO).code == 4  # the published step stays pending
    before = dump(acme / layout.DB_NAME)
    r = gct("doc", "label", 3, "--privacy", "shareable", *WHO)
    assert r.code == 4 and f"next: Finish removing it with: gct doc delete 3 --confirm {token(3)}" in r.err
    assert dump(acme / layout.DB_NAME) == before


# AC 4 (P2): a duplicate with another label, including availability only; byte-identical when they agree
def test_a_duplicate_with_another_label_says_it_was_not_applied(acme, gct, db, make_file):
    a = make_file("a.pdf")
    gct("doc", "add", a, "--company", "Acme")
    assert gct("doc", "add", a, "--company", "Acme").out == f"duplicate of 1: {a}\n1 duplicate\n"
    r = gct("doc", "add", a, "--company", "Acme", "--privacy", "shareable", "--json")
    assert r.data["items"][0]["cause"] == (
        "The requested label (shareable, availability unknown) was not applied: document 1 keeps private, availability"
        " unknown. Change it with: gct doc label 1 --privacy shareable --as KEY --capacity TEXT --rationale TEXT")
    r = gct("doc", "add", a, "--company", "Acme", "--availability", "internal")
    assert r.out.splitlines()[1].endswith("gct doc label 1 --availability internal --as KEY --capacity TEXT"
                                          " --rationale TEXT")
    assert label_rows(db) == [(1, "private", "unknown", None, None, None)]


# AC 4 (P2): a new document with the same file under another label warns, naming it; a deleted one is ignored
def test_a_new_document_with_the_same_file_under_another_label_warns(acme, gct, db, make_file):
    for name in ("Beta", "Gamma", "Delta"):
        gct("company", "add", name)
    a = make_file("a.pdf")
    gct("doc", "add", a, "--company", "Acme")  # 1 private
    r = gct("doc", "add", a, "--company", "Beta", "--privacy", "shareable")  # 2 shareable
    assert r.out.splitlines()[:2] == ["registered 2: a.pdf (version 1, shareable, availability unknown)",
                                      f"Warning: document 1 (Acme) has the same file and is labelled private. {WARN}"]
    r = gct("doc", "add", a, "--company", "Gamma", "--json")  # 3 private: only document 2 differs
    assert r.data["items"][0]["cause"] == (
        f"Warning: document 2 (Beta) has the same file and is labelled shareable. {WARN}")
    gct("doc", "add", make_file("x.pdf", PDF + b"x"), "--company", "Delta")
    assert gct("doc", "add", make_file("y.pdf", PDF + b"y"), "--company", "Delta").out.splitlines()[1] == "1 registered"
    sha = db.execute("SELECT sha256 FROM document WHERE id = 2").fetchone()[0]
    assert gct("doc", "delete", 2, "--confirm", sha[:12], *WHO).code == 0
    r = gct("doc", "add", a, "--company", "Delta", "--privacy", "private", "--json")
    assert r.data["items"][0]["cause"] is None  # the deleted shareable twin is ignored, the others agree


# Matrix (correction 8): a relabel to shareable of a document whose twin is private prints no warning (P2 warns at
# intake only); labels.effective still makes it private (P3 rule 3)
def test_a_relabel_beside_a_private_twin_does_not_warn_and_stays_private_in_reports(acme, gct, db, make_file):
    gct("company", "add", "Beta")
    a = make_file("a.pdf")
    gct("doc", "add", a, "--company", "Acme")
    gct("doc", "add", a, "--company", "Beta")
    r = gct("doc", "label", 2, "--privacy", "shareable", *WHO)
    assert r.code == 0 and len(r.out.splitlines()) == 2
    assert labels.effective(db)[2] == {"label": "private", "availability": "unknown"}


# AC 5 (P3): one test per rule
def test_labels_effective_applies_each_p3_rule(acme, gct, db, make_file):
    gct("company", "add", "Beta")
    add = lambda name, *flags, company="Acme": gct("doc", "add", make_file(name, PDF + name.encode()),  # noqa: E731
                                                   "--company", company, *flags)
    add("plain.pdf", "--privacy", "shareable")  # 1
    add("relabelled.pdf", "--privacy", "shareable")  # 2, private after the build
    add("later.pdf")  # 3, shareable after the build
    gct("doc", "add", make_file("twin.pdf"), "--company", "Acme")  # 4 private
    gct("doc", "add", make_file("twin.pdf"), "--company", "Beta", "--privacy", "shareable")  # 5 same file
    add("archived.pdf", "--privacy", "shareable")  # 6
    gct("doc", "archive", 6, *WHO)
    assert gct("publish", "build").code == 0
    add("unpublished.pdf", "--privacy", "shareable")  # 7, not in the version
    gct("doc", "label", 2, "--privacy", "private", *WHO)
    gct("doc", "label", 3, "--privacy", "shareable", *WHO)
    v = published.open_version(acme / "published" / "v1.db")
    try:
        with_version = {d: x["label"] for d, x in labels.effective(db, v).items()}
    finally:
        v.close()
    assert with_version == {1: "shareable", 2: "private", 3: "private", 4: "private", 5: "private", 6: "private",
                            7: "private"}
    alone = {d: x["label"] for d, x in labels.effective(db).items()}
    assert alone == {1: "shareable", 2: "private", 3: "shareable", 4: "private", 5: "private", 6: "shareable",
                     7: "shareable"}
    sha = db.execute("SELECT sha256 FROM document WHERE id = 1").fetchone()[0]
    assert gct("doc", "delete", 1, "--confirm", sha[:12], *WHO).code == 0
    assert labels.effective(db)[1] == {"label": "private", "availability": "unknown"}


# AC 5 (P6): the record kind and its table give the same decision; the flag, P8 and attempt rules
def test_labels_ships_takes_the_kind_or_its_table(acme, gct, db, make_file):
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme", "--privacy", "shareable")
    gct("doc", "add", make_file("b.pdf", PDF + b"b"), "--company", "Acme")
    for kind, table in labels.KINDS.items():
        for ids in ([], [1], [2], [1, 2], [9]):
            for mode in ("sanitised", "complete"):
                for include in ((), ("flags",)):
                    assert labels.ships(db, None, kind, ids, mode, include) == labels.ships(db, None, table, ids, mode,
                                                                                         include), (kind, ids)
    ships = lambda kind, ids, include=(): labels.ships(db, None, kind, ids, "sanitised", include)  # noqa: E731
    assert ships("claim", [1]) and not ships("claim", [2]) and not ships("claim", [1, 2]) and not ships("claim", [9])
    assert not ships("reviewer flag", [1]) and ships("reviewer flag", [1], ("flags",))
    assert not ships("hidden-by-archive entry", [1]) and not ships("deleted_document", [])
    assert not ships("attempt", []) and ships("attempt", [1])
    assert labels.ships(db, None, "claim", [2], "complete", ()) and labels.ships(db, None, "reviewer_flag", [2],
                                                                                 "complete", ())
    with pytest.raises(ValueError):
        ships("no such kind", [1])


# AC 5 (C7): the order over shipped records, kinds and table names alike, numbered without gaps
def test_labels_pseudonyms_number_in_the_c7_order():
    records = [("highlight", 9, "k3"), ("company confirmation", 5, "k2"), ("auditor review", 1, "k1"),
               ("sheet_mapping", 1, "k4"), ("basis_scope", 2, "k5"), ("document label change", 1, "k2"),
               ("reviewer flag", 3, "k6"), ("adjudication", 7, "k7")]
    want = {"k2": "Contributor 1", "k1": "Contributor 2", "k7": "Contributor 3", "k3": "Contributor 4",
            "k6": "Contributor 5", "k5": "Contributor 6", "k4": "Contributor 7"}
    assert labels.pseudonyms(records) == want
    assert labels.pseudonyms([(labels.KINDS.get(k, k), i, key) for k, i, key in reversed(records)]) == want
    assert [labels._table(k) for k in ("company confirmation", "auditor review", "adjudication", "restatement",
                                       "correction", "highlight", "reviewer flag", "gap confirmation",
                                       "page acceptance", "document label change")] == list(labels.ORDER)
    assert labels.pseudonyms([]) == {}


# AC 5 (P4): labels.NAMES classifies every workspace table, its columns are the foreign keys that reach a document
def test_labels_names_covers_every_table_and_the_keys_that_reach_a_document(db):
    assert set(labels.NAMES) == set(deletion.classification())

    def reaches(t):
        cols, rule = labels.NAMES[t]
        return t == "document" or bool(cols) or t == "expected_item"

    for t, (cols, rule) in labels.NAMES.items():
        fks = {r["from"]: r["table"] for r in db.execute(f"PRAGMA foreign_key_list({t})")}
        want = {"id": "document"} if t == "document" else {c: x for c, x in fks.items() if reaches(x)}
        assert cols == want, t
    assert {t for t, (_, rule) in labels.NAMES.items() if rule} == {"attempt", "expected_item", "gap_confirmation",
                                                                     "saved_view"}


def test_labels_named_walks_the_keys_and_applies_the_text_rules(tmp_path, gct):
    import gate_fixture

    root = gate_fixture.build(tmp_path / "gws")
    conn = store.connect(root / layout.DB_NAME)
    docs = {r[0] for r in conn.execute("SELECT id FROM document")}
    for t in labels.NAMES:
        for row in conn.execute(f"SELECT * FROM {t}").fetchall():
            assert labels.named(conn, t, row) <= docs, t
    for t in ("review_company", "review_auditor"):
        for row in conn.execute(f"SELECT * FROM {t}").fetchall():
            own = conn.execute("SELECT c.document_id FROM claim_version v JOIN claim c ON c.id = v.claim_id"
                               " WHERE v.id = ?", (row["claim_version_id"],)).fetchone()[0]
            assert labels.named(conn, t, row) == {own} | ({row["evidence_document_id"]} - {None})
    for row in conn.execute("SELECT * FROM adjudication").fetchall():
        sides = {d for (d,) in conn.execute(
            "SELECT c.document_id FROM claim_version v JOIN claim c ON c.id = v.claim_id WHERE v.id IN (?, ?)",
            (row["low_version_id"], row["high_version_id"]))}
        assert labels.named(conn, "adjudication", row) == sides | ({row["counter_document_id"]} - {None})
    read = conn.execute("SELECT * FROM attempt WHERE stage = 'read' LIMIT 1").fetchone()
    assert labels.named(conn, "attempt", read) == {int(read["item"].split(":")[0])}
    assert labels.named(conn, "attempt", {"run_id": None, "stage": "fetch", "item": "http://x/1.pdf"}) == set()
    assert labels.named(conn, "saved_view", {"contributor_version_id": 1}) == set()
    a, b = sorted(docs)[:2]
    with store.transaction(conn):
        conn.execute("INSERT INTO expected_item (company_id, metric_text, created_at) VALUES (1, 'x', 't')")
        item = conn.execute("SELECT MAX(id) FROM expected_item").fetchone()[0]
        conn.execute("INSERT INTO expected_item_document VALUES (?, ?)", (item, a))
    assert labels.named(conn, "expected_item", {"id": item}) == {a}
    gap = {"expected_item_id": item, "contributor_version_id": 1, "documents_checked": json.dumps([{"id": b}])}
    assert labels.named(conn, "gap_confirmation", gap) == {a, b}
    conn.close()


# AC 5: only labels.py reads the label to decide; every other reader is a named exemption (an AST and SQL scan)
SQL = re.compile(r"\b(SELECT|WHERE|JOIN|FROM|INSERT|UPDATE|CREATE)\b")
EXEMPT = {
    ("gct/workspace/labels.py", "*"),  # the lookup and inclusion code
    ("gct/workspace/registry.py", "DOCUMENT_SQL"),  # the stored label for display, through labels.STORED_*
    ("gct/workspace/registry.py", "_register"),  # writes document.privacy at intake
    ("gct/workspace/published.py", "PROJECTION_SCHEMA"),  # the projected column
    ("gct/workspace/published.py", "DOCUMENT_COLUMNS"),  # the projection through the stored label
    ("gct/workspace/published.py", "history_mark"),  # counts document_label ids only
    ("gct/stages/deletion.py", "KEPT"), ("gct/stages/deletion.py", "CLEAR"),  # the column classification
    ("gct/stages/deletion.py", "PROJECTION"), ("gct/stages/deletion.py", "RECORDS"),  # a deleted document's records
}


def label_reads(path: str, source: str) -> set[tuple[str, str]]:
    """(module, top-level name) of every string that reads document.privacy or the document_label table."""
    found = set()
    for node in ast.parse(source).body:
        names = ([node.name] if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else
                 [t.id for t in getattr(node, "targets", [getattr(node, "target", None)]) if isinstance(t, ast.Name)])
        for c in ast.walk(node):
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and (
                    "document_label" in c.value or (SQL.search(c.value) and re.search(r"\bprivacy\b", c.value))):
                found |= {(path, n) for n in names or ["<module>"]}
    return found


def test_only_labels_py_reads_the_label_to_decide():
    found = set()
    for p in sorted(GCT.rglob("*.py")):
        rel = p.relative_to(GCT.parent).as_posix()
        found |= {r for r in label_reads(rel, p.read_text(encoding="utf-8"))
                  if r not in EXEMPT and (rel, "*") not in EXEMPT}
    assert found == set()
    planted = 'ROWS = "SELECT id FROM document WHERE privacy = \'shareable\'"\ndef f(c):\n    return c.execute(' \
              '"SELECT privacy FROM document_label")\n'
    assert label_reads("gct/stages/planted.py", planted) == {("gct/stages/planted.py", "ROWS"),
                                                              ("gct/stages/planted.py", "f")}


# AC 8 (part A's projection lines): the projection carries the stored label; a relabel makes the version stale
def test_the_projection_carries_the_stored_label_and_a_relabel_makes_it_stale(acme, gct, db, make_file):
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme")
    assert gct("publish", "build").code == 0
    assert not gct("publish", "status", "--json").data["stale"]
    gct("doc", "label", 1, "--privacy", "shareable", *WHO)
    assert gct("publish", "status", "--json").data["stale"]
    assert published.history_mark(db).split(".")[-1] == "2"
    assert gct("publish", "build").code == 0
    for v, want in ((1, "private"), (2, "shareable")):
        conn = published.open_version(acme / "published" / f"v{v}.db")
        assert conn.execute("SELECT privacy FROM document").fetchone()[0] == want
        conn.close()


# Correction 4: deletion clears the label changes, keeps the intake row as it is, and shows the changes with the marker
def test_deletion_clears_label_changes_and_shows_them_with_the_marker(acme, gct, db, make_file):
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme")
    gct("doc", "add", make_file("b.pdf", PDF + b"b"), "--company", "Acme")
    sha = lambda d: db.execute("SELECT sha256 FROM document WHERE id = ?", (d,)).fetchone()[0]  # noqa: E731
    assert "document_label" not in gct("doc", "delete", 2, "--json").data["clears"]
    gct("doc", "label", 1, "--privacy", "shareable", *WHO)
    assert gct("doc", "delete", 1, "--json").data["clears"]["document_label"] == 1
    assert gct("doc", "delete", 1, "--confirm", sha(1)[:12], *WHO).code == 0
    marker = deletion.MARKER.format(1)
    assert label_rows(db) == [(1, "private", "unknown", None, None, None), (2, "private", "unknown", None, None, None),
                              (1, "shareable", "unknown", 1, marker, marker)]
    records = gct("doc", "show", 1, "--json").data["deletion"]["records"]
    (change,) = [r for r in records if r["kind"] == "label change"]
    assert (change["what"], change["contributor"], change["rationale"]) == (
        "shareable, availability unknown", "Ana", "cleared with document 1")
    assert change["evidence_deleted"]["document"] == 1
    assert "label change #3 shareable, availability unknown by Ana" in gct("doc", "show", 1).out
