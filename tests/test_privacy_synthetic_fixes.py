"""Regression tests for synthetic privacy leak repairs FR1 through FR4.

Tests cover:
- FR1: PDF annotation appearance text credential withholding (packages and evidence crops).
- FR2: PDF /Info metadata credential withholding (packages).
- FR3: Spreadsheet (CSV and XLSX) cell credential withholding (packages).
- FR4: Fullwidth credential NFKC-aware redaction in package databases.
- Clean document export preservation and missing-original refusal.
"""
import io
import sqlite3
import unicodedata
import zipfile
from pathlib import Path

import openpyxl
import pytest

from gate_fixture import SCOPE_1, WHO, gct, page
from report_fixture import ready
from test_labels import acme  # noqa: F401
from gct.models.redact import scrub
from gct.reports import crops, dataset, package
from gct.workspace import layout, registry, store
from gct.workspace.layout import GctError, NOT_FOUND

KEY = "sk-PROBEFINALa1b2c3d4e5f6g7h8i9j0k1l2m3n4"
FULLWIDTH = "ｓｋ－EPIC7PdfCredential8729000000"


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_with(pages, size=(612, 792), info=None):
    """Make valid PDF with per-page text, stroked lines, FreeText annotations with /AP, and optional /Info metadata."""
    w, h = size
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for p in pages:
        ops = [f"BT /F1 12 Tf 1 0 0 1 {x} {h - top} Tm ({_esc(s)}) Tj ET" for x, top, s in p.get("text", [])]
        ops += [f"{x0} {h - t0} m {x1} {h - t1} l S" for x0, t0, x1, t1 in p.get("lines", [])]
        stream = "\n".join(ops).encode("latin-1")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")
        content = len(objs)
        annots = []
        for item in p.get("annots", []):
            x, top, s = item[0], item[1], item[2]
            if len(item) > 3 and item[3] == "raw":
                ap = f"BT /F1 12 Tf 2 10 Td {s} ET".encode("latin-1")
            else:
                ap = f"BT /F1 12 Tf 2 10 Td ({_esc(s)}) Tj ET".encode("latin-1")
            objs.append(f"<< /Type /XObject /Subtype /Form /BBox [0 0 400 30] /Resources << /Font << /F1 3 0 R >> >>"
                        f" /Length {len(ap)} >>\nstream\n".encode("latin-1") + ap + b"\nendstream")
            form = len(objs)
            objs.append(f"<< /Type /Annot /Subtype /FreeText /F 4 /Rect [{x} {h - top - 30} {x + 400} {h - top}]"
                        f" /Contents (note) /DA (/F1 12 Tf 0 g) /AP << /N {form} 0 R >> >>")
            annots.append(f"{len(objs)} 0 R")
        extra = f" /Annots [{' '.join(annots)}]" if annots else ""
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Resources << /Font << /F1 3 0 R >> >>"
                    f" /Contents {content} 0 R{extra} >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    info_ref = ""
    if info:
        objs.append(f"<< /Title ({_esc(info)}) >>")
        info_ref = f" /Info {len(objs)} 0 R"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + (body if isinstance(body, bytes) else body.encode("latin-1")) + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R{info_ref} >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def xlsx_with(rows):
    """Make valid XLSX bytes containing rows."""
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def find_needle_hits(folder: Path, needle: str = KEY) -> list[str]:
    """Find occurrences of needle in plain files and zip members under folder."""
    needle_bytes = needle.encode("utf-8")
    found = []
    for p in Path(folder).rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(folder))
        raw = p.read_bytes()
        if needle_bytes in raw:
            found.append(rel)
        elif zipfile.is_zipfile(p):
            try:
                with zipfile.ZipFile(p) as z:
                    for name in z.namelist():
                        if needle_bytes in z.read(name):
                            found.append(f"{rel}!{name}")
            except Exception:
                pass
    return sorted(found)


def _create_package(conn, root: Path, mode: str) -> Path:
    p = package.plan(conn, root, mode)
    made = package.create(conn, root, mode, (), p["token"], include_private=mode == "complete")
    return root / made["folder"]


