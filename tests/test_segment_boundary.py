import json
import sqlite3
import pytest

from conftest import make_pdf
from gct.stages import infer, view
from gct.workspace import published, store
from gct.measure.g2 import measure, score_row, classify_state

WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked on the page")


def page(lines):
    return {"text": [(40, 80 + 20 * i, s) for i, s in enumerate(lines)]}


def add_doc(gct, make_file, name, pages):
    r = gct("doc", "add", make_file(name, make_pdf([page(p) for p in pages])), "--company", "Acme", "--json")
    return r.data["items"][0]["document"]["id"]


def make_claim_version(db, doc_id, page_number, locator, metric_text, value_text, unit_text, period_label, boundary_label=None, reporting_boundary="unknown", boundary_detail=None):
    claim_id = db.execute(
        "INSERT INTO claim (company_id, document_id, page_number, locator, created_at) VALUES (1, ?, ?, ?, 't')",
        (doc_id, page_number, locator)
    ).lastrowid
    v_id = db.execute(
        "INSERT INTO claim_version (claim_id, run_id, method, config_version, metric_text, value_text, value, unit_text, period_label, boundary_label, reporting_boundary, boundary_detail, created_at) "
        "VALUES (?, 1, 'hand', 'c', ?, ?, 100.0, ?, ?, ?, ?, ?, 't')",
        (claim_id, metric_text, value_text, unit_text, period_label, boundary_label, reporting_boundary, boundary_detail)
    ).lastrowid
    db.execute(
        "INSERT INTO evidence_ref (claim_version_id, document_id, page_number, created_at) VALUES (?, ?, ?, 't')",
        (v_id, doc_id, page_number)
    )
    db.commit()
    return claim_id, v_id


def test_ac1_migration_0022_schema_and_check_constraints(tmp_path):
    conn = store.connect(tmp_path / "test.db")
    store.migrate(conn)
    current = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert current >= 22

    conn.execute("INSERT INTO company (name, created_at) VALUES ('Acme', 't')")
    conn.execute("INSERT INTO document (company_id, logical_name, version, sha256, kind, file_type, privacy, size_bytes, created_at)"
                 " VALUES (1, 'd.pdf', 1, 'hash', 'report', 'pdf', 'shareable', 10, 't')")
    conn.execute("INSERT INTO run (started_at, command, gct_version) VALUES ('t', 'c', 'v')")
    conn.execute("INSERT INTO claim (company_id, document_id, page_number, locator, created_at) VALUES (1, 1, 1, 'l1', 't')")

    # 1. claim_version accepts segment
    conn.execute("INSERT INTO claim_version (claim_id, run_id, method, config_version, value_text, reporting_boundary, boundary_detail, created_at)"
                 " VALUES (1, 1, 'm', 'c', '10', 'segment', 'Commercial Vehicles', 't')")

    # 2. basis accepts segment
    conn.execute("INSERT INTO basis (document_id, page_number, kind, wording, boundary, boundary_detail, run_id, config_version, created_at)"
                 " VALUES (1, 1, 'reporting_boundary', 'Commercial Vehicles segment', 'segment', 'Commercial Vehicles', 1, 'c', 't')")

    # 3. inference accepts machine-inferred state and segment boundary
    conn.execute("INSERT INTO inference (claim_version_id, field, state, boundary, boundary_detail, basis_id, group_key, run_id, config_version, created_at)"
                 " VALUES (1, 'boundary', 'machine-inferred', 'segment', 'Commercial Vehicles', 1, 'k', 1, 'c', 't')")

    # 4. inference_review accepts segment boundary
    conn.execute("INSERT INTO contributor_version (contributor_key, name, organisation, created_at) VALUES ('k1', 'Alice', 'Org', 't')")
    conn.execute("INSERT INTO inference_review (inference_id, claim_version_id, field, decision, boundary, boundary_detail, contributor_version_id, capacity, rationale, created_at)"
                 " VALUES (1, 1, 'boundary', 'resolved', 'segment', 'Commercial Vehicles', 1, 'cap', 'rat', 't')")

    # 5. sheet_mapping accepts segment boundary
    conn.execute("INSERT INTO sheet_mapping (document_id, sheet, position, value_col, boundary_is, boundary_detail, contributor_version_id, capacity, rationale, created_at)"
                 " VALUES (1, 's1', 1, 'A', 'segment', 'Commercial Vehicles', 1, 'cap', 'rat', 't')")

    # Check constraints reject invalid values
    bad_statements = [
        "INSERT INTO claim_version (claim_id, run_id, method, config_version, value_text, reporting_boundary, created_at) VALUES (1, 1, 'm', 'c', '10', 'group', 't')",
        "INSERT INTO basis (document_id, page_number, kind, wording, boundary, run_id, config_version, created_at) VALUES (1, 1, 'reporting_boundary', 'w', 'group', 1, 'c', 't')",
        "INSERT INTO inference (claim_version_id, field, state, group_key, run_id, config_version, created_at) VALUES (1, 'boundary', 'approved', 'k', 1, 'c', 't')",
        "INSERT INTO inference_review (claim_version_id, field, decision, boundary, contributor_version_id, capacity, rationale, created_at) VALUES (1, 'boundary', 'resolved', 'invalid_boundary', 1, 'cap', 'rat', 't')",
    ]
    for stmt in bad_statements:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(stmt)

    conn.close()


