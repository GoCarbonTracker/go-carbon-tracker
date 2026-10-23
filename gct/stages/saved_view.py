"""Saved views and guided questions (story 6.4 part A, FR45, FR46, AD-18, E6-D6, E6-D11). A saved view is a name, the
normalised filter (story 6.1 F1) and the section it opens; it stores no claims and no data version, so it is answered on
the current version and takes in claims of reports added later. Rows are insert-only: the newest row per name decides,
and a removal is a row too. A guided question is a fixed saved view shipped with gct. Nothing here builds a version or
opens a run; saved_view is never published."""
import json
import shlex
import unicodedata

from gct.stages import view
from gct.stages.missing import contributor
from gct.workspace import store
from gct.workspace.layout import NOT_FOUND, USAGE, GctError

SECTIONS = ("tables", "graphs")
MAX_NAME = 80
SERIES_QUESTION = "metric-over-time"
# (key, the question as shown, its filter, the section it opens); E6-D6 with note W7's wording of the second.
QUESTIONS = (
    ("restated", "Which figures were restated?", {"comparison": ["restatement"]}, "graphs"),
    ("different-values", "Where do two reports give different values for the same figure and period, with no"
                         " restatement recorded?", {"comparison": ["unresolved"]}, "graphs"),
    (SERIES_QUESTION, "How did one figure change across reports?", {"match": ["series"]}, "graphs"),
    ("not-matched-to-source", "Which figures could not be matched to their place in the source?",
     {"evidence": ["cited", "unresolved"]}, "tables"),
    ("ledgers-disagree", "Where do the company confirmation and the auditor review disagree?",
     {"review": ["disagreement"]}, "graphs"),
    ("needs-renewed-review", "Which figures need renewed review after a correction?", {"review": ["needs-re-review"]},
     "tables"),
)

# Every row of one name with the newest first, its contributor as recorded.
ROWS = """
SELECT s.*, c.name AS who FROM saved_view s JOIN contributor_version c ON c.id = s.contributor_version_id
WHERE s.name = ? ORDER BY s.id DESC
"""


def _name(name) -> str:
    """The name as typed, trimmed: 1 to 80 characters on one line."""
    name = (name or "").strip()
    example = 'for example "Scope 1 by year"'
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        raise GctError(USAGE, "The saved view name has a line break or another control character.",
                       f"Give a name on one line, {example}.")
    if not name:
        raise GctError(USAGE, "The saved view name is empty.", f"Give a name, {example}.")
    if len(name) > MAX_NAME:
        raise GctError(USAGE, f"The saved view name is longer than {MAX_NAME} characters.",
                       f"Give a name of at most {MAX_NAME} characters.")
    return name


def _newest(conn, name: str) -> list:
    """Every row of the name, newest first; refused when there is none or the newest is a removal."""
    rows = conn.execute(ROWS, (name,)).fetchall()
    if not rows:
        raise GctError(NOT_FOUND, f"There is no saved view named {name}.", "See the saved views with: gct view list")
    if rows[0]["action"] == "remove":
        raise GctError(NOT_FOUND, f"Saved view {name} was removed on {rows[0]['created_at'][:10]}.",
                       f"Save it again with: gct view save {shlex.quote(name)} --filter JSON --as KEY")
    return rows


def _view(rows: list) -> dict:
    r = rows[0]
    return {"name": r["name"], "filter": json.loads(r["filter"]), "section": r["section"], "contributor": r["who"],
            "saved_at": r["created_at"], "earlier": sum(1 for x in rows[1:] if x["action"] == "save")}


def get(conn, name) -> dict:
    """The newest save of a view."""
    return _view(_newest(conn, _name(name)))


def listing(conn) -> dict:
    """The views whose newest row is a save, by name, and how many names are removed."""
    names = [n for (n,) in conn.execute("SELECT DISTINCT name FROM saved_view ORDER BY name")]
    newest = {n: conn.execute(ROWS, (n,)).fetchall() for n in names}
    return {"views": [_view(rows) for rows in newest.values() if rows[0]["action"] == "save"],
            "hidden": sum(1 for rows in newest.values() if rows[0]["action"] == "remove")}


def save(conn, name, flt, section, key) -> dict:
    """One save row: the name, the normalised filter and the section. A filter matching nothing today is saved."""
    name, flt = _name(name), view.normalise(flt)
    if section not in SECTIONS:
        raise GctError(USAGE, f"The section {section} is not tables or graphs.",
                       "Choose tables (the default) or graphs, the tab the view opens.")
    who = contributor(conn, key)
    with store.transaction(conn):
        conn.execute("INSERT INTO saved_view (name, action, filter, section, contributor_version_id, created_at)"
                     " VALUES (?, 'save', ?, ?, ?, ?)", (name, json.dumps(flt), section, who["version"], store.now()))
    return {"view": get(conn, name)}


def remove(conn, name, key) -> dict:
    """One remove row: the view leaves the list; its save rows stay."""
    name = _name(name)
    _newest(conn, name)
    who = contributor(conn, key)
    at = store.now()
    with store.transaction(conn):
        conn.execute("INSERT INTO saved_view (name, action, contributor_version_id, created_at)"
                     " VALUES (?, 'remove', ?, ?)", (name, who["version"], at))
    return {"removed": {"name": name, "contributor": who["name"], "removed_at": at}}


def questions(pconn) -> dict:
    """The guided questions with their counts on one version (6.1 F2). metric-over-time also lists its choices, the
    series with two or more periods; its count is the number of choices."""
    out = []
    for key, text, flt, section in QUESTIONS:
        flt = view.normalise(flt)
        choices = []
        if key == SERIES_QUESTION:
            choices = [{"series": s, "company": company, "label": label or metric, "periods": periods,
                        "filter": {"series": [s]}}
                       for s, company, label, metric, periods in pconn.execute(
                           "SELECT s.id, m.name, s.label, s.metric_key, s.periods FROM series s JOIN company m"
                           " ON m.id = s.company_id WHERE s.periods >= 2 ORDER BY m.name, s.label, s.metric_key, s.id")]
        out.append({"key": key, "text": text, "filter": flt, "section": section,
                    "matched": len(view.select(pconn, flt)), "choices": choices})
    return {"data_version": view._version(pconn), "questions": out}
