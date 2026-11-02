"""Story 4.1: metric keys, units, series across periods and reports, the review queue. No real report is used."""
import json
import re
import sqlite3
from pathlib import Path

import pytest

from conftest import grid, make_pdf
from test_extract import count, newest_run
from gct.stages import extract, match
from gct.workspace import layout, published, store

WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked on the page")
BOTH = ("FY 2024-25", "FY 2023-24")
SCOPE_1 = ["Total Scope 1 emissions", "tCO2e", "1,234", "1,100"]
ENERGY = ["Total energy consumed (A+B+C) (in GJ)", "", "5,000", "4,800"]
WASTE = ["Total waste generated (A+B+C)", "A+B+C", "300", "250"]


def report(rows, periods=BOTH, boundary="standalone", fy=True, lines=()) -> bytes:
    """A BRSR-shaped page: the fiscal-year statement, the item-13 boundary answer and a ruled table with a unit column
    and one column per period, as rung 1 reads it. `lines` are extra text lines (x, y, text)."""
    t = grid(40, 200, [250, 60] + [80] * len(periods), [20] * (len(rows) + 1), [["Parameter", "Unit", *periods], *rows])
    text = [(40, 80, "The financial year ended March 31, 2025."), *lines] if fy else list(lines)
    if boundary:
        text.append((40, 100, f"Reporting boundary: Report is prepared on a {boundary} basis."))
    return make_pdf([{"text": t["text"] + text, "lines": t["lines"]}])


@pytest.fixture
def acme(ws, gct):
    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")


def add(gct, make_file, name, rows, **kw) -> int:
    r = gct("doc", "add", make_file(name, report(rows, **kw)), "--company", "Acme", "--json")
    return r.data["items"][0]["document"]["id"]


def ready(gct, scoped=None):
    """Read, extract and infer every document, declare page 1 for the boundary statements of the scoped documents
    (default: all), accept every proposed group and match."""
    for step in ("read", "extract", "infer"):
        assert gct(step).code == 0
    for b in gct("infer", "bases", "--json").data["bases"]:
        if b["kind"] == "reporting_boundary" and (scoped is None or b["document"] in scoped):
            gct("infer", "scope", b["id"], "--pages", "1", *WHO)
    gct("infer")
    for g in gct("infer", "groups", "--state", "proposed", "--json").data["groups"]:
        gct("infer", "accept", g["id"], *WHO)
    r = gct("match", "--json")
    assert r.code == 0, r.out
    return r.data


def ids(gct, doc) -> dict:
    """{(metric text, period label): claim id} of one document."""
    return {(c["metric_text"], c["period_label"]): c["id"] for c in gct("claims", "list", "--doc", doc, "--json").data["claims"]}


def series(gct, metric=None) -> list:
    return gct("series", "list", *(("--metric", metric) if metric else ()), "--json").data["series"]


def states(db) -> dict:
    """{claim id: (match state, reason, series id)} from match.compute."""
    conn = store.connect(db.execute("PRAGMA database_list").fetchone()[2])
    try:
        return {c["claim_id"]: (c["state"], c["reason"], c["series_id"]) for c in match.compute(conn)["claims"]}
    finally:
        conn.close()


# AC 1
def test_migration_12_applies_to_a_version_11_workspace(tmp_path, gct):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    assert store.migrate(c, up_to=11) == list(range(1, 12))
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.close()
    assert gct("contributor", "list", "--workspace", root).code == 0
    c = store.connect(root / layout.DB_NAME)
    assert c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 23
    c.close()


def test_matching_tables_are_append_only_and_check_their_values(db):
    db.execute("INSERT INTO metric_assignment (claim_version_id, unit_source, run_id, config_version, created_at)"
               " VALUES (1, 'label', 1, 'c', 't')")
    db.execute("INSERT INTO match_review (claim_version_id, series_key, reason, decision, contributor_version_id, capacity,"
               " rationale, created_at) VALUES (1, 'k', 'boundary unknown', 'linked', 1, 'c', 'r', 't')")
    for table in ("metric_assignment", "match_review"):
        for stmt in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
                db.execute(stmt)
    for stmt in ("INSERT INTO metric_assignment (claim_version_id, unit_source, run_id, config_version, created_at)"
                 " VALUES (1, 'guess', 1, 'c', 't')",
                 "INSERT INTO match_review (claim_version_id, series_key, reason, decision, contributor_version_id,"
                 " capacity, rationale, created_at) VALUES (1, 'k', 'r', 'maybe', 1, 'c', 'r', 't')",
                 "INSERT INTO match_review (claim_version_id, series_key, decision, contributor_version_id, capacity,"
                 " rationale, created_at) VALUES (1, 'k', 'linked', 1, 'c', 'r', 't')"):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(stmt)


# AC 2
def test_metric_list_on_the_real_labels():
    got = {label: match.metric_of(label) for label in (
        "total scope 1 emissions# tcoe 2", "total scope 2 emissions# tco 2",
        "total energy consumed (a+b+c+d+e+f) (in gj)", "total energy consumed from renewable source (a+b+c)",
        "total volume of water consumption (in kilolitres)", "total water discharged (in kilolitres)",
        "total scope 1 and scope 2 emissions per rupee of turnover adjusted for purchasing power parity",
        "energy intensity per rupee of turnover (total energy consumed / revenue from operations)",
        "category 3 : fuel- and energy-related activities tco",
        "total volume of water withdrawal and total water discharged")}
    assert [k for k, _ in got.values()] == ["ghg_scope_1", "ghg_scope_2", "energy_total", "energy_renewable",
                                            "water_consumption_total", "water_discharge_total", None, None, None, None]
    assert got["total volume of water withdrawal and total water discharged"] == (None, "ambiguous")
    assert got["category 3 : fuel- and energy-related activities tco"] == (None, None)
    assert got["total scope 1 emissions# tcoe 2"][1] == "ghg_scope_1: scope 1"
    assert match.metric_of("Total Scope 1 and Scope 2 emissions")[0] == "ghg_scope_1_2"
    assert match.metric_of("Scope-1 emissions")[0] == match.metric_of("Scope I emissions")[0] == "ghg_scope_1"
    assert match.metric_of("Scope II emissions") == (None, None)
    assert match.metric_of("Scope 2 emissions (market-based)")[0] == "ghg_scope_2_market"
    # ratio and category are whole words: operations, generation and corporation still map
    assert [match.metric_of(label)[0] for label in (
        "Total Scope 1 emissions from operations", "total energy consumed from generation",
        "total water discharged (in kilolitres) from operations", "Scope 2 emissions of the corporation")] == [
        "ghg_scope_1", "energy_total", "water_discharge_total", "ghg_scope_2"]
    assert match.metric_of("Total Scope 1 emissions ratio") == match.metric_of("Scope 3 category emissions") == (None, None)
    assert match.metric_of(None) == (None, None)


