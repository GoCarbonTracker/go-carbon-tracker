import re
from pathlib import Path

from conftest import PDF, make_pdf

DOC = Path(__file__).resolve().parent.parent / "docs" / "cli-json.md"


def spec():
    """{command: {where: set(keys)}} parsed from docs/cli-json.md."""
    out, section = {}, None
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = out.setdefault(line[3:].strip(), {})
        elif m := re.match(r"^- (\w+): (.+)$", line):
            section[m[1]] = set(m[2].replace(" ", "").split(","))
    return out


def check(command, data):
    expected = spec()[command]
    assert set(data) == expected["top"], command
    for where, keys in expected.items():
        if where == "top":
            continue
        nested = data[where]
        for record in nested if isinstance(nested, list) else [nested]:
            assert set(record) == keys, (command, where)


def test_every_command_matches_the_documented_keys(tmp_path, gct, make_file):
    ws = tmp_path / "ws"
    check("workspace init", gct("workspace", "init", ws, "--json").data)
    assert gct("workspace", "init", ws, "--json").data["status"] == "already_initialised"
    check("workspace init", gct("workspace", "init", ws, "--json").data)
    w = ("--workspace", ws)
    new = gct("company", "add", "Acme", *w, "--json").data
    check("company add", new)
    exists = gct("company", "add", "acme", *w, "--json").data
    assert exists["status"] == "exists"
    check("company add", exists)
    check("company list", gct("company", "list", *w, "--json").data)
    f = make_file("a.pdf", PDF)
    added = gct("doc", "add", f, "--company", "Acme", *w, "--json").data
    check("doc add", added)
    dup = gct("doc", "add", f, "--company", "Acme", *w, "--json").data
    assert dup["status"] == "ok" and dup["items"][0]["action"] == "duplicate"
    check("doc add", dup)
    check("doc list", gct("doc", "list", *w, "--json").data)
    check("doc show", gct("doc", "show", 1, *w, "--json").data)
    check("doc pages", gct("doc", "pages", 1, *w, "--json").data)
    gct("doc", "add", make_file("b.pdf", make_pdf([{"text": [(72, 72, "Scope 1")]}, {}])), "--company", "Acme", *w)
    partial = gct("read", *w, "--json").data
    assert partial["status"] == "partial" and {"cause", "next_action"} <= set(partial)
    check("read", {k: v for k, v in partial.items() if k not in ("cause", "next_action")})
    ok = gct("read", 2, *w, "--json").data
    assert ok["status"] == "ok"
    check("read", ok)
    check("doc pages", gct("doc", "pages", 2, *w, "--json").data)
    check("extract", gct("extract", *w, "--json").data)
    check("link", gct("link", *w, "--json").data)
    check("contributor add", gct("contributor", "add", "ana", "--name", "Ana", *w, "--json").data)
    check("contributor edit", gct("contributor", "edit", "ana", "--organisation", "Acme", *w, "--json").data)
    check("contributor list", gct("contributor", "list", *w, "--json").data)
    check("expect add", gct("expect", "add", "--company", "Acme", "--metric", "scope 1", "--doc", 2, *w, "--json").data)
    check("expect add", gct("expect", "add", "--company", "Acme", "--metric", "water", "--doc", 2, *w, "--json").data)
    who = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked by eye")
    check("pages accept", gct("pages", "accept", "--doc", 2, "--pages", "1-2", "--type", "figures", *who, *w, "--json").data)
    gct("pages", "accept", "--doc", 2, "--pages", "2", "--type", "text", *who, *w)  # the empty page has no text
    check("gap confirm", gct("gap", "confirm", 2, *who, *w, "--json").data)
    check("expect list", gct("expect", "list", *w, "--json").data)
    check("claims list", gct("claims", "list", "--doc", 2, *w, "--json").data)
    check("claims list", gct("claims", "list", "--doc", 1, *w, "--json").data)
    check("publish status", gct("publish", "status", *w, "--json").data)
    check("publish build", gct("publish", "build", *w, "--json").data)
    check("publish build", gct("publish", "build", *w, "--json").data)
    check("publish restore", gct("publish", "restore", *w, "--json").data)
    check("publish status", gct("publish", "status", *w, "--json").data)
    check("workspace status", gct("workspace", "status", *w, "--json").data)
    check("run list", gct("run", "list", *w, "--json").data)
    check("run show", gct("run", "show", 1, *w, "--json").data)
    check("error", gct("doc", "show", 99, *w, "--json").data)


