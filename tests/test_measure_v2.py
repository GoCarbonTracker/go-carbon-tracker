import json
from pathlib import Path
import pytest

from gct.measure import g2


def make_gold_row(
    id_="r-01",
    doc="doc.pdf",
    page=1,
    answer="4,560",
    unit="MWh",
    metric="energy consumed",
    period=None,
    boundary="standalone",
    bbox=None,
    kind="text",
):
    if period is None:
        period = {"kind": "fiscal_year", "start": "2023-04-01", "end": "2024-03-31"}
    return {
        "id": id_,
        "doc": doc,
        "page": page,
        "expected_answer": answer,
        "unit": unit,
        "metric": metric,
        "period": period,
        "boundary": boundary,
        "bbox": bbox or [10, 10, 50, 50],
        "kind": kind,
        "aliases": [],
    }


def make_claim(
    id_=1,
    company="Acme Limited",
    doc_id=1,
    page=1,
    metric="energy consumed",
    value="4,560",
    unit="MWh",
    start="2023-04-01",
    end="2024-03-31",
    period_state="machine-inferred",
    boundary="standalone",
    boundary_state="machine-inferred",
    boundary_detail=None,
    box=None,
):
    c = {
        "id": id_,
        "company": company,
        "document_id": doc_id,
        "page_number": page,
        "claim_version_id": id_,
        "metric_text": metric,
        "value_text": value,
        "unit_text": unit,
        "period_start": start,
        "period_end": end,
        "period_state": period_state,
        "reporting_boundary": boundary,
        "boundary_state": boundary_state,
        "boundary_detail": boundary_detail,
    }
    refs = [{"page_number": page, "boxes": json.dumps([box or [10, 10, 50, 50]])}]
    return c, refs


# ==============================================================================
# AC 2: Zero False Found by Test
# ==============================================================================


def test_ac2_baseline_is_found():
    row = make_gold_row()
    c, refs = make_claim()
    j = g2._judge(c, row, "Acme Limited", refs)
    assert j["verdict"] == "Found"
    assert j["origin"] == "machine-inferred"
    assert j["failing"] == []


def test_ac2_each_of_six_found_conditions_mutated_is_not_found():
    """Mutating any one of the six Found conditions produces not Found."""
    base_row = make_gold_row()
    base_claim, refs = make_claim()

    # 1. Metric mutated -> Partial
    c1 = {**base_claim, "metric_text": "water withdrawn"}
    j1 = g2._judge(c1, base_row, "Acme Limited", refs)
    assert j1["verdict"] == "Partial"
    assert "metric" in j1["failing"]

    # 2. Entity mutated -> Partial
    c2 = {**base_claim, "company": "Beta Corp"}
    j2 = g2._judge(c2, base_row, "Acme Limited", refs)
    assert j2["verdict"] == "Partial"
    assert "entity" in j2["failing"]

    # 3. Value mutated -> Missed
    c3 = {**base_claim, "value_text": "9,999"}
    j3 = g2._judge(c3, base_row, "Acme Limited", refs)
    assert j3["verdict"] == "Missed"

    # 4. Unit mutated -> Missed
    c4 = {**base_claim, "unit_text": "kL"}
    j4 = g2._judge(c4, base_row, "Acme Limited", refs)
    assert j4["verdict"] == "Missed"

    # 5. Period mutated:
    # 5a. Period start wrong -> Partial
    c5a = {**base_claim, "period_start": "2022-04-01"}
    j5a = g2._judge(c5a, base_row, "Acme Limited", refs)
    assert j5a["verdict"] == "Partial"
    assert "period" in j5a["failing"]

    # 5b. Period end wrong -> Partial
    c5b = {**base_claim, "period_end": "2023-12-31"}
    j5b = g2._judge(c5b, base_row, "Acme Limited", refs)
    assert j5b["verdict"] == "Partial"
    assert "period" in j5b["failing"]

    # 5c. Period state unresolved -> Partial
    c5c = {**base_claim, "period_state": "unresolved"}
    j5c = g2._judge(c5c, base_row, "Acme Limited", refs)
    assert j5c["verdict"] == "Partial"
    assert "period" in j5c["failing"]

    # 5d. Period start is None -> Partial
    c5d = {**base_claim, "period_start": None}
    j5d = g2._judge(c5d, base_row, "Acme Limited", refs)
    assert j5d["verdict"] == "Partial"
    assert "period" in j5d["failing"]

    # 6. Boundary mutated:
    # 6a. Boundary value wrong -> Partial
    c6a = {**base_claim, "reporting_boundary": "consolidated"}
    j6a = g2._judge(c6a, base_row, "Acme Limited", refs)
    assert j6a["verdict"] == "Partial"
    assert "boundary" in j6a["failing"]

    # 6b. Boundary state unresolved -> Partial
    c6b = {**base_claim, "boundary_state": "unresolved"}
    j6b = g2._judge(c6b, base_row, "Acme Limited", refs)
    assert j6b["verdict"] == "Partial"
    assert "boundary" in j6b["failing"]


