# CLI JSON output

Every command prints one JSON object on stdout when `--json` is given. `status` is one of
`ok`, `partial`, `exists`, `already_initialised`, `error`. The lines below are checked by
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

`status` is `ok` when every item was registered or a duplicate (and always with `--plan`), else `partial` (exit 4), which adds `cause` and `next_action` at the top; `next_action` names the sources that were not added. `action` is `registered`, `duplicate`, `refused` or `failed`; with `--plan` it is `would register`, `would fetch`, `duplicate` or `refused`. `document` has the keys of `doc show` for `registered` and `duplicate` (null for a duplicate of an earlier item in the same plan), null otherwise. `cause` and `next_action` are set only for `refused` and `failed`. `cached` is true when a URL was already fetched by an earlier command and was not downloaded again.

## doc list
- top: status, documents
- documents: id, company, logical_name, version, sha256, kind, file_type, privacy, size_bytes, source, created_at, state

## doc show
- top: status, document
- document: id, company, logical_name, version, sha256, kind, file_type, privacy, size_bytes, source, created_at, state

## doc pages
- top: status, document, pages
- pages: page_number, rung, method, width, height, words, tables, flags, artifact

One record per page number, from its newest reading. `document` is the id. `flags` lists the quality codes (`no_text`, `fragmented_text`, `sparse_tables`). `artifact` is the SHA-256 of the reading file `artifacts/<first two characters>/<sha256>.json`. An unread document gives an empty `pages` list.

## read
- top: status, documents
- documents: id, logical_name, pages, read, cached, flagged, failed, flags, action, cause, next_action

`status` is `ok` when no document and no page failed (flags are not failures; exit 0), else `partial` (exit 4), which adds `cause` and `next_action` at the top. `action` is `read`, `skipped` (not a PDF, or for `run retry` no longer active) or `failed` (the PDF could not be opened). `read` counts pages read by this command, `cached` pages already read under the same document bytes and reader settings, `failed` pages that raised. `flags` maps each quality code to its number of pages. `cause` is set for `skipped`; `cause` and `next_action` for `failed` and for a `read` document with failed pages; null otherwise. Nothing to read gives `{"status": "ok", "documents": []}`.

## extract
- top: status, documents
- documents: id, logical_name, pages, extracted, cached, failed, figures, no_box, action, cause, next_action

`status` is `ok` when no page failed (exit 0), else `partial` (exit 4), which adds `cause` and `next_action` at the top. `action` is `extracted` or `skipped` (not a PDF, or no page read yet; then `next_action` is `read it first: gct read`). `pages` counts the read pages, `extracted` the pages extracted by this command, `cached` the pages whose reading had not changed since they were extracted. `figures` and `no_box` count the claims of those pages and the claims without a source box (source match `cited`, reason `no box`). Nothing to extract gives `{"status": "ok", "documents": []}`.

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

One series as in `series list`: the points of the latest period, or with `--all` every point, oldest period first. Each point's `pairs` give the state of every pair of its same-period set. An unknown series is refused (exit 3).

## restate list
- top: status, pairs, hidden
- pairs: series_id, company_id, company, metric_key, label, reporting_boundary, boundary_detail, period_start, period_end, state, reason, restatement, a, b

One record per pair of points of one same-period set of a series, over the active documents (`--company NAME` for one company). `a` and `b` are the two points as in `series list` (`claim_id, claim_version_id, document_id, page_number, locator, period_start, period_end, value_text, unit_text, unit_key, number, value_base, link, comparable, reason, review`), ordered by document id then claim id for display only (the store never orders reports). `state` is `same value`, `restatement`, `unresolved conflict` or `not compared`; `reason` is set only for `not compared` (`unit as printed`, `reviewed, not comparable`, `no numeric value`, `same table row`). `restatement` is null or the current record: `id, original_version, restated_version, decision, document, page, quote, contributor, organisation, capacity, rationale, created_at`. `--state same|restatement|unresolved|not-compared` hides the other pairs and `hidden` counts them (0 without `--state`). See `docs/restatements.md`.

## restate show
- top: status, claim, pairs, versions
- claim: id, document, page_number, version, match_state, match_reason, series_id
- versions: claim, id, reviews

