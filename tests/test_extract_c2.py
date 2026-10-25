import json
import pytest

from conftest import grid, make_pdf
from gct.stages import extract


def test_r1_currency_and_extended_units_recognition():
    """R-1: Currency units and extended units vocabulary recognized."""
    # Currency units
    for u in ("INR", "₹", "Rs", "Rs.", "crore", "crores", "lakh", "lakhs", "INR crore", "₹ crore", "Rs crore"):
        assert extract._unit(u) is not None, f"Failed to recognise currency unit: {u}"
        assert extract._unit(u.lower()) is not None

    # Extended units
    for u in ("year", "years", "hours/week", "hours per week", "GJ", "TJ", "million", "billion", "nos", "nos."):
        assert extract._unit(u) is not None, f"Failed to recognise extended unit: {u}"

    # Rejection of unlisted / invalid units
    assert extract._unit("arbitrary_unknown_unit") is None
    assert extract._unit("footbars") is None


def test_r1_extract_unit_from_parentheticals():
    """R-1: Currency and extended units parsed from parenthetical headers."""
    assert extract._extract_unit("Revenue (INR crore)") == "INR crore"
    assert extract._extract_unit("Total spend (₹ in crore)") == "₹ crore"
    assert extract._extract_unit("Capital expenditure (Rs. in Lakhs)") == "Rs. Lakhs"
    assert extract._extract_unit("Working hours (hours/week)") == "hours/week"
    assert extract._extract_unit("Tenure (years)") == "years"
    assert extract._extract_unit("Energy (GJ)") == "GJ"
    assert extract._extract_unit("Market based (standalone)") is None


def test_r2_and_r4_column_header_joins_metric_text():
    """R-2, R-4: Table column headers join row labels in metric_text."""
    # Table where column 1 is Scope 1 emissions, row 1 is Passenger Vehicles
    reading = {
        "height": 792, "width": 612, "words": [],
        "tables": [{
            "bbox": [50, 100, 450, 250],
            "rows": [
                ["Segment", "Scope 1 emissions (tCO2e)", "Scope 2 emissions (tCO2e)"],
                ["Passenger Vehicles", "1,234", "567"],
                ["Commercial Vehicles", "2,345", "678"],
            ],
            "cells": [
                [[50, 100, 150, 130], [150, 100, 300, 130], [300, 100, 450, 130]],
                [[50, 130, 150, 160], [150, 130, 300, 160], [300, 130, 450, 160]],
                [[50, 160, 150, 190], [150, 160, 300, 190], [300, 160, 450, 190]],
            ]
        }]
    }
    claims = list(extract.rules(reading))
    claims_by_loc = {c["locator"]: c for c in claims}

    # Passenger Vehicles + Scope 1 emissions
    c1 = claims_by_loc["t0r1c1"]
    assert c1["value_text"] == "1,234"
    assert c1["value"] == 1234.0
    assert c1["unit_text"] == "tCO2e"
    assert "Passenger Vehicles" in c1["metric_text"]
    assert "Scope 1 emissions" in c1["metric_text"]

    # Commercial Vehicles + Scope 2 emissions
    c2 = claims_by_loc["t0r2c2"]
    assert c2["value_text"] == "678"
    assert c2["value"] == 678.0
    assert c2["unit_text"] == "tCO2e"
    assert "Commercial Vehicles" in c2["metric_text"]
    assert "Scope 2 emissions" in c2["metric_text"]


def test_r3_header_only_currency_units_attached_to_claim():
    """R-3: Printed units in column headers are attached to claims."""
    reading = {
        "height": 792, "width": 612, "words": [],
        "tables": [{
            "bbox": [50, 100, 450, 200],
            "rows": [
                ["Category", "FY24 (₹ in crore)", "FY23 (₹ in crore)"],
                ["R&D expenditure", "450", "380"],
            ],
            "cells": [
                [[50, 100, 150, 130], [150, 100, 300, 130], [300, 100, 450, 130]],
                [[50, 130, 150, 160], [150, 130, 300, 160], [300, 130, 450, 160]],
            ]
        }]
    }
    claims = list(extract.rules(reading))
    claims_by_loc = {c["locator"]: c for c in claims}

    c = claims_by_loc["t0r1c1"]
    assert c["value_text"] == "450"
    assert c["value"] == 450.0
    assert c["unit_text"] == "₹ crore"
    assert c["period_label"] == "FY24"
    assert "R&D expenditure" in c["metric_text"]


def test_table_title_band_unit_and_metric_propagation():
    """Table title band above table provides default unit and metric context."""
    words = [
        {"text": "Table", "x0": 50, "top": 50, "x1": 80, "bottom": 65, "dir": "ltr"},
        {"text": "1:", "x0": 82, "top": 50, "x1": 95, "bottom": 65, "dir": "ltr"},
        {"text": "Energy", "x0": 100, "top": 50, "x1": 140, "bottom": 65, "dir": "ltr"},
        {"text": "Consumption", "x0": 145, "top": 50, "x1": 220, "bottom": 65, "dir": "ltr"},
        {"text": "(MWh)", "x0": 225, "top": 50, "x1": 260, "bottom": 65, "dir": "ltr"},
    ]
    reading = {
        "height": 792, "width": 612, "words": words,
        "tables": [{
            "bbox": [50, 80, 450, 180],
            "rows": [
                ["Source", "FY24"],
                ["Grid electricity", "10,500"],
            ],
            "cells": [
                [[50, 80, 200, 110], [200, 80, 450, 110]],
                [[50, 110, 200, 140], [200, 110, 450, 140]],
            ]
        }]
    }
    claims = list(extract.rules(reading))
    assert len(claims) == 1
    c = claims[0]
    assert c["value_text"] == "10,500"
    assert c["value"] == 10500.0
    assert c["unit_text"] == "MWh"
    assert "Grid electricity" in c["metric_text"]
    assert "Energy Consumption" in c["metric_text"]


def test_text_claims_with_prefix_currency():
    """Prefix currency in body text (e.g., ₹ 4,560 or INR 500) extracted properly."""
    words = [
        {"text": "Total", "x0": 50, "top": 100, "x1": 80, "bottom": 115, "dir": "ltr"},
        {"text": "spending", "x0": 85, "top": 100, "x1": 140, "bottom": 115, "dir": "ltr"},
        {"text": "was", "x0": 145, "top": 100, "x1": 165, "bottom": 115, "dir": "ltr"},
        {"text": "INR", "x0": 170, "top": 100, "x1": 190, "bottom": 115, "dir": "ltr"},
        {"text": "500", "x0": 195, "top": 100, "x1": 215, "bottom": 115, "dir": "ltr"},
        {"text": "in", "x0": 220, "top": 100, "x1": 230, "bottom": 115, "dir": "ltr"},
        {"text": "FY24.", "x0": 235, "top": 100, "x1": 265, "bottom": 115, "dir": "ltr"},
    ]
    reading = {
        "height": 792, "width": 612, "words": words, "tables": []
    }
    claims = list(extract.rules(reading))
    assert len(claims) == 1
    c = claims[0]
    assert c["value_text"] == "500"
    assert c["value"] == 500.0
    assert c["unit_text"] == "INR"
    assert c["period_label"] == "FY24"
    assert "Total spending" in c["metric_text"]
    assert c["boxes"] == [[170, 100, 215, 115]]
