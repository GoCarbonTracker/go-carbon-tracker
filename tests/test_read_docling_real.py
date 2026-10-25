import os
import pytest
from pathlib import Path

from gct.stages import read, extract
from gct.stages.read_docling import is_docling_available

THREE = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 3/Kids[3 0 R 4 0 R 5 0 R]>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R>>endobj\n"
    b"4 0 obj<</Type/Page/Parent 2 0 R>>endobj\n"
    b"5 0 obj<</Type/Page/Parent 2 0 R>>endobj\n"
    b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n"
    b"0000000115 00000 n \n0000000156 00000 n \n0000000197 00000 n \n"
    b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n238\n%%EOF\n"
)


@pytest.fixture
def add(gct, make_file):
    gct("company", "add", "Acme")

    def add(name, content=THREE, company="Acme"):
        r = gct("doc", "add", make_file(name, content), "--company", company, "--json")
        assert r.code == 0
        return r.data["items"][0]["document"]["id"]

    return add


@pytest.mark.skipif(not is_docling_available(), reason="docling not installed in test environment")
def test_docling_reading_and_extract_integration(ws, db, gct, add, monkeypatch):
    monkeypatch.setenv("GCT_USE_DOCLING", "1")
    add("r.pdf")

    # Run gct read
    res = gct("read", "--json")
    assert res.code == 0
    (doc,) = res.data["documents"]
    assert doc["read"] > 0

    # Verify workspace db recorded reading
    rows = db.execute("SELECT page_number, method, words, tables FROM page ORDER BY page_number").fetchall()
    assert len(rows) > 0

    # Run gct extract
    res_ext = gct("extract", "--json")
    assert res_ext.code == 0
