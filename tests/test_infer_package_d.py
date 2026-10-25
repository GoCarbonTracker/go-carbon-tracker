"""Tests for Story M1-3.8 Package D: Automatic period and boundary inference.

Acceptance criteria:
- Fixtures for dated labels, fiscal-year labels, header-recovered labels.
- Agreeing boundary statements infer the boundary across the whole document (or page range) automatically without manual scoping, marked machine-inferred.
- Differing boundary statements stay unresolved with reason.
- Fiscal year statement parsing ('FY_LABEL_STMT') captures statement forms like 'Financial year for which reporting is being done: 2024-25'.
- Period inheritance: unlabelled claims inherit period from document's agreeing fiscal basis.
- Published precedence: deterministic period and boundary with basis publish as machine-inferred.
"""
from datetime import date
import pytest
from gct.stages import infer
from gct.workspace import published
from test_infer import add_doc, label_claims, listed, run_infer, WHO


@pytest.fixture
def acme(ws, gct):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")


def test_fy_label_statement_parsing():
    """Bases extraction recognizes FY_LABEL_STMT forms."""
    reading = {
        "text": "General Information. Financial year for which reporting is being done: 2024-25. Some more text.",
        "words": [],
        "page_number": 1,
    }
    bases, heading = infer.bases_of(reading)
    fy_bases = [b for b in bases if b["kind"] == "fiscal_year_end"]
    assert len(fy_bases) == 1
    assert fy_bases[0]["period_start"] == "2024-04-01"
    assert fy_bases[0]["period_end"] == "2025-03-31"
    assert fy_bases[0]["fy_end"] == "03-31"


def test_period_inheritance_on_unlabelled_claims(ws, db, gct, make_file, acme):
    """Claims without period label inherit period if document has agreeing fiscal basis."""
    fy_line = ["General Information.", "Financial year for which reporting is being done: 2024-25."]
    data_line = ["Total Scope 1 emissions: 1500 tCO2e"]
    doc = add_doc(gct, make_file, "fy_inherit.pdf", [fy_line, data_line])
    gct("read")

    # Label claim with no period label (None)
    (claim_id,) = label_claims(db, doc, [None], page_number=2)

    run_infer(gct)
    cs = listed(gct, doc)
    c = cs[claim_id]

    # Inferred period has inherited fiscal year start and end
    assert c["period"]["state"] == "proposed"
    assert c["period"]["kind"] == "fiscal_year"
    assert c["period"]["start"] == "2024-04-01"
    assert c["period"]["end"] == "2025-03-31"
    assert c["period"]["basis"] is not None


def test_agreeing_boundary_statements_auto_scope_and_publish_machine_inferred(ws, db, gct, make_file, acme):
    """Agreeing boundary statements auto-scope to all pages and publish as machine-inferred."""
    b_line = ["13. Reporting boundary: Report is prepared on a standalone basis i.e, Tata Motors Limited.",
              "Financial Year ended March 31, 2025."]
    data_line = ["Scope 1 emissions: 200 tCO2e", "FY 2024-25"]
    doc = add_doc(gct, make_file, "agreeing_b.pdf", [b_line, data_line])
    gct("read")

    (claim_id,) = label_claims(db, doc, ["FY 2024-25"], page_number=2)
    run_infer(gct)

    # In published db without human review, both period and boundary publish as machine-inferred
    v = gct("publish", "build", "--json").data
    conn = published.open_version(ws / "published" / f"v{v['version']}.db")
    row = dict(conn.execute("SELECT * FROM claim WHERE id = ?", (claim_id,)).fetchone())
    conn.close()

    assert row["reporting_boundary"] == "standalone"
    assert row["boundary_state"] == "machine-inferred"
    assert row["period_kind"] == "fiscal_year"
    assert row["period_start"] == "2024-04-01"
    assert row["period_end"] == "2025-03-31"
    assert row["period_state"] == "machine-inferred"


def test_differing_boundary_statements_stay_unresolved(ws, db, gct, make_file, acme):
    """Differing boundary statements in same document leave pages unresolved without explicit scope."""
    p1 = ["13. Reporting boundary: Report is prepared on a standalone basis."]
    p2 = ["Data page 2: Scope 1 emissions: 100 tCO2e"]
    p3 = ["The report is prepared on a consolidated basis."]
    doc = add_doc(gct, make_file, "differing_b.pdf", [p1, p2, p3])
    gct("read")

    (claim_id,) = label_claims(db, doc, [None], page_number=2)
    run_infer(gct)

    cs = listed(gct, doc)
    assert cs[claim_id]["boundary"]["state"] == "unresolved"
    assert cs[claim_id]["boundary"]["reason"] == "no boundary statement covers this page"
