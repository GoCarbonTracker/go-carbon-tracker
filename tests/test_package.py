"""Story 7.6 (TASK-0223): gct package preview and gct package create, complete and sanitised packages (D1 to D10).
The leakage scans through 7.7's found() with 7.1's report_fixture.SEEDS (G1, G2) and the differential (G6) wait for
those modules; the spot checks here use the gate fixture's own words and are no scanner."""
import ast
import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

import gate_fixture
from conftest import PDF
from test_intake import web  # noqa: F401 (a fixture)
from gct.reports import package
from gct.reports import pin as pinning
from gct.stages import deletion
from gct.workspace import layout, published, registry, runs, store

GCT = Path(__file__).resolve().parent.parent / "gct"
WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked the company website")
SHARED = [1, 2, 3]  # acme-2025.pdf, acme-2024.pdf and acme-meter.csv of the gate fixture
CSV = b"Metric,Value,Unit,Period\nTotal water recycled,40,kL,FY 2024-25\n"
KEY = "sk-" + "Q" * 24  # a credential typed into a record (scrubbed in both modes)


def read_back(path) -> dict:
    """A package as 7.7 reads it: every row of both databases (read-only, immutable), the manifest, every file."""
    path = Path(path)

    def rows(db):
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY rowid")] for (t,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")}
        finally:
            conn.close()

    return {"workspace": rows(path / layout.DB_NAME), "published": rows(path / "published" / "v1.db"),
            "manifest": json.loads((path / package.MANIFEST).read_text(encoding="utf-8")),
            "files": sorted(p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file())}


def dump(root) -> dict:
    conn = sqlite3.connect(Path(root) / layout.DB_NAME)
    try:
        return {t: conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
                for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")}
    finally:
        conn.close()


def tree(root) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for d in ("files", "artifacts", "published") for p in (Path(root) / d).rglob("*") if p.is_file()}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """The gate fixture with its first three documents relabelled shareable and a fresh version 2 (built once)."""
    root = gate_fixture.build(tmp_path_factory.mktemp("gate") / "gws")
    for d in SHARED:
        gate_fixture.gct("doc", "label", d, "--privacy", "shareable", *WHO, "--workspace", root)
    gate_fixture.gct("publish", "build", "--workspace", root)
    return root


@pytest.fixture
def src(built, tmp_path, monkeypatch):
    root = tmp_path / "src"
    shutil.copytree(built, root)
    monkeypatch.setenv("GCT_WORKSPACE", str(root))
    return root


def preview(gct, *flags) -> dict:
    r = gct("package", "preview", *flags, "--json")
    assert r.code == 0, r.out
    return r.data


def create(gct, *flags, token=None):
    """Preview with the same mode and classes, then create with that token (or the one given)."""
    token = token or preview(gct, *(f for f in flags if f != "--include-private"))["token"]
    return gct("package", "create", *flags, "--confirm", token, "--json")


def made(src) -> list:
    return sorted(p.name for p in (src / "exports").iterdir())


def run_count(src) -> int:
    return len(dump(src)["run"])


def refused(gct, src, argv, cause, code=4) -> dict:
    """The command is refused with this cause and writes nothing: no folder, no .incoming-*, no run."""
    before, runs_before = made(src), run_count(src)
    r = gct(*argv, "--json")
    assert (r.code, r.data["status"], r.data["cause"]) == (code, "error", cause), r.data
    assert made(src) == before and run_count(src) == runs_before
    return r.data


# AC 1 (D3 test (a)): COLUMNS names every table and column of a freshly migrated workspace, and nothing else
def unclassified(conn) -> set:
    schema = {(t, r[1]) for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"
                                                 " AND name NOT LIKE 'sqlite_%'") for r in conn.execute(f"PRAGMA table_info({t})")}
    return schema ^ {(t, c) for t, cols in package.COLUMNS.items() for c in cols}


def test_columns_cover_every_table_and_column(tmp_path):
    root = layout.init_workspace(tmp_path / "w")[1]
    conn = store.connect(root / layout.DB_NAME)
    assert unclassified(conn) == set()
    assert {c for cols in package.COLUMNS.values() for c in cols.values()} == {
        package.ID, package.ID_HASH, package.KEEP, package.CONTENT, package.IDENTITY, package.TEXT, package.LOCAL}
    conn.execute("ALTER TABLE claim_note ADD COLUMN mood TEXT")  # a later migration that classifies nothing
    assert unclassified(conn) == {("claim_note", "mood")}
    conn.close()


# AC 1 (D3 test (b)): what deletion calls content is never id, id_hash or keep; every stage says how its items name
# documents (a new Stage name fails until it is added here with an item labels.named resolves)
ITEMS = {"read": "7:2", "extract": "7:2", "sheet": "7:1", "link": "7:REF", "infer": "7", "match": "7"}


def test_columns_agree_with_deletion_and_every_stage_names_its_documents(tmp_path):
    for t, cols in deletion.classification().items():
        for c, cls in cols.items():
            if cls == "content":
                assert package.COLUMNS[t][c] not in (package.ID, package.ID_HASH, package.KEEP), (t, c)
    stages = {n.args[0].value for p in GCT.rglob("*.py") for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
              if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Stage" and n.args
              and isinstance(n.args[0], ast.Constant)}
    assert stages == set(ITEMS) | {"fetch"}
    from gct.workspace import labels
    conn = store.connect(layout.init_workspace(tmp_path / "w")[1] / layout.DB_NAME)
    for stage, item in ITEMS.items():
        assert labels.named(conn, "attempt", {"run_id": None, "stage": stage, "item": item}) == {7}, stage
    assert labels.named(conn, "attempt", {"run_id": None, "stage": "fetch", "item": "http://x/7.pdf"}) == set()
    conn.close()


