import os
import zipfile

import pytest

from conftest import PDF, xlsx_bytes
from gct.workspace import registry


@pytest.fixture
def add(ws, gct, make_file):
    gct("company", "add", "Acme")

    def run(name, content):
        return gct("doc", "add", make_file(name, content), "--company", "Acme", "--json")

    return run


def test_pdf_renamed_txt_is_accepted(add):
    r = add("notes.txt", PDF)
    assert r.code == 0 and r.data["document"]["file_type"] == "pdf"


def test_text_renamed_pdf_is_refused(add):
    assert add("fake.pdf", b"just some text, really").code == 4


def test_xlsx_accepted(add, tmp_path):
    r = add("book.xlsx", xlsx_bytes(tmp_path))
    assert r.code == 0 and r.data["document"]["file_type"] == "xlsx"


def test_csv_with_and_without_bom(add):
    plain = add("a.csv", b"a,b\n1,2\n")
    bom = add("b.csv", b"\xef\xbb\xbfa;b\n1;2\n")
    assert plain.data["document"]["file_type"] == "csv"
    assert bom.data["document"]["file_type"] == "csv"


def test_csv_must_decode_and_have_a_delimiter(add):
    assert add("nodelim.csv", b"single column\nvalue\n").code == 4
    assert add("latin.csv", b"a,b\n\xe9,2\n").code == 4


def test_csv_extension_required(add):
    assert add("data.txt", b"a,b\n1,2\n").code == 4


def test_docx_refused(add, tmp_path):
    docx = xlsx_bytes(tmp_path, parts=("[Content_Types].xml", "word/document.xml"))
    assert add("memo.docx", docx).code == 4


def test_empty_file_refused(add):
    assert add("empty.pdf", b"").code == 4
    assert add("empty.csv", b"").code == 4


def test_xlsx_missing_workbook_part_refused(add, tmp_path):
    assert add("x.xlsx", xlsx_bytes(tmp_path, parts=("[Content_Types].xml",))).code == 4


def test_logical_name_splits_windows_paths_on_any_os():
    assert registry.logical_name("C:\\reports\\2024.pdf") == "2024.pdf"
    assert registry.logical_name("/tmp/reports/2024.pdf") == "2024.pdf"
    assert registry.logical_name("report.pdf") == "report.pdf"


@pytest.mark.skipif(os.name == "nt", reason="a file name containing backslashes needs a POSIX file system")
def test_windows_style_source_path_gives_base_name(ws, gct, tmp_path):
    odd = tmp_path / "C:\\reports\\2024.pdf"  # one file whose literal name holds backslashes
    odd.write_bytes(PDF)
    gct("company", "add", "Acme")
    r = gct("doc", "add", odd, "--company", "Acme", "--json")
    assert r.data["document"]["logical_name"] == "2024.pdf"