def test_ac2_s1_segment_boundary_rules():
    """S-1: segment boundary matching and printed segment name guard."""
    row = make_gold_row(boundary="segment")

    # Segment match with printed segment name -> Found
    c_ok, refs = make_claim(boundary="segment", boundary_detail="Commercial Vehicles")
    j_ok = g2._judge(c_ok, row, "Acme Limited", refs)
    assert j_ok["verdict"] == "Found"

    # Segment vs standalone: claim is standalone -> Partial
    c_sa, refs = make_claim(boundary="standalone", boundary_detail="Commercial Vehicles")
    j_sa = g2._judge(c_sa, row, "Acme Limited", refs)
    assert j_sa["verdict"] == "Partial"
    assert "boundary" in j_sa["failing"]

    # Segment claim with no printed name (None) -> Partial
    c_none, refs = make_claim(boundary="segment", boundary_detail=None)
    j_none = g2._judge(c_none, row, "Acme Limited", refs)
    assert j_none["verdict"] == "Partial"
    assert "boundary" in j_none["failing"]

    # Segment claim with empty printed name ("") -> Partial
    c_empty, refs = make_claim(boundary="segment", boundary_detail="")
    j_empty = g2._judge(c_empty, row, "Acme Limited", refs)
    assert j_empty["verdict"] == "Partial"
    assert "boundary" in j_empty["failing"]


def test_ac2_s2_percent_of_group_rules():
    """S-2: % of <group> phrase-in-metric matching and guards."""
    row = make_gold_row(unit="% of key suppliers", metric="supplier emissions")

    # Correct group phrase in claim metric_text -> Found
    c_match, refs = make_claim(unit="%", metric="supplier emissions % of key suppliers")
    j_match = g2._judge(c_match, row, "Acme Limited", refs)
    assert j_match["verdict"] == "Found"

    # Words in different order ("suppliers key" instead of "key suppliers") -> Missed (unit mismatch)
    c_order, refs = make_claim(unit="%", metric="supplier emissions % of suppliers key")
    j_order = g2._judge(c_order, row, "Acme Limited", refs)
    assert j_order["verdict"] == "Missed"

    # Different denominator (% of total employees) -> Missed
    c_diff, refs = make_claim(unit="%", metric="supplier emissions % of total employees")
    j_diff = g2._judge(c_diff, row, "Acme Limited", refs)
    assert j_diff["verdict"] == "Missed"

    # Claim unit is not % (e.g., MWh) -> Missed
    c_not_pct, refs = make_claim(unit="MWh", metric="supplier emissions % of key suppliers")
    j_not_pct = g2._judge(c_not_pct, row, "Acme Limited", refs)
    assert j_not_pct["verdict"] == "Missed"


