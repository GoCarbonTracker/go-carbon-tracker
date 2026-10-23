"""The viewer pages (story 7.5, form B): one HTML file per report the command names, written from the dataset alone.
A page holds no script and loads nothing from the network (its own policy: default-src 'none'; img-src 'self';
style-src 'unsafe-inline'), so it opens from disk in any browser. Its evidence images are crops.cut's bytes as they
are, written once each as crops/E<id>.png beside the pages. Layout provisional until practitioner feedback (U23).

Every string, GCT's own words included, goes through esc (html.escape with quote=True) and lands in a text node or
the one alt attribute; every id, href, src and file name is built from integer ids only. Standard library only, and
every file is opened with mode x (7.1 C4, C4b)."""
import html
import json
from pathlib import Path

REPORTS = ("evidence_index", "restatement_log", "gap_report")
SECTIONS = ("candidates", "expectations", "documents_checked", "extraction_limits", "archived", "deleted")
PAIRS = ("restatement_log", "candidates")  # tables whose rows have two sides
POLICY = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
MARKED = ' class="marked"'  # the cited cell of a spreadsheet row
STYLE = (
    "body{margin:24px;font:14px/1.45 system-ui,-apple-system,'Segoe UI',sans-serif;color:#1d1d1f;background:#fff}"
    "h1{font-size:22px;margin:0 0 6px}h2{font-size:17px;margin:28px 0 6px}h3{font-size:15px;margin:14px 0 4px}"
    "p{margin:4px 0;max-width:90ch}.wrap{overflow-x:auto}table{border-collapse:collapse;margin:6px 0 12px}"
    "th,td{border:1px solid #c8c8cc;padding:3px 6px;text-align:left;vertical-align:top;white-space:pre-wrap}"
    "thead th,.identity th{background:#f2f2f4;font-weight:600}tr.more>td{background:#fafafa}"
    "tr.more>td>*{position:sticky;left:6px;max-width:calc(100vw - 80px)}.evidence{margin:6px 0}"
    "img{display:block;max-width:100%;height:auto;border:1px solid #c8c8cc;margin:4px 0}"
    ".marked{font-weight:700;background:#fff2b3}summary{cursor:pointer;font-weight:600}a{color:#0b57d0}"
    "footer{margin-top:28px;color:#555}")


class Refusal(Exception):
    """A dataset or crops map this renderer will not print; gct report refuses with cause and next_step."""

    def __init__(self, cause: str, next_step: str):
        super().__init__(cause)
        self.cause, self.next_step = cause, next_step


def esc(s: str) -> str:
    """The one way a string reaches the page. U+0000 is written as U+FFFD, which is what a browser shows for it."""
    return html.escape(s.replace("\0", "�"), quote=True)


def _dotted(row, key):
    """A row value by its columns key: a dotted key walks the object (null when the object is null);
    outside_selection's a and b are its two items."""
    value = row
    for part in key.split("."):
        if value is None:
            return None
        value = value[{"a": 0, "b": 1}[part]] if isinstance(value, list) else value[part]
    return value


def _shown(value, row, key, words) -> str:
    """The one print form of a dataset value (7.1 C2a, C3)."""
    if row is not None and key in row["withheld"]:
        return words["withheld"]
    if key is not None and key.startswith("outside_selection."):
        return words["outside_selection"] if value else ""
    if value is None:
        return ""
    if isinstance(value, bool):
        return words["fixed"]["booleans"]["true" if value else "false"]
    if isinstance(value, list):
        return words["fixed"]["separator"].join(str(x) for x in value)
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _attributed(rows, columns) -> bool:
    """7.1 C2a: a row with a non-null contributor or dotted *.contributor column."""
    keys = [c["key"] for c in columns if c["key"] == "contributor" or c["key"].endswith(".contributor")]
    return any(_dotted(r, k) is not None for r in rows for k in keys)


