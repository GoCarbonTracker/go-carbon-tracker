# Matching and time series

`gct match` gives each claim version a canonical metric key and a unit, then series of one metric over reporting
periods are worked out on read from those assignments, the effective periods and boundaries (`gct infer`, accepted or
resolved only) and the claim states (`gct correct`). Series are never stored in `workspace.db`; `gct publish build`
writes them to the published version. Matching links figures. It never says that two values agree or differ.

Versions: match rules 1, metric list 1, unit table 1. All three are folded into the stage's config version, so a change
to any of them makes the next `gct match` assign every claim again (a row is added only where the result changes).

## Metric list v1

Absolute totals only. The label is lowercased, whitespace collapsed and the footnote marks `#`, `*` and `†` removed
before matching. A label containing any of `intensity`, `per rupee`, `per unit`, ` per `, `%` or `percentage`, or
the whole word `ratio` or `category`, is unmapped for every key (`operations` and `generation` contain `ratio` but
are not excluded). The same words are checked on the printed unit, normalised the same way: a target `Scope 3:
Achieve a` with unit `%` is unmapped.

| Key | Must contain one of | Must not contain |
|---|---|---|
| `ghg_scope_1` | `scope 1`, `scope-1`, `scope i` | `scope 2`, `scope ii`, `scope 3`, `scope 1 and`, `scope i and`, `scope 1 +`, `scope 1+`, `scope 1 &`, `scope 1,` |
| `ghg_scope_2` | `scope 2` | `scope 1`, `scope 3`, `market`, `location` |
| `ghg_scope_1_2` | `scope 1 and scope 2`, `scope 1 and 2`, `scope 1+2`, `scope 1 + 2`, `scope 1 & 2`, `scope 1 &2` | `scope 3` |
| `ghg_scope_3` | `scope 3` | `scope 1`, `scope 2` |
| `energy_total` | `total energy consum` | `renewable` |
| `energy_renewable` | `energy consumed from renewable` | `non-renewable`, `non renewable` |
| `energy_non_renewable` | `energy consumed from non-renewable`, `energy consumed from non renewable` | |
| `water_withdrawal_total` | `total volume of water withdrawal` | |
| `water_consumption_total` | `total volume of water consumption` | |
| `water_discharge_total` | `total water discharged` | |
| `waste_total` | `total waste generated` | |

A phrase ending in a number or a one-letter word ends there: `scope 1` does not match `scope 12`, `scope i` does not
match `scope ii`. A label that satisfies exactly one key gets that key, and `rule` records the key and the phrase
(`ghg_scope_1: scope 1`). A label that satisfies two keys is unmapped with rule `ambiguous`. Any other label is
unmapped with no rule. The printed wording is never changed.

## Unit table v1

The unit comes from the claim's printed unit. When that is empty or not in the table, it comes from a unit printed in
the label (recorded as `unit_source` `label`): each parenthesised group, last first (`(in kilolitres)`), then the
label's last five, four, three, two or one words joined without spaces (`tco 2` is looked up as `tco2`). Otherwise the
unit is unknown. A printed unit left out of the table on purpose (`mtco2e`, `ml`, below) stays unknown: the label is
not read for a unit then.

Before lookup the text is lowercased, the word `in`, brackets and whitespace are removed, and one magnitude word at the
start or end is multiplied in: `thousand` and `'000` ×1e3, `lakh` ×1e5, `crore` ×1e7, `million` ×1e6, `billion` ×1e9.

Each unit belongs to one conversion family, named by its base unit. Two units are comparable only inside one family; a
broad dimension such as "emissions" never makes them comparable.

