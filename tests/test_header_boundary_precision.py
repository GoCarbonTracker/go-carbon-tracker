"""Tests for multi-line figure heading stacking and boundary precision."""

import sqlite3
from gct.stages import extract, infer


def test_multiline_figure_heading_stacking():
    """Figure stat cards with category/segment on line n-2 stack into metric text."""
    reading = {
        "height": 792,
        "width": 612,
        "tables": [],
        "words": [
            # Line n-2: Category / segment header
            {"text": "SUV", "top": 156.0, "bottom": 165.0, "x0": 741.0, "x1": 760.0},
            # Line n-1: Metric name
            {"text": "Revenue", "top": 170.0, "bottom": 179.0, "x0": 741.0, "x1": 775.0},
            {"text": "market", "top": 170.0, "bottom": 179.0, "x0": 778.0, "x1": 810.0},
            {"text": "share", "top": 170.0, "bottom": 179.0, "x0": 813.0, "x1": 840.0},
            # Line n: Figure value
            {"text": "22.5%", "top": 184.0, "bottom": 198.0, "x0": 741.0, "x1": 810.0},
        ],
    }
    claims = list(extract._text_claims(reading))
    assert len(claims) == 1
    assert claims[0]["value_text"] == "22.5"
    assert claims[0]["unit_text"] == "%"
    assert claims[0]["metric_text"] == "SUV Revenue market share"


def test_segment_name_isolation_in_bases():
    """Segment bases isolate clean segment names from statements and headings."""
    text = (
        "(a) Automotive: This segment comprises of sale of automobiles.\n"
        "(b) Farm Equipment: This segment comprises of sale of tractors.\n"
        "operating segments to which it relates: 'Farm Equipment' segment - Rs 100 cr\n"
        "Growth in compact SUV segment was 15%.\n"
    )
    bases, heading = infer.bases_of({"text": text})
    segs = {b["boundary_detail"] for b in bases if b["kind"] == "reporting_boundary" and b["boundary"] == "segment"}
    assert "Automotive" in segs
    assert "Farm Equipment" in segs
    assert "SUV" in segs


def test_listed_entity_standalone_inference():
    """Claims mentioning the listed entity or TML infer standalone boundary."""
    normal_bases = [
        {"id": 1, "kind": "reporting_boundary", "boundary": "standalone", "boundary_detail": "Tata Motors Limited"},
        {"id": 2, "kind": "reporting_boundary", "boundary": "subsidiary_set", "boundary_detail": "TML, TMPVL and TPEML"},
    ]
    claim_tml = {
        "page_number": 83,
        "metric_text": "CSR Projects: TML Education No. of persons benefitted",
        "boundary_label": None,
    }
    boundary, detail, basis, origin = infer.boundary_of(claim_tml, scoped=[], normal_bases=normal_bases)
    assert boundary == "standalone"
    assert origin == "machine-inferred"

    claim_cin = {
        "page_number": 1,
        "metric_text": "Corporate Identity Number (CIN) of Tata Motors Limited",
        "boundary_label": None,
    }
    boundary, detail, basis, origin = infer.boundary_of(claim_cin, scoped=[], normal_bases=normal_bases)
    assert boundary == "standalone"
    assert origin == "machine-inferred"