def test_infer_matches_the_documented_keys(tmp_path, gct, make_file):
    ws = tmp_path / "ws"
    gct("workspace", "init", ws)
    w = ("--workspace", ws)
    who = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked by eye")
    gct("company", "add", "Acme", *w)
    gct("contributor", "add", "ana", "--name", "Ana", *w)
    check("infer", gct("infer", *w, "--json").data)
    text = [(40, 80, "Energy FY24 4,560 MWh"), (40, 100, "Water 2023 120 kL"),
            (40, 120, "The financial year ended March 31, 2024."),
            (40, 140, "Reporting boundary: Report is prepared on a standalone basis.")]
    gct("doc", "add", make_file("a.pdf", make_pdf([{"text": text}, {"text": [(40, 80, "Reporting boundary")]}])),
        "--company", "Acme", *w)
    gct("doc", "add", make_file("b.pdf", make_pdf([{"text": [(40, 80, "nothing")]}])), "--company", "Acme", *w)
    gct("read", *w)
    gct("extract", *w)
    check("infer", gct("infer", *w, "--json").data)
    bases = gct("infer", "bases", *w, "--json").data
    check("infer bases", bases)
    assert bases["bases"] and bases["headings"]
    boundary = next(b["id"] for b in bases["bases"] if b["kind"] == "reporting_boundary")
    check("infer scope", gct("infer", "scope", boundary, "--pages", "1-2", *who, *w, "--json").data)
    gct("infer", *w)
    groups = gct("infer", "groups", *w, "--json").data
    check("infer groups", groups)
    proposed = [g["id"] for g in groups["groups"] if g["state"] == "proposed"]
    assert len(proposed) >= 2
    check("infer accept", gct("infer", "accept", proposed[0], *who, *w, "--json").data)
    check("infer reject", gct("infer", "reject", proposed[1], *who, *w, "--json").data)
    check("infer resolve", gct("infer", "resolve", 1, "--field", "boundary", "--boundary", "standalone", *who, *w, "--json").data)
    check("claims list", gct("claims", "list", "--doc", 1, *w, "--json").data)
    check("correct", gct("correct", 1, "--value", "4,570", *who, *w, "--json").data)
    history = gct("claims", "history", 1, *w, "--json").data
    check("claims history", history)
    assert history["versions"][0]["reviews"] and history["versions"][1]["correction"]
    listed = gct("claims", "list", "--doc", 1, "--state", "current", *w, "--json").data
    check("claims list", listed)
    assert any(c["needs_re_review"] for c in listed["claims"])


def test_match_and_series_match_the_documented_keys(ws, gct, make_file, monkeypatch):
    from test_match import SCOPE_1, WHO, add, ready
    from gct.stages import match

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    check("match", gct("match", "--json").data)
    check("match status", gct("match", "status", "--json").data)
    check("series list", gct("series", "list", "--json").data)
    add(gct, make_file, "a.pdf", [SCOPE_1])
    add(gct, make_file, "d.pdf", [["Total Scope 1 emissions", "tCO2e", "999"]], periods=("FY 2024-25",), boundary=None)
    check("match", ready(gct))
    check("match metrics", gct("match", "metrics", "--json").data)
    items = gct("match", "review", "--json").data
    check("match review", items)
    (item,) = items["items"]
    check("match link", gct("match", "link", item["claim"], "--series", item["series"], *WHO, "--json").data)
    check("match unlink", gct("match", "unlink", item["claim"], "--series", item["series"], *WHO, "--json").data)
    check("match status", gct("match", "status", "--json").data)
    listed = gct("series", "list", "--json").data
    check("series list", listed)
    check("series show", gct("series", "show", listed["series"][0]["id"], "--all", "--json").data)
    real = match.assign
    monkeypatch.setattr(match, "assign", lambda *a: (_ for _ in ()).throw(ValueError("boom")))
    gct("correct", item["claim"], "--value", "998", *WHO)
    failed = gct("match", "--json").data
    assert failed["status"] == "partial"
    monkeypatch.setattr(match, "assign", real)
    n = gct("run", "list", "--json").data["runs"][0]["id"]
    retried = gct("run", "retry", n, "--json").data
    assert set(retried) == spec()["match"]["top"] | {"run_id", "of_run"}
    for d in retried["documents"]:
        assert set(d) == spec()["match"]["documents"]