# AC 1 (ID_TEXT): each entry parses the stored values of its column (on the gate fixture; on 7.1 part C's fixture when
# it lands); infer and match input_version stay id_hash, outside ID_TEXT
def test_id_text_entries_parse_the_stored_values(src):
    conn = store.connect(src / layout.DB_NAME)
    seen = {}
    for (table, column), spec in package.ID_TEXT.items():
        stages = spec.get("stages")
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        for r in rows:
            if stages and r["stage"] not in stages or r[column] is None:
                continue
            value = r[column]
            if "pattern" in spec:
                found = re.search(spec["pattern"], value)
                assert found or spec.get("partial"), (table, column, value)
                if found:
                    assert conn.execute(f"SELECT 1 FROM {spec['table']} WHERE id = ?", (int(found[1]),)).fetchone()
                    seen[table, column] = True
            else:
                data = json.loads(value)
                keys = spec["json"][r["stage"]] if stages else spec["json"]
                for entry in data if spec.get("list") else [data]:
                    for key, target in keys.items():
                        ids = entry[key] if isinstance(entry[key], list) else [entry[key]]
                        assert all(conn.execute(f"SELECT 1 FROM {target} WHERE id = ?", (i,)).fetchone() for i in ids)
                        seen[table, column] = True
    assert {("attempt", "item"), ("attempt", "input_version"), ("attempt", "output"), ("basis", "wording")} <= set(seen)
    assert package.COLUMNS["attempt"]["input_version"] == package.ID_HASH
    assert "infer" not in package.ID_TEXT["attempt", "input_version"]["stages"]
    assert "match" not in package.ID_TEXT["attempt", "input_version"]["stages"]
    conn.close()


# AC 2: package.py holds no second map and no SQL naming the label or the document-naming columns
def test_package_py_has_no_map_of_its_own_and_no_label_sql():
    tree_ = ast.parse((GCT / "reports" / "package.py").read_text(encoding="utf-8"))
    dicts = {t.id for n in tree_.body if isinstance(n, (ast.Assign, ast.AnnAssign))
             and (isinstance(n.value, (ast.Dict, ast.DictComp)) or isinstance(n.value, ast.Call) and (getattr(
                 n.value.func, "id", None) in ("dict", "_c") or getattr(n.value.func, "attr", None) == "fromkeys"))
             for t in (n.targets if isinstance(n, ast.Assign) else [n.target]) if isinstance(t, ast.Name)}
    assert dicts == {"COLUMNS", "ID_TEXT"}
    sql = re.compile(r"\b(SELECT|WHERE|JOIN|FROM|INSERT|UPDATE)\b")
    for n in ast.walk(tree_):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and sql.search(n.value):
            for word in ("document_label", "privacy", "documents_checked", "expected_item_document"):
                assert word not in n.value, (word, n.value)


# AC 3, 4, 7, 8 (G3, G4): the sanitised package equals its preview, holds only shareable rows and reopens
def test_a_sanitised_package_holds_what_its_preview_says_and_reopens(src, gct, make_file):
    p = preview(gct)
    assert p["filter"] == {} and p["mode"] == "sanitised" and set(p) >= {
        "included", "withheld", "history_mark", "labels_mark", "filter", "lines", "data_version", "mode", "include",
        "not_in_packages", "token"}
    out = create(gct, token=p["token"])
    assert out.code == 0, out.data
    folder = src / out.data["folder"]
    back, ws = read_back(folder), read_back(folder)["workspace"]
    assert {t: len(ws[t]) for t in p["included"]["tables"]} == p["included"]["tables"]
    assert [[d["id"], d["sha256"]] for d in ws["document"]] == [[d["id"], d["sha256"]] for d in
                                                                   p["included"]["documents"]]
    assert [d["id"] for d in ws["document"]] == SHARED and {d["label"] for d in p["included"]["documents"]} == {
        "shareable"}
    files = p["included"]["files"]
    assert set(back["files"]) == {"workspace.db", "published/v1.db", package.MANIFEST} | {
        f"files/{o['sha256'][:2]}/{o['sha256']}" for o in files["originals"]} | {
        a["path"] for a in ws["artifact"] if (src / a["path"]).is_file()}
    assert len([f for f in back["files"] if f.startswith("artifacts/")]) == files["readings"] > 0
    assert not [f for f in back["files"] if f.endswith(("-wal", "-shm")) or f.startswith(("logs/", "artifacts/pages"))]
    assert not list((src / "exports").glob(".incoming-*"))
    # D3, D4, D7: no approval, saved view, fetch attempt or run line but each shipped run's finished event
    assert ws["approval"] == [] and ws["saved_view"] == [] and not [a for a in ws["attempt"] if a["stage"] == "fetch"]
    assert {(e["kind"], e["item"], e["message"]) for e in ws["run_event"]} == {("finished", None, None)}
    assert {e["run_id"] for e in ws["run_event"]} == {r["id"] for r in ws["run"]}
    who = [(c["contributor_key"], c["name"], c["organisation"]) for c in ws["contributor_version"]]
    assert who == [(f"contributor-{n}", f"Contributor {n}", None) for n in range(1, len(who) + 1)] and who
    for t, cols in package.COLUMNS.items():
        for c in (c for c, cls in cols.items() if cls == package.TEXT):
            assert {r[c] for r in ws.get(t, [])} <= {None, package.MARKER}, (t, c)
    assert {d["source"] for d in ws["document"]} == {None}
    conn = store.connect(folder / layout.DB_NAME)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [] and registry.verify(conn, folder) == []
    assert all(runs.selection(conn, r["id"]) is None for r in ws["run"])
    conn.close()
    # spot checks (not G2): words the gate fixture stored are in the source and absent from the package
    words = (b"Ana", b"Raj", b"Acme audit", b"beta-2025.pdf", b"acme-old.pdf", b"/tmp", gate_fixture.VERIFIED.encode(),
             b"compared both tables")
    source = (src / "workspace.db").read_bytes()
    raw = b"".join((folder / f).read_bytes() for f in ("workspace.db", "published/v1.db"))
    for word in words:
        assert word in source and word not in raw, word
    # J6: the recipient reopens the package, adds a report and processes it
    w = ("--workspace", folder)
    assert gct("workspace", "status", *w).code == 0
    assert [d["id"] for d in gct("doc", "list", *w, "--json").data["documents"]] == SHARED
    assert {r["outcome"] for r in gct("run", "list", *w, "--json").data["runs"]} == {"ok"}
    assert ", 0 read, 2 cached," in gct("read", *w).out
    assert ", 0 extracted, 3 cached," in gct("extract", *w).out
    shipped_run = ws["run"][0]["id"]
    resume = gct("run", "resume", shipped_run, *w, "--json")
    assert resume.code == 4 and resume.data["cause"] == f"Run {shipped_run} finished; nothing to resume."
    assert gct("doc", "add", make_file("new.csv", CSV), "--company", "Acme", "--kind", "evidence", *w).code == 0
    assert gct("sheet", "map", 4, "--sheet", "new", "--metric", "Metric", "--value", "Value", "--unit", "Unit",
               "--period", "Period", "--year-end", "03-31", "--as", "contributor-1", "--capacity", "c",
               "--rationale", "r", *w).code == 0
    assert "1 extracted" in gct("extract", 4, *w).out
    assert gct("publish", "build", *w, "--json").data["version"] == 2
    assert gct("publish", "restore", *w, "--json").data["version"] == 1


