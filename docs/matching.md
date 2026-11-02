# Matching and time series

`gct match` gives each claim version a canonical metric key and a unit, then series of one metric over reporting
periods are worked out on read from those assignments, the effective periods and boundaries (`gct infer`, accepted or
resolved only) and the claim states (`gct correct`). Series are never stored in `workspace.db`; `gct publish build`
writes them to the published version. Matching links figures. It never says that two values agree or differ; the
pairs of a same-period set are compared by `gct restate` (`docs/restatements.md`).

Versions: match rules 4, metric list 3, unit table 2. All three are folded into the stage's config version, which is
stored on every assignment row, so a change to any of them makes the next `gct match` assign every claim again and add
one row for every newest claim version, even where the key, rule and unit stay the same. Reviews bind to the claim
version and series, so they and the series stay as they were. Later runs with an unchanged config add a row only where
the result changes. Match rules 2 (story 4.2) adds the number rule below. Metric list 2 is the combined-scope list of
4.1 fix 95e3c9e (`scope 1 & 2` and the other combined forms map to `ghg_scope_1_2`, and the exclusion words are checked
on the printed unit too), given its own version number in story 4.2; the list did not change then. Story 4.6 raises
all three: match rules 4 adds the count rule, metric list 3 adds the count and currency totals, unit table 2 adds the
currency families and the magnitude plurals. Because the count and currency families change the series key of a claim
that had no family before, a claim that was `unit unknown` under the earlier versions becomes a rule point of a series
after the next `gct match`. A review or restatement recorded before keeps its row, bound to the claim version; the
earlier assignment rows stay in history. Archived and deleted documents are not matched again.

## Numbers (match rules 2)

The number of a point is the claim's value when extraction gave it one. Otherwise it is read from the value as printed,
after trailing footnote marks `*`, `#`, `†` and `^` are removed: the Western form extraction accepts (`43,325`,
`1,234.5`), or Indian grouping (`29,79,832`, `9,76,828.5`: the last group three digits, every earlier one two). `12,34`,
`1,2345`, `1.234,56`, `NA` and `-` have no number, and parentheses never give a sign: `(1,234)` has no number. The
number is used for the base value and for comparison only: the printed value and the claim's value are never
rewritten and no claim version is added.

## Metric list v3

Absolute totals only (headcount, board, safety, spend and financial totals join the emissions, energy, water and waste
keys). The label is lowercased, whitespace collapsed and the footnote marks `#`, `*` and `†` removed
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
| `employees_total` | `permanent employees (d)`, `total employees (d+ e)` | `other than`, `workers`, `covered`, `minimum wages`, `/`, `male`, `female`, `differently abled` |
| `workers_total` | `total workers (f` | `permanent`, `male`, `female`, `/`, `differently abled` |
| `employees_male` | `total employees (d+ e) male` | `%`, `covered` |
| `employees_female` | `total employees (d+ e) female` | `%`, `covered`, `posh` |
| `fatalities` | `no. of fatalities` | `category`, `rate` |
| `recordable_injuries` | `total recordable work-related injuries` | `rate`, `frequency`, `category` |
| `board_size` | `board of directors` | `female`, `percentage`, `(bod) male`, `(bod) female`, `meeting`, `attendance` |
| `community_investment` | `total amount spent for the financial year` | `unspent` |
| `regulatory_fines` | `penalty/ fine` | `settlement`, `compounding` |
| `auditor_fees` | `audit fees` | `cost audit`, `tax audit`, `internal` |
| `revenue_total` | `revenue from operations`, `gross turnover`, `turnover (in` | `rate`, `contract`, `inc./`, `%`, `employee`, `staff`, `attrition`, `inventory`, `asset` |
| `paid_up_capital` | `paid-up capital`, `share capital` | `partly`, `per share`, `authorised`, `bonus` |
| `net_worth` | `net worth` | `yes` |
| `ebitda` | `ebitda` | `margin`, `%`, `ebit ` |
| `operating_income` | `operating profit`, `underlying ebit` | `ebitda`, `margin`, `%` |
| `profit_before_tax` | `profit before tax`, `profit before taxation` | `effect on`, `eur`, `inr effect` |
| `net_income` | `profit for the year`, `profit after tax` | `margin`, `average`, `non`, `attributable`, `%` |
| `total_assets` | `total assets` | `non-current`, `current`, `financial`, `deferred`, `fair value`, `intangible` |
| `cash_equivalents` | `cash and cash equivalents` | `increased`, `decreased`, `other bank`, `%` |
| `accounts_receivable` | `trade receivables` | `not due`, `continued`, `allowance`, `impairment` |
| `inventory` | `inventories` | `raw materials`, `finished goods`, `stock-in-trade`, `ghg`, `emission`, `carbon`, `turnover`, `write` |
| `operating_cash_flow` | `net cash from operating activities`, `net cash provided by operating activities` | `investing`, `financing`, `totalled` |
| `dividends_paid` | `dividend paid` | `income`, `received`, `per share`, `(%)`, `proposed`, `tax on` |
| `rd_expenditure` | `r&d expenditure` | |