def _subs(table_id, row) -> list:
    """A row's non-empty sub-tables. A pair side prints its own row only: its records are the evidence index's."""
    return [] if table_id == "pair_sides" else [v for v in row.values() if isinstance(v, dict) and "rows" in v and v["rows"]]


def _walk(table_id, rows):
    """Every row a table prints and, depth first, the rows of its sub-tables."""
    for r in rows:
        yield r
        for v in _subs(table_id, r):
            yield from _walk(v["id"], v["rows"])


def _sides(dataset, pairs) -> tuple[list, set]:
    """Each distinct pair side once, in first-appearance order (claim_a before claim_b), and the ids of the sides
    that come from related_claims. A side id no list holds has no row."""
    selected = {r["id"]: r for r in dataset["evidence_index"]}
    related = {r["id"]: r for r in dataset["related_claims"]}
    order = dict.fromkeys(p[k] for p in pairs for k in ("claim_a", "claim_b") if p[k] in selected or p[k] in related)
    return [selected.get(i) or related[i] for i in order], {i for i in order if i not in selected}


def _blocks(dataset, report) -> list[tuple]:
    """A page's tables in order: (table id, columns key, rows, ids of outside sides). The report's own tables come
    first, then pair sides after the pairs, the unpaired restatements on the restatement log, and the documents."""
    if report == "gap_report":
        out = []
        for s in SECTIONS:
            out.append((s, s, dataset["gap_report"][s], set()))
            if s == "candidates":
                out.append(("pair_sides", "evidence_index", *_sides(dataset, dataset["gap_report"][s])))
    else:
        out = [(report, report, dataset[report], set())]
    if report == "restatement_log":
        out.append(("pair_sides", "evidence_index", *_sides(dataset, dataset["restatement_log"])))
        out.append(("unpaired_restatements", "unpaired_restatements", dataset["unpaired_restatements"]["rows"], set()))
    out.append(("documents", "documents", dataset["documents"], set()))
    return out


def _check(dataset, reports, crops):
    """The four refusals (story 7.5 Design, "Refusals"), before any file is opened. A cause names tables, ids and
    fixed headings only."""
    again = "Run the report again. If this message repeats, report it as a fault in GCT."
    if [r for r in reports if r not in REPORTS]:
        raise Refusal("A viewer page was asked for a report this data does not hold.", again)
    ids = {e["id"] for e in dataset["evidence"]}
    pages = {e["id"] for e in dataset["evidence"] if e["page"] is not None}
    if odd := sorted(set(crops) - ids):
        raise Refusal(f"A page image was made for evidence E{odd[0]}, which this report's data does not hold.", again)
    if crops and (lacking := sorted(pages - set(crops))):
        raise Refusal(f"No page image was made for evidence E{lacking[0]}.", again)
    version = dataset["data_version"]["version"]
    for report in reports:
        other = sorted((r["id"], r["data_version"]) for t, _, rows, _ in _blocks(dataset, report)
                       for r in _walk(t, rows) if r["data_version"] != version)
        if other:
            title = dataset["words"]["fixed"]["titles"][report]
            raise Refusal(f"Row {other[0][0]} of {title} comes from data version {other[0][1]}, but this report is"
                          f" for data version {version}.", "Run the report again so every row comes from one data version.")


def _shown_crops(dataset, reports, cap) -> set:
    """R5.3: the page entries a binding row of a selected report cites (pair sides and sub-tables included)."""
    if cap:
        return set()
    pages = {e["id"] for e in dataset["evidence"] if e["page"] is not None}
    return {i for report in reports for t, _, rows, _ in _blocks(dataset, report) for r in _walk(t, rows)
            if r.get("binds") is not False for i in r["evidence"] if i in pages}


