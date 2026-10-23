"""Story 7.2: gct report NAME --format json, the export folder, the format table and the published dataset schema, on
tests/report_fixture.py (section G). read_back(path) and printed(value, row, key, fmt) are the JSON format's part of
the shared read-back contract (C4b, readiness resolution 3 as amended) that story 7.7 calls for every format."""
import ast
import copy
import hashlib
import json
import shutil
import sqlite3
import sys
import tomllib
import types
from importlib import resources
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import gct.reports
import report_fixture as f
from leakage import found
from test_gate_privacy_exports import build, env, w  # noqa: F401 (module fixtures: the fixture and its environment)
from test_gate_tables_graphs import FILTERS
from test_view import dump
from gct import cli
from gct.reports import dataset, export, pin
from gct.stages import adjudicate, correct, match, missing, restate, review, view
from gct.workspace import labels, layout, lock, store

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_BYTES = resources.files("gct.reports").joinpath("dataset-1.schema.json").read_bytes()
SCHEMA = json.loads(SCHEMA_BYTES)
VALIDATOR = Draft202012Validator(SCHEMA)
WHO = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked on the page")
# 7.1 C3 and C7, written out here (not taken from dataset.WITHHELD): per row kind, the W keys each class restores.
W = {
    "evidence_index": {"contributor_text": {"correction.contributor", "correction.organisation", "correction.capacity",
                                            "correction.rationale"}},
    "records": {"identity": {"organisation", "capacity"},
                "contributor_text": {"scope", "conclusion", "evidence_note", "note", "rationale"}},
    "restatements": {"identity": {"organisation", "capacity"}, "contributor_text": {"rationale"}},
    "adjudications": {"identity": {"organisation", "capacity"},
                      "contributor_text": {"counter_note", "rationale", "procedure", "follow_up", "closure_reason"}},
    "expectations": {"identity": {"confirmation.organisation", "confirmation.capacity"},
                     "contributor_text": {"confirmation.rationale"}},
}
W["related_claims"], W["unpaired_restatements"] = W["evidence_index"], W["restatements"]
SUBS = ("records", "disagreements", "restatements", "adjudications", "reasons", "accepted", "declared")
SECTIONS = ("candidates", "expectations", "documents_checked", "extraction_limits", "archived", "deleted")


# The read-back contract (C4b)

def dotted(row, key):
    """A row value by its columns key: a dotted key walks the object (null when the object is null); outside_selection's
    a and b are its two items."""
    value = row
    for part in key.split("."):
        if value is None:
            return None
        value = value[{"a": 0, "b": 1}[part]] if isinstance(value, list) else value[part]
    return value


def read_back(path) -> dict:
    """{data_version: the file's data_version as the mode holds it, rows: {table: [{columns key: value}]}} of an export
    folder: evidence_index, restatement_log (pair rows only) and gap_report.<section> for each section the file holds.
    JSON prints each value as itself, so the values are the parsed JSON values."""
    d = json.loads((Path(path) / "dataset.json").read_text(encoding="utf-8"))
    tables = {"evidence_index": ("evidence_index", d["evidence_index"]),
              "restatement_log": ("restatement_log", d["restatement_log"]),
              **{f"gap_report.{s}": (s, rows) for s, rows in d["gap_report"].items()}}
    return {"data_version": d["data_version"],
            "rows": {t: [{c["key"]: dotted(r, c["key"]) for c in d["columns"][cols]} for r in rows]
                     for t, (cols, rows) in tables.items()}}


def printed(value, row, key, fmt):
    """How the JSON format prints a dataset value: as itself (the identity), whatever the type."""
    return value


# Helpers

def rows_of(d):
    """(table, row) for every report, list and sub-table row of a dataset, related claims and documents included."""
    out = []
    lists = [("documents", d["documents"]), ("evidence_index", d["evidence_index"]),
             ("related_claims", d["related_claims"]), ("restatement_log", d["restatement_log"]),
             ("unpaired_restatements", d["unpaired_restatements"]["rows"]),
             *((s, d["gap_report"][s]) for s in SECTIONS)]
    for t, rows in lists:
        for r in rows:
            out.append((t, r))
            out += [(k, x) for k in SUBS if k in r for x in r[k]["rows"]]
    return out


def withheld_problems(d) -> list:
    """What the schema cannot carry (it depends on mode and include): every key named in withheld is null, and in
    sanitised mode each row's withheld holds exactly the W keys of its kind that no include class restores."""
    out = []
    for t, r in rows_of(d):
        for k in r["withheld"]:
            if dotted(r, k) is not None:
                out.append(f"{t} {r['id']}: {k} is withheld but not null")
        want = set() if d["mode"] == "complete" else {
            k for cls, keys in W.get(t, {}).items() if cls not in d["include"] for k in keys}
        if set(r["withheld"]) != want:
            out.append(f"{t} {r['id']}: withheld {sorted(r['withheld'])}, expected {sorted(want)}")
    return out


def errors(d) -> list:
    return [f"{list(e.absolute_path)}: {e.message[:120]}" for e in VALIDATOR.iter_errors(d)]


def no_constant(name):
    raise ValueError(f"non-finite number {name}")


def check(folder: Path) -> dict:
    """Every check one JSON export must pass (sections G and AC 4 to 6). Returns the parsed file."""
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")) == ["dataset-1.schema.json",
                                                                                     "dataset.json"]
    assert (folder / "dataset-1.schema.json").read_bytes() == SCHEMA_BYTES
    raw = (folder / "dataset.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and raw.endswith(b"}\n")
    d = json.loads(raw.decode("utf-8"), parse_constant=no_constant)
    # ensure_ascii=False, indent=1, allow_nan=False, the dataset's own key order, one final newline
    assert raw == (json.dumps(d, ensure_ascii=False, indent=1, allow_nan=False) + "\n").encode("utf-8")
    assert errors(d) == []
    assert withheld_problems(d) == []
    v = d["data_version"]["version"]
    assert {r["data_version"] for _, r in rows_of(d)} <= {v}  # K15
    assert folder.name.startswith(f"-v{v}-".join(folder.name.split(f"-v{v}-")[:1]) + f"-v{v}-")
    assert folder.name.endswith(f"-{d['mode']}") and folder.parent.name == "exports"
    return d


def export_(gct, root, *argv, name="all", fmt="json"):
    r = gct("report", name, "--format", fmt, *argv, "--workspace", root, "--json")
    assert r.code == 0, r.out
    return r.data, Path(r.data["folder"])


