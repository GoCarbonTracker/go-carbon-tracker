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
- `--format` is a comma list of format names; each format has its own section in this file. A repeated name counts
  once. An unknown name is refused before anything is read: "Unknown format X. Available: " and the format names in
  alphabetical order.
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
workspace, a workspace that needs an upgrade (an export never upgrades it: run a command that writes, for example
`gct publish build`, first), a workspace made by a newer gct, no published version, a `--data-version` that is not the current one, a version file that is missing or
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
`fixed`, which holds titles, column headings and the other fixed labels the formats print. Among them, for images
and PDFs:

- `image_alt`, an image's alt text naming the claim, document and page; `image_alt_entry`, the alt text naming the
  evidence reference instead (for example E12), for an entry no row with a claim id cites; `image_cap`, the caption
  of an outlined area.
- `image_limit`, the sentence printed once when an export cites more locations than GCT draws as images. It holds no
  number.
- `pdf.row`, a row block's heading, `{title} {id}`; `pdf.evidence`, the label of the line that lists a row's
  evidence references; `pdf.font_note`, the note that a character the font lacks is printed as its NFKC form or as
  `[U+XXXX]`, never as a box.

Every word is the same in both modes.

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

GCT never changes or removes an export or a file you put in `exports/`; it removes only the temporary folder of an
export that failed. Copies already exported or shared, including files in
`exports/`, cannot be recalled by GCT: after `gct doc delete`, an export made before the deletion still holds the
deleted document's rows. An export made after it reads the rewritten version, with a new `sha256`.

## XLSX and CSV

`--format xlsx` writes one workbook per report `NAME` names: `evidence-index.xlsx`, `restatement-log.xlsx` and
`gap-report.xlsx`. `--format csv` writes one folder per report, `evidence-index/`, `restatement-log/` and
`gap-report/`, holding `about.csv` and one file per table, named after the table's key in `columns` (for example
`records.csv`), and `pair_sides.csv` for the pair sides. `--format xlsx,csv` writes both into one export folder. The
layout is provisional until people who use the reports have said what they need.

### Tables

Each report holds its own tables, the sheets of its workbook and the files of its folder, in this order:

- evidence index: Evidence index, Review records, Disagreements, Documents;
- restatement log: Restatement log, Restatement records, Adjudications, Unpaired restatements, Pair sides,
  Documents;
- gap report: Inconsistency candidates, Restatement records, Adjudications, Pair sides, Expectations, Missing
  reasons, Accepted pages, Declared documents, Documents checked, Extraction limits, Archived documents, Deleted
  documents, Documents.

Titles come from `words.fixed.titles` and the columns, their headings and their order from `columns`. A sub-table's
sheet holds the sub-table rows of every parent row, in parent order, and each row names its parent in the parent's
id column (Claim, Pair or Expectation). A table with no rows still has its heading row.

**Pair sides.** A restatement log or candidates row names its two claims only by `claim_a` and `claim_b`. The Pair
sides table holds each claim a pair of that report names, once, in pair order: its `evidence_index` row, or its
`related_claims` row when it is outside the selection, with the evidence index's columns. The pair row's Claim A
selection and Claim B selection columns say "outside this selection" for such a side, and are empty otherwise. The
related claims have no table of their own.

### The About sheet, the version band and the notices

The first sheet, About, and `about.csv` hold a Field and Value heading and one row per item: the data version
fields the mode holds (`history_mark` and `labels_mark` in a complete output only), the dataset's built time, schema
and GCT version, the mode line, the included classes, the filter, every notice, and the line "Identities and
capacities are self-declared. GCT does not check them and does not adopt any conclusion as its own." when the output
holds a row with a contributor. The mode line, the notices and that line have an empty Field cell. The filter is
compact JSON with sorted keys; in a sanitised output a withheld `text` shows `withheld`.

Every other sheet starts with the version band: the data version number, when the version was built, its SHA-256
and the mode line. The next rows hold every notice, one per row, then the self-declared line when that sheet holds
a row with a contributor, then one empty row, the headings and the data. Panes are frozen under the headings and a
filter covers the headings and the data. A CSV table file starts with its headings. In both formats every data row
carries the data version in its Data version column.

### Values

- Text is written as text. A number is a number: in XLSX as the file stores it, at most 16 significant digits (so
  `1260.0` reads back as `1260`), in CSV as Python writes it (`1260.0`).
- `true` and `false` print `yes` and `no`; a list prints its items joined with `; `; a key named in the row's
  `withheld` list prints `withheld`, also when its object is `null`; a `null` or empty value is an empty cell. A
  dotted column such as `correction.created_at` takes the value inside its object.