def test_restate_matches_the_documented_keys(ws, gct, make_file):
    from test_match import WHO
    from test_restate import cp2, record

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    check("restate list", gct("restate", "list", "--json").data)
    a, b, restated, original = cp2(gct, make_file)
    check("restate list", gct("restate", "list", "--json").data)
    check("restate list", gct("restate", "list", "--state", "same", "--json").data)
    check("restate record", record(gct, original, restated, "--json").data)
    check("restate show", gct("restate", "show", restated, "--json").data)
    check("restate show", gct("restate", "show", original, "--json").data)
    check("restate withdraw", gct("restate", "withdraw", "--original", original, "--restated", restated, *WHO,
                                  "--json").data)
    for p in gct("restate", "list", "--json").data["pairs"]:
        assert set(p["a"]) == set(p["b"]) == {
            "claim_id", "claim_version_id", "document_id", "page_number", "locator", "period_start", "period_end",
            "value_text", "unit_text", "unit_key", "number", "value_base", "link", "comparable", "reason", "review"}
    shown = gct("series", "list", "--json").data
    check("series list", shown)
    assert all(set(q) == {"claim", "state", "reason", "restatement"} for s in shown["series"] for p in s["points"]
               for q in p["pairs"])


def test_highlight_matches_the_documented_keys(ws, gct, make_file):
    from test_match import SCOPE_1, ids
    from test_restate import add

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")
    doc = add(gct, make_file, "a.pdf", [SCOPE_1])
    gct("read")
    gct("extract")
    claim = ids(gct, doc)[(SCOPE_1[0], "FY 2024-25")]
    version = gct("claims", "history", claim, "--json").data["versions"][-1]["id"]
    check("highlight list", gct("highlight", "list", claim, "--json").data)
    check("highlight add", gct("highlight", "add", claim, "--version", version, "--note", "n", "--as", "ana",
                               "--capacity", "c", "--json").data)
    listed = gct("highlight", "list", claim, "--json").data
    check("highlight list", listed)
    entry = spec()["highlight add"]["entry"]
    assert [set(h) for v in listed["versions"] for h in v["highlights"]] == [entry]


def test_review_matches_the_documented_keys(ws, gct, make_file):
    from test_match import SCOPE_1, ids
    from test_restate import add
    from test_review import rec

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana", "--organisation", "Acme audit")
    doc = add(gct, make_file, "a.pdf", [SCOPE_1])
    gct("read")
    gct("extract")
    claim = ids(gct, doc)[(SCOPE_1[0], "FY 2024-25")]
    version = gct("claims", "history", claim, "--json").data["versions"][-1]["id"]
    check("review list", gct("review", "list", claim, "--json").data)
    check("review company", rec(gct, "company", claim, version, "accepted", "--evidence-doc", doc, "--evidence-page", 1,
                                "--json").data)
    check("review auditor", rec(gct, "auditor", claim, version, "disputed", "--json").data)
    listed = gct("review", "list", claim, "--json").data
    check("review list", listed)
    entry = spec()["review company"]["entry"]
    (v,) = listed["versions"]
    assert v["disagreement"] == {"company": ["accepted"], "auditor": ["disputed"]}
    assert all(set(e) == entry for e in v["company_confirmations"] + v["auditor_reviews"])
    h = gct("claims", "history", claim, "--json").data
    check("claims history", h)
    assert all(set(e) == entry for x in h["versions"] for e in x["company_confirmations"] + x["auditor_reviews"])