def listing(root) -> list:
    return sorted(p.relative_to(root).as_posix() for p in (root / "exports").rglob("*"))


def files(folder) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


@pytest.fixture
def ws(w, env, tmp_path):
    """A copy of the fixture workspace for a test that writes."""
    return Path(shutil.copytree(w, tmp_path / "ws"))


def report_runs(root) -> list:
    with sqlite3.connect(root / layout.DB_NAME) as c:
        return c.execute("SELECT r.id, r.command, e.kind, e.stage, e.item, e.message, e.outcome FROM run r"
                         " JOIN run_event e ON e.run_id = r.id WHERE r.command = 'report' ORDER BY e.id").fetchall()


# The schema (AC 6, 13)

def test_the_schema_is_a_described_draft_2020_12_schema_that_ships():
    Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert SCHEMA["$id"] == "urn:gct:dataset-schema:1" and SCHEMA["title"] and SCHEMA["description"]
    missing_ = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.get("properties", {}).items():
                if not (isinstance(v, dict) and v.get("description")):
                    missing_.append(f"{path}/properties/{k}")
            for k, v in node.items():
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}/{i}")

    walk(SCHEMA, "")
    assert missing_ == []
    package_data = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]
    assert package_data["gct.reports"] == ["*.schema.json"]
    assert f"dataset-{dataset.DATASET_SCHEMA}.schema.json" in [p.name for p in resources.files("gct.reports").iterdir()]


def test_the_schema_enums_equal_the_code_constants():
    d = SCHEMA["$defs"]
    assert d["claim_state"]["enum"] == list(correct.STATES.values())
    assert d["missing_state"]["enum"] == [missing.INCOMPLETE, missing.NOT_FOUND_IN, missing.CONFIRMED]
    assert d["pair_state"]["enum"] == list(restate.STATES)
    assert d["adjudication_state"]["enum"] == list(adjudicate.STATES.values())
    assert d["shown_state"]["enum"] == [*adjudicate.STATES.values(), adjudicate.UNREVIEWED]
    assert d["outcome"]["enum"] == list(review.OUTCOMES)
    assert d["record_kind"]["enum"] == [*(v[1] for v in review.LEDGERS.values()), "reviewer flag", "highlight"]
    assert d["record_kind"]["enum"] == list(dataset.LEDGER_KINDS.values())
    assert d["match_state"]["enum"] == list(match.STATES)
    assert d["label"]["enum"] == sorted(labels.PRIVACY)
    assert d["documents"]["properties"]["availability"]["enum"] == list(labels.AVAILABILITY)
    assert d["extraction_limits"]["properties"]["type"]["enum"] == list(missing.TYPES)
    assert SCHEMA["properties"]["dataset_schema"]["const"] == dataset.DATASET_SCHEMA
    assert SCHEMA["properties"]["mode"]["enum"] == list(dataset.MODES)
    assert SCHEMA["properties"]["include"]["items"]["enum"] == list(dataset.INCLUDE)
    assert list(SCHEMA["properties"]["columns"]["properties"]) == list(dataset.COLUMNS)
    for name in ("filter_complete", "filter_sanitised"):
        props = d[name]["properties"]
        assert [k for k in props if k != "withheld"] == list(view.FIELDS)
        for field, values in view.CHOICES.items():
            if values is not None:
                assert props[field]["items"]["enum"] == list(values), (name, field)
    for table, parent in dataset.SUB_TABLES.items():
        sub = d[f"{table}_table"]["properties"]
        assert sub["title"]["const"] == dataset.TITLES[table]
        assert sub["parent_key"].get("const") == parent
    for table, keys in dataset._KEYS.items():  # every printed column key is a row key of the schema
        props = d[table]["properties"]
        assert {k.split(".")[0] for k in keys} <= set(props), table


def test_gct_never_imports_jsonschema():
    for p in (ROOT / "gct").rglob("*.py"):
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                assert not [a for a in n.names if a.name.split(".")[0] == "jsonschema"], p
            if isinstance(n, ast.ImportFrom):
                assert (n.module or "").split(".")[0] != "jsonschema", p


# Section G: every export validates (the id story 7.7 cites)

def test_every_export_validates(ws, gct):
    names = sorted(export.REPORTS)
    configs = [(), ("--complete",), *(("--include", c) for c in dataset.INCLUDE),
               ("--include", ",".join(dataset.INCLUDE)), ("--filter", "{}"),
               ("--filter", json.dumps({"text": "nothing matches this"})),
               ("--filter", json.dumps({"text": f.METRIC, "document": [8, 1]})),
               *(("--filter", json.dumps(x)) for x in FILTERS),
               *(("--complete", "--filter", json.dumps(x)) for x in FILTERS)]
    seen = {}
    for argv in configs:
        d = check(export_(gct, ws, *argv)[1])
        seen.setdefault(d["mode"], []).append(d)
    by_name = []
    for name in names:
        data, folder = export_(gct, ws, name=name)
        assert folder.name.startswith(f"{name}-v")
        by_name.append(check(folder))
    assert all(x == by_name[0] for x in by_name)  # one dataset whatever NAME is (built_at fixed by the fixture)
    # the fixture reaches the cases the schema distinguishes
    flat = [(t, r) for ds in seen.values() for d in ds for t, r in rows_of(d)]
    assert {t for t, _ in flat} >= {"records", "restatements", "adjudications", "unpaired_restatements", "expectations",
                                    "reasons", "declared", "documents_checked", "extraction_limits", "archived",
                                    "deleted", "candidates", "disagreements"}
    kinds = {e["sheet"] is None for ds in seen.values() for d in ds for e in d["evidence"]}
    assert kinds == {True, False}
    assert any(isinstance(r["series_id"], str) for t, r in flat if t == "restatement_log")
    assert any(d["filter"].get("series") for ds in seen.values() for d in ds)
    assert any(r["withheld"] for t, r in flat if t == "records")


def test_evidence_entries_match_exactly_one_branch(w, env, gct, tmp_path):
    d = json.loads((export_(gct, Path(shutil.copytree(w, tmp_path / "c")), "--complete")[1] / "dataset.json")
                   .read_text())
    page, cell = (next(e for e in d["evidence"] if (e["sheet"] is None) == p) for p in (True, False))
    branches = [{"$defs": SCHEMA["$defs"], "$ref": f"#/$defs/{b}"} for b in ("evidence_page", "evidence_cell")]
    for e in d["evidence"]:
        assert sum(Draft202012Validator(b).is_valid(e) for b in branches) == 1, e
    for entry, mutate in ((cell, {"page": 1}), (page, {"sheet": "Sheet1", "cell": "B2"}), (page, {"page": None}),
                          (cell, {"boxes": [[0, 0, 1, 1]]}), (page, {"marked": 0})):
        bad = copy.deepcopy(d)
        next(e for e in bad["evidence"] if e["id"] == entry["id"]).update(mutate)
        assert errors(bad), mutate