The 24 new rows are 7 count keys and 17 currency keys. Where each phrase comes from (every phrase comes from a page or a
named form, never from what a row would probably say):

- **A printed label** (22 keys): the text was read from a report we hold; `tests/test_match.py` names the report and
  page next to each phrase. `rd_expenditure` comes from a sentence (currency keys are not limited to table cells);
  `r&d investment` is not a phrase because the extracted CDP row reads `investment in low-carbon r&d`, a subset.
- **A form's wording** (2 keys): `regulatory_fines` is the row `Penalty/ Fine` of the monetary table in Principle 1,
  Essential Indicator 2 of the SEBI BRSR format (Annexure I to circular SEBI/HO/CFD/CMD-2/P/CIR/2021/562, 10 May 2021,
  PDF page 9; the column is `Amount (In INR)`); `community_investment` is the row `Total amount spent for the Financial
  Year` of Annexure II of the Companies (Corporate Social Responsibility Policy) Rules 2014, as inserted by the 2021
  amendment (Gazette Part II Section 3(i)). Both were copied from the form text.
- **Reserved** (19 keys): below.

Bare `turnover` is not a phrase: two Mahindra sustainability pages print `turnover rate` 25 times, and `turnover rate
for permanent employees and workers` (BRSR Principle 3 Q3, a percent table) is unmapped. `revenue_total` carries `rate`
and `attrition` in its `must not` list for that reason. `total equity and liabilities`, `capital expenditure on r&d`,
`borrowings` and `board meetings held` are unmapped. `turnover (€ million)` gives a unit (`eur`, ×1e6) but no metric
key, since only `turnover (in` is a phrase.

A phrase ending in a number or a one-letter word ends there: `scope 1` does not match `scope 12`, `scope i` does not
match `scope ii`. A label that satisfies exactly one key gets that key, and `rule` records the key and the phrase
(`ghg_scope_1: scope 1`). A label that satisfies two keys is unmapped with rule `ambiguous`. Any other label is
unmapped with no rule. The printed wording is never changed.

## Unit table v2

The unit comes from the claim's printed unit. When that is empty or not in the table, it comes from a unit printed in
the label (recorded as `unit_source` `label`): each parenthesised group, last first (`(in kilolitres)`), then the
label's last five, four, three, two or one words joined without spaces (`tco 2` is looked up as `tco2`). Otherwise the
unit is unknown. A printed unit left out of the table on purpose (`mtco2e`, `ml`, below) stays unknown: the label is
not read for a unit then. So does a printed unit that is a magnitude word alone (`in crores`, `million`): it names no
currency, and reading the label would record a crore figure at factor 1. A rule that joins such a unit with the
currency in the label is a later rules version.

Before lookup the text is lowercased, the word `in`, brackets and whitespace are removed, and one magnitude word at the
start or end is multiplied in: `thousand` and `'000` ×1e3, `lakh` and `lakhs` ×1e5, `crore` and `crores` ×1e7, `million`,
`millions` and `mn` ×1e6, `billion`, `billions` and `bn` ×1e9. There is no `m`: `mtco2e` would then read as `tco2e`
×1e6, and it is left out on purpose.

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

Currency words (`CURRENCY_UNITS`, merged with the table only when a unit is looked up; they are kept out of the table
because `gct extract` reads the table to decide what a unit cell is) give one family per currency, factor 1, and no
exchange rate:

