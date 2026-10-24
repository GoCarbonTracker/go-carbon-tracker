# Setup

This page takes you from a computer with nothing set up to a first workspace, a first look at the evidence in the viewer and a first report. It installs GCT without any model. It has not yet been followed start to finish on a clean computer: its first-run commands are checked by a test on a synthetic report, and the install steps are written, not run. The version it is written for is Python 3.13 on macOS with Apple Silicon. Python 3.11 and 3.12 are what the package allows and have not been run, and Windows is described in its own section.

## What you need

| | No assistant (the viewer and the command line) | Claude |
|---|---|---|
| Python | Python 3.11 or newer | the same |
| A browser | for `gct serve` | the same |
| Disk | what your documents take, plus a little for the history GCT keeps | the same |
| Network | to install (path A below), never by the no-model workflow after that | also whatever Claude Code needs |
| Anything else | no | Claude Code and the files copied in under "Using Claude" |

Codex and agy are not set up in this version.

Nothing here needs Node, npm, Docker or a database server.

A model is not needed either. GCT reads PDF pages with the text layer they carry (see "What the no-model install reads"). How well those fixed reading rules find figures was measured once, against a private gold set of 170 figures from the reports of two real companies (scorer version 1, gold commit 3985743): 0 of 80 in the text group, 0 of 50 in the table group and 0 of 40 in the figure group were Found, where Found means value, unit, metric, entity, boundary and period all match. The release plan's accuracy gate (G2) sets a target of 90% Found in each group, so the no-model baseline fails it. A model file, if you ever write one, is described in [docs/models.md](models.md).

## Getting Python 3.11 or newer

Check what you have:

```
python3 --version
```

Stock macOS ships an older Python (3.9), which is too old. On macOS install a newer one with Homebrew (`brew install python@3.13`) or with the installer from python.org. On Windows use the installer from python.org. These are instructions; nothing on this page runs them for you.

## Getting the code

Use the folder or archive you were given, unpacked anywhere you like, or run `git clone` on the address you were given. This page does not name an address. The steps below start inside that folder, the one that holds `pyproject.toml`.

## Install (user form)

This installs a copy of GCT into a new virtual environment, not linked to the code folder. Path A is the networked install: pip fetches what GCT needs. `python3` must be 3.11 or newer (check with `python3 --version`). Python 3.13 on Apple Silicon macOS is the only combination that has been run; 3.11 and 3.12 are allowed by the package and have not been run.

macOS:

