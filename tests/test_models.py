import json
import sqlite3
import urllib.request

import pytest

from conftest import make_pdf
from gct.models import adapters, policy, redact
from gct.models.adapters import Request
from gct.stages import Result, SentFailure, Stage, run_stage
from gct.workspace import layout, registry, runs, store
from gct.workspace.layout import GctError

KEY = "testkey-abc123xyz"  # not shaped like sk- or nvapi-, so only the configured-name path can redact it

OLLAMA = """
[adapters.ollama]
provider = "openai_chat"
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5vl:7b"
external = false
paid = false
"""
NVIDIA = """
[adapters.nvidia]
provider = "openai_chat"
base_url = "https://integrate.api.nvidia.com/v1"
model = "meta/llama-3.2-90b-vision-instruct"
external = true
paid = false
api_key_env = "NVIDIA_API_KEY"
"""
PAID = """
[adapters.paid]
provider = "openai_chat"
base_url = "https://api.example.com/v1"
model = "big"
external = true
paid = true
price_in = 1.0
price_out = 2.0
api_key_env = "GCT_TEST_KEY"
"""
OK = {"choices": [{"message": {"content": "ok"}}]}


@pytest.fixture
def models(tmp_path, monkeypatch):
    def write(text=OLLAMA + NVIDIA + PAID):
        path = tmp_path / "models.toml"
        path.write_text(text)
        monkeypatch.setenv("GCT_MODELS", str(path))
        redact._names.cache_clear()
        return path

    return write


class Calls(list):
    answer = (200, OK)


@pytest.fixture
def sent(monkeypatch):
    """Replaces the transport: records each call, answers with sent.answer."""
    calls = Calls()

    def post(url, headers, body, timeout=120.0):
        calls.append({"url": url, "headers": headers, "body": body})
        return calls.answer

    monkeypatch.setattr(adapters, "_post", post)
    return calls


@pytest.fixture
def conn(ws):
    c = store.connect(ws / layout.DB_NAME)
    yield c
    c.close()


def req(tokens_in, max_tokens=1, text="hello"):
    return Request([{"role": "user", "content": text}], max_tokens, tokens_in)


def through_stage(conn, run_id, adapter, request, item, private=True):
    def work(_, c):
        r = policy.call(c, run_id, adapter, request, private=private)
        return Result(output=r.text, method=adapter.name, cost_estimated=r.cost_estimated, cost_confirmed=r.cost_confirmed)

    return run_stage(conn, run_id, Stage("model", "c1", work, lambda _: "v1"), [item])


def refused(conn, run_id, adapter, request, private=True) -> str:
    with pytest.raises(GctError) as e:
        policy.call(conn, run_id, adapter, request, private=private)
    assert e.value.code == 4
    return e.value.cause


# AC 1
def test_migration_6_upgrades_a_version_5_workspace(tmp_path, gct):
    root = tmp_path / "old"
    root.mkdir()
    for name in layout.SUBDIRS:
        (root / name).mkdir()
    c = store.connect(root / layout.DB_NAME)
    assert store.migrate(c, up_to=5) == [1, 2, 3, 4, 5]
    c.execute("INSERT INTO workspace (id, created_at, gct_version) VALUES (1, 't', '0.0.0')")
    c.close()
    assert gct("approve", "list", "--workspace", root).code == 0
    c = store.connect(root / layout.DB_NAME)
    assert c.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 17
    (run,) = runs.list_runs(c)
    assert [e["message"] for e in runs.show_run(c, run["id"])["events"]] == [
        "applied migration 6", "applied migration 7", "applied migration 8", "applied migration 9", "applied migration 10", "applied migration 11", "applied migration 12", "applied migration 13", "applied migration 14", "applied migration 15", "applied migration 16", "applied migration 17", None]
    c.close()