# AC 6: every planted mutation fails

def mutations():
    def first(t):
        return lambda d: next(r for x, r in rows_of(d) if x == t)

    def row_of(t, cond):
        return lambda d: next(r for x, r in rows_of(d) if x == t and cond(r))

    company = row_of("records", lambda r: r["kind"] == "company confirmation")
    return {
        "extra top-level key": ("sanitised", lambda d: d.update(extra=1)),
        "extra key on an evidence index row": ("sanitised", lambda d: d["evidence_index"][0].update(extra=1)),
        "data_version removed": ("complete", lambda d: d.pop("data_version")),
        "history_mark in a sanitised data_version": ("sanitised", lambda d: d["data_version"].update(
            history_mark="1.2")),
        "labels_mark in a sanitised data_version": ("sanitised", lambda d: d["data_version"].update(labels_mark=1)),
        "complete data_version without history_mark": ("complete", lambda d: d["data_version"].pop("history_mark")),
        "a row without its data_version": ("sanitised", lambda d: first("records")(d).pop("data_version")),
        "matched in a sanitised dataset": ("sanitised", lambda d: d.update(matched=3)),
        "hidden_by_archive in a sanitised gap report": ("sanitised", lambda d: d["gap_report"].update(
            hidden_by_archive=[])),
        "an archived row in a sanitised gap report": ("sanitised", lambda d: d["gap_report"]["archived"].append(
            copy.deepcopy(d["gap_report"]["documents_checked"][0]))),
        "a label column in sanitised columns": ("sanitised", lambda d: d["columns"]["documents"].append(
            {"key": "label", "heading": "Label", "complete_only": True})),
        "a sanitised filter with text null and no withheld": ("sanitised", lambda d: d.update(filter={"text": None})),
        "a sanitised filter with its text": ("sanitised", lambda d: d.update(filter={"text": "x", "withheld": ["text"]})),
        "withheld on a complete filter": ("complete", lambda d: d.update(filter={"text": "x", "withheld": ["text"]})),
        "label public": ("complete", lambda d: d["documents"][0].update(label="public")),
        "an adjudication state_text not in adjudicate.STATES": ("complete", lambda d: first("adjudications")(d).update(
            state_text="reviewer_confirmed_issue")),
        "dataset_schema 2": ("sanitised", lambda d: d.update(dataset_schema=2)),
        "a 63-character sha256": ("sanitised", lambda d: d["data_version"].update(sha256="a" * 63)),
        "an evidence sha256 in capitals": ("sanitised", lambda d: d["evidence"][0].update(sha256="A" * 64)),
        "a built_at without +00:00": ("sanitised", lambda d: d.update(built_at="2026-10-23T00:00:00")),
        "a company confirmation's conclusion null without it in withheld": ("sanitised", lambda d: company(d).update(
            withheld=[k for k in company(d)["withheld"] if k != "conclusion"])),
        "a complete company confirmation's conclusion null": ("complete", lambda d: company(d).update(conclusion=None)),
        "a complete restatement's capacity null": ("complete", lambda d: first("restatements")(d).update(
            capacity=None)),
        "an integer series_id": ("sanitised", lambda d: d["restatement_log"][0].update(series_id=5)),
        "an integer in filter.series": ("complete", lambda d: d.update(filter={"series": [5]})),
        "an empty string in filter.series": ("sanitised", lambda d: d.update(filter={"series": [""]})),
        "a claim state not in correct.STATES": ("sanitised", lambda d: d["evidence_index"][0].update(
            claim_state="not-found")),
        "a missing state merged": ("complete", lambda d: first("expectations")(d).update(state="missing")),
        "a pair state code": ("sanitised", lambda d: d["restatement_log"][0].update(state="same")),
        "a projection_schema of 14": ("sanitised", lambda d: d["data_version"].update(projection_schema=14)),
        "a version 0": ("sanitised", lambda d: d["data_version"].update(version=0)),
        "a document id as a string": ("sanitised", lambda d: d["evidence_index"][0].update(document_id="1")),
        "an unknown inclusion class": ("sanitised", lambda d: d.update(include=["names"])),
        "a sub-table without columns": ("sanitised", lambda d: d["evidence_index"][0]["records"].pop("columns")),
        "a non-finite-shaped value": ("sanitised", lambda d: d["evidence_index"][0].update(value="Infinity")),
    }


@pytest.fixture(scope="module")
def exports_(w, env, tmp_path_factory):
    """One sanitised and one complete export of a copy of the fixture, parsed."""
    root = Path(shutil.copytree(w, tmp_path_factory.mktemp("m") / "ws"))
    out = {}
    for mode, argv in (("sanitised", []), ("complete", ["--complete"])):
        assert cli.main(["report", "all", "--format", "json", *argv, "--workspace", str(root)]) == 0
    for folder in (root / "exports").iterdir():
        d = json.loads((folder / "dataset.json").read_text())
        out[d["mode"]] = d
    return out


@pytest.mark.parametrize("name", list(mutations()))
def test_the_schema_refuses_each_planted_mutation(exports_, name):
    mode, mutate = mutations()[name]
    d = copy.deepcopy(exports_[mode])
    assert errors(d) == []
    mutate(d)
    assert errors(d), name


def test_the_withheld_checks_refuse_what_the_schema_cannot_see(exports_):
    d = exports_["sanitised"]
    assert withheld_problems(d) == []
    bad = copy.deepcopy(d)
    r = next(r for t, r in rows_of(bad) if t == "records" and "scope" in r["withheld"])
    r["scope"] = "a value"  # listed in withheld, but a string
    assert withheld_problems(bad) and not errors(bad)
    bad = copy.deepcopy(d)
    r = next(r for t, r in rows_of(bad) if t == "records" and r["kind"] == "highlight")
    assert r["evidence_note"] is None  # stored null on a highlight
    r["withheld"].remove("evidence_note")
    assert withheld_problems(bad) and not errors(bad)
    bad = copy.deepcopy(d)  # organisation (nullable in storage): withheld in sanitised mode, stored null included
    r = next(r for t, r in rows_of(bad) if t == "records")
    r["withheld"].remove("organisation")
    assert withheld_problems(bad) and not errors(bad)