| Family | Words |
|---|---|
| `inr` | `inr`, `₹`, `rs`, `rs.`, `rupees` |
| `eur` | `eur`, `€`, `euro`, `euros` |
| `usd` | `usd`, `$`, `us$` |
| `gbp` | `gbp`, `£` |

With a magnitude word they read as in `INR crore` (`inr` ×1e7), `Rs. crores` (`inr` ×1e7), `EUR million` (`eur` ×1e6),
`$ mn` (`usd` ×1e6). A figure in one currency never converts to another: two currencies of one metric and company form
two series, and neither is a candidate of the other. There is no exchange-rate source; comparing across currencies is
for the calculation builder. The symbols `€`, `$` and `£` are not yet in the extractor's unit vocabulary, so a euro
figure printed as `€ million` reaches the matcher through the label only (`turnover (€ million)`); adding them to
`gct extract` is a follow-up.

Counts. The family `count` has factor 1 and no unit words in the table. A count key (`employees_total`, `workers_total`,
`employees_male`, `employees_female`, `fatalities`, `recordable_injuries`, `board_size`) takes it only for a table
cell, and only when the unit has no family: the printed unit is empty (`unit_source` `key`) or one of `nos`, `nos.`,
`no.`, `number`, `numbers`, `persons`, `employees`, `workers`, `meetings`, `complaints`, `units`, `vehicles`
(`unit_source` `unit`). Any other printed unit (`A+B+C`, `FY 2024-25`, `No. (B)`, `ML`) leaves the unit unknown, a
figure in running text never gets a family from its key, and count words are never read from the label. A `%` on a count
key is unmapped as for every key. The BRSR tables print a count with no unit, which is why the key itself says
"count". Because the unit of an annual-report statement sits in a header, its currency keys have no unit in the row:
they map, form `unit as printed` series inside a document and do not join across documents until a later rules version
reads the header unit.

The families each key accepts: the emissions keys `tco2e` or `tco2` (each its own series), the energy keys `gj`, the
water keys `kl`, `waste_total` `t`, the count keys `count`, the currency keys `inr`, `eur`, `usd` and `gbp` (each its
own series). An unmapped label accepts any family. A unit in the table whose family the key does not accept (a Scope 1
figure in GJ, an employee count in tCO2e) is `unit not convertible`; that is never the state of a second currency.

The base value (`number × factor`, numbers above) is used for display and for comparing the pairs of a same-period
set. The printed value and unit are never rewritten.

## Reserved keys

These 19 keys have an entry in the table of accepted families but no phrase in the metric list, so the matcher never
assigns them. A later list version adds the phrase when a page or a form gives one. Nine are count keys and ten are
currency keys.

- `employees_other`: the BRSR employee table has no "other" column.
- `board_meetings_held`: sentences only; a sentence gets no family.
- `shareholder_complaints`: the BRSR table labels its rows by stakeholder group and the metric sits in the column header.
- `regulatory_violations`: no form fixes a count row.
- `supplier_count`: no total in the reports read.
- `active_customers`: no row in the reports read.
- `new_customers_acquired`: no row in the reports read.
- `fulfillment_centers`: the BRSR prints plants split by national and international, with no total.
- `production_capacity`: segment rows only, no company total.
- `ceo_salary`: remuneration is printed in sentences or in rows named after the person.
- `ceo_bonus`: as `ceo_salary`.
- `ceo_stock_options`: as `ceo_salary`.
- `gross_profit`: Ind AS Schedule III has no gross profit line.
- `current_assets`: form read, row not printed: the Schedule III Division II balance sheet prints `Total Assets` and no `Total current assets` row; no page read gives the row.
- `current_liabilities`: form read, row not printed: the format prints `Total Equity and Liabilities` and no `Total current liabilities` row.
- `shareholders_equity`: form read, row not printed: the format prints `Equity Share capital`, `Other Equity` and no `Total equity` row.
- `total_debt`: `Borrowings` is printed under both non-current and current liabilities with no total, so the label cannot tell the two apart until header-joined labels exist.
- `free_cash_flow`: not an Ind AS line.
- `capital_expenditure`: no extracted label; amounts sit in sentences.

Deferred keys: `ghg_scope_3_category_1` and `ghg_scope_3_category_4` are not in the list. `category` stays an
exclusion word, which protects every total from a category row.

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
as printed and its source, and each pair of its points has a state (`docs/restatements.md`).

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
