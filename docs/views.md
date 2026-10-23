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