# AC 6 (D6): complete needs --include-private, carries every row but approvals, and the source records the authorisation
def test_a_complete_package_needs_include_private_and_carries_every_row(src, gct):
    assert gct("doc", "label", 4, "--availability", "internal", "--as", "ana", "--capacity", "analyst",
               "--rationale", f"pasted {KEY} by mistake").code == 0
    assert gct("approve", "spend", "5").code == 0
    assert gct("publish", "build").code == 0
    p = preview(gct, "--complete")
    assert "It carries 3 private documents: 4, 6, 7." in p["lines"]
    refused(gct, src, ["package", "create", "--complete", "--confirm", p["token"]],
            "A complete package includes private content: 3 private documents, contributor names and text, and run"
            " log lines that name local paths.")
    before = dump(src)
    out = create(gct, "--complete", "--include-private", token=p["token"])
    assert out.code == 0, out.data
    folder = src / out.data["folder"]
    ws = read_back(folder)["workspace"]
    for t in package.COLUMNS:
        if t not in package.FROM_INIT + package.NEVER:
            assert len(ws[t]) == len(before[t]), t
    assert ws["approval"] == [] and len(before["approval"]) == 1
    assert "package create" not in {r["command"] for r in ws["run"]}
    assert [a for a in ws["artifact"] if a["document_id"] == 5] and not (
        folder / registry.stored_path(Path(), before["document"][4][4])).exists()
    assert KEY.encode() in (src / "workspace.db").read_bytes() and KEY.encode() not in (folder / "workspace.db").read_bytes()
    conn = store.connect(src / layout.DB_NAME)
    run_id = conn.execute("SELECT MAX(id) FROM run WHERE command = 'package create'").fetchone()[0]
    assert runs.selection(conn, run_id) == {"mode": "complete", "include": [], "token": p["token"],
                                            "folder": out.data["folder"]}
    assert "private content authorised: documents 4, 6, 7" in [e["message"] for e in runs.show_run(conn, run_id)["events"]]
    conn.close()
    w = ("--workspace", folder)  # J6 in the complete package
    assert gct("workspace", "status", *w).code == 0
    assert [d["id"] for d in gct("doc", "list", *w, "--json").data["documents"]] == [1, 2, 3, 4, 5, 6, 7]
    assert ", 0 extracted," in gct("extract", *w).out
    assert gct("publish", "build", *w, "--json").data["version"] == 2