def test_combined_scopes_and_targets_in_percent():
    # review F3, hand run H2
    assert match.metric_of("Total Scope 1+2 emissions") == ("ghg_scope_1_2", "ghg_scope_1_2: scope 1+2")
    assert match.metric_of("Total Scope 1 & 2 emissions") == ("ghg_scope_1_2", "ghg_scope_1_2: scope 1 & 2")
    assert match.metric_of("Total Scope 1, 2 and 3 emissions") == (None, None)
    assert match.metric_of("Total Scope I and Scope II emissions") == (None, None)
    # the exclusion words are checked on the printed unit too
    assert match.metric_of("Scope 3: Achieve a", "%") == match.metric_of("Scope 1 & 2: Achieve a", "%") == (None, None)
    assert match.metric_of("Scope 3: Achieve a")[0] == "ghg_scope_3"
    assert match.assign("Scope 3: Achieve a", "%")[:2] == (None, None)


# AC 3
@pytest.mark.parametrize("unit, label, expected", [
    ("in GJ", "Total energy", ("gj", 1.0, "unit")),
    (None, "total volume of water consumption (in kilolitres)", ("kl", 1.0, "label")),
    ("MWh", None, ("gj", 3.6, "unit")),
    ("'000 tCO2e", None, ("tco2e", 1000.0, "unit")),
    ("in lakh GJ", None, ("gj", 1e5, "unit")),
    (None, "total scope 2 emissions# tco 2", ("tco2", 1.0, "label")),
    (None, "total scope 1 emissions# tcoe 2", ("tco2e", 1.0, "label")),
    (None, "total scope 1 emissions# metric tonnes of co 2", ("tco2", 1.0, "label")),
    ("A+B+C", "total energy consumed (a+b+c+d+e+f) (in gj)", ("gj", 1.0, "label")),
    ("MtCO2e", "Scope 1 emissions", (None, None, None)),
    ("MtCO2e", "Total Scope 1 emissions (tCO2e)", (None, None, None)),  # review F4: no label fallback
    ("ML", "Total volume of water consumption (in kilolitres)", (None, None, None)),
    ("ML", "Water withdrawn", (None, None, None)),
    ("A+B+C", "total energy consumed from renewable source (a+b+c)", (None, None, None)),
    (None, None, (None, None, None)),
])
def test_unit_table(unit, label, expected):
    assert match.unit_of(unit, label) == expected


def test_tco2_never_converts_to_tco2e():
    assert {match.UNITS[u][0] for u in ("tco2", "tonnesofco2", "metrictonnesofco2")} == {"tco2"}
    assert all(f in match.FAMILIES for f, _ in match.UNITS.values())
    assert "mtco2e" not in match.UNITS and "ml" not in match.UNITS


def test_unit_as_printed_only_inside_its_own_row(ws, db, gct, make_file, acme):
    # the two columns of one row form a two-period series; a second row with the same label and unit is another one
    a = add(gct, make_file, "a.pdf", [WASTE, [WASTE[0], "a + b + c", "30", "25"]])
    b = add(gct, make_file, "b.pdf", [WASTE[:3]], periods=BOTH[:1])
    ready(gct)
    ss = series(gct, "waste_total")
    assert [(s["unit_family"], s["document_id"], s["periods"], s["same_period_sets"]) for s in ss] == [
        ("printed:a+b+c", a, 2, 0)] * 2
    shown = {s["id"]: gct("series", "show", s["id"], "--all", "--json").data["series"]["points"] for s in ss}
    by = {tuple(p["value_text"] for p in points): sid for sid, points in shown.items()}
    assert set(by) == {("250", "300"), ("25", "30")}
    assert [(p["unit_text"], p["link"], p["comparable"], p["reason"], p["value_base"]) for p in shown[by[("250", "300")]]] == [
        ("A+B+C", "rule", False, "unit as printed", None)] * 2
    assert match.unit_text_of("a + b + c") == match.unit_text_of("A+B+C") == "a+b+c"  # Q11
    items = gct("match", "review", "--json").data["items"]
    assert {(i["claim"], i["reason"]) for i in items} == {(ids(gct, b)[(WASTE[0], "FY 2024-25")], "unit unknown")}
    assert {i["series"] for i in items} == set(shown)


def page(tables, lines=()) -> bytes:
    """One page: the fiscal-year and standalone statements, text lines and ruled tables (y, rows) in the report()
    shape."""
    hdr = ["Parameter", "Unit", *BOTH]
    grids = [grid(40, y, [250, 60, 80, 80], [20] * (len(rows) + 1), [hdr, *rows]) for y, rows in tables]
    text = [(40, 80, "The financial year ended March 31, 2025."),
            (40, 100, "Reporting boundary: Report is prepared on a standalone basis."), *lines]
    return make_pdf([{"text": [t for g in grids for t in g["text"]] + text, "lines": [x for g in grids for x in g["lines"]]}])


def test_unmapped_labels_link_only_inside_their_row(ws, db, gct, make_file, acme):
    # review F2, hand run H1: a generic label never pools tables or rows
    gct("doc", "add", make_file("w.pdf", page([(200, [["(i) Recycled", "MT", "10", "9"], ["Total", "MT", "15", "12"]]),
                                              (300, [["(i) Incineration", "MT", "3", "2"], ["Total", "MT", "5", "4"]]),
                                              (400, [["NA", "", "8", "7"], ["NA", "", "6", "1"]])])), "--company", "Acme")
    ready(gct)
    got = sorted((s["label"], s["unit_family"], s["periods"], s["same_period_sets"],
                  tuple(p["value_text"] for p in gct("series", "show", s["id"], "--all", "--json").data["series"]["points"]))
                 for s in series(gct))
    assert got == [("(i) incineration", "t", 2, 0, ("2", "3")), ("(i) recycled", "t", 2, 0, ("9", "10")),
                   ("na", "printed:-", 2, 0, ("1", "6")), ("na", "printed:-", 2, 0, ("7", "8")),
                   ("total", "t", 2, 0, ("12", "15")), ("total", "t", 2, 0, ("4", "5"))]
    assert gct("match", "review", "--json").data["items"] == []


def test_an_unmapped_figure_outside_a_table_is_not_matchable(ws, db, gct, make_file, acme):
    gct("doc", "add", make_file("w.pdf", page([(200, [SCOPE_1])], [(40, 140, "Plastic waste recycled 40 tonnes in FY 2024-25")])),
        "--company", "Acme")
    ready(gct)
    text = [c for c in match.compute(store.connect(ws / "workspace.db"))["claims"] if not c["locator"].startswith("t")]
    assert [(c["metric_text"], c["state"], c["reason"]) for c in text] == [
        ("Plastic waste recycled", "not matchable", "unmapped outside a table row")]