| Family (base) | Units and factor to the base |
|---|---|
| `tco2e` | `tco2e`, `tco2-e`, `tco2eq`, `tonnesco2e`, `tonnesofco2e`, `metrictonnesofco2e`, `tcoe2` (rung 1 reads a printed `tCO₂e` as `tCOe 2`) ×1; `ktco2e` ×1000 |
| `tco2` | `tco2`, `tonnesofco2`, `metrictonnesofco2` ×1. Never converted to `tco2e` |
| `gj` | `mj` ×0.001, `gj` ×1, `tj` ×1000, `pj` ×1e6, `kwh` ×0.0036, `mwh` ×3.6, `gwh` ×3600 |
| `kl` | `kl`, `kilolitres`, `kiloliters`, `m3`, `cubicmetres` ×1, `litres` ×0.001, `megalitres` ×1000 |
| `t` | `t`, `tonnes`, `tons`, `mt`, `metrictonnes` ×1 (in these reports `MT` is metric tonnes), `kg` ×0.001 |

Left out on purpose: `mtco2e` (megatonnes or metric tonnes cannot be told apart) and `ml` (millilitres or megalitres).

The families each key accepts: the emissions keys `tco2e` or `tco2` (each its own series), the energy keys `gj`, the
water keys `kl`, `waste_total` `t`. An unmapped label accepts any family. A unit in the table whose family the key does
not accept (a Scope 1 figure in GJ) is `unit not convertible`.

The base value (`value × factor`) is for display only. The printed value and unit are never rewritten.

## Series key

A series is: the company; the metric key, or for an unmapped claim
`doc:<document id>:p<page>:<tNrR>:<label as matched>`, where `tNrR` is the table and row part of the claim's table
cell locator `tNrRcC` (an unmapped label matches only the other columns of its own printed table row, so a generic
label such as `Total` or `NA` never pools rows or tables); the effective boundary and, for `subsidiary_set`, its
detail; the unit family (or, for a `unit as printed` series, `printed:<unit text normalised as for the lookup, or ->`
with the document, page and table row); the effective period kind. The series id is the first 12 hex digits of the
SHA-256 of that key.

A claim joins a series by rule only when its newest version is `current`, its period is `resolved` or `accepted`, its
boundary is `resolved` or `accepted` and not `unknown`, and its unit is known and accepted for its metric.

`unit as printed`: table cells with a resolved boundary whose unit is unknown or not convertible form a series with
the other cells of the same printed table row (same document, page and `tNrR`) that have the same series key and the
same unit text once normalised as
for the lookup (`A+B+C` and `a + b + c` are the same; both empty counts as the same), when there are at least two.
Such a series has no base values and its points are not comparable. Its points still show the unit as printed.

A same-period set is two or more points of one series with equal period start and end. It is listed with every value
as printed and its source; 4.1 never compares them.

## Review queue

A current claim with a known period and a metric that did not join a series is an uncertain item when at least one
series exists with the same company, metric and period kind, and, when the claim's own boundary is known, the same
boundary (and detail), and, when the claim's unit is known and accepted for its metric, the same unit family (never
another family or a `unit as printed` series). The reason is `boundary unknown` (checked first; every boundary is then a candidate),
`unit unknown` or `unit not convertible`. There is one item per claim version and candidate series. A `linked` review
puts the claim in the series as `reviewed, not comparable`; a `not_linked` review takes the item off the queue. A
claim is in one series at most, and the newest review per claim version and series wins. A review never makes the
boundary or the unit known, so a reviewed point is stored with `comparable` 0 and its reason. A new version of the
claim is unreviewed again.

## Never linked

Each claim ends in exactly one match state: `series`, `reviewed`, `uncertain` or `not matchable`. Not matchable, with
its reason, never linked and never queued:

- `not current`: the claim's newest version is not current.
- `not mapped yet: gct match`: `gct match` has not run since the newest version appeared.
- `period unknown`: the period is not resolved or accepted.
- `no metric label`: an unmapped claim with no label.
- `unmapped outside a table row`: an unmapped claim whose locator is not a table cell (a figure in running text).
- `boundary unknown, no series to join`, `unit unknown, no series to join`, `unit not convertible, no series to join`:
  no candidate series exists.
- `not linked by review`: every candidate was answered `not_linked`.

Standalone and consolidated figures never share a series, by construction, nor do tCO2 and tCO2e, a quarter and a
year, or an `as_at` stock and a flow.
