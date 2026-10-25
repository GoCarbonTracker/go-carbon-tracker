# Tables and Graphs: one filter, one version

The Tables and Graphs section of the viewer and `gct view records` read the claims of one published data version
through one filter object. A table, a graph and a series of the same filter and version are built from the same
selection, so they always hold the same claims, the same version and the same evidence. A filter only hides claims
from an answer: no read writes anything and no run is opened.

## The filter object

Every field is optional. Fields combine with AND; the values in one list combine with OR. `{}` selects every claim of
the version. An empty list, a field not listed here, a value of the wrong type or a value not in the field's list is
refused (HTTP 400, exit 2) with the field named; an id need not exist.

| Field | Values |
|---|---|
| `company` | company ids |
| `document` | document ids |
| `metric` | metric keys (`ghg_scope_1`, `ghg_scope_2`, `ghg_scope_1_2`, `ghg_scope_3`, `energy_total`, `energy_renewable`, `energy_non_renewable`, `water_withdrawal_total`, `water_consumption_total`, `water_discharge_total`, `waste_total`) and `unmapped` for a claim with no key |
| `text` | 1 to 200 characters, found in the metric wording, case not minded |
| `period` | `{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}`, either end optional: the claim's known period lies inside, ends included |
| `boundary` | `standalone`, `subsidiary_set`, `consolidated`, `unknown` (a boundary not resolved or accepted is unknown) |
| `claim_state` | `current`, `not-found`, `not-extracted` |
| `evidence` | `matched`, `cited`, `unresolved`, `not-checked` (no `gct link` result) |
| `match` | `series`, `reviewed`, `uncertain`, `not-matchable` |
| `series` | series ids |
| `comparison` | `same`, `restatement`, `unresolved`, `not-compared`: the claim is in a comparison in that state |
| `review` | `company-confirmation`, `auditor-review`, `disagreement`, `flag-raised`, `highlight`, `needs-re-review`, `corrected`, `adjudicated` |

A period is known when its state is resolved or accepted. A claim whose period is not known never matches a `period`
condition; `excluded.period_unknown` counts the claims every other condition matches that the period left out for that
reason. Reviews count on the claim's current version only: records on an older version show as `needs_re_review`.

## Versions

Every request reads one version, resolved once: the current one, or the one pinned with `data_version`. A pin that is
no longer current is refused (HTTP 409, exit 4): "Data version V is no longer the current one; the current version is
W." with "Reload to see version W." Before the first `gct publish build`, and for a version built by a gct older than
projection 14, the answer is 409 with `gct publish build` as the next step. The viewer holds its pin and shows
"Data version W is available." with a Reload button after a 409 or after a write in the Evidence section.

## Archived and deleted documents

The claims of an archived document are in no answer. `hidden_by_archive` counts them, and its `text` reads "N claims
of M archived documents are not in this or any view. Restore a document to include its claims." A document named in
the filter that was permanently deleted is listed in `deleted_in_filter`, "Document N was permanently deleted."
A document deleted after the last build stops contributing rows at once, but it is named in `deleted_in_filter` only
after the next build (`gct publish build`), since the deletion is recorded in the version file at build.

## Requests