def test_ac2_s4_string_answer_rules():
    """S-4: whole normalised string matching and digit-bearing guards."""
    row = make_gold_row(answer="ISO 45001:2018", unit=None, metric="occupational health cert")

    # Exact string match -> Found
    c_exact, refs = make_claim(value="ISO 45001:2018", unit=None, metric="occupational health cert")
    j_exact = g2._judge(c_exact, row, "Acme Limited", refs)
    assert j_exact["verdict"] == "Found"

    # Near match string -> Missed
    c_near, refs = make_claim(value="ISO 45001:2015", unit=None, metric="occupational health cert")
    j_near = g2._judge(c_near, row, "Acme Limited", refs)
    assert j_near["verdict"] == "Missed"

    # Numeric claim (number-only token) against digit-bearing string -> Missed
    c_num, refs = make_claim(value="45001", unit="MWh", metric="occupational health cert")
    j_num = g2._judge(c_num, row, "Acme Limited", refs)
    assert j_num["verdict"] == "Missed"


def test_ac2_origin_separation_in_found_rows():
    """Origin split: machine-inferred vs review-assisted tally."""
    row = make_gold_row()

    # Both machine-inferred -> origin is machine-inferred
    c_auto, refs = make_claim(period_state="machine-inferred", boundary_state="machine-inferred")
    j_auto = g2._judge(c_auto, row, "Acme Limited", refs)
    assert j_auto["verdict"] == "Found"
    assert j_auto["origin"] == "machine-inferred"

    # Period is accepted -> origin is review-assisted
    c_p_acc, refs = make_claim(period_state="accepted", boundary_state="machine-inferred")
    j_p_acc = g2._judge(c_p_acc, row, "Acme Limited", refs)
    assert j_p_acc["verdict"] == "Found"
    assert j_p_acc["origin"] == "review-assisted"

    # Period is resolved -> origin is review-assisted
    c_p_res, refs = make_claim(period_state="resolved", boundary_state="machine-inferred")
    j_p_res = g2._judge(c_p_res, row, "Acme Limited", refs)
    assert j_p_res["verdict"] == "Found"
    assert j_p_res["origin"] == "review-assisted"

    # Machine-inferred period and reviewed boundary -> origin is review-assisted
    c_mixed, refs = make_claim(period_state="machine-inferred", boundary_state="accepted")
    j_mixed = g2._judge(c_mixed, row, "Acme Limited", refs)
    assert j_mixed["verdict"] == "Found"
    assert j_mixed["origin"] == "review-assisted"


# ==============================================================================
# AC 6: S-1 to S-6 Unit Tests
# ==============================================================================


def test_s1_segment_boundary_unit():
    row = make_gold_row(boundary="segment")
    c_ok, refs = make_claim(boundary="segment", boundary_detail="Commercial Vehicles")
    j_ok = g2._judge(c_ok, row, "Acme Limited", refs)
    assert j_ok["verdict"] == "Found"

    c_no_detail, refs = make_claim(boundary="segment", boundary_detail="")
    j_no_detail = g2._judge(c_no_detail, row, "Acme Limited", refs)
    assert j_no_detail["verdict"] == "Partial"
    assert "boundary" in j_no_detail["failing"]


def test_s2_unit_match_phrase_unit():
    assert g2.unit_match("%", "% of key suppliers", metric_text="Energy used by % of key suppliers") is True
    assert g2.unit_match("%", "% of key suppliers", metric_text="Suppliers who are key use % renewable") is False
    assert g2.unit_match("%", "% of key suppliers", metric_text="Energy used by % of total employees") is False
    assert g2.unit_match("%", "% of key suppliers", metric_text="Energy used by % of suppliers") is False
    assert g2.unit_match("MWh", "% of key suppliers", metric_text="Energy used by % of key suppliers") is False
    assert g2.unit_match("%", "% of key suppliers", metric_text=None) is False