# D7 (review finding): a shipped failed attempt is never replayed in a sanitised package; the source still retries it
def test_retry_of_a_shipped_failed_run_is_refused_in_the_package_and_works_in_the_source(ws, gct, tmp_path,
                                                                                        monkeypatch):
    from conftest import make_pdf
    from gct.stages import read

    gct("company", "add", "Acme")
    path = tmp_path / "shared.pdf"
    path.write_bytes(make_pdf([{"text": [(40, 80, "Total Scope 1 emissions 1,234")], "lines": []}]))
    assert gct("doc", "add", path, "--company", "Acme", "--privacy", "shareable").code == 0
    with monkeypatch.context() as m:
        m.setattr(read, "_work", lambda *a: (_ for _ in ()).throw(OSError("transient")))
        assert gct("read", 1).code == 4
    failed = dump(ws)["run"][-1][0]
    assert gct("publish", "build").code == 0
    folder = ws / create(gct).data["folder"]
    conn = store.connect(folder / layout.DB_NAME)
    assert conn.execute("SELECT COUNT(*) FROM attempt WHERE run_id = ? AND outcome = 'failed'", (failed,)).fetchone()[0]
    assert runs.selection(conn, failed) is None
    conn.close()
    before, files = dump(folder), tree(folder)
    r = gct("run", "retry", failed, "--workspace", folder, "--json")
    assert (r.code, r.data["cause"], r.data["next_action"]) == (
        4, f"Run {failed} has no record of what it was given, so it cannot be replayed.",
        "Run gct read again with the same documents.")
    assert dump(folder) == before and tree(folder) == files
    again = gct("run", "retry", failed, "--json")
    assert again.code == 0 and again.data["of_run"] == failed and again.data["documents"][0]["read"] == 1


def test_without_private_documents_the_complete_refusal_names_none(src, gct):
    for d in (4, 6, 7):
        assert gct("doc", "label", d, "--privacy", "shareable", *WHO).code == 0
    assert gct("publish", "build").code == 0
    refused(gct, src, ["package", "create", "--complete", "--confirm", preview(gct, "--complete")["token"]],
            "A complete package includes contributor names and text, and run log lines that name local paths.")


# AC 5, D8 order (1): what pin refuses
def test_no_version_is_refused(ws, gct, make_file):
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("a.pdf", PDF), "--company", "Acme", "--privacy", "shareable")
    refused(gct, ws, ["package", "preview"], "There is no published data version yet.")
    refused(gct, ws, ["package", "create", "--confirm", "x"], "There is no published data version yet.")


def test_an_older_projection_is_refused_until_publish_build(src, gct):
    out = sqlite3.connect(published.version_path(src, 2))
    out.execute("UPDATE meta SET value = '14' WHERE key = 'projection_schema'")
    out.commit()
    out.close()
    got = refused(gct, src, ["package", "preview"], "Data version 2 was built by an older gct and cannot be filtered.")
    assert got["next_action"] == "Build a fresh version with: gct publish build"
    assert gct("publish", "build").code == 0
    assert preview(gct)["data_version"]["version"] == 3


def test_an_unfinished_deletion_is_refused(src, gct, monkeypatch):
    t = preview(gct)["token"]

    def boom(*a):
        raise OSError("held open")

    monkeypatch.setitem(deletion.WORK, "published", boom)
    assert gct("doc", "delete", 7, "--confirm", registry.show_document(store.connect(src / layout.DB_NAME), 7)[
        "sha256"][:12], *WHO).code == 4
    for argv in (["package", "preview"], ["package", "create", "--confirm", t]):
        refused(gct, src, argv, "Document 7 was deleted but its removal did not finish.")


# D8 (2): a stale version, by a relabel, an archive, a new review and a deletion between preview and create
@pytest.mark.parametrize("change", ["relabel", "archive", "review", "delete"])
def test_a_stale_version_is_refused(src, gct, change):
    t = preview(gct)["token"]
    conn = store.connect(src / layout.DB_NAME)
    claim, version = conn.execute("SELECT c.id, MAX(v.id) FROM claim c JOIN claim_version v ON v.claim_id = c.id"
                                  " WHERE c.document_id = 1 GROUP BY c.id ORDER BY c.id LIMIT 1").fetchone()
    sha = registry.show_document(conn, 7)["sha256"]
    conn.close()
    argv = {"relabel": ["doc", "label", 6, "--availability", "internal", *WHO],
            "archive": ["doc", "archive", 2, *WHO],
            "review": ["review", "company", claim, "--version", version, "--outcome", "accepted", "--conclusion",
                       "agrees", "--scope", "s", "--evidence-note", "ledger", "--as", "ana", "--capacity", "c"],
            "delete": ["doc", "delete", 7, "--confirm", sha[:12], *WHO]}[change]
    assert gct(*argv).code == 0
    for argv in (["package", "create", "--confirm", t], ["package", "preview"]):
        got = refused(gct, src, argv, "Data version 2 is out of date.")
        assert got["next_action"] == "Build a fresh version with: gct publish build"
    assert gct("publish", "build").code == 0
    assert create(gct).code == 0


# D8 (3): another token, with writes that leave the version fresh, and tokens of another mode or class set
MISMATCH = ("What the package would hold has changed since that preview, or the preview was for another mode or"
            " inclusion.")


def fresh(gct) -> bool:
    return gct("publish", "status", "--json").data["stale"] is False


def test_a_token_that_no_longer_matches_is_refused(src, gct):
    t = preview(gct)["token"]
    assert gct("publish", "build").code == 0 and fresh(gct)  # a new sha256
    refused(gct, src, ["package", "create", "--confirm", t], MISMATCH)
    # A first gct link also writes source_match rows, which history_mark counts, so it makes the version stale; a
    # stage result alone (an attempt of a shipped document) leaves the version fresh and still changes the token.
    assert gct("link").code == 0 and not fresh(gct) and gct("publish", "build").code == 0
    t = preview(gct)["token"]
    conn = store.connect(src / layout.DB_NAME)
    mark, attempts = published.history_mark(conn), len(dump(src)["attempt"])
    conn.execute("INSERT INTO attempt (run_id, stage, item, input_version, config_version, outcome, at)"
                 " VALUES (1, 'link', '1:t0r9c9', 'x', 'y', 'ok', 'now')")
    assert published.history_mark(conn) == mark and len(dump(src)["attempt"]) == attempts + 1 and fresh(gct)
    conn.close()
    refused(gct, src, ["package", "create", "--confirm", t], MISMATCH)
    t = preview(gct, "--complete")["token"]
    assert gct("read").code == 0 and fresh(gct)  # any run changes what a complete package holds
    refused(gct, src, ["package", "create", "--complete", "--include-private", "--confirm", t], MISMATCH)
    refused(gct, src, ["package", "create", "--include", "identity", "--confirm", preview(gct)["token"]], MISMATCH)
    refused(gct, src, ["package", "create", "--complete", "--include-private", "--confirm", preview(gct)["token"]],
            MISMATCH)


