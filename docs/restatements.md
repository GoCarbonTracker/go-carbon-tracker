# Restatements and conflicts

A same-period set is two or more points of one series (`docs/matching.md`) with the same period start and end: one
company, one metric, one boundary, one unit family and one period, printed more than once. `gct restate` gives every
pair of points of every same-period set exactly one state. The states are computed on read from the series, the
claim versions and the restatement records; they are never stored in `workspace.db`. `gct publish build` writes them
to the published version (`comparison`), with every restatement row (`restatement`).

## States

- `not compared`, with a reason. When more than one applies, the first in this order is given:
  - `unit as printed`: the series is a `unit as printed` series, whose unit is not in the unit table.
  - `reviewed, not comparable`: a point was linked by review (`gct match link`); its boundary or unit stays unknown.
  - `no numeric value`: a point has no number (below).
  - `same table row`: both points come from one document, one page and one printed table row. Two columns of one row
    are never the same figure printed twice, even when both resolve to one period.
- `same value`: the base values are equal (below).
- `restatement`: a current restatement record names exactly this pair of claim versions.
- `unresolved conflict`: the base values differ and no current record names the pair. This is an inconsistency
  candidate. Two tables of one report that print different values for the same metric and period are one too, and
  stay unresolved until a record cites the source.

A pair never mixes standalone and consolidated figures, an unknown boundary, tCO2 and tCO2e, or two kinds of period:
those never share a series, so they never form a pair.

## Numbers and equality

The number of a point is the claim's value, or, when extraction gave it none, the number read from the value as
printed by match rules 2: the Western form, or Indian grouping (`29,79,832`), after trailing footnote marks `*`, `#`,
`†` and `^` are removed. Parentheses never give a sign; `(1,234)` has no number. The base value is the number times
the unit's factor. The printed value and the claim's value are never rewritten.

Two base values are equal when they differ by at most 1e-9 of the larger one, which only absorbs float conversion
error (1,000 MWh × 3.6 against 3,600 GJ). Any larger difference is a difference. There is no size threshold and no
rounding tolerance: a report that prints `43,325` beside `43,325.4` gives an unresolved conflict. `gct restate list
--state` hides rows from the listing and says how many it hid; it never drops a pair or a record.

## What establishes a restatement

Only a record made by a contributor with `gct restate record`. It names the original claim and the restated claim
(the contributor says which is which), and it cites a page of the document that prints the restated figure and the
line quoted exactly as printed there. The quote must be found on the newest reading of that page, its words joined by
single spaces in reading order; whitespace in the quote is collapsed, case is kept, and a line broken by a hyphen is
not joined. Contributor, capacity and rationale are required as for every review record. The quote check proves only
that the text is printed on that page, not that it is a restatement statement; the contributor's rationale carries
that judgment.

A record is accepted only for a pair that is an `unresolved conflict` now. It is refused for a pair that is
`same value` or `not compared`, for two claims that are not in one same-period set of one series, for a claim that is
not current or whose newest version has not been matched yet (`gct match`), for a page outside the document or not
read, and for a quote not on the page.

`gct restate withdraw` adds a `withdrawn` row for the pair, which then is computed again (usually `unresolved
conflict`). Records are never changed or removed; the newest row for an original and restated version decides.

gct does not detect restatement notes printed in reports. A restated figure printed with a footnote mark or outside a
ruled table is not extracted by rung 1 yet, so such a note has no claim to bind to; automatic proposals wait for an
extract rules version that reads those figures.

## Binding to versions

A record binds to the two claim versions it names. When either claim gets a new version (a correction or a new
extraction), the record no longer names the pair of newest versions, so the pair is compared again, and the old
record stays in the history: `gct restate show CLAIM` lists it under the version it names.

`binds` says whether a row still applies: it is true (1 in the published `restatement` table) when both versions the
row names are their claims' newest versions, and false (0) otherwise. A row that does not bind decides no pair, even
when it is the current row for its two versions; `gct restate show` marks it `(on an earlier version)`. Such a record
cannot be withdrawn, since `gct restate withdraw` names the pair of newest versions, and it needs no withdrawal.

## No report order

Documents carry no publication date, so the store never decides which report is later. `gct restate list` and the
published `comparison` order the two points of a pair by document id, then claim id, for display only. Which figure
is the original and which the restated one is what the contributor recorded.

## Commands

- `gct restate list [--company NAME] [--state same|restatement|unresolved|not-compared]`: one line per pair: series
  id, company, metric key, boundary, period, both values as printed with document, page and claim, the state and the
  reason or the record id.
- `gct restate show CLAIM`: the pairs of the claim's newest version and every record attached to each version of the
  claim, to the other version of each pair and to the other version named by each restatement row on the claim's
  versions: period and boundary reviews, corrections, match reviews, the newest source match of each location and
  every restatement row, withdrawn and superseded ones included. With no pair, it says why: the claim's match state
  and reason when it is in no series, else that it shares no period.
- `gct restate record --original CLAIM --restated CLAIM --page N --quote TEXT --as KEY --capacity TEXT --rationale TEXT`
- `gct restate withdraw --original CLAIM --restated CLAIM --as KEY --capacity TEXT --rationale TEXT`
- `gct series show` marks each point of a same-period set with its pair states, and `gct match status` counts pairs
  by state per company.

`--json` shapes are in `docs/cli-json.md`.