def test_review_pending_matches_the_documented_keys(ws, gct, make_file):
    from test_match import WHO
    from test_restate import cp2
    from test_review import rec

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    check("review pending", gct("review", "pending", "--json").data)
    _, _, restated, original = cp2(gct, make_file)
    version = gct("claims", "history", restated, "--json").data["versions"][-1]["id"]
    assert rec(gct, "auditor", restated, version).code == 0
    assert gct("flag", "raise", restated, "--version", version, *WHO).code == 0
    assert gct("correct", restated, "--value", "1,101", *WHO).code == 0
    shown = gct("review", "pending", "--json").data
    check("review pending", shown)
    assert [k["kind"] for k in shown["kinds"]][-2:] == ["auditor review", "reviewer flag"]
    assert all(set(e) == {"claim", "document", "company", "version", "entry", "renew"} and set(e["entry"]) == {
        "kind", "id", "version"} for k in shown["kinds"] for e in k["entries"])
    h = gct("claims", "history", restated, "--json").data
    check("claims history", h)
    flags = set(spec()["flag list"]["flags"])
    assert [set(f) for v in h["versions"] for f in v["reviewer_flags"]] == [flags]
    check("restate show", gct("restate", "show", restated, "--json").data)


def test_adjudicate_and_flag_match_the_documented_keys(ws, gct, make_file):
    from test_match import WHO
    from test_restate import QUOTE, cp2

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    for command, argv in (("adjudicate list", ["list"]), ("adjudicate status", ["status"])):
        check(command, gct("adjudicate", *argv, "--json").data)
    check("flag list", gct("flag", "list", "--json").data)
    _, _, restated, original = cp2(gct, make_file)
    record = gct("adjudicate", "record", original, restated, "--state", "extraction-error", "--procedure", "p", *WHO,
                 "--json").data
    check("adjudicate record", record)
    shown = gct("adjudicate", "list", "--json").data
    check("adjudicate list", shown)
    entry = set(spec()["adjudicate record"]["adjudication"])
    assert [set(x) for c in shown["candidates"] for x in c["adjudications"]] == [entry]
    check("adjudicate status", gct("adjudicate", "status", "--json").data)
    r = record["adjudication"]
    v = {r["low_claim"]: r["low_version"], r["high_claim"]: r["high_version"]}[restated]
    check("flag raise", gct("flag", "raise", restated, "--version", v, *WHO, "--json").data)
    check("flag withdraw", gct("flag", "withdraw", restated, "--version", v, *WHO, "--json").data)
    check("flag list", gct("flag", "list", "--json").data)
    assert gct("restate", "record", "--original", original, "--restated", restated, "--page", 1, "--quote", QUOTE,
               *WHO).code == 0
    later = gct("adjudicate", "list", "--json").data
    check("adjudicate list", later)
    assert len(later["earlier"]) == 1


def test_sheet_commands_match_the_documented_keys(ws, gct, make_file):
    from test_match import ready
    from test_sheet import MAP, ROWS, WHO, add, csv_bytes, report, xlsx

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    add(gct, make_file, "r.pdf", report([["Total Scope 1 emissions", "tCO2e", "1,234", "1,100"]]))
    doc = add(gct, make_file, "m.csv", csv_bytes(ROWS))
    add(gct, make_file, "b.xlsx", xlsx({"Fuel": [["Fuel", "Litres"], ["Diesel", 120]]}))
    check("sheet show", gct("sheet", "show", doc, "--json").data)
    check("sheet map", gct("sheet", "map", doc, "--sheet", "m", *MAP, "--year-end", "03-31", "--boundary-is", "standalone",
                           *WHO, "--json").data)
    check("sheet show", gct("sheet", "show", doc, "--json").data)
    gct("read")
    extracted = gct("extract", "--json").data
    check("extract", extracted)
    assert [d["action"] for d in extracted["documents"]] == ["extracted", "extracted", "skipped"]
    ready(gct)
    check("claims list", gct("claims", "list", "--doc", doc, "--json").data)
    check("claims history", gct("claims", "history", 3, "--json").data)
    sid = gct("series", "list", "--metric", "ghg_scope_1", "--json").data["series"][0]["id"]
    check("series show", gct("series", "show", sid, "--all", "--json").data)
    n = next(r["id"] for r in gct("run", "list", "--json").data["runs"] if r["command"] == "sheet")
    assert set(gct("run", "retry", n, "--json").data) == {"status", "run_id", "of_run", "documents"}