def test_a_write_to_a_table_that_does_not_ship_leaves_the_token_valid(src, gct):
    t = preview(gct)["token"]
    assert gct("approve", "spend", "5").code == 0
    assert gct("view", "save", "mine", "--filter", "{}", "--as", "ana").code == 0
    assert preview(gct)["token"] == t
    assert create(gct, token=t).code == 0


# D8 (4): every document private: the preview shows P-empty's lines adapted, create refuses with the relabel line
def test_an_empty_sanitised_plan_previews_the_relabel_line_and_create_refuses(src, gct):
    for d in SHARED:
        assert gct("doc", "label", d, "--privacy", "private", *WHO).code == 0
    assert gct("publish", "build").code == 0
    p = preview(gct)
    assert p["included"]["documents"] == [] and p["lines"][1:] == [
        package.EMPTY, *(line for line in p["lines"][2:-1]), package.RELABEL] and len(p["lines"]) == 3 + 7
    assert p["lines"][2] == "  1  Acme  acme-2025.pdf  private label"
    got = refused(gct, src, ["package", "create", "--confirm", p["token"]], package.EMPTY)
    assert got["next_action"] == package.RELABEL
    assert create(gct, "--complete", "--include-private").code == 0  # complete mode is not empty


# D8 (5): an existing final name is refused, never overwritten
def test_an_existing_package_name_is_refused(src, gct, monkeypatch):
    monkeypatch.setattr(package, "_stamp", lambda: "20261023T000000000000Z")
    t = preview(gct)["token"]
    assert create(gct, token=t).code == 0
    first = tree(src / "exports" / made(src)[0])
    stem = "package-v2-20261023T000000000000Z-sanitised"
    refused(gct, src, ["package", "create", "--confirm", t],
            f"A package named {stem} already exists; nothing was overwritten.")
    assert tree(src / "exports" / stem) == first


# AC 5: a failed check removes the .incoming- folder and records the run failed; sanitised retries with the same token
def test_a_failed_check_writes_no_folder_and_records_the_run_failed(src, gct, monkeypatch):
    for mode in ([], ["--complete", "--include-private"]):
        t = preview(gct, *mode[:1])["token"]
        monkeypatch.setattr(registry, "verify", lambda conn, root: [{"problem": "missing"}])
        r = gct("package", "create", *mode, "--confirm", t, "--json")
        cause = "The package did not verify: an original file does not match its document."
        assert (r.code, r.data["cause"]) == (4, cause)
        assert made(src) == [] or all(not m.startswith(".incoming-") for m in made(src))
        conn = store.connect(src / layout.DB_NAME)
        last = runs.list_runs(conn)[0]
        assert (last["command"], last["outcome"]) == ("package create", "failed")
        conn.close()
        monkeypatch.undo()
        monkeypatch.setenv("GCT_WORKSPACE", str(src))
        again = gct("package", "create", *mode, "--confirm", t, "--json")
        if mode:  # the failed run is in what a complete package holds, so its token changed
            assert again.code == 4 and again.data["cause"] == MISMATCH
        else:
            assert again.code == 0


# R3 preservation: preview writes nothing; create adds one run with its events and changes nothing else
def test_preview_writes_nothing_and_create_adds_only_its_run(src, gct):
    assert gct("workspace", "status").code == 0  # any upgrade run is written before the comparison
    before, files = dump(src), tree(src)
    for flags in ([], ["--complete"], ["--include", "identity,contributor_text,flags"]):
        preview(gct, *flags)
        assert gct("package", "preview", *flags).code == 0
    assert dump(src) == before and tree(src) == files
    t = preview(gct)["token"]
    assert create(gct, token=t).code == 0
    after = dump(src)
    new_run = [r for r in after["run"] if r not in before["run"]]
    assert len(new_run) == 1 and new_run[0][2] == "package create"
    assert {e[1] for e in after["run_event"] if e not in before["run_event"]} == {new_run[0][0]}
    assert {t_: rows for t_, rows in after.items() if t_ not in ("run", "run_event")} == {
        t_: rows for t_, rows in before.items() if t_ not in ("run", "run_event")}
    assert tree(src) == files


