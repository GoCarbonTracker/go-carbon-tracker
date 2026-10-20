import hashlib

from conftest import PDF
from gct.workspace import registry, store


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stored(ws, data: bytes):
    d = sha(data)
    return ws / "files" / d[:2] / d


def files_on_disk(ws):
    return sorted(p.name for p in (ws / "files").rglob("*") if p.is_file())


def test_company_add_list_and_case_insensitive_exists(ws, gct):
    r = gct("company", "add", "  Acme Ltd ", "--sector-ref", "S1", "--sector-version", "v2", "--json")
    assert r.code == 0 and r.data["status"] == "ok"
    assert r.data["name"] == "Acme Ltd" and r.data["sector_ref"] == "S1" and r.data["sector_version"] == "v2"
    again = gct("company", "add", "ACME ltd", "--json")
    assert again.code == 0 and again.data["status"] == "exists" and again.data["id"] == r.data["id"]
    assert [c["name"] for c in gct("company", "list", "--json").data["companies"]] == ["Acme Ltd"]


def test_sector_columns_may_stay_empty(ws, gct, db):
    gct("company", "add", "Acme")
    row = db.execute("SELECT sector_ref, sector_version FROM company").fetchone()
    assert tuple(row) == (None, None)


def test_new_document(ws, gct, db, make_file):
    gct("company", "add", "Acme")
    f = make_file("report.pdf")
    r = gct("doc", "add", f, "--company", "Acme", "--json")
    assert r.code == 0 and r.data["status"] == "ok"
    d = r.data["document"]
    assert (d["logical_name"], d["version"], d["kind"], d["file_type"], d["privacy"], d["state"]) == (
        "report.pdf", 1, "report", "pdf", "private", "registered",
    )
    assert d["sha256"] == sha(PDF) and d["size_bytes"] == len(PDF)
    rows = db.execute("SELECT * FROM document").fetchall()
    assert len(rows) == 1 and rows[0]["sha256"] == sha(PDF)
    states = db.execute("SELECT state FROM document_state WHERE document_id = ?", (d["id"],)).fetchall()
    assert [s["state"] for s in states] == ["registered"]
    assert stored(ws, PDF).read_bytes() == PDF
    assert files_on_disk(ws) == [sha(PDF)]


def test_options_are_stored(ws, gct, make_file):
    gct("company", "add", "Acme")
    r = gct(
        "doc", "add", make_file("e.pdf"), "--company", "Acme", "--kind", "evidence",
        "--privacy", "shareable", "--name", "Annual 2024", "--source", "company website", "--json",
    )
    d = r.data["document"]
    assert (d["kind"], d["privacy"], d["logical_name"], d["source"]) == (
        "evidence", "shareable", "Annual 2024", "company website",
    )


def test_duplicate_same_company_same_bytes(ws, gct, db, make_file):
    gct("company", "add", "Acme")
    first = gct("doc", "add", make_file("a.pdf"), "--company", "Acme", "--json").data["document"]
    second = gct("doc", "add", make_file("renamed.pdf"), "--company", "Acme", "--json")
    assert second.code == 0 and second.data["status"] == "duplicate"
    assert second.data["document"]["id"] == first["id"]
    assert db.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM document_state").fetchone()[0] == 1
    assert files_on_disk(ws) == [sha(PDF)]


def test_new_version_keeps_both(ws, gct, db, make_file):
    gct("company", "add", "Acme")
    v2_bytes = PDF + b"changed"
    gct("doc", "add", make_file("r.pdf"), "--company", "Acme")
    r = gct("doc", "add", make_file("r.pdf", v2_bytes), "--company", "Acme", "--json")
    assert r.data["status"] == "ok" and r.data["document"]["version"] == 2
    rows = db.execute("SELECT version, sha256 FROM document ORDER BY version").fetchall()
    assert [(x["version"], x["sha256"]) for x in rows] == [(1, sha(PDF)), (2, sha(v2_bytes))]
    assert stored(ws, PDF).exists() and stored(ws, v2_bytes).exists()
    states = gct("doc", "list", "--workspace", ws, "--json").data["documents"]
    assert [(d["version"], d["state"]) for d in states] == [(1, "registered"), (2, "registered")]


def test_other_company_same_bytes_registers_separately_stores_once(ws, gct, db, make_file):
    gct("company", "add", "Acme")
    gct("company", "add", "Beta")
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme")
    r = gct("doc", "add", make_file("a.pdf"), "--company", "Beta", "--json")
    assert r.data["status"] == "ok" and r.data["document"]["version"] == 1
    assert db.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 2
    assert files_on_disk(ws) == [sha(PDF)]


def test_unknown_company(ws, gct, db, make_file):
    r = gct("doc", "add", make_file("a.pdf"), "--company", "Nobody")
    assert r.code == 3 and "gct company add" in r.err
    assert db.execute("SELECT COUNT(*) FROM document").fetchone()[0] == 0
    assert files_on_disk(ws) == []


def test_doc_list_filter_and_show(ws, gct, make_file):
    gct("company", "add", "Acme")
    gct("company", "add", "Beta")
    gct("doc", "add", make_file("a.pdf"), "--company", "Acme")
    gct("doc", "add", make_file("b.pdf", PDF + b"b"), "--company", "Beta")
    assert len(gct("doc", "list", "--json").data["documents"]) == 2
    only = gct("doc", "list", "--company", "beta", "--json").data["documents"]
    assert [d["company"] for d in only] == ["Beta"]
    assert gct("doc", "show", 1, "--json").data["document"]["logical_name"] == "a.pdf"
    assert gct("doc", "show", 99).code == 3


def test_verify_reports_corrupted_file(ws, gct, make_file):
    gct("company", "add", "Acme")
    doc = gct("doc", "add", make_file("a.pdf"), "--company", "Acme", "--json").data["document"]
    conn = store.connect(ws / "workspace.db")
    assert registry.verify(conn, ws) == []
    stored(ws, PDF).write_bytes(b"tampered")
    assert registry.verify(conn, ws) == [
        {"document_id": doc["id"], "sha256": sha(PDF), "problem": "mismatch"}
    ]
    stored(ws, PDF).unlink()
    assert registry.verify(conn, ws)[0]["problem"] == "missing"
    conn.close()