def test_approve_and_model_match_the_documented_keys(tmp_path, gct, monkeypatch):
    from gct.models import redact

    models = tmp_path / "models.toml"
    models.write_text('[adapters.ollama]\nprovider = "openai_chat"\nbase_url = "http://127.0.0.1:11434/v1"\n'
                      'model = "qwen2.5vl:7b"\nexternal = false\npaid = false\n')
    monkeypatch.setenv("GCT_MODELS", str(models))
    redact._names.cache_clear()
    ws = tmp_path / "ws"
    gct("workspace", "init", ws)
    w = ("--workspace", ws)
    check("approve list", gct("approve", "list", *w, "--json").data)
    check("approve spend", gct("approve", "spend", "50", *w, "--json").data)
    check("approve transfer", gct("approve", "transfer", "ollama", *w, "--json").data)
    check("approve list", gct("approve", "list", *w, "--json").data)
    check("model list", gct("model", "list", "--json").data)


def test_serve_matches_the_documented_keys(tmp_path, gct, monkeypatch):
    from gct.api import server

    monkeypatch.setattr(server.Server, "wait", lambda self: None)
    ws = tmp_path / "ws"
    gct("workspace", "init", ws)
    check("serve", gct("serve", "--port", 0, "--no-open", "--workspace", ws, "--json").data)


def test_empty_lists_still_match(tmp_path, gct):
    ws = tmp_path / "ws"
    gct("workspace", "init", ws)
    check("company list", gct("company", "list", "--workspace", ws, "--json").data)
    check("doc list", gct("doc", "list", "--workspace", ws, "--json").data)
    check("run list", gct("run", "list", "--workspace", ws, "--json").data)
    check("workspace status", gct("workspace", "status", "--workspace", ws, "--json").data)
    check("approve list", gct("approve", "list", "--workspace", ws, "--json").data)
    check("model list", gct("model", "list", "--json").data)


def test_resume_and_retry_match_the_documented_keys(tmp_path, gct, make_file, monkeypatch):
    from gct.stages import read

    ws = tmp_path / "ws"
    gct("workspace", "init", ws)
    w = ("--workspace", ws)
    gct("company", "add", "Acme", *w)
    gct("doc", "add", make_file("b.pdf", make_pdf([{}, {}, {}])), "--company", "Acme", *w)
    real = read.read_page

    def failing(number, error):
        def flaky(page):
            if page.page_number == number:
                raise error
            return real(page)
        monkeypatch.setattr(read, "read_page", flaky)

    failing(2, KeyboardInterrupt)
    try:
        gct("read", *w)
    except KeyboardInterrupt:
        pass
    failing(3, ValueError)
    partial = gct("run", "resume", 2, *w, "--json").data
    assert partial["status"] == "partial"
    check("run resume", {k: v for k, v in partial.items() if k not in ("cause", "next_action")})
    monkeypatch.setattr(read, "read_page", real)
    check("run retry", gct("run", "retry", 3, *w, "--json").data)
    check("run retry", gct("run", "retry", 3, *w, "--json").data)
    doc_add = spec()["doc add"]["top"] | {"run_id", "of_run"}
    gone = tmp_path / "src" / "later.pdf"
    gct("doc", "add", gone, "--company", "Acme", *w)
    gone.write_bytes(PDF + b"later")
    assert set(gct("run", "retry", 5, *w, "--json").data) == doc_add
    assert set(gct("run", "retry", 5, *w, "--json").data) == {"status", "run_id", "of_run", "items"}


