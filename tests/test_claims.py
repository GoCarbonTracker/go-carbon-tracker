from conftest import make_pdf
from gct.workspace import published

A = make_pdf([{"text": [(72, 300, "Energy consumed 4,560 MWh in 2023")]}])
B = make_pdf([{"text": [(72, 300, "Water withdrawn 120 kL")]}])


def rows(path, sql):
    conn = published.open_version(path)
    try:
        return [tuple(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def test_claims_list(ws, gct, make_file):
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("a.pdf", A), "--company", "Acme")
    assert gct("claims", "list", "--doc", 1).out.strip() == "No claims yet. Run: gct extract 1"
    gct("read")
    r = gct("extract")
    assert r.code == 0 and "1 figures, 0 without a box" in r.out
    line = gct("claims", "list", "--doc", 1).out.strip()
    assert line.startswith("1  p1  4,560  MWh  Energy consumed  2023  unknown  matched  box ")
    (c,) = gct("claims", "list", "--doc", 1, "--json").data["claims"]
    assert (c["value"], c["method"], len(c["boxes"])) == (4560, "rung1-rules", 1)
    assert (c["source_match"], c["source_match_reason"]) == ("matched", None)


# AC 6
def test_publish_carries_the_claims_of_active_documents_only(ws, db, gct, make_file):
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("a.pdf", A), "--company", "Acme")
    gct("doc", "add", make_file("b.pdf", B), "--company", "Acme")
    gct("read")
    before = published.history_mark(db)
    gct("extract")
    assert published.history_mark(db) != before
    db.execute("INSERT INTO document_state (document_id, state, at) VALUES (2, 'archived', 't')")
    db.commit()
    v = gct("publish", "build", "--json").data
    path = ws / "published" / f"v{v['version']}.db"
    assert rows(path, "SELECT document_id, page_number, value_text, unit_text, metric_text, period_label,"
                      " reporting_boundary, method FROM claim") == [
        (1, 1, "4,560", "MWh", "Energy consumed", "2023", "unknown", "rung1-rules")]
    (ref,) = rows(path, "SELECT e.document_id, e.page_number, e.boxes FROM evidence_ref e"
                        " JOIN claim c ON c.claim_version_id = e.claim_version_id")
    assert ref[:2] == (1, 1) and ref[2].startswith("[[")
    assert rows(path, "SELECT COUNT(*) FROM evidence_ref") == [(1,)]