- An XLSX text cell is always an inline string, never a formula or an error value, so `=1+1` and `#N/A` stay text.

### Cell safety

Three transforms are applied, in this order, and nothing else:

1. Both formats: the control characters U+0000 to U+0008, U+000B, U+000C and U+000E to U+001F, and U+FFFE and
   U+FFFF, become U+FFFD. Tab, line feed and carriage return stay.
2. XLSX only: a carriage return and line feed, or a carriage return alone, becomes a line feed, since an XLSX file
   cannot hold a carriage return that reads back.
3. CSV only: a text that starts with a tab or a carriage return, or with `=`, `+`, `-` or `@` and is not a plain
   number such as `-12.5` or `-1,234`, gets one leading `'`, so a spreadsheet program does not read it as a formula.

The command prints, as notes on your terminal only, how many characters were replaced and how many CSV cells got a
leading `'`. Use the JSON export for exact text.

CSV files are UTF-8 with a byte order mark, comma separated, with CRLF line ends, every text field quoted and
numbers bare. A spreadsheet program may still read some CSV text in its own way, for example as a date; the
workbook keeps text as text. Two CSV exports of one dataset are identical byte for byte; two workbooks hold the same
cells but differ in their stored save times.

### XLSX refusals

Before any file is written, an XLSX export is refused when a cell would be longer than 32,767 UTF-16 units after the
transforms, or a sheet would have more than 1,048,576 rows, the band and the headings included. The refusal names
the table, the row id and the column, and its next step is "Export CSV or JSON for this selection, or narrow the
filter." CSV has neither limit.

## PDF

`--format pdf` writes one PDF per report `NAME` names: `evidence-index.pdf`, `restatement-log.pdf` and
`gap-report.pdf` (all three for `all`). The layout is provisional until practitioners have used it.

- **Pages.** A4 portrait, 36 pt margins, the Vera fonts that ship with reportlab. The first page holds the report
  title, every `data_version` key the mode holds, the dataset's `gct_version`, `built_at`, `dataset_schema` and
  `include`, the mode line, the filter (one field per line), the notices and, when any row is attributed, the
  self-declared line. Every page's footer holds the report title, the data version, the first 12 characters of its
  `sha256`, the page number and, in a sanitised PDF, the privacy notice.
- **Rows.** One block per row, opened by its heading (`words.fixed.pdf.row`, for example "Evidence index 19"), then
  one "heading: value" line for every column of the table, an empty value included, and a line with the row's
  evidence references ("E12; E14"). Sub-tables follow under their parent row, indented, with their title. Each
  restatement log pair and gap report candidate prints both claims under "Pair sides", a claim outside the
  selection marked "outside this selection"; the restatement log then prints the unpaired restatements. The gap
  report prints its six parts in a fixed order. Every PDF ends its rows with the documents table.
- **Evidence appendix.** One entry per evidence reference the PDF's rows cite, in document and page order, with the
  document name and version and the page, or the sheet and cell. A located figure shows a band of its page: the
  page's full width (one half of a two-page spread when the figure sits in that half) by the figure's boxes plus
  24 pt above and below, rendered at 216 dpi by the viewer's own renderer, each box outlined in red just outside its
  edge. It is drawn at most at full size and scaled down only to fit the page. A reference without a box shows the
  whole page as the viewer shows it. A spreadsheet cell shows its row as a two-column table with the header, the
  cited cell in bold, and no image. A record on an earlier version shows its location as text, no image. The
  pictures are cut from the stored originals when the export runs, from the same data version as the rows; the
  viewer's page cache is neither read nor written.
- **Image cap.** When the dataset holds more than 500 page locations, the PDFs hold no images: every location is
  listed as text and `words.fixed.image_limit` is printed once. A narrower `--filter` brings the images back.
- **Characters.** A character the font cannot draw is printed as its NFKC form when that is drawable (`CO₂` as
  `CO2`), else as `[U+XXXX]` (`₹` as `[U+20B9]`), and the first page prints `words.fixed.pdf.font_note` once. The
  text you see is the text a PDF reader extracts. The format's note on the terminal gives the count per file.
- **What a sanitised PDF leaves out.** The same rows and fields as the sanitised dataset, and no image of a page of
  a private document. A complete PDF holds private documents' names, figures and page images.
- **Repeat runs.** Two PDFs of one dataset are byte-identical: the PDF's own date is 2000-01-01 unless
  `SOURCE_DATE_EPOCH` is set, and the dataset's `built_at` on the first page is the time that counts.
- **Refusals.** The export is refused, with nothing written, when the stored copy of a document whose page it shows
  is missing from the workspace (add the same file again with `gct doc add` to restore it) or when a row comes from
  another data version than the report.
