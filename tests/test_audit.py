"""Unit and integration tests for Story M1-5.5: Auditor Greenwashing Copilot."""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from gct.stages.audit import (
    AUDIT_VERDICTS,
    GREENWASHING_TYPES,
    audit_claim,
    format_qualitative_audit_prompt,
    parse_audit_response,
    scan_workspace_candidates,
)


def test_audit_type_1_unaccredited_certification():
    claim = "Our operations are certified Carbon Neutral under ISO 14001."
    contexts = [
        "In fiscal year 2024, our ISO 14001 certification is pending audit review and not certified."
    ]
    res = audit_claim(claim, contexts)
    assert res["verdict"] == "greenwashing"
    assert res["greenwashing_type"] == "Type 1"
    assert "certification" in res["justification"].lower()
    assert res["missing_evidence_reason"] is None


def test_audit_type_2_mandated_action_as_voluntary():
    claim = "We voluntarily spearheaded BS-VI emissions standards across our truck lines."
    contexts = [
        "Transition to BS-VI engine compliance was a statutory requirement mandated by national regulation from April 2020."
    ]
    res = audit_claim(claim, contexts)
    assert res["verdict"] == "greenwashing"
    assert res["greenwashing_type"] == "Type 2"
    assert "mandated" in res["justification"].lower() or "statutory" in res["justification"].lower()
    assert res["missing_evidence_reason"] is None


def test_audit_type_3_boundary_overgeneralization():
    claim = "We transitioned our entire fleet to zero-emission electric vehicles."
    contexts = [
        "Electric vehicle adoption in 2024 was limited to headquarters shuttle vans, representing 2% of total transport."
    ]
    res = audit_claim(claim, contexts)
    assert res["verdict"] == "greenwashing"
    assert res["greenwashing_type"] == "Type 3"
    assert "partial" in res["justification"].lower() or "scope" in res["justification"].lower()
    assert res["missing_evidence_reason"] is None


def test_audit_type_4_factual_contradiction():
    claim = "We successfully reduced emissions by 15% across our manufacturing facilities."
    contexts = [
        "Due to increased production volume in 2024, total manufacturing emissions increased by 8% from 1.2 to 1.3 MtCO2e."
    ]
    res = audit_claim(claim, contexts)
    assert res["verdict"] == "greenwashing"
    assert res["greenwashing_type"] == "Type 4"
    assert "emissions" in res["justification"].lower()
    assert res["missing_evidence_reason"] is None


def test_audit_verified_claim():
    claim = "Our facility achieved a 25% reduction in municipal water withdrawal in 2024."
    contexts = [
        "Our facility achieved a 25% reduction in municipal water withdrawal in 2024 through rainwater harvesting systems."
    ]
    res = audit_claim(claim, contexts)
    assert res["verdict"] == "verified"
    assert res["greenwashing_type"] is None
    assert "corroborated" in res["justification"].lower()


def test_audit_responsible_abstention_on_empty_context():
    claim = "We plan to become the world's most sustainable logistics company by 2030."
    res = audit_claim(claim, contexts=[])
    assert res["verdict"] == "abstain"
    assert res["greenwashing_type"] is None
    assert "responsible abstention" in res["justification"].lower()
    assert res["missing_evidence_reason"] is not None


def test_audit_abstention_on_tone_or_suspicion():
    # Ambitious marketing prose that sounds suspicious, but context neither confirms nor refutes
    claim = "We are passionately driving an eco-revolution with game-changing green breakthroughs."
    contexts = [
        "Company financials for FY2024 report total operating revenue of 500 million INR."
    ]
    res = audit_claim(claim, contexts)
    # MUST abstain; tone alone must NEVER trigger greenwashing
    assert res["verdict"] == "abstain"
    assert res["greenwashing_type"] is None
    assert res["missing_evidence_reason"] is not None


def test_format_and_parse_audit_response():
    prompt = format_qualitative_audit_prompt(
        "We are 100% solar powered.",
        contexts=["Page 14: Solar panels supply 40% of facility electricity."],
    )
    assert "<CLAIM>" in prompt
    assert "<CONTEXT>" in prompt

    sample_llm_out = """
Label: greenwashing
Type: Type 3
Justification: Context on page 14 states solar panels only provide 40% of electricity, refuting the 100% claim.
"""
    parsed = parse_audit_response(sample_llm_out)
    assert parsed["verdict"] == "greenwashing"
    assert parsed["greenwashing_type"] == "Type 3"
    assert "refuting the 100% claim" in parsed["justification"]