def test_approval_checks_and_append_only(ws, db, conn):
    rid = runs.start(conn, "t")
    sql = ("INSERT INTO approval (kind, provider, destination, run_id, amount, granted, created_at)"
           " VALUES (?, ?, ?, ?, ?, ?, 't')")
    for good in (("spend_cap", None, None, None, 0, 1), ("run_allowance", None, None, rid, 2.5, 1),
                 ("transfer", "x", "d", None, None, 0)):
        db.execute(sql, good)
    for bad in (
        ("other", None, None, None, 1, 1),  # unknown kind
        ("transfer", None, "d", None, None, 1), ("spend_cap", "x", None, None, 1, 1),  # provider exactly for transfer
        ("transfer", "x", None, None, None, 1), ("spend_cap", None, "d", None, 1, 1),  # destination exactly for transfer
        ("run_allowance", None, None, None, 1, 1), ("spend_cap", None, None, rid, 1, 1),  # run exactly for run_allowance
        ("spend_cap", None, None, None, None, 1), ("transfer", "x", "d", None, 1, 1),  # amount exactly for spend kinds
        ("spend_cap", None, None, None, -1, 1),  # amount >= 0
        ("transfer", "x", "d", None, None, 2), ("spend_cap", None, None, None, 1, 0),  # granted
        ("run_allowance", None, None, rid, 1, 0),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(sql, bad)
    for stmt in ("UPDATE approval SET amount = 1", "DELETE FROM approval"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only table"):
            db.execute(stmt)


# AC 2
def test_spend_cap_newest_wins(ws, db, conn, gct):
    assert gct("approve", "list").out == "No estimated spending limit. Paid work is off.\n"
    assert gct("approve", "spend", "50").out == "Estimated spending limit set to $50.00 (estimated spend so far $0.00).\n"
    r = gct("approve", "spend", "20", "--json")
    assert r.data == {"status": "ok", "cap": 20.0, "spent": 0.0}
    assert db.execute("SELECT COUNT(*) FROM approval WHERE kind = 'spend_cap'").fetchone()[0] == 2
    assert policy.cap(conn) == 20.0
    assert gct("approve", "list").out.startswith("Estimated spending limit $20.00, estimated spend $0.00")
    assert gct("approve", "list", "--json").data == {"status": "ok", "cap": 20.0, "spent": 0.0, "adapters": []}
    for bad in ("-1", "abc", "nan", "inf"):
        r = gct("approve", "spend", bad)
        assert r.code == 2 and "Traceback" not in r.err
    for bad in (-1, float("nan"), float("inf")):
        with pytest.raises(GctError) as e:
            policy.set_cap(conn, bad)
        assert e.value.code == 2
    assert db.execute("SELECT COUNT(*) FROM approval").fetchone()[0] == 2


# AC 3
def test_transfer_grant_revoke_grant(ws, db, conn, gct, models):
    path = models()
    assert gct("approve", "transfer", "nvidia").out == "nvidia may receive private content.\n"
    assert gct("approve", "transfer", "nvidia", "--revoke").out == "nvidia may no longer receive private content.\n"
    assert policy.transfer_granted(conn, adapters.get("nvidia")) is False
    assert "nvidia  external  free  transfer not granted" in gct("approve", "list").out
    assert gct("approve", "transfer", "nvidia", "--json").data == {"status": "ok", "provider": "nvidia", "granted": True}
    assert db.execute("SELECT COUNT(*) FROM approval WHERE kind = 'transfer'").fetchone()[0] == 3
    assert policy.transfer_granted(conn, adapters.get("nvidia")) is True
    lines = gct("approve", "list").out.splitlines()
    assert lines[1:] == ["ollama  local  free  transfer not granted", "nvidia  external  free  transfer granted",
                         "paid  external  paid  transfer not granted"]
    r = gct("approve", "transfer", "nobody", "--json")
    assert r.code == 3 and str(path) in r.data["next_action"]
    assert db.execute("SELECT COUNT(*) FROM approval").fetchone()[0] == 3
    # The grant was for this endpoint and model: changing either drops it until approved again.
    for changed in (NVIDIA.replace("integrate.api.nvidia.com", "other.example.com"), NVIDIA.replace("90b", "11b")):
        models(OLLAMA + changed + PAID)
        nvidia = adapters.get("nvidia")
        assert policy.transfer_granted(conn, nvidia) is False
        assert ("nvidia  external  free  transfer granted for a different endpoint or model, approve it again"
                in gct("approve", "list").out)
        assert gct("approve", "list", "--json").data["adapters"][1]["transfer_granted"] is False
        cause = refused(conn, runs.start(conn, "t"), nvidia, req(10))
        assert cause == ("nvidia was approved for a different endpoint or model. "
                         "Approve it again with: gct approve transfer nvidia")
        gct("approve", "transfer", "nvidia")
        assert policy.transfer_granted(conn, nvidia) is True


# AC 4
def test_transfer_check(ws, conn, models, sent, monkeypatch):
    models()
    monkeypatch.setenv("NVIDIA_API_KEY", KEY)
    a, rid = adapters.load(), runs.start(conn, "t")
    cause = refused(conn, rid, a["nvidia"], req(10))
    assert "nvidia" in cause and "gct approve transfer nvidia" in cause and sent == []
    assert policy.call(conn, rid, a["nvidia"], req(10), private=False).text == "ok"
    assert policy.call(conn, rid, a["ollama"], req(10), private=True).text == "ok"
    assert [c["url"] for c in sent] == ["https://integrate.api.nvidia.com/v1/chat/completions",
                                        "http://127.0.0.1:11434/v1/chat/completions"]
    assert conn.execute("SELECT COUNT(*) FROM approval").fetchone()[0] == 0


# AC 5
def test_spend_check_in_order(ws, conn, gct, models, sent, monkeypatch):
    models(PAID.replace("price_out = 2.0", "price_out = 0.0"))
    monkeypatch.setenv("GCT_TEST_KEY", KEY)
    paid = adapters.get("paid")
    gct("approve", "transfer", "paid")
    with runs.run(conn, "paid test") as rid:
        assert "No estimated spending limit" in refused(conn, rid, paid, req(1_500_000))
        gct("approve", "spend", "0")
        assert "$0.00" in refused(conn, rid, paid, req(1_500_000))
        gct("approve", "spend", "10")
        assert "no allowance" in refused(conn, rid, paid, req(1_500_000))
        for bad in (-1, float("nan"), float("inf")):
            with pytest.raises(GctError) as e:
                policy.allow_run(conn, rid, bad)
            assert e.value.code == 2
        with pytest.raises(GctError) as e:
            policy.allow_run(conn, rid, 15)
        assert e.value.code == 4 and "15.00" in e.value.cause and "10.00" in e.value.cause
        assert conn.execute("SELECT COUNT(*) FROM approval WHERE kind = 'run_allowance'").fetchone()[0] == 0
        policy.allow_run(conn, rid, 2)
        assert policy.allowance(conn, rid) == 2
        assert through_stage(conn, rid, paid, req(1_500_000), "a")["processed"] == 1
        assert len(sent) == 1 and policy.spent(conn, rid) == pytest.approx(1.5)
        cause = refused(conn, rid, paid, req(1_000_000))
        assert all(n in cause for n in ("2.00", "1.50", "1.00")) and "allowance" in cause and len(sent) == 1
        gct("approve", "spend", "1.60")
        cause = refused(conn, rid, paid, req(200_000))
        assert all(n in cause for n in ("1.60", "1.50", "0.20")) and "estimated spending limit" in cause and len(sent) == 1
        # Inside a stage the refusal is a failed attempt with the cause and no cost.
        assert through_stage(conn, rid, paid, req(200_000), "b")["failed"] == 1
    row = conn.execute("SELECT error, cost_estimated FROM attempt WHERE item = 'b'").fetchone()
    assert "1.60" in row["error"] and row["cost_estimated"] is None and len(sent) == 1
    assert conn.execute("SELECT COUNT(*) FROM approval").fetchone()[0] == 5  # transfer, 3 caps, 1 allowance
    with runs.run(conn, "sub-cent") as rid:  # amounts under a cent keep two significant digits
        policy.allow_run(conn, rid, 0.001)
        assert refused(conn, rid, paid, req(1200)) == (
            "This run's allowance of $0.0010 is used up (estimated spend $0.00, the next call is about $0.0012).")
    assert [policy.money(x) for x in (0, 0.0012, 0.01, 1.955, 5)] == ["$0.00", "$0.0012", "$0.01", "$1.96", "$5.00"]


# AC 6
def test_estimate_and_confirmed_cost_reach_the_attempt_and_run_show(ws, conn, gct, models, sent, monkeypatch):
    models()
    monkeypatch.setenv("GCT_TEST_KEY", KEY)
    paid = adapters.get("paid")
    request = Request([{"role": "user", "content": "x"}], 500, 1000)
    assert adapters.estimate(paid, request) == pytest.approx(0.002)
    assert adapters.estimate(adapters.get("ollama"), request) == 0
    for bad in (Request([], 0), Request([], 1.5), Request([], True), Request([], 10, -1), Request([], 10, float("nan"))):
        with pytest.raises(GctError) as e:
            adapters.estimate(paid, bad)
        assert e.value.code == 2
    gct("approve", "spend", "10")
    usage = {"prompt_tokens": 1000, "completion_tokens": 100}
    # Usage times the configured prices is a calculation: it replaces the estimate, it never confirms anything.
    sent.answer = (200, {**OK, "usage": usage})
    r = adapters.send(paid, request)
    assert (r.cost_estimated, r.cost_confirmed) == (pytest.approx(0.0012), None)
    # Only a cost figure the provider returned is confirmed.
    sent.answer = (200, {**OK, "usage": {**usage, "cost": 0.0011}})
    with runs.run(conn, "cost test") as rid:
        policy.allow_run(conn, rid, 1)
        through_stage(conn, rid, paid, request, "a", private=False)
    est, conf = conn.execute("SELECT cost_estimated, cost_confirmed FROM attempt").fetchone()
    assert (est, conf) == (pytest.approx(0.0012), pytest.approx(0.0011))
    (cost,) = [e for e in runs.show_run(conn, rid)["events"] if e["kind"] == "cost"]
    assert (cost["cost_estimated"], cost["cost_confirmed"]) == (pytest.approx(0.0012), pytest.approx(0.0011))
    out = gct("run", "show", rid).out
    assert "Estimated cost: 0.0012" in out and "Confirmed cost: 0.0011" in out
    assert policy.spent(conn, rid) == pytest.approx(0.0011)  # confirmed wins over the calculation
    sent.answer = (200, OK)
    with runs.run(conn, "no usage") as rid2:
        policy.allow_run(conn, rid2, 1)
        through_stage(conn, rid2, paid, request, "b", private=False)
    est, conf = conn.execute("SELECT cost_estimated, cost_confirmed FROM attempt WHERE item = 'b'").fetchone()
    assert (est, conf) == (pytest.approx(0.002), None)
    assert policy.spent(conn, rid2) == pytest.approx(0.002)
    assert policy.spent(conn) == pytest.approx(0.0031)


# AC 7
def test_failure_after_sending_counts_its_estimate(ws, conn, gct, models, sent, monkeypatch):
    models()
    monkeypatch.setenv("GCT_TEST_KEY", KEY)
    paid = adapters.get("paid")
    request = Request([{"role": "user", "content": "x"}], 500, 1000)
    sent.answer = (500, {"error": f"invalid key {KEY}"})
    with pytest.raises(SentFailure) as e:
        adapters.send(paid, request)
    assert e.value.cause.startswith("paid answered 500") and KEY not in e.value.cause
    sent.answer = (302, {})
    with pytest.raises(SentFailure, match="paid answered 302; redirects are not followed") as e:
        adapters.send(paid, request)
    assert e.value.cost_estimated == pytest.approx(0.002)
    handler = adapters._NoRedirects()
    req302 = urllib.request.Request("https://api.example.com/v1/chat/completions", b"{}")
    assert handler.redirect_request(req302, None, 302, "Found", {}, "https://elsewhere.example.com/") is None
    sent.answer = (500, {"error": f"invalid key {KEY}"})
    gct("approve", "spend", "10")
    with runs.run(conn, "fail test") as rid:
        policy.allow_run(conn, rid, 1)
        assert through_stage(conn, rid, paid, request, "a", private=False)["failed"] == 1
    error, est = conn.execute("SELECT error, cost_estimated FROM attempt").fetchone()
    assert est == pytest.approx(0.002) and "[redacted]" in error and KEY not in error
    (failure,) = [e for e in runs.show_run(conn, rid)["events"] if e["kind"] == "failure"]
    assert "[redacted]" in failure["message"] and KEY not in failure["message"]
    assert policy.spent(conn) == pytest.approx(0.002)


def test_unreachable_and_unreadable_answers_are_sent_failures(models, sent, monkeypatch):
    models()
    ollama = adapters.get("ollama")
    sent.answer = (200, {"nothing": 1})
    with pytest.raises(SentFailure, match="without a message"):
        adapters.send(ollama, req(10))
    paid = adapters.get("paid")
    monkeypatch.setenv("GCT_TEST_KEY", KEY)
    sent.answer = (200, {"choices": [{"message": {"content": "ok"}}], "usage": [1]})
    with pytest.raises(SentFailure, match="usage that is not an object") as e:
        adapters.send(paid, req(10))
    assert e.value.cost_estimated == adapters.estimate(paid, req(10)) > 0

    def not_json(*a, **k):  # what _post raises for a 2xx body such as a captive portal page
        return 200, json.loads(b"<html>captive portal</html>")

    monkeypatch.setattr(adapters, "_post", not_json)
    with pytest.raises(SentFailure, match="not JSON") as e:
        adapters.send(paid, req(10))
    assert e.value.cost_estimated == adapters.estimate(paid, req(10)) > 0

    def down(*a, **k):
        raise ConnectionRefusedError

    monkeypatch.setattr(adapters, "_post", down)
    with pytest.raises(SentFailure, match="ollama could not be reached"):
        adapters.send(ollama, req(10))


# AC 8
def test_credentials_never_leave_the_environment(ws, conn, gct, models, sent, monkeypatch):
    models()
    nvidia = adapters.get("nvidia")
    gct("approve", "transfer", "nvidia")
    rid = runs.start(conn, "t")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    assert "NVIDIA_API_KEY" in refused(conn, rid, nvidia, req(10)) and sent == []
    assert "key NVIDIA_API_KEY not set" in gct("model", "list").out
    monkeypatch.setenv("NVIDIA_API_KEY", KEY)
    policy.call(conn, rid, nvidia, Request([{"role": "user", "content": [
        {"type": "text", "text": f"my key is {KEY}"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}},
    ]}], 10), private=True)
    (call,) = sent
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"
    assert call["body"]["messages"][0]["content"][0]["text"] == "my key is [redacted]"
    assert call["body"]["messages"][0]["content"][1]["image_url"]["url"] == "data:image/png;base64,AA"
    text, data = gct("model", "list").out, gct("model", "list", "--json").out
    assert "key NVIDIA_API_KEY set" in text and KEY not in text + data
    sent.answer = (401, {"error": f"bad {KEY}"})
    through_stage(conn, rid, nvidia, req(10), "a")

    def boom(*a, **k):
        raise RuntimeError(f"leaked {KEY}")

    monkeypatch.setattr(registry, "list_companies", boom)
    assert gct("company", "list").code == 1
    (log,) = (ws / "logs").glob("error-*.log")
    assert "leaked [redacted]" in log.read_text() and KEY not in log.read_text()
    rows = conn.execute("SELECT error FROM attempt UNION ALL SELECT message FROM run_event").fetchall()
    assert any(r[0] and "[redacted]" in r[0] for r in rows) and not any(r[0] and KEY in r[0] for r in rows)


# AC 9
def test_configuration_loading(tmp_path, gct, models, monkeypatch):
    assert adapters.load() == {}
    r = gct("model", "list")
    assert r.code == 0 and r.out.startswith("No model adapters configured (looked for ") and "Rung 1" in r.out
    assert gct("model", "list", "--json").data["adapters"] == []
    models(OLLAMA + NVIDIA)
    a = adapters.load()
    assert set(a) == {"ollama", "nvidia"} and a["ollama"].external is False and a["nvidia"].api_key_env == "NVIDIA_API_KEY"
    assert a["ollama"].timeout == 120 and a["ollama"].price_in == 0
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    assert gct("model", "list").out.splitlines() == [
        "ollama  openai_chat  qwen2.5vl:7b  http://127.0.0.1:11434/v1  local  free  no key",
        "nvidia  openai_chat  meta/llama-3.2-90b-vision-instruct  https://integrate.api.nvidia.com/v1  external  free"
        "  key NVIDIA_API_KEY not set",
    ]
    for text, key in (
        (OLLAMA.replace("openai_chat", "other"), "provider"),
        (OLLAMA.replace('model = "qwen2.5vl:7b"\n', ""), "model"),
        (PAID.replace("price_in = 1.0\n", ""), "price_in"),
        (PAID.replace("price_in = 1.0", "price_in = -1"), "price_in"),
        (PAID.replace("price_out = 2.0", "price_out = nan"), "price_out"),
        (OLLAMA + "timeout = inf\n", "timeout"),
        (OLLAMA.replace("http://127.0.0.1:11434/v1", "https://example.com/v1"), "base_url"),
        (OLLAMA.replace("http://127.0.0.1", "file://127.0.0.1"), "base_url"),
        (OLLAMA.replace("external = false", 'external = "no"'), "external"),
        (OLLAMA.replace("http://127.0.0.1:11434/v1", "http://[bad/v1"), "base_url"),
        (NVIDIA.replace('"NVIDIA_API_KEY"', "5"), "api_key_env"),
        ("[adapters.x\n", "TOML"),
    ):
        path = models(text)
        r = gct("model", "list", "--json")
        assert r.code == 4 and key in r.data["cause"] and str(path) in r.data["cause"], (key, r.data)
    models(OLLAMA)
    with pytest.raises(GctError) as e:
        adapters.get("nobody")
    assert e.value.code == 3


# AC 10
def test_scrub_patterns(models, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", KEY)
    assert redact.scrub(f"key sk-{'a' * 16} and nvapi-{'B_-' * 6} here") == "key [redacted] and [redacted] here"
    assert redact.scrub("Authorization: Bearer x") == "Authorization: [redacted]"
    plain = "Scope 1 emissions rose; sk-short nvapi-short ask-me"
    assert redact.scrub(plain) == plain and redact.scrub(None) is None
    assert redact.scrub(f"value {KEY}") == f"value {KEY}"  # no file: patterns only
    models(NVIDIA)
    assert redact.scrub(f"value {KEY}") == "value [redacted]"
    monkeypatch.setenv("NVIDIA_API_KEY", "changed-later")  # names cached, values read live
    assert redact.scrub("value changed-later") == "value [redacted]"


# AC 11
def test_read_without_models_file_writes_no_approval(ws, db, gct, make_file):
    gct("company", "add", "Acme")
    gct("doc", "add", make_file("a.pdf", make_pdf([{"text": [(72, 72, "Scope 1")]}])), "--company", "Acme")
    assert gct("read").code == 0
    assert db.execute("SELECT COUNT(*) FROM approval").fetchone()[0] == 0
    assert {r[0] for r in db.execute("SELECT kind FROM run_event")} <= {"item", "output", "finished", "note"}
