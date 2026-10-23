import sqlite3
from pathlib import Path

import pytest

from conftest import PDF
from gct.workspace import published, store

PRIVATE_NAMES = ("published_version", "published_pointer", "published_purge", "document_state", "history_mark")


def state(db, doc_id, value):
    db.execute("INSERT INTO document_state (document_id, state, at) VALUES (?, ?, 't')", (doc_id, value))
    db.commit()


def rows(path, sql):
    conn = published.open_version(path)
    try:
        return [tuple(r) for r in conn.execute(sql)]
    finally:
        conn.close()


@pytest.fixture
def seeded(ws, gct, make_file):
    gct("company", "add", "Acme", "--sector-ref", "NACE:C10", "--sector-version", "2")
    gct("company", "add", "Beta")
    gct("doc", "add", make_file("a.pdf", PDF), "--company", "Acme")
    gct("doc", "add", make_file("b.pdf", PDF + b"b"), "--company", "Acme", "--privacy", "shareable")
    gct("doc", "add", make_file("c.pdf", PDF + b"c"), "--company", "Beta")
    return ws


def pointers(db):
    return [tuple(r) for r in db.execute("SELECT version, action FROM published_pointer ORDER BY id")]


def test_migration_applies_to_a_story_1_1_workspace(tmp_path):
    from importlib import resources

    conn = store.connect(tmp_path / "old.db")
    sql = (resources.files("gct.workspace") / "migrations" / "0001_initial.sql").read_text(encoding="utf-8")
    conn.executescript(sql + "INSERT INTO schema_version VALUES (1, 't');")
    conn.execute("INSERT INTO company (name, created_at) VALUES ('Acme', 't')")
    store.migrate(conn)
    assert [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY version")] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
    assert conn.execute("SELECT name FROM company").fetchall()[0][0] == "Acme"
    conn.close()


def test_fresh_workspace_has_both_migrations(db):
    assert [r[0] for r in db.execute("SELECT version FROM schema_version ORDER BY version")] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]


@pytest.mark.parametrize("table", ["published_version", "published_pointer", "published_purge"])
def test_published_tables_reject_update_and_delete(seeded, db, gct, table):
    for _ in range(3):
        gct("publish", "build")
    for stmt in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
            db.execute(stmt)


def test_build_writes_a_complete_read_only_version(seeded, db, gct):
    r = gct("publish", "build", "--json")
    assert r.code == 0 and r.data["version"] == 1 and r.data["companies"] == 2 and r.data["documents"] == 3
    path = seeded / "published" / "v1.db"
    assert rows(path, "SELECT name, sector_ref, sector_version FROM company ORDER BY id") == [
        ("Acme", "NACE:C10", "2"), ("Beta", None, None),
    ]
    assert rows(path, "SELECT logical_name, privacy FROM document ORDER BY id") == [
        ("a.pdf", "private"), ("b.pdf", "shareable"), ("c.pdf", "private"),
    ]
    meta = dict(rows(path, "SELECT key, value FROM meta"))
    assert meta["version"] == "1" and meta["projection_schema"] == "15" and meta["history_mark"] == "2.3.3.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.3"
    assert set(meta) == {"version", "built_at", "history_mark", "gct_version", "projection_schema", "hidden_by_archive",
                         "deleted_documents"}
    assert sorted(p.name for p in (seeded / "published").iterdir()) == ["v1.db"]
    assert pointers(db) == [(1, "build")]
    with pytest.raises(sqlite3.OperationalError):
        published.open_version(path).execute("INSERT INTO meta VALUES ('x', 'y')")


def test_only_active_documents_are_published(seeded, db, gct):
    state(db, 1, "archived")
    state(db, 2, "deleted")
    state(db, 3, "archived")
    state(db, 3, "restored")
    gct("publish", "build")
    assert rows(seeded / "published" / "v1.db", "SELECT id FROM document") == [(3,)]


def test_new_version_keeps_the_old_one(seeded, db, gct, make_file):
    gct("publish", "build")
    history = [db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("company", "document")]
    gct("doc", "add", make_file("d.pdf", PDF + b"d"), "--company", "Beta")
    gct("publish", "build")
    assert len(rows(seeded / "published" / "v2.db", "SELECT id FROM document")) == 4
    assert len(rows(seeded / "published" / "v1.db", "SELECT id FROM document")) == 3
    assert db.execute("SELECT COUNT(*) FROM document").fetchone()[0] == history[1] + 1
    assert db.execute("SELECT COUNT(*) FROM company").fetchone()[0] == history[0]


def test_doc_add_does_not_publish(seeded, db):
    assert db.execute("SELECT COUNT(*) FROM published_version").fetchone()[0] == 0
    assert not list((seeded / "published").iterdir())


def test_restore_moves_the_pointer_and_nothing_else(seeded, db, gct):
    gct("publish", "build")
    gct("publish", "build")
    before = {n: (seeded / "published" / n).read_bytes() for n in ("v1.db", "v2.db")}
    r = gct("publish", "restore", "--json")
    assert r.code == 0 and r.data["version"] == 1
    assert pointers(db) == [(1, "build"), (2, "build"), (1, "restore")]
    assert db.execute("SELECT COUNT(*) FROM published_version").fetchone()[0] == 2
    assert sorted(p.name for p in (seeded / "published").iterdir()) == ["v1.db", "v2.db"]
    assert before == {n: (seeded / "published" / n).read_bytes() for n in before}
    assert gct("publish", "restore", "--json").data["version"] == 2


