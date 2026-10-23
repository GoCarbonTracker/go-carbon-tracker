"""Story 7.1 part A (TASK-0218): gct.reports.pin, one published version per report build (C-version V1 to V3)."""
import hashlib
import sqlite3

import pytest

from conftest import PDF
from gct.reports import pin as pinning
from gct.stages import deletion, view
from gct.workspace import layout, published
from gct.workspace.layout import GctError

WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked the company website")


@pytest.fixture
def acme(ws, gct, make_file):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    for n in "ab":
        gct("doc", "add", make_file(f"{n}.pdf", PDF + n.encode()), "--company", "Acme", "--privacy", "shareable")
    return ws


def refusal(call):
    with pytest.raises(GctError) as e:
        call()
    return e.value.code, e.value.cause, e.value.next_action


def token(db, d):
    return db.execute("SELECT sha256 FROM document WHERE id = ?", (d,)).fetchone()[0][:12]


# Matrix "no version": the same refusal as view.pinned
def test_no_version_is_refused_as_view_pinned_refuses(acme, db):
    got = refusal(lambda: pinning.pin(db, acme))
    assert got == refusal(lambda: view.pinned(db, acme))
    assert got == (layout.REFUSED, "There is no published data version yet.", "Create one with: gct publish build")


# Matrix "explicit current pin" and V3: the identity; "stale": the same refusal as view.pinned
def test_the_current_version_is_pinned_and_a_stale_pin_is_refused(acme, gct, db):
    assert gct("publish", "build").code == 0
    gct("doc", "label", 1, "--availability", "public", *WHO)
    assert gct("publish", "build").code == 0
    pconn, ident = pinning.pin(db, acme, 2)
    path = published.version_path(acme, 2)
    built_at, mark = db.execute("SELECT built_at, history_mark FROM published_version WHERE version = 2").fetchone()
    assert ident == {"version": 2, "built_at": built_at, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "projection_schema": 16, "history_mark": mark, "labels_mark": 3}
    assert mark == published.history_mark(db)
    assert [tuple(r) for r in pconn.execute("SELECT id, privacy FROM document ORDER BY id")] == [(1, "shareable"),
                                                                                              (2, "shareable")]
    pconn.close()
    assert pinning.pin(db, acme)[1] == ident
    got = refusal(lambda: pinning.pin(db, acme, 1))
    assert got == refusal(lambda: view.pinned(db, acme, 1))
    assert got[1:] == ("Data version 1 is no longer the current one; the current version is 2.",
                       "Reload to see version 2.")


# Matrix "below 16": a file of an older projection is refused, with view.pinned's text (its own floor is 14)
def test_an_older_projection_is_refused(acme, gct, db):
    assert gct("publish", "build").code == 0
    path = published.version_path(acme, 1)
    out = sqlite3.connect(path)
    out.execute("UPDATE meta SET value = '13' WHERE key = 'projection_schema'")
    out.commit()
    out.close()
    got = refusal(lambda: pinning.pin(db, acme))
    assert got == refusal(lambda: view.pinned(db, acme))
    assert got[1:] == ("Data version 1 was built by an older gct and cannot be filtered.", published.BUILD_AGAIN)
    for schema in ("14", "15"):  # view still reads both; a report needs part C's match candidates (projection 16)
        out = sqlite3.connect(path)
        out.execute("UPDATE meta SET value = ? WHERE key = 'projection_schema'", (schema,))
        out.commit()
        out.close()
        assert refusal(lambda: pinning.pin(db, acme)) == got
        view.pinned(db, acme)[1].close()


# Matrix "missing current file"
def test_a_missing_current_file_is_refused(acme, gct, db):
    assert gct("publish", "build").code == 0
    published.version_path(acme, 1).unlink()
    assert refusal(lambda: pinning.pin(db, acme)) == (layout.REFUSED, "Version 1 is no longer on disk.",
                                                       published.BUILD_AGAIN)


# Matrix "pending purge", including a document archived and then deleted (K3)
@pytest.mark.parametrize("archived", [False, True])
def test_an_unfinished_deletion_is_refused_with_the_finish_command(acme, gct, db, monkeypatch, archived):
    assert gct("publish", "build").code == 0
    if archived:
        assert gct("doc", "archive", 2, *WHO).code == 0

    def boom(*a):
        raise OSError("held open")

    real = deletion.WORK["published"]
    monkeypatch.setitem(deletion.WORK, "published", boom)
    assert gct("doc", "delete", 2, "--confirm", token(db, 2), *WHO).code == 4
    assert refusal(lambda: pinning.pin(db, acme)) == (
        layout.REFUSED, "Document 2 was deleted but its removal did not finish.",
        f"Finish removing it with: gct doc delete 2 --confirm {token(db, 2)}")
    monkeypatch.setitem(deletion.WORK, "published", real)  # not undo(): that drops the workspace setting too
    assert gct("doc", "delete", 2, "--confirm", token(db, 2), *WHO).code == 0
    pconn, ident = pinning.pin(db, acme)
    assert [r[0] for r in pconn.execute("SELECT id FROM document")] == [1]
    pconn.close()


# Matrix: a finished deletion whose current file still holds the document (a file put back by hand)
def test_a_version_that_still_holds_a_deleted_document_is_refused(acme, gct, db):
    assert gct("publish", "build").code == 0
    path = published.version_path(acme, 1)
    kept = path.read_bytes()
    assert gct("doc", "delete", 2, "--confirm", token(db, 2), *WHO).code == 0
    path.write_bytes(kept)
    assert refusal(lambda: pinning.pin(db, acme)) == (
        layout.REFUSED, "Version 1 still contains a document that has since been deleted.", published.BUILD_AGAIN)


def file_backed(conn, root, data_version=None):
    """The variant K14 rules out: the pin reads the version file itself instead of a copy of its bytes."""
    version, path = published.current_version(conn, root)
    return published.open_version(path), {"version": version}


# K14: a purge of the file after the pin changes nothing the build reads; reading the file itself would see it
@pytest.mark.parametrize("variant", [pinning.pin, file_backed])
def test_a_purge_after_the_pin_changes_nothing_the_build_reads(acme, gct, db, variant):
    assert gct("publish", "build").code == 0
    pconn, ident = variant(db, acme)
    read = lambda: [r[0] for r in pconn.execute("SELECT id FROM document ORDER BY id")]  # noqa: E731
    assert read() == [1, 2]
    path = published.version_path(acme, 1)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    published.purge(path, 2, [], [], [], deletion.MARKER.format(2))
    assert hashlib.sha256(path.read_bytes()).hexdigest() != before
    if variant is pinning.pin:
        assert read() == [1, 2]
        assert hashlib.sha256(pconn.serialize()).hexdigest() == before == ident["sha256"]
    else:
        assert read() == [1]  # shown failing: this is why the pin copies the bytes
    pconn.close()


# V2: the pinned copy refuses writes, and the file is never written through it
def test_the_pinned_copy_refuses_writes(acme, gct, db):
    assert gct("publish", "build").code == 0
    before = published.version_path(acme, 1).read_bytes()
    pconn, _ = pinning.pin(db, acme)
    for stmt in ("DELETE FROM document", "CREATE TABLE x (a)", "UPDATE meta SET value = '0'"):
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            pconn.execute(stmt)
    pconn.close()
    assert published.version_path(acme, 1).read_bytes() == before