# AC 7: each inclusion class restores only its part
def test_each_inclusion_class_restores_only_its_part(src, gct):
    conn = store.connect(src / layout.DB_NAME)
    claim, version = conn.execute("SELECT c.id, MAX(v.id) FROM claim c JOIN claim_version v ON v.claim_id = c.id"
                                  " WHERE c.document_id = 1 GROUP BY c.id ORDER BY c.id LIMIT 1").fetchone()
    conn.close()
    assert gct("flag", "raise", claim, "--version", version, *WHO).code == 0
    assert gct("publish", "build").code == 0
    got = {}
    for inc in ("", "identity", "contributor_text", "flags"):
        out = create(gct, *(["--include", inc] if inc else []))
        assert out.code == 0, out.data
        ws = read_back(src / out.data["folder"])["workspace"]
        got[inc] = ({c["name"] for c in ws["contributor_version"]}, {r["rationale"] for r in ws["correction"]},
                    len(ws["reviewer_flag"]), read_back(src / out.data["folder"])["manifest"]["include"])
    assert got[""] == ({"Contributor 1", "Contributor 2"}, set(), 0, [])
    assert got["identity"][0] == {"Ana", "Raj"} and got["identity"][2] == 0
    assert got["contributor_text"][0] == got[""][0] and got["contributor_text"][2] == 0
    assert got["flags"] == ({"Contributor 1", "Contributor 2"}, set(), 1, ["flags"])
    ws = read_back(src / create(gct, "--include", "contributor_text").data["folder"])["workspace"]
    assert {h["note"] for h in ws["highlight"]} == {"largest energy figure"}


# Moka's ruling Q1: a spreadsheet declaration's wording is regenerated with the pseudonym, never edited in place
def test_a_declared_basis_names_the_pseudonym_and_another_wording_gets_the_marker(src, gct):
    folder = src / create(gct).data["folder"]
    back = read_back(folder)
    declared = [b["wording"] for b in back["workspace"]["basis"] if b["document_id"] == 3]
    key = {r["id"]: r["name"] for r in back["workspace"]["contributor_version"]}
    mapping = back["workspace"]["sheet_mapping"][0]
    assert declared == [f"declared in sheet mapping #{mapping['id']} by {key[mapping['contributor_version_id']]}"] * 2
    assert {json.loads(c["period_basis"])["wording"] for c in back["published"]["claim"] if c["document_id"] == 3} == {
        declared[0]}
    ident = read_back(src / create(gct, "--include", "identity").data["folder"])["workspace"]["basis"]
    assert [b["wording"] for b in ident if b["document_id"] == 3] == ["declared in sheet mapping #1 by Ana"] * 2
    row = {"document_id": 3, "wording": "declared in sheet mapping #1 by Ana (edited)"}
    ctx = {"file_types": {3: "csv"}, "ship": {"sheet_mapping": [{"id": 1, "document_id": 3, "contributor_version_id": 1}]},
           "who": {1: {"name": "Ana", "contributor_key": "ana"}}, "names": {"ana": "Contributor 1"}}
    assert package._declared(row, row["wording"], ctx) == package.MARKER
    assert package._declared({"document_id": 3}, "declared in sheet mapping #1 by Ana", ctx) == (
        "declared in sheet mapping #1 by Contributor 1")


# AC 7: a contributor seen only on a sheet_mapping row is numbered; two versions of one key share one number
def test_a_contributor_only_on_a_mapping_is_numbered(src, gct, make_file):
    gct("contributor", "add", "sam", "--name", "Sam")
    gct("doc", "add", make_file("s.csv", CSV), "--company", "Acme", "--kind", "evidence", "--privacy", "shareable")
    assert gct("sheet", "map", 8, "--sheet", "s", "--metric", "Metric", "--value", "Value", "--unit", "Unit",
               "--period", "Period", "--year-end", "03-31", "--as", "sam", "--capacity", "c", "--rationale", "r").code == 0
    assert gct("contributor", "edit", "ana", "--name", "Ana B").code == 0
    assert gct("doc", "label", 2, "--availability", "internal", *WHO).code == 0
    assert gct("publish", "build").code == 0
    ws = read_back(src / create(gct).data["folder"])["workspace"]
    by_id = {c["id"]: c["contributor_key"] for c in ws["contributor_version"]}
    assert sorted(set(by_id.values())) == ["contributor-1", "contributor-2", "contributor-3"]
    ana = {c["id"] for c in ws["contributor_version"]} - {m["contributor_version_id"] for m in ws["sheet_mapping"]
                                                          if m["document_id"] == 8}
    assert len({by_id[i] for i in ana if i in {r["contributor_version_id"] for r in ws["document_label"]
                                               if r["contributor_version_id"]}}) == 1


# D3 local: source ships only for an http(s) address of a document declared public
def test_a_source_ships_only_for_a_public_url(ws, gct, web):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    assert gct("doc", "add", web.url("/r.pdf"), "--company", "Acme", "--availability", "public").code == 0
    assert gct("doc", "add", web.url("/r2.pdf"), "--company", "Acme", "--privacy", "shareable").code == 0
    assert gct("publish", "build").code == 0
    back = read_back(ws / create(gct).data["folder"])["workspace"]
    assert [(d["id"], d["source"]) for d in back["document"]] == [(1, web.url("/r.pdf")), (2, None)]
    assert back["attempt"] == [] and {d["id"] for d in back["document"]} == {1, 2}
    assert {a[2] for a in dump(ws)["attempt"]} == {"fetch"}  # the source holds the download results


# Behaviour: archive, deletion, missing evidence, renewed review, same bytes (one test each)
def test_an_archived_shareable_document_ships_still_archived(src, gct):
    assert gct("doc", "archive", 2, *WHO).code == 0
    assert gct("publish", "build").code == 0
    folder = src / create(gct).data["folder"]
    back = read_back(folder)
    assert [s["state"] for s in back["workspace"]["document_state"] if s["document_id"] == 2] == ["registered",
                                                                                                 "archived"]
    meta = {m["key"]: m["value"] for m in back["published"]["meta"]}
    assert json.loads(meta["hidden_by_archive"])["documents"] == 1
    assert 2 not in {d["id"] for d in back["published"]["document"]}


