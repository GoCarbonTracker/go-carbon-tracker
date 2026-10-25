import json
import sqlite3
from unittest.mock import MagicMock
import pytest

from conftest import make_pdf
from gct.models import semantic_filter
from gct.models.semantic_filter import _get_device, classify_sentence
from gct.stages import extract


def test_classify_sentence_unavailable(monkeypatch):
    """When dependencies or weights are unavailable, classify_sentence returns (False, 0.0) with a warning."""
    semantic_filter._reset_model()

    def mock_load_model():
        import warnings
        warnings.warn("Semantic filter model 'climatebert/environmental-claims' unavailable: test")
        return None, None, None

    monkeypatch.setattr(semantic_filter, "_load_model", mock_load_model)
    with pytest.warns(UserWarning, match="unavailable"):
        verdict, prob = classify_sentence("We aim to reduce Scope 1 emissions.")
    assert verdict is False
    assert prob == 0.0

    # Blank text returns immediately
    assert classify_sentence("") == (False, 0.0)
    assert classify_sentence("   ") == (False, 0.0)


def test_device_selection_order():
    """Device selection follows mps -> cuda -> cpu order."""
    # 1. MPS available
    torch_mps = MagicMock()
    torch_mps.backends.mps.is_available.return_value = True
    torch_mps.device.side_effect = lambda d: f"device:{d}"
    assert _get_device(torch_mps) == "device:mps"

    # 2. CUDA available (MPS unavailable)
    torch_cuda = MagicMock()
    torch_cuda.backends.mps.is_available.return_value = False
    torch_cuda.cuda.is_available.return_value = True
    torch_cuda.device.side_effect = lambda d: f"device:{d}"
    assert _get_device(torch_cuda) == "device:cuda"

    # 3. CPU fallback
    torch_cpu = MagicMock()
    torch_cpu.backends.mps.is_available.return_value = False
    torch_cpu.cuda.is_available.return_value = False
    torch_cpu.device.side_effect = lambda d: f"device:{d}"
    assert _get_device(torch_cpu) == "device:cpu"


def test_classify_sentence_environmental_and_non_environmental():
    """Test classify_sentence on environmental and non-environmental text."""
    semantic_filter._reset_model()

    # Environmental text
    env_text = "We aim to achieve net zero carbon emissions across our operations by 2030."
    verdict, prob = classify_sentence(env_text, threshold=0.05)
    assert verdict is True
    assert prob >= 0.05

    # Non-environmental text
    fin_text = "Consolidated financial results for the quarter showed a revenue growth of 12%."
    verdict, prob = classify_sentence(fin_text, threshold=0.05)
    assert verdict is False
    assert prob < 0.05

    # Threshold gating
    mid_text = "The company reduced Scope 1 and Scope 2 greenhouse gas emissions by 25%."
    verdict_low, prob_mid = classify_sentence(mid_text, threshold=0.05)
    assert verdict_low is True
    assert 0.05 <= prob_mid < 0.20

    verdict_high, _ = classify_sentence(mid_text, threshold=0.50)
    assert verdict_high is False


def test_semantic_text_claims_extraction(monkeypatch):
    """Test _semantic_text_claims extracts qualitative claims with correct metadata."""
    def mock_classify(text, threshold=0.05):
        if "solar" in text.lower() or "renewable" in text.lower():
            return True, 0.75
        return False, 0.001

    monkeypatch.setattr(extract, "classify_sentence", mock_classify)

    reading = {
        "width": 612,
        "height": 792,
        "tables": [],
        "words": [
            # Sentence 1: Qualitative environmental claim
            {"text": "The", "x0": 50, "top": 100, "x1": 70, "bottom": 112, "dir": "ltr"},
            {"text": "company", "x0": 75, "top": 100, "x1": 120, "bottom": 112, "dir": "ltr"},
            {"text": "transitioned", "x0": 125, "top": 100, "x1": 185, "bottom": 112, "dir": "ltr"},
            {"text": "to", "x0": 190, "top": 100, "x1": 200, "bottom": 112, "dir": "ltr"},
            {"text": "solar", "x0": 205, "top": 100, "x1": 235, "bottom": 112, "dir": "ltr"},
            {"text": "power", "x0": 240, "top": 100, "x1": 270, "bottom": 112, "dir": "ltr"},
            {"text": "in", "x0": 275, "top": 100, "x1": 285, "bottom": 112, "dir": "ltr"},
            {"text": "FY24.", "x0": 290, "top": 100, "x1": 320, "bottom": 112, "dir": "ltr"},
            # Sentence 2: Non-environmental statement
            {"text": "Board", "x0": 50, "top": 120, "x1": 80, "bottom": 132, "dir": "ltr"},
            {"text": "meetings", "x0": 85, "top": 120, "x1": 130, "bottom": 132, "dir": "ltr"},
            {"text": "were", "x0": 135, "top": 120, "x1": 160, "bottom": 132, "dir": "ltr"},
            {"text": "held", "x0": 165, "top": 120, "x1": 185, "bottom": 132, "dir": "ltr"},
            {"text": "quarterly.", "x0": 190, "top": 120, "x1": 240, "bottom": 132, "dir": "ltr"},
        ]
    }

    claims = list(extract._semantic_text_claims(reading))
    assert len(claims) == 1
    c = claims[0]
    assert c["locator"] == "p0s0"
    assert c["metric_text"] == "The company transitioned to solar power in FY24."
    assert c["value_text"] is None
    assert c["value"] is None
    assert c["unit_text"] is None
    assert c["period_label"] == "FY24"
    assert c["method"] == "rung2-climatebert"
    assert c["claim_probability"] == 0.75
    assert c["boxes"] == [[50, 100, 320, 112]]