def test_scan_workspace_candidates_integration():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        db_path = root / "workspace.db"
        conn = sqlite3.connect(db_path)

        # Build schema mock
        conn.executescript("""
        CREATE TABLE company (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE document (id INTEGER PRIMARY KEY, logical_name TEXT);
        CREATE TABLE claim (id INTEGER PRIMARY KEY, company_id INTEGER, document_id INTEGER);
        CREATE TABLE claim_version (id INTEGER PRIMARY KEY, claim_id INTEGER, metric_text TEXT);
        CREATE TABLE evidence_ref (id INTEGER PRIMARY KEY, claim_version_id INTEGER, page_number INTEGER, boxes TEXT);
        CREATE TABLE page (id INTEGER PRIMARY KEY, document_id INTEGER, page_number INTEGER, artifact_id INTEGER);
        CREATE TABLE artifact (id INTEGER PRIMARY KEY, path TEXT);
        CREATE TABLE reviewer_flag (id INTEGER PRIMARY KEY, claim_version_id INTEGER);
        """)

        # Insert test data
        conn.execute("INSERT INTO company VALUES (1, 'Acme Motors')")
        conn.execute("INSERT INTO document VALUES (10, 'Sustainability_Report_2024.pdf')")

        # Claim 1: Type 3 candidate (entire fleet vs headquarters only)
        conn.execute("INSERT INTO claim VALUES (101, 1, 10)")
        conn.execute("INSERT INTO claim_version VALUES (1001, 101, 'We transitioned our entire fleet to zero-emission electric vehicles.')")
        conn.execute("INSERT INTO evidence_ref VALUES (501, 1001, 14, '[[100, 200, 300, 400]]')")

        # Claim 2: Clean claim
        conn.execute("INSERT INTO claim VALUES (102, 1, 10)")
        conn.execute("INSERT INTO claim_version VALUES (1002, 102, 'Total water consumption was 50,000 kilolitres.')")
        conn.execute("INSERT INTO evidence_ref VALUES (502, 1002, 15, '[[100, 200, 300, 400]]')")

        # Claim 3: Type 3 candidate that ALREADY has a reviewer flag (should be excluded)
        conn.execute("INSERT INTO claim VALUES (103, 1, 10)")
        conn.execute("INSERT INTO claim_version VALUES (1003, 103, 'We transitioned our entire fleet to zero-emission electric vehicles.')")
        conn.execute("INSERT INTO evidence_ref VALUES (503, 1003, 16, '[[100, 200, 300, 400]]')")
        conn.execute("INSERT INTO reviewer_flag VALUES (1, 1003)")

        # Create artifact reading for page 14
        art_dir = root / "artifacts"
        art_dir.mkdir(parents=True)
        art_file = art_dir / "reading_p14.json"
        art_file.write_text(json.dumps({
            "words": [
                {"text": "Electric"}, {"text": "vehicle"}, {"text": "adoption"},
                {"text": "in"}, {"text": "2024"}, {"text": "was"},
                {"text": "limited"}, {"text": "to"}, {"text": "headquarters"},
                {"text": "shuttle"}, {"text": "vans."}
            ]
        }))

        conn.execute("INSERT INTO artifact VALUES (1, 'artifacts/reading_p14.json')")
        conn.execute("INSERT INTO page VALUES (1, 10, 14, 1)")
        conn.commit()

        candidates = scan_workspace_candidates(conn, root)
        assert len(candidates) == 1
        c = candidates[0]
        assert c["claim_id"] == 101
        assert c["version_id"] == 1001
        assert c["company"] == "Acme Motors"
        assert c["document_name"] == "Sustainability_Report_2024.pdf"
        assert c["page_number"] == 14
        assert c["greenwashing_type"] == "Type 3"
        assert c["boxes"] == [[100, 200, 300, 400]]
        assert "partial" in c["justification"].lower() or "scope" in c["justification"].lower()