# AC 4
def test_one_brsr_gives_a_two_period_series_per_metric(ws, db, gct, make_file, acme):
    doc = add(gct, make_file, "a.pdf", [SCOPE_1, ENERGY])
    (d,) = ready(gct)["documents"]
    assert (d["claims"], d["mapped"], d["unmapped"], d["unit_unknown"]) == (4, 4, 0, 0)
    ss = {s["metric_key"]: s for s in series(gct)}
    assert set(ss) == {"ghg_scope_1", "energy_total"}
    s = ss["ghg_scope_1"]
    assert (s["reporting_boundary"], s["unit_family"], s["period_kind"], s["periods"], s["latest_period_end"]) == (
        "standalone", "tco2e", "fiscal_year", 2, "2025-03-31")
    assert [p["value_text"] for p in s["points"]] == ["1,234"]  # the latest period
    out = gct("series", "show", s["id"]).out
    assert "2024-04-01..2025-03-31  1,234  tCO2e  1234 tco2e" in out and "1,100" not in out
    out = gct("series", "show", s["id"], "--all").out.splitlines()
    assert [line.split()[0] for line in out[1:]] == ["2023-04-01..2024-03-31", "2024-04-01..2025-03-31"]
    e = gct("series", "show", ss["energy_total"]["id"], "--all", "--json").data["series"]
    assert [(p["value_text"], p["unit_text"], p["unit_key"], p["value_base"], p["link"], p["comparable"])
            for p in e["points"]] == [("4,800", "in GJ", "gj", 4800.0, "rule", True), ("5,000", "in GJ", "gj", 5000.0, "rule", True)]
    assert set(states(db).values()) == {("series", None, ss["ghg_scope_1"]["id"]), ("series", None, ss["energy_total"]["id"])}
    assert all(c["document_id"] == doc for c in match.compute(store.connect(ws / "workspace.db"))["claims"])


# AC 5
def test_two_reports_one_series_and_a_same_period_set(ws, db, gct, make_file, acme):
    a = add(gct, make_file, "a.pdf", [SCOPE_1])
    b = add(gct, make_file, "b.pdf", [["Total Scope 1 emissions", "tCO2e", "1,150"]], periods=("FY 2023-24",))
    ready(gct)
    (s,) = series(gct)
    assert (s["periods"], s["same_period_sets"]) == (2, 1)
    shown = gct("series", "show", s["id"], "--all", "--json").data["series"]
    assert [(p["value_text"], p["document_id"], p["page_number"], p["same_period"]) for p in shown["points"]] == [
        ("1,100", a, 1, 2), ("1,150", b, 1, 2), ("1,234", a, 1, 1)]
    out = gct("series", "show", s["id"], "--all").out
    assert out.count("same period: 2 values") == 2 and f"document {a} p1" in out and f"document {b} p1" in out
    for text in (out, json.dumps(shown), gct("match", "status").out, gct("series", "list").out):
        assert not any(w in text.lower() for w in ("agree", "differ"))
    (st,) = gct("match", "status", "--json").data["companies"]
    assert (st["series"], st["same_period_sets"], st["uncertain_items"], st["states"]) == (1, 1, 0, {"series": 3})


# AC 6
def test_what_is_never_linked(ws, db, gct, make_file, acme):
    plastic = ["Plastic waste recycled (in MT)", "", "40", "35"]
    a = add(gct, make_file, "a.pdf", [SCOPE_1, plastic, ["Total Scope 2 emissions", "tCO2e", "700", "650"]])
    b = add(gct, make_file, "b.pdf", [plastic, ["Total Scope 2 emissions", "tCO 2", "710", "660"]])
    c = add(gct, make_file, "c.pdf", [SCOPE_1], boundary="consolidated")
    d = add(gct, make_file, "d.pdf", [["Total Scope 1 emissions", "tCO2e", "999"],
                                      ["Total volume of water consumption (in kilolitres)", "", "77"]],
            periods=("FY 2024-25",), boundary=None)
    e = add(gct, make_file, "e.pdf", [["Total Scope 1 emissions", "tCO2e", "888"]], periods=("FY 2024-25",), fy=False)
    f = add(gct, make_file, "f.pdf", [["Total Scope 1 emissions", "GJ", "555"]], periods=("FY 2024-25",))
    ready(gct)
    by = {(s["metric_key"] or s["label"], s["reporting_boundary"], s["unit_family"], s["document_id"]): s for s in series(gct)}
    assert set(by) == {("ghg_scope_1", "standalone", "tco2e", None), ("ghg_scope_1", "consolidated", "tco2e", None),
                       ("ghg_scope_2", "standalone", "tco2e", None), ("ghg_scope_2", "standalone", "tco2", None),
                       ("plastic waste recycled (in mt)", "standalone", "t", a),
                       ("plastic waste recycled (in mt)", "standalone", "t", b)}
    assert by[("ghg_scope_1", "consolidated", "tco2e", None)]["periods"] == 2
    st = states(db)
    unknown = ids(gct, d)[("Total Scope 1 emissions", "FY 2024-25")]
    assert st[unknown] == ("uncertain", "boundary unknown", None)
    items = [i for i in gct("match", "review", "--json").data["items"] if i["claim"] == unknown]
    assert sorted(i["reporting_boundary"] for i in items) == ["consolidated", "standalone"]
    water = ids(gct, d)[("Total volume of water consumption (in kilolitres)", "FY 2024-25")]
    assert st[water] == ("not matchable", "boundary unknown, no series to join", None)
    assert st[ids(gct, e)[("Total Scope 1 emissions", "FY 2024-25")]][0] == "series"
    gj = ids(gct, f)[("Total Scope 1 emissions", "FY 2024-25")]
    assert st[gj] == ("uncertain", "unit not convertible", None)
    (item,) = [i for i in gct("match", "review", "--json").data["items"] if i["claim"] == gj]
    assert item["series"] == by[("ghg_scope_1", "standalone", "tco2e", None)]["id"]  # its own boundary only
    assert len(gct("match", "review", "--reason", "boundary unknown", "--json").data["items"]) == 2
    (status,) = gct("match", "status", "--json").data["companies"]
    assert status["not_matchable"] == {"boundary unknown, no series to join": 1}
    assert status["uncertain_items"] == 3 and status["claims"] == sum(status["states"].values())