# AC 1, 3, 4, 5: the command, the run and the file

def test_an_export_writes_one_folder_one_run_and_the_dataset_itself(ws, gct):
    before = dump(ws)
    published_before = {p.name: p.read_bytes() for p in (ws / "published").iterdir()}
    (ws / "exports" / "mine.csv").write_text("a user's own file\n")
    r = gct("report", "all", "--format", "json,json", "--workspace", ws, "--json")
    assert r.code == 0
    folder = Path(r.data["folder"])
    assert folder.is_absolute() and folder.parent == ws.resolve() / "exports"
    d = check(folder)
    assert d["mode"] == "sanitised" and r.data["mode"] == "sanitised" and r.data["include"] == []
    assert r.data["files"] == ["dataset.json", "dataset-1.schema.json"]
    assert r.data["outputs"] == [{"format": "json", "files": ["dataset.json"], "notes": []}]  # json,json is json
    conn = store.connect(ws / layout.DB_NAME)
    again, preview = dataset.build(conn, ws)
    pconn, ident = pin.pin(conn, ws)
    pconn.close()
    assert d == again  # the file is the dataset (store.now is fixed by the fixture's environment)
    assert r.data["preview"] == preview and r.data["stale"] is False
    assert r.data["data_version"] == {**ident} and set(d["data_version"]) == {"version", "built_at", "sha256",
                                                                               "projection_schema"}
    v = ident["version"]
    assert d["data_version"] == {k: ident[k] for k in ("version", "built_at", "sha256", "projection_schema")}
    assert ident["sha256"] == hashlib.sha256((ws / "published" / f"v{v}.db").read_bytes()).hexdigest()
    assert folder.name.startswith(f"all-v{v}-") and folder.name.endswith("-sanitised")
    # R3: one run row and its note, output and finished events; nothing else changed
    after = dump(ws)
    changed = {t for t in after if after[t] != before[t]}
    assert changed == {"run", "run_event"}
    (run_id,) = {x[0] for x in report_runs(ws)}
    assert run_id == r.data["run_id"]
    assert [x[2:] for x in report_runs(ws)] == [
        ("note", "report", "all json", None, None),
        ("output", "report", f"exports/{folder.name}/dataset.json", None, None),
        ("output", "report", f"exports/{folder.name}/dataset-1.schema.json", None, None),
        ("finished", None, None, None, "ok")]
    assert len(set(after["run"]) - set(before["run"])) == 1 and len(set(after["run_event"]) - set(before["run_event"])) == 4
    assert {p.name: p.read_bytes() for p in (ws / "published").iterdir()} == published_before
    assert (ws / "exports" / "mine.csv").read_text() == "a user's own file\n"
    conn.close()


def test_the_complete_export_carries_both_marks_and_the_text_says_so(ws, gct):
    r = gct("report", "evidence-index", "--format", "json", "--complete", "--workspace", ws)
    assert r.code == 0
    folder = Path(next(line for line in r.out.splitlines() if line.startswith("Wrote ")).split(" to ", 1)[1][:-1])
    d = check(folder)
    assert folder.name.endswith("-complete") and d["mode"] == "complete"
    assert set(d["data_version"]) == {"version", "built_at", "sha256", "projection_schema", "history_mark",
                                      "labels_mark"}
    lines = r.out.splitlines()
    assert lines[0] == f"Wrote complete report data for data version {d['data_version']['version']} to {folder}:"
    assert lines[1:3] == ["  dataset.json", "  dataset-1.schema.json"]
    assert lines[3:3 + len(d["notices"])] == d["notices"]
    assert lines[3 + len(d["notices"])] == "This export includes private content. Check it before you share it."
    assert "Data version" in lines[4 + len(d["notices"])]  # then 7.1's preview printer


def test_two_renders_are_byte_identical_and_two_exports_differ_only_in_built_at(ws, gct, tmp_path, monkeypatch):
    from gct.reports import render_json

    conn = store.connect(ws / layout.DB_NAME)
    d, _ = dataset.build(conn, ws, mode="complete")
    for n in (1, 2):
        (tmp_path / str(n)).mkdir()
        assert render_json.write(d, ["evidence_index"], tmp_path / str(n), {}) == {"files": ["dataset.json"],
                                                                                   "notes": []}
    assert (tmp_path / "1" / "dataset.json").read_bytes() == (tmp_path / "2" / "dataset.json").read_bytes()
    with pytest.raises(FileExistsError):  # mode "x": a renderer never overwrites
        render_json.write(d, [], tmp_path / "1", {})
    # the renderer adds no string of its own
    def strings(x):
        if isinstance(x, str):
            return {x}
        return set().union(*(strings(v) | (set(x) if isinstance(x, dict) else set())
                             for v in (x.values() if isinstance(x, dict) else x))) if x else set()
    assert strings(json.loads((tmp_path / "1" / "dataset.json").read_text())) == strings(d)
    conn.close()
    first = check(export_(gct, ws, "--complete")[1])
    monkeypatch.setattr(store, "now", lambda: "2026-10-24T01:02:03+00:00")
    second = check(export_(gct, ws, "--complete")[1])
    assert second["built_at"] == "2026-10-24T01:02:03+00:00"
    assert {**first, "built_at": None} == {**second, "built_at": None}


def test_the_preview_and_its_lines_stay_on_the_terminal(ws, gct):
    r = gct("report", "all", "--format", "json", "--workspace", ws)
    assert r.code == 0
    assert dataset.SOME_PRIVATE in r.out and dataset.RELABEL in r.out and "Left out: " in r.out
    folder = Path(r.out.splitlines()[0].split(" to ", 1)[1][:-1])
    text = (folder / "dataset.json").read_text()
    for line in (dataset.SOME_PRIVATE, dataset.RELABEL, "Left out", "Every document in this selection"):
        assert line not in text


# AC 2, 3: refusals write nothing; renderer failures leave no folder; the lock

