"""Story 3.5 stream R: headers printed above a table and row labels left of it (AC 3), comparison years (AC 4)."""
import copy
import io

import pdfplumber

from pdf_layouts import RAGGED_LABELS, TATA_P134, VALUE_COLUMNS, pdf
from gct.stages import extract, read


def reading(layout) -> dict:
    with pdfplumber.open(io.BytesIO(pdf([layout]))) as doc:
        return read.read_page(doc.pages[0])


def by_locator(r) -> dict:
    return {f["locator"]: f for f in extract.rules(r)}


# AC 3
def test_headers_above_a_table_head_their_columns():
    r = reading(TATA_P134)
    found = by_locator(r)
    for row, metric in ((0, "Scope 1 emissions (tCO2e)"), (1, "Scope 2 emissions (tCO2e)")):
        got = [(found[f"t0r{row}c{c}"]["period_label"], found[f"t0r{row}c{c}"]["boundary_label"],
                found[f"t0r{row}c{c}"]["metric_text"], found[f"t0r{row}c{c}"]["unit_text"]) for c in range(3)]
        assert got == [("FY24", "Standalone*", metric, "tCO2e"), ("FY23", "Standalone*", metric, "tCO2e"),
                       ("FY24", "Consolidated", metric, "tCO2e")]
    # Dash cells are empty, so the row takes its label from the left; the column right of the bbox gets nothing.
    assert [loc for loc in found if loc.startswith("t0r2")] == ["t0r2c2"]
    assert (found["t0r2c2"]["value_text"], found["t0r2c2"]["metric_text"], found["t0r2c2"]["period_label"],
            found["t0r2c2"]["boundary_label"]) == ("699.80", "Other income", "FY24", "Consolidated")
    assert "7,070" not in {f["value_text"] for f in found.values()}
    # The second table has a header-like line more than 30 pt above it; the fourth sits under a short table.
    for loc in ("t1r0c0", "t1r0c1", "t3r0c0", "t3r0c1"):
        assert (found[loc]["period_label"], found[loc]["boundary_label"], found[loc]["metric_text"]) == (None, None, None)
    far = next(w for w in r["words"] if w["text"] == "FY22")
    assert r["tables"][1]["bbox"][1] - far["bottom"] > extract.HEADER_BAND
    above = next(w for w in r["words"] if w["text"] == "FY21")
    assert r["tables"][3]["bbox"][1] - above["bottom"] <= extract.HEADER_BAND  # only the table between stops it
    # Outside the tables nothing takes a header: the text claim keeps its own line's period.
    text = [f for f in found.values() if f["locator"].startswith("l")]
    assert [(f["value_text"], f["period_label"], f["boundary_label"]) for f in text] == [("5", "FY24", None)]
    assert set(found["t0r0c0"]) == {"locator", "metric_text", "value_text", "value", "unit_text", "period_label",
                                    "boundary_label", "boxes"}


def test_the_header_band_ends_at_30_points():
    r = reading(TATA_P134)
    top = r["tables"][1]["bbox"][1]
    for gap, period in ((30, "FY22"), (31, None)):
        moved = copy.deepcopy(r)
        w = next(w for w in moved["words"] if w["text"] == "FY22")
        w["top"], w["bottom"] = top - gap - (w["bottom"] - w["top"]), top - gap
        assert by_locator(moved)["t1r0c0"]["period_label"] == period


def test_a_header_line_that_is_not_all_headers_ends_the_band():
    r = copy.deepcopy(reading(TATA_P134))
    fy = [w for w in r["words"] if w["text"] in ("FY24", "FY23") and w["top"] < 179]
    for w in fy:
        w["text"] = "Units"
    found = by_locator(r)
    assert [found[f"t0r0c{c}"]["period_label"] for c in range(3)] == [None] * 3
    assert [found[f"t0r0c{c}"]["boundary_label"] for c in range(3)] == [None] * 3


def test_one_long_line_past_a_gap_is_no_gutter():
    found = by_locator(reading(RAGGED_LABELS))
    assert {found[f"t0r4c{c}"]["metric_text"] for c in range(3)} == {
        "Profit before interest, foreign exchange, depreciation, amortization, exceptional item and tax"}


def test_value_columns_left_of_a_table_are_not_row_labels():
    # Mahindra AR p75: figures and units printed between the label column and the bbox are values, not wording.
    found = by_locator(reading(VALUE_COLUMNS))
    assert [found[f"t0r{r}c0"]["metric_text"] for r in range(4)] == [
        "Tractors sold", None, "Scope 1 emissions", "Category 1 : Purchased goods"]
    assert found["t0r0c0"]["value_text"] == "43,01,848"


# AC 4
LINES = ["a 3% and 28% increase in their sales volumes as compared to FY23",
         "grew 12% in FY24 as compared to FY23",
         "Scope 1 emissions FY23 12,345 tCO2e",
         "emissions over FY24 were 23,456 tCO2e",
         "emissions 34,567 tCO2e as compared to FY23"]


def test_a_figure_never_takes_its_comparison_year():
    r = reading({"text": [(40, 100 + 20 * i, s, 10) for i, s in enumerate(LINES)]})
    got = {f["value_text"]: f["period_label"] for f in extract.rules(r)}
    assert got == {"3": None, "28": None, "12": "FY24", "12,345": "FY23", "23,456": "FY24", "34,567": None}


def test_the_change_word_on_the_line_before_does_not_matter():
    # Tata AR p135 as printed: the change word ends one line, the figure and its comparison year start the next.
    r = reading({"text": [(40, 100, "Sales volumes have decreased by", 10), (40, 114, "12% as compared to FY23.", 10)]})
    assert {f["value_text"]: f["period_label"] for f in extract.rules(r)} == {"12": None}
