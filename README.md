# gct

A workspace folder for company documents, kept as an append-only history. Early work: this is not released and not published anywhere.

## What works today

- `gct workspace init PATH` creates a workspace folder (SQLite database plus `files/`, `artifacts/`, `published/`, `exports/`, `logs/`).
- `gct company add NAME` and `gct company list`.
- `gct doc add FILE --company NAME` registers a PDF, XLSX or CSV (recognised from content). The original is stored once by SHA-256. Adding the same bytes again is reported as a duplicate. Adding a changed file under the same name creates a new version and keeps the old one.
- `gct doc list` and `gct doc show ID`.
- Documents default to the `private` label.
- `--json` on every command. Key names are in `docs/cli-json.md`.
- Every table except `schema_version` rejects updates and deletes.

## What does not exist yet

Reading document contents, extraction, review, reports, a viewer, a local service, archive and delete, published data versions, a run log.

## Setup

Needs Python 3.11 or newer.

```
python3.13 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

## Licence

MIT. See `LICENSE`. Copied code is logged in `ORIGINS.md`.