`POST /api/records` takes a JSON object with `filter`, `data_version`, `shape` (`table`, the default, `graph`,
`series` or `values`), `offset` (0) and `limit` (200, at most 1000) for a table, `sort` (at most one
`{"key", "dir"}`; keys `company`, `document`, `page`, `metric`, `value`, `period`, `boundary`, `evidence`, `state`;
claim id always last ascending; claims without the value last in both directions) and `claim_ids` (1 to 1000 ids:
the answer is the filter's selection limited to them, the others listed in `not_found`). `gct view records` takes the
same as `--filter JSON|@FILE`, `--shape`, `--offset`, `--limit`, `--sort KEY[:desc]` and `--claims ID,ID`.

A graph draws at most 500 claims; above that it answers `drawable: false` with the reason. A series answers
`drawable: false` unless every selected claim is a point of one series. The values shape lists the metric keys and
series of the selection, for the filter bar; it takes no claim ids.

`GET /api/documents/{id}/cells?sheet=S&cell=C[&data_version=V]` answers a spreadsheet claim's evidence: the sheet's
header row and the row of the cell, with the cell's column marked. A PDF, an archived or deleted document, an unknown
sheet and a cell outside the sheet are refused with the next step.

## Evidence locations

Every row, node and edge carries where its source opens, as a `location`: a `page` of a PDF (with the `claim_id` to
select) or a `sheet` and `cell`. A claim whose source match is unresolved still opens the page or cell its evidence
reference names, as the Evidence view does; its evidence text says "unresolved: reason". When it cannot open,
`resolved` is false and `reason` says why ("unresolved: ..." when no page is named, "no page: ..." for a
spreadsheet's declared mapping). A location is never made up.

## Tables

The Tables tab of the viewer shows the claims the filter selects on the pinned version, 200 rows a page, with First,
Previous, Next, Last and "Rows A to B of N". Each page is one `POST /api/records` request with the `table` shape; a
new page replaces the rows on screen, so every row shown is from the version the caption names. A filter change, a
sort change or a new version goes back to the first page.

The columns are Company, Document, Location ("page P" or "sheet S, cell C"), Metric wording ("no metric wording"
when none), Value with its unit as printed, Period, Boundary, Evidence, Review and Claim state. Evidence and Review
print the row's evidence and review texts. Stored words are printed with spaces ("fiscal year", "subsidiary set").
Pressing a column header sorts by it, ascending first, then descending; Review cannot be sorted. With no column
chosen the order is company, document and page.

Checked rows stay checked across the pages of one filter and one version; a filter change or a new version clears
them and says so. The table is one Tab stop: the arrow keys move between rows, Space checks a row and Enter opens its
evidence. A PDF row opens its page in the Evidence section with the claim selected (its box drawn when it has one);
a spreadsheet row opens the cell view; a row with no page or cell, or a page outside its document, opens nothing and
says "This claim has no source location to open." When another writer has published meanwhile, the next page is
refused and the viewer offers the new version with Reload; the rows on screen keep their own version until then.

## Keys

Graph node ids are `claim:N`, `page:D:P`, `cell:D:SHEET!CELL`, `period:START..END`, `boundary:VALUE[:DETAIL]`,
`series:ID`, `company:N`, `auditor:N`, `flag:N`, `highlight:N` and `adjudication:N`; each claim has one hyperedge
whose members are its other nodes and the claims compared with it inside the selection. A comparison with a claim
outside the selection draws no edge; the claim node's `outside_text` reads "N related claims outside this selection".
Contributor text on review nodes is quoted as written and `self_declared`: GCT never checks who a contributor is.

- `table`: `status`, `data_version`, `filter`, `matched`, `total`, `offset`, `limit`, `rows`, `empty`, `excluded`, `hidden_by_archive`, `deleted_in_filter`, `not_found`
- `graph`: `status`, `data_version`, `filter`, `matched`, `graph_limit`, `drawable`, `reason`, `nodes`, `hyperedges`, `edges`, `excluded`, `hidden_by_archive`, `deleted_in_filter`, `not_found`
- `series`: `status`, `data_version`, `filter`, `matched`, `drawable`, `reason`, `series`, `points`, `comparisons`, `excluded`, `hidden_by_archive`, `deleted_in_filter`, `not_found`
- `values`: `status`, `data_version`, `filter`, `matched`, `metric_keys`, `series`
- `hidden by archive`: `documents`, `claims`, `by_document`, `text`
- `row`: `claim`, `company_name`, `document_name`, `evidence`, `review`
- `row claim`: `id`, `company`, `document`, `page`, `sheet`, `cell`, `locator`, `metric_text`, `metric_key`, `value_text`, `value`, `unit_text`, `period_label`, `period`, `boundary`, `claim_state`, `series_id`, `match_state`, `match_reason`
- `row evidence`: `source_match`, `reason`, `page`, `boxes`, `sheet`, `cell`, `document_state`, `location`, `text`
- `row review`: `company`, `auditor`, `disagreement`, `flags_raised`, `highlights`, `needs_re_review`, `corrected`, `candidate_pairs`, `adjudications`, `text`
- `location`: `document`, `page`, `sheet`, `cell`, `claim_id`, `resolved`, `reason`
- `claim node`: `id`, `kind`, `label`, `evidence`, `row`, `outside`, `outside_text`
- `node`: `id`, `kind`, `label`, `evidence`
- `review node`: `id`, `kind`, `label`, `evidence`, `contributor`, `organisation`, `capacity`, `self_declared`, `outcome`, `text`, `evidence_note`
- `hyperedge`: `id`, `claim`, `members`
- `edge`: `id`, `kind`, `source`, `target`, `state`, `reason`, `restatement`, `evidence`
- `series info`: `id`, `company`, `company_name`, `metric_key`, `label`, `reporting_boundary`, `boundary_detail`, `unit_family`, `period_kind`
- `point`: `claim`, `company_name`, `document_name`, `evidence`, `review`, `period_order`, `period_start`, `period_end`, `value_base`, `comparable`, `not_comparable_reason`
- `series comparison`: `claim_a`, `claim_b`, `period_start`, `period_end`, `state`, `reason`, `restatement`, `evidence`
- `values metric`: `metric_key`, `claims`
- `values series`: `id`, `metric_key`, `company_id`, `points`
- `cells`: `status`, `data_version`, `document`, `name`, `sheet`, `cell`, `columns`, `header`, `row`, `cells`, `column`

`node` is a page, cell, period, boundary or series node; `review node` a company confirmation, auditor review, flag,
highlight or adjudication. A `point` is the row of its claim plus its place in the series. An `edge` of kind `member`
links a claim to one of its nodes; one of kind `comparison` links two compared claims and carries both locations.

The review text names, in this order, the company's and the auditor's latest outcomes, "disagreement", "flags raised:
N", "highlights: N", "needs renewed review: N", "corrected" and "adjudications: N", or reads "no review records". The
evidence text reads "matched", "cited: reason", "unresolved: reason" or "not checked: run gct link". No score,
percentage or ranking is given.

## Graphs

The Graphs tab of the viewer draws the claims of one `graph` or `series` answer in three views. Neighbourhood and
Hypergraph are drawn from the same `graph` answer, so switching between them sends no request; Time series asks the
`series` shape. The tab sends the shared filter and the pinned version, and states the count and version of the answer
it drew, in the words of the count line above it.

- Neighbourhood: each claim node joined to its page or cell, its known period and boundary, its series, its review
  records and adjudications, and an edge labelled with the comparison state between two compared claims of the answer.
- Hypergraph: one small hub per claim, joined to the claim and to each member of its hyperedge. Members are the same
  shared nodes as in the neighbourhood view, so a page of three claims is one node with three hub edges.
- Time series: one node per point, a column per period in order, a row per document (a restatement in a later report
  sits in the original's column), points of one period and document stacked by claim id. The value and unit are
  printed on the point; there is no value axis.

Over the graph limit, or with no single series for the time series, the tab shows the answer's `reason` and draws
nothing. Every drawn element is also a row of a table under the canvas (Nodes and Edges, Hyperedges, or Points and
Comparisons); a row's button selects its element on focus, opens its source on Enter or a click, and Space adds it to
the selection. A double-click on the canvas opens the source too. A page target is opened only when its page lies
inside the document; a location that does not resolve shows its reason and opens nothing. Labels use printed wording
and plain words only.

Layout: Cytoscape's built-in `cose` (no animation), except above 250 nodes, where `breadthfirst` is used, and the
time series, which is placed by its own positions. Measured in headless Chrome on 2026-10-23 (Apple silicon laptop,
fixture of `tests/test_viewer_graphs.py`): `cose` alone took about 1.0 s at 230 nodes, 1.5 s at 283, 2.2 s at 334,
5.2 to 6.4 s for the 500-claim neighbourhood graph (538 nodes, 1,100 edges) and about 20 s for its hypergraph (1,038
nodes); `breadthfirst` took 74 ms and 131 ms on those two. With the 250-node rule, the 500-claim neighbourhood graph
was drawn about 0.7 s after the filter changed and its hypergraph about 0.4 s after the view switched.

## Saved views and guided questions

A saved view is a name, a filter and the tab it opens (Tables or Graphs). It stores the normalised filter, never the
claims and never a data version, so it always opens on the current version and includes the claims of reports added
since it was saved. After an archive it shows the remaining claims and the line "N claims of M archived documents are
not in this or any view. Restore a document to include its claims."; a view naming a deleted document shows "Document
N was permanently deleted." A filter that matches nothing today is saved, since a later report may match it.

    gct view save "Scope 1 by year" --filter '{"metric": ["ghg_scope_1"]}' --section graphs --as ana
    gct view list
    gct view open "Scope 1 by year" [--shape table|graph|series] [--offset N] [--limit N] [--sort KEY[:desc]]
    gct view remove "Scope 1 by year" --as ana
    gct view questions

A name is 1 to 80 characters on one line, at least one of them visible (a name of only spaces and invisible characters
such as U+200B is refused as empty), trimmed, and compared exactly (two names differing in case are two views).
Saving under an existing name puts the new view first and keeps the earlier one (`earlier` counts them). Removing a view
takes it off the list; its saves and the removal stay in the workspace, and `gct view list` says how many names are
removed. Every save and removal names its contributor. Opening a view answers exactly what `gct view records` answers
for its filter, on the current version; a stored filter that the filter rules no longer accept is refused naming the
field. Saving or removing a view builds no data version and opens no run, so a table or graph pinned to the current
version stays valid. Saved views are part of the workspace only: they are never published, and deleting a document
leaves them as they are.

The local service offers `GET /api/views`, `POST /api/views` (`name`, `filter`, optional `section`, `contributor`),
`POST /api/views/remove` (`name`, `contributor`) and `GET /api/questions` (optional `?data_version=V`, refused as a stale
pin when it is not the current version). The viewer opens a view by sending its filter to `POST /api/records`. The
answers are the JSON of the commands, listed in `docs/cli-json.md`.

The six guided questions are fixed saved views shipped with gct; no model writes or ranks them. Each shows its count
on the current version, 0 included:

| Key | Question | Filter | Opens |
|---|---|---|---|
| `restated` | Which figures were restated? | `{"comparison": ["restatement"]}` | Graphs |
| `different-values` | Where do two reports give different values for the same figure and period, with no restatement recorded? | `{"comparison": ["unresolved"]}` | Graphs |
| `metric-over-time` | How did one figure change across reports? | `{"match": ["series"]}`; one series chosen opens `{"series": [ID]}` | Graphs, as a series |
| `not-matched-to-source` | Which figures could not be matched to their place in the source? | `{"evidence": ["cited", "unresolved"]}` | Tables |
| `ledgers-disagree` | Where do the company confirmation and the auditor review disagree? | `{"review": ["disagreement"]}` | Graphs |
| `needs-renewed-review` | Which figures need renewed review after a correction? | `{"review": ["needs-re-review"]}` | Tables |

`different-values` cannot leave out pairs that already have an adjudication; each row shows its adjudications.
`metric-over-time` lists its choices, the series with two or more periods (company, label and number of periods), and
its count is the number of choices. `not-matched-to-source` leaves out claims whose evidence is not checked yet, and
`ledgers-disagree` counts the current version of each claim only (`gct review list` shows earlier versions).

## Auditor Copilot and Restatement Extensions (Story M1-6.5)

The viewer integrates four forensic assurance capabilities:

1. **EmeraldMind 4-Type Taxonomy**: Reviewer flags recorded on `/api/claims/{id}/flags` provide structured classification:
   - `Type 1`: Unaccredited or false green labels/certifications
   - `Type 2`: Mandatory statutory obligations framed as voluntary actions
   - `Type 3`: Scope overgeneralization / boundary mismatches
   - `Type 4`: Direct factual contradictions against disclosed tables
2. **Copilot Proposals Drawer**: `GET /api/copilot/candidates` serves unreviewed candidates surfaced by `gct flag propose` alongside citation page and bounding boxes for auditor review (FR39).
3. **Rung 1 vs Rung 2 Badges**: Claims in tables distinguish deterministic figures (`[R1 Numeric]`) from qualitative commitments (`[R2 Qualitative]`).
4. **Interactive Restatement Matrix**: `GET /api/restate/pairs` exposes cross-report comparisons directly in the web UI.