def test_archive_and_restore_match_the_documented_keys(ws, gct, make_file):
    from test_match import SCOPE_1, WHO, add, ready

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    a = add(gct, make_file, "a.pdf", [SCOPE_1])
    add(gct, make_file, "b.pdf", [["Total Scope 1 emissions", "tCO2e", "1,150"]], periods=("FY 2023-24",))
    ready(gct)
    plan = gct("doc", "archive", a, "--plan", "--json").data
    check("doc archive", plan)
    (s,), (p,) = plan["impact"]["series"], plan["impact"]["same_period_sets"]
    assert set(s) == {"id", "metric_key", "label", "unit_family", "reporting_boundary", "points", "points_left"}
    assert set(p) == {"series", "period_start", "period_end", "points", "points_left"}
    check("doc show", gct("doc", "show", a, "--json").data)
    check("doc archive", gct("doc", "archive", a, *WHO, "--json").data)
    check("doc show", gct("doc", "show", a, "--json").data)
    check("doc list", gct("doc", "list", "--active", "--json").data)
    check("claims history", gct("claims", "history", 1, "--json").data)
    check("doc restore", gct("doc", "restore", a, *WHO, "--json").data)


def test_delete_matches_the_documented_keys(ws, gct, make_file):
    from test_match import SCOPE_1, WHO, add, ready

    gct("company", "add", "Acme")
    gct("contributor", "add", "ana", "--name", "Ana")
    a = add(gct, make_file, "a.pdf", [SCOPE_1])
    ready(gct)
    plan = gct("doc", "delete", a, "--json")
    assert plan.code == 4 and plan.data["status"] == "plan"
    check("doc delete", plan.data)
    assert set(plan.data["document"]) == spec()["doc show"]["document"]
    assert set(plan.data["impact"]) == spec()["doc archive"]["impact"]
    assert set(plan.data["files"]) == {"files", "artifacts", "renders"}
    done = gct("doc", "delete", a, "--confirm", plan.data["token"], *WHO, "--json").data
    check("doc show", done)
    assert set(done["deletion"]) == {"at", "steps", "pending", "records"}
    check("doc show", gct("doc", "show", a, "--json").data)
    check("doc list", gct("doc", "list", "--active", "--json").data)
    check("claims history", gct("claims", "history", 1, "--json").data)


def test_view_records_matches_the_documented_keys(tmp_path, gct):
    import gate_fixture

    root = gate_fixture.build(tmp_path / "gws")
    check("view records", gct("view", "records", "--workspace", root, "--json").data)
    check("view records", gct("view", "records", "--filter", '{"text": "zzz"}', "--workspace", root, "--json").data)


def test_saved_views_and_questions_match_the_documented_keys(tmp_path, gct):
    import gate_fixture

    root = gate_fixture.build(tmp_path / "gws")
    w = ("--workspace", root, "--json")
    check("view list", gct("view", "list", *w).data)
    check("view save", gct("view", "save", "v", "--filter", '{"company": [1]}', "--as", "ana", *w).data)
    check("view save", gct("view", "save", "v", "--filter", "{}", "--as", "ana", *w).data)
    check("view list", gct("view", "list", *w).data)
    check("view open", gct("view", "open", "v", *w).data)
    check("view questions", gct("view", "questions", *w).data)
    check("view remove", gct("view", "remove", "v", "--as", "ana", *w).data)
    check("view list", gct("view", "list", *w).data)


