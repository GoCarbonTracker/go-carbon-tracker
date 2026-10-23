"""gct report NAME --format F (story 7.2): one dataset, every format asked, one folder under exports/. The folder is
written under a temporary name and renamed once its files are checked, so a failed export leaves nothing behind and
no export is ever overwritten."""
import os
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from gct.reports import render_json, render_page, render_pdf, render_sheets
from gct.workspace.layout import REFUSED, GctError

# The only list of formats. Each write(dataset, reports, folder, crops) -> {"files": [...], "notes": [...]}; crops is
# {} unless the format is flagged, then the one dict crops.cut returned, shared by every flagged format.
FORMATS = {
    "json": {"write": render_json.write, "crops": False},
    "xlsx": {"write": render_sheets.write_xlsx, "crops": False},
    "csv": {"write": render_sheets.write_csv, "crops": False},
    "pdf": {"write": render_pdf.write, "crops": True},
    "page": {"write": render_page.write, "crops": True},
}
# NAME: the dataset reports its renderers receive.
REPORTS = {"evidence-index": ["evidence_index"], "restatement-log": ["restatement_log"], "gap-report": ["gap_report"],
           "all": ["evidence_index", "restatement_log", "gap_report"]}


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


@contextmanager
def folder(root, stem, files=None):
    """Yields exports/.incoming-<stem>/ (exports/ made if missing). On a normal exit: refuses unless the files under
    it are exactly files (when given; read on exit, subfolders included) and unless exports/<stem> is absent, then
    renames it to exports/<stem>. On any exception, a refusal of its own included, removes it and re-raises."""
    exports = Path(root) / "exports"
    exports.mkdir(exist_ok=True)
    tmp = exports / f".incoming-{stem}"
    tmp.mkdir()
    try:
        yield tmp
        if files is not None:
            got = {p.relative_to(tmp).as_posix() for p in tmp.rglob("*") if p.is_file()}
            if got != set(files):  # no file name in the cause: it reaches the run log, and a name can be private
                raise GctError(REFUSED, "An export's files did not match the files its formats listed. Nothing was"
                                        " exported.", "Report this to the GCT maintainers.")
        target = exports / stem
        if target.exists():  # os.rename onto an empty folder would succeed silently on POSIX
            raise GctError(REFUSED, f"An export named {stem} already exists; nothing was overwritten.",
                           "Run the command again.")
        os.rename(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def write(root, dataset, reports, formats, name) -> dict:
    """Writes exports/<name>-v<N>-<stamp>-<mode>/ with each format's files (in formats' order) and, with json, the
    schema file. Returns {folder, files, outputs: [{format, files, notes}]}. A renderer refuses by raising an exception
    with string attributes cause and next_step: the command then refuses with them."""
    stem = f"{name}-v{dataset['data_version']['version']}-{stamp()}-{dataset['mode']}"
    files, outputs = [], []
    with folder(root, stem, files) as tmp:
        crops = {}
        if any(FORMATS[f]["crops"] for f in formats):
            from gct.reports import crops as cutter  # 7.4's; never imported by a json-only export

            crops = cutter.cut(root, dataset)
        try:
            for f in formats:
                out = FORMATS[f]["write"](dataset, reports, tmp, crops if FORMATS[f]["crops"] else {})
                outputs.append({"format": f, "files": out["files"], "notes": out["notes"]})
                files += out["files"]
        except GctError:
            raise
        except Exception as e:
            cause, step = getattr(e, "cause", None), getattr(e, "next_step", None)
            if isinstance(cause, str) and isinstance(step, str):
                raise GctError(REFUSED, cause, step) from None
            raise
        if "json" in formats:
            schema = f"dataset-{dataset['dataset_schema']}.schema.json"
            (tmp / schema).write_bytes(resources.files("gct.reports").joinpath(schema).read_bytes())
            files.append(schema)
    return {"folder": Path(root) / "exports" / stem, "files": files, "outputs": outputs}