def test_restore_refusals(seeded, db, gct):
    gct("publish", "build")
    r = gct("publish", "restore")
    assert r.code == 4 and "gct publish build" in r.err
    gct("publish", "build")
    state(db, 1, "deleted")  # deleted after both versions were built
    before = pointers(db)
    r = gct("publish", "restore")
    assert r.code == 4 and "deleted" in r.err and "gct publish build" in r.err
    assert pointers(db) == before
    (seeded / "published" / "v1.db").unlink()
    assert "no longer on disk" in gct("publish", "restore").err


def test_status_reports_stale(seeded, db, gct, make_file):
    assert gct("publish", "status", "--json").data["stale"] is False
    assert "gct publish build" in gct("publish", "status").out
    gct("publish", "build")
    assert gct("publish", "status", "--json").data["stale"] is False
    state(db, 1, "archived")
    assert gct("publish", "status", "--json").data["stale"] is True
    gct("publish", "build")
    assert gct("publish", "status", "--json").data["stale"] is False
    gct("doc", "add", make_file("z.pdf", PDF + b"z"), "--company", "Acme")
    st = gct("publish", "status", "--json").data
    assert st["stale"] is True and st["files"] == [1, 2] and st["previous_version"] == 1
    assert "Out of date: yes" in gct("publish", "status").out


def test_retention_keeps_current_and_previous(seeded, db, gct, monkeypatch):
    for _ in range(3):
        gct("publish", "build")
    assert sorted(p.name for p in (seeded / "published").iterdir()) == ["v2.db", "v3.db"]
    assert [tuple(r) for r in db.execute("SELECT version, reason FROM published_purge")] == [(1, "retention")]
    gct("publish", "restore")  # current 2, previous 3
    assert gct("publish", "status", "--json").data["current_version"] == 2
    gct("publish", "build")  # current 4, previous 2
    assert sorted(p.name for p in (seeded / "published").iterdir()) == ["v2.db", "v4.db"]

    real_unlink = Path.unlink

    def locked(self, *a, **k):
        if self.name == "v2.db":
            raise PermissionError("in use")
        return real_unlink(self, *a, **k)

    purges = db.execute("SELECT COUNT(*) FROM published_purge").fetchone()[0]
    with monkeypatch.context() as m:
        m.setattr(Path, "unlink", locked)
        assert gct("publish", "build").code == 0  # current 5, previous 4; v2 is old now
    assert (seeded / "published" / "v2.db").exists()
    assert db.execute("SELECT COUNT(*) FROM published_purge").fetchone()[0] == purges
    assert gct("publish", "build").code == 0
    assert sorted(p.name for p in (seeded / "published").iterdir()) == ["v5.db", "v6.db"]
    assert [r[0] for r in db.execute("SELECT version FROM published_purge ORDER BY id")] == [1, 3, 2, 4]


def test_crash_between_rename_and_record(seeded, db, gct, monkeypatch):
    gct("publish", "build")
    marks = [tuple(r) for r in db.execute("SELECT * FROM published_pointer")]

    def boom(conn):
        raise RuntimeError("crash")

    with monkeypatch.context() as m:
        m.setattr(published.store, "transaction", boom)
        assert gct("publish", "build").code == 1
    assert (seeded / "published" / "v2.db").exists()  # orphan
    assert [tuple(r) for r in db.execute("SELECT * FROM published_pointer")] == marks
    assert gct("publish", "status", "--json").data["current_version"] == 1
    r = gct("publish", "build", "--json")
    assert r.code == 0 and r.data["version"] == 2
    assert rows(seeded / "published" / "v2.db", "SELECT value FROM meta WHERE key = 'built_at'") == [(r.data["built_at"],)]


def test_concurrent_reader_keeps_its_rows(seeded, gct):
    gct("publish", "build")
    reader = published.open_version(seeded / "published" / "v1.db")
    first = [tuple(r) for r in reader.execute("SELECT id FROM document ORDER BY id")]
    gct("publish", "build")
    gct("publish", "build")
    assert [tuple(r) for r in reader.execute("SELECT id FROM document ORDER BY id")] == first
    reader.close()


def test_empty_workspace_builds_an_empty_version(ws, gct):
    r = gct("publish", "build", "--json")
    assert r.code == 0 and r.data["version"] == 1
    st = gct("publish", "status", "--json").data
    assert st["companies"] == 0 and st["documents"] == 0 and st["stale"] is False


def test_current_version_lookup(seeded, db, gct):
    assert published.current_version(db, seeded) is None
    gct("publish", "build")
    assert published.current_version(db, seeded) == (1, seeded / "published" / "v1.db")
    gct("publish", "build")
    gct("publish", "restore")
    assert published.current_version(db, seeded)[0] == 1
    gct("publish", "restore")
    assert published.current_version(db, seeded) == (2, seeded / "published" / "v2.db")


def test_refusals_hide_internal_names(seeded, db, gct):
    gct("publish", "build")
    gct("publish", "build")
    state(db, 1, "deleted")
    for flag in ([], ["--json"]):
        r = gct("publish", "restore", *flag)
        text = r.err + r.out
        assert r.code == 4 and "Traceback" not in text
        assert not any(n in text for n in PRIVATE_NAMES)
    r = gct("publish", "restore", "--json")
    assert r.data["cause"] and r.data["next_action"]
