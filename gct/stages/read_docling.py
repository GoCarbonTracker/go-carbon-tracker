"""Docling reading adapter for GCT (Story M1-2.6).

Extracts high-fidelity structured tables, markdown paragraphs, and cell-level bounding boxes
using Docling (DocumentConverter), with seamless fallback to pdfplumber when unanchored or unavailable.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DOCLING_AVAILABLE: Optional[bool] = None
_DOC_CACHE: dict[Path, Any] = {}


def is_docling_available() -> bool:
    """Return True if docling is installed and importable."""
    global _DOCLING_AVAILABLE
    if _DOCLING_AVAILABLE is None:
        try:
            import docling  # noqa: F401
            from docling.document_converter import DocumentConverter  # noqa: F401
            _DOCLING_AVAILABLE = True
        except ImportError:
            _DOCLING_AVAILABLE = False
    return _DOCLING_AVAILABLE


def get_docling_document(pdf_path: Path | str) -> Optional[Any]:
    """Convert a PDF document with Docling, caching the result in memory."""
    if not is_docling_available():
        return None
    path = Path(pdf_path).resolve()
    if path in _DOC_CACHE:
        return _DOC_CACHE[path]
    try:
        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        conv_res = converter.convert(path, raises_on_error=False)
        from docling.datamodel.base_models import ConversionStatus
        if conv_res.status == ConversionStatus.SUCCESS:
            _DOC_CACHE[path] = conv_res.document
            return conv_res.document
        logger.warning("Docling conversion of %s finished with status %s", path, conv_res.status)
        return None
    except Exception as exc:
        logger.warning("Docling conversion failed on %s: %s", path, exc)
        return None


def clear_docling_cache() -> None:
    """Clear in-memory cached Docling documents."""
    _DOC_CACHE.clear()


def _r(x: float | int | None) -> float:
    return round(float(x or 0.0), 2)


def _convert_bbox_to_topleft(bbox: Any, page_height: float) -> list[float]:
    """Convert Docling bounding box to top-left origin [x0, top, x1, bottom]."""
    if bbox is None:
        return [0.0, 0.0, 0.0, 0.0]
    l, t, r, b = getattr(bbox, "l", 0.0), getattr(bbox, "t", 0.0), getattr(bbox, "r", 0.0), getattr(bbox, "b", 0.0)
    coord_origin = getattr(bbox, "coord_origin", None)
    origin_str = str(coord_origin).upper() if coord_origin else ""
    if "BOTTOMLEFT" in origin_str:
        top = page_height - t
        bottom = page_height - b
        if top > bottom:
            top, bottom = bottom, top
        return [_r(l), _r(top), _r(r), _r(bottom)]
    return [_r(l), _r(t), _r(r), _r(b)]


def extract_tables_docling(docling_doc: Any, page_no: int, page_height: float) -> list[dict]:
    """Extract structured tables from Docling for a given page number."""
    if docling_doc is None:
        return []
    tables = []
    for tbl in getattr(docling_doc, "tables", []):
        if not getattr(tbl, "prov", None):
            continue
        if tbl.prov[0].page_no != page_no:
            continue

        tbl_bbox = _convert_bbox_to_topleft(tbl.prov[0].bbox, page_height)
        data = getattr(tbl, "data", None)
        if not data or not getattr(data, "table_cells", None):
            continue

        num_rows = getattr(data, "num_rows", 0)
        num_cols = getattr(data, "num_cols", 0)
        if num_rows == 0 or num_cols == 0:
            continue

        grid_cells = [[None for _ in range(num_cols)] for _ in range(num_rows)]
        grid_rows = [["" for _ in range(num_cols)] for _ in range(num_rows)]

        for cell in data.table_cells:
            r = getattr(cell, "start_row_offset_idx", 0)
            c = getattr(cell, "start_col_offset_idx", 0)
            if 0 <= r < num_rows and 0 <= c < num_cols:
                txt = getattr(cell, "text", "") or ""
                grid_rows[r][c] = txt.strip()
                cell_bbox = getattr(cell, "bbox", None)
                if cell_bbox:
                    grid_cells[r][c] = _convert_bbox_to_topleft(cell_bbox, page_height)
                else:
                    grid_cells[r][c] = tbl_bbox

        tables.append({
            "bbox": tbl_bbox,
            "rows": grid_rows,
            "cells": grid_cells,
        })
    return tables


def extract_paragraphs_docling(docling_doc: Any, page_no: int, page_height: float) -> list[dict]:
    """Extract paragraphs and short items from Docling for a given page number."""
    if docling_doc is None:
        return []
    items = []
    for txt in getattr(docling_doc, "texts", []):
        if not getattr(txt, "prov", None):
            continue
        if txt.prov[0].page_no != page_no:
            continue
        content = getattr(txt, "text", "") or ""
        if not content.strip():
            continue
        bbox = _convert_bbox_to_topleft(txt.prov[0].bbox, page_height)
        items.append({
            "text": content.strip(),
            "bbox": bbox,
            "label": getattr(txt, "label", "text"),
        })
    return items


def read_page_docling(
    docling_doc: Any,
    pdfplumber_page: Any,
    words_fallback: list[dict],
) -> dict:
    """Build a GCT-compatible reading dict using Docling structured extractions."""
    p_num = pdfplumber_page.page_number
    p_w = _r(pdfplumber_page.width)
    p_h = _r(pdfplumber_page.height)

    tables = extract_tables_docling(docling_doc, p_num, p_h)
    paragraphs = extract_paragraphs_docling(docling_doc, p_num, p_h)

    # If Docling found neither tables nor text items, fallback to pdfplumber words
    if not tables and not paragraphs:
        return {
            "page": p_num,
            "width": p_w,
            "height": p_h,
            "text": "\n".join(w["text"] for w in words_fallback),
            "words": words_fallback,
            "tables": [],
            "method": "pdfplumber",
        }

    # Synthesize text from Docling paragraphs and table text
    text_lines = [p["text"] for p in paragraphs]
    for t in tables:
        for row in t["rows"]:
            row_txt = " | ".join(c for c in row if c)
            if row_txt:
                text_lines.append(row_txt)
    page_text = "\n".join(text_lines)

    return {
        "page": p_num,
        "width": p_w,
        "height": p_h,
        "text": page_text,
        "words": words_fallback,  # Keep word-level coordinates for exact line bounding
        "tables": tables,
        "method": "docling",
    }