def test_a_known_unit_is_offered_only_series_of_its_family(ws, db, gct, make_file, acme):
    # review F1: a tCO2e figure with an unknown boundary is never offered the tco2 series, nor a unit as printed one
    add(gct, make_file, "a.pdf", [["Total Scope 2 emissions", "tCO2e", "700", "650"], WASTE])
    add(gct, make_file, "b.pdf", [["Total Scope 2 emissions", "tCO2", "510", "460"]])
    c = add(gct, make_file, "c.pdf", [["Total Scope 2 emissions", "tCO2e", "520"], ["Total waste generated", "MT", "40"]],
            periods=BOTH[:1], boundary=None)
    ready(gct)
    by = {s["unit_family"]: s["id"] for s in series(gct)}
    assert set(by) == {"tco2e", "tco2", "printed:a+b+c"}
    scope, waste = (ids(gct, c)[(label, "FY 2024-25")] for label in ("Total Scope 2 emissions", "Total waste generated"))
    assert [(i["claim"], i["reason"], i["series"]) for i in gct("match", "review", "--json").data["items"]] == [
        (scope, "boundary unknown", by["tco2e"])]
    assert states(db)[waste] == ("not matchable", "boundary unknown, no series to join", None)
    refused = gct("match", "link", scope, "--series", by["tco2"], *WHO)
    assert refused.code == 4 and "has no uncertain item for series" in refused.err


# AC 7
def test_review_links_unlinks_and_binds_to_the_claim_version(ws, db, gct, make_file, acme):
    a = add(gct, make_file, "a.pdf", [SCOPE_1])
    add(gct, make_file, "c.pdf", [SCOPE_1], boundary="consolidated")
    d = add(gct, make_file, "d.pdf", [["Total Scope 1 emissions", "tCO2e", "999"]], periods=("FY 2024-25",), boundary=None)
    ready(gct)
    claim = ids(gct, d)[("Total Scope 1 emissions", "FY 2024-25")]
    other = ids(gct, a)[("Total Scope 1 emissions", "FY 2024-25")]  # in the standalone series: no item
    standalone, consolidated = (next(s["id"] for s in series(gct) if s["reporting_boundary"] == b)
                                for b in ("standalone", "consolidated"))
    r = gct("match", "link", claim, "--series", standalone, *WHO, "--json")
    assert r.code == 0, r.out
    assert (r.data["match_state"], r.data["series_id"], r.data["by"]["contributor"], r.data["by"]["capacity"]) == (
        "reviewed", standalone, "Ana", "analyst")
    point = next(p for p in gct("series", "show", standalone, "--json").data["series"]["points"] if p["claim_id"] == claim)
    assert (point["link"], point["comparable"], point["reason"], point["review"]["contributor"]) == (
        "reviewed", False, "boundary unknown", "Ana")
    assert "reviewed, not comparable (boundary unknown) by Ana" in gct("series", "show", standalone).out
    assert gct("match", "review", "--json").data["items"] == []  # one series per claim: the other item left too
    again = gct("match", "link", claim, "--series", consolidated, *WHO)
    assert again.code == 4 and "already linked" in again.err and "gct match unlink" in again.err
    assert gct("match", "link", claim, "--series", standalone, *WHO).code == 4  # linking twice adds nothing
    assert gct("match", "unlink", claim, "--series", standalone, *WHO).code == 0
    assert [i["series"] for i in gct("match", "review", "--json").data["items"]] == [consolidated]
    assert gct("match", "unlink", claim, "--series", consolidated, *WHO).code == 0
    assert gct("match", "review", "--json").data["items"] == []
    assert states(db)[claim] == ("not matchable", "not linked by review", None)
    refused = gct("match", "link", other, "--series", standalone, *WHO)
    assert refused.code == 4 and "has no uncertain item for series" in refused.err
    assert gct("match", "link", claim, "--series", "000000000000", *WHO).code == 4
    gct("match", "link", claim, "--series", standalone, *WHO)
    assert gct("correct", claim, "--value", "998", *WHO).code == 0
    assert states(db)[claim] == ("not matchable", "not mapped yet: gct match", None)
    ready(gct)
    assert states(db)[claim] == ("uncertain", "boundary unknown", None)
    assert count(db, "match_review") == 4


# AC 8
def test_a_corrected_wording_is_mapped_again(ws, db, gct, make_file, acme):
    doc = add(gct, make_file, "a.pdf", [SCOPE_1[:3], ["Direct emissions (tCO2e)", "", "1,100"]], periods=BOTH[:1])
    ready(gct)
    claim = ids(gct, doc)[("Direct emissions (tCO2e)", "FY 2024-25")]
    old = db.execute("SELECT MAX(id) FROM claim_version WHERE claim_id = ?", (claim,)).fetchone()[0]
    assert db.execute("SELECT metric_key, unit_key FROM metric_assignment WHERE claim_version_id = ?", (old,)).fetchone()[:] == (
        None, "tco2e")
    assert gct("correct", claim, "--metric", "Total Scope 1 emissions", *WHO).code == 0
    ready(gct)
    new = db.execute("SELECT MAX(id) FROM claim_version WHERE claim_id = ?", (claim,)).fetchone()[0]
    assert db.execute("SELECT metric_key, rule FROM metric_assignment WHERE claim_version_id = ?", (new,)).fetchone()[:] == (
        "ghg_scope_1", "ghg_scope_1: scope 1")
    assert db.execute("SELECT COUNT(*) FROM metric_assignment WHERE claim_version_id = ?", (old,)).fetchone()[0] == 1
    (s,) = series(gct, "ghg_scope_1")
    shown = gct("series", "show", s["id"], "--json").data["series"]
    assert sorted(p["claim_id"] for p in shown["points"]) == [
        c["id"] for c in gct("claims", "list", "--doc", doc, "--json").data["claims"]]
    assert "same period: 2 values" in gct("series", "show", s["id"]).out


# AC 9
def test_rerun_is_cached(ws, db, gct, make_file, acme):
    add(gct, make_file, "a.pdf", [SCOPE_1])
    ready(gct)
    rows = count(db, "metric_assignment")
    (d,) = gct("match", "--json").data["documents"]
    assert (d["matched"], d["cached"], count(db, "metric_assignment")) == (0, 1, rows)


def two_docs(gct, make_file):
    first = add(gct, make_file, "a.pdf", [SCOPE_1])
    second = add(gct, make_file, "b.pdf", [ENERGY])
    for step in ("read", "extract"):
        gct(step)
    return first, second


