import re
from importlib import metadata

# Permissive licences only. Entries are matched as whole lowercase names or as a prefix
# followed by a space or hyphen, so "BSD-3-Clause" and "BSD License" both pass.
ALLOWED = ("mit", "bsd", "apache", "isc", "psf", "python software foundation", "python-2.0", "mit-cmu", "hpnd",
           "historical permission notice and disclaimer")
CLASSIFIER_PREFIX = "License :: OSI Approved :: "


def permitted(name: str) -> bool:
    name = name.strip().lower()
    return any(name == a or re.match(re.escape(a) + r"[ \-_.]", name) for a in ALLOWED)


def expression_ok(expr: str) -> bool:
    """'A AND B' needs every part allowed. 'A OR B' needs one alternative allowed."""
    expr = expr.replace("(", " ").replace(")", " ")
    return all(
        any(permitted(alt) for alt in re.split(r"\s+OR\s+", part, flags=re.I) if alt.strip())
        for part in re.split(r"\s+AND\s+", expr, flags=re.I)
        if part.strip()
    )


def licences_of(dist) -> list[str]:
    meta = dist.metadata
    if meta.get("License-Expression"):
        return [meta["License-Expression"]]
    classified = [c[len(CLASSIFIER_PREFIX):] for c in meta.get_all("Classifier") or [] if c.startswith(CLASSIFIER_PREFIX)]
    if classified:
        return classified
    text = (meta.get("License") or "").strip()
    return [text] if text and len(text) < 80 and "\n" not in text else []


def test_expression_rules():
    assert expression_ok("MIT")
    assert expression_ok("Apache-2.0 OR BSD-2-Clause")
    assert expression_ok("MIT AND (BSD-3-Clause OR Apache-2.0)")
    assert not expression_ok("GPL-3.0-only")
    assert not expression_ok("MIT AND AGPL-3.0-or-later")
    assert not expression_ok("AGPL-3.0-only OR GPL-3.0-only")


def test_installed_distributions_use_permissive_licences():
    bad = []
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        found = licences_of(dist)
        # Several old-style classifiers all describe the same package: one allowed entry is enough.
        if not found or not any(expression_ok(f) for f in found):
            bad.append((name, found))
    assert not bad, f"licence not on the permissive allowlist (or unreadable): {bad}"
