# Troubleshooting

## When a command fails

A failed command prints two lines on stderr: `error:` says what went wrong and `next:` says one thing to do about
it. With `--json` it prints one object on stdout instead, `{"status": "error", "cause": ..., "next_action": ...}`
(see `docs/cli-json.md`, "error"). A mistyped or missing option is a usage error and has the same shape; its next
action names the command's `--help`. `--json` counts only before a `--`.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | done |
| 1 | something unexpected went wrong (see below) |
| 2 | a usage error: an option is missing, unknown or of the wrong form |
| 3 | something named does not exist: a workspace, company, document, run or adapter |
| 4 | refused: the command understood you and will not do it, for example a read-only workspace folder or another command holding the workspace |

`gct doc add` keeps going past a bad item and exits 4 when any item was refused or failed; with `--json` its
status is then `partial` and each item carries its own cause and next action.

## Unexpected errors

"Something unexpected went wrong." means gct hit a problem it has no message for. The full Python traceback is
written to `logs/error-<time>.log` inside the workspace, and the `next:` line names that file. When `logs/` cannot be
written, the line says so and no file is written. The log holds local paths and the exception's own text, which can
name your documents; only credentials (configured key values and `sk-`, `nvapi-` and `Bearer` tokens) are replaced.
Read it before you share it, or send the troubleshooting export below instead.

## Reading the run log

`gct run list` shows each run: when it started, the command, and its outcome. `gct run show N` shows one run's
events. `outcome` is how the run ended, so a `doc add` that refused one item still ends `ok`; `Failures` counts the
items it refused or that failed. The run's first note, `selection:`, records exactly what the command was given, so
it holds absolute paths and the names you chose. Treat `run show` output as private.

## The troubleshooting export

`gct troubleshoot export` writes a new folder, `exports/troubleshooting-<time>/`, with two files:
`troubleshooting.json` and `troubleshooting.txt` (the same content as `key.path: value` lines). Nothing else in the
workspace changes: the export records no run and takes no lock of its own, so it works while another command holds
the workspace. An older workspace is upgraded first, as `gct run list` does, and holds the workspace lock while it
upgrades.

The JSON holds these keys:

- `created_at`: when the export was made (UTC).
- `gct`: the gct version running, and the version installed as a package (`null` when it is not installed; a
  different value means the installed copy is out of date).
- `python`: the Python version and implementation.
- `os`: the operating system's name, release, machine type and platform string.
- `dependencies`: each library gct declares, with the version installed (`null` when missing).
- `workspace`: the schema version, every migration with the time it was applied, when the workspace was made and by
  which gct version, and the current published version.
- `counts`: companies, documents by state, pages by reading rung, and claims. Numbers only.
- `runs`: every run with its start time, command, gct version and outcome, and its events with their time, kind,
  stage, method, outcome and cost. An event's `message` is shown only for a failure or a failed finish, and only as
  the product sentence it was made from, with each detail as `{}` (for example "The file {} does not exist."), or
  the exception class name, or `withheld`.
- `error_logs`: the newest five error logs, each as its file name, the lines of gct code it passed through
  (`gct/<file>:<line> in <function>`), the number of other lines, and the exception class names. Source lines and
  exception text are left out.

What it never holds: document, company or contributor names, file names, folder paths, URLs, selection notes,
contributor text, claim values, ids, hashes, credentials, environment variables, the host name or the user name.
As a last step every text is checked again: the workspace folder becomes `<workspace>`, your home folder `<home>`,
and any text still holding an absolute path becomes `[path removed]`.

The export is not a package: a package (`docs/packages.md`) is a copy of the workspace for another gct user; the
troubleshooting export is for a maintainer and holds no workspace data. Read both files before you send them. The
address for reports to the maintainers is set when gct is published.

On Windows the workspace folder looks like `C:\gct\workspace` and the export like
`C:\gct\workspace\exports\troubleshooting-<time>\`; this has not been checked on Windows yet.
