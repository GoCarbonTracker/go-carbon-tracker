# Packages

A package is a copy of a workspace for someone else, for example a client who reopens it, adds reports and processes
again. gct writes it fresh: a new workspace folder, the rows inserted one table at a time with their ids, the original
files and readings copied, and its own data version 1 built from its own rows. Both kinds are written by the same code;
they differ in which rows go in and how some columns are written.

A copy of the workspace folder is a complete copy of everything in it and is never a sanitised package.

## Commands

- `gct package preview [--complete] [--include CLASS,CLASS] [--json]` shows what the package would hold and prints
  the token `create` needs. It writes nothing.
- `gct package create --confirm TOKEN [--include CLASS,CLASS] [--json]` writes a sanitised package.
- `gct package create --complete --include-private --confirm TOKEN [--json]` writes a complete package.

Both take the workspace lock, because the plan reads the current data version under it.
The package is written to `exports/package-v<N>-<stamp>-<mode>/` in the workspace, where N is the data version it was
made from. It is written under `exports/.incoming-<name>/` first and renamed only after every check passed; a name that
already exists is refused, never overwritten. `--json` keys are in `docs/cli-json.md`.

## The preview and the token

The preview lists the data version it reads, each document that goes in (id, company, name, label), each document
left out with the reason in words ("private label", "same file as private document M", "deleted"), the row count per
table, the files and their bytes, how contributors and their text are written, and what never goes into a package. It
is for you only; none of it is written into the package.

The token is the first 12 hex digits of a hash of the data version's sha256, the mode, the inclusion classes and what
the package holds (documents, row counts per table, files). `create` works out the plan again under the lock and
refuses a token that does not match: another mode or class set, a newer data version, or any write that changes what
would go in (a run in complete mode, a new stage result of an included document). A write that changes nothing in
the package, such as an approval, a saved view or a run log line of a sanitised package, leaves the token valid.

Both commands refuse, in this order, with nothing written and no run opened: no data version, a version built by an
older gct, a deletion that did not finish, a data version that is out of date ("Build a fresh version with: gct
publish build"), and for `create` only a token that no longer matches, a sanitised package with no document, and an
existing folder name. When every document is private the preview says so, lists them and gives the relabel command,
and `create` refuses with that same command (`gct doc label ID --privacy shareable ...`).

## The sanitised package

Only rows whose every document is shareable go in, as `labels.ships` decides with the documents `labels.named` finds
for each row (the same decision reports use). So:

- private documents, a shareable document whose file equals a private document's, and deleted documents are left out,
  with every row that names one of them: claims, readings, stage results, reviews, adjudications, restatements,
  expectations and gap confirmations;
- an archived shareable document goes in, still archived;
- companies, contributors and runs go in only when a row that goes in points at them;
- each run that goes in keeps its row and the line that records how it finished, so `gct run list` shows the outcome;
  no other run log line goes in (they name local paths), so `gct run resume` and `retry` in the package have nothing
  to replay;
- approvals, saved views and stage results of downloads never go in;
- contributors are written as "Contributor 1", "Contributor 2" and so on, numbered over the records that go in, with
  keys `contributor-1`, `contributor-2` and no organisation; a spreadsheet's declared basis names that pseudonym;
- contributor text (capacity, rationale, scope, conclusion, notes, procedure and the like) is written as "withheld
  from the sanitised package", and stays empty where it was empty;
- a document's source address goes in only for an `http` or `https` address of a document whose availability is
  `public`;
- reviewer flags are left out.

`--include identity` keeps names, organisations and keys as recorded; `--include contributor_text` keeps the
contributor text; `--include flags` keeps reviewer flags. Each restores only its own part.

A recipient who records with `--as contributor-1` adds a version of that pseudonymous contributor. Recipients should
add their own contributor with `gct contributor add` and use their own key.

Ids are kept as in the source, because stage results are keyed by them. Gaps in the ids of a sanitised package show
roughly how many rows were left out.

## The complete package

`--complete` needs `--include-private`: it holds every document, private ones included, every row of every table
(run log and download results included) apart from approvals, with contributor names and text, flags and saved
views. A deleted document goes in as its record of deletion, without its file. The authorisation is recorded in the
source workspace's run log: a `package create` run with the mode, classes, token and folder, and a note naming the
private documents. That run is not in the package it writes.

In both kinds every text value passes the credential scrubber before it is written, and neither holds `published/`
files of the source, page images, `logs/` or `exports/`.

## The manifest

`gct-package.json` at the package root records `package_schema`, `mode`, `include`, `created_at`, `gct_version`,
`data_version` (the package's own version 1) and `source_data_version` (the version it was made from); in a
sanitised package both without `history_mark` or `labels_mark`. Its `text` says what the folder held when gct wrote
it, with version 1's sha256. Anything added to the folder later is not covered: after the recipient adds a document
and builds a version, the folder is theirs, and no gct command calls it a sanitised package. Only `gct package create`
uses those words, of the folder it has just written.

## What gct cannot recall

Copies already exported or shared, including files in exports/, cannot be recalled by GCT. A deletion in the source
after a package was made does not reach the package.
