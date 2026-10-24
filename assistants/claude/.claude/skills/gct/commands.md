# gct command reference

Generated from the command parser and `docs/cli-json.md` by `python tests/test_assistant_claude.py --write`. Do not edit
it by hand: a test fails when this file and the parser disagree.

Run a line below as `gct PATH ... --json`. A line gives the path, the positional names, `required:` options, other
`options:` and the `top:` keys the JSON object holds. `--json` and `--workspace PATH` are left out of every line; a
command that does not take one says `no --json` or `no --workspace`. `gct --version` prints `gct VERSION` as text and
exits 0.

- workspace init PATH | top: path, status | no --workspace
- workspace status | top: companies, documents, gct_version, latest_run_outcome, published_version, runs, schema_version, status
- company add NAME | options: --sector-ref SECTOR_REF, --sector-version SECTOR_VERSION | top: created_at, id, name, sector_ref, sector_version, status
- company list | top: companies, status
- doc add SOURCE... | required: --company COMPANY | options: --kind {report,evidence}, --privacy {private,shareable}, --availability {public,internal,unknown}, --name NAME, --source SOURCE, --plan | top: items, label, status
- doc list | options: --company COMPANY, --active | top: documents, hidden_by_archive, hidden_deleted, status
- doc show ID | top: deletion, document, state_change, status
- doc label ID | required: --as KEY, --capacity CAPACITY, --rationale RATIONALE | options: --privacy {private,shareable}, --availability {public,internal,unknown} | top: change, document, new, old, status
- doc pages ID | top: document, document_state, pages, status
- doc archive ID | options: --plan, --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: document, impact, state_change, status
- doc restore ID | required: --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: document, state_change, status
- doc delete ID | options: --confirm TOKEN, --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: cause, clears, document, files, impact, next_action, status, token, versions, warning
- read [ID...] | options: --company COMPANY | top: documents, status
- extract [ID...] | options: --company COMPANY | top: documents, status
- link [ID...] | options: --company COMPANY | top: documents, status
- infer | options: --doc ID, --company COMPANY | top: documents, status
- infer bases | options: --doc ID | top: bases, headings, status
- infer scope BASIS | required: --pages FIRST-LAST, --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: basis, status
- infer groups | options: --doc ID, --state {proposed,unresolved} | top: groups, status
- infer accept GROUP | required: --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: accepted, by, group, skipped, status
- infer resolve CLAIM | required: --field {period,boundary}, --as KEY, --capacity CAPACITY, --rationale RATIONALE | options: --kind {fiscal_year,calendar_year,half,quarter,as_at}, --start YYYY-MM-DD, --end YYYY-MM-DD, --boundary {standalone,subsidiary_set,consolidated}, --detail TEXT | top: claim, effective, field, status
- infer reject [GROUP] | required: --as KEY, --capacity CAPACITY, --rationale RATIONALE | options: --claim CLAIM, --field {period,boundary} | top: by, group, rejected, skipped, status
- match | options: --doc ID, --company COMPANY | top: documents, status
- match metrics | top: excluded, metrics, metrics_version, prefixes, rules_version, status, units, units_version
- match review | options: --company COMPANY, --reason {boundary unknown,unit unknown,unit not convertible} | top: items, status
- match link CLAIM | required: --series SERIES, --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: by, claim, decision, match_reason, match_state, series, series_id, status, version
- match unlink CLAIM | required: --series SERIES, --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: by, claim, decision, match_reason, match_state, series, series_id, status, version
- match status | options: --company COMPANY | top: companies, status
- series list | options: --company COMPANY, --metric KEY | top: series, status
- series show SERIES | options: --all | top: series, status
- restate list | options: --company COMPANY, --state {same,restatement,unresolved,not-compared} | top: hidden, pairs, status
- restate show CLAIM | top: claim, pairs, status, versions
- restate record | required: --original CLAIM, --restated CLAIM, --page N, --quote TEXT, --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: pair, restatement, status
- restate withdraw | required: --original CLAIM, --restated CLAIM, --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: pair, restatement, status
- review company CLAIM | required: --version V, --outcome accepted|rejected|disputed, --scope TEXT, --conclusion TEXT, --as KEY, --capacity CAPACITY | options: --evidence-doc ID, --evidence-page N, --evidence-note TEXT, --date YYYY-MM-DD | top: claim, disagreement, entry, status
- review auditor CLAIM | required: --version V, --outcome accepted|rejected|disputed, --scope TEXT, --conclusion TEXT, --as KEY, --capacity CAPACITY | options: --evidence-doc ID, --evidence-page N, --evidence-note TEXT, --date YYYY-MM-DD | top: claim, disagreement, entry, status
- review list CLAIM | top: claim, status, versions
- review pending | options: --company COMPANY, --doc ID | top: kinds, status
- adjudicate list | options: --company COMPANY, --state {unreviewed,explained-difference,extraction-error,reviewer-confirmed-issue,evidence-not-found}, --claim CLAIM | top: candidates, earlier, hidden, status
- adjudicate record A B | required: --state STATE, --procedure TEXT, --as KEY, --capacity CAPACITY, --rationale RATIONALE | options: --counter-doc ID, --counter-page N, --counter-note TEXT, --follow-up TEXT, --closure-reason TEXT | top: adjudication, adjudication_state, next, status
- adjudicate status | options: --company COMPANY | top: companies, status
- flag raise CLAIM | required: --version V, --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: flag, status
- flag withdraw CLAIM | required: --version V, --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: flag, status
- flag list | options: --company COMPANY, --claim CLAIM | top: flags, status
- highlight add CLAIM | required: --version V, --note TEXT, --as KEY, --capacity CAPACITY | top: claim, entry, status
- highlight list CLAIM | top: claim, status, versions
- claims list | required: --doc ID | options: --state {current,not-found,not-extracted} | top: claims, document, status
- claims history CLAIM | top: claim, status, versions
- sheet show DOC | top: document, sheets, status
- sheet map DOC | required: --sheet NAME, --metric COL, --as KEY, --capacity CAPACITY, --rationale RATIONALE | options: --value COL, --unit COL, --period COL, --boundary COL, --company COL, --note COL, --year-end MM-DD, --boundary-is {standalone,subsidiary_set,consolidated}, --boundary-detail TEXT | top: mapping, status
- correct CLAIM | required: --as KEY, --capacity CAPACITY, --rationale RATIONALE | options: --value TEXT, --unit TEXT, --metric TEXT, --period-label TEXT | top: claim, correction, status, version
- contributor add KEY | required: --name NAME | options: --organisation ORGANISATION | top: contributor, status
- contributor edit KEY | options: --name NAME, --organisation ORGANISATION | top: contributor, status
- contributor list | top: contributors, status
- expect add | required: --company COMPANY, --metric TEXT | options: --period LABEL, --doc ID | top: expectation, status
- expect list | options: --company COMPANY | top: expectations, status
- pages accept | required: --doc ID, --pages SPEC, --type {text,tables,figures}, --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: accepted, document, pages, status, type
- gap confirm ITEM | required: --as KEY, --capacity CAPACITY, --rationale RATIONALE | top: expectation, status
- publish build | top: built_at, companies, documents, history_mark, status, version
- publish restore | top: built_at, companies, documents, history_mark, status, version
- publish status | top: built_at, companies, current_version, documents, files, history_mark, previous_version, stale, status
- package preview | options: --complete, --include CLASS,CLASS | top: data_version, filter, history_mark, include, included, labels_mark, lines, mode, not_in_packages, status, token, withheld
- package create | required: --confirm TOKEN | options: --complete, --include CLASS,CLASS, --include-private | top: data_version, folder, include, lines, mode, run_id, source_data_version, status, token
- view records | options: --filter JSON|@FILE, --shape {table,graph,series,values}, --offset N, --limit N, --sort KEY[:desc], --claims ID,ID | top: data_version, deleted_in_filter, empty, excluded, filter, hidden_by_archive, limit, matched, not_found, offset, rows, status, total
- view save NAME | required: --filter JSON|@FILE, --as KEY | options: --section tables|graphs | top: data_version, status, view
- view list | top: data_version, hidden, status, views
- view open NAME | options: --shape {table,graph,series}, --offset N, --limit N, --sort KEY[:desc] | top: data_version, deleted_in_filter, empty, excluded, filter, hidden_by_archive, limit, matched, not_found, offset, rows, status, total, view
- view remove NAME | required: --as KEY | top: data_version, removed, status
- view questions | top: data_version, questions, status
- report preview | options: --filter JSON|@FILE, --complete, --include CLASSES, --data-version V | top: data_version, include, mode, preview, status
- report evidence-index | required: --format F[,F...] | options: --filter JSON|@FILE, --complete, --include CLASSES, --data-version V | top: data_version, files, folder, include, mode, outputs, preview, run_id, stale, status
- report restatement-log | required: --format F[,F...] | options: --filter JSON|@FILE, --complete, --include CLASSES, --data-version V | top: data_version, files, folder, include, mode, outputs, preview, run_id, stale, status
- report gap-report | required: --format F[,F...] | options: --filter JSON|@FILE, --complete, --include CLASSES, --data-version V | top: data_version, files, folder, include, mode, outputs, preview, run_id, stale, status
- report all | required: --format F[,F...] | options: --filter JSON|@FILE, --complete, --include CLASSES, --data-version V | top: data_version, files, folder, include, mode, outputs, preview, run_id, stale, status
- run list | top: runs, status
- run show ID | top: command, cost_confirmed, cost_estimated, events, failures, finished_at, gct_version, id, methods, outcome, outputs, retries, started_at, status
- run resume ID | top: documents, of_run, run_id, status
- run retry ID | top: documents, of_run, run_id, status
- approve spend AMOUNT | top: cap, spent, status
- approve transfer NAME | options: --revoke | top: granted, provider, status
- approve list | top: adapters, cap, spent, status
- model list | top: adapters, path, reading_steps, status | no --workspace
- measure g2 | required: --gold FOLDER | options: --seed SEED, --against REPORT | top: adjudication, aggregate, delta, document_types, documents, gct_commit, gold, headline, published, published_version, report_path, rows, run_id, runs, scorer_version, status, target, types, workspace
- troubleshoot export | top: files, folder, status
- serve | options: --port PORT, --no-open | top: port, status, url