def test_doc_label_and_the_doc_add_label_match_the_documented_keys(tmp_path, gct, make_file):
    ws = tmp_path / "ws"
    gct("workspace", "init", ws)
    w = ("--workspace", ws, "--json")
    gct("company", "add", "Acme", *w)
    gct("company", "add", "Beta", *w)
    gct("contributor", "add", "ana", "--name", "Ana", *w)
    f = make_file("a.pdf", PDF)
    check("doc add", gct("doc", "add", f, "--company", "Acme", "--availability", "public", *w).data)
    check("doc add", gct("doc", "add", f, "--company", "Acme", "--plan", *w).data)  # duplicate, label not applied
    check("doc add", gct("doc", "add", f, "--company", "Beta", *w).data)  # same file, another label: warning
    who = ("--as", "ana", "--capacity", "analyst", "--rationale", "checked the website")
    check("doc label", gct("doc", "label", 1, "--privacy", "private", *who, *w).data)
    check("doc label", gct("doc", "label", 1, "--availability", "internal", *who, *w).data)
    check("doc show", gct("doc", "show", 1, *w).data)
    check("error", gct("doc", "label", 1, "--availability", "internal", *who, *w).data)


def test_package_preview_and_create_match_the_documented_keys(tmp_path, gct, make_file):
    ws = tmp_path / "ws"
    gct("workspace", "init", ws)
    w = ("--workspace", ws, "--json")
    gct("company", "add", "Acme", *w)
    gct("doc", "add", make_file("a.pdf", PDF), "--company", "Acme", "--privacy", "shareable", *w)
    gct("doc", "add", make_file("b.pdf", PDF + b"b"), "--company", "Acme", *w)
    gct("publish", "build", *w)
    for flags in ((), ("--complete",), ("--include", "identity,flags")):
        check("package preview", gct("package", "preview", *flags, *w).data)
    token = gct("package", "preview", *w).data["token"]
    check("package create", gct("package", "create", "--confirm", token, *w).data)
    check("error", gct("package", "create", "--confirm", token, "--complete", *w).data)


def test_report_preview_matches_the_documented_keys(tmp_path, gct):
    import gate_fixture

    root = gate_fixture.build(tmp_path / "gws")
    w = ("--workspace", root, "--json")
    for extra in ((), ("--complete",), ("--include", "flags,identity"), ("--filter", '{"document": [2]}')):
        r = gct("report", "preview", *extra, *w)
        assert r.code == 0, r.out
        check("report preview", r.data)
    check("error", gct("report", "preview", "--data-version", 9, *w).data)


def test_report_exports_match_the_documented_keys(tmp_path, gct):
    import gate_fixture

    root = gate_fixture.build(tmp_path / "gws")
    w = ("--workspace", root, "--json")
    for name in ("evidence-index", "restatement-log", "gap-report", "all"):
        for extra in ((), ("--complete",), ("--include", "flags,identity"), ("--filter", '{"document": [2]}')):
            r = gct("report", name, "--format", "json", *extra, *w)
            assert r.code == 0, r.out
            check(f"report {name}", r.data)
        check("error", gct("report", name, "--format", "xlsx", *w).data)
        check("error", gct("report", name, "--format", "json", "--data-version", 9, *w).data)


def test_every_command_has_a_documented_section():
    assert set(spec()) == {
        "workspace init", "company add", "company list", "doc add", "doc list", "doc show", "doc archive", "doc restore",
        "doc delete", "doc label",
        "doc pages", "read", "extract", "link", "claims list",
        "claims history", "correct",
        "infer", "infer bases", "infer scope", "infer groups", "infer accept", "infer resolve", "infer reject",
        "match", "match metrics", "match review", "match link", "match unlink", "match status", "series list",
        "series show", "restate list", "restate show", "restate record", "restate withdraw", "review company", "review auditor", "review list", "review pending", "sheet show", "sheet map",
        "adjudicate list", "adjudicate record", "adjudicate status", "flag raise", "flag withdraw", "flag list",
        "highlight add", "highlight list", "contributor add", "contributor edit", "contributor list", "expect add", "expect list", "pages accept", "gap confirm",
        "publish build", "publish restore", "publish status", "package preview", "package create", "view records", "view save", "view list", "view open",
        "view remove", "view questions", "report preview", "report evidence-index", "report restatement-log",
        "report gap-report", "report all",
        "workspace status", "run list", "run show", "run resume", "run retry", "serve", "error",
        "approve spend", "approve transfer", "approve list", "model list", "measure g2",
    }