def test_every_refusal_writes_nothing(ws, gct, tmp_path, monkeypatch):
    from gct.stages import deletion

    empty = tmp_path / "empty"
    gct("workspace", "init", empty)
    cases = [(ws, ("--format", "xlsx"), 2, "Unknown format xlsx. Available: json."),
             (ws, ("--format", "json,pdf"), 2, "Unknown format pdf. Available: json."),
             (ws, ("--format", "json", "--filter", '{"colour": [1]}'), 2, "The filter has no field colour."),
             (ws, ("--format", "json", "--filter", "{"), 2, None),
             (ws, ("--format", "json", "--filter", f"@{tmp_path / 'none.json'}"), 3, None),
             (ws, ("--format", "json", "--include", "names"), 2, "names is not an inclusion class."),
             (ws, ("--format", "json", "--data-version", 1), 4, "Data version 1 is no longer the current one;"),
             (empty, ("--format", "json"), 4, None)]
    for root, argv, code, cause in cases:
        before, files_before = dump(root), listing(root)
        r = gct("report", "all", *argv, "--workspace", root, "--json")
        assert r.code == code and r.data["status"] == "error", (argv, r.out)
        assert cause is None or r.data["cause"].startswith(cause), (argv, r.data)
        assert dump(root) == before and listing(root) == files_before, argv
    # a current file below projection 16
    old = Path(shutil.copytree(ws, tmp_path / "old"))
    c = sqlite3.connect(old / "published" / "v2.db")
    c.execute("UPDATE meta SET value = '15' WHERE key = 'projection_schema'")
    c.commit()
    c.close()
    before, files_before = dump(old), listing(old)
    r = gct("report", "all", "--format", "json", "--workspace", old, "--json")
    assert r.code == 4 and r.data["next_action"] == "Build a fresh version with: gct publish build"
    assert dump(old) == before and listing(old) == files_before
    # an unfinished deletion (K3)
    def boom(*a):
        raise OSError("held open")
    real = deletion.WORK["published"]
    monkeypatch.setitem(deletion.WORK, "published", boom)
    token = sqlite3.connect(ws / layout.DB_NAME).execute("SELECT sha256 FROM document WHERE id = 1").fetchone()[0][:12]
    assert gct("doc", "delete", 1, "--confirm", token, *WHO, "--workspace", ws).code == 4
    monkeypatch.setitem(deletion.WORK, "published", real)
    before, files_before = dump(ws), listing(ws)
    r = gct("report", "all", "--format", "json", "--workspace", ws, "--json")
    assert r.code == 4 and r.data["cause"] == "Document 1 was deleted but its removal did not finish."
    assert dump(ws) == before and listing(ws) == files_before
    # a held lock
    held = lock.hold(old)
    try:
        r = gct("report", "all", "--format", "json", "--workspace", old, "--json")
        assert r.code == 4 and r.data["cause"] == "Another gct command is using this workspace."
    finally:
        lock.release(held)
    assert dump(old) == before | {} and True  # the lock refusal opened nothing either
    assert listing(old) == files_before


def test_a_renderer_failure_leaves_a_failed_run_and_no_folder(ws, gct, monkeypatch):
    def broken(dataset_, reports, folder, crops):
        open(folder / "half.json", "x").write("{")
        raise RuntimeError("renderer bug")

    monkeypatch.setitem(export.FORMATS, "broken", {"write": broken, "crops": False})
    files_before = listing(ws)
    r = gct("report", "all", "--format", "json,broken", "--workspace", ws)
    assert r.code == 1 and listing(ws)[:-1] == files_before[:0] + listing(ws)[:-1]
    assert [p for p in listing(ws) if not p.startswith("logs")] == [p for p in files_before if not p.startswith("logs")]
    rows = report_runs(ws)
    assert rows[0][2:5] == ("note", "report", "all json,broken") and rows[-1][2:] == ("finished", None, None,
                                                                                    "RuntimeError", "failed")
    assert [x for x in rows if x[2] == "output"] == []


def test_an_existing_export_is_never_overwritten(ws, gct, monkeypatch):
    monkeypatch.setattr(export, "stamp", lambda: "20261023T000000000000Z")  # two exports in the same microsecond
    data, folder = export_(gct, ws)
    kept = files(folder)
    r = gct("report", "all", "--format", "json", "--workspace", ws, "--json")
    assert r.code == 4 and r.data["cause"] == f"An export named {folder.name} already exists; nothing was overwritten."
    assert r.data["next_action"] == "Run the command again."
    assert files(folder) == kept and listing(ws) == sorted([f"{folder.name}", f"{folder.name}/dataset.json",
                                                             f"{folder.name}/dataset-1.schema.json"])
    assert report_runs(ws)[-1][2:] == ("finished", None, None, r.data["cause"], "failed")
    shutil.rmtree(folder)
    folder.mkdir()  # an empty folder of that name: os.rename would replace it silently on POSIX
    assert gct("report", "all", "--format", "json", "--workspace", ws).code == 4
    assert list(folder.iterdir()) == [] and listing(ws) == [folder.name]


def test_a_removed_exports_folder_is_made_again(ws, gct):
    shutil.rmtree(ws / "exports")
    check(export_(gct, ws)[1])


def test_the_lock_is_held_from_the_build_until_the_files_are_in_place(ws, gct, monkeypatch):
    held = []

    def refused():
        with pytest.raises(layout.GctError, match="Another gct command"):
            lock.release(lock.hold(ws))
        held.append(True)

    real_build, real_write, real_rename = dataset.build, export.FORMATS["json"]["write"], export.os.rename
    monkeypatch.setattr(dataset, "build", lambda *a, **k: (refused(), real_build(*a, **k))[1])
    monkeypatch.setitem(export.FORMATS, "json", {"write": lambda *a: (refused(), real_write(*a))[1], "crops": False})
    monkeypatch.setattr(export.os, "rename", lambda *a: (refused(), real_rename(*a))[1])
    check(export_(gct, ws)[1])
    assert held == [True] * 3


def test_a_report_run_is_not_resumed_or_retried(ws, gct):
    run_id = export_(gct, ws)[0]["run_id"]
    for verb, word in (("resume", "resumed"), ("retry", "retried")):
        r = gct("run", verb, run_id, "--workspace", ws, "--json")
        assert r.code == 4 and r.data["cause"] == (f"Run {run_id} was a report run. Only read, extract, link, infer,"
                                                   f" match, sheet and doc add runs can be {word}.")


# AC 12, 12a, 12b: the format table, the shared folder writer, renderer refusals