@pytest.mark.parametrize("mode", dataset.MODES)
def test_fr1_pdf_annotation_credential_withheld(acme, make_file, mode):
    at = ("--workspace", acme)
    first = page([[SCOPE_1, "tCO2e", "22"]], ["FY 2024-25"])
    first["annots"] = [(40, 300, KEY)]
    src = make_file("annot.pdf", pdf_with([first]))
    doc = gct("doc", "add", src, "--company", "Acme", "--privacy", "shareable", *at)["items"][0]["document"]["id"]
    ready(at)
    gct("publish", "build", *at)

    conn = store.connect(acme / layout.DB_NAME)
    try:
        d = registry.show_document(conn, doc)

        # 1. Credential detection
        held = crops.credential_documents(conn, acme, [d])
        assert held == {doc}, f"FR1: Document with annotation credential was not held: {held}"

        # 2. Source original preservation in workspace files/: exact bytes match source
        orig = registry.stored_path(acme, d["sha256"])
        assert orig.is_file(), "FR1: Source original file missing from workspace"
        assert orig.read_bytes() == src.read_bytes(), "FR1: Stored original bytes differ from source bytes"

        # 3. Evidence image withholding in reports
        ds, _ = dataset.build(conn, acme, mode=mode)
        images = crops.cut(acme, ds)
        doc_ev_ids = [e["id"] for e in ds["evidence"] if e["document_id"] == doc]
        assert not any(eid in images for eid in doc_ev_ids), (
            f"FR1: Evidence image for doc {doc} was not withheld in mode {mode}: {images.keys()}"
        )

        # 4. Package original withholding in both package modes
        pkg_folder = _create_package(conn, acme, mode)
        hits = find_needle_hits(pkg_folder, KEY)
        assert not hits, f"FR1: Annotation credential leaked into {mode} package: {hits}"
    finally:
        conn.close()


@pytest.mark.parametrize("mode", dataset.MODES)
def test_fr2_pdf_metadata_credential_withheld(acme, make_file, mode):
    at = ("--workspace", acme)
    first = page([[SCOPE_1, "tCO2e", "22"]], ["FY 2024-25"])
    src = make_file("info.pdf", pdf_with([first], info=KEY))
    doc = gct("doc", "add", src, "--company", "Acme", "--privacy", "shareable", *at)["items"][0]["document"]["id"]
    ready(at)
    gct("publish", "build", *at)

    conn = store.connect(acme / layout.DB_NAME)
    try:
        d = registry.show_document(conn, doc)

        # 1. Credential detection
        held = crops.credential_documents(conn, acme, [d])
        assert held == {doc}, f"FR2: Document with metadata credential was not held: {held}"

        # 2. Source original preservation: exact bytes match source
        orig = registry.stored_path(acme, d["sha256"])
        assert orig.is_file(), "FR2: Source original file missing from workspace"
        assert orig.read_bytes() == src.read_bytes(), "FR2: Stored original bytes differ from source bytes"

        # 3. Package withholding in both package modes
        pkg_folder = _create_package(conn, acme, mode)
        hits = find_needle_hits(pkg_folder, KEY)
        assert not hits, f"FR2: Metadata credential leaked into {mode} package: {hits}"
    finally:
        conn.close()


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
@pytest.mark.parametrize("mode", dataset.MODES)
def test_fr3_spreadsheet_cell_credential_withheld(acme, make_file, kind, mode):
    at = ("--workspace", acme)
    rows = [["Parameter", "Unit", "FY 2024-25"], [SCOPE_1, "tCO2e", "22"], ["Note", KEY, ""]]
    content = ("\n".join(",".join(r) for r in rows) + "\n").encode() if kind == "csv" else xlsx_with(rows)
    src = make_file(f"sheet.{kind}", content)
    doc = gct("doc", "add", src, "--company", "Acme", "--privacy", "shareable", *at)["items"][0]["document"]["id"]
    ready(at)
    gct("publish", "build", *at)

    conn = store.connect(acme / layout.DB_NAME)
    try:
        d = registry.show_document(conn, doc)

        # 1. Credential detection
        held = crops.credential_documents(conn, acme, [d])
        assert held == {doc}, f"FR3: {kind.upper()} document with cell credential was not held: {held}"

        # 2. Source original preservation: exact bytes match source
        orig = registry.stored_path(acme, d["sha256"])
        assert orig.is_file(), f"FR3: {kind.upper()} source original file missing from workspace"
        assert orig.read_bytes() == src.read_bytes(), f"FR3: {kind.upper()} stored original bytes differ from source bytes"

        # 3. Package withholding in both package modes
        pkg_folder = _create_package(conn, acme, mode)
        hits = find_needle_hits(pkg_folder, KEY)
        assert not hits, f"FR3: {kind.upper()} cell credential leaked into {mode} package: {hits}"
    finally:
        conn.close()


