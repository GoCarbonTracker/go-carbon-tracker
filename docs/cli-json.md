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

`status` is `ok` when no document and no page failed (flags are not failures; exit 0), else `partial` (exit 4), which adds `cause` and `next_action` at the top. `action` is `read`, `skipped` (not a PDF) or `failed` (the PDF could not be opened). `read` counts pages read by this command, `cached` pages already read under the same document bytes and reader settings, `failed` pages that raised. `flags` maps each quality code to its number of pages. `cause` is set for `skipped`; `cause` and `next_action` for `failed` and for a `read` document with failed pages; null otherwise. Nothing to read gives `{"status": "ok", "documents": []}`.

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

## serve
- top: status, url, port

## error
- top: status, cause, next_action