def test_formats_come_from_the_table_and_may_write_subfolders_and_notes(ws, gct, monkeypatch):
    def deep(dataset_, reports, folder, crops):
        (folder / "evidence-index").mkdir()
        open(folder / "evidence-index" / "a.txt", "x").write(",".join(reports))
        return {"files": ["evidence-index/a.txt"], "notes": ["3 cells were prefixed."]}

    monkeypatch.setitem(export.FORMATS, "deep", {"write": deep, "crops": False})
    r = gct("report", "all", "--format", "nope", "--workspace", ws, "--json")
    assert r.data["cause"] == "Unknown format nope. Available: deep, json."
    r = gct("report", "restatement-log", "--format", "deep,json", "--workspace", ws, "--json")
    assert r.code == 0
    folder = Path(r.data["folder"])
    assert r.data["files"] == ["evidence-index/a.txt", "dataset.json", "dataset-1.schema.json"]
    assert r.data["outputs"] == [{"format": "deep", "files": ["evidence-index/a.txt"], "notes": ["3 cells were prefixed."]},
                                 {"format": "json", "files": ["dataset.json"], "notes": []}]
    assert (folder / "evidence-index" / "a.txt").read_text() == "restatement_log"
    assert [x[4] for x in report_runs(ws) if x[2] == "output"] == [f"exports/{folder.name}/{n}" for n in r.data["files"]]
    text = gct("report", "all", "--format", "deep", "--workspace", ws)
    assert "3 cells were prefixed." in text.out.splitlines()


def test_an_unlisted_or_missing_file_is_refused(ws, gct, monkeypatch):
    def extra(dataset_, reports, folder, crops):
        (folder / "sub").mkdir()
        open(folder / "sub" / "x.txt", "x").write("x")
        open(folder / "sub" / "y.txt", "x").write("y")
        return {"files": ["sub/x.txt"], "notes": []}

    def short(dataset_, reports, folder, crops):
        return {"files": ["never.txt"], "notes": []}

    for fn, odd in ((extra, "sub/y.txt"), (short, "never.txt")):
        monkeypatch.setitem(export.FORMATS, "odd", {"write": fn, "crops": False})
        r = gct("report", "all", "--format", "odd", "--workspace", ws, "--json")
        assert r.code == 4 and odd in r.data["cause"] and listing(ws) == []


@pytest.fixture
def crops_stub(monkeypatch):
    """A test-only stand-in for 7.4's gct.reports.crops (one entry per page entry), at both places an import finds
    it, whatever an earlier test imported. Story 7.4 moves these tests to its real crops.cut."""
    calls = []

    def cut(root, dataset_):
        out = {e["id"]: b"png" for e in dataset_["evidence"] if e["page"] is not None}
        calls.append((root, dataset_, out))
        return out

    mod = types.ModuleType("gct.reports.crops")
    mod.cut, mod.LIMIT = cut, 500
    monkeypatch.setitem(sys.modules, "gct.reports.crops", mod)
    monkeypatch.setattr(gct.reports, "crops", mod, raising=False)
    return calls


def test_crops_are_cut_once_for_every_flagged_format_and_never_for_json(ws, gct, monkeypatch, crops_stub):
    seen = []

    def flagged(name):
        def write(dataset_, reports, folder, crops):
            seen.append((name, dataset_, crops))
            open(folder / f"{name}.txt", "x").write("x")
            return {"files": [f"{name}.txt"], "notes": []}
        return write

    for n in ("p1", "p2"):
        monkeypatch.setitem(export.FORMATS, n, {"write": flagged(n), "crops": True})
    check(export_(gct, ws)[1])
    assert crops_stub == []  # a json-only export never reaches the crops module
    data, folder = export_(gct, ws, fmt="p1,json,p2")
    assert len(crops_stub) == 1
    (root, cut_dataset, cut), = crops_stub
    assert [x[0] for x in seen] == ["p1", "p2"]
    assert all(x[2] is cut and x[1] is cut_dataset for x in seen) and cut  # one dict, the same dataset, never {}
    assert cut_dataset["data_version"]["version"] == data["data_version"]["version"]
    seen.clear()
    export_(gct, ws, fmt="p2")
    assert len(crops_stub) == 2 and [x[0] for x in seen] == ["p2"]


def test_the_shared_folder_writer(tmp_path):
    root = tmp_path / "w"
    root.mkdir()
    with export.folder(root, "s1") as tmp:
        assert tmp == root / "exports" / ".incoming-s1"
        (tmp / "a").write_text("a")
    assert files(root / "exports" / "s1") == {"a": b"a"} and listing(root) == ["s1", "s1/a"]
    with pytest.raises(ZeroDivisionError):
        with export.folder(root, "s2") as tmp:
            (tmp / "a").write_text("a")
            1 / 0
    assert listing(root) == ["s1", "s1/a"]
    for existing in ("s1", "empty"):
        (root / "exports" / "empty").mkdir(exist_ok=True)
        with pytest.raises(layout.GctError, match="already exists; nothing was overwritten"):
            with export.folder(root, existing) as tmp:
                (tmp / "b").write_text("b")
        assert listing(root) == ["empty", "s1", "s1/a"]
    listed = []
    with export.folder(root, "s3", listed) as tmp:  # a list filled inside the block is the one checked on exit
        (tmp / "d").mkdir()
        (tmp / "d" / "x").write_text("x")
        listed.append("d/x")
    assert files(root / "exports" / "s3") == {"d/x": b"x"}
    for written, given in ((["d/x", "d/y"], ["d/x"]), (["d/x"], ["d/x", "d/z"])):
        with pytest.raises(layout.GctError, match="did not match"):
            with export.folder(root, "s4", given) as tmp:
                (tmp / "d").mkdir()
                for n in written:
                    (tmp / n).write_text("x")
        assert not (root / "exports" / "s4").exists() and not (root / "exports" / ".incoming-s4").exists()


class CellRefusal(Exception):
    """A renderer's refusal: any exception with string cause and next_step (no gct.workspace import)."""
    cause = "The evidence index has a cell longer than the format can hold (claim 3, column Metric as printed)."
    next_step = "Export that report as JSON instead: gct report evidence-index --format json"


def test_a_renderer_refusal_is_the_commands_refusal(ws, gct, monkeypatch):
    def refuses(dataset_, reports, folder, crops):
        open(folder / "part.txt", "x").write("x")
        raise CellRefusal()

    monkeypatch.setitem(export.FORMATS, "strict", {"write": refuses, "crops": False})
    human = gct("report", "all", "--format", "json,strict", "--workspace", ws)
    machine = gct("report", "all", "--format", "strict", "--workspace", ws, "--json")
    assert human.code == machine.code == layout.REFUSED
    assert human.err == f"error: {CellRefusal.cause}\nnext: {CellRefusal.next_step}\n" and human.out == ""
    assert machine.data == {"status": "error", "cause": CellRefusal.cause, "next_action": CellRefusal.next_step}
    assert listing(ws) == []
    finished = [x for x in report_runs(ws) if x[2] == "finished"]
    assert [x[5:] for x in finished] == [(CellRefusal.cause, "failed")] * 2
    assert "gct.workspace" not in Path(__file__).read_text().split("class CellRefusal")[1].split("def test_a_rend")[0]