def test_retry_only_the_failed_documents_of_a_match_run(ws, db, gct, make_file, acme, monkeypatch):
    first, second = two_docs(gct, make_file)
    real = match.assign

    def flaky(metric_text, unit_text):
        if "energy" in metric_text.lower():
            raise ValueError("boom")
        return real(metric_text, unit_text)

    monkeypatch.setattr(match, "assign", flaky)
    r = gct("match", "--json")
    assert r.code == 4 and r.data["status"] == "partial" and r.data["next_action"] == match.RETRY
    n = newest_run(db)
    monkeypatch.setattr(match, "assign", real)
    r = gct("run", "retry", n, "--json")
    assert r.code == 0 and (r.data["run_id"], r.data["of_run"]) == (n + 1, n)
    (d,) = r.data["documents"]
    assert (d["id"], d["matched"], d["failed"]) == (second, 1, 0)
    assert gct("run", "resume", n + 1).code == 4  # it finished
    assert gct("run", "retry", n, "--json").data["documents"] == []


def test_resume_an_interrupted_match(ws, db, gct, make_file, acme, monkeypatch):
    first, second = two_docs(gct, make_file)
    real = match.assign

    def stop(metric_text, unit_text):
        if "energy" in metric_text.lower():
            raise KeyboardInterrupt
        return real(metric_text, unit_text)

    monkeypatch.setattr(match, "assign", stop)
    with pytest.raises(KeyboardInterrupt):
        gct("match")
    n = newest_run(db)
    monkeypatch.setattr(match, "assign", real)
    r = gct("run", "resume", n, "--json")
    assert r.code == 0 and r.data["of_run"] == n
    assert [(d["id"], d["matched"], d["cached"]) for d in r.data["documents"]] == [(first, 0, 1), (second, 1, 0)]
    assert gct("run", "resume", n).out.splitlines()[0] == f"Run {n + 2} resumes run {n}."


# AC 10
def test_projection_schema_6(ws, db, gct, make_file, acme):
    a = add(gct, make_file, "a.pdf", [SCOPE_1, WASTE])
    add(gct, make_file, "d.pdf", [["Total Scope 1 emissions", "tCO2e", "999"]], periods=("FY 2024-25",), boundary=None)
    add(gct, make_file, "e.pdf", [["Total Scope 1 emissions", "tCO2e", "888"]], periods=("FY 2024-25",), fy=False)
    ready(gct)

    def build():
        v = gct("publish", "build", "--json").data
        conn = published.open_version(ws / "published" / f"v{v['version']}.db")
        try:
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            return (meta, [dict(r) for r in conn.execute("SELECT * FROM claim ORDER BY id")],
                    [dict(r) for r in conn.execute("SELECT * FROM series")],
                    [dict(r) for r in conn.execute("SELECT * FROM series_point ORDER BY series_id, period_end")])
        finally:
            conn.close()

    meta, claims, ss, points = build()
    assert meta["projection_schema"] == "16"
    assert {c["match_state"] for c in claims} == {"series", "uncertain"} and all(c["match_state"] for c in claims)
    scope = next(c for c in claims if c["document_id"] == a and c["period_label"] == "FY 2024-25" and c["unit_text"] == "tCO2e")
    assert (scope["metric_text"], scope["metric_key"], scope["metric_rule"], scope["unit_key"], scope["unit_factor"]) == (
        "Total Scope 1 emissions", "ghg_scope_1", "ghg_scope_1: scope 1", "tco2e", 1.0)
    assert {(s["metric_key"], s["unit_family"], s["periods"], s["latest_period_end"]) for s in ss} == {
        ("ghg_scope_1", "tco2e", 2, "2025-03-31"), ("waste_total", "printed:a+b+c", 2, "2025-03-31")}
    assert scope["series_id"] in {s["id"] for s in ss}
    p = next(p for p in points if p["claim_id"] == scope["id"])
    assert (p["value_text"], p["unit_text"], p["unit_key"], p["value_base"], p["link"], p["comparable"], p["reason"]) == (
        "1,234", "tCO2e", "tco2e", 1234.0, "rule", 1, None)
    uncertain = next(c for c in claims if c["match_state"] == "uncertain")
    assert (uncertain["series_id"], uncertain["match_reason"]) == (None, "boundary unknown")
    mark = published.history_mark(db)
    sid = next(s["id"] for s in ss if s["metric_key"] == "ghg_scope_1")
    assert gct("match", "link", uncertain["id"], "--series", sid, *WHO).code == 0
    assert published.history_mark(db) != mark
    _, claims, _, points = build()
    linked = next(p for p in points if p["claim_id"] == uncertain["id"])
    assert (linked["link"], linked["comparable"], linked["reason"], linked["value_base"]) == ("reviewed", 0, "boundary unknown", None)
    assert next(c for c in claims if c["id"] == uncertain["id"])["match_state"] == "reviewed"
    assert gct("publish", "restore").code == 0


# Story 4.6, metric list v3. A document phrase names the report and page it was read from (labels file of 2026-11-02:
# Tata Motors BRSR FY2024-25 = doc 1, Annual Report 2023-24 = 6, BRSR FY2023-24 = 7, Mahindra IAR 2024-25 = 8).
V3_LABELS = [
    ("permanent employees (d)", "employees_total"),  # doc 1 p3
    ("total employees (d+ e)", "employees_total"),  # doc 7 p2
    ("total workers (f +g)", "workers_total"),  # doc 1 p3; "(f+g)" in the story
    ("total workers (f+g)", "workers_total"),
    ("total employees (d+ e) male", "employees_male"),  # doc 1 p3, column-joined
    ("total employees (d+ e) female", "employees_female"),  # doc 1 p3, column-joined
    ("no. of fatalities", "fatalities"),  # doc 1 p45 (BRSR P3 Q11)
    ("total recordable work-related injuries", "recordable_injuries"),  # doc 1 p45
    ("board of directors total (a)", "board_size"),  # doc 8 p115
    ("audit fees", "auditor_fees"),  # doc 8 p110
    ("revenue from operations", "revenue_total"),  # doc 8 p45, doc 6 p217
    ("gross turnover", "revenue_total"),  # doc 8 p228
    ("turnover (in rs.)", "revenue_total"),  # BRSR Section A shape
    ("paid-up capital", "paid_up_capital"),  # doc 7 p1
    ("net worth", "net_worth"),  # doc 8 p141
    ("underlying ebitda", "ebitda"),  # doc 6 p217
    ("operating profit", "operating_income"),  # doc 6 p134
    ("profit before tax", "profit_before_tax"),  # doc 6 p217
    ("profit before taxation", "profit_before_tax"),  # doc 8 p45 (IAR 2024-25), decided 2026-11-02
    ("profit for the year", "net_income"),  # doc 6 p217
    ("total assets", "total_assets"),  # doc 6 p280
    ("(c) cash and cash equivalents", "cash_equivalents"),  # doc 6 p355
    ("(b) trade receivables", "accounts_receivable"),  # doc 6 p355
    ("inventories", "inventory"),  # doc 6 p282
    ("net cash from operating activities", "operating_cash_flow"),  # doc 6 p282
    ("dividend paid", "dividends_paid"),  # doc 6 p374
    ("r&d expenditure", "rd_expenditure"),  # doc 8 p178, a sentence: currency keys are not limited to table cells
    # Form wording, copied from the form text on 2026-11-02:
    # SEBI, Annexure I (BRSR format) to circular SEBI/HO/CFD/CMD-2/P/CIR/2021/562 of 10 May 2021, PDF page 9, Principle 1
    # Essential Indicator 2, monetary table, row "Penalty/ Fine", column "Amount (In INR)".
    ("Penalty/ Fine", "regulatory_fines"),
    # Companies (Corporate Social Responsibility Policy) Amendment Rules 2021, Gazette Part II Section 3(i), Annexure II
    # (format of the annual report on CSR activities), item 8 row (f) and the set-off table row (ii), pages 18 and 19.
    ("Total amount spent for the Financial Year", "community_investment"),
]
V3_UNMAPPED = [
    "turnover",  # doc 9 p225 and p233 print "turnover rate" 25 times: bare turnover is not a phrase
    "employee turnover rate", "voluntary turnover rate", "inventory turnover",
    "turnover rate for permanent employees and workers",  # doc 1 BRSR P3 Q3, a percent table
    "total equity and liabilities", "capital expenditure on r&d", "borrowings",
    "board meetings held",  # reserved
    "the board of directors held 7 meetings",
    "number of women on the board", "revenue per employee", "employees by region", "r&d investment",
    # Ind AS Schedule III Division II prints no "Total current assets", "Total current liabilities" or "Total equity" row
    # (ICAI Guidance Note on Division II, balance sheet format, pages 111 to 114): these keys are reserved.
    "total current assets", "total current liabilities", "total equity",
    "(i) low-carbon r&d investment", "total r&d expenditure (%)",
]


