# Deletion

Deleting a document removes its content from every place gct keeps it, including the published versions still on
disk, and cannot be undone. The reviews other people made on it stay on record and say that their evidence was
deleted. It is the one exception to the append-only history (FR32). Archive (`docs/archive.md`) is the reversible
step; delete only what must not stay in the workspace.

## Commands

- `gct doc delete ID` prints the plan and stores nothing (exit 4): what leaves the active outputs (the archive
  summary of `gct doc archive --plan`), how many rows per table have their content cleared, what is kept, the files,
  reading files and page images it removes or keeps, the published versions it purges, the export warning and the
  confirmation token (the first 12 characters of the file's SHA-256).
- `gct doc delete ID --confirm TOKEN --as KEY --capacity TEXT --rationale TEXT` deletes it. Only the token the plan
  prints is accepted, so a deletion always follows a look at its plan. Your capacity and rationale are kept with the
  deletion, so do not quote the document in them.
- `gct doc show ID` shows the deletion: who, when and why, the steps done, any step still pending, and the records
  made on the document itself (page acceptances, boundary page declarations, spreadsheet column mappings, earlier
  archive and restore records), each with the marker. `gct doc list` shows `deleted` with the date; `--active` hides
  deleted documents and counts them. `gct sheet show` and `gct sheet map` refuse a deleted spreadsheet.

A document can be deleted when it is `registered`, `restored` or `archived`. A deleted document is refused with the
message and the next step: deleting it again, restoring it, archiving it and every write on it (corrections, reviews,
page acceptances, restatement records, company confirmations and auditor reviews on its claims or citing it,
expectations).

## Order

1. **Database, one transaction** in `workspace.db`: the tombstone (a `deleted` row in `document_state`), the record of
   who deleted it (`document_state_change`), the deletion record (`document_deletion`, with the counts of the plan),
   then the clearing of every content column of the rows attached to the document. The append-only UPDATE triggers
   of the cleared tables are dropped and created again from their stored SQL inside that same transaction, so a
   failure leaves every trigger and every row as they were. No row is deleted from `workspace.db`, so every foreign
   key and every retained review still resolves.
2. **Files**: the original in `files/`, unless a document not deleted (of any company) has the same file. That
   document keeps the file, and if it was read, its own readings, claims and statements hold the same text: they are
   its records, not the deleted document's, and stay.
3. **Artifacts**: each reading file in `artifacts/` that no document not deleted also uses (readings are stored by
   content, so two documents can share one).
4. **Renders**: the page images in `artifacts/pages/<sha256>/`, by the same rule as the original.
5. **Published**: every `published/vN.db` still on disk loses the rows of the document, of its claims and claim
   versions, and every row that names one of them (comparison pairs and restatement rows included), the series only
   it made, and the contributor text the database step cleared (gap confirmations, and the acceptance lines of
   expectations that declared it, which clears another document's lines of those expectations too). Each file is
   then vacuumed and gets a `published_purge` row with reason `deletion`. A file built by an older projection schema
   is purged in the tables and columns it has.
6. **Vacuum**: `PRAGMA wal_checkpoint(TRUNCATE)` and `VACUUM` of `workspace.db`, so freed pages do not keep the text.

Each step after the first is recorded in `document_deletion_step` when it finishes. If one fails (a file held open
by another program, a disk error), the steps before it stand, the others still run, and the command names the
pending steps (exit 4). `gct doc show ID` lists them, and `gct publish restore` still refuses a version that holds
the document. Run `gct doc delete ID --confirm TOKEN` again (no contributor options needed) to finish them.

## What is cleared and what is kept

A column is **kept** when it is an id, a foreign key, a state, a reason code, a date, a config or rules version, a
contributor identity field (key, version, name, organisation), or the document's `sha256`, `kind`, `file_type`,
`privacy`, `size_bytes` or `version`. Every other column holds something read from the document, inferred from it or
typed about it, and is **cleared** on the rows attached to the deleted document: NULL, or the value in the table
below where the column cannot be NULL, sits in a UNIQUE key or a CHECK. `cleared with document N` is written in
place of contributor text (`capacity`, `rationale`) on records attached to the document, since such text often
quotes the page. The classification lives in `gct/stages/deletion.py` (`KEPT`, `CLEAR`, `PROJECTION`);
`tests/test_deletion.py` fails when any table or column is in neither, so a later migration classifies its own.

| Table | Rows attached to document N | Cleared (value written) | Kept, not an id, key, state, reason or date |
|---|---|---|---|
| `schema_version`, `workspace`, `company`, `published_version`, `published_pointer`, `published_purge`, `run`, `approval`, `contributor_version`, `claim_seen`, `expected_item_document`, `document_deletion`, `document_deletion_step` | none | nothing | everything (`run.command` is the command name; `document_deletion.plan` holds counts only) |
| `source_match` | checks of its spreadsheet references whose reason quotes the cell (`cell D7 under mapping #2 reads ...`) | `reason` (`cleared with document N`) | `status`; every other reason, a reason code |
| `sheet_mapping` | its column mappings | `sheet`, `value_col` (`''`, NOT NULL); `metric_col`, `unit_col`, `period_col`, `boundary_col`, `company_col`, `note_col`, `year_end`, `boundary_is`, `boundary_detail` (NULL); `capacity`, `rationale` (`cleared with document N`) | `position` |
| `claim_note` | the notes of its claim versions | `text` (`''`) | |
| `adjudication` | adjudications naming one of its versions, either side, or citing it as counter-evidence | `rationale`, `procedure`, `capacity` (`cleared with document N`); `counter_note`, `follow_up`, `closure_reason` (`cleared with document N`; NULL stays NULL) | `state`, `counter_page` |
| `reviewer_flag` | reviewer flags on its versions | `capacity`, `rationale` (`cleared with document N`) | `decision` |
| `document` | the document | `logical_name` (`cleared with document N`, unique per document), `source` (NULL) | `sha256`, `kind`, `file_type`, `privacy`, `size_bytes`, `version` |
| `document_state` | its states | `note` (NULL) | |
| `document_state_change` | its archive and restore records before the deletion | `capacity`, `rationale` (`cleared with document N`) | the deletion's own record, unchanged |
| `claim` | none | nothing | `page_number`, `locator` (a position such as `t0r3c2`), `sector_ref`, `sector_version` |
| `claim_version` | every version of its claims | `metric_text`, `value`, `unit_text`, `period_label`, `period_kind`, `period_start`, `period_end`, `metric_key`, `boundary_detail`, `boundary_label` (NULL); `value_text` (`''`); `reporting_boundary` (`unknown`, its CHECK) | `method`, `config_version` |
| `evidence_ref` | its locations and those of its versions | `boxes`, `cell` (NULL); `sheet` (`''` on a spreadsheet location, its CHECK) | `page_number` |
| `artifact` | none | nothing (the reading files go in the artifacts step) | `sha256`, `path` (hashes), `kind`, `size_bytes` |
| `page` | none | nothing | `page_number`, `rung`, `method`, `width`, `height`, `words`, `tables` (measurements and counts), `flags` (codes) |
| `basis` | its statements | `wording` (`cleared with document N, basis B`, unique per row), `fy_end`, `period_start`, `period_end`, `boundary`, `boundary_detail` (NULL) | `page_number`, `kind` |
| `basis_scope` | declarations on its statements | `capacity`, `rationale` (`cleared with document N`) | `first_page`, `last_page` |
| `inference` | inferences on its versions | `period_kind`, `period_start`, `period_end`, `boundary`, `boundary_detail` (NULL); `group_key` (`''`) | `field`, `reason` (a reason code or page and basis numbers) |
| `inference_review` | period and boundary reviews of its versions | `period_kind`, `period_start`, `period_end`, `boundary`, `boundary_detail` (NULL); `capacity`, `rationale` (`cleared with document N`) | `field`, `decision` |
| `correction` | corrections of its versions | `capacity`, `rationale` (`cleared with document N`) | `fields` (the names of the fields changed) |
| `metric_assignment` | assignments of its versions | `metric_key`, `rule`, `unit_key`, `unit_factor` (NULL) | `unit_source` |
| `match_review` | match reviews of its versions | `series_key` (`''`: it holds the printed label of an unmapped series); `capacity`, `rationale` (`cleared with document N`) | `reason`, `decision` |
| `restatement` | rows naming one of its versions, either side, or citing it | `series_key`, `evidence_quote` (`''`; NULL stays NULL on a withdrawn row); `capacity`, `rationale` (`cleared with document N`) | `decision`, `evidence_page` |
| `review_company`, `review_auditor` | company confirmations and auditor reviews on one of its versions, or citing it as evidence (`evidence_document_id`) | `capacity`, `scope`, `conclusion` (`cleared with document N`); `evidence_note` (`cleared with document N`; NULL stays NULL) | `reviewed_on`, `outcome`, `evidence_page` |
| `expected_item` | none | nothing (the expectation is the user's wording) | `metric_text`, `period_label` |
| `page_acceptance` | acceptances of its pages | `capacity`, `rationale` (`cleared with document N`) | `page_number`, `content_type` |
| `gap_confirmation` | confirmations whose checked set names it | `capacity`, `rationale` (`cleared with document N`) | `documents_checked` (document ids, file hashes, reading ids) |
| `run_event` | the register and fetch lines of its own add runs that name one of its addresses, the register and fetch failure lines of its addresses in any add run for its company, the selection notes of its own add runs, its `sheet` stage lines, and free-text messages that hold its logical name or source (one row per kind below) | `item`, `message` of those register and fetch lines; `message` of the rest (`cleared with document N`) | `kind`, `stage`, `method`, `outcome`, costs; every other `item` (ids and paths that retry reads back); another document's register line and another run's selection note |
| `attempt` | fetch attempts whose `item` or `output` holds its logical name or source; its `sheet` attempts (item `N:sheet position`); attempts of any stage whose `error` holds its name or source | `item`, `output` of those fetch attempts; the `sheet` name inside a sheet attempt's JSON output; `error` (`cleared with document N`) | `stage`, `input_version`, `config_version`, `method`, `rung`, `outcome`, costs; the `item` and `output` of every other stage (page ids, document ids and counts) and the rest of a sheet output (counts and claim ids) |

`gct doc add` records, in the run it made, the file paths or folders given, the company, `--name` and `--source`
(the selection note used by `gct run resume` and `gct run retry`), a fetch line per address, and one register line per
file with its resolved path or address and the id of the document it registered (`document N`), or a failure line
with the cause.

The document's **addresses** are the items of its register lines, every folder given in the sources of those lines'
runs that holds one of those paths, and its source. Its register lines are the ones naming it (`document N`); on a
workspace written before the id was recorded, a register line with no id whose path still holds the same bytes, in a
run whose selection names the document's company. Its **own add runs** are the runs of those register lines, and
every other doc add run whose selection names the document's company and either gives only its addresses as sources
or gives its logical name as `--name` or its source as `--source`, each compared as a whole value, never as a
substring, unless a register line of that run names another document. So a failed add of the same file, folder or
address before the successful one is its own run, and so is an old add run of a file moved since, when it was given
the document's name. A run that gave its file together with other files is not, unless it gave its name or source.

| Run line | Tied to document N by | Cleared |
|---|---|---|
| register line (item) | `document N`, or (an id-less line) the path still holding its bytes in a run for its company; any other register line of its own add runs with an `item` equal to one of its addresses | `item` and `message` |
| register failure | any add run whose selection names its company, with an `item` equal to one of its addresses (a file, a folder) | `item` and `message` |
| fetch line (item, retry, cost) | one of its own add runs, with an `item` equal to one of its addresses (the URL) | `item` and `message` |
| fetch failure | any add run whose selection names its company, with an `item` equal to one of its addresses | `item` and `message` |
| selection note | one of its own add runs | `message` |
| read failure | none (its `item` is a document id) | `message` only when the text rule below finds its name or source in it |
| `sheet` stage line | its `item` is `N` or `N:sheet position` | `message` (it holds the sheet name); `item` kept (ids) |
| any other free-text message | the text rule below | `message` |

Resume and retry of one of its own add runs then have nothing left to replay: the selection note is gone. In any add
run for its company, a cleared failure line carries the same marker as the document's cleared register line, so
`gct run retry` of that run does not register the file again: when the register line came later it finds no failed
item, and the other files' failed items are retried as before; when the register line came earlier, retry reports the
cleared item as a missing file and registers nothing. What may remain: the path or folder in the sources of
the selection note of an add run for its company that is not its own (it registered another document, or gave its
file together with other files and registered none of them), which stays so that run's other files can still be
resumed and retried, together with that run's fetch retry line for the document's URL; the folder in the failure
line of a refused folder add that is its own run only by name or source, when the file was later added on its own
rather than from that folder (the folder is then not one of its addresses); the path in an id-less register line of a document whose file was renamed, moved or removed
since (its run is found only by the name or source it was given, and an id-less line cannot be told apart from
another file's in the same run); and an old line whose run names no company (an id-less line of another company's
document with the same file stays its own). The one over-clear among the add runs: a failed add of another file, for
the same company, that gave the same `--name` or `--source` and registered nothing, counts as the document's own run.

Beyond those lines, run messages are matched on the text itself (the logical name and the source, as typed and as
written inside JSON). This clears by design more than the document's own lines: the free-text message of another
document's line (a failure cause, a note) that holds the same text is cleared too, never the reverse. Outside the
document's own add runs nothing else that runs read back changes: no other `item` (another company's fetch line of
the same address stays as it was), no register line naming another document and no selection note, so another
document's add path, resume and retry stay as they were. Attempts are not run text: the `item` and `output` of a read, extract,
infer, link or match attempt are the cache key and the result of another document's stage, so only fetch attempts
(whose item is the address and whose output names the downloaded file) are matched on them. `error` is text and is
matched in every stage. The `sheet` stage (story 4.3) keys its attempts and lines on ids, so the deleted document's
are found by that key, never by text: another spreadsheet's sheet attempts stay as they were.

In a published version (`projection_schema` 13) a row whose `document_id`, `evidence_document_id`,
`counter_document_id`, `claim_id`, `low_claim_id`, `high_claim_id`, `claim_a`, `claim_b`, `id` of `claim` or
`document`, `claim_version_id`, `original_version_id`, `restated_version_id`, `low_version_id`, `high_version_id`,
`version_a` or `version_b` names the document, one of its claims or one of its claim versions is removed, in
`document`, `claim` (with its `note`, the spreadsheet row's note cell), `series`, `series_point`, `comparison`,
`restatement`, `evidence_ref` (with its `sheet` and `cell`), `expected_item_document`, `page_acceptance`,
`hidden_by_archive`, `sheet_mapping` (every column mapping of a spreadsheet), `review_company` and
`review_auditor` (an entry on one of its claims or citing it as evidence; the next build projects a surviving claim's
entry again with its text cleared and `evidence_state` `deleted`), `adjudication` (also a row citing it
as counter-evidence; a later build projects that row again, its text cleared) and `reviewer_flag`. `meta`, `company`,
`expected_item`, `gap_confirmation` and `deleted_document` keep their rows (`expected_item.accepted` and the gap
confirmation's `capacity` and `rationale` are rewritten as above, and `meta.hidden_by_archive` is counted again from
the `hidden_by_archive` rows left, so an archived document deleted since leaves the counts too).

## Markers

Every command that shows a record whose claim version, page or statement belongs to a deleted document adds
`evidence deleted (document N, YYYY-MM-DD)` after the record (with the record's own date) in text, and
`evidence_deleted: {"document": N, "at": ...}` in JSON: `gct claims history` (claim level, every review and
correction), `gct restate show` (every version of a deleted document's claim, from either side of a restatement
record, so a record whose other claim survives shows it from the survivor's side; a restatement record carries the
marker of either version's document or its evidence document, also when listed under the survivor's version),
`gct expect list` (a gap
confirmation that looked in a deleted document), `gct adjudicate list` (an adjudication citing a deleted counter
document, whose two claims survive), `gct review list` and `gct claims history` (a company confirmation or auditor
review carries the marker of its claim's document or its evidence document, whichever was deleted; `docs/reviews.md`)
and `gct doc show` (the records on the document itself). Each record
keeps its contributor, decision, states and dates; its capacity and rationale read `cleared with document N`.
`gct match review` lists only the review queue of active documents, so it never shows a deleted document's item; its
match reviews are listed by `gct restate show CLAIM`.

## What else changes

- A deleted document is not active anywhere: its figures leave the series, same-period sets and pairs (worked out
  again on read), the review queue and the expectations; a gap confirmation that looked in it reads
  `was made on older readings`. An expectation whose declared documents were all deleted says so and asks for a new
  expectation instead of a restore.
- Adding the same file again registers a new document id with new readings; nothing of the deleted one comes back.
- `gct publish build` (schema 10) adds the table `deleted_document` (`document_id`, `deleted_at`: ids and dates
  only) and the `meta` key `deleted_documents` (the count). `gct publish restore` to an older version shows that
  version without the deleted document; a version whose purge is still pending is refused. `gct publish status`,
  `restore` and `build` count the companies and documents in the version file, so a purged version reports what it
  holds now.
- Retention keeps removing older version files after a deletion: only `retention` purge rows count as gone.

## What gct cannot recall

Copies already exported or shared, including files in `exports/`, cannot be recalled by GCT. Neither can copies sent
elsewhere, backups, file-system snapshots or anything else outside the workspace folder, and deletion does not wipe
free disk blocks. `exports/` is never touched.
