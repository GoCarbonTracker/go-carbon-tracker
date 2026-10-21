# Workspace migrations

A workspace records its schema version in the database. When gct opens a workspace, it applies every
migration newer than that version, in order, each in its own transaction, before the command runs. The
upgrade is recorded as a run with the command `workspace upgrade` and one note per migration
("applied migration N"), so `gct run list` shows when it happened and which gct did it. Opening an
up-to-date workspace applies nothing and records nothing.

A workspace made by a newer gct than the one installed is refused (exit code 4) and nothing is written.
Install the newer gct to open it.

No migration edits or removes existing rows. Each one only adds tables and the triggers that keep them
append-only.

| Version | Story | Adds |
|---|---|---|
| 1 | M1-1.1 | `schema_version`, `workspace`, `company`, `document`, `document_state` |
| 2 | M1-1.2 | `published_version`, `published_pointer`, `published_purge` (published data versions) |
| 3 | M1-1.3 | `run`, `run_event` (the run log) |
| 4 | M1-2.1 | `attempt` (stage attempts and the result cache) |
| 5 | M1-2.3 | `artifact`, `page` (page readings and the files that hold them) |
| 6 | M1-2.4 | `approval` (spend cap, run allowances and data-transfer approvals) |
| 7 | M1-3.1 | `claim`, `claim_version`, `evidence_ref` (extracted figures, their versions and source locations) |
