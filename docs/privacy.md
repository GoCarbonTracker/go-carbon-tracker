# Privacy labels and sanitised reports

Every document has a privacy label and an availability. Reports use the label to decide which rows they hold. A
sanitised output, the default, holds only rows built from shareable documents. A complete output holds every row
of the selection, each with its label.

## Labels and availability

- The label is `private` or `shareable`. The availability is `public`, `internal` or `unknown`.
- At `gct doc add` the availability is `unknown` unless `--availability` gives it. The label is `shareable` only
  for `--kind report` with `--availability public`, and `private` otherwise. `--privacy` overrides the label, and
  the registered line prints the label used.
- A file's name, type, folder or web address never sets either value.
- Documents registered before labels existed keep their stored label, with availability `unknown`.

## Change records

`gct doc label ID [--privacy L] [--availability A] --as KEY --capacity TEXT --rationale TEXT` stores one change
record: the label before and after, who made it, in what capacity and why. Records are never overwritten. A
duplicate `doc add` that asks for another label says it was not applied and names `gct doc label`. A new document
whose file another document holds under the other label prints a warning naming that document.

## The label a report uses

The stored label is the newest change record, else the label given at intake. A report uses the effective label,
which applies three rules to it, the most restrictive winning:

1. A document that is not in the published version (archived, deleted, or registered after the build) is private.
2. Otherwise the more restrictive of the label stored in the version and the label stored now, so relabelling a
   document `private` after a build takes effect at once. Relabelling it `shareable` takes effect at the next
   `gct publish build`.
3. A document is private while any document that is not deleted holds the same file under a private label.

## What a row inherits

A row is private when any document it names is private. A row names its own document and the documents its
records point at:

- a claim, its evidence, its basis wording and its correction: the claim's document;
- a company confirmation or auditor review: the claim's document and the evidence document it cites;
- a comparison pair, a restatement record and an unpaired restatement record: both claims' documents and the
  restatement's evidence document;
- an adjudication: both claims' documents and its counter document;
- an expectation: every declared document, archived ones included, and the documents its gap confirmation checked;
- a needs-renewed-review entry: the documents of the record it points to and of the other claim it names.

A record whose document the version cannot trace counts as private.

## Modes

- **Sanitised** (the default). Rows are left out when they name a private document. Archived and deleted
  documents are neither named nor counted. Reviewer flags are left out. Every contributor name becomes "Contributor
  N", numbered within one output by record kind and record id, counting only the records that stay. Organisation,
  capacity and contributor-typed text (scope, conclusion, rationale, procedure, notes, follow-up, closure reason,
  and a correction's corrector, organisation, capacity and rationale) are withheld: the key stays, its value is
  `null` and the row's `withheld` list names it. `--include identity,contributor_text,flags` keeps the named
  classes. A sanitised output carries the line "Private content is excluded from this output."
- **Complete** (`--complete`). Every row of the selection, with its label, and every record.

`gct report preview` shows, for the local user only, the rows a report would hold and, for a sanitised output, the
rows it leaves out, each counted once under its first cause. When every document in the selection is private it
names each one and gives the relabel command. The preview writes nothing: it takes the workspace lock, reads
`workspace.db` read-only and refuses a workspace that needs an upgrade.

## Computed values

Every computed value in a sanitised output is worked out again from the rows that stay: the review summary, the
disagreement line, the latest position of each contributor, the comparison state of a pair, the adjudication
state shown, the needs-renewed-review entries, a claim's match state and series, and every count. GCT builds one
in-memory copy of the published version without the left-out rows and runs the selection and every calculation on
it. A sanitised output therefore reads as if the private records did not exist. A filter on review or comparison
state selects as if they did not exist too. The cost: a reader may see "company accepted" on a claim whose private
dispute is not shown.

## What never leaves

No output carries the run log or its lines, selection notes, approvals and spend, a document's source address, the
workspace path, error logs, contributor keys, the full text of readings, the list of documents a gap confirmation
checked, or the SHA-256 of a document that does not ship. Every string passes the credential scrubber in both
modes.

## Sequential ids

Document, claim and record ids are kept as they are in sanitised outputs. Because they are sequential, a gap in
them shows roughly how many records exist that the output does not hold. This is accepted for now; renumbering ids
in sanitised outputs was considered and not done.

## What GCT does not do

- It does not decide what is private. A label is what a person stored; GCT only applies it.
- It does not read a document to find personal or confidential content. A shareable document's text ships as
  printed.
- It does not check a contributor's typed text for names. `--include contributor_text` ships it as typed.
- It does not hide that a document exists from someone who holds the workspace; labels govern outputs only.
