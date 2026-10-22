# Archive

Archiving takes a document out of every active output and keeps everything it had. It is the step before
deletion (a later version): look at what drops out, archive, and restore if it was a mistake.

## Commands

- `gct doc archive ID --plan` prints what the archive would take out of the active outputs and stores nothing.
- `gct doc archive ID --as KEY --capacity TEXT --rationale TEXT` archives the document and prints the same summary,
  worked out just before the archive is stored.
- `gct doc restore ID --as KEY --capacity TEXT --rationale TEXT` makes an archived document active again.
- `gct doc list [--company NAME] [--active]` shows each document's state (`registered`, `archived` or `restored`).
  `--active` leaves archived documents out and says how many it left out.
- `gct doc show ID` shows the state and, for an archived or restored document, who made that change, in what
  capacity, when and why.

`--as` names a contributor (`gct contributor add`); the capacity and the rationale are what you write, each time.

## What archive keeps

Everything. An archive adds one state row (`archived`) and one record of who archived it, when and why. The file stays
in the store, and every claim, claim version, location, source check, reading, inference, review, correction, match
review, page acceptance, expectation and gap confirmation stays as it was. A restore adds one `restored` state row and
one record in the same way.

## What leaves the active outputs

- `gct read`, `gct extract`, `gct link`, `gct infer` and `gct match` without ids leave it out. Named by id
  (`gct extract 6`, `gct match --doc 6`) it is reported as `skipped`: `the document is no longer active`, and nothing
  is written for it. `gct run resume` and `gct run retry` skip it the same way.
- Its claims leave the series (`gct series list`, `gct series show`), the review queue (`gct match review`) and the
  counts of `gct match status`. A period that had its value and another report's value becomes a single value.
- An expectation looks only in the active documents of its set, so the archived document's claims no longer count
  for it, and its pages are no longer checked for it (`gct expect list`). When every document of the set is archived,
  the item is `processing incomplete or failed` with the reason `no active document in its declared set`, so it can
  never be confirmed as a gap over nothing.
- Its figures leave every comparison pair (`gct restate list`), since pairs come from the series.
- `gct publish build` leaves out the document, its claims, their locations, their series points and its page
  acceptances (see Hidden counts), the pairs and restatement records that name a version of its claims, and the
  column mappings of a spreadsheet (`sheet_mapping`).
  The viewer reads only the published version, so after the next build it no longer offers the document.

## Refused while archived

These are refused with `Document N is archived.` and the next step `Restore it with: gct doc restore N`:
`gct correct` on one of its claims, `gct infer resolve` and `gct infer reject --claim` on one of its claims,
`gct infer scope` on one of its statements, `gct pages accept --doc N`, `gct expect add --doc N`, and
`gct restate record` and `gct restate withdraw` naming one of its claims, and `gct sheet map N`. Archiving an
archived document and restoring one that is not archived are refused too. Adding its file again with `gct doc add`
reports the duplicate and adds `It is archived. Restore it with: gct doc restore N`.

`gct gap confirm` is not refused. A confirmation records the documents it checked; with the archived document out of
the set it records the active ones only. After a restore the set is different again, so that confirmation shows as
made on older readings and the item shows its computed state.

Still available and saying `archived`: `gct claims history` (the document's state is on the first line),
`gct doc show`, `gct doc pages` (first line `Document N is archived.`, `document_state` in its JSON) and
`gct restate show` on one of its claims (`Document N is archived.` in place of the match state, `match_state` null in its JSON, and every record). `gct claims list --doc N` still lists its
claims.

## The impact

`--plan` and the archive print the same summary:

- the document's claims (the newest version of each) and their evidence locations;
- each series it has points in, with the points it gives and the points left;
- each period of a series that holds more than one value and loses one, with the count before and after;
- its items in the review queue;
- the expectations whose state is worked out from it;
- the review records that stay stored but leave the active outputs: period and boundary reviews, corrections and
  match reviews on any version of its claims, its page acceptances, the restatement records (recorded or withdrawn) naming any version of its claims as original
  or restated, and every column mapping of a spreadsheet (`gct sheet map`).

The summary lists the document's own points and items. If another document's figure waited in the review queue only
for a series that this document alone made, that item leaves the queue too; the series shows `points_left` 0.

## Restore

Series, review items, effective periods and boundaries, claim states and expectation states are worked out each time
they are asked for, never stored. A restore therefore brings every output back as it was before the archive:
`gct match status`, `gct series show SERIES --all`, `gct restate list` and the claims, series, points, pairs,
restatement records and sheet mappings of the next `gct publish build` are the same as before.

## Hidden counts

From projection schema 8, a published version has a table `hidden_by_archive` with one row per archived document:
its id, name, when it was archived, and how many claims, evidence locations and review records it hides. The `meta`
key `hidden_by_archive` holds the totals. A view built on the published version can show "N records hidden by
archive" instead of shrinking without saying why.

## Older published versions

`gct publish restore` makes the previous published version current again. That restores a published version, not a
document's state: if the document was archived after that version was built, the version still shows it. Build a new
version (`gct publish build`) to leave it out again. Deletion, in a later version, is different: a published version
that holds a deleted document can never be made current again.
