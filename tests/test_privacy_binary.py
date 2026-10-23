"""Credential-bearing PDFs retain rows but supply no transferable files or images."""
import json
from pathlib import Path

import pytest

from conftest import make_pdf
from gate_fixture import SCOPE_1, gct, page
from report_fixture import ready
from test_privacy_review_fixes import small  # noqa: F401
from test_labels import acme  # noqa: F401
from test_render_pdf import page_texts
from gct.reports import crops, dataset, package
from gct.workspace import layout, registry, store

KEY = "sk-EPIC7BinaryCredential872900000"


@pytest.mark.parametrize("mode", dataset.MODES)
def test_credential_document_supplies_no_files_or_images(small, make_file, mode, monkeypatch):
    root, safe = small
    at = ("--workspace", root)
    source = make_file("credential.pdf", make_pdf([
        page([[SCOPE_1, "tCO2e", "22"]], ["FY 2024-25"]), {"text": [(40, 80, KEY)]}]))
    doc = gct("doc", "add", source, "--company", "Acme", "--privacy", "shareable",
              *at)["items"][0]["document"]["id"]
    ready(at)
    gct("publish", "build", *at)
    monkeypatch.setattr(store, "now", lambda: "2026-10-23T00:00:00+00:00")
    conn = store.connect(root / layout.DB_NAME)
    try:
        d, _ = dataset.build(conn, root, mode=mode)
        secret = registry.show_document(conn, doc)
        original = registry.stored_path(root, secret["sha256"])
        readings = {r[0] for r in conn.execute("SELECT path FROM artifact WHERE document_id = ?", (doc,))}
        render = crops._render

        def safe_render(path, number, scale):
            assert path != original
            return render(path, number, scale)

        monkeypatch.setattr(crops, "_render", safe_render)
        images = crops.cut(root, d)
        denied = {e["id"] for e in d["evidence"] if e["document_id"] == doc}
        safe_ids = {e["id"] for e in d["evidence"] if e["document_id"] == safe and e["page"] is not None}
        assert denied and safe_ids
        assert not denied & set(images)
        assert safe_ids <= set(images)
        note = next(n for n in d["notices"] if n.startswith(f"Evidence images for document {doc} ("))
        assert "credential.pdf" in note and KEY not in note
        with monkeypatch.context() as mp:
            mp.setattr(crops, "credential_documents", lambda *a: set())
            unheld, _ = dataset.build(conn, root, mode=mode)
        assert {k: v for k, v in d.items() if k != "notices"} == {
            k: v for k, v in unheld.items() if k != "notices"}
        assert d["notices"] == [*unheld["notices"], note]
        p = package.plan(conn, root, mode)
        assert "Original and reading files for document " + str(doc) in "\n".join(p["lines"])
        out = package.create(conn, root, mode, (), p["token"], include_private=mode == "complete")
        folder = root / out["folder"]
        assert not (folder / original.relative_to(root)).exists()
        assert not any((folder / r).exists() for r in readings)
        manifest = json.loads((folder / package.MANIFEST).read_text())
        assert f"document {doc} (credential.pdf)" in manifest["text"]
        for path in folder.rglob("*"):
            if path.is_file():
                assert KEY.encode() not in path.read_bytes(), path
    finally:
        conn.close()
    flags = ("--complete",) if mode == "complete" else ()
    out = gct("report", "all", "--format", "json,xlsx,csv,pdf,page", *flags, *at)
    folder = Path(out["folder"])
    pdf = "\n".join(page_texts(folder / "evidence-index.pdf"))
    assert f"Evidence images for document {doc} (credential.pdf)" in pdf
    assert "credential or could not be read" in " ".join(pdf.split())
    assert KEY not in pdf
    html = (folder / "evidence-index.html").read_text()
    assert note in html
    assert not any((folder / "crops" / f"E{i}.png").exists() for i in denied)
    assert all((folder / "crops" / f"E{i}.png").exists() for i in safe_ids)


@pytest.mark.parametrize("reading", [False, True])
def test_any_page_credential_withholds_the_document(acme, make_file, reading):
    at = ("--workspace", acme)
    source = make_file("any-page.pdf", make_pdf([{"text": [(40, 80, "clean")]}, {"text": [(40, 80, KEY)]}]))
    doc = gct("doc", "add", source, "--company", "Acme", "--privacy", "shareable", *at)["items"][0]["document"]["id"]
    if reading:
        gct("read", *at)
    conn = store.connect(acme / layout.DB_NAME)
    try:
        docs = [registry.show_document(conn, doc)]
        assert crops.credential_documents(conn, acme, docs) == {doc}
    finally:
        conn.close()


def test_unreadable_pdf_text_fails_closed(acme, make_file, monkeypatch):
    import pdfplumber

    doc = gct("doc", "add", make_file("broken.pdf"), "--company", "Acme", "--privacy", "shareable",
              "--workspace", acme)["items"][0]["document"]["id"]
    conn = store.connect(acme / layout.DB_NAME)
    try:
        def failed(*args, **kwargs):
            raise ValueError("unreadable text layer")

        monkeypatch.setattr(pdfplumber, "open", failed)
        assert crops.credential_documents(conn, acme, [registry.show_document(conn, doc)]) == {doc}
    finally:
        conn.close()


def test_all_images_withheld_do_not_claim_the_image_count_limit(small, monkeypatch, tmp_path):
    from gct.reports import render_page, render_pdf

    root, doc = small
    conn = store.connect(root / layout.DB_NAME)
    try:
        row = conn.execute("SELECT path FROM artifact WHERE document_id = ? LIMIT 1", (doc,)).fetchone()
        reading = root / row[0]
        content = json.loads(reading.read_text())
        content["text"] = "ｓｋ－EPIC7BinaryCredential872900000"
        reading.write_text(json.dumps(content))
        d, _ = dataset.build(conn, root)
    finally:
        conn.close()
    assert crops.cut(root, d) == {}
    assert any(n.startswith(f"Evidence images for document {doc} (") for n in d["notices"])
    out = tmp_path / "withheld"
    out.mkdir()
    page_out = render_page.write(d, ["evidence_index"], out, {})
    render_pdf.write(d, ["evidence_index"], out, {})
    assert page_out["notes"] == []
    assert "<img " not in (out / "evidence-index.html").read_text()
    assert d["words"]["fixed"]["image_limit"] not in (out / "evidence-index.html").read_text()
    assert "draws as images" not in " ".join(page_texts(out / "evidence-index.pdf"))
