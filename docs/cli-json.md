# CLI JSON output

Every command prints one JSON object on stdout when `--json` is given. `status` is one of
`ok`, `partial`, `exists`, `already_initialised`, `plan` (`doc delete` without `--confirm`), `error`. The lines below are checked by
`tests/test_json.py`: `top` lists the keys of the object, any other name lists the keys of the
nested record (or of each record in the nested list) under that key.

## workspace init
- top: status, path

## workspace status
- top: status, schema_version, gct_version, companies, documents, published_version, runs, latest_run_outcome

## company add
- top: status, id, name, sector_ref, sector_version, created_at

## company list
- top: status, companies
- companies: id, name, sector_ref, sector_version, created_at

## doc add
- top: status, items
- items: source, company, action, document, cause, next_action, cached

`status` is `ok` when every item was registered or a duplicate (and always with `--plan`), else `partial` (exit 4), which adds `cause` and `next_action` at the top; `next_action` names the sources that were not added. `action` is `registered`, `duplicate`, `refused` or `failed`; with `--plan` it is `would register`, `would fetch`, `duplicate` or `refused`. `document` has the keys of `doc show` for `registered` and `duplicate` (null for a duplicate of an earlier item in the same plan), null otherwise. `cause` and `next_action` are set only for `refused` and `failed`, except that a `duplicate` of an archived document has `next_action` `Restore it with: gct doc restore N`. `cached` is true when a URL was already fetched by an earlier command and was not downloaded again.

## doc list
- top: status, documents, hidden_by_archive, hidden_deleted
- documents: id, company, logical_name, version, sha256, kind, file_type, privacy, size_bytes, source, created_at, state, deleted_at

`state` is `registered`, `archived`, `restored` or `deleted`; `deleted_at` is when a deleted document was deleted, else null (every record with these keys has it). With `--active` archived and deleted documents are left out and `hidden_by_archive` and `hidden_deleted` count them; without it every document is listed and both are 0.

## doc show
- top: status, document, state_change, deletion
- document: id, company, logical_name, version, sha256, kind, file_type, privacy, size_bytes, source, created_at, state, deleted_at

`state_change` is null for a registered document, else who made its newest state (`archived`, `restored` or `deleted`), when and why: `state`, `at`, `contributor`, `organisation`, `capacity`, `rationale`. `deletion` is null unless the document was deleted, else `at`, `steps` (done, in order: `database`, `files`, `artifacts`, `renders`, `published`, `vacuum`), `pending` (the steps not done yet; finish them with `gct doc delete N --confirm TOKEN`) and `records`: the contributor records on the document itself that stay (`kind` `page acceptance`, `basis scope`, `sheet mapping` or `state change`, `id`, `what`, `contributor`, `organisation`, `capacity`, `rationale` (both read `cleared with document N`), `created_at`, `evidence_deleted`). A deleted document's `logical_name` reads `cleared with document N` and its `source` is null.

## doc delete
- top: status, cause, next_action, document, impact, clears, files, versions, warning, token

Without `--confirm` nothing is stored: `status` is `plan` and the exit code is 4, with `cause` and `next_action` (the command that deletes, with the token). `document` has the keys of `doc show`; `impact` is that of `doc archive` (for an archived document only its counts and expectations, the rest empty, as it already gives no active points); `clears` counts per table the rows whose content is cleared (tables with none are left out); `files` gives, for `files` (the original), `artifacts` (reading files) and `renders` (page images), the number to `remove` and to `keep` because a document not deleted uses them; `versions` lists the published versions purged; `warning` is the export warning; `token` is the first 12 characters of the document's SHA-256. With `--confirm TOKEN --as KEY --capacity TEXT --rationale TEXT` the result has the keys of `doc show` (`status` `ok`). A wrong token or a deleted document with nothing pending is refused (exit 4), missing contributor flags exit 2. When a step fails (a file held open), the database step and the tombstone stand, the error names the pending steps (exit 4), and the same command with only `--confirm TOKEN` finishes them. See `docs/deletion.md`.

## doc archive
- top: status, document, impact, state_change
- document: id, company, logical_name, version, sha256, kind, file_type, privacy, size_bytes, source, created_at, state, deleted_at
- impact: claims, evidence_refs, review_records, series, same_period_sets, uncertain_items, expected_items

