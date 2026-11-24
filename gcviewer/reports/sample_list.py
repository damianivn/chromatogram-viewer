"""Sample-list spreadsheet exports; pandas is imported only on export."""
from pathlib import Path
from gcviewer.parsers.spl import parse_spl, match_rows_to_raw

_EXPORT_COLUMNS = [
    ("index", "Index"),
    ("file_name", "File Name"),
    ("method", "Acquisition Method"),
    ("detector", "Detector"),
    ("vial", "Vial"),
    ("sample_type", "Sample Type"),
    ("description", "Description"),
    ("inj_vol", "Injection Volume"),
    ("ms_file", "MS Method File"),
    ("inlet_file", "Inlet Method File"),
    ("raw_match", "Data file"),
]


def spl_to_df(meta, rows):
    """Convert parsed SPL rows to a pandas DataFrame for export."""
    import pandas as pd

    data = {label: [row.get(key, "") for row in rows]
            for key, label in _EXPORT_COLUMNS}
    df = pd.DataFrame(data)
    df.attrs["spl_meta"] = meta
    return df


def export_spl(filepath, output_path, data_folder=None, fmt=None):
    """
    Parse a sample list and write a spreadsheet.

    fmt: "xlsx" or "csv" (inferred from output_path extension if omitted).
    data_folder: optional path to match .raw directories (adds Matched .raw column).
    """
    path = Path(output_path)
    if fmt is None:
        fmt = path.suffix.lstrip(".").lower() or "xlsx"
    fmt = fmt.lower()

    meta, rows = parse_spl(filepath)
    if data_folder:
        match_rows_to_raw(rows, data_folder)
    else:
        for row in rows:
            row.setdefault("raw_match", "")

    df = spl_to_df(meta, rows)
    if fmt == "csv":
        df.to_csv(path, index=False)
    elif fmt in ("xlsx", "xls"):
        df.to_excel(path, index=False, sheet_name="Sample List")
    else:
        raise ValueError(f"Unsupported export format: {fmt}")

    return meta, rows, path


def sample_list_table_df(rows):
    """Build a display DataFrame for the in-app sample list sheet."""
    import pandas as pd

    records = []
    for row in rows:
        raw = row.get("raw_match") or ""
        records.append({
            "Index": row.get("index", ""),
            "File Name": row.get("file_name", ""),
            "Acquisition Method": row.get("method", ""),
            "Detector": row.get("detector", ""),
            "Vial": row.get("vial", ""),
            "Sample Type": row.get("sample_type", ""),
            "Description": row.get("description", ""),
            "Status": "Found" if raw else "No data file",
            "_raw": raw,
        })
    return pd.DataFrame(records)