def _page(dataset, report, reports, shown, cap) -> str:
    words, fixed = dataset["words"], dataset["words"]["fixed"]
    titles, headings, sep = fixed["titles"], fixed["headings"], fixed["separator"]
    evidence = {e["id"]: e for e in dataset["evidence"]}
    documents = {d["id"]: d for d in dataset["documents"]}
    version = dataset["data_version"]["version"]
    blocks = _blocks(dataset, report)
    anchors = {r["id"] for t, _, rows, _ in blocks if t == "pair_sides" for r in rows}
    index = {r["id"] for r in dataset["evidence_index"]} if "evidence_index" in reports else set()
    by_claim = {r["claim_id"]: r["id"] for r in dataset["evidence_index"]} if index else {}
    also = esc(titles["evidence_index"])

    def cell(table, row, key):
        text, v = esc(_shown(_dotted(row, key), row, key, words)), row.get(key)
        if table in PAIRS and key in ("claim_a", "claim_b") and v in anchors:
            text = f'<a href="#claim-{int(v)}">{text}</a>'
            if v in index:
                text += f' <a class="also" href="evidence-index.html#claim-{int(v)}">{also}</a>'
        elif table == "unpaired_restatements" and key in ("original_claim_id", "restated_claim_id") and v in by_claim:
            text = f'<a href="evidence-index.html#claim-{int(by_claim[v])}">{text}</a>'
        return f"<td>{text}</td>"

    def where(i, row):
        """One evidence location: its words, then the crop (a binding row's page entry) or the cell's row."""
        e = evidence[i]
        name = _shown(documents[e["document_id"]]["name"], None, None, words)
        loc = [("document_name", name)] + ([("page", e["page"])] if e["page"] is not None else
                                           [("sheet", e["sheet"]), ("cell", e["cell"])])
        out = [f'<div class="evidence"><p>{esc(sep.join([f"E{int(i)}"] + [f"{headings[k]}: {_shown(v, None, k, words)}" for k, v in loc]))}</p>']
        if i in shown and row.get("binds") is not False:
            claim = row.get("claim_id")
            alt = (fixed["image_alt"].format(claim=claim, document=name, page=e["page"]) if claim is not None else
                   fixed["image_alt_entry"].format(evidence=i, document=name, page=e["page"]))
            out.append(f'<img src="crops/E{int(i)}.png" alt="{esc(alt)}">')
            if e["boxes"]:
                out.append(f'<p>{esc(fixed["image_cap"])}</p>')
        if e["header"] is not None:  # a spreadsheet cell: its row under the header, the cited cell marked (D16)
            n = max(len(e["header"]), len(e["row"]))
            lines = ["<tr>" + "".join(f"<{tag}{MARKED if k == e['marked'] else ''}>"
                                      f"{esc(xs[k] if k < len(xs) else '')}</{tag}>" for k in range(n)) + "</tr>"
                     for tag, xs in (("th", e["header"]), ("td", e["row"]))]
            out.append(f'<table class="cell">{"".join(lines)}</table>')
        return "".join(out) + "</div>"

    def table(table_id, title, columns, rows, cls, level, outside=frozenset()):
        tag = "h2" if level == 0 else "h3"
        out = [f'<section class="{cls}"><{tag}>{esc(title)}</{tag}>']
        if _attributed(rows, columns):
            out.append(f'<p>{esc(words["self_declared"])}</p>')
        out.append('<div class="wrap"><table><thead><tr>'
                   + "".join(f'<th scope="col">{esc(c["heading"])}</th>' for c in columns) + "</tr></thead><tbody>")
        for r in rows:
            anchor = f' id="claim-{int(r["id"])}"' if table_id in ("evidence_index", "pair_sides") else ""
            row_cols = dataset["columns"]["related_claims"] if r["id"] in outside else columns
            out.append(f'<tr class="row"{anchor}>' + "".join(cell(table_id, r, c["key"]) for c in row_cols) + "</tr>")
            more = [f'<p>{esc(words["outside_selection"])}</p>'] if r["id"] in outside else []
            more += [where(i, r) for i in r["evidence"]]
            subs = _subs(table_id, r)
            if subs:  # R5.6: only a row with sub-table rows, and only its non-empty sub-tables
                more.append(f'<details><summary>{esc(sep.join(v["title"] for v in subs))}</summary>'
                            + "".join(table(v["id"], v["title"], v["columns"], v["rows"], "sub", level + 1)
                                      for v in subs) + "</details>")
            if more:
                out.append(f'<tr class="more"><td colspan="{len(columns)}">{"".join(more)}</td></tr>')
        out.append("</tbody></table></div></section>")
        return "\n".join(out)

    body = []
    for table_id, cols_key, rows, outside in blocks:
        cls = "report" if table_id == report or table_id in SECTIONS else "table"
        body.append(table(table_id, titles[table_id], dataset["columns"][cols_key], rows, cls, 0, outside))
    attributed = any(_attributed(rows, columns) for columns, rows in _tables(dataset, blocks))
    stamp = f"{fixed['data_version']} {version}"
    head = [f"<h1>{esc(titles[report])}</h1>", f'<p class="version">{esc(stamp)}</p>',
            f"<p>{esc(fixed['mode'][dataset['mode']])}</p>", *(f"<p>{esc(n)}</p>" for n in dataset["notices"])]
    if attributed:
        head.append(f'<p>{esc(words["self_declared"])}</p>')
    about = [(fixed["identity"][k], _shown(v, None, k, words)) for k, v in dataset["data_version"].items()]
    about += [(fixed["dataset"][k], _shown(dataset[k], None, k, words)) for k in ("gct_version", "built_at",
                                                                                  "dataset_schema")]
    about += [(fixed["dataset"]["filter"], json.dumps(dataset["filter"], ensure_ascii=False)),
              (fixed["dataset"]["include"], _shown(dataset["include"], None, "include", words))]
    return "\n".join([
        "<!DOCTYPE html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
        f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(titles[report] + sep + stamp)}</title>", f"<style>{STYLE}</style>", "</head>", "<body>",
        "<header>", *head, "</header>", *([f'<p>{esc(fixed["image_limit"])}</p>'] if cap else []),
        f'<section class="identity"><h2>{esc(fixed["data_version"])}</h2><table><tbody>'
        + "".join(f'<tr><th scope="row">{esc(k)}</th><td>{esc(v)}</td></tr>' for k, v in about) + "</tbody></table></section>",
        *body, f'<footer><p class="version">{esc(stamp)}</p></footer>', "</body>", "</html>", ""])


