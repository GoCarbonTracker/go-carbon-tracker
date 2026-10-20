"""scrub(): replace credentials with [redacted] before text reaches a log, an error, the run log or a model.

Imports nothing from gct at module level: layout, runs and stages import this module."""
import functools
import os
import re

MARK = "[redacted]"
PATTERNS = re.compile(r"sk-[A-Za-z0-9_-]{16,}|nvapi-[A-Za-z0-9_-]{16,}|Bearer\s+\S+")


@functools.lru_cache(maxsize=None)
def _names() -> tuple[str, ...]:
    """The api_key_env names in the configuration file, read once per process (tests clear the cache)."""
    from gct.models import adapters
    from gct.workspace.layout import GctError

    try:
        return tuple(a.api_key_env for a in adapters.load().values() if a.api_key_env)
    except GctError:  # an invalid file must not break error logging; the patterns still apply
        return ()


def scrub(text):
    if not text:
        return text
    for name in _names():
        if value := os.environ.get(name):  # read live, so a key set after the first call is still redacted
            text = text.replace(value, MARK)
    return PATTERNS.sub(MARK, text)