```
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

Windows: not tested; the steps follow the macOS ones, and `py -3` must be 3.11 or newer too (check with `py -3 --version`).

```
py -3 -m venv .venv
.venv\Scripts\activate
pip install .
```

Check it. `gct --version` prints the version. Then change to any folder outside the code folder and ask Python where it found GCT:

```
gct --version
python -c "import gct; print(gct.__file__)"
```

The second line must name a `site-packages` folder inside your `.venv`. If it names the code folder, the install is linked to the code and is not the user form.

## Install (contributor form)

For someone who changes GCT or wants to run its tests. The install is linked to the code folder, so edits show at once. The wheel test needs `setuptools` 77 or newer, which a fresh environment does not carry:

```
pip install -e '.[dev]'
pip install 'setuptools>=77'
pytest
```

Some tests skip when a tool is absent, and the summary says so with `pytest -rs`: the viewer tests skip when the viewer's build tools or a Chrome browser are absent. A skip that mentions setuptools, a missing `gct` script or git means the environment is not complete. Rebuilding the viewer, only if you change its source, needs Node: see [viewer/README.md](../viewer/README.md).

## Offline install from a wheelhouse (path B)

Path B installs without a network from a folder of ready-made packages, a wheelhouse. It needs a wheelhouse built once with Varun's approval; this page does not build one and runs no download. A wheelhouse fits the Python version and the kind of computer it was built for, and the `SOURCE.txt` beside it says which. It must also hold `setuptools` 77 or newer, which building GCT itself needs. Then, in the new environment:

```
pip install --no-index --find-links WHEELHOUSE .
```

Replace `WHEELHOUSE` with the folder. Path A is the same install with a network; the checks under "Install (user form)" apply to both.

## What gets installed

Pip works out the versions from `pyproject.toml`. Runtime packages:

- `fastapi`: the local server behind `gct serve`.
- `uvicorn`: runs that server on your own computer.
- `pdfplumber`: reads the text, words and ruled tables of PDF pages.
- `pypdfium2`: draws PDF pages as pictures for the viewer and for evidence.
- `openpyxl`: writes the spreadsheet form of a report.
- `reportlab`: writes the PDF form of a report.
- `pillow`: cuts the pictures of cited figures out of page images.

Contributor form only:

- `pytest`: the test runner.
- `jsonschema`: checks exported report data against its published schema.

## First run

If you have no report to try, make a synthetic one from the test fixture. This needs the contributor form and runs in the code folder, because the tests are not part of the installed copy. It writes `test-workspaces/sample.pdf`, a one-page table with one made-up figure (git ignores the `test-workspaces` folder):

```
python -c "import os, sys; sys.path.insert(0, 'tests'); from conftest import make_pdf; from gate_fixture import page, SCOPE_1; os.makedirs('test-workspaces', exist_ok=True); open('test-workspaces/sample.pdf', 'wb').write(make_pdf([page([[SCOPE_1, 'tCO2e', '100']], ['FY 2024-25'])]))"
```

Use that file as `<PDF>` below and a new folder inside `test-workspaces` as `<WORKSPACE>`. To see a whole workspace without typing the lines, `python -m tests.gate_fixture FOLDER` builds one in FOLDER (new or empty): two made-up companies, several made-up reports, reviews and a published version, with no real report in it. Open it with `gct serve --workspace FOLDER`.

Each line below is one command. Replace `<WORKSPACE>` with the folder to create, `<PDF>` with a PDF report and `<COMPANY>` with one word naming the company. After `workspace init`, either run the later lines from inside the workspace folder or set `GCT_WORKSPACE` to it. The numbers 1 and 1 in `flag raise` are the claim and version that `claims list` printed for the first row of your report; use your own. `flag raise` needs the contributor named by `--as` to be registered first, which is what the `contributor add` line does; with an unregistered key it stops with exit code 3 and a next step that gives the `contributor add` line.

```gct-replay
gct workspace init <WORKSPACE>  # => 0
gct company add <COMPANY>  # => 0 ok
gct doc add <PDF> --company <COMPANY>  # => 0 ok
gct read  # => 0 ok
gct extract  # => 0 ok
gct publish build  # => 0 ok
gct claims list --doc 1  # => 0 ok
gct contributor add me --name Me  # => 0 ok
gct flag raise 1 --version 1 --as me --capacity analyst --rationale needs-a-second-look  # => 0 ok
gct report all --format json  # => 0 ok
```

Then look at the evidence: `gct serve` prints a web address and opens your browser. Add `--no-open` to keep the browser closed and open the printed address yourself, or `--port 8766` to use another port. The address works on this computer only and is new each time. Press Ctrl-C to stop.

Things the lines above do not say:

- A document added with `doc add` is `private` by default. The report step writes a sanitised report, which is designed to leave out the rows of a private document, so your first report is empty until you decide a document can be shared and relabel it `shareable` (`gct doc label --help` shows how). GCT then says so in plain words and still exits 0. Sanitised output has known limits, listed under [Status](../README.md#status) and in [docs/privacy.md](privacy.md) under "What never leaves"; read it before you share it.
- This is experimental software: the privacy acceptance of the sharing features FAILED, the release's final acceptance is INCOMPLETE, and the leakage check on exports made from real data left 15 images unread, so a sanitised output or package is not verified to be free of private content.
- Do not add `--complete` unless you want the private content in the export folder for your own use. It writes private text and figures into `exports/`.
- `report` and `package preview` take the writer lock. If another gct command is running on the workspace they stop with the third message under "When something fails" instead of waiting.
- `publish build` comes before views and reports. A view or report reads the published version, so run it again after you add or change documents. In the lines above, `contributor add` and `flag raise` come after the build, so the report prints that the workspace has changed since data version 1 was built. That is expected here; `gct publish build` followed by the report again reads the latest state.
- Nothing above sends anything anywhere.

## Using Claude

This is the Claude configuration; the no-assistant path above does not need it. The order matters: make the workspace first, with the environment active, then copy the Claude files into it, then start Claude Code inside the workspace.

```
gct workspace init WORKSPACE
cp -R assistants/claude/. WORKSPACE/
cd WORKSPACE
```

Copying the files into a folder before `workspace init` makes `workspace init` refuse it, because the folder is no longer empty.

## What the no-model install reads

GCT reads the text, the words with their positions and the ruled tables of PDF pages with pdfplumber, the first and only reading step in this version. It does not read scanned pages: a page with no text layer is counted as a page without text and stays empty. It does not read charts or images. Nothing is sent anywhere. A configured model changes none of this in this version; [docs/models.md](models.md) says what the file does and does not do.

## Moving a workspace to another computer

A workspace is one folder. To move it, copy the whole folder while no gct command is running on it. On the other computer install the same or a newer gct, then run `gct workspace status` before anything else.

What comes with the folder: the documents, their history, the published versions, the run log (with the file paths of the old computer in it), the spending limit and the transfer approvals. What does not: the model file (`models.toml`), environment variables and keys, the address of the viewer (new each time you run `gct serve`), and anything you exported and handed on.

The folder holds private documents. To share work outside the team, make a sanitised package ([docs/packages.md](packages.md)) instead of copying the folder, and read the package before you share it (see [Status](../README.md#status)). A copy made before a document was permanently deleted still holds that document; GCT cannot recall it ([docs/deletion.md](deletion.md)).

An older gct refuses a newer workspace, and a newer gct upgrades an older one and records the upgrade in the run log ([docs/migrations.md](migrations.md)).

## Windows

Windows: not tested. The steps above show the Windows form of the virtual environment commands and nothing else was changed for Windows. The default model file is under your user profile, in `.config\gct\models.toml`. The lock that stops two commands from writing to a workspace at once has a Windows branch that nobody has run yet. Acceptance on Windows comes after this release.

## When something fails

A failed command prints what went wrong and one thing to do. These are the messages this page expects, quoted from the program:

- Code text: "No workspace found."
- Code text: "{path} is not empty and is not a workspace."
- Code text: "Another gct command is using this workspace."
- Code text: "This workspace was made by a newer version of gct than the one installed."

The first means the command could not find a workspace: point at one with `--workspace`, set `GCT_WORKSPACE`, or run it from inside the workspace folder. The second means the folder you gave to `workspace init` already holds something that is not a workspace. The third means wait for the other command and try again. The fourth means install the newer gct. Everything else is in [docs/troubleshooting.md](troubleshooting.md).