`pairs` are the pairs (as in `restate list`) the claim's newest version is in. `versions` holds every version of the claim, oldest first, then the other version of each pair and of each restatement row on the claim's versions; `reviews` is every record attached to that version: `inference_reviews`, `corrections` (with `role` `made this version` or `replaced this version`), `match_reviews` (with the series id in `series`), `source_match` (the newest check of each evidence ref, `status` null when not checked) and `restatements` (every row naming the version, withdrawn and superseded ones included, with `role` `original` or `restated`, `current` and `binds`, false when either version it names is not its claim's newest; see `docs/restatements.md`). An unknown claim is refused (exit 3).

## restate record
- top: status, restatement, pair
- restatement: id, original_version, restated_version, decision, document, page, quote, contributor, organisation, capacity, rationale, created_at

Records that the `--restated` claim's newest version restates the `--original` claim's newest version, citing `--page` of the restated claim's document and `--quote`, the line as printed there. `pair` is the pair as computed afterwards (state `restatement`). Refused (exit 4): the two claims not in one same-period set of one series, a claim that is not current or whose newest version has not been matched yet, a pair that is `same value` or `not compared`, a page outside the document or not read, a quote not on the page's newest reading (whitespace collapsed, case kept). An unknown claim or contributor exits 3, an empty quote, capacity or rationale exits 2.

## restate withdraw
- top: status, restatement, pair
- restatement: id, original_version, restated_version, decision, document, page, quote, contributor, organisation, capacity, rationale, created_at

Adds a `withdrawn` row for the pair of the two claims' newest versions (`page` and `quote` null); `pair` is the pair as computed afterwards, usually `unresolved conflict`, or null when the claims no longer form a pair. Refused (exit 4) when no current `recorded` row names the claims in that order.

## claims list
- top: status, document, claims
- claims: id, page_number, locator, value_text, value, unit_text, metric_text, period_label, reporting_boundary, boundary_label, method, boxes, source_match, source_match_reason, period, boundary, claim_state, needs_re_review

One record per claim, from its newest version. `id` is the claim id that `gct infer resolve` and `gct infer reject --claim` take. `document` is the id. `period` and `boundary` are the effective values (see `infer resolve` for their keys); `period_label` and `reporting_boundary` stay as extracted. `value_text`, `unit_text`, `metric_text` and `period_label` are as printed; `metric_text` is null for a table row with no label; `value` is null unless the figure is in plain Western form. `reporting_boundary` is `unknown` until a later step sets it. `method` is `rung1-rules` for the fixed-rule baseline. `boxes` is a list of `[x0, top, x1, bottom]` in PDF points from the top-left of the page, or null when there is no box. `source_match` is the newest status of the location: `matched` (the words in the box reproduce the figure), `cited` (page known, but no box or the box no longer reproduces it) or `unresolved` (the page has no reading); null when it has not been checked yet (run `gct link`). `source_match_reason` is null for `matched`, else `no box`, `box does not reproduce the figure`, `reading has no text direction: gct read again` (a reading made before reading config 3), `page not read: gct read` or `spreadsheet check not built`. `method` is `correction` when the newest version is a contributor's correction. `boundary_label` is a boundary header printed above the figure's table column (`Standalone*`, `Consolidated`), as printed, or null; it does not set `reporting_boundary`. `claim_state` is `current` (the page's newest reading was extracted with the current rules and found the claim), `not found in the newest reading` or `page read again, not yet extracted`; claims in the last two states are listed, never as current. `--state current|not-found|not-extracted` lists one state only. `needs_re_review` lists the decisions made on an earlier version that do not apply to the newest one, each `kind` (`correction`, `period review` or `boundary review`), `id` (the record) and `version` (the claim version it was made on); it is empty when there are none.

## claims history
- top: status, claim, versions
- claim: id, document, page_number, locator, state, needs_re_review
- versions: id, method, config_version, run_id, created_at, metric_text, value_text, value, unit_text, period_label, boundary_label, evidence_refs, inferences, reviews, correction, seen

Every version of one claim, oldest first; nothing is left out. `state` and `needs_re_review` are those of `claims list`. `evidence_refs` are the version's locations, each `id`, `page_number`, `boxes` and `source_match` (every check of it, oldest first: `id`, `status`, `reason`, `run_id`, `created_at`). `inferences` and `reviews` are the period and boundary rows of `gct infer` made on this version. `correction` is null for an extracted version, else the record that made it: `id`, `corrects_version`, `fields` (the fields changed), `replaced` (`value_text`, `unit_text`, `metric_text`, `period_label` of the version it corrects), `contributor`, `organisation`, `capacity`, `rationale`, `created_at`. `seen` lists the extractions that found this version: `page_id` (the reading), `config_version` (the extract rules), `run_id`, `created_at`. An unknown claim is refused (exit 3).

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

`metric_text` is the wording as typed, whitespace collapsed; `period_label` as typed or null. `documents` lists the ids of the fixed document set. `found` is true when the newest version of a `current` claim (see `claims list`) on the set has a metric wording containing `metric_text` (case-insensitive) and, when given, the same period label as printed; `claims` then lists them (`id`, `document_id`, `page_number`, `metric_text`, `value_text`, `unit_text`, `period_label`) and `state` is null. Otherwise `state` is `processing incomplete or failed`, `not found in successfully processed material` or `confirmed disclosure gap`. `reasons` lists what keeps pages from being ready, as `{type, reason, count}`: `type` is `text`, `tables` or `figures` with `count` pages and `reason` `not read`, `read failed`, a quality flag, `charts not read` or `accepted on an earlier reading`; or `text` with `reason` `wording printed but no figure extracted` (no claim on those pages carries the wording) or `wording printed; figures found only for other or missing period labels` (claims there carry the wording but not the expected period label), `count` pages and `pages` listing them as `"document:page"`; either keeps the item out of state 2 (exact wording only, ignoring case and extra spaces; the period is never looked for on the page); or `document` with `count` documents and `reason` `not opened` or `not a PDF`; or `confirmation`, naming an earlier gap confirmation that `was made on older readings` or `no longer holds: processing incomplete`. `accepted` lists pages counted as ready by a reviewer's acceptance, as `{type, accepted, count}` with `accepted` `accepted by <name> (<capacity>)`; they are never counted as checked. `confirmation` is null or the newest gap confirmation: `id`, `contributor`, `organisation`, `capacity`, `rationale`, `created_at`, `current` (false once the readings it was made on are no longer the newest, the state is no longer `not found in successfully processed material`, or the item is found; a found item still shows its newest confirmation).

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

In the published version (`projection_schema` 4), a claim's `period_kind`, `period_start`, `period_end`, `reporting_boundary` and `boundary_detail` hold only accepted or resolved values, else what was extracted. A proposal is in `proposed_period_kind`, `proposed_period_start`, `proposed_period_end`, `proposed_reporting_boundary` and `proposed_boundary_detail`. `period_state` and `boundary_state` are `resolved`, `accepted`, `proposed`, `unresolved` or `extracted`. `period_basis` and `boundary_basis` (`{"page", "wording"}` as JSON, or null) are filled for a proposal as well as for an accepted value, so read them together with the state: while the state is `proposed` the main values stay empty. From `projection_schema` 6 (story 4.1) a claim also has `metric_key` (the assigned key, null when unmapped), `metric_rule`, `unit_key`, `unit_factor`, `series_id`, `match_state` (`series`, `reviewed`, `uncertain` or `not matchable`) and `match_reason`, and the tables `series` and `series_point` hold the series of `gct series list` and their points (a time series is `series_point` ordered by `period_end`).

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

Resuming a `read` run gives the keys of `read` plus `run_id` (the new run, null when there was nothing to read) and `of_run` (the run resumed). Resuming an `extract` run gives the keys of `extract` plus the same two, a `link` run the keys of `link`, an `infer` run the keys of `infer`, and a `match` run the keys of `match`. Resuming a `doc add` run gives the keys of `doc add` (`items` in place of `documents`) plus the same two. `status`, `cause`, `next_action` and the exit codes are as for `read`, `extract` and `doc add`.

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
