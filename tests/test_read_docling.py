import pytest
from unittest.mock import MagicMock

from gct.stages.read_docling import (
    _convert_bbox_to_topleft,
    extract_paragraphs_docling,
    extract_tables_docling,
    is_docling_available,
    read_page_docling,
)


def test_is_docling_available():
    # In this environment, docling is installed in the project venv
    assert is_docling_available() in (True, False)


def test_convert_bbox_to_topleft():
    class MockBbox:
        l = 100.0
        t = 700.0
        r = 300.0
        b = 650.0
        coord_origin = "BOTTOMLEFT"

    # page height 842 pt
    topleft = _convert_bbox_to_topleft(MockBbox(), 842.0)
    assert topleft[0] == 100.0
    assert topleft[1] == 142.0  # 842 - 700
    assert topleft[2] == 300.0
    assert topleft[3] == 192.0  # 842 - 650


def test_extract_tables_docling():
    mock_doc = MagicMock()
    mock_table = MagicMock()
    mock_table.prov = [MagicMock(page_no=1, bbox=MagicMock(l=50.0, t=600.0, r=400.0, b=200.0, coord_origin="BOTTOMLEFT"))]
    mock_data = MagicMock()
    mock_data.num_rows = 2
    mock_data.num_cols = 2
    
    cell0 = MagicMock(start_row_offset_idx=0, start_col_offset_idx=0, text="Metric", bbox=None)
    cell1 = MagicMock(start_row_offset_idx=0, start_col_offset_idx=1, text="FY24", bbox=None)
    cell2 = MagicMock(start_row_offset_idx=1, start_col_offset_idx=0, text="Scope 1", bbox=None)
    cell3 = MagicMock(start_row_offset_idx=1, start_col_offset_idx=1, text="12,500 tCO2e", bbox=None)
    mock_data.table_cells = [cell0, cell1, cell2, cell3]
    mock_table.data = mock_data
    mock_doc.tables = [mock_table]

    tables = extract_tables_docling(mock_doc, page_no=1, page_height=800.0)
    assert len(tables) == 1
    t = tables[0]
    assert t["rows"][0] == ["Metric", "FY24"]
    assert t["rows"][1] == ["Scope 1", "12,500 tCO2e"]
    assert len(t["cells"]) == 2


def test_extract_paragraphs_docling():
    mock_doc = MagicMock()
    mock_text = MagicMock()
    mock_text.prov = [MagicMock(page_no=2, bbox=MagicMock(l=50.0, t=750.0, r=500.0, b=700.0, coord_origin="BOTTOMLEFT"))]
    mock_text.text = "The company achieved 100% renewable electricity across all plants."
    mock_text.label = "text"
    mock_doc.texts = [mock_text]

    items = extract_paragraphs_docling(mock_doc, page_no=2, page_height=800.0)
    assert len(items) == 1
    assert "renewable electricity" in items[0]["text"]
    assert items[0]["label"] == "text"


def test_read_page_docling_fallback():
    mock_page = MagicMock()
    mock_page.page_number = 3
    mock_page.width = 600.0
    mock_page.height = 800.0
    words = [{"text": "Hello", "x0": 10, "top": 10, "x1": 50, "bottom": 20}]

    # Empty docling doc -> falls back to pdfplumber
    mock_doc = MagicMock()
    mock_doc.tables = []
    mock_doc.texts = []

    res = read_page_docling(mock_doc, mock_page, words)
    assert res["page"] == 3
    assert res["method"] == "pdfplumber"
    assert res["text"] == "Hello"