def test_a_deleted_document_is_absent_from_the_sanitised_and_a_tombstone_in_the_complete(src, gct):
    conn = store.connect(src / layout.DB_NAME)
    sha = registry.show_document(conn, 5)["sha256"]
    conn.close()
    san = read_back(src / create(gct).data["folder"])
    assert 5 not in {d["id"] for d in san["workspace"]["document"]} and not san["workspace"]["document_deletion"]
    com = read_back(src / create(gct, "--complete", "--include-private").data["folder"])
    assert [s["state"] for s in com["workspace"]["document_state"] if s["document_id"] == 5][-1] == "deleted"
    assert com["workspace"]["document_deletion"] and not [f for f in com["files"] if sha in f]


def test_expected_items_ship_only_with_their_documents_and_keep_their_states(src, gct):
    assert gct("expect", "add", "--company", "Acme", "--metric", "Total Scope 1 emissions").code == 0
    assert gct("expect", "add", "--company", "Beta", "--metric", "Total Scope 1 emissions").code == 0
    assert gct("publish", "build").code == 0
    back = read_back(src / create(gct).data["folder"])
    assert [e["company_id"] for e in back["workspace"]["expected_item"]] == [1]
    source = sqlite3.connect(published.version_path(src, 3))
    source.row_factory = sqlite3.Row
    mine = [dict(r) for r in source.execute("SELECT * FROM expected_item WHERE company_id = 1")]
    source.close()
    assert back["published"]["expected_item"] == mine


# AC 2: attempt items, documents_checked, expected_item_document and the rows only pointed at, each by its own rule
def test_each_naming_rule_decides_its_rows(src, gct):
    assert gct("expect", "add", "--company", "Acme", "--metric", "Total water recycled").code == 0
    for d in (1, 2):  # charts are not read: accept the figures pages first
        assert gct("pages", "accept", "--doc", d, "--pages", "1", "--type", "figures", *WHO).code == 0
    assert gct("gap", "confirm", 1, *WHO).code == 0
    assert gct("publish", "build").code == 0
    ws = read_back(src / create(gct).data["folder"])["workspace"]
    source = store.connect(src / layout.DB_NAME)
    checked = {d["id"] for d in json.loads(source.execute("SELECT documents_checked FROM gap_confirmation").fetchone()[0])}
    declared = {d for (d,) in source.execute("SELECT document_id FROM expected_item_document")}
    assert checked <= set(SHARED) and declared <= set(SHARED)
    assert len(ws["gap_confirmation"]) == 1 and len(ws["expected_item_document"]) == len(declared)
    heads = {int(a["item"].split(":")[0]) for a in ws["attempt"]}
    assert heads == set(SHARED) and source.execute("SELECT COUNT(*) FROM attempt WHERE item LIKE '6%'").fetchone()[0]
    assert [c["name"] for c in ws["company"]] == ["Acme"]  # Beta has only private documents
    used = {r["run_id"] for t in ws.values() for r in t if "run_id" in r and t is not ws["run_event"]}
    assert {r["id"] for r in ws["run"]} == used < {r for (r,) in source.execute("SELECT id FROM run")}
    source.close()
    assert gct("doc", "label", 2, "--privacy", "private", *WHO).code == 0  # a declared and checked document
    assert gct("publish", "build").code == 0
    ws = read_back(src / create(gct).data["folder"])["workspace"]
    assert ws["gap_confirmation"] == [] and ws["expected_item"] == [] and ws["expected_item_document"] == []


def compare(src, folder, version) -> dict:
    """{table: {column}} of the package's v1 rows that differ from the source version's rows with the same id."""
    a = sqlite3.connect(published.version_path(src, version))
    b = sqlite3.connect(folder / "published" / "v1.db")
    out = {}
    for t in ("claim", "expected_item", "series", "series_point", "comparison", "restatement", "adjudication",
              "review_company", "review_auditor", "highlight", "sheet_mapping"):
        cols = [r[1] for r in b.execute(f"PRAGMA table_info({t})")]
        if "id" not in cols:  # series points and comparisons: every package row is a source row
            rows = set(a.execute(f"SELECT * FROM {t}"))
            out[t] = {"row"} if set(b.execute(f"SELECT * FROM {t}")) - rows else set()
            continue
        ra = {r[0]: r for r in a.execute(f"SELECT * FROM {t}")}
        for r in b.execute(f"SELECT * FROM {t}"):
            out.setdefault(t, set()).update(c for i, c in enumerate(cols) if ra[r[0]][i] != r[i])
    a.close()
    b.close()
    return {t: cols for t, cols in out.items() if cols}


# G5 and renewed review: the package's v1 equals the source version for shipped rows, apart from D3's replacements
def test_version_1_equals_the_source_version_for_shipped_rows(src, gct):
    com = src / create(gct, "--complete", "--include-private").data["folder"]
    assert compare(src, com, 2) == {}
    san = src / create(gct).data["folder"]
    diff = compare(src, san, 2)
    assert diff.pop("claim") == {"period_basis", "boundary_basis"}  # the declared wording names the pseudonym
    assert set(diff) <= {"restatement", "adjudication", "review_company", "review_auditor", "highlight",
                         "sheet_mapping"}
    for cols in diff.values():
        assert cols <= {"contributor_name", "contributor_organisation", "capacity", "rationale", "procedure", "scope",
                        "conclusion", "evidence_note", "note", "counter_note", "follow_up", "closure_reason"}, cols
    flags = [c["needs_re_review"] for c in read_back(san)["published"]["claim"]]
    assert flags and compare(src, san, 2).get("claim", set()) & {"needs_re_review", "claim_state"} == set()


