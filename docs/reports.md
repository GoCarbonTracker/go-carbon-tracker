# Report exports

`gct report NAME --format F` writes the report data of the current published version into a new folder under the
workspace's `exports/`. Which rows an export holds, and what a sanitised export leaves out, is the same as for
`gct report preview`; `docs/privacy.md` explains both. This file describes the command, the folder, the JSON file
and its schema.

## The command

`gct report NAME --format F[,F...] [--filter JSON|@FILE] [--complete] [--include identity,contributor_text,flags]
[--data-version V] [--json]`

- `NAME` is `evidence-index`, `restatement-log`, `gap-report` or `all` (the three). It names the reports a format
  writes. A JSON export holds the whole dataset whichever you name, because the three reports share the
  `documents`, `evidence` and `related_claims` lists.
- `--format` is a comma list of format names. Today there is one, `json`. A repeated name counts once. An unknown
  name is refused before anything is read: "Unknown format X. Available: json."
- `--filter`, `--complete`, `--include` and `--data-version` are those of `gct report preview`. The export is
  sanitised unless you add `--complete`. `--include` keeps the named classes in a sanitised export.
- `--json` prints the result as JSON (`docs/cli-json.md`, section `report evidence-index`).

The command takes the workspace lock, builds the dataset once from the current published version, writes the folder
and prints the folder and its files, the dataset's notices, each format's notes and then the preview. The preview
and the notes are printed on your terminal only; no file holds them. A complete export also prints "This export
includes private content. Check it before you share it."

When the workspace has changed since the current version was built, the command still exports that version and
prints "The workspace has changed since data version V was built; this export shows version V. To include the
changes: gct publish build, then export again."

## Refusals

A refused export writes nothing: no folder, no run, and the workspace is unchanged. It is refused for an unknown
format, a filter, filter file or inclusion class that `gct report preview` refuses, another command holding the
workspace, no published version, a `--data-version` that is not the current one, a version file that is missing or
still holds a deleted document, a deletion that did not finish, and a version file built before projection schema
16 (build a fresh one with `gct publish build`).

Two refusals come after the run has opened: an export folder of the same name already exists (nothing is
overwritten; run the command again), or a format refuses its data. Both leave no folder, and the run is recorded
as failed with the cause.

## The export folder

`exports/<NAME>-v<N>-<stamp>-<mode>/`, where `N` is the data version, `stamp` the UTC time to the microsecond (for
example `20261023T091258123456Z`) and `mode` is `sanitised` or `complete`, so a complete export cannot be mistaken
for a sanitised one by its name. A JSON export holds two files:

- `dataset.json`: the dataset, UTF-8 without a byte order mark, every character as itself, indented by one space,
  keys in the order below, and a final newline. Two exports of one version differ only in `built_at`.
- `dataset-1.schema.json`: the JSON Schema the file follows, so a recipient can check it without GCT.

The folder is written under the temporary name `exports/.incoming-<NAME>-v<N>-<stamp>-<mode>/` and renamed once
its files are checked. An export is never overwritten. If `exports/` was removed, the command makes it again. A
crash can leave an `.incoming-*` folder; nothing reads it and you may remove it.

The run log keeps one `report` run per export: a line with the report name and formats (for example `all json`) and
one line per file with its path inside the workspace. It holds no filter, no folder outside the workspace and no
message. `gct run resume` and `gct run retry` refuse a report run; run the export again instead.

## Modes and inclusion classes

`mode` is `sanitised` (the default) or `complete`. A sanitised export holds only rows built from shareable
documents, leaves out reviewer flags, names no archived or deleted document, gives each contributor a pseudonym
"Contributor N" and withholds organisation, capacity and contributor-typed text. `--include identity`,
`contributor_text` and `flags` keep those classes. A complete export holds every row of the selection with its
`label`. The rules are in `docs/privacy.md`.

A withheld field keeps its key with the value `null`, and the row's `withheld` list names it, also when nothing was
stored there. A dotted name in `withheld`, for example `correction.rationale`, names a key inside an object.

## The data version

