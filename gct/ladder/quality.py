"""Per-page quality checks over a reading dict. A flag is recorded and counted; nothing escalates yet."""
import re

FRAGMENT_MIN_TOKENS = 20
FRAGMENT_MAX_LEN = 2
FRAGMENT_SHARE = 0.5
SPARSE_SHARE = 0.5


def thresholds() -> tuple:
    return FRAGMENT_MIN_TOKENS, FRAGMENT_MAX_LEN, FRAGMENT_SHARE, SPARSE_SHARE


def no_text(reading: dict) -> bool:
    return not reading["words"]


def fragmented_text(reading: dict) -> bool:
    tokens = [w["text"] for w in reading["words"] if re.fullmatch(r"[^\W\d_]+", w["text"])]
    short = sum(len(t) <= FRAGMENT_MAX_LEN for t in tokens)
    return len(tokens) >= FRAGMENT_MIN_TOKENS and short > FRAGMENT_SHARE * len(tokens)


def sparse_tables(reading: dict) -> bool:
    cells = [c for t in reading["tables"] for row in t["rows"] for c in row]
    empty = sum(c is None or not str(c).strip() for c in cells)
    return bool(reading["tables"]) and empty > SPARSE_SHARE * len(cells)


CHECKS = {"no_text": no_text, "fragmented_text": fragmented_text, "sparse_tables": sparse_tables}


def check(reading: dict) -> list[str]:
    return [code for code, fn in CHECKS.items() if fn(reading)]

