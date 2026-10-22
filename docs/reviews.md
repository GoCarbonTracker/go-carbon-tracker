# Company confirmations and auditor reviews

A claim can carry two kinds of conclusion from people outside GCT, kept in two separate ledgers:

- a **company confirmation**: someone speaking for the company says what they make of one version of a figure
  (`gct review company`);
- an **auditor review**: an auditor, or anyone acting as one, says the same in their own words (`gct review auditor`).

Both are records of what a contributor said. GCT does not check who they are, does not decide whether they are right,
and does not adopt either conclusion as its own. Every command that lists these entries says so once:

> Identities and capacities are self-declared. GCT does not check them and does not adopt any conclusion as its own.

In JSON every entry has `self_declared: true`.

## Recording an entry

```
gct review company CLAIM --version V --outcome accepted|rejected|disputed --scope TEXT --conclusion TEXT
    --as KEY --capacity TEXT (--evidence-doc ID [--evidence-page N] | --evidence-note TEXT) [--date YYYY-MM-DD]
gct review auditor CLAIM ...the same options
```

- `--version` is required and must be the claim's newest version (see it with `gct claims history CLAIM`), so nobody
  confirms a figure they did not see. The claim must be `current` and its document active (not archived, not
  deleted).
- `--outcome` is read by gct: `accepted`, `rejected` or `disputed`. `--conclusion` is your own words, stored and
  shown exactly as typed, including words such as "verified" or "assured": they are attributed to you, never to GCT.
  `--scope` says what you looked at; `--capacity` the capacity you act in, as you describe it. None may be empty.
- `--date` is the day of your review (default today, never in the future). It is kept apart from the time the entry
  was stored.
- Evidence: a document in the workspace (`--evidence-doc`, active when you record) with an optional page of a PDF
  (`--evidence-page`, within its page count), a free-text `--evidence-note` (evidence outside the workspace, or a
  sheet and cell of a spreadsheet), or both. A spreadsheet has no pages. The evidence document may belong to another
  company; its company is printed with it.
- `--as` names a contributor (`gct contributor add`). The entry keeps the contributor version of that moment, so a
  later `gct contributor edit` does not change the name shown on it.
- The claim's company is read from the claim and printed apart from the contributor's own organisation; neither is
  copied into the other.
- Recording opens no run and writes nothing to the run log. A refused entry writes nothing.

Adding a document, mapping a spreadsheet and every stage (`read`, `extract`, `link`, `infer`, `match`) write no
entry: uploading evidence never confirms a claim.

## What is kept and how it is read

- **Nothing is overwritten.** A later entry is a new row; every earlier one, rejected and disputed ones included,
  stays listed. There is no edit and no withdraw: to change your position, record again.
- **Latest per contributor.** On one claim version, a contributor's position in one ledger is their newest entry
  (`latest: true`); their earlier entries stay listed with `latest: false`.
- **Binding.** An entry binds while the version it names is the claim's newest version. After `gct correct` (or a
  new extraction), earlier entries stay under the earlier version with `binds: false`, and the new version starts with
  no entries.
- **The two ledgers are independent.** An entry is written in one ledger only, and nothing in one ledger is read to
  decide the other.
- **Disagreement.** Each ledger's position on a version is the set of its contributors' latest outcomes. When both
  ledgers have a position and the two sets differ, the version shows
  `company confirmation and auditor review disagree on version V: company accepted; auditor disputed`
  (`disagreement: {"company": [...], "auditor": [...]}` in JSON, else null). It is computed each time, never stored,
  and neither ledger overrides the other. Two contributors of one ledger who differ are not a disagreement in this
  sense; both entries are listed.

## Reading the entries

- `gct review list CLAIM` lists every version of the claim, oldest first, each with its company confirmations and
  auditor reviews as two lists and the disagreement, if any.
- `gct claims history CLAIM` adds `company_confirmations`, `auditor_reviews` and `disagreement` to every version, so
  the local service's claim history carries them too.
- Each entry reads `company confirmation #ID OUTCOME on DATE by NAME (ORGANISATION), capacity "...", scope "...":
  "conclusion"; evidence ...`.
- `evidence_state` is the evidence document's state now (`registered`, `restored`, `archived` or `deleted`; null for
  a note only).
- `gct publish build` (`projection_schema` 12) writes both ledgers as `review_company` and `review_auditor`, with
  `latest`, `binds` and `evidence_state`, for the claims of active documents.

## Archive and deletion

- Archiving the claim's document keeps its entries stored; they leave the published version and are counted in the
  archive summary and in `hidden_by_archive`. A restore brings them back unchanged. Recording on an archived
  document's claim, or citing an archived document, is refused. An entry that cites a document archived after it was
  recorded stays listed and published, with `evidence_state` `archived`.
- Deleting the claim's document, or the evidence document an entry cites, keeps the entry with its ids, contributor,
  outcome, page and dates; its capacity, scope, conclusion and note read `cleared with document N`, and every listing
  adds `evidence deleted (document N, date)`. It leaves the published versions on disk; an entry on a surviving claim
  is published again by the next build with its text cleared. See `docs/deletion.md`.

## What GCT does not do

GCT does not authenticate contributors, check their capacity or affiliation, read the cited evidence to see whether it supports the conclusion (it only
checks that the document is active and the page is in it), weigh
one entry against another, or present any entry as its own certification or assurance. Settling a disagreement is
not part of this step.