def test_ac3_segment_matching_printed_label_to_segment(ws, db, gct, make_file):
    gct("company", "add", "Acme")
    seg_note = [
        "13. Segment information:",
        "The reportable segments comprise Commercial Vehicles and Passenger Vehicles.",
    ]
    doc = add_doc(gct, make_file, "seg_doc.pdf", [seg_note, ["FY24 Data"]])
    gct("read")

    # Claim with boundary_label = "Commercial Vehicles"
    c1, v1 = make_claim_version(db, doc, 2, "loc1", "Scope 1 emissions", "100", "tCO2e", "FY24", boundary_label="Commercial Vehicles")
    # Claim with metric_text containing "Passenger Vehicles"
    c2, v2 = make_claim_version(db, doc, 2, "loc2", "Passenger Vehicles Scope 1 emissions", "50", "tCO2e", "FY24")

    gct("infer")

    # Verify both got machine-inferred segment
    infs = db.execute("SELECT claim_version_id, boundary, boundary_detail, state FROM inference WHERE field = 'boundary' ORDER BY id").fetchall()
    infs_by_cv = {r[0]: (r[1], r[2], r[3]) for r in infs}

    assert infs_by_cv[v1] == ("segment", "Commercial Vehicles", "machine-inferred")
    assert infs_by_cv[v2] == ("segment", "Passenger Vehicles", "machine-inferred")


def test_ac3_segment_no_label_stays_unresolved(ws, db, gct, make_file):
    gct("company", "add", "Acme")
    seg_note = [
        "The reportable segments comprise Commercial Vehicles and Passenger Vehicles.",
    ]
    doc = add_doc(gct, make_file, "seg_doc2.pdf", [seg_note, ["FY24 Data"]])
    gct("read")

    # Claim has no segment label or metric wording
    c, v = make_claim_version(db, doc, 2, "loc_nolabel", "Scope 1 emissions", "100", "tCO2e", "FY24")
    gct("infer")

    inf = db.execute("SELECT boundary, boundary_detail, state, reason FROM inference WHERE claim_version_id = ? AND field = 'boundary'", (v,)).fetchone()
    assert inf[2] == "unresolved"
    assert inf[3] == infer.NO_SCOPE


def test_ac3_segment_differing_statements_unresolved(ws, db, gct, make_file):
    gct("company", "add", "Acme")
    seg_note = [
        "The reportable segments comprise Commercial Vehicles and Passenger Vehicles.",
    ]
    doc = add_doc(gct, make_file, "seg_conflict.pdf", [seg_note, ["FY24 Data"]])
    gct("read")

    # Claim wording mentions BOTH segments
    c, v = make_claim_version(db, doc, 2, "loc_conflict", "Commercial Vehicles and Passenger Vehicles total", "200", "tCO2e", "FY24")
    gct("infer")

    inf = db.execute("SELECT boundary, boundary_detail, state, reason FROM inference WHERE claim_version_id = ? AND field = 'boundary'", (v,)).fetchone()
    assert inf[2] == "unresolved"
    assert "differing segment statements" in inf[3]


