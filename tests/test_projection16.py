"""Story 7.1 part C, C-projection (TASK-0218, P-match, AC 21): projection schema 16 adds match_candidate and the two
restatement claim ids, with three projection-local DELETE triggers. The projection-15 reader of E6 is the code of
E6_BASE, from `git archive`; the tests that use it skip outside a git checkout that holds it."""
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from old_code import run_old
from test_match import BOTH, SCOPE_1, WHO, ids, ready, series
from test_restate import NOTE, add, record
from gct.reports import pin as pinning
from gct.stages import deletion, match, view
from gct.workspace import layout, published
from gct.workspace.layout import GctError

E6_BASE = "1dcbd65"  # product main with E6's view and API, projection 15, workspace schema 20
MIA = ("--as", "mia", "--capacity", "canary-capacity", "--rationale", "canary-rationale")
CANARIES = (b"Mia Canaryname", b"Canary Org", b"canary-capacity", b"canary-rationale")
UNIT = "Qzkt"  # a printed unit no family knows: a unit as printed series whose key holds it
PRINTED = f"printed:{UNIT.lower()}"
TRIGGERS = {"match_candidate_claim", "match_candidate_series", "match_candidate_rule"}


@pytest.fixture
def acme(ws, gct):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")
    gct("contributor", "add", "mia", "--name", "Mia Canaryname", "--organisation", "Canary Org")


@pytest.fixture(scope="session")
def e6_tree(tmp_path_factory) -> Path:
    try:
        data = subprocess.run(["git", "archive", E6_BASE, "gct"], cwd=Path(__file__).resolve().parent.parent,
                              capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip(f"needs a git checkout containing {E6_BASE}")
    tree = tmp_path_factory.mktemp("e6-code")
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(tree, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    return tree


def old_python(tree: Path, script: str, *args) -> dict:
    """The JSON a script printed, run by the code of tree (its folder first on sys.path, as run_old does)."""
    p = subprocess.run([sys.executable, "-c", script, *map(str, args)], cwd=tree, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(tree)})
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout.splitlines()[-1])
    assert Path(out.pop("gct")).resolve().is_relative_to(tree.resolve())
    return out


@pytest.fixture
def world(ws, db, gct, make_file, acme):
    """Two waiting claims d and e (boundary unknown) with candidates standalone (rule points of a only) and
    consolidated (rule points of c and c2); d answered not_linked on consolidated, then linked to standalone; e
    answered nothing. A waiting claim w (unit unknown) whose only candidate is p's unit as printed series. A
    restatement row on an earlier version of r1's claim, restating r2's. Then version 1."""
    docs = {
        "a": add(gct, make_file, "a.pdf", [SCOPE_1]),
        "c": add(gct, make_file, "c.pdf", [SCOPE_1], boundary="consolidated"),
        "c2": add(gct, make_file, "c2.pdf", [["Total Scope 1 emissions", "tCO2e", "1,300", "1,200"]],
                  boundary="consolidated"),
        "d": add(gct, make_file, "d.pdf", [["Total Scope 1 emissions", "tCO2e", "999"]], periods=BOTH[:1], boundary=None),
        "e": add(gct, make_file, "e.pdf", [["Total Scope 1 emissions", "tCO2e", "888"]], periods=BOTH[:1], boundary=None),
        "p": add(gct, make_file, "p.pdf", [["Total waste generated", UNIT, "300", "250"]]),
        "w": add(gct, make_file, "w.pdf", [["Total waste generated", "", "41"]], periods=BOTH[:1]),
        "r1": add(gct, make_file, "r1.pdf", [["Total Scope 2 emissions", "tCO2e", "700", "650"]], lines=[(40, 150, NOTE)]),
        "r2": add(gct, make_file, "r2.pdf", [["Total Scope 2 emissions", "tCO2e", "640"]], periods=BOTH[1:]),
    }
    ready(gct)
    one = {k: ids(gct, docs[k])[(m, BOTH[0])] for k, m in (
        ("d", SCOPE_1[0]), ("e", SCOPE_1[0]), ("w", "Total waste generated"))}
    by = {(s["metric_key"], s["reporting_boundary"], s["unit_family"]): s["id"] for s in series(gct)}
    s = {"std": by[("ghg_scope_1", "standalone", "tco2e")], "con": by[("ghg_scope_1", "consolidated", "tco2e")],
         "p": by[("waste_total", "standalone", PRINTED)]}
    assert gct("match", "unlink", one["d"], "--series", s["con"], *MIA).code == 0
    assert gct("match", "link", one["d"], "--series", s["std"], *MIA).code == 0
    original = ids(gct, docs["r2"])[("Total Scope 2 emissions", BOTH[1])]
    restated = ids(gct, docs["r1"])[("Total Scope 2 emissions", BOTH[1])]
    assert record(gct, original, restated).code == 0
    earlier = db.execute("SELECT MAX(id) FROM claim_version WHERE claim_id = ?", (restated,)).fetchone()[0]
    assert gct("correct", restated, "--value", "641", *WHO).code == 0
    ready(gct)
    assert gct("publish", "build").code == 0
    return {"ws": ws, "docs": docs, "claims": one, "series": s, "original": original, "restated": restated,
            "earlier": earlier}


