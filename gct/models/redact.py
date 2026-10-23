"""scrub(): replace credentials with [redacted] before text reaches a log, an error, the run log or a model.

Imports nothing from gct at module level: layout, runs and stages import this module."""
import functools
import os
import re

MARK = "[redacted]"
# Prose: "Bearer" and any token (as before), and in any case a credential-shaped token (16 or more token characters)
# after "bearer", joined or apart by spaces, brackets or the marks match.label_of drops; "the bearer of" stays
PATTERNS = re.compile(r'(?i:(?<![A-Za-z0-9])(?:sk|nvapi)-[A-Za-z0-9_-]{16,})|Bearer\s+[^\s"]+'
                      r'|(?i:bearer)[\s()\[\]{}#*†]*[A-Za-z0-9._~+/=-]{16,}')
# Key text (a series key, a group key, a unit family, a series label) is machine text that match.label_of lowercases
# and match.unit_text_of joins: "bearer" with any token after it, spaced or joined, is a credential there
KEY_PATTERN = re.compile(r'bearer\s*[A-Za-z0-9._~+/=-]+', re.I)


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
            text = re.sub(re.escape(value), MARK, text, flags=re.I)
    return PATTERNS.sub(MARK, text)


def scrub_key(text):
    """scrub, then the key rule: for the text of a key or a label built from claim text, never prose."""
    return text and KEY_PATTERN.sub(MARK, scrub(text))
