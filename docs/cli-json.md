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

## claims list
- top: status, document, claims
- claims: page_number, locator, value_text, value, unit_text, metric_text, period_label, reporting_boundary, method, boxes, source_match, source_match_reason

One record per claim, from its newest version. `document` is the id. `value_text`, `unit_text`, `metric_text` and `period_label` are as printed; `metric_text` is null for a table row with no label; `value` is null unless the figure is in plain Western form. `reporting_boundary` is `unknown` until a later step sets it. `method` is `rung1-rules` for the fixed-rule baseline. `boxes` is a list of `[x0, top, x1, bottom]` in PDF points from the top-left of the page, or null when there is no box. `source_match` is the newest status of the location: `matched` (the words in the box reproduce the figure), `cited` (page known, but no box or the box no longer reproduces it) or `unresolved` (the page has no reading); null when it has not been checked yet (run `gct link`). `source_match_reason` is null for `matched`, else `no box`, `box does not reproduce the figure`, `page not read: gct read` or `spreadsheet check not built`.

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

`metric_text` is the wording as typed, whitespace collapsed; `period_label` as typed or null. `documents` lists the ids of the fixed document set. `found` is true when a newest claim version on the set has a metric wording containing `metric_text` (case-insensitive) and, when given, the same period label as printed; `claims` then lists them (`id`, `document_id`, `page_number`, `metric_text`, `value_text`, `unit_text`, `period_label`) and `state` is null. Otherwise `state` is `processing incomplete or failed`, `not found in successfully processed material` or `confirmed disclosure gap`. `reasons` lists what keeps pages from being ready, as `{type, reason, count}`: `type` is `text`, `tables` or `figures` with `count` pages and `reason` `not read`, `read failed`, a quality flag, `charts not read` or `accepted on an earlier reading`; or `text` with `reason` `wording printed but no figure extracted` (no claim on those pages carries the wording) or `wording printed; figures found only for other or missing period labels` (claims there carry the wording but not the expected period label), `count` pages and `pages` listing them as `"document:page"`; either keeps the item out of state 2 (exact wording only, ignoring case and extra spaces; the period is never looked for on the page); or `document` with `count` documents and `reason` `not opened` or `not a PDF`; or `confirmation`, naming an earlier gap confirmation that `was made on older readings` or `no longer holds: processing incomplete`. `accepted` lists pages counted as ready by a reviewer's acceptance, as `{type, accepted, count}` with `accepted` `accepted by <name> (<capacity>)`; they are never counted as checked. `confirmation` is null or the newest gap confirmation: `id`, `contributor`, `organisation`, `capacity`, `rationale`, `created_at`, `current` (false once the readings it was made on are no longer the newest, the state is no longer `not found in successfully processed material`, or the item is found; a found item still shows its newest confirmation).

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

Resuming a `read` run gives the keys of `read` plus `run_id` (the new run, null when there was nothing to read) and `of_run` (the run resumed). Resuming an `extract` run gives the keys of `extract` plus the same two, and a `link` run the keys of `link`. Resuming a `doc add` run gives the keys of `doc add` (`items` in place of `documents`) plus the same two. `status`, `cause`, `next_action` and the exit codes are as for `read`, `extract` and `doc add`.

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

## serve
- top: status, url, port

## error
- top: status, cause, next_action