def test_semantic_text_claims_avoids_r1_duplicates(monkeypatch):
    """When a sentence contains an existing Rung 1 numeric claim, Rung 1 retains priority."""
    def mock_classify(text, threshold=0.05):
        return True, 0.95

    monkeypatch.setattr(extract, "classify_sentence", mock_classify)

    reading = {
        "width": 612,
        "height": 792,
        "tables": [],
        "words": [
            {"text": "We", "x0": 50, "top": 100, "x1": 70, "bottom": 112, "dir": "ltr"},
            {"text": "consumed", "x0": 75, "top": 100, "x1": 130, "bottom": 112, "dir": "ltr"},
            {"text": "500", "x0": 135, "top": 100, "x1": 155, "bottom": 112, "dir": "ltr"},
            {"text": "MWh", "x0": 160, "top": 100, "x1": 185, "bottom": 112, "dir": "ltr"},
            {"text": "of", "x0": 190, "top": 100, "x1": 200, "bottom": 112, "dir": "ltr"},
            {"text": "renewable", "x0": 205, "top": 100, "x1": 260, "bottom": 112, "dir": "ltr"},
            {"text": "energy.", "x0": 265, "top": 100, "x1": 305, "bottom": 112, "dir": "ltr"},
        ]
    }

    # Rung 1 extracted "500 MWh" with box [135, 100, 185, 112]
    r1_claim = [{"locator": "l0w2", "boxes": [[135, 100, 185, 112]]}]
    claims = list(extract._semantic_text_claims(reading, existing_claims=r1_claim))
    assert len(claims) == 0  # Skipped because Rung 1 has priority


def test_gct_extract_completes_without_errors(gct, make_file, db, monkeypatch):
    """gct extract completes without errors and stores qualitative semantic claims."""
    def mock_classify(text, threshold=0.05):
        if "solar" in text.lower():
            return True, 0.85
        return False, 0.001

    monkeypatch.setattr(extract, "classify_sentence", mock_classify)

    page = {
        "text": [
            (72, 200, "Energy consumed 4,560 MWh in 2023"),
            (72, 300, "The factory installed solar panels in FY24."),
        ],
        "lines": [],
    }

    gct("company", "add", "SolarCorp")
    r = gct("doc", "add", make_file("report.pdf", make_pdf([page])), "--company", "SolarCorp", "--json")
    doc_id = r.data["items"][0]["document"]["id"]

    # Run read and extract
    r_read = gct("read")
    assert r_read.code == 0
    r_extract = gct("extract", "--json")
    assert r_extract.code == 0

    doc_report = r_extract.data["documents"][0]
    assert doc_report["extracted"] == 1
    assert doc_report["failed"] == 0
    assert doc_report["figures"] == 2  # 1 numeric figure + 1 semantic claim

    # Verify rows in database
    rows = db.execute(
        "SELECT c.locator, v.method, v.metric_text, v.value_text, v.value, v.period_label"
        " FROM claim c JOIN claim_version v ON v.claim_id = c.id WHERE c.document_id = ?"
        " ORDER BY c.locator",
        (doc_id,),
    ).fetchall()

    locators = {r["locator"]: dict(r) for r in rows}
    assert "l0w2" in locators
    assert locators["l0w2"]["method"] == "rung1-rules"
    assert locators["l0w2"]["value_text"] == "4,560"

    assert "p1s0" in locators
    semantic = locators["p1s0"]
    assert semantic["method"] == "rung2-climatebert"
    assert semantic["metric_text"] == "The factory installed solar panels in FY24."
    assert semantic["value_text"] == ""
    assert semantic["value"] is None
    assert semantic["period_label"] == "FY24"
