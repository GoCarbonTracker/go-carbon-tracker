"""Model adapters are configuration: [adapters.NAME] tables in a TOML file outside every workspace, one wire (openai_chat)."""
import http.client
import json
import math
import os
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from gct.models.redact import scrub
from gct.stages import SentFailure, version_of
from gct.workspace.layout import NOT_FOUND, REFUSED, USAGE, GctError

LOOPBACK = ("127.0.0.1", "localhost", "::1")
REQUIRED = ("provider", "base_url", "model", "external", "paid")


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A 3xx comes back as an answer: neither the key nor the content ever reaches a second host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# No proxy from the environment and no redirects: the request goes only to the configured base_url.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirects)


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


@dataclass(frozen=True)
class Adapter:
    name: str
    provider: str
    base_url: str
    model: str
    external: bool
    paid: bool
    api_key_env: str | None = None
    price_in: float = 0.0
    price_out: float = 0.0
    timeout: float = 120.0


@dataclass
class Request:
    messages: list
    max_tokens: int
    tokens_in: int | None = None


@dataclass
class Response:
    text: str
    tokens_in: int | None
    tokens_out: int | None
    cost_estimated: float
    cost_confirmed: float | None


def path() -> Path:
    return Path(os.environ.get("GCT_MODELS") or Path.home() / ".config" / "gct" / "models.toml")


def _check(table: dict, name: str, file: Path) -> Adapter:
    def bad(key, problem):
        return GctError(REFUSED, f"{file}: adapters.{name}.{key} {problem}.", f"Correct {key} for {name} in {file}.")

    for key in REQUIRED:
        if key not in table:
            raise bad(key, "is missing")
    if table["provider"] != "openai_chat":
        raise bad("provider", f"is {table['provider']!r}; the only provider is 'openai_chat'")
    for key in ("external", "paid"):
        if not isinstance(table[key], bool):
            raise bad(key, "must be true or false")
    for key in ("base_url", "model"):
        if not isinstance(table[key], str):
            raise bad(key, "must be text")
    if "api_key_env" in table and not (isinstance(table["api_key_env"], str) and table["api_key_env"]):
        raise bad("api_key_env", "must be the name of an environment variable")
    try:
        url = urlparse(table["base_url"])
        host = url.hostname
    except ValueError:
        raise bad("base_url", "is not a valid address") from None
    if url.scheme not in ("http", "https"):
        raise bad("base_url", "must be an http or https address")
    if not table["external"] and host not in LOOPBACK:
        raise bad("base_url", f"points at {host}, which is not this computer, but external is false")
    for key in ("price_in", "price_out", "timeout"):
        if key in table and not _finite(table[key]):
            raise bad(key, "must be a finite number of 0 or more")
    if table["paid"] and not ("price_in" in table and "price_out" in table):
        raise bad("price_in" if "price_in" not in table else "price_out", "is missing; a paid adapter needs both prices")
    fields = ("api_key_env", "price_in", "price_out", "timeout")
    return Adapter(name=name, **{k: table[k] for k in (*REQUIRED, *fields) if k in table})


def load() -> dict[str, Adapter]:
    """{name: Adapter} from the configuration file; no file means no adapters."""
    file = path()
    if not file.is_file():
        return {}
    try:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except OSError:
        raise GctError(REFUSED, f"{file} could not be opened.", f"Correct {file}.") from None
    except UnicodeDecodeError:
        raise GctError(REFUSED, f"{file} is not UTF-8 text.", f"Correct {file}.") from None
    except tomllib.TOMLDecodeError as e:
        line = f" (line {e.lineno})" if getattr(e, "lineno", None) else ""  # Python 3.14 adds lineno
        raise GctError(REFUSED, f"{file} is not valid TOML{line}.", f"Correct {file}.") from None
    return {name: _check(table, name, file) for name, table in data.get("adapters", {}).items()}


def get(name: str) -> Adapter:
    adapters = load()
    if name not in adapters:
        raise GctError(NOT_FOUND, f"There is no model adapter named {name}.",
                       f"See the configured adapters with: gct model list (configuration file {path()})")
    return adapters[name]


def destination(adapter: Adapter) -> str:
    """What a transfer approval is given for: this endpoint and this model."""
    return version_of(adapter.base_url, adapter.model)


def estimate(adapter: Adapter, request: Request) -> float:
    m, t = request.max_tokens, request.tokens_in
    if not (isinstance(m, int) and not isinstance(m, bool) and m > 0) or (t is not None and not _finite(t)):
        raise GctError(USAGE, "The request needs a positive whole number of output tokens and a token count of 0 or more.",
                       "Correct the request before sending it.")
    if not adapter.paid:
        return 0.0
    tokens_in = request.tokens_in or len(json.dumps(request.messages)) / 4
    return tokens_in * adapter.price_in / 1e6 + request.max_tokens * adapter.price_out / 1e6


def _post(url: str, headers: dict, body: dict, timeout: float = 120.0) -> tuple[int, dict]:
    """The one transport call; tests replace it. Network errors propagate, an HTTP error returns its status."""
    req = urllib.request.Request(url, json.dumps(body).encode("utf-8"), {**headers, "Content-Type": "application/json"})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": raw}


def _scrubbed(message: dict) -> dict:
    content = message.get("content")
    if isinstance(content, str):
        return {**message, "content": scrub(content)}
    if isinstance(content, list):
        return {**message, "content": [{**p, "text": scrub(p["text"])} if "text" in p else p for p in content]}
    return message


def send(adapter: Adapter, request: Request) -> Response:
    """POST to {base_url}/chat/completions. Call it only through policy.call."""
    headers = {}
    if adapter.api_key_env:
        key = os.environ.get(adapter.api_key_env)
        if not key:
            raise GctError(REFUSED, f"The environment variable {adapter.api_key_env} that holds the key for {adapter.name} is not set.",
                           f"Set {adapter.api_key_env}, then run the command again.")
        headers["Authorization"] = f"Bearer {key}"
    cost = estimate(adapter, request)
    body = {"model": adapter.model, "messages": [_scrubbed(m) for m in request.messages], "max_tokens": request.max_tokens}
    retry = "Check the adapter in gct model list, then run the same command again."
    try:
        status, data = _post(adapter.base_url.rstrip("/") + "/chat/completions", headers, body, adapter.timeout)
    except (OSError, http.client.HTTPException):
        raise SentFailure(f"{adapter.name} could not be reached.", retry, cost_estimated=cost) from None
    except ValueError:  # a 2xx body that is not JSON: the call was sent, so its estimate counts
        raise SentFailure(f"{adapter.name} answered with something that is not JSON.", retry, cost_estimated=cost) from None
    if 300 <= status < 400:
        raise SentFailure(f"{adapter.name} answered {status}; redirects are not followed.", retry, cost_estimated=cost)
    if not 200 <= status < 300:
        detail = scrub(json.dumps(data))[:200]
        raise SentFailure(f"{adapter.name} answered {status}: {detail}", retry, cost_estimated=cost)
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise SentFailure(f"{adapter.name} answered without a message.", retry, cost_estimated=cost) from None
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        raise SentFailure(f"{adapter.name} answered with a usage that is not an object.", retry, cost_estimated=cost)
    tokens_in, tokens_out = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if _finite(tokens_in) and _finite(tokens_out):  # usage times configured prices: a calculation, not a bill
        cost = tokens_in * adapter.price_in / 1e6 + tokens_out * adapter.price_out / 1e6
    confirmed = usage.get("cost") if _finite(usage.get("cost")) else None  # only a figure the provider returned
    return Response(text, tokens_in, tokens_out, cost, confirmed)
