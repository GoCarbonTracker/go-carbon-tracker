# CLI JSON output

Every command prints one JSON object on stdout when `--json` is given. `status` is one of
`ok`, `duplicate`, `exists`, `already_initialised`, `error`. The lines below are checked by
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
- top: status, document
- document: id, company, logical_name, version, sha256, kind, file_type, privacy, size_bytes, source, created_at, state

## doc list
- top: status, documents
- documents: id, company, logical_name, version, sha256, kind, file_type, privacy, size_bytes, source, created_at, state

## doc show
- top: status, document
- document: id, company, logical_name, version, sha256, kind, file_type, privacy, size_bytes, source, created_at, state

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

## error
- top: status, cause, next_action
