# Adjudication and reviewer flags

Two kinds of record a reviewer makes after looking at the figures: an adjudication says what the difference between
two figures is, and a reviewer flag raises a potential greenwashing concern about one figure. Both are insert-only
(migration 18, tables `adjudication` and `reviewer_flag`): a later decision is a new row, and every earlier row stays
listed. Neither opens a run or writes a run-log line.

## Candidates

An inconsistency candidate is a pair of `gct restate list` whose state is `unresolved conflict`, with both documents
active: two figures for one company, metric, boundary, unit family and period whose base values differ and that no
restatement record explains (`docs/restatements.md`). Nothing else is a candidate. Pairs in the states `same value`,
`restatement` and `not compared`, figures waiting in the review queue of `gct match review` (an unknown boundary or an
unusable unit) and expectations are not. A standalone and a consolidated figure never share a series, so they never
form a pair and never form a candidate.

A candidate is keyed on the two claim versions it compares. Its state is computed on read:

- `unreviewed candidate` until someone records an adjudication on exactly these two versions;
- otherwise the state of the newest such adjudication, whoever recorded it: `explained difference`, `extraction
  error`, `reviewer-confirmed issue` or `evidence not found`.

`gct adjudicate list [--company NAME] [--state STATE] [--claim CLAIM]` prints each candidate with both figures and
their sources, its state, and every adjudication on any version of its two claims, oldest first. A row on an earlier
version of either claim is marked `(on an earlier version)` and no longer decides the state. Below the candidates it
lists the adjudications whose two claims are not a candidate now, with the state of their pair now (for example
`restatement`). `--claim` keeps the candidates and adjudications naming that claim.

`gct adjudicate status [--company NAME]` counts, per company, the candidates and how many are in each state. Only an
adjudication on the candidate's current versions counts.

## Recording an adjudication

    gct adjudicate record A B --state STATE --procedure TEXT --as KEY --capacity TEXT --rationale TEXT
        [--counter-doc ID [--counter-page N]] [--counter-note TEXT] [--follow-up TEXT] [--closure-reason TEXT]

`A` and `B` are the two claims; the record names their newest versions. `--state` is one of:

- `explained-difference`: the difference has an explanation other than a restatement, such as a different scope
  note or rounding stated in the report. It needs counter-evidence: `--counter-doc` (an active document of any
  company, with `--counter-page` for a page of a PDF) or `--counter-note` (for evidence outside the workspace, or a
  sheet and cell of a spreadsheet, which has no pages).
- `extraction-error`: one of the figures was read wrongly. This does not change the claim; correct the figure with
  `gct correct CLAIM --value TEXT ...`, which the command names.
- `reviewer-confirmed-issue`: the reviewer confirms the two printed figures disagree.
- `evidence-not-found`: the reviewer looked for an explanation and found none. This is not a confirmed disclosure gap
  (`gct gap confirm`).

`--rationale` (why) and `--procedure` (how you checked) are required; follow-up and closure reason are optional.
The text is stored as typed (spacing collapsed) and always shown in quotes after the contributor's name,
organisation and capacity.

There is no restatement state. When the later figure restates the earlier one, record it with its evidence:
`gct restate record --original A --restated B --page N --quote TEXT ...`. The pair then becomes a `restatement`
and leaves the candidates; its earlier adjudications stay listed.

A record is refused, and nothing is written, for two claims that are not an unresolved conflict now, a claim, document
or contributor that does not exist, an archived or deleted document on either side or as counter-evidence, a page
outside the counter document, and empty text.

## A correction makes a new candidate

An adjudication holds for the two claim versions it names. When either figure is corrected or extracted again, the
pair has a new version and shows `unreviewed candidate` again; the earlier rows stay listed with `binds: false`.

## Reviewer flags

    gct flag raise CLAIM --version V --as KEY --capacity TEXT --rationale TEXT
    gct flag withdraw CLAIM --version V --as KEY --capacity TEXT --rationale TEXT
    gct flag list [--company NAME | --claim CLAIM]

A reviewer flag records a potential greenwashing concern about one claim version, with a rationale. `--version` must
be the claim's newest version, the claim must be current and its document active, so nobody flags a figure they did
not see. A contributor's position on a version is their newest row; their earlier rows stay listed as an earlier
position. A withdraw is refused when the contributor has no flag raised on that version. Every flag is shown as
"potential greenwashing concern raised by NAME (self-declared)". A correction leaves the flags on the old version,
marked `(on an earlier version)`.

## What GCT never does

- It never creates a flag or an adjudication. Only `gct flag raise` writes a flag and only `gct adjudicate record`
  writes an adjudication; adding documents, reading, extracting, matching and listing write neither.
- It never counts a candidate as a confirmed issue. `reviewer-confirmed issue` counts only adjudications on the
  candidate's current versions, and GCT's own text never calls a candidate a contradiction.
- It never certifies anything. Identities and capacities are self-declared: GCT does not check them and does not
  adopt any conclusion as its own. Every listing says so, and every record carries `self_declared: true` in JSON.

## Archive, deletion and the published version

Archiving the document of either claim takes its adjudications, and the flags on its claims, out of `adjudicate list`,
`adjudicate status` and the published version. `claims history` and `restate show` keep the row on the other claim and
mark the other side: the line ends `; other document archived` and the JSON record carries `other_document_state`.
The rows stay stored, are counted in the archive impact and `hidden_by_archive`, and come back on restore. An
adjudication citing an archived counter document stays listed, with the document's state.

Deleting a document clears the text (rationale, procedure, capacity, notes, follow-up, closure reason) of every
adjudication naming one of its claims or citing it, and of the flags on its claims, to `cleared with document N`;
the rows keep their ids, state, page and dates. A row citing it whose two claims survive stays listed with
`evidence deleted (document N, date)`. See `docs/deletion.md`.

`gct publish build` (projection schema 12) writes the tables `adjudication` and `reviewer_flag`, with `binds` (and
`latest` for flags) computed at build time, for rows whose claims' documents are active.