# AC 9: leakage (section G steps 1 to 5)

def test_no_seed_leaves_in_a_sanitised_export_and_the_complete_one_holds_its_reachable_seeds(w, env, gct, tmp_path):
    root = Path(shutil.copytree(w, tmp_path / "ws"))
    never = [s for s in f.SEEDS if s["expect"] == "never"]
    complete_only = [s for s in f.SEEDS if s["expect"] == "complete_only"]
    raw = found(root, [s for s in never if s["name"] in f.STORED_RAW])
    assert set(raw) == set(f.STORED_RAW)  # step 1: each one first found where it is stored
    flt = json.dumps({"document": [8, 1, 19], "company": [1, 2, 3], "text": f.METRIC})
    for flags in ((), ("--filter", flt)):
        complete_data, complete = export_(gct, root, "--complete", *flags)
        conn = store.connect(root / layout.DB_NAME)
        built, _ = dataset.build(conn, root, mode="complete", filter=json.loads(flags[1]) if flags else None)
        conn.close()
        text = json.dumps(built, ensure_ascii=False)
        expected = {s["name"] for s in complete_only if s["kind"] != "image" and s["value"] in text}
        hits = found(complete, complete_only)
        assert set(hits) >= expected and set(hits) <= expected | set()
        if not flags:  # step 2: the expected set holds each kind
            kinds = {s["kind"] for s in complete_only if s["name"] in expected}
            assert {"document_text", "contributor", "file_hash"} <= kinds
            assert "CON-ACCEPT-01" not in expected and "DOC-CELL-02" in expected and "FILE-PDF-01" in expected
        _, sanitised = export_(gct, root, *flags)
        assert found(sanitised, f.SEEDS) == {}  # step 3: no complete_only seed, no never seed
        assert found(complete, never) == {}
        for folder in (sanitised, complete):
            assert str(root).encode() not in (folder / "dataset.json").read_bytes()
            assert str(root.resolve()).encode() not in (folder / "dataset.json").read_bytes()
    # step 4: the report runs' lines hold no seed, no path and no message
    lines = tmp_path / "runs.txt"
    lines.write_text(json.dumps(report_runs(root), ensure_ascii=False))
    assert found(lines, f.SEEDS) == {} and str(root.resolve()) not in lines.read_text()
    assert {x[5] for x in report_runs(root) if x[2] != "finished"} == {None}


def test_the_sanitised_ids_and_filter_echo(w, env, gct, tmp_path):
    """Step 5 and the filter echo: the ids the filter gave, kept only for companies and documents with a shipped row
    and series with a shipped point, computed here from the fixture (the dataset cannot answer it itself)."""
    root = Path(shutil.copytree(w, tmp_path / "ws"))
    conn = store.connect(root / layout.DB_NAME)
    pconn, ident = pin.pin(conn, root)
    eff = labels.effective(conn, pconn)
    active = {i for (i,) in pconn.execute("SELECT id FROM document")}
    private = {i for i, x in eff.items() if x["label"] == "private"}
    assert max(eff) in private  # the private document has the highest id (a leaked history_mark would tell, K2)
    names = dict(conn.execute("SELECT id, name FROM company").fetchall())
    only_private = [c for c in names if not {i for (i,) in pconn.execute(
        "SELECT id FROM document WHERE company_id = ?", (c,))} - private]
    assert only_private == [3]
    # a series that only private claims make exist, and one with shareable points
    rule = {}
    for s, d in pconn.execute("SELECT p.series_id, c.document_id FROM series_point p JOIN claim c ON c.id = p.claim_id"
                              " WHERE p.link = 'rule'"):
        rule.setdefault(s, set()).add(d)
    hidden = sorted(s for s, docs in rule.items() if docs <= private)[0]
    shown = sorted(s for s, docs in rule.items() if docs - private)[0]
    pconn.close()
    flt = {"company": [1, 2, 3], "document": sorted(eff), "series": [hidden, shown], "text": "Scope 1"}
    data, folder = export_(gct, root, "--filter", json.dumps(flt))
    d = check(folder)
    shipped_docs = {x["id"] for x in d["documents"]}
    assert shipped_docs and not shipped_docs & private
    shipped_companies = {x["company"] for x in d["documents"]} | {r["company"] for r in d["evidence_index"]}
    assert d["filter"]["company"] == [c for c in flt["company"] if names[c] in shipped_companies] == [1, 2]
    assert d["filter"]["document"] == [i for i in flt["document"] if i in active and i not in private
                                       and i in shipped_docs]
    with sqlite3.connect(root / "published" / f"v{ident['version']}.db") as c:
        claim_series = dict(c.execute("SELECT id, series_id FROM claim").fetchall())
    shipped_series = {claim_series[r["claim_id"]] for r in d["evidence_index"]} | {
        r["series_id"] for r in d["restatement_log"]}
    assert d["filter"]["series"] == [s for s in flt["series"] if s in shipped_series] and hidden not in shipped_series
    assert d["filter"]["text"] is None and d["filter"]["withheld"] == ["text"]
    text = (folder / "dataset.json").read_text()
    assert names[3] not in text and "Scope 1" in text  # the text appears as claim wording, never as the filter
    for t, r in rows_of(d):
        assert not set(r["documents"]) & private and r.get("document_id") not in private, (t, r["id"])
    assert not {e["document_id"] for e in d["evidence"]} & private

    def keys(x):
        if isinstance(x, dict):
            return set(x) | set().union(*map(keys, x.values()))
        return set().union(*map(keys, x)) if isinstance(x, list) else set()
    assert not keys({k: v for k, v in d.items() if k not in ("words", "columns")}) & {
        "history_mark", "labels_mark", "matched", "total", "excluded", "hidden_by_archive", "deleted_in_filter"}
    conn.close()