def test_ac2_machine_inferred_precedence_and_publication(ws, db, gct, make_file):
    gct("contributor", "add", "ana", "--name", "Ana")
    gct("company", "add", "Acme")
    seg_note = [
        "The reportable segments comprise Commercial Vehicles and Passenger Vehicles.",
    ]
    doc = add_doc(gct, make_file, "seg_prec.pdf", [seg_note, ["FY24 Data"]])
    gct("read")

    c1, v1 = make_claim_version(db, doc, 2, "loc_p1", "Scope 1", "100", "tCO2e", "FY24", boundary_label="Commercial Vehicles")
    c2, v2 = make_claim_version(db, doc, 2, "loc_p2", "Scope 2", "50", "tCO2e", "FY24", boundary_label="Passenger Vehicles")
    gct("infer")

    # 1. Publish without review: machine-inferred is published in main fields
    v_res = gct("publish", "build", "--json").data
    p_conn = published.open_version(ws / "published" / f"v{v_res['version']}.db")
    row_c1 = dict(p_conn.execute("SELECT * FROM claim WHERE id = ?", (c1,)).fetchone())
    assert row_c1["reporting_boundary"] == "segment"
    assert row_c1["boundary_detail"] == "Commercial Vehicles"
    assert row_c1["boundary_state"] == "machine-inferred"
    assert row_c1["proposed_reporting_boundary"] is None
    p_conn.close()

    # 2. Reviewer resolves c1 with standalone: resolved overrides machine-inferred
    gct("infer", "resolve", str(c1), "--field", "boundary", "--boundary", "standalone", *WHO)
    v_res2 = gct("publish", "build", "--json").data
    p_conn2 = published.open_version(ws / "published" / f"v{v_res2['version']}.db")
    row_c1_rev = dict(p_conn2.execute("SELECT * FROM claim WHERE id = ?", (c1,)).fetchone())
    assert row_c1_rev["reporting_boundary"] == "standalone"
    assert row_c1_rev["boundary_state"] == "resolved"

    # 3. Reviewer rejects c2: rejected keeps claim unresolved
    gct("infer", "reject", "--claim", str(c2), "--field", "boundary", *WHO)
    v_res3 = gct("publish", "build", "--json").data
    p_conn3 = published.open_version(ws / "published" / f"v{v_res3['version']}.db")
    row_c2_rej = dict(p_conn3.execute("SELECT * FROM claim WHERE id = ?", (c2,)).fetchone())
    assert row_c2_rej["reporting_boundary"] == "unknown"
    assert row_c2_rej["boundary_state"] == "unresolved"
    p_conn3.close()


def test_ac4_scorer_v2_scores_segment_found_and_partial():
    # Gold expectation: boundary is segment
    gold_row = {
        "id": "r1",
        "doc": "doc.pdf",
        "kind": "figure",
        "page": 2,
        "expected_answer": "100",
        "unit": "tco2e",
        "period": {"start": "2023-04-01", "end": "2024-03-31"},
        "boundary": "segment",
        "content_type": "figure",
        "source": "table",
        "metric": "Scope 1",
        "aliases": [],
        "verify_status": "VERIFIED",
    }

    # Case A: claim has segment boundary and printed detail under machine-inferred state -> Found
    claim_found = {
        "id": 1,
        "claim_version_id": 1,
        "document_id": 1,
        "page_number": 2,
        "company": "Acme",
        "value_text": "100",
        "unit_text": "tco2e",
        "metric_text": "Scope 1",
        "period_start": "2023-04-01",
        "period_end": "2024-03-31",
        "period_state": "accepted",
        "period_origin": "reviewed",
        "reporting_boundary": "segment",
        "boundary_detail": "Commercial Vehicles",
        "boundary_state": "machine-inferred",
        "boundary_origin": "machine-inferred",
    }
    doc = {"company": "Acme", "id": 1, "document_type": "BRSR"}
    ws_doc = {"id": 1}
    res_found = score_row(gold_row, doc, ws_doc, [claim_found], {})
    assert res_found["verdict"] == "Found"

    # Case B: claim has no segment boundary (e.g. unknown) -> Partial with ceiling "gold boundary segment"
    claim_partial = {**claim_found, "reporting_boundary": "unknown", "boundary_detail": None, "boundary_state": "unresolved", "boundary_origin": "unresolved"}
    res_partial = score_row(gold_row, doc, ws_doc, [claim_partial], {})
    assert res_partial["verdict"] == "Partial"
    assert "gold boundary segment" in res_partial["ceiling"]
    assert "gold boundary segment" in res_partial["ceiling"]