def test_s3_unit_key_normalisation_unit():
    # Latent defect fix: t CO2e, tco2 e, tonnes co2e all normalise to tco2e
    assert g2.unit_key("t CO2e") == "tco2e"
    assert g2.unit_key("tco2 e") == "tco2e"
    assert g2.unit_key("tonnes co2e") == "tco2e"
    assert g2.unit_key("tco2e") == "tco2e"
    assert g2.unit_key("t CO2e") == g2.unit_key("tco2e") == g2.unit_key("tonnes co2e")


def test_s4_digit_bearing_strings_unit():
    assert g2.is_string_answer("ISO 45001:2018") is True
    assert g2.is_string_answer("14 May 2025") is True
    assert g2.is_string_answer("Level 3") is True
    assert g2.is_string_answer("4,560") is False
    assert g2.is_string_answer("123.45") is False

    assert g2.value_match("ISO 45001:2018", "ISO 45001:2018") is True
    assert g2.value_match("iso 45001:2018", "ISO 45001:2018") is True
    assert g2.value_match("ISO  45001:2018", "ISO 45001:2018") is True
    assert g2.value_match("ISO 45001:2015", "ISO 45001:2018") is False
    assert g2.value_match("45001", "ISO 45001:2018") is False


def test_s5_origin_states_and_summarise_unit():
    assert g2.classify_state("machine-inferred") == ("machine-inferred", None)
    assert g2.classify_state("accepted") == ("reviewed", None)
    assert g2.classify_state("resolved") == ("reviewed", None)
    assert g2.classify_state("unresolved") == ("unresolved", None)
    assert g2.classify_state("proposed") == ("unresolved", None)
    assert g2.classify_state("unknown") == ("unresolved", None)
    assert g2.classify_state("rejected") == ("unresolved", None)
    assert g2.classify_state(None) == ("unresolved", None)
    assert g2.classify_state("custom_state") == ("unresolved", "custom_state")

    # summarise() tracks automatic vs review-assisted Found counts
    rows = [
        {"verdict": "Found", "origin": "machine-inferred", "evidence_found": True, "value_elsewhere_in_document": False, "ceiling": []},
        {"verdict": "Found", "origin": "machine-inferred", "evidence_found": True, "value_elsewhere_in_document": False, "ceiling": []},
        {"verdict": "Found", "origin": "review-assisted", "evidence_found": True, "value_elsewhere_in_document": False, "ceiling": []},
        {"verdict": "Partial", "failing": ["period"], "evidence_found": False, "value_elsewhere_in_document": False, "ceiling": []},
    ]
    auto_sum = g2.summarise(rows, review_assisted=False)
    assert auto_sum["found_total"] == 3
    assert auto_sum["found_automatic"] == 2
    assert auto_sum["found_review_assisted"] == 1
    assert auto_sum["found"] == 3
    assert auto_sum["found_automatic_text"] == "2/4 (50.0%)"
    # Automatic gate uses found_automatic (2/4 = 50.0% < 90% target -> fail)
    assert auto_sum["verdict"] == "fail"

    rev_sum = g2.summarise(rows, review_assisted=True)
    # Review-assisted gate uses found_total (3/4 = 75.0% < 90% target -> fail)
    assert rev_sum["found_total"] == 3
    assert rev_sum["found_review_assisted"] == 1


