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


def test_every_command_has_a_documented_section():
    assert set(spec()) == {
        "workspace init", "company add", "company list", "doc add", "doc list", "doc show", "doc pages", "read", "extract", "claims list",
        "publish build", "publish restore", "publish status",
        "workspace status", "run list", "run show", "run resume", "run retry", "serve", "error",
        "approve spend", "approve transfer", "approve list", "model list",
    }