`data_version` names the published version the rows come from:

- `version`: the version number, the current one at export time; the folder name carries it too.
- `built_at`: when that version was built.
- `sha256`: the SHA-256 of the version file as read. A permanent deletion rewrites a version file in place under the
  same number, so two exports of "version 3" made before and after a deletion have different `sha256` values.
- `projection_schema`: the projection schema of the version file; reports read 16 or later.
- `history_mark` and `labels_mark`: complete mode only. `history_mark` is the version's workspace-wide record counts,
  dot-separated, and `labels_mark` the newest label change id. A sanitised file leaves both out, since the counts
  would tell how many private records exist.

Every row and sub-table row carries `data_version` too, as the plain number, always equal to `data_version.version`.

## The JSON file

The top-level keys, in file order:

| Key | Meaning |
|---|---|
| `dataset_schema` | The dataset schema number the file follows, `1`. |
| `gct_version` | The GCT version that built the dataset. |
| `built_at` | When the dataset was built (UTC, for example `2026-10-23T09:12:58+00:00`). |
| `mode` | `sanitised` or `complete`. |
| `include` | The inclusion classes a sanitised export kept, sorted; empty in complete mode. |
| `data_version` | The published version, as above. |
| `filter` | The filter the rows were selected with (below). |
| `words` | GCT's fixed wording (below). |
| `columns` | The printed columns of every report, sub-table and gap report section: a list of `key`, `heading` and, on the label column, `complete_only`. |
| `documents` | Every document the rows name, plus the gap report's documents that ship. |
| `evidence_index` | One row per selected claim that ships. |
| `related_claims` | Claims outside the selection that a comparison pair names, in the evidence index's shape. |
| `restatement_log` | One row per comparison pair with a selected side. |
| `unpaired_restatements` | The sub-table of restatement records whose two claims form no pair in this version. |
| `gap_report` | The gap report: `candidates`, `expectations`, `documents_checked`, `extraction_limits`, `archived` and `deleted`. |
| `evidence` | One entry per evidence location of a shipped row. |
| `notices` | The sentences every rendering prints, in order, for example "Private content is excluded from this output." |

Every key is always present. A file with no matching rows still has every key, with empty lists.

### Keys on every row

Every row of a report, a gap report section and a sub-table has:

- `id`: the record, claim, document or item id the row stands for, or its position in its list where it has none.
- `data_version`: the version number.
- `label`: `private` when any document the row names is private, else `shareable`. A sanitised file holds
  `shareable` rows only.
- `documents`: the ids of every document the row names.
- `evidence`: ids into the top-level `evidence` list; empty when the row has no evidence location.
- `withheld`: the keys withheld in this mode; empty in complete mode.

### Evidence index and related claims

`evidence_index` and `related_claims` rows:

- `claim_id`, `version_id`: the claim and its current version.
- `company`, `document_id`, `document_name`, `document_version`: where the claim comes from.
- `page` for a PDF claim; `sheet` and `cell` (for example `C2`) for a spreadsheet claim; the others `null`.
- `metric_text`, `value_text`, `unit_text`, `period_label`: the claim as printed in the document.
- `value`: the number read from `value_text`, `null` when it has no unambiguous, finite value.
- `period_start`, `period_end` and `period_state`: the effective period and how it was settled.
- `boundary`, `boundary_detail` and `boundary_state`: the effective reporting boundary and how it was settled.
- `claim_state`, `match_state` and `match_reason`: the claim's state and match state in GCT's printed words, and
  why.
- `evidence_text`: whether the claim's own evidence was matched, cited or unresolved.
- `review_text`: the review summary, computed from the records in this file.
- `needs_renewed_review`: one sentence per record on an earlier version that asks for a renewed review.
- `correction`: the correction that made the current version, or `null` for an extracted one: its `id`,
  `corrects_version`, the corrected `fields`, the `replaced` values (`value_text`, `unit_text`, `metric_text`,
  `period_label`), `created_at`, `contributor`, `organisation`, `capacity` and `rationale`.
- `records` and `disagreements`: two sub-tables (below).

### Sub-tables