def test_s6_ceiling_and_change_ledger_unit(tmp_path):
    # Five ceiling reasons:
    # 1. gold boundary segment
    r1 = make_gold_row(boundary="segment")
    assert "gold boundary segment" in g2.ceiling(r1)

    # 2. gold currency unit
    r2 = make_gold_row(unit="INR crore")
    assert "gold currency unit" in g2.ceiling(r2)

    # 3. gold value is not a figure
    r3 = make_gold_row(answer="Not disclosed")
    assert "gold value is not a figure" in g2.ceiling(r3)

    # 4. unit not in extractor's vocabulary
    r4 = make_gold_row(unit="light years")
    assert "unit not in the extractor's vocabulary" in g2.ceiling(r4)

    # 5. string answer
    r5 = make_gold_row(answer="ISO 45001:2018")
    assert "string answer" in g2.ceiling(r5)

    # Change ledger generation and attribution
    prev = {
        "rows": [
            {"id": "r-01", "verdict": "Partial", "failing": ["boundary"], "ceiling": ["gold boundary segment"]},
            {"id": "r-02", "verdict": "Missed", "failing": [], "ceiling": []},
            {"id": "r-03", "verdict": "Partial", "failing": ["period"], "ceiling": []},
            {"id": "r-04", "verdict": "Missed", "failing": [], "ceiling": []},
        ]
    }
    curr_rows = [
        # S-1: segment row moves from Partial to Found
        {
            "id": "r-01", "verdict": "Found", "failing": [], "ceiling": ["gold boundary segment"],
            "boundary": "segment", "boundary_detail": "Commercial Vehicles", "claim": 1,
            "value_text": "10", "unit_text": "MWh", "page": 1, "doc": "doc.pdf", "company": "Acme",
        },
        # S-2: % of unit
        {
            "id": "r-02", "verdict": "Partial", "failing": ["period"], "ceiling": [],
            "unit_text": "%", "metric_text": "renewable energy % of suppliers", "claim": 2,
            "value_text": "50", "page": 1, "doc": "doc.pdf", "company": "Acme",
        },
        # S-5: origin change
        {
            "id": "r-03", "verdict": "Found", "failing": [], "ceiling": [],
            "origin": "machine-inferred", "period_origin": "machine-inferred", "claim": 3,
            "value_text": "20", "unit_text": "MWh", "page": 1, "doc": "doc.pdf", "company": "Acme",
        },
        # S-6: only ceiling changes
        {
            "id": "r-04", "verdict": "Missed", "failing": [], "ceiling": ["string answer"],
            "claim": None, "value_text": None, "unit_text": None, "page": 1, "doc": "doc.pdf", "company": "Acme",
        },
    ]
    report_file = tmp_path / "g2-report-v1-20261025.json"
    ledger = g2.build_change_ledger(prev, curr_rows, report_file)
    assert len(ledger) == 4

    rules = {entry["id"]: entry["attributed_to"] for entry in ledger}
    assert rules["r-01"] == "scorer:S-1"
    assert ledger[0]["segment_name"] == "Commercial Vehicles"
    assert rules["r-02"] == "scorer:S-2"
    assert rules["r-03"] == "scorer:S-5"
    assert rules["r-04"] == "scorer:S-6"

    ledger_file = tmp_path / "g2-ledger-v1-20261025.jsonl"
    assert ledger_file.is_file()
    lines = [json.loads(l) for l in ledger_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 4


# ==============================================================================
# AC 8: Report Compatibility
# ==============================================================================


def test_ac8_report_backward_compatibility(tmp_path):
    """v1 report keys keep their name/meaning; new v2 keys are additive only."""
    manifest = {"sha256": {"documents.json": "d", "text.jsonl": "t", "tables.jsonl": "b", "figures.jsonl": "f"}}

    v1_report = {
        "published_version": 1,
        "gct_commit": "e931eeb",
        "scorer_version": "1",
        "status": "ok",
        "run_id": "20261021T132603934294Z",
        "report_path": str(tmp_path / "g2-report-v1.json"),
        "workspace": str(tmp_path / "ws"),
        "published": {"workspace": str(tmp_path / "ws"), "built_at": "2026-10-21", "history_mark": "m", "sha256": "s"},
        "gold": {"folder": str(tmp_path / "gold"), "version": "test", "commit": "c", "sha256": manifest["sha256"]},
        "headline": "headline text",
        "target": "90%",
        "delta": None,
        "rows": [{"id": "r-01", "verdict": "Found", "failing": [], "ceiling": []}],
        "types": [
            {"company": "Acme Limited", "kind": "text", "n": 1, "found": 1, "partial": 0, "missed": 0,
             "found_text": "1/1 (100.0%)", "verdict": "at or above 90% before adjudication", "re_adjudicate": True}
        ],
        "document_types": [],
        "documents": [],
        "runs": [{"row": "rung 1", "state": "scored"}],
        "adjudication": {"seed": 42, "missed": [], "found_sample": []},
        "aggregate": [],
    }
    v1_path = tmp_path / "prev_v1_report.json"
    v1_path.write_text(json.dumps(v1_report), encoding="utf-8")

    # Test that _previous loads v1 report without issue
    loaded = g2._previous(str(v1_path), manifest)
    assert loaded["scorer_version"] == "1"
    assert loaded["published_version"] == 1

    # Test that delta attributes change to scorer because scorer_version changed from 1 to 2
    v2_types = [
        {"company": "Acme Limited", "kind": "text", "n": 1, "found": 1, "partial": 0, "missed": 0,
         "found_text": "1/1 (100.0%)"}
    ]
    identity = {"workspace": str(tmp_path / "ws"), "built_at": "2026-10-21", "history_mark": "m", "sha256": "s"}
    ch = g2.delta(loaded, identity, v2_types)
    assert ch["attributed_to"] == "scorer"
    assert ch["previous"]["scorer_version"] == "1"


# ==============================================================================
# AC 9: Unknown States
# ==============================================================================


def test_ac9_origin_states_and_unrecognised_states():
    """Recognised vs unrecognised origin states."""
    row = make_gold_row()

    # Recognised origins:
    # 1. machine-inferred
    c1, refs = make_claim(period_state="machine-inferred")
    j1 = g2._judge(c1, row, "Acme Limited", refs)
    assert j1["verdict"] == "Found"
    assert j1["origin"] == "machine-inferred"
    assert j1["period_origin"] == "machine-inferred"

    # 2. accepted
    c2, refs = make_claim(period_state="accepted")
    j2 = g2._judge(c2, row, "Acme Limited", refs)
    assert j2["verdict"] == "Found"
    assert j2["origin"] == "review-assisted"
    assert j2["period_origin"] == "reviewed"

    # 3. resolved
    c3, refs = make_claim(period_state="resolved")
    j3 = g2._judge(c3, row, "Acme Limited", refs)
    assert j3["verdict"] == "Found"
    assert j3["origin"] == "review-assisted"
    assert j3["period_origin"] == "reviewed"

    # Recognised unresolved states -> period condition fails -> Partial
    for state in ("unresolved", "proposed", "unknown", "rejected"):
        c_unres, refs = make_claim(period_state=state)
        j_unres = g2._judge(c_unres, row, "Acme Limited", refs)
        assert j_unres["verdict"] == "Partial"
        assert "period" in j_unres["failing"]
        assert j_unres["period_origin"] == "unresolved"
        assert j_unres["unrecognised_states"] == []

    # Unrecognised states -> scored as unresolved, reported by name
    c_custom, refs = make_claim(period_state="custom_audited_state")
    j_custom = g2._judge(c_custom, row, "Acme Limited", refs)
    assert j_custom["verdict"] == "Partial"
    assert "period" in j_custom["failing"]
    assert j_custom["period_origin"] == "unresolved"
    assert j_custom["unrecognised_states"] == ["custom_audited_state"]

    # machine-inferred is recognized ONLY as exact string (casing/separator variations are unrecognised)
    c_case, refs = make_claim(period_state="Machine-Inferred")
    j_case = g2._judge(c_case, row, "Acme Limited", refs)
    assert j_case["verdict"] == "Partial"
    assert j_case["period_origin"] == "unresolved"
    assert "Machine-Inferred" in j_case["unrecognised_states"]