def _tables(dataset, blocks):
    """(columns, rows) for every table a page prints, sub-tables included."""
    out = []

    def subs(table_id, rows):
        for r in rows:
            for v in _subs(table_id, r):
                out.append((v["columns"], v["rows"]))
                subs(v["id"], v["rows"])

    for table_id, cols_key, rows, _ in blocks:
        out.append((dataset["columns"][cols_key], rows))
        subs(table_id, rows)
    return out


def write(dataset, reports, folder, crops) -> dict:
    """Writes <stem>.html into folder for each of reports (dataset keys) and crops/E<id>.png for each page entry a
    binding row of those reports cites, every file opened with mode x. crops is the one dict crops.cut returned; {}
    with a page entry in the dataset is the image cap: no image, and the cap sentence on every page and in notes."""
    _check(dataset, reports, crops)
    cap = not crops and any(e["page"] is not None for e in dataset["evidence"])
    shown = _shown_crops(dataset, reports, cap)
    pages = {f"{r.replace('_', '-')}.html": _page(dataset, r, reports, shown, cap) for r in reports}
    folder = Path(folder)
    for name, text in pages.items():
        with open(folder / name, "x", encoding="utf-8", newline="\n") as f:
            f.write(text)
    if shown:
        (folder / "crops").mkdir()
    for i in sorted(shown):
        with open(folder / "crops" / f"E{int(i)}.png", "xb") as f:
            f.write(crops[i])
    files = sorted([*pages, *(f"crops/E{int(i)}.png" for i in shown)])
    return {"files": files, "notes": [dataset["words"]["fixed"]["image_limit"]] if cap else []}