def test_a_shareable_twin_of_a_private_file_is_withheld_with_its_cause(src, gct, tmp_path):
    copy = tmp_path / "twin.pdf"
    conn = store.connect(src / layout.DB_NAME)
    copy.write_bytes(registry.stored_path(src, registry.show_document(conn, 1)["sha256"]).read_bytes())
    conn.close()
    assert gct("doc", "add", copy, "--company", "Beta").code == 0  # private by default, same bytes as document 1
    assert gct("publish", "build").code == 0
    p = preview(gct)
    assert "  1  Acme  acme-2025.pdf  same file as private document 8" in p["lines"]
    assert p["withheld"]["same_bytes_private"] == 1 and p["withheld"]["private_document"] == 5
    back = read_back(src / create(gct, token=p["token"]).data["folder"])
    assert [d["id"] for d in back["workspace"]["document"]] == [2, 3]
    assert not [f for f in back["files"] if registry.show_document(store.connect(src / layout.DB_NAME), 1)[
        "sha256"] in f]


# AC 10 (FR72): only package.py says "sanitised package"; only create describes a folder as one, the one it wrote
PHRASE = re.compile(r"sanitised package", re.I)


def test_only_package_py_holds_the_phrase():
    found = {p.relative_to(GCT.parent).as_posix() for p in GCT.rglob("*.py")
             for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
             if isinstance(n, ast.Constant) and isinstance(n.value, str) and PHRASE.search(n.value)}
    assert found == {"gct/reports/package.py"}
    assert "A copy of the workspace folder is a complete copy of everything in it and is never a sanitised package." in (
        GCT.parent / "docs" / "packages.md").read_text(encoding="utf-8")


def outputs(gct, root) -> str:
    w = ("--workspace", root)
    return "\n".join(gct(*argv, *w).out + gct(*argv, *w).err for argv in (
        ("workspace", "status"), ("doc", "list"), ("publish", "status"), ("run", "list"), ("package", "preview"),
        ("package", "preview", "--complete")))


def test_no_command_calls_a_copied_or_changed_folder_sanitised(src, gct, tmp_path, make_file):
    out = create(gct)
    assert PHRASE.search(gct("package", "create", "--confirm", preview(gct)["token"]).out)  # create, of its own folder
    copy = tmp_path / "copy"
    shutil.copytree(src, copy)
    assert not PHRASE.search(outputs(gct, copy))
    conn = store.connect(copy / layout.DB_NAME)
    for d in (4, 6, 7):  # the private documents deleted by hand in the copy
        sha = registry.show_document(conn, d)["sha256"]
        assert gct("doc", "delete", d, "--confirm", sha[:12], *WHO, "--workspace", copy).code == 0
    conn.close()
    assert gct("publish", "build", "--workspace", copy).code == 0
    assert not PHRASE.search(outputs(gct, copy).replace(package.EMPTY, ""))
    folder = src / out.data["folder"]
    w = ("--workspace", folder)
    assert gct("doc", "add", make_file("p.pdf", PDF + b"p"), "--company", "Acme", *w).code == 0
    assert gct("publish", "build", *w).code == 0
    assert not PHRASE.search(outputs(gct, folder).replace(package.EMPTY, ""))
    manifest = read_back(folder)["manifest"]
    assert manifest["data_version"]["sha256"] != hashlib.sha256(published.version_path(folder, 2).read_bytes()).hexdigest()


# AC 12 (K15): the source version is shown, the manifest's identities equal pin's and the package's own file
def test_the_manifest_holds_both_identities_and_sanitised_ones_hold_no_marks(src, gct):
    conn = store.connect(src / layout.DB_NAME)
    pconn, source = pinning.pin(conn, src)
    pconn.close()
    conn.close()
    p = preview(gct)
    assert p["data_version"] == source and p["lines"][0].startswith("Package preview (sanitised) of data version 2,")
    for flags in ([], ["--complete", "--include-private"]):
        out = create(gct, *flags)
        assert "from data version 2 (built" in out.data["lines"][0] and out.data["lines"][2] == deletion.WARNING
        m = read_back(src / out.data["folder"])["manifest"]
        own = hashlib.sha256((src / out.data["folder"] / "published" / "v1.db").read_bytes()).hexdigest()
        assert m["data_version"]["sha256"] == own and m["data_version"]["version"] == 1 and own in m["text"]
        if flags:
            assert m["source_data_version"] == source and m["mode"] == "complete"
            assert set(m["data_version"]) == set(source)
        else:
            assert m["source_data_version"] == {k: source[k] for k in ("version", "built_at", "sha256",
                                                                         "projection_schema")}
            assert set(m["data_version"]) == {"version", "built_at", "sha256", "projection_schema"}
        assert set(m) == {"package_schema", "mode", "include", "created_at", "gct_version", "data_version",
                          "source_data_version", "text"} and m["package_schema"] == 1


# G7: every fixed text of package.py passes the wording guard
def test_package_texts_pass_the_wording_guard():
    from test_review import WORDS
    for n in ast.walk(ast.parse((GCT / "reports" / "package.py").read_text(encoding="utf-8"))):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            assert not WORDS.search(n.value) and "contradiction" not in n.value.lower(), n.value