def test_read_back_has_the_shared_shape(exports_, w, env, gct, tmp_path):
    root = Path(shutil.copytree(w, tmp_path / "ws"))
    for argv in ((), ("--complete",)):
        folder = export_(gct, root, *argv)[1]
        d = json.loads((folder / "dataset.json").read_text())
        back = read_back(folder)
        assert back["data_version"] == d["data_version"]
        assert set(back["rows"]) == {"evidence_index", "restatement_log", *(f"gap_report.{s}" for s in SECTIONS)}
        for t, rows in back["rows"].items():
            src = d[t] if "." not in t else d["gap_report"][t.split(".")[1]]
            cols = d["columns"][t.split(".")[-1]]
            assert len(rows) == len(src)
            for got, row in zip(rows, src):
                assert list(got) == [c["key"] for c in cols]
                assert got == {c["key"]: printed(dotted(row, c["key"]), row, c["key"], "json") for c in cols}
        corrected = next(r for r in d["evidence_index"] if r["correction"])
        i = d["evidence_index"].index(corrected)
        assert back["rows"]["evidence_index"][i]["correction.created_at"] == corrected["correction"]["created_at"]
        plain = next(i for i, r in enumerate(d["evidence_index"]) if r["correction"] is None)
        assert back["rows"]["evidence_index"][plain]["correction.created_at"] is None
    assert printed([1, 2], {}, "claims", "json") == [1, 2] and printed(None, {}, "x", "json") is None


# AC 10, 11: P-empty and the behaviour sections

def test_every_document_private_still_writes_a_valid_empty_export(ws, gct):
    for x in gct("doc", "list", "--workspace", ws, "--json").data["documents"]:
        if x["state"] != "deleted" and x["privacy"] == "shareable":
            assert gct("doc", "label", x["id"], "--privacy", "private", *WHO, "--workspace", ws).code == 0
    assert gct("publish", "build", "--workspace", ws).code == 0
    r = gct("report", "all", "--format", "json", "--workspace", ws)
    assert r.code == 0 and dataset.ALL_PRIVATE in r.out and dataset.RELABEL in r.out
    folder = Path(r.out.splitlines()[0].split(" to ", 1)[1][:-1])
    d = check(folder)
    v = d["data_version"]["version"]
    assert d["documents"] == [] and d["evidence_index"] == d["related_claims"] == d["restatement_log"] == []
    assert d["unpaired_restatements"]["rows"] == [] and all(x == [] for x in d["gap_report"].values())
    assert d["evidence"] == [] and d["filter"] == {}
    assert d["notices"] == [dataset.sanitised_empty(v), dataset.PRIVACY_NOTICE, dataset.ARCHIVE_NOTICE]
    text = (folder / "dataset.json").read_text()
    for x in gct("doc", "list", "--workspace", ws, "--json").data["documents"]:
        assert x["logical_name"] not in text
    data, folder = export_(gct, ws, "--filter", json.dumps({"company": [3], "document": [18, 19]}))
    d = check(folder)
    assert d["filter"] == {"company": [], "document": []} and d["documents"] == []


def test_archive_warns_stale_then_the_rebuild_withholds_it(ws, gct):
    first, folder = export_(gct, ws)
    assert gct("doc", "archive", 1, *WHO, "--workspace", ws).code == 0
    r = gct("report", "all", "--format", "json", "--workspace", ws)
    v = first["data_version"]["version"]
    assert (f"The workspace has changed since data version {v} was built; this export shows version {v}. To include"
            " the changes: gct publish build, then export again.") in r.out.splitlines()
    stale = check(Path(r.out.splitlines()[0].split(" to ", 1)[1][:-1]))
    assert stale["data_version"]["sha256"] == first["data_version"]["sha256"]  # archive changes no file
    assert gct("report", "all", "--format", "json", "--workspace", ws, "--json").data["stale"] is True
    assert gct("publish", "build", "--workspace", ws).code == 0
    after = check(export_(gct, ws)[1])
    assert 1 not in {x["id"] for x in after["documents"]} and after["data_version"]["version"] == v + 1
    complete = check(export_(gct, ws, "--complete")[1])
    assert 1 in {x["document_id"] for x in complete["gap_report"]["archived"]}
    assert {x["state"] for x in complete["documents"] if x["id"] == 1} <= {"archived"}


def test_a_deletion_keeps_earlier_exports_and_report_run_lines(ws, gct, make_file):
    from conftest import make_pdf

    pdf = make_file("x.pdf", make_pdf([{"text": [(72, 72, "Scope 1")]}]))
    assert gct("doc", "add", pdf, "--company", "Acme", "--name", "sanitised", "--workspace", ws).code == 0
    (named,) = [x["id"] for x in gct("doc", "list", "--workspace", ws, "--json").data["documents"]
                if x["logical_name"] == "sanitised"]
    for fmt in ("json", "json"):  # 'json', 'all' and 'sanitised' are all in the report run lines
        export_(gct, ws, fmt=fmt)
    first, folder = export_(gct, ws, "--complete")
    kept, lines = files(folder), report_runs(ws)
    token = sqlite3.connect(ws / layout.DB_NAME).execute("SELECT sha256 FROM document WHERE id = ?",
                                                         (named,)).fetchone()[0][:12]
    assert gct("doc", "delete", named, "--confirm", token, *WHO, "--workspace", ws).code == 0
    assert report_runs(ws) == lines and files(folder) == kept
    token = sqlite3.connect(ws / layout.DB_NAME).execute("SELECT sha256 FROM document WHERE id = 1").fetchone()[0][:12]
    assert gct("doc", "delete", 1, "--confirm", token, *WHO, "--workspace", ws).code == 0  # in the current version
    assert report_runs(ws) == lines and files(folder) == kept
    after = check(export_(gct, ws, "--complete")[1])
    assert after["data_version"]["version"] == first["data_version"]["version"]
    assert after["data_version"]["sha256"] != first["data_version"]["sha256"]  # purged in place under one number
    assert 1 in {x["document_id"] for x in after["gap_report"]["deleted"]}
    assert {x["name"] for x in after["documents"] if x["id"] == 1} <= {None}
    assert all(r["document_id"] != 1 for r in after["evidence_index"])


def test_missing_states_non_binding_records_and_empty_results(exports_, ws, gct):
    d = exports_["complete"]
    states = {r["state"] for r in d["gap_report"]["expectations"]}
    assert states and states <= {missing.INCOMPLETE, missing.NOT_FOUND_IN, missing.CONFIRMED}
    earlier = [r for t, r in rows_of(d) if t in ("records", "restatements", "adjudications") and not r["binds"]]
    assert earlier and {r["earlier"] for r in earlier} == {d["words"]["earlier_version"]}
    assert {r["earlier"] for t, r in rows_of(d) if t == "records" and r["binds"]} == {None}
    for argv in ((), ("--complete",)):
        e = check(export_(gct, ws, "--filter", json.dumps({"document": [5]}), *argv)[1])  # the deleted document
        assert e["evidence_index"] == e["restatement_log"] == e["documents"] == []
        v = e["data_version"]["version"]
        assert e["notices"][0] == (view.empty_text(v) if argv else dataset.sanitised_empty(v))
