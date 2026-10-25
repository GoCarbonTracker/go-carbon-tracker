import json
import pytest

from gct.stages import extract


def test_rules_version():
    """Package C bumped RULES_VERSION to 8, Package B bumped to 9."""
    assert extract.RULES_VERSION >= 8


def test_table_word_and_string_claims():
    """Package C: Table cells with qualitative answers extract as string claims."""
    reading = {
        "height": 792, "width": 612, "words": [
            {"text": "Type", "x0": 50, "top": 100, "x1": 150, "bottom": 130, "dir": "ltr"},
            {"text": "Assurance", "x0": 150, "top": 100, "x1": 300, "bottom": 130, "dir": "ltr"},
            {"text": "Scope 3 emissions", "x0": 50, "top": 130, "x1": 150, "bottom": 160, "dir": "ltr"},
            {"text": "Limited", "x0": 150, "top": 130, "x1": 300, "bottom": 160, "dir": "ltr"},
            {"text": "ISO Standard", "x0": 50, "top": 160, "x1": 150, "bottom": 190, "dir": "ltr"},
            {"text": "ISO 45001:2018", "x0": 150, "top": 160, "x1": 300, "bottom": 190, "dir": "ltr"},
        ],
        "tables": [{
            "bbox": [50, 100, 300, 190],
            "rows": [
                ["Type", "Assurance"],
                ["Scope 3 emissions", "Limited"],
                ["ISO Standard", "ISO 45001:2018"],
            ],
            "cells": [
                [[50, 100, 150, 130], [150, 100, 300, 130]],
                [[50, 130, 150, 160], [150, 130, 300, 160]],
                [[50, 160, 150, 190], [150, 160, 300, 190]],
            ]
        }]
    }

    claims = list(extract._table_claims(reading))
    assert len(claims) >= 2

    # Check "Limited" claim
    c_lim = next(c for c in claims if c["value_text"] == "Limited")
    assert "Scope 3 emissions" in c_lim["metric_text"]
    assert c_lim["value"] is None
    assert c_lim["boxes"] is not None

    # Check "ISO 45001:2018" claim (digit-bearing string stored whole)
    c_iso = next(c for c in claims if c["value_text"] == "ISO 45001:2018")
    assert "ISO Standard" in c_iso["metric_text"]
    assert c_iso["value"] is None


def test_text_key_value_string_claims():
    """Package C: Key-value text lines extract as word/string claims."""
    words = [
        # Line 1: Corporate Identity Number (CIN): L28920MH1945PLC004520
        {"text": "Corporate", "x0": 50, "top": 100, "x1": 100, "bottom": 115, "dir": "ltr"},
        {"text": "Identity", "x0": 105, "top": 100, "x1": 150, "bottom": 115, "dir": "ltr"},
        {"text": "Number", "x0": 155, "top": 100, "x1": 195, "bottom": 115, "dir": "ltr"},
        {"text": "(CIN):", "x0": 200, "top": 100, "x1": 235, "bottom": 115, "dir": "ltr"},
        {"text": "L28920MH1945PLC004520", "x0": 240, "top": 100, "x1": 400, "bottom": 115, "dir": "ltr"},
        # Line 2: Name of Assurance Provider: KPMG
        {"text": "Name", "x0": 50, "top": 130, "x1": 85, "bottom": 145, "dir": "ltr"},
        {"text": "of", "x0": 90, "top": 130, "x1": 105, "bottom": 145, "dir": "ltr"},
        {"text": "Assurance", "x0": 110, "top": 130, "x1": 170, "bottom": 145, "dir": "ltr"},
        {"text": "Provider:", "x0": 175, "top": 130, "x1": 230, "bottom": 145, "dir": "ltr"},
        {"text": "KPMG", "x0": 235, "top": 130, "x1": 275, "bottom": 145, "dir": "ltr"},
    ]

    reading = {"height": 792, "width": 612, "tables": [], "words": words}
    claims = list(extract._text_claims(reading))
    assert len(claims) >= 2

    c_cin = next(c for c in claims if "L28920MH1945PLC004520" in (c["value_text"] or ""))
    assert c_cin["value_text"] == "L28920MH1945PLC004520"
    assert "Corporate Identity Number" in c_cin["metric_text"]

    c_kpmg = next(c for c in claims if c["value_text"] == "KPMG")
    assert "Assurance Provider" in c_kpmg["metric_text"]