@pytest.mark.parametrize("label, key", V3_LABELS)
def test_metric_list_v3_maps_printed_labels(label, key):
    assert match.metric_of(label)[0] == key


@pytest.mark.parametrize("label", V3_UNMAPPED)
def test_metric_list_v3_leaves_these_unmapped(label):
    assert match.metric_of(label) == (None, None)


def test_metric_list_v3_edges():
    assert match.metric_of("Penalty/ Fine", "Amount (In INR)")[0] == "regulatory_fines"
    assert match.metric_of("total r&d expenditure", "%") == (None, None)  # the exclusion on the printed unit
    assert match.metric_of("scope 1 ghg inventory")[0] == "ghg_scope_1"  # "inventories" is not "inventory"
    assert match.metric_of("board of directors 9")[0] == "board_size"
    assert match.metric_of("profit before tax and net worth") == (None, "ambiguous")  # two v3 keys
    assert [match.metric_of(label)[0] for label in (  # BRSR 20(b) and the No. and % columns of one row
        "total employees (d+ e) differently abled", "permanent employees (d) male", "board of directors female")] == [None] * 3


# AC 3 (D1): counts
CELL, SENTENCE = "t1r2c3", "p1s1"


@pytest.mark.parametrize("label, unit, locator, expected", [
    ("permanent employees (d)", None, CELL, ("count", 1.0, "key")),
    ("permanent employees (d)", "  ", CELL, ("count", 1.0, "key")),
    ("permanent employees (d)", "nos.", CELL, ("count", 1.0, "unit")),
    ("permanent employees (d)", "Persons", CELL, ("count", 1.0, "unit")),
    ("permanent employees (d)", "A+B+C", CELL, (None, None, None)),
    ("permanent employees (d)", "FY 2024-25", CELL, (None, None, None)),
    ("permanent employees (d)", "No. (B)", CELL, (None, None, None)),
    ("permanent employees (d)", "ML", CELL, (None, None, None)),
    ("permanent employees (d)", "tco2e", CELL, ("tco2e", 1.0, "unit")),
    ("permanent employees (d)", None, SENTENCE, (None, None, None)),
    ("permanent employees (d)", None, None, (None, None, None)),
    ("board of directors 9", None, SENTENCE, (None, None, None)),
    ("ghg scope 1", None, CELL, (None, None, None)),
    ("number of employees", None, CELL, (None, None, None)),
    ("scope 1 emissions from vehicles", None, CELL, (None, None, None)),
    ("total energy consumed by employees", None, CELL, (None, None, None)),
    ("permanent employees (d) (tco2e)", None, CELL, ("tco2e", 1.0, "label")),
])
def test_counts_take_a_family_from_the_key_only_in_a_table_cell(label, unit, locator, expected):
    assert match.assign(label, unit, locator)[2:] == expected


def test_a_percent_count_is_unmapped_and_count_words_stay_out_of_the_unit_table():
    assert match.assign("permanent employees (d)", "%", CELL)[:2] == (None, None)
    assert match.assign("permanent employees (d)", "nos.")[2:] == (None, None, None)  # no locator: not a table cell
    assert not match.COUNT_UNITS & set(match.UNITS) and not set(match.CURRENCY_UNITS) & set(match.UNITS)
    assert match.unit_of("nos.", "permanent employees (d)") == (None, None, None)  # unit_of is unchanged


def test_a_count_figure_with_another_family_is_not_convertible(ws, db, gct, make_file, acme):
    row = "Permanent employees (D)"
    add(gct, make_file, "a.pdf", [[row, "", "8,616", "7,982"]])
    b = add(gct, make_file, "b.pdf", [[row, "tCO2e", "5"]], periods=("FY 2024-25",))
    ready(gct)
    (s,) = series(gct, "employees_total")
    assert (s["unit_family"], s["periods"]) == ("count", 2)
    assert states(db)[ids(gct, b)[(row, "FY 2024-25")]][:2] == ("uncertain", "unit not convertible")


# AC 4 (D2): currency
@pytest.mark.parametrize("unit, label, expected", [
    ("INR crore", None, ("inr", 1e7, "unit")), ("₹ crore", None, ("inr", 1e7, "unit")),
    ("Rs. crores", None, ("inr", 1e7, "unit")), ("INR lakh", None, ("inr", 1e5, "unit")),
    ("EUR million", None, ("eur", 1e6, "unit")), ("GBP billion", None, ("gbp", 1e9, "unit")),
    ("USD", None, ("usd", 1.0, "unit")), ("$ mn", None, ("usd", 1e6, "unit")), ("€ bn", None, ("eur", 1e9, "unit")),
    ("in Rs. lakhs", None, ("inr", 1e5, "unit")),
    (None, "turnover (€ million)", ("eur", 1e6, "label")),
    (None, "turnover (in rs.)", ("inr", 1.0, "label")),
    ("in crores", None, (None, None, None)), ("million", None, (None, None, None)),
    ("in crores", "turnover (in rs.)", (None, None, None)),  # the label is not read
    ("MtCO2e", None, (None, None, None)), ("mn", None, (None, None, None)),
])
def test_currency_units(unit, label, expected):
    assert match.unit_of(unit, label) == expected