@pytest.mark.parametrize("mode", dataset.MODES)
def test_fr4_fullwidth_credential_in_package_db_redacted(acme, make_file, mode):
    at = ("--workspace", acme)
    first = page([[SCOPE_1, "tCO2e", "55"]], ["FY 2024-25"])
    src = make_file("clean.pdf", pdf_with([first]))
    doc = gct("doc", "add", src,
              "--company", "Acme", "--privacy", "shareable", *at)["items"][0]["document"]["id"]
    ready(at)
    gct("publish", "build", *at)
    claim = gct("claims", "list", "--doc", doc, *at)["claims"][0]["id"]
    gct("correct", claim, "--value", FULLWIDTH, *WHO, *at)
    gct("publish", "build", *at)

    ascii_form = unicodedata.normalize("NFKC", FULLWIDTH)
    assert scrub(ascii_form) != ascii_form and scrub(FULLWIDTH) == FULLWIDTH

    conn = store.connect(acme / layout.DB_NAME)
    try:
        d = registry.show_document(conn, doc)
        orig = registry.stored_path(acme, d["sha256"])
        assert orig.is_file(), "FR4: Source original file missing from workspace"
        assert orig.read_bytes() == src.read_bytes(), "FR4: Stored original bytes differ from source bytes"

        pkg_folder = _create_package(conn, acme, mode)
        leaked_dbs = []
        for db_file in pkg_folder.rglob("*.db"):
            c = sqlite3.connect(db_file)
            dump = "\n".join(c.iterdump())
            c.close()
            if FULLWIDTH in dump or ascii_form in dump:
                leaked_dbs.append(str(db_file.relative_to(pkg_folder)))
        assert not leaked_dbs, f"FR4: Fullwidth credential leaked into {mode} package databases: {leaked_dbs}"
    finally:
        conn.close()


def test_control_clean_document_preserved_and_missing_original_refusal(acme, make_file):
    """Preserve clean-document export behavior and the restored missing-original refusal."""
    at = ("--workspace", acme)
    first = page([[SCOPE_1, "tCO2e", "22"]], ["FY 2024-25"])
    src = make_file("clean.pdf", pdf_with([first]))
    doc = gct("doc", "add", src, "--company", "Acme", "--privacy", "shareable", *at)["items"][0]["document"]["id"]
    ready(at)
    gct("publish", "build", *at)

    conn = store.connect(acme / layout.DB_NAME)
    try:
        d = registry.show_document(conn, doc)
        # Clean document is NOT held
        assert crops.credential_documents(conn, acme, [d]) == set()

        # Clean document stored original bytes match source bytes
        orig = registry.stored_path(acme, d["sha256"])
        assert orig.is_file(), "Control: Source original file missing from workspace"
        assert orig.read_bytes() == src.read_bytes(), "Control: Stored original bytes differ from source bytes"

        # Clean document evidence image is generated
        ds, _ = dataset.build(conn, acme, mode="sanitised")
        images = crops.cut(acme, ds)
        assert len(images) > 0, "Clean document evidence images should not be withheld"

        # Missing original refusal test: removing the stored copy triggers GctError NOT_FOUND
        orig_backup = orig.read_bytes()
        orig.unlink()
        try:
            with pytest.raises(GctError) as exc_info:
                crops.cut(acme, ds)
            assert exc_info.value.code == NOT_FOUND
            assert f"The stored copy of document {doc} is missing" in exc_info.value.cause
            assert "Add the same file again with gct doc add to restore it" in exc_info.value.next_action
        finally:
            orig.write_bytes(orig_backup)
    finally:
        conn.close()


def test_fr1_pdf_annotation_octal_escaped_credential_withheld(acme, make_file):
    """PDF annotation appearance stream with octal escapes is decoded and withheld."""
    at = ("--workspace", acme)
    first = page([[SCOPE_1, "tCO2e", "22"]], ["FY 2024-25"])
    octal = "".join(f"\\{ord(c):03o}" for c in KEY)
    first["annots"] = [(40, 300, f"({octal}) Tj", "raw")]
    src = make_file("octal.pdf", pdf_with([first]))
    assert KEY.encode() not in src.read_bytes(), "Test fixture error: raw key must not appear in octal PDF"
    doc = gct("doc", "add", src, "--company", "Acme", "--privacy", "shareable", *at)["items"][0]["document"]["id"]
    ready(at)
    gct("publish", "build", *at)

    conn = store.connect(acme / layout.DB_NAME)
    try:
        d = registry.show_document(conn, doc)
        held = crops.credential_documents(conn, acme, [d])
        assert held == {doc}, f"FR1 (octal): Document with octal annotation credential was not held: {held}"

        orig = registry.stored_path(acme, d["sha256"])
        assert orig.is_file(), "FR1 (octal): Source original file missing from workspace"
        assert orig.read_bytes() == src.read_bytes(), "FR1 (octal): Stored original bytes differ from source bytes"

        ds, _ = dataset.build(conn, acme, mode="sanitised")
        images = crops.cut(acme, ds)
        doc_ev_ids = [e["id"] for e in ds["evidence"] if e["document_id"] == doc]
        assert not any(eid in images for eid in doc_ev_ids), "FR1 (octal): Evidence images not withheld"

        pkg_folder = _create_package(conn, acme, "sanitised")
        hits = find_needle_hits(pkg_folder, KEY)
        assert not hits, f"FR1 (octal): Octal credential leaked into package: {hits}"
    finally:
        conn.close()