def rows(ws, version, sql, *params) -> list[tuple]:
    conn = published.open_version(published.version_path(ws, version))
    try:
        return [tuple(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def tables(ws, version) -> dict:
    conn = published.open_version(published.version_path(ws, version))
    try:
        return {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
                for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    finally:
        conn.close()


def candidates(ws, version=1) -> list[tuple]:
    return rows(ws, version, "SELECT claim_id, series_id, decision FROM match_candidate ORDER BY rowid")


def delete(gct, db, doc):
    token = db.execute("SELECT sha256 FROM document WHERE id = ?", (doc,)).fetchone()[0][:12]
    return gct("doc", "delete", doc, "--confirm", token, *WHO)


def no_residue(ws, version=1) -> None:
    """No candidate names a claim the file lacks or a series without a rule point there."""
    assert rows(ws, version, "SELECT * FROM match_candidate WHERE claim_id NOT IN (SELECT id FROM claim)"
                             " OR series_id NOT IN (SELECT series_id FROM series_point WHERE link = 'rule')") == []


# AC 21: ids, series key and the exact newest decision only; no match review text
def test_match_candidate_holds_ids_key_and_the_newest_decision(world, db):
    ws, c, s = world["ws"], world["claims"], world["series"]
    assert tables(ws, 1)["match_candidate"] == ["claim_id", "claim_version_id", "series_id", "series_key", "decision"]
    assert candidates(ws) == [(c["d"], s["std"], "linked"), (c["d"], s["con"], "not_linked"),
                              (c["e"], s["std"], None), (c["e"], s["con"], None), (c["w"], s["p"], None)]
    newest = {(r["claim_version_id"], r["series_key"]): r["decision"] for r in db.execute(match.NEWEST_REVIEWS)}
    projected = rows(ws, 1, "SELECT m.claim_id, m.claim_version_id, m.series_key, m.decision, s.id FROM match_candidate m"
                            " JOIN claim k ON k.id = m.claim_id AND k.claim_version_id = m.claim_version_id"
                            " LEFT JOIN series s ON s.id = m.series_id")
    assert len(projected) == 5 and all(sid for *_, sid in projected)  # each on the claim's version, each series projected
    assert {(v, key): d for _, v, key, d, _ in projected if d} == newest
    assert all(json.loads(key)[0] == 1 for *_, key, _, _ in projected)
    (key,) = [k for cl, _, k, _, _ in projected if cl == c["w"]]
    assert json.loads(key)[4:6] == [PRINTED, world["docs"]["p"]]  # document-derived text
    data = published.version_path(ws, 1).read_bytes()
    assert not [x for x in CANARIES if x in data]
    assert rows(ws, 1, "SELECT match_state, series_id FROM claim WHERE id = ?", c["d"]) == [("reviewed", s["std"])]


# AC 21: both claim ids on every restatement row, a row on an earlier version included
def test_restatement_rows_carry_both_claim_ids(world, db):
    ws = world["ws"]
    (row,) = rows(ws, 1, "SELECT original_claim_id, restated_claim_id, restated_version_id, binds FROM restatement")
    assert row == (world["original"], world["restated"], world["earlier"], 0)
    assert rows(ws, 1, "SELECT claim_version_id FROM claim WHERE id = ?", world["restated"]) != [(world["earlier"],)]


# AC 21: the three triggers; history_mark is unchanged (33 parts, test_published pins the literal)
def test_a_16_file_carries_the_triggers_and_history_mark_is_unchanged(world, db):
    assert {n for (n,) in rows(world["ws"], 1, "SELECT name FROM sqlite_master WHERE type = 'trigger'")} == TRIGGERS
    assert rows(world["ws"], 1, "SELECT value FROM meta WHERE key = 'projection_schema'") == [("16",)]
    assert len(published.history_mark(db).split(".")) == 33
    assert db.execute("SELECT history_mark FROM published_version").fetchone()[0] == published.history_mark(db)


# Deletion matrix: a deleted claim's candidates; a deleted document-scoped series with a text canary
def test_purge_removes_the_candidates_of_a_deleted_claim_and_of_a_deleted_series(world, db, gct):
    ws, c, s, docs = world["ws"], world["claims"], world["series"], world["docs"]
    assert delete(gct, db, docs["d"]).code == 0
    assert candidates(ws) == [(c["e"], s["std"], None), (c["e"], s["con"], None), (c["w"], s["p"], None)]
    assert delete(gct, db, docs["p"]).code == 0
    assert candidates(ws) == [(c["e"], s["std"], None), (c["e"], s["con"], None)]
    assert rows(ws, 1, "SELECT id FROM series WHERE id = ?", s["p"]) == []
    assert PRINTED.encode() not in published.version_path(ws, 1).read_bytes()
    no_residue(ws)


# Deletion matrix: a series kept only by a reviewed point loses its candidates; a mixed series keeps its own
def test_a_series_without_a_rule_point_loses_its_candidates_and_a_mixed_series_keeps_them(world, db, gct):
    ws, c, s, docs = world["ws"], world["claims"], world["series"], world["docs"]
    assert delete(gct, db, docs["c2"]).code == 0  # consolidated keeps c's rule points
    assert delete(gct, db, docs["a"]).code == 0  # standalone keeps only d's reviewed point
    assert rows(ws, 1, "SELECT link FROM series_point WHERE series_id = ?", s["std"]) == [("reviewed",)]
    assert rows(ws, 1, "SELECT id FROM series WHERE id = ?", s["std"]) == [(s["std"],)]
    assert candidates(ws) == [(c["d"], s["con"], "not_linked"), (c["e"], s["con"], None), (c["w"], s["p"], None)]
    no_residue(ws)


# Deletion matrix: restatement rows naming a deleted claim, an earlier-version row included, from either side
@pytest.mark.parametrize("side", ["r1", "r2"])
def test_a_restatement_row_goes_with_either_claim_document(world, db, gct, side):
    assert len(rows(world["ws"], 1, "SELECT id FROM restatement")) == 1
    assert delete(gct, db, world["docs"][side]).code == 0
    assert rows(world["ws"], 1, "SELECT id FROM restatement") == []


# AC 21 and deletion matrix: a retained 15 file (built by E6_BASE) and a 16 file purged in one deletion; the new
# table and columns only at 16; the 15 file restores and pin refuses it
def test_retained_15_and_16_files_are_purged_in_one_deletion_and_the_15_file_restores(world, db, gct, e6_tree):
    ws, c, s, docs = world["ws"], world["claims"], world["series"], world["docs"]
    (r,) = run_old(e6_tree, ws, ("publish", "build", "--json"), newer=True)  # E6_BASE is schema 20; ws is 21
    assert r["code"] == 0 and json.loads(r["out"])["version"] == 2
    assert gct("publish", "build").code == 0
    assert sorted(p.name for p in (ws / "published").iterdir()) == ["v2.db", "v3.db"]
    old, new = tables(ws, 2), tables(ws, 3)
    assert rows(ws, 2, "SELECT value FROM meta WHERE key = 'projection_schema'") == [("15",)]
    assert "match_candidate" not in old and "match_candidate" in new
    assert set(new["restatement"]) - set(old["restatement"]) == {"original_claim_id", "restated_claim_id"}
    assert {t: cols for t, cols in new.items() if t != "match_candidate"} == {
        t: [*cols, *(("original_claim_id", "restated_claim_id") if t == "restatement" else ())] for t, cols in old.items()}
    assert rows(ws, 2, "SELECT name FROM sqlite_master WHERE type = 'trigger'") == []
    gone = [docs["d"], docs["r1"]]
    for d in gone:
        assert delete(gct, db, d).code == 0
    claims = [k for (k,) in db.execute("SELECT id FROM claim WHERE document_id IN (?, ?)", gone)]
    for v in (2, 3):
        assert rows(ws, v, "SELECT id FROM document WHERE id IN (?, ?)", *gone) == []
        assert rows(ws, v, "SELECT id FROM claim WHERE document_id IN (?, ?)", *gone) == []
        assert rows(ws, v, "SELECT id FROM restatement") == []
        assert rows(ws, v, "SELECT claim_id FROM series_point WHERE claim_id IN (SELECT value FROM json_each(?))",
                    json.dumps(claims)) == []
    assert candidates(ws, 3) == [(c["e"], s["std"], None), (c["e"], s["con"], None), (c["w"], s["p"], None)]
    no_residue(ws, 3)
    r = gct("publish", "restore", "--json")
    assert r.code == 0 and r.data["version"] == 2
    with pytest.raises(GctError) as e:
        pinning.pin(db, ws)
    assert (e.value.code, e.value.cause, e.value.next_action) == (
        layout.REFUSED, "Data version 2 was built by an older gct and cannot be filtered.", published.BUILD_AGAIN)
    view.pinned(db, ws)[1].close()  # E6 still reads it


OLD_PURGE = """
import json, sys
from pathlib import Path
import gct
from gct.workspace import published
a = json.loads(sys.argv[1])
published.purge(Path(a["path"]), a["doc"], a["claims"], a["versions"], [], "cleared")
print(json.dumps({"gct": gct.__file__}))
"""


def old_purge(tree, db, path, d) -> None:
    """E6_BASE's purge of document d from the file at path, with the ids its deletion would pass."""
    old_python(tree, OLD_PURGE, json.dumps({
        "path": str(path), "doc": d, "claims": [x for (x,) in db.execute("SELECT id FROM claim WHERE document_id = ?", (d,))],
        "versions": [x for (x,) in db.execute(deletion.VERSIONS, {"d": d})]}))


# AC 21: E6_BASE's purge of a alone, while d survives: standalone keeps d's reviewed point and its series row, so
# only match_candidate_rule can remove standalone's candidates; consolidated keeps its own (Codex review of 68ba933)
def test_the_older_purge_of_the_last_rule_points_leaves_the_reviewed_point_and_no_candidate(world, db, e6_tree, tmp_path):
    ws, docs, s, c = world["ws"], world["docs"], world["series"], world["claims"]
    path = tmp_path / "copy.db"
    shutil.copyfile(published.version_path(ws, 1), path)
    old_purge(e6_tree, db, path, docs["a"])
    conn = sqlite3.connect(path)
    try:
        points = conn.execute("SELECT link, claim_id FROM series_point WHERE series_id = ?", (s["std"],)).fetchall()
        kept = conn.execute("SELECT id FROM series WHERE id = ?", (s["std"],)).fetchall()
        left = conn.execute("SELECT claim_id, series_id, decision FROM match_candidate ORDER BY rowid").fetchall()
    finally:
        conn.close()
    assert points == [("reviewed", c["d"])] and kept == [(s["std"],)]
    assert left == [(c["d"], s["con"], "not_linked"), (c["e"], s["con"], None), (c["w"], s["p"], None)]


# AC 21: E6_BASE's purge, which does not know match_candidate, run directly on a 16 file: the triggers leave no
# candidate behind; the same purge on the file without its triggers does (so the check can fail)
@pytest.mark.parametrize("triggers", [True, False])
def test_the_older_purge_on_a_16_file_leaves_no_candidate(world, db, e6_tree, tmp_path, triggers):
    ws, docs = world["ws"], world["docs"]
    path = tmp_path / "copy.db"
    shutil.copyfile(published.version_path(ws, 1), path)
    if not triggers:
        conn = sqlite3.connect(path)
        for t in TRIGGERS:
            conn.execute(f"DROP TRIGGER {t}")
        conn.commit()
        conn.close()
    for k in ("d", "p", "a"):  # the waiting claim's own, a document-scoped series, the last rule points of standalone
        old_purge(e6_tree, db, path, docs[k])
    conn = sqlite3.connect(path)
    try:
        left = conn.execute("SELECT claim_id, series_id FROM match_candidate ORDER BY rowid").fetchall()
        bad = conn.execute("SELECT COUNT(*) FROM match_candidate WHERE claim_id NOT IN (SELECT id FROM claim)"
                           " OR series_id NOT IN (SELECT series_id FROM series_point WHERE link = 'rule')").fetchone()[0]
    finally:
        conn.close()
    s, c = world["series"], world["claims"]
    if triggers:
        assert left == [(c["e"], s["con"])] and bad == 0
    else:
        assert len(left) == 5 and bad == 4
        assert PRINTED.encode() in path.read_bytes()


READER = """
import json, sys, urllib.request
from pathlib import Path
import gct
from gct.api import server
from gct.stages import view
from gct.workspace import published, store
root, claims = Path(sys.argv[1]), json.loads(sys.argv[2])
conn = store.connect(root / "workspace.db")
_, path = published.current_version(conn, root)
conn.close()
pconn = published.open_version(path)
sids = [s for (s,) in pconn.execute("SELECT id FROM series ORDER BY id")]
out = {"view": {shape: view.answer(pconn, {}, shape) for shape in view.SHAPES},
       "series": {s: view.answer(pconn, {"series": [s]}, "series") for s in sids}}
pconn.close()
srv = server.serve(root, port=0)
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def ask(p, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{srv.port}{p}", data=body and json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {srv.token}", "Content-Type": "application/json"})
    with opener.open(req, timeout=30) as r:
        return json.loads(r.read())
try:
    docs = [d["id"] for d in ask("/api/companies/1/documents")["documents"]]
    out["api"] = {"companies": ask("/api/companies"), "documents": {d: ask(f"/api/documents/{d}") for d in docs},
                  "claims": {d: ask(f"/api/documents/{d}/claims") for d in docs},
                  "history": {c: ask(f"/api/claims/{c}/history") for c in claims},
                  "candidates": ask("/api/companies/1/candidates"), "questions": ask("/api/questions"),
                  "records": {s: ask("/api/records", {"shape": s}) for s in view.SHAPES},
                  "series": {s: ask("/api/records", {"shape": "series", "filter": {"series": [s]}}) for s in sids}}
finally:
    srv.stop()
print(json.dumps({"gct": gct.__file__, **out}))
"""


def _unversioned(x):
    if isinstance(x, dict):
        return {k: _unversioned(v) for k, v in x.items() if k != "data_version"}
    return [_unversioned(v) for v in x] if isinstance(x, list) else x


# AC 21: E6_BASE's view and API read a 16 file as they read the 15 file of the same data
def test_the_projection_15_reader_reads_a_16_file_unchanged(world, db, gct, e6_tree):
    ws = world["ws"]
    (r,) = run_old(e6_tree, ws, ("publish", "build", "--json"), newer=True)
    assert r["code"] == 0
    assert gct("publish", "build").code == 0  # version 3 (16) current, 2 (15) previous, same history
    claims = json.dumps([*world["claims"].values(), world["original"], world["restated"]])
    on_16 = old_python(e6_tree, READER, ws, claims)
    assert gct("publish", "restore").code == 0
    on_15 = old_python(e6_tree, READER, ws, claims)
    assert on_16["api"]["records"]["table"]["data_version"] == 3 and on_15["api"]["records"]["table"]["data_version"] == 2
    assert on_16["view"]["table"]["rows"] and on_16["api"]["claims"]
    std = on_16["series"][world["series"]["std"]]  # the reviewed point of d is read from the 16 file
    assert [p["not_comparable_reason"] for p in std["points"] if p["claim"]["id"] == world["claims"]["d"]] == [
        "boundary unknown"] and on_16["api"]["series"][world["series"]["std"]]["points"]
    assert _unversioned(on_16) == _unversioned(on_15)


# The code before schema 21 refuses the workspace before it can purge anything (a separate check from the reader's)
def test_the_code_of_schema_20_refuses_the_workspace(world, db, e6_tree):
    ws, d = world["ws"], world["docs"]["d"]
    before = {p.name: p.read_bytes() for p in (ws / "published").iterdir()}
    token = db.execute("SELECT sha256 FROM document WHERE id = ?", (d,)).fetchone()[0][:12]
    (r,) = run_old(e6_tree, ws, ("doc", "delete", d, "--confirm", token, *WHO))
    assert r["code"] == 4 and "newer" in r["err"], r["err"]
    assert db.execute("SELECT COUNT(*) FROM document_state WHERE state = 'deleted'").fetchone()[0] == 0
    assert {p.name: p.read_bytes() for p in (ws / "published").iterdir()} == before