def test_currency_words_are_not_in_the_unit_table_and_every_family_is_listed():
    assert all(f in match.FAMILIES for f, _ in {**match.UNITS, **match.CURRENCY_UNITS}.values())
    assert "count" in match.FAMILIES and set(match.CURRENCIES) <= set(match.FAMILIES)
    assert not set(match.CURRENCY_UNITS) & set(match.UNITS) and "m" not in match.PREFIXES


# AC 6
RESERVED_COUNT = {"employees_other", "board_meetings_held", "shareholder_complaints", "regulatory_violations",
                  "supplier_count", "active_customers", "new_customers_acquired", "fulfillment_centers",
                  "production_capacity"}  # the count rows of the v3 table in the story
RESERVED_CURRENCY = {"ceo_salary", "ceo_bonus", "ceo_stock_options", "gross_profit", "current_assets",
                     "current_liabilities", "total_debt", "shareholders_equity", "free_cash_flow", "capital_expenditure"}


def reserved_in_docs() -> set:
    text = (Path(__file__).parent.parent / "docs" / "matching.md").read_text()
    section = text.split("## Reserved keys", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^- `(\w+)`", section, re.M))


def test_accepts_is_complete_and_reserved_keys_are_the_documented_ones():
    mapped = {k for k, _, _ in match.METRICS}
    assert mapped <= set(match.ACCEPTS) and match.COUNT_KEYS <= mapped
    reserved = set(match.ACCEPTS) - mapped
    assert reserved == RESERVED_COUNT | RESERVED_CURRENCY == reserved_in_docs()
    counts = {k for k, f in match.ACCEPTS.items() if f == ("count",)}
    currency = {k for k, f in match.ACCEPTS.items() if f == match.CURRENCIES}
    assert (len(counts), len(currency), len(match.ACCEPTS) - len(counts) - len(currency)) == (16, 27, 13)
    assert RESERVED_COUNT <= counts and RESERVED_CURRENCY <= currency and match.COUNT_KEYS <= counts


def test_no_reserved_key_is_ever_assigned_a_phrase():
    reserved = set(match.ACCEPTS) - {k for k, _, _ in match.METRICS}
    for label in ("total current assets", "total current liabilities", "total equity", "total debt", "ceo salary",
                  "free cash flow", "gross profit", "capital expenditure", "supplier count", "fulfillment centers"):
        assert match.metric_of(label)[0] not in reserved


# AC 7: the extractor reads match.UNITS and unit_text_of, so the new words must not change what it returns.
# Pasted from b2838b3: (text, _is_unit_cell(text), _extract_unit(text), _extract_unit(f"Scope 1 ({text})")).
EXTRACT_AT_BASE = [
    ("tCO2e", True, None, "tCO2e"), ("GJ", True, None, "GJ"), ("Nos.", True, None, "Nos."),
    ("employees", False, None, None), ("INR crore", True, None, "INR crore"), ("₹", True, None, "₹"),
    ("A+B+C", False, None, None), ("FY 2024-25", False, None, None), ("persons", False, None, None),
    ("$", False, None, None), ("Rs. crores", True, None, "Rs. crores"), ("€ million", False, None, None),
    ("mn", False, None, None), ("crores", True, None, "crores"),
]


@pytest.mark.parametrize("text, is_unit, bare, in_brackets", EXTRACT_AT_BASE)
def test_the_extractor_answers_as_before(text, is_unit, bare, in_brackets):
    assert (extract._is_unit_cell(text), extract._extract_unit(text), extract._extract_unit(f"Scope 1 ({text})")) == (
        is_unit, bare, in_brackets)


# AC 8
def test_versions_and_reassignment(ws, db, gct, make_file, acme, monkeypatch):
    assert (match.METRICS_VERSION, match.UNITS_VERSION, match.RULES_VERSION) == (4, 2, 4)
    add(gct, make_file, "a.pdf", [["Permanent employees (D)", "", "8,616", "7,982"]])
    real = match.CONFIG
    monkeypatch.setattr(match, "CONFIG", "match-before")
    ready(gct)
    before = count(db, "metric_assignment")
    assert before > 0
    monkeypatch.setattr(match, "CONFIG", real)
    (d,) = gct("match", "--json").data["documents"]
    assert (d["matched"], count(db, "metric_assignment")) == (1, 2 * before)  # every claim once; earlier rows stay
    (d,) = gct("match", "--json").data["documents"]
    assert (d["matched"], d["cached"], count(db, "metric_assignment")) == (0, 1, 2 * before)


# AC 1
def test_migration_23_keeps_the_rows_and_accepts_the_key_source(tmp_path):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    store.migrate(c, up_to=22)
    c.execute("PRAGMA foreign_keys = OFF")  # the rows below stand alone; a missing parent must not pass for the CHECK
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.execute("INSERT INTO metric_assignment (claim_version_id, metric_key, unit_source, run_id, config_version, created_at)"
              " VALUES (1, 'ghg_scope_1', 'label', 1, 'c', 't')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO metric_assignment (claim_version_id, unit_source, run_id, config_version, created_at)"
                  " VALUES (1, 'key', 1, 'c', 't')")
    assert store.migrate(c) == [23]
    c.execute("PRAGMA foreign_keys = OFF")  # migrate turns it back on
    assert [tuple(r) for r in c.execute("SELECT id, metric_key, unit_source FROM metric_assignment")] == [
        (1, "ghg_scope_1", "label")]
    c.execute("INSERT INTO metric_assignment (claim_version_id, unit_source, run_id, config_version, created_at)"
              " VALUES (2, 'key', 1, 'c', 't')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO metric_assignment (claim_version_id, unit_source, run_id, config_version, created_at)"
                  " VALUES (3, 'other', 1, 'c', 't')")
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE tbl_name = 'metric_assignment'")}
    assert {"metric_assignment_by_version", "metric_assignment_no_update", "metric_assignment_no_delete"} <= names
    for stmt in ("UPDATE metric_assignment SET id = id", "DELETE FROM metric_assignment"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
            c.execute(stmt)
    c.close()


# AC 5
def test_a_brsr_employee_table_without_a_unit_is_one_count_series(ws, db, gct, make_file, acme):
    add(gct, make_file, "a.pdf", [["Permanent employees (D)", "", "8,616", "7,982"]])
    ready(gct)
    (s,) = series(gct, "employees_total")
    assert (s["unit_family"], s["periods"], s["reporting_boundary"]) == ("count", 2, "standalone")
    pts = gct("series", "show", s["id"], "--all", "--json").data["series"]["points"]
    assert [(p["value_text"], p["unit_text"], p["unit_key"], p["value_base"], p["link"], p["comparable"]) for p in pts] == [
        ("7,982", None, "count", 7982.0, "rule", True), ("8,616", None, "count", 8616.0, "rule", True)]


def test_revenue_in_one_currency_joins_across_reports_and_another_currency_does_not(ws, db, gct, make_file, acme):
    row = "Revenue from operations"
    a = add(gct, make_file, "a.pdf", [[row, "INR crore", "98,763.42", "90,000.5"]])
    b = add(gct, make_file, "b.pdf", [[row, "INR crore", "89,500"]], periods=("FY 2023-24",))
    c = add(gct, make_file, "c.pdf", [[row, "EUR mn", "1,200"]], periods=("FY 2024-25",))  # "EUR million" wraps in the 60-point cell
    ready(gct)
    ss = {s["unit_family"]: s for s in series(gct, "revenue_total")}
    assert set(ss) == {"inr", "eur"}
    assert (ss["inr"]["periods"], ss["inr"]["same_period_sets"]) == (2, 1)
    shown = gct("series", "show", ss["inr"]["id"], "--all", "--json").data["series"]["points"]
    assert sorted((p["value_text"], p["document_id"], p["value_base"], p["same_period"]) for p in shown) == [
        ("89,500", b, 8.95e11, 2), ("90,000.5", a, 9.00005e11, 2), ("98,763.42", a, 9.876342e11, 1)]
    (e,) = gct("series", "show", ss["eur"]["id"], "--all", "--json").data["series"]["points"]
    assert (e["document_id"], e["unit_key"], e["value_base"]) == (c, "eur", 1.2e9)
    assert gct("match", "review", "--json").data["items"] == []  # neither currency is a candidate of the other
    assert not {st[1] for st in states(db).values()} & {"unit not convertible", "unit unknown"}


# AC 12
def test_a_review_and_a_restatement_recorded_before_the_upgrade_survive_it(ws, db, gct, make_file, acme, monkeypatch):
    from gct.stages import restate
    note = [(40, 150, "The figures for the previous year have been restated due to reclassification.")]
    row = "Permanent employees (D)"
    real, config = match.assign, match.CONFIG

    def v2(metric_text, unit_text, locator=None):  # the build before 4.6: no family from the key alone
        out = real(metric_text, unit_text, locator)
        return (*out[:2], None, None, None) if out[4] == "key" else out

    monkeypatch.setattr(match, "assign", v2)
    monkeypatch.setattr(match, "CONFIG", "match-v2")
    a = add(gct, make_file, "a.pdf", [[row, "", "8,700"]], periods=("FY 2024-25",))  # no printed unit
    b = add(gct, make_file, "b.pdf", [[row, "Nos.", "8,616", "7,982"]])
    c = add(gct, make_file, "c.pdf", [[row, "Nos.", "8,000"]], periods=("FY 2023-24",), lines=note)
    ready(gct)
    claim_a = ids(gct, a)[(row, "FY 2024-25")]
    assert states(db)[claim_a][:2] == ("uncertain", "unit unknown")
    (item,) = [i for i in gct("match", "review", "--json").data["items"] if i["claim"] == claim_a]
    assert gct("match", "link", claim_a, "--series", item["series"], *WHO).code == 0
    original, restated = ids(gct, b)[(row, "FY 2023-24")], ids(gct, c)[(row, "FY 2023-24")]
    assert gct("restate", "record", "--original", original, "--restated", restated, "--page", 1,
               "--quote", "The figures for the previous year have been restated", *WHO).code == 0
    reviews = [tuple(r) for r in db.execute("SELECT * FROM match_review")]
    restatements = [tuple(r) for r in db.execute("SELECT * FROM restatement")]
    assert len(reviews) == len(restatements) == 1

    monkeypatch.setattr(match, "assign", real)
    monkeypatch.setattr(match, "CONFIG", config)
    assert gct("match", "--json").code == 0
    assert [tuple(r) for r in db.execute("SELECT * FROM match_review")] == reviews
    assert [tuple(r) for r in db.execute("SELECT * FROM restatement")] == restatements
    assert states(db)[claim_a][0] in ("series", "reviewed") and states(db)[claim_a][1] is None
    assert not [i for i in gct("match", "review", "--json").data["items"] if i["claim"] == claim_a]
    (s,) = series(gct, "employees_total")
    assert s["unit_family"] == "count" and s["id"] == item["series"]
    claim_pair = gct("restate", "list", "--json").data["pairs"]
    assert [p["state"] for p in claim_pair if {p["a"]["claim_id"], p["b"]["claim_id"]} == {original, restated}] == ["restatement"]
    rows = db.execute("SELECT unit_key, unit_source, config_version FROM metric_assignment WHERE claim_version_id ="
                      " (SELECT MAX(id) FROM claim_version WHERE claim_id = ?) ORDER BY id", (claim_a,)).fetchall()
    assert [tuple(r) for r in rows] == [(None, None, "match-v2"), ("count", "key", match.CONFIG)]


# Correction 1: the current extraction joins the column header before the row label (hand run, 2026-11-02)
@pytest.mark.parametrize("label, key", [
    ("Male Total Employees (D+ E)", "employees_male"),  # Tata BRSR FY2024-25 doc 1 p3; BRSR FY2023-24 doc 7 p2, cell t2r5c3
    ("Female Total Employees (D+ E)", "employees_female"),  # doc 1 p3; doc 7 p2, cell t2r5c5
])
def test_employees_by_gender_in_the_current_extraction(label, key):
    assert match.metric_of(label)[0] == key


def test_gender_rows_do_not_cross_or_take_the_differently_abled_table():
    assert match.metric_of("(iii) Employees and workers (including differently abled) of TML, TMPVL and TPEML: "
                           "Male Total Employees (D+ E)") == (None, None)  # BRSR 20(b), doc 1 p4 and p5
    assert match.metric_of("Female Total Employees (D+ E) differently abled") == (None, None)
    assert match.metric_of("Female Total Employees (D+ E)")[0] == "employees_female"  # not ambiguous with male
    assert match.metric_of("Total Employees (D+ E)")[0] == "employees_total"
    assert match.metric_of("Male Total Employees (D+ E)")[1] == "employees_male: male total employees (d+ e)"
