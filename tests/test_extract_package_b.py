"""Tests for Story M1-3.8 Package B: Units and Header Context (extract rules).

Acceptance criteria:
- Fixtures preserve every printed value and box.
- Currency value is kept with its unit (INR, ₹, crore, lakh).
- Table column headers join the claim's metric text.
- Header-only unit is attached.
- Substantive row label is picked when column 0 is an item index/bullet (i., 1., a.).
- Preceding/succeeding text label is attached to callout figure numbers in text claims.
- RULES_VERSION is bumped.
"""
from gct.stages import extract


def test_item_number_skipping_picks_substantive_label():
    reading = {
        "height": 792,
        "words": [],
        "tables": [{
            "bbox": [50, 100, 400, 200],
            "rows": [
                ["Sr. No.", "Particulars", "Total (A)"],
                ["i.", "Permanent employees (D)", "8,616"],
                ["ii.", "Total Workers (F +G)", "28,257"],
            ],
            "cells": [
                [[50, 100, 80, 120], [80, 100, 250, 120], [250, 100, 400, 120]],
                [[50, 120, 80, 150], [80, 120, 250, 150], [250, 120, 400, 150]],
                [[50, 150, 80, 180], [80, 150, 250, 180], [250, 150, 400, 180]],
            ]
        }]
    }
    claims = list(extract._table_claims(reading))
    assert len(claims) == 2
    c0 = claims[0]
    assert c0["value_text"] == "8,616"
    assert "Permanent employees" in c0["metric_text"]
    assert "Total" in c0["metric_text"]

    c1 = claims[1]
    assert c1["value_text"] == "28,257"
    assert "Total Workers" in c1["metric_text"]


def test_stat_callout_attaches_heading_from_preceding_line():
    reading = {
        "height": 792,
        "tables": [],
        "words": [
            # Line 0: Heading "Market Share"
            {"text": "Market", "x0": 100, "x1": 150, "top": 100, "bottom": 115, "dir": "ltr"},
            {"text": "Share", "x0": 155, "x1": 200, "top": 100, "bottom": 115, "dir": "ltr"},
            # Line 1: Figure "18.7%"
            {"text": "18.7%", "x0": 100, "x1": 160, "top": 125, "bottom": 150, "dir": "ltr"},
        ]
    }
    claims = list(extract._text_claims(reading))
    assert len(claims) == 1
    c = claims[0]
    assert c["value_text"] == "18.7"
    assert c["unit_text"] == "%"
    assert c["metric_text"] == "Market Share"


def test_stat_callout_attaches_label_from_succeeding_line():
    reading = {
        "height": 792,
        "tables": [],
        "words": [
            # Line 0: Figure "43.3%"
            {"text": "43.3%", "x0": 100, "x1": 160, "top": 100, "bottom": 125, "dir": "ltr"},
            # Line 1: Label "Renewable energy"
            {"text": "Renewable", "x0": 100, "x1": 170, "top": 135, "bottom": 150, "dir": "ltr"},
            {"text": "energy", "x0": 175, "x1": 220, "top": 135, "bottom": 150, "dir": "ltr"},
        ]
    }
    claims = list(extract._text_claims(reading))
    assert len(claims) == 1
    c = claims[0]
    assert c["value_text"] == "43.3"
    assert c["unit_text"] == "%"
    assert c["metric_text"] == "Renewable energy"


def test_currency_prefix_and_units():
    reading = {
        "height": 792,
        "tables": [],
        "words": [
            {"text": "Revenue", "x0": 50, "x1": 100, "top": 100, "bottom": 115, "dir": "ltr"},
            {"text": "₹", "x0": 105, "x1": 115, "top": 100, "bottom": 115, "dir": "ltr"},
            {"text": "4,300", "x0": 120, "x1": 160, "top": 100, "bottom": 115, "dir": "ltr"},
            {"text": "crore", "x0": 165, "x1": 200, "top": 100, "bottom": 115, "dir": "ltr"},
        ]
    }
    claims = list(extract._text_claims(reading))
    assert len(claims) == 1
    assert claims[0]["value_text"] == "4,300"
    assert claims[0]["unit_text"] in ("crore", "₹ crore", "₹")