`impact` is what leaves the active outputs, computed before the archive is stored, so `--plan` and the archive itself give the same `impact`. `claims` counts the newest version of each of the document's claims and `evidence_refs` their locations. `review_records` counts, per kind, the records that stay stored but leave the active outputs: `inference_review`, `correction`, `match_review` (on any version of the document's claims), `page_acceptance` (on its pages), `restatement` (rows naming any version of its claims as original or restated) and `sheet_mapping` (every column mapping row of a spreadsheet). `series` lists each series the document has points in: `id`, `metric_key`, `label`, `unit_family`, `reporting_boundary`, `points` (the document's) and `points_left`. `same_period_sets` lists each period of a series that holds more than one value and loses one: `series`, `period_start`, `period_end`, `points`, `points_left`. `uncertain_items` counts the document's items in the match review queue, `expected_items` lists the ids of the expectations whose state is computed from it. With `--plan` nothing is stored and `state_change` is null; otherwise it is the record stored (see `doc show`). Archiving an archived document is refused (exit 4), as is archiving without `--as`, `--capacity` and `--rationale` (exit 2).

## doc restore
- top: status, document, state_change
- document: id, company, logical_name, version, sha256, kind, file_type, privacy, size_bytes, source, created_at, state, deleted_at

`state_change` is the `restored` record stored (see `doc show`). Restoring a document that is not archived is refused (exit 4).

## doc pages
- top: status, document, document_state, pages
- pages: page_number, rung, method, width, height, words, tables, flags, artifact

One record per page number, from its newest reading. `document` is the id, `document_state` its state (`registered`, `archived` or `restored`). `flags` lists the quality codes (`no_text`, `fragmented_text`, `sparse_tables`). `artifact` is the SHA-256 of the reading file `artifacts/<first two characters>/<sha256>.json`. An unread document gives an empty `pages` list.

## read
- top: status, documents
- documents: id, logical_name, pages, read, cached, flagged, failed, flags, action, cause, next_action

`status` is `ok` when no document and no page failed (flags are not failures; exit 0), else `partial` (exit 4), which adds `cause` and `next_action` at the top. `action` is `read`, `skipped` (not a PDF, or for `run retry` no longer active) or `failed` (the PDF could not be opened). `read` counts pages read by this command, `cached` pages already read under the same document bytes and reader settings, `failed` pages that raised. `flags` maps each quality code to its number of pages. `cause` is set for `skipped`; `cause` and `next_action` for `failed` and for a `read` document with failed pages; null otherwise. Nothing to read gives `{"status": "ok", "documents": []}`.

## extract
- top: status, documents
- documents: id, logical_name, pages, extracted, cached, failed, figures, no_box, action, cause, next_action

`status` is `ok` when no page failed (exit 0), else `partial` (exit 4), which adds `cause` and `next_action` at the top. `action` is `extracted` or `skipped` (no page read yet; then `next_action` is `read it first: gct read`). `pages` counts the read pages, `extracted` the pages extracted by this command, `cached` the pages whose reading had not changed since they were extracted. `figures` and `no_box` count the claims of those pages and the claims without a source box (source match `cited`, reason `no box`). Nothing to extract gives `{"status": "ok", "documents": []}`.

CSV and XLSX documents are extracted by their own stage, `sheet`, in a second run when the selection also holds PDFs; their records have the same keys, PDF records first. For a spreadsheet `pages` counts the sheets with a confirmed mapping, `extracted` and `cached` those sheets, `figures` the rows with a value, and `no_box` is 0. `cause` may be set on an `extracted` spreadsheet without failures: it lists, separated by `; `, each `sheet NAME: no confirmed mapping`, each `sheet NAME: N skipped (row for another company)` and each `sheet NAME: N skipped (row without a company)`. When every failed document is a spreadsheet, the top-level `next_action` is the spreadsheet retry wording. A spreadsheet with no confirmed mapping is `skipped` with `next_action` `map its columns first: gct sheet show ID`; a file that cannot be read as a spreadsheet is `skipped` with the reason.

## link
- top: status, documents
- documents: id, logical_name, refs, checked, cached, failed, matched, cited, unresolved, action, cause, next_action

`status` is `ok` when no location failed to be checked (exit 0), else `partial` (exit 4), which adds `cause` and `next_action` at the top. `action` is `checked` or `skipped` (no claims yet; then `next_action` is `extract it first: gct extract`; for `run retry`, also a document no longer active). `refs` counts the source locations of the newest claim versions, `checked` those checked by this command, `cached` those already checked against the same reading. `matched`, `cited` and `unresolved` count the newest source match status of those locations. Nothing to check gives `{"status": "ok", "documents": []}`.

## infer
- top: status, documents
- documents: id, logical_name, claims, inferred, cached, failed, bases, headings, period, boundary, action, cause, next_action

`status` is `ok` when no document failed (exit 0), else `partial` (exit 4), which adds `cause` and `next_action` at the top. `action` is `inferred` or `skipped` (no claims yet; then `next_action` is `extract it first: gct extract`; for `run retry`, also a document no longer active). `inferred` is 1 when the document was inferred by this command, `cached` 1 when its claims, readings and declared ranges had not changed since. `bases` counts the period and boundary statements found on its newest readings, `headings` the pages with a reporting-boundary heading but no readable answer. `period` and `boundary` count the claims by effective state (`resolved`, `accepted`, `proposed`, `unresolved`, `extracted`) and add one key `unresolved: <reason>` per reason. Nothing to infer gives `{"status": "ok", "documents": []}`.

## infer bases
- top: status, bases, headings
- bases: id, document, page, kind, wording, year_end, start, end, boundary, detail, scope
- headings: document, page, reason

The statements found by the newest `gct infer` of each active document. `kind` is `fiscal_year_end` (with `year_end` as `MM-DD`, and `start` and `end` when the statement prints both dates) or `reporting_boundary` (with `boundary` and `detail`, the entity wording as printed or null). `wording` is the text as read, whitespace collapsed. `scope` is null or the newest declared range: `first`, `last`, `contributor`, `capacity`, `rationale`, `created_at`. `headings` lists pages with a reporting-boundary heading but no readable answer, `reason` `heading without a readable answer`.

## infer scope
- top: status, basis
- basis: id, document, page, kind, wording, year_end, start, end, boundary, detail, scope

The statement after the range is declared. Only a `reporting_boundary` statement takes a range (else exit 4); the range must lie in the document. It applies from the next `gct infer`.

## infer groups
- top: status, groups
- groups: id, document, field, state, kind, start, end, boundary, detail, reason, basis, claims, reviews

One record per group of current inferences (newest claim versions of active documents) derived the same way to the same result. `id` is the handle `infer accept` and `infer reject` take. `field` is `period` (values in `kind`, `start`, `end`) or `boundary` (values in `boundary`, `detail`); the other field's keys are null. `state` is `proposed` or `unresolved` (then `reason` says why and the values are null). `basis` is null when the label is its own source, else `id`, `page`, `wording`, `kind`. `reviews` counts the claims by their current review: `accepted`, `resolved`, `rejected`, `open`.

## infer accept
- top: status, group, accepted, skipped, by

`group` is as in `infer groups`, after the acceptance; `accepted` is the number of claims accepted (only members whose current state is `proposed`), `skipped` counts the members left as they were by their decision (`{"resolved": 1, "rejected": 1, "accepted": 2}`; empty when none): a resolution or rejection made claim by claim is never overridden by a group decision. `by` is `<name> (<capacity>)`. An unresolved group is refused (exit 4). An acceptance holds for the inference it was given on: a new claim version or a changed inference is `proposed` again.

## infer resolve
- top: status, claim, field, effective

`effective` is the claim's field after the resolution, with the keys of the `period` and `boundary` records of `claims list`: `state` (`resolved`, `accepted`, `proposed`, `unresolved` or `extracted`, the last when `gct infer` has not run), the values (`kind`, `start`, `end`, `label` for a period; `boundary`, `detail` for a boundary), `reason` (why unresolved, `rejected` after a rejection), `basis` (`id`, `page`, `wording`, or null), `group` and `review` (null or `decision`, `contributor`, `organisation`, `capacity`, `rationale`, `created_at`). The values of a proposal show here and in `claims list`, never in the published main fields. A start after the end, a date not in `YYYY-MM-DD` form, or values of the other field give exit 2.

## infer reject
- top: status, group, rejected, skipped, by

As `infer accept`, for a rejection: it acts on members still proposed and on members accepted, and leaves resolved and already rejected members as they were (counted in `skipped`). A group rejection is not undone by a later group accept, which skips rejected members; resolve each claim instead. With `--claim CLAIM --field FIELD` the shape is that of `infer resolve`. This claim-by-claim rejection may follow an acceptance or a resolution of that claim. A claim with no current proposal, or one already rejected, is refused (exit 4).

## match
- top: status, documents
- documents: id, logical_name, claims, matched, cached, failed, mapped, unmapped, unit_unknown, action, cause, next_action

`status` is `ok` when no document failed (exit 0), else `partial` (exit 4), which adds `cause` and `next_action` at the top. `action` is `matched` or `skipped` (no claims yet; then `next_action` is `extract it first: gct extract`; for `run retry`, also a document no longer active). `matched` is 1 when the document's claims were given a metric key and unit by this command, `cached` 1 when its newest claim versions had not changed since. `mapped` and `unmapped` count the newest claim versions by whether a metric key was assigned, `unit_unknown` those without a known unit. Nothing to match gives `{"status": "ok", "documents": []}`. See `docs/matching.md` for the rules.

## match metrics
- top: status, rules_version, metrics_version, units_version, excluded, metrics, units, prefixes
- metrics: key, must, never
- units: text, base, factor
- prefixes: text, factor

The built-in metric list and unit table. `excluded` lists the wording that leaves a label unmapped for every key. Each metric has the phrases one of which the label must contain (`must`) and the phrases it may not contain (`never`). Each unit is the text as looked up (lowercased, the word `in`, brackets and spaces removed), its base unit (the conversion family) and the factor to it. `prefixes` are the magnitude words multiplied in.

## match review
- top: status, items
- items: claim, version, document, page_number, metric_text, value_text, unit_text, reason, series, metric_key, label, reporting_boundary, boundary_detail

One record per uncertain item: claim version `version` of claim `claim` could join series `series` after review, because of `reason` (`boundary unknown`, `unit unknown` or `unit not convertible`). `metric_key` (null for an unmapped series, then `label`), `reporting_boundary` and `boundary_detail` describe the candidate series. `--company NAME` and `--reason R` filter. An unknown company is refused (exit 3).

## match link
- top: status, claim, version, series, decision, match_state, match_reason, series_id, by
- by: contributor, organisation, capacity, rationale

Records a `linked` review for the claim's newest version and the series. `match_state` is then `reviewed`, `series_id` the series and `match_reason` the uncertain reason: the point is stored with `comparable` false. A claim with no uncertain item for that series (or no candidate at all), a link already made, or a claim already linked to another series is refused (exit 4); an unknown claim or contributor exits 3.

## match unlink
- top: status, claim, version, series, decision, match_state, match_reason, series_id, by
- by: contributor, organisation, capacity, rationale

As `match link`, with `decision` `not_linked`: the item leaves the queue (or a link to that series is undone). When every candidate of the claim is answered `not_linked`, `match_state` is `not matchable` with `match_reason` `not linked by review`.

## match status
- top: status, companies
- companies: company, claims, mapped, unmapped, unit_unknown, not_mapped_yet, series, same_period_sets, uncertain_items, states, not_matchable, pairs

Counts per company over the newest claim versions of active documents. `mapped` is `{metric key: claims}`; `not_mapped_yet` counts versions `gct match` has not seen. `states` counts claims by match state (`series`, `reviewed`, `uncertain`, `not matchable`), `not_matchable` by reason. `same_period_sets` counts the periods of a series with two or more points. `pairs` counts the pairs of those sets by state (`same value`, `restatement`, `unresolved conflict`, `not compared`; see `restate list`).

## series list
- top: status, series
- series: id, company_id, metric_key, label, document_id, reporting_boundary, boundary_detail, unit_family, period_kind, periods, latest_period_end, company, points, same_period_sets

One record per series, with `points` holding only the points of its latest period (the newest `period_end`). `metric_key` is null for an unmapped label, which then has `label` (lowercased as matched) and `document_id`; a `unit as printed` series also has `document_id`. `unit_family` is the base unit (`tco2e`, `tco2`, `gj`, `kl`, `t`) or `printed:<unit text lowercased, the word in, brackets and spaces removed, or ->`. `periods` counts the distinct periods. Each point: `claim_id`, `claim_version_id`, `document_id`, `page_number`, `period_start`, `period_end`, `value_text` and `unit_text` as printed, `unit_key`, `locator`, `number` (the number read from the printed value by match rules 2: the claim's value, else Western or Indian grouping with trailing footnote marks removed; null when none), `value_base` (`number` in the base unit, null when the point is not comparable or has no number), `link` (`rule` or `reviewed`), `comparable` (false for a reviewed link and a `unit as printed` point), `reason` (why not comparable, else null), `review` (null, or `decision`, `contributor`, `organisation`, `capacity`, `rationale`, `created_at`) and `same_period` (how many points of the series share its period) and `pairs` (one per other point of its period: `claim`, `state`, `reason`, `restatement` (the record id or null); see `restate list`). `--metric KEY` and `--company NAME` filter.

## series show
- top: status, series
- series: id, company_id, metric_key, label, document_id, reporting_boundary, boundary_detail, unit_family, period_kind, periods, latest_period_end, company, points, same_period_sets

One series as in `series list`: the points of the latest period, or with `--all` every point, oldest period first. Each point's `pairs` give the state of every pair of its same-period set. Each point also has `sheet` and `cell`: the sheet name and value cell of a spreadsheet point (`page_number` is then the sheet's position), null for a page. An unknown series is refused (exit 3).

## restate list
- top: status, pairs, hidden
- pairs: series_id, company_id, company, metric_key, label, reporting_boundary, boundary_detail, period_start, period_end, state, reason, restatement, a, b

One record per pair of points of one same-period set of a series, over the active documents (`--company NAME` for one company). `a` and `b` are the two points as in `series list` (`claim_id, claim_version_id, document_id, page_number, locator, period_start, period_end, value_text, unit_text, unit_key, number, value_base, link, comparable, reason, review`), ordered by document id then claim id for display only (the store never orders reports). `state` is `same value`, `restatement`, `unresolved conflict` or `not compared`; `reason` is set only for `not compared` (`unit as printed`, `reviewed, not comparable`, `no numeric value`, `same table row`). `restatement` is null or the current record: `id, original_version, restated_version, decision, document, page, quote, contributor, organisation, capacity, rationale, created_at`. `--state same|restatement|unresolved|not-compared` hides the other pairs and `hidden` counts them (0 without `--state`). See `docs/restatements.md`.

## restate show
- top: status, claim, pairs, versions
- claim: id, document, page_number, version, match_state, match_reason, series_id, evidence_deleted, needs_re_review
- versions: claim, id, reviews, evidence_deleted

`evidence_deleted` (on the claim and on each version, which may belong to another claim) is null unless that claim's document was deleted, else `{"document": N, "at": ...}`; each entry of `restatements` has its own `evidence_deleted`, set when either version it names or its evidence document was deleted; a match review of a deleted document has `series` null (its key is cleared), and a restatement record naming it has an empty `quote`.

`pairs` are the pairs (as in `restate list`) the claim's newest version is in. `versions` holds every version of the claim, oldest first, then the other version of each pair and of each restatement row on the claim's versions; `reviews` is every record attached to that version: `inference_reviews`, `corrections` (with `role` `made this version` or `replaced this version`), `match_reviews` (with the series id in `series`), `source_match` (the newest check of each evidence ref, `status` null when not checked) and `restatements` (every row naming the version, withdrawn and superseded ones included, with `role` `original` or `restated`, `current` and `binds`, false when either version it names is not its claim's newest; see `docs/restatements.md`), then `company_confirmations`, `auditor_reviews`, `disagreement`, `reviewer_flags` and `adjudications` as in `claims history`. `claim.needs_re_review` is that of `claims list`. An unknown claim is refused (exit 3).

## restate record
- top: status, restatement, pair
- restatement: id, original_version, restated_version, decision, document, page, quote, contributor, organisation, capacity, rationale, created_at

Records that the `--restated` claim's newest version restates the `--original` claim's newest version, citing `--page` of the restated claim's document and `--quote`, the line as printed there. `pair` is the pair as computed afterwards (state `restatement`). Refused (exit 4): the two claims not in one same-period set of one series, a claim that is not current or whose newest version has not been matched yet, a pair that is `same value` or `not compared`, a page outside the document or not read, a quote not on the page's newest reading (whitespace collapsed, case kept). An unknown claim or contributor exits 3, an empty quote, capacity or rationale exits 2.

## restate withdraw
- top: status, restatement, pair
- restatement: id, original_version, restated_version, decision, document, page, quote, contributor, organisation, capacity, rationale, created_at

Adds a `withdrawn` row for the pair of the two claims' newest versions (`page` and `quote` null); `pair` is the pair as computed afterwards, usually `unresolved conflict`, or null when the claims no longer form a pair. Refused (exit 4) when no current `recorded` row names the claims in that order.

## review company
- top: status, claim, entry, disagreement
- claim: id, document, company, version
- entry: id, ledger, claim_version, contributor, organisation, contributor_version, capacity, scope, reviewed_on, conclusion, outcome, evidence_document, evidence_company, evidence_page, evidence_note, evidence_state, latest, binds, self_declared, evidence_deleted, created_at

Records a company confirmation on the newest version of a current claim of an active document. `claim.company` is the claim's company, read from the claim; `entry.organisation` is the contributor's own, as declared. `entry` is the new row as `review list` shows it: `ledger` `company`; `capacity`, `scope`, `conclusion` and `evidence_note` exactly as typed; `reviewed_on` the `--date` (default today); `outcome` `accepted`, `rejected` or `disputed`; `evidence_document` and `evidence_page` the cited document and page or null, with `evidence_company` (that document's company) and `evidence_state` (its state now: `registered`, `restored`, `archived` or `deleted`; null without a document); `contributor_version` the contributor version recorded; `latest` and `binds` (see `review list`); `self_declared` always true; `evidence_deleted` null unless the claim's document or the evidence document was deleted, else `{"document": N, "at": ...}`. `disagreement` is that of the version after recording. No run is opened. Refused, writing nothing: an unknown claim, contributor or evidence document (exit 3); an empty capacity, scope, conclusion or note, an outcome other than the three, a malformed or future date, no evidence document and no note, a page without a document (exit 2); a claim that is not current, a claim or evidence document that is archived or deleted, a `--version` that is not the claim's newest, a page outside the document or on a spreadsheet (exit 4).

## review auditor
- top: status, claim, entry, disagreement
- claim: id, document, company, version
- entry: id, ledger, claim_version, contributor, organisation, contributor_version, capacity, scope, reviewed_on, conclusion, outcome, evidence_document, evidence_company, evidence_page, evidence_note, evidence_state, latest, binds, self_declared, evidence_deleted, created_at

As `review company`, in the other ledger (`ledger` `auditor`).

## review list
- top: status, claim, versions
- claim: id, document, document_state, company, version, state, evidence_deleted
- versions: id, binds, company_confirmations, auditor_reviews, disagreement

Every version of one claim, oldest first; `claim.version` is the newest, `claim.state` as in `claims list`, `document_state` the state of the claim's document (an archived or deleted document's claim is listed too). `company_confirmations` and `auditor_reviews` are two lists, oldest first, each entry with the keys of `review company`'s `entry`; none is hidden. `latest` is true on a contributor's newest entry in that ledger on that version (by contributor key), false on their earlier ones. `binds` (on the version and on each entry) is true only for the claim's newest version. `disagreement` is null, or `{"company": [...], "auditor": [...]}`, the latest outcomes of each ledger in the order accepted, rejected, disputed, when both are non-empty and differ. An unknown claim is refused (exit 3). See `docs/reviews.md`.

## review pending
- top: status, kinds
- kinds: kind, entries

Every `needs_re_review` entry of the claims of active documents, grouped by `kind` in the order `correction`, `period review`, `boundary review`, `company confirmation`, `auditor review`, `reviewer flag`, `adjudication` (a kind with no entry is left out). Each of `entries`, by claim then record id, has `claim`, `document`, `company` (the claim's company), `version` (the claim's newest version), `entry` (the `needs_re_review` entry) and `renew` (the command that makes a record of that kind on the newest version, with the claim and version filled in). `--company NAME` and `--doc ID` narrow the documents; an unknown company or document exits 3, an archived or deleted `--doc` exits 4. Reads only. See `docs/reviews.md`.

## adjudicate list
- top: status, candidates, hidden, earlier
- candidates: series_id, company_id, company, metric_key, label, reporting_boundary, boundary_detail, period_start, period_end, state, reason, restatement, a, b, adjudications, adjudication_state
- earlier: id, low_version, high_version, low_claim, high_claim, state, rationale, procedure, counter_document, counter_page, counter_note, evidence_state, counter_company, follow_up, closure_reason, contributor, organisation, capacity, binds, created_at, self_declared, evidence_deleted, pair_state

`candidates` are the pairs of `restate list` whose `state` is `unresolved conflict` (both documents active), with `adjudication_state` `unreviewed candidate`, `explained difference`, `extraction error`, `reviewer-confirmed issue` or `evidence not found`: the state of the newest adjudication row that binds, else unreviewed. `adjudications` lists every adjudication row whose two versions belong to the candidate's two claims, oldest first, with the keys of `earlier` less `pair_state`; `state` is the stored code (`explained_difference`, `extraction_error`, `reviewer_confirmed_issue`, `evidence_not_found`); `binds` is false when either version it names is not its claim's newest; `evidence_state` is the counter-evidence document's newest state (`registered`, `restored`, `archived`, `deleted`) and `counter_company` its company, both null without a counter document; `evidence_deleted` is null unless a document it names was deleted, else `{"document": N, "at": ...}`; `self_declared` is always true. `earlier` holds the adjudication rows on active documents whose two claims are not a candidate now, with `pair_state` the state of the claims' pair now (`restatement`, `same value`, `not compared`) or null when they form none. `--company NAME`, `--claim CLAIM` (a claim of an active document; archived or deleted is refused, exit 4) and `--state unreviewed|explained-difference|extraction-error|reviewer-confirmed-issue|evidence-not-found` narrow the candidates; `hidden` counts the candidates the state filter hid. See `docs/adjudication.md`.

## adjudicate record
- top: status, adjudication, adjudication_state, next
- adjudication: id, low_version, high_version, low_claim, high_claim, state, rationale, procedure, counter_document, counter_page, counter_note, evidence_state, counter_company, follow_up, closure_reason, contributor, organisation, capacity, binds, created_at, self_declared, evidence_deleted

Records an adjudication of the candidate the two claims' newest versions form. `adjudication_state` is the candidate's state afterwards; `next` names `gct correct` for an `extraction-error` (the claim is not changed) and is null otherwise. Refused, writing nothing: `--state restatement` (exit 4, naming `gct restate record`), an unknown state (exit 2), an empty rationale, procedure, capacity, counter-evidence note, follow-up or closure reason, `explained-difference` without `--counter-doc` or `--counter-note`, `--counter-page` without `--counter-doc` (exit 2); an unknown claim, contributor or counter document (exit 3); the same claim twice, claims that are not an unresolved conflict now, an archived or deleted document on either side or as counter-evidence, a page outside the counter document or on a spreadsheet (exit 4).

## adjudicate status
- top: status, companies
- companies: company, candidates, unreviewed, explained_difference, extraction_error, reviewer_confirmed_issue, evidence_not_found

One record per company with candidates (`--company NAME` for one): how many, and how many are in each state of `adjudicate list`. Only binding rows count, so a row on an earlier version leaves its candidate unreviewed.

## flag raise
- top: status, flag
- flag: id, claim, version, decision, rationale, contributor, organisation, capacity, latest, binds, created_at, self_declared

Records a potential greenwashing concern on `--version`, which must be the claim's newest version, of a current claim of an active document. Refused, writing nothing: a version that is not the newest, a claim that is not current, an archived or deleted document (exit 4); an unknown claim or contributor (exit 3); an empty capacity or rationale (exit 2).

## flag withdraw
- top: status, flag
- flag: id, claim, version, decision, rationale, contributor, organisation, capacity, latest, binds, created_at, self_declared

As `flag raise`, with `decision` `withdrawn`; refused (exit 4) when the contributor's newest flag on that version is not `raised`.

## flag list
- top: status, flags
- flags: id, claim, version, decision, rationale, contributor, organisation, capacity, latest, binds, created_at, self_declared

Every flag row on a claim of an active document, oldest first (`--company NAME` or `--claim CLAIM`). `latest` is true on a contributor's newest row on that version; `binds` is false once the version is not its claim's newest.

## highlight add
- top: status, claim, entry
- claim: id, document, company, version
- entry: id, claim_version, contributor, organisation, contributor_version, capacity, note, latest, binds, self_declared, evidence_deleted, created_at

Records a highlight on `--version`, which must be the claim's newest version, of a current claim of an active document. `entry` is the new row as `highlight list` shows it: `capacity` and `note` exactly as typed; `contributor_version` the contributor version recorded; `self_declared` always true; `evidence_deleted` null unless the claim's document was deleted, else `{"document": N, "at": ...}`. A highlight is not a confirmation, a correction or a review outcome: no state, count or renewed-review entry reads it. No run is opened. Refused, writing nothing: an unknown claim or contributor (exit 3); an empty capacity or note (exit 2); a claim that is not current, an archived or deleted document, a `--version` that is not the claim's newest (exit 4).

## highlight list
- top: status, claim, versions
- claim: id, document, document_state, company, version, state, evidence_deleted
- versions: id, binds, highlights

Every version of one claim, oldest first (an archived or deleted document's claim is listed too), each with its `highlights`, oldest first, with the keys of `highlight add`'s `entry`; none is hidden. `latest` is true on a contributor's newest highlight on that version (by contributor key); `binds` (on the version and on each entry) is true only for the claim's newest version. An unknown claim is refused (exit 3). See "Highlights" in `docs/reviews.md`.

## claims list
- top: status, document, claims
- claims: id, page_number, locator, value_text, value, unit_text, metric_text, period_label, reporting_boundary, boundary_label, method, boxes, source_match, source_match_reason, period, boundary, claim_state, needs_re_review, sheet, cell

`sheet` and `cell` locate a spreadsheet claim (`Energy`, `C7`; `page_number` is then the sheet's 1-based position and `locator` is `s<position>r<row>`); both are null for a claim on a page.

One record per claim, from its newest version. `id` is the claim id that `gct infer resolve` and `gct infer reject --claim` take. `document` is the id. `period` and `boundary` are the effective values (see `infer resolve` for their keys); `period_label` and `reporting_boundary` stay as extracted. `value_text`, `unit_text`, `metric_text` and `period_label` are as printed; `metric_text` is null for a table row with no label; `value` is null unless the figure is in plain Western form. `reporting_boundary` is `unknown` until a later step sets it. `method` is `rung1-rules` for the fixed-rule baseline. `boxes` is a list of `[x0, top, x1, bottom]` in PDF points from the top-left of the page, or null when there is no box. `source_match` is the newest status of the location: `matched` (the words in the box reproduce the figure), `cited` (page known, but no box or the box no longer reproduces it) or `unresolved` (the page has no reading); null when it has not been checked yet (run `gct link`). `source_match_reason` is null for `matched`, else `no box`, `box does not reproduce the figure`, `reading has no text direction: gct read again` (a reading made before reading config 3), `page not read: gct read` or `spreadsheet check not built`. `method` is `correction` when the newest version is a contributor's correction. `boundary_label` is a boundary header printed above the figure's table column (`Standalone*`, `Consolidated`), as printed, or null; it does not set `reporting_boundary`. `claim_state` is `current` (the page's newest reading was extracted with the current rules and found the claim), `not found in the newest reading` or `page read again, not yet extracted`; claims in the last two states are listed, never as current. `--state current|not-found|not-extracted` lists one state only. `needs_re_review` lists the decisions made on an earlier version that do not apply to the newest one, each `kind` (`correction`, `period review`, `boundary review`, `company confirmation`, `auditor review`, `reviewer flag` or `adjudication`), `id` (the record) and `version` (the claim version it was made on); an `adjudication` entry also has `with` (`claim`, `version`: the other side the row names). It is empty when there are none. See "Renewed review" in `docs/reviews.md`.

## claims history
- top: status, claim, versions
- claim: id, document, document_state, page_number, locator, state, needs_re_review, evidence_deleted
- versions: id, method, config_version, run_id, created_at, metric_text, value_text, value, unit_text, period_label, boundary_label, evidence_refs, inferences, reviews, correction, seen, company_confirmations, auditor_reviews, disagreement, reviewer_flags, adjudications

Every version of one claim, oldest first; nothing is left out. `evidence_deleted` is null unless the claim's document was deleted, else `{"document": N, "at": ...}`: every review and correction listed then keeps its contributor, decision and date, its capacity and rationale read `cleared with document N`, and the version's values are cleared (see `docs/deletion.md`). `document_state` is the state of the claim's document (`registered`, `archived` or `restored`); an archived document's claims keep their whole history. `state` and `needs_re_review` are those of `claims list`. `evidence_refs` are the version's locations, each `id`, `page_number`, `boxes`, `sheet`, `cell` and `source_match` (every check of it, oldest first: `id`, `status`, `reason`, `run_id`, `created_at`). `inferences` and `reviews` are the period and boundary rows of `gct infer` made on this version. `correction` is null for an extracted version, else the record that made it: `id`, `corrects_version`, `fields` (the fields changed), `replaced` (`value_text`, `unit_text`, `metric_text`, `period_label` of the version it corrects), `contributor`, `organisation`, `capacity`, `rationale`, `created_at`. `seen` lists the extractions that found this version: `page_id` (the reading), `config_version` (the extract rules), `run_id`, `created_at`. `company_confirmations`, `auditor_reviews` and `disagreement` are those of `review list` for this version; `reviewer_flags` are the flag rows on it (keys of `flag list`) and `adjudications` the adjudication rows naming it on either side (keys of `adjudicate record`'s `adjudication`, plus `other_document_state`, the state of the other claim's document), oldest first, those of an inactive document included; the text line ends `; other document archived` when that document is not active. An unknown claim is refused (exit 3).

## sheet show
- top: status, document, sheets
- sheets: name, position, header, rows, mapping

One record per sheet of a CSV or XLSX document, in workbook order (a CSV is one sheet named after its file, position 1). `header` is row 1 as stored; `rows` the first five data rows, each `row` (the spreadsheet row number) and `cells`, every row as wide as the widest. `mapping` is the sheet's current mapping with the keys of `sheet map`, or null (`no confirmed mapping`). A PDF document is refused (exit 4), as is a deleted one (its mappings are listed by `doc show`).

## sheet map
- top: status, mapping
- mapping: id, document, sheet, position, metric, value, unit, period, boundary, company, note, year_end, boundary_is, boundary_detail, contributor, organisation, capacity, rationale, created_at

Stores one insert-only mapping row; the newest per sheet is current and applies from the next `gct extract`. `metric` to `note` are the headers of row 1 the columns were mapped to (null when not mapped). `year_end` (`MM-DD`) and `boundary_is` are declarations: `gct infer` turns them into proposals, and nothing is effective until `gct infer accept`. `contributor` and `organisation` are the contributor's name and organisation. An unknown sheet is refused (exit 3); a header not in row 1 or printed twice in it (exit 4); a missing `--value`, a bad `--year-end` or a `--boundary-detail` without `--boundary-is` (exit 2).

## correct
- top: status, claim, version, correction

Records a correction of the newest version of a current claim as a new version with `method` `correction`. `version` is the new version's id; `correction` has the keys of the `claims history` correction record. The value is stored as typed, and gets a number only in the plain Western form. The correction copies the corrected version's page and boxes, so the next `gct link` checks the corrected figure against the page (`cited` when the box does not reproduce it). No field given, or an empty one, gives exit 2; an unknown claim or contributor exit 3; a claim that is not current, or values equal to the current ones, exit 4.

## contributor add
- top: status, contributor
- contributor: key, name, organisation, version, created_at

`version` is the id of the contributor version every record made now will cite. A key that exists is refused (exit 4).

## contributor edit
- top: status, contributor
- contributor: key, name, organisation, version, created_at

A new version with the same key; a field not given keeps its value. Records made earlier keep the version they cite.

## contributor list
- top: status, contributors
- contributors: key, name, organisation, version, created_at

The newest version of each contributor, by key.

## expect add
- top: status, expectation
- expectation: id, company, metric_text, period_label, documents, found, claims, state, reasons, accepted, confirmation

`metric_text` is the wording as typed, whitespace collapsed; `period_label` as typed or null. `documents` lists the ids of the fixed document set. `found` is true when the newest version of a `current` claim (see `claims list`) on the set has a metric wording containing `metric_text` (case-insensitive) and, when given, the same period label as printed; `claims` then lists them (`id`, `document_id`, `page_number`, `metric_text`, `value_text`, `unit_text`, `period_label`) and `state` is null. Otherwise `state` is `processing incomplete or failed`, `not found in successfully processed material` or `confirmed disclosure gap`. `reasons` lists what keeps pages from being ready, as `{type, reason, count}`: `type` is `text`, `tables` or `figures` with `count` pages and `reason` `not read`, `read failed`, a quality flag, `charts not read` or `accepted on an earlier reading`; or `text` with `reason` `wording printed but no figure extracted` (no claim on those pages carries the wording) or `wording printed; figures found only for other or missing period labels` (claims there carry the wording but not the expected period label), `count` pages and `pages` listing them as `"document:page"`; either keeps the item out of state 2 (exact wording only, ignoring case and extra spaces; the period is never looked for on the page); or `document` with `count` documents and `reason` `not opened` or `not a PDF`; or `confirmation`, naming an earlier gap confirmation that `was made on older readings` or `no longer holds: processing incomplete`. `accepted` lists pages counted as ready by a reviewer's acceptance, as `{type, accepted, count}` with `accepted` `accepted by <name> (<capacity>)`; they are never counted as checked. `confirmation` is null or the newest gap confirmation: `id`, `contributor`, `organisation`, `capacity`, `rationale`, `created_at`, `current` (false once the readings it was made on are no longer the newest, the state is no longer `not found in successfully processed material`, or the item is found; a found item still shows its newest confirmation), `evidence_deleted` (null, or `{"document": N, "at": ...}` when a document it looked in was deleted; its capacity and rationale then read `cleared with document N`).

## expect list
- top: status, expectations
- expectations: id, company, metric_text, period_label, documents, found, claims, state, reasons, accepted, confirmation

One record per expectation, as for `expect add`, computed when asked.

## pages accept
- top: status, document, type, pages, accepted

`pages` lists the page numbers accepted for `type` on their newest reading; `accepted` is `accepted by <name> (<capacity>)`. A page not read or whose newest read failed, a page already checked for that type, and a page outside the document are refused (exit 4) and nothing is recorded.

## gap confirm
- top: status, expectation

`expectation` is as for `expect add`, after the confirmation. Refused (exit 4) when the item is found or its computed state is not `not found in successfully processed material`; the cause names the incomplete types, or, for a wording-printed reason, the pages, with a next action to check them (reading, retrying or accepting does not clear that reason).

## publish build
- top: status, version, built_at, history_mark, companies, documents

In the published version (`projection_schema` 4), a claim's `period_kind`, `period_start`, `period_end`, `reporting_boundary` and `boundary_detail` hold only accepted or resolved values, else what was extracted. A proposal is in `proposed_period_kind`, `proposed_period_start`, `proposed_period_end`, `proposed_reporting_boundary` and `proposed_boundary_detail`. `period_state` and `boundary_state` are `resolved`, `accepted`, `proposed`, `unresolved` or `extracted`. `period_basis` and `boundary_basis` (`{"page", "wording"}` as JSON, or null) are filled for a proposal as well as for an accepted value, so read them together with the state: while the state is `proposed` the main values stay empty. From `projection_schema` 6 (story 4.1) a claim also has `metric_key` (the assigned key, null when unmapped), `metric_rule`, `unit_key`, `unit_factor`, `series_id`, `match_state` (`series`, `reviewed`, `uncertain` or `not matchable`) and `match_reason`, and the tables `series` and `series_point` hold the series of `gct series list` and their points (a time series is `series_point` ordered by `period_end`). From `projection_schema` 8 (story 4.4) the table `hidden_by_archive` has one row per archived document (`document_id`, `logical_name`, `archived_at`, `claims`, `evidence_refs`, `review_records`, counted as in `doc archive`), and `meta` key `hidden_by_archive` holds the totals as JSON (`documents`, `claims`, `evidence_refs`, `review_records`). An archived document, its claims, their locations and series points are not in the other tables, and `expected_item_document` lists only active documents.

## publish restore
- top: status, version, built_at, history_mark, companies, documents

## publish status
- top: status, current_version, built_at, history_mark, companies, documents, previous_version, stale, files

## run list
- top: status, runs
- runs: id, started_at, finished_at, command, gct_version, outcome, events

## run show
- top: status, id, started_at, finished_at, command, gct_version, outcome, events, methods, failures, retries, cost_estimated, cost_confirmed, outputs
- events: id, at, kind, stage, item, method, outcome, cost_estimated, cost_confirmed, message

## run resume
- top: status, run_id, of_run, documents
- documents: id, logical_name, pages, read, cached, flagged, failed, flags, action, cause, next_action

Resuming a `read` run gives the keys of `read` plus `run_id` (the new run, null when there was nothing to read) and `of_run` (the run resumed). Resuming an `extract` run gives the keys of `extract` plus the same two, a `link` run the keys of `link`, an `infer` run the keys of `infer`, a `match` run the keys of `match`, and a `sheet` run (the spreadsheet part of `gct extract`) the keys of `extract`. Resuming a `doc add` run gives the keys of `doc add` (`items` in place of `documents`) plus the same two. `status`, `cause`, `next_action` and the exit codes are as for `read`, `extract` and `doc add`.

## run retry
- top: status, run_id, of_run, documents
- documents: id, logical_name, pages, read, cached, flagged, failed, flags, action, cause, next_action

The same shapes as `run resume`. For a `read` run, `read` counts the failed pages read again and `pages` is still the document's page count; `action` `skipped` with a cause also marks a document no longer active. For an `extract` run, `pages` counts only the failed pages extracted again; for a `link` run, `refs` counts only the failed locations checked again. With nothing failed: `{"status": "ok", "run_id": null, "of_run": N, "documents": []}` (`items` for a `doc add` run), exit 0, and no new run.

## approve spend
- top: status, cap, spent

Amounts are USD. `spent` is the cost of every attempt so far: the cost the provider returned where there is one (confirmed), otherwise gct's estimate (usage times the configured prices, or the pre-call estimate).

## approve transfer
- top: status, provider, granted

## approve list
- top: status, cap, spent, adapters
- adapters: name, external, paid, transfer_granted

`cap` is null when no spend cap was ever set. `transfer_granted` is true only when the newest transfer approval for that adapter was given for its current address and model. `adapters` lists every adapter in the configuration file (empty without one).

## model list
- top: status, path, adapters
- adapters: name, provider, model, base_url, external, paid, price_in, price_out, api_key_env, key_set

`path` is the configuration file looked for (`$GCT_MODELS`, else `~/.config/gct/models.toml`). `api_key_env` is the name of the environment variable that holds the key (null for none); `key_set` says whether it is set. The key itself is never printed.

## measure g2
- top: published_version, gct_commit, scorer_version, status, run_id, report_path, workspace, published, gold, headline, target, delta, rows, types, document_types, documents, runs, adjudication, aggregate
- published: workspace, built_at, history_mark, sha256
- gold: folder, version, commit, sha256
- rows: id, kind, company, doc, document_type, page, verdict, failing, reason, claim, value_text, unit_text, metric_text, iou, evidence_found, value_elsewhere_in_document, ceiling
- types: company, kind, n, found, partial, missed, found_text, verdict, re_adjudicate, evidence_found_among_found, evidence_found_among_partial, value_and_unit_on_gold_page, partial_failing, missed_reasons, value_elsewhere_in_document, ceiling
- document_types: company, document_type, kind, n, found, partial, missed, found_text, verdict, re_adjudicate, evidence_found_among_found, evidence_found_among_partial, value_and_unit_on_gold_page, partial_failing, missed_reasons, value_elsewhere_in_document, ceiling
- documents: doc, company, document_type, document_id, n, found, partial, missed, found_text, verdict, re_adjudicate, evidence_found_among_found, evidence_found_among_partial, value_and_unit_on_gold_page, partial_failing, missed_reasons, value_elsewhere_in_document, ceiling, method_mix, cost
- runs: row, state
- adjudication: seed, missed, found_sample
- aggregate: kind, n, found, partial, missed, found_text, verdict, re_adjudicate, evidence_found_among_found, evidence_found_among_partial, value_and_unit_on_gold_page, partial_failing, missed_reasons, value_elsewhere_in_document, ceiling

`gct measure g2 --gold FOLDER [--workspace PATH] [--seed N]` scores the current published version (`published/vN.db`) against a gold folder (`MANIFEST.json`, `documents.json`, `text.jsonl`, `tables.jsonl`, `figures.jsonl`) with the rules frozen as `scorer_version` 1 (story 3.6). Claims are the published version's `claim_state` `current` claims of the gold document (joined by `sha256`) on the gold page. The published `period_start`, `period_end` and `reporting_boundary` are compared; `proposed_*` values are never read. The working database is opened read-only, only for each page's rung and method (`method_mix`) and the run log costs (`cost`: `estimated` and `confirmed` are null with a `reason` when the run log has no cost event for the document). Its content is never changed, but SQLite adds `workspace.db-wal` and `workspace.db-shm` beside it to read it; in a read-only workspace folder the command refuses (exit 4) and names the folder. The text output's first line, and the first three keys of the JSON, name the published version, the gct commit (`unknown` outside a git checkout, with `-dirty` appended when a tracked file differs from that commit; `gold.commit` likewise) and the scorer version. `published` identifies the scored version: the workspace path, its `built_at` and `history_mark`, and the sha256 of `vN.db`.

`verdict` in `rows` is `Found`, `Partial` (value and unit match; `failing` lists metric, entity, boundary or period) or `Missed` (`reason`: `gold value is not a figure`, `page has no current claim`, `no value match on the page`, `value matches, unit does not`). `evidence_found` is true when the chosen Found or Partial claim's boxes on the gold page enclose a box with IoU (`iou`) of at least 0.5 with the gold `bbox`. `ceiling` lists why a row cannot be Found under rule 1 (`gold boundary segment`, `gold currency unit`, `gold value is not a figure`). A summary's `verdict` is `UNMEASURED` (no gold rows), `fail` (Found below 90%) or `at or above 90% before adjudication`; `re_adjudicate` is true above 95%. Every percentage is printed beside its count (`found_text`, `1/8 (12.5%)`). `found_sample` holds, per company and content type, 10% of the Found ids (at least 10, all when fewer) drawn with `random.Random(seed)` over the sorted ids. `runs` reports `rung 1` and `local escalation` (`not run` when no page was read above rung 1). `aggregate` comes last.

`--against REPORT` compares with a previous report of the same gold version. `delta` (null without it) is `{"attributed_to", "previous", "types"}`: `scorer` when the published version is the same (its whole `published` identity, not only the number, so version 1 of another workspace or of a rebuilt one is a different version) and the scorer version changed, `extraction` when the scorer version is the same; each type gives `before`, `after`, `found_change` and `partial_change`. When both changed the command refuses: re-score the previous baseline's published version with the new scorer first. In the text output the delta is the second line, before any result.

The report is also written to `g2-report-v<N>-<run id>.json` in the workspace's parent folder. The command refuses with exit 4 and writes nothing when there is no published version, a file listed in `MANIFEST.json` (and each scored gold file) is absent or has another sha256, a gold document has no document row in the version or a different sha256, or a gold company has no current claims; a missing gold file is exit 3.

## serve
- top: status, url, port

`POST /api/claims/{id}/corrections` takes a JSON object with the `gct correct` fields as strings (`value`, `unit`, `metric`, `period_label`, `contributor`, `capacity`, `rationale`) and answers like `correct` plus `data_version`, the new published version. A field that is present and not a string is refused with 400 and nothing is written. The correction is committed before the published version is rebuilt: if the build then fails, the response is the error (500, `Something unexpected went wrong.`, with the error log path in `next_action`), the correction stays in the workspace, and no new published version exists until `gct publish build` runs.

## error
- top: status, cause, next_action
