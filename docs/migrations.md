# Workspace migrations

A workspace records its schema version in the database. When gct opens a workspace, it applies every
migration newer than that version, in order, each in its own transaction, before the command runs. The
upgrade is recorded as a run with the command `workspace upgrade` and one note per migration
("applied migration N"), so `gct run list` shows when it happened and which gct did it. Opening an
up-to-date workspace applies nothing and records nothing.

A workspace made by a newer gct than the one installed is refused (exit code 4) and nothing is written.
Install the newer gct to open it.

No migration edits or removes existing rows. Each one only adds tables and the triggers that keep them
append-only, or (11) a column that is empty on existing rows.

| Version | Story | Adds |
|---|---|---|
| 1 | M1-1.1 | `schema_version`, `workspace`, `company`, `document`, `document_state` |
| 2 | M1-1.2 | `published_version`, `published_pointer`, `published_purge` (published data versions) |
| 3 | M1-1.3 | `run`, `run_event` (the run log) |
| 4 | M1-2.1 | `attempt` (stage attempts and the result cache) |
| 5 | M1-2.3 | `artifact`, `page` (page readings and the files that hold them) |
| 6 | M1-2.4 | `approval` (spend cap, run allowances and data-transfer approvals) |
| 7 | M1-3.1 | `claim`, `claim_version`, `evidence_ref` (extracted figures, their versions and source locations) |
| 8 | M1-3.3 | `source_match` (whether each source location reproduces its figure; newest row per location is current) |
| 9 | M1-3.3 | `contributor_version`, `expected_item`, `expected_item_document`, `page_acceptance`, `gap_confirmation` (contributors, expected figures, review records for missing evidence) |
| 10 | M1-3.2 | `basis`, `basis_scope`, `inference`, `inference_review` (period and boundary statements found, the page ranges declared for them, inferences per claim version and field, and the reviews of them; newest row wins) |
| 11 | M1-3.5 | `claim_version.boundary_label` (a boundary header printed above a table column, as printed; empty on earlier versions), `correction` (a contributor's correction: the new version, the version it corrects, the fields changed), `claim_seen` (which extraction of which reading found which version). Reading config 4 (text direction, column order and word spaces), extract rules 5, link config 2 and infer rules 2 come with this story; earlier readings are kept and the next `gct read` reads each page again |
| 12 | M1-4.1 | `metric_assignment` (the metric key, rule, unit key and factor assigned to each claim version by `gct match`; newest row per version is current, a re-run adds a row only where the result changed), `match_review` (a contributor's `linked` or `not_linked` decision on one claim version and one candidate series; newest row per version and series wins). Match rules 1, metric list 1 and unit table 1 come with this story; series are computed on read, never stored |
| 13 | M1-4.2 | `restatement` (a contributor's `recorded` or `withdrawn` decision that one claim version restates another, with the series key at record time, the document, page and quoted line that establish it (empty on a `withdrawn` row), and the contributor, capacity and rationale; newest row per original and restated version is current). Match rules 2 (numbers read from Indian grouping and figures with footnote marks) and metric list 2 (the version number for the 4.1 combined-scope list, unchanged) come with this story, so the next `gct match` adds one assignment row per newest claim version; pair states are computed on read, never stored |