A sub-table is an object with `id`, `title` (from `words.fixed.titles`), `rows`, `parent_key` (the row key that
holds the parent row's id; `null` for `unpaired_restatements`) and `columns`.

`records` rows are company confirmations, auditor reviews, reviewer flags and highlights on any version of the
claim:

- `claim_id`: the parent claim; `kind`: the record kind in GCT's words; `claim_version_id`: the version it is on.
- `binds`: true when the record is on the current version, so it counts now; `earlier`: `words.earlier_version`
  when it does not bind, else `null`; `latest`: true for the contributor's latest position on that version.
- `outcome`, `reviewed_on`, `scope`, `conclusion`, `evidence_document_id`, `evidence_page` and `evidence_note`: a
  company confirmation's or auditor review's fields; `evidence_state` is the cited document's state when it is not
  active.
- `decision` and `rationale`: a reviewer flag's; `note`: a highlight's. A field that does not belong to the record's
  kind is `null`.
- `created_at`, `contributor`, `organisation` and `capacity`: when and by whom, with the capacity the contributor
  declared (self-declared, not checked by GCT).

`disagreements` rows: `claim_id`, `claim_version_id` and `text`, the disagreement sentence between the latest
company and auditor positions on that version.

`restatements` rows (on a pair) and `unpaired_restatements` rows: `pair_id` (the pair row; on an unpaired record
`original_claim_id` and `restated_claim_id` instead), `restatement_id`, `original_version_id`,
`restated_version_id`, `decision` (recorded or withdrawn), `evidence_document_id`, `evidence_page`,
`evidence_quote`, `binds`, `earlier`, `contributor`, `organisation`, `capacity`, `rationale` and `created_at`.

`adjudications` rows: `pair_id`, `adjudication_id`, `low_version_id` and `high_version_id` (the two claim versions),
`state_text` (the outcome in GCT's words), `binds`, `earlier`, `counter_document_id`, `counter_page`,
`counter_note`, `rationale`, `procedure`, `follow_up`, `closure_reason`, `contributor`, `organisation`, `capacity`
and `created_at`.

### Restatement log

`restatement_log` rows are comparison pairs; `gap_report.candidates` rows are the pairs still in unresolved
conflict, with the same keys:

- `series_id` (a text hash), `metric_key` (`null` for an unmapped series), `reporting_boundary` and `unit_family`.
- `period_start` and `period_end`: the compared period.
- `claim_a` and `claim_b`: the row ids, in `evidence_index` or `related_claims`, of the two claims;
  `outside_selection`: for each of the two, true when it is outside the selection and listed in `related_claims`.
- `state`: the comparison state in GCT's words; `reason`: why, where GCT gives one; `shown_state`: for an
  unresolved conflict, its adjudication state from the binding records in this file, else `null`.
- `restatements` and `adjudications`: two sub-tables.

### Gap report

`gap_report` has six sections, each a list of rows:

- `candidates`: as the restatement log.
- `expectations`: a figure a company is expected to report: `expected_item_id`, `company`, `metric_text`,
  `period_label`, `found` (a matching claim was found), `claims` (the matching current claims), `state` (the
  missing-evidence state, `null` when found), `confirmation` and three sub-tables. `confirmation` is the newest gap
  confirmation or `null`: `gap_confirmation_id`, `current` (true while it still holds), `created_at`,
  `contributor`, `organisation`, `capacity` and `rationale`. The sub-tables are `reasons` (`expected_item_id`,
  `type`, `reason`, `count`, `pages`: why the figure is missing, per content type), `accepted` (`expected_item_id`,
  `type`, `acceptance_id`, `count`: page acceptances counted for the item) and `declared` (`expected_item_id`,
  `document_id`, `state`: the documents declared for the item).
- `documents_checked`: one row per document of the gap report's scope: `document_id`; for a PDF `pages`, `read`,
  `read_failed`, `not_read`, `limit_text`, `limit_tables` and `limit_figures` (page counts); for a spreadsheet
  `sheets_mapped`; and `limit_note`, a fixed sentence where a limit applies.
- `extraction_limits`: `type`, `reason` and `count`, a kind of content GCT could not read and over how many
  documents.
- `archived`: archived documents of the selection (`document_id`, `name`, `archived_at`, `claims`); empty in
  sanitised mode.
- `deleted`: permanently deleted documents by `document_id` and `deleted_at` only; empty in sanitised mode.

### Documents

`documents` rows: `company`, `name`, `version`, `kind`, `file_type` (for example `pdf` or `csv`), `availability`
(`public`, `internal` or `unknown`) and `state` (whether the document is in this version). `company`, `version`,
`kind` and `file_type` are `null` for a document not in this version, and `name` for a deleted one.

### Evidence entries

Each `evidence` entry has `id`, `kind` (what it is evidence of: `claim`, `basis`, `restatement` or `review`),
`document_id`, `sha256` (of the document's original file) and either a page location or a cell location:

- a page: `page` and `boxes`, a list of `[x0, top, x1, bottom]` in PDF points from the page's top left corner, or
  `null` for the whole page; `sheet`, `cell`, `header`, `row` and `marked` are `null`;
- a cell: `sheet`, `cell`, `header` (the sheet's header row), `row` (the cell's row) and `marked` (the cell's index
  in `row`), the last three `null` when the sheet could not be read; `page` and `boxes` are `null`.

### Filter

`filter` echoes the filter, `{}` for the whole version. Its keys are those of `docs/views.md`, each present only
when given: `company`, `document`, `metric`, `text`, `period` (with `from`, `to` or both), `boundary`,
`claim_state`, `evidence`, `match`, `series`, `comparison` and `review`. A complete file shows the filter as given.
A sanitised file keeps only the `company`, `document` and `series` ids that have a shipped row, and replaces a
`text` with `null` and adds `withheld: ["text"]`.

### Words

`words` holds GCT's fixed wording, the only text a format adds to the rows: `self_declared`, `privacy_notice`,
`archive_notice`, `earlier_version`, `earlier_position`, `outside_selection`, `withheld`, `needs_renewed_review`, and
`fixed`, which holds titles, column headings and the other fixed labels the formats print.

## Checking a file against the schema

`dataset-1.schema.json` is a JSON Schema (Draft 2020-12, `$id` `urn:gct:dataset-schema:1`). Every object is closed
and every key required; the identity, the filter echo and the count fields depend on `mode`. Any Draft 2020-12
validator can check a file without a network. With Python and the `jsonschema` package:

```python
import json
from pathlib import Path

from jsonschema import Draft202012Validator

folder = Path("exports/all-v3-20261023T091258123456Z-sanitised")
schema = json.loads((folder / "dataset-1.schema.json").read_text(encoding="utf-8"))
data = json.loads((folder / "dataset.json").read_text(encoding="utf-8"))
errors = list(Draft202012Validator(schema).iter_errors(data))
print("valid" if not errors else "\n".join(e.message for e in errors))
```

The schema checks times by pattern; `format: date-time` is a note for readers. Two rules are outside it: a key named
in a row's `withheld` is `null`, and every row's `data_version` equals `data_version.version`.

## Schema versions

`dataset_schema` is the number of the dataset's shape, and `dataset-<N>.schema.json` is its schema. Until the first
public release of GCT the number stays 1 and a shape change edits `dataset-1.schema.json`. From the first release
on, every change of shape, an added key included, gets the next number and a new schema file, and earlier schema
files keep shipping so an older export can still be checked.

## Formats added later

Each format is one entry in the format table in `gct/reports/export.py` and writes its files into the export folder
only. A format that must refuse its data raises an error with a cause and a next step; the command then refuses with
that cause and next step and writes no folder. Because the cause reaches the run log, it names tables, ids and fixed
headings only, never a value from a row.

## Exports and deletion

GCT never changes or removes a file in `exports/`. Copies already exported or shared, including files in
`exports/`, cannot be recalled by GCT: after `gct doc delete`, an export made before the deletion still holds the
deleted document's rows. An export made after it reads the rewritten version, with a new `sha256`.