def test_fr1_pdf_annotation_hex_string_credential_withheld(acme, make_file):
    """PDF annotation appearance stream with hex string is decoded and withheld."""
    at = ("--workspace", acme)
    first = page([[SCOPE_1, "tCO2e", "22"]], ["FY 2024-25"])
    hex_s = KEY.encode("latin-1").hex()
    first["annots"] = [(40, 300, f"<{hex_s}> Tj", "raw")]
    src = make_file("hex.pdf", pdf_with([first]))
    assert KEY.encode() not in src.read_bytes(), "Test fixture error: raw key must not appear in hex PDF"
    doc = gct("doc", "add", src, "--company", "Acme", "--privacy", "shareable", *at)["items"][0]["document"]["id"]
    ready(at)
    gct("publish", "build", *at)

    conn = store.connect(acme / layout.DB_NAME)
    try:
        d = registry.show_document(conn, doc)
        held = crops.credential_documents(conn, acme, [d])
        assert held == {doc}, f"FR1 (hex): Document with hex annotation credential was not held: {held}"

        orig = registry.stored_path(acme, d["sha256"])
        assert orig.is_file(), "FR1 (hex): Source original file missing from workspace"
        assert orig.read_bytes() == src.read_bytes(), "FR1 (hex): Stored original bytes differ from source bytes"

        ds, _ = dataset.build(conn, acme, mode="sanitised")
        images = crops.cut(acme, ds)
        doc_ev_ids = [e["id"] for e in ds["evidence"] if e["document_id"] == doc]
        assert not any(eid in images for eid in doc_ev_ids), "FR1 (hex): Evidence images not withheld"

        pkg_folder = _create_package(conn, acme, "sanitised")
        hits = find_needle_hits(pkg_folder, KEY)
        assert not hits, f"FR1 (hex): Hex credential leaked into package: {hits}"
    finally:
        conn.close()


def test_fr1_pdf_annotation_parser_failure_withheld(acme, make_file):
    """PDF annotation appearance stream with parser syntax error fails closed and is withheld."""
    at = ("--workspace", acme)
    first = page([[SCOPE_1, "tCO2e", "22"]], ["FY 2024-25"])
    first["annots"] = [(40, 300, "[(broken array Tj", "raw")]
    src = make_file("corrupt.pdf", pdf_with([first]))
    doc = gct("doc", "add", src, "--company", "Acme", "--privacy", "shareable", *at)["items"][0]["document"]["id"]
    ready(at)
    gct("publish", "build", *at)

    conn = store.connect(acme / layout.DB_NAME)
    try:
        d = registry.show_document(conn, doc)
        held = crops.credential_documents(conn, acme, [d])
        assert held == {doc}, f"FR1 (parser failure): Corrupt stream was not held: {held}"

        orig = registry.stored_path(acme, d["sha256"])
        assert orig.is_file(), "FR1 (parser failure): Source original file missing from workspace"
        assert orig.read_bytes() == src.read_bytes(), "FR1 (parser failure): Stored bytes differ"

        ds, _ = dataset.build(conn, acme, mode="sanitised")
        images = crops.cut(acme, ds)
        doc_ev_ids = [e["id"] for e in ds["evidence"] if e["document_id"] == doc]
        assert not any(eid in images for eid in doc_ev_ids), "FR1 (parser failure): Images not withheld"
    finally:
        conn.close()


def test_package_file_notes_truthful_reason(acme, make_file):
    """Package file notes name source text, metadata or annotations instead of PDF text layer."""
    at = ("--workspace", acme)
    rows = [["Parameter", "Unit", "FY 2024-25"], [SCOPE_1, "tCO2e", "22"], ["Note", KEY, ""]]
    src = make_file("sheet.csv", ("\n".join(",".join(r) for r in rows) + "\n").encode())
    doc = gct("doc", "add", src, "--company", "Acme", "--privacy", "shareable", *at)["items"][0]["document"]["id"]
    ready(at)
    gct("publish", "build", *at)

    conn = store.connect(acme / layout.DB_NAME)
    try:
        p = package.plan(conn, acme, "sanitised")
        expected_phrase = "source text, metadata or annotations contain a credential or could not be read."
        assert any(expected_phrase in line for line in p["lines"]), (
            f"Package plan lines did not contain truthful withholding reason: {p['lines']}"
        )
        assert not any("PDF text layer contains" in line for line in p["lines"]), (
            f"Package plan lines still refer to PDF text layer for spreadsheet: {p['lines']}"
        )
    finally:
        conn.close()
