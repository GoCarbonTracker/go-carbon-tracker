# Spreadsheets

A company's own evidence, such as a metering export, can sit beside its reports as a CSV or XLSX document. Its
figures become claims that point at the file version, the sheet and the cell. Adding or mapping a spreadsheet never
confirms anything.

Version: sheet rules 1, folded into the `sheet` stage's config, so a change to the rules makes the next `gct extract`
read every mapped sheet again (a claim version is added only where a field changes).

## Formats

- CSV: UTF-8 (a byte order mark is ignored). The delimiter is detected among `,`, `;`, tab and `|`, the same ones
  `gct doc add` accepts. A CSV is one sheet, named after the file without its suffix (`metering.csv` is sheet
  `metering`, position 1).
- XLSX: read with the Python standard library (`zipfile` and `xml.etree`), no other package. Sheets keep their
  workbook order; the first is position 1.
- Nothing else: no ODS, no XLS, no JSON. Add those as CSV or XLSX.

## One header row

Row 1 of each sheet is its header. Every column is named by the text printed there. Merged headers, headers over two
rows or a table that starts lower down are not supported; such a file needs saving with one header row first.

`gct sheet show DOC` prints each sheet with its header row, its first five data rows as stored, and its current
mapping, or `no confirmed mapping`.

## The mapping

`gct sheet map DOC --sheet NAME --metric COL --value COL [--unit COL] [--period COL] [--boundary COL] [--company COL]
[--note COL] [--year-end MM-DD] [--boundary-is standalone|consolidated|subsidiary_set [--boundary-detail TEXT]]
--as KEY --capacity TEXT --rationale TEXT`

COL is a header as printed in row 1 (runs of spaces count as one). A header that is not in row 1, or that row 1
prints twice, is refused. The mapping is a record by a named contributor: it says what each column means and nothing
about whether the values are right. It is insert-only; the newest mapping of a sheet is current, and the earlier ones
stay in the history and in the published version. A sheet with no mapping is never read for figures.

## What is extracted

`gct extract` runs the `extract` stage for PDF documents and the `sheet` stage for CSV and XLSX documents; a
selection holding both makes two runs. The `sheet` stage has one item per mapped sheet, keyed on the file's SHA-256
and the current mapping, so running it again with nothing changed reuses the result, and a new mapping reads the sheet
again.

Each data row whose value cell is not empty becomes one claim:

| Claim field | From |
|---|---|
| page number | the sheet's position (a CSV: 1) |
| locator | `s<position>r<row>`, the row as numbered in the spreadsheet (the header is row 1) |
| metric text, value text, unit text, period label | the mapped cells, as stored |
| value | the value text when it is a plain number (`1234.5`, `1,234`), else none |
| boundary label | the boundary cell, as printed; it never becomes a reporting boundary on its own |
| note | the note cell, kept beside the claim version |

A row whose company cell (when that column is mapped) is not the document's company, compared without case and with
runs of spaces as one, is skipped and counted (`row for another company`). A row whose company cell is empty is
skipped and counted on its own (`row without a company`). A claim keeps its identity by its sheet and
row; a new mapping adds a version only where the value, unit, metric, period label, boundary label, value cell or
note changes. `gct extract` reports each sheet without a mapping and the rows skipped for another company or without
one.

## Cell references

The claim's evidence is the sheet name and the value cell (`Energy`, `C7`) of the stored file version, with no page
and no box. `gct claims list` prints `sheet Energy cell C7` where a report claim prints its page, and `gct series
show` names the sheet and cell of a spreadsheet point.

`gct link` reads the value cell of the claim's row under the sheet's current mapping from the stored file. When it
holds the claim's value text the location is `matched`; otherwise it is `cited` with the cell and what it holds, for
example after a new mapping points the value column elsewhere and before `gct extract` has run again.

## Comparisons and restatements

A spreadsheet figure in a same-period set is compared like any other (`docs/restatements.md`). It is never `same
table row`, since it has no printed table, so a different value from a report is an `unresolved conflict`.
`gct restate record` cannot name it as the restated figure: the record needs a quote found on a page reading of
the restated figure's document, and a spreadsheet has no pages. It can be the original. `gct restate list` and
`gct restate show` print its sheet and cell where a report figure prints its page.

## Archive

Archiving a spreadsheet (`docs/archive.md`) takes its claims and its column mappings out of the active outputs and
of the published version; `gct extract` skips it when it is named, and `gct sheet map` on it is refused until
`gct doc restore`. Its mapping rows are counted among the review records the archive hides.

## What the upload never does

`gct doc add`, `gct sheet map` and `gct extract` write files, mapping rows, claims, the note of each claim version
(`claim_note`) and, as the PDF extraction does, the location check of each new evidence reference (`source_match`,
the same check `gct link` makes) only. None of them writes a
period or boundary review, a match review, a correction, a gap confirmation or a page acceptance. Internal evidence is
evidence to compare, never a confirmation of a report's figure.

## Declarations are proposals

`--year-end` and `--boundary-is` are the contributor's declarations for the sheet. `gct sheet map` stores them only.
The next `gct infer` writes each current mapping's declaration as a statement worded `declared in sheet mapping #N by
NAME`, so it is never taken for printed text, and a boundary declaration covers only its own sheet, declared by the
mapping's contributor. `gct infer` then proposes periods (a label such as `FY 2023-24` with year end `03-31` is
2023-04-01 to 2024-03-31) and boundaries exactly as for a report. Nothing is effective until `gct infer accept` or
`gct infer resolve`. Only the current mappings' declarations count. Without a year end, fiscal-year labels stay
unresolved (`no fiscal year statement in this document`), as for a report; two sheets declaring different year ends
are a conflict.

## Privacy

A spreadsheet keeps the registry's rule: it is `private` unless it was added with `--privacy shareable`. The published
version carries the document's privacy as for any document.

## The readers' limits

- Values are read as stored. Number formats are not applied: a cell shown as `12.5%` or `1,234.00` is read as its
  stored number (`0.125`, `1234`).
- Dates are not interpreted: an Excel date is its stored serial number (`45382`).
- Formulas are not evaluated: a formula cell is read as the value the file stored for it when it was last saved.
- Shared strings, inline strings and rich-text runs are read as plain text; phonetic guides are left out.
- Every cell needs its reference (`C7`) in the file; Excel and LibreOffice write it.
