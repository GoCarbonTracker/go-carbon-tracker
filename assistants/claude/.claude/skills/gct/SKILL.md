---
name: gct
description: Drive the GCT command line in this workspace. Use when the user talks about GCT, a workspace, a sustainability report PDF, claims, reviews or exporting report data. Takes a PDF to an exported report with `gct` commands and stops where only the user may decide.
---

# Working in a GCT workspace

Read `CLAUDE.md` in this folder first. Its Never list and refusal rule apply to every step below. `commands.md` beside this file lists every command with its options and the keys of its JSON.

## The workflow

Each step is one command. Run them in this order and one at a time. Ids such as `1` are for a new workspace; use the ids the JSON gives you.

| Step | Command | Writes |
|---|---|---|
| Check the install | `gct --version` | no |
| Make the workspace (the user does this) | `gct workspace init PATH` | yes |
| Add the company | `gct company add NAME` | yes |
| Add the PDF | `gct doc add PATH --company NAME` | yes |
| Read, extract, link | `gct read`, then `gct extract`, then `gct link` | yes |
| Publish a data version | `gct publish build` | yes |
| List the claims of a document | `gct claims list --doc ID` | no |
| Read one claim's versions | `gct claims history CLAIM` | no |
| Record the user's review (next section) | `gct flag raise` or `gct review auditor` | yes |
| Publish again | `gct publish build` | yes |
| Look before writing | `gct report preview` | no, but it takes the lock |
| Write the report | `gct report all --format FORMATS` | yes |

`gct publish build` comes before any view or report. Every change to documents, claims or reviews needs another `gct publish build` before it shows in a report. The formats are `json`, `xlsx`, `csv`, `pdf` and `page`, separated by commas. The reports are `evidence-index`, `restatement-log`, `gap-report` and `all`.

These lines run in the test suite on a synthetic PDF and show the result each one should give. The first `gct report preview` is refused because nothing is published yet.

```gct-replay
gct workspace init <WORKSPACE>  # => 0 ok
gct company add <COMPANY>  # => 0 ok
gct doc add <PDF> --company <COMPANY>  # => 0 ok
gct doc add <WORKSPACE>/missing.pdf --company <COMPANY>  # => 4 partial
gct read  # => 0 ok
gct extract  # => 0 ok
gct link  # => 0 ok
gct report preview  # => 4 error
gct publish build  # => 0 ok
gct claims list --doc 1  # => 0 ok
gct claims history 1  # => 0 ok
gct contributor add <AS> --name <NAME>  # => 0 ok
gct flag raise 1 --version 1 --as <AS> --capacity <CAPACITY> --rationale <RATIONALE>  # => 0 ok
gct review auditor 1 --version 1 --outcome <OUTCOME> --scope <SCOPE> --conclusion <CONCLUSION> --as <AS> --capacity <CAPACITY> --evidence-doc 1 --evidence-page 1  # => 0 ok
gct publish build  # => 0 ok
gct report preview  # => 0 ok
gct report all --format json,csv  # => 0 ok
gct doc list --active  # => 0 ok
gct run list  # => 0 ok
gct doc delete 1  # => 4 plan
```

The `<AS>`, `<CAPACITY>` and similar words are the user's. Never fill them in yourself.

## Reviews

A review is the user's own statement, so ask for every word of it.

- The shortest record is `gct flag raise CLAIM --version V --as KEY --capacity TEXT --rationale TEXT`.
- The review the product names is `gct review auditor CLAIM --version V --outcome accepted|rejected|disputed --scope TEXT --conclusion TEXT --as KEY --capacity TEXT` with evidence: `--evidence-doc ID` and `--evidence-page N`, or `--evidence-note TEXT`. Without evidence it is refused.
- The contributor must exist first: `gct contributor add KEY --name NAME`.
- The version race: read `gct claims history CLAIM` first and pass the newest version id (the largest `versions[].id`) as `--version`. If the claim changed since, the command is refused. Code text: "is not claim {claim}'s newest version"
- Read the history again, show the user what changed, and ask again before you retry.

## Evidence

There are two honest forms.

1. Page numbers and boxes. `gct claims list --doc ID` and `gct claims history CLAIM` print the page and the box of every claim as text. Say them to the user.
2. The page image. No command prints an image. The viewer shows it. Start `gct serve --no-open --json` in the background and give the user the URL it prints. The URL carries a one-time token, so it is for the user and no one else. The command does not return, so if your shell cannot run it in the background, tell the user to run `gct serve --no-open --json` in their own terminal.

## Locks, upgrades and hidden rows

- One writer at a time. `gct report preview` and `gct package preview` write nothing but still take the workspace lock. If a command is refused with Code text: "Another gct command is using this workspace." wait for the other command to finish and run yours again. Never run two at once.
- Any command on an older workspace upgrades it first and records a `workspace upgrade` run. Report that run line to the user.
- An archived document is hidden from active listings, not gone. When `gct doc list --active` prints Code text: "hidden. Show every document with: gct doc list" relay that line and do not conclude that nothing else exists. The JSON keys are `hidden_by_archive` and `hidden_deleted`.
- `gct doc delete ID` prints a plan and a token and stops with status `plan`. Deleting clears the document from the workspace rows and cannot recall what you already read. After a deletion do not repeat that document's text.

## Common refusals

Quote these as the command prints them.

- No published version. Code text: "There is no published data version yet." The next action is to run `gct publish build`.
- Not in a workspace. Code text: "No workspace found." Start in the workspace folder or pass `--workspace PATH`.
- A workspace folder that is not empty. Code text: "{path} is not empty and is not a workspace." Run `gct workspace init` before you copy these files in.
- A crash. Code text: "Something unexpected went wrong." A log was written under `logs/`. Ask before you open it.

## Where results are

Writing a report puts a folder at `exports/<NAME>-v<N>-<stamp>-<mode>/` in the workspace. `<mode>` is `sanitised` or `complete`, so a complete export cannot be mistaken for a sanitised one. A sanitised export holds only rows from documents the user labelled shareable.

Everything here is demonstrated on a synthetic PDF. It is not an acceptance run on real documents.
