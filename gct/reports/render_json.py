"""The JSON export (story 7.2): the dataset exactly as built, one file, keys in the dataset's own order."""
import json


def write(dataset, reports, folder, crops) -> dict:
    """Writes dataset.json into folder. The whole dataset whatever reports names (its reports share the documents,
    evidence and related claims lists); crops are not used. Streamed to the file, never held as one string."""
    with open(folder / "dataset.json", "x", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=1, allow_nan=False)
        f.write("\n")
    return {"files": ["dataset.json"], "notes": []}
