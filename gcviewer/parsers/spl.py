"""
Perkin-Elmer Sample List (.SPL) Parser
=======================================
Reads TotalChrom / TurboMass GC-MS acquisition sample lists (Jet 3 database).
No Streamlit dependency — can be used standalone.

Format:
    Magic:  "Standard Jet DB" at offset 0x004 (Microsoft Jet 3.x)
    Table:  ANALYSIS (one row per injection)
    Link:   FILE_NAME column -> {name}.raw directory on disk

Note:
    PE sample lists use an old Jet 3 database (same .SPL extension as Waters
    MassLynx, but a different vendor). We read them with the pure-Python
    access-parser library, with a compatibility patch and PE-specific field
    mapping (the generic parser mis-aligns several columns in this format).
"""

import re
import struct
from functools import partial
from pathlib import Path

JET_MAGIC = b"Standard Jet DB"
TABLE_NAME = "ANALYSIS"
VENDOR = "totalchrom_turbomass"
_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,62}$")
_CC_PREFIX_RE = re.compile(r"^(.+_CC)\d+$", re.IGNORECASE)

_ACCESS_PATCHED = False


# Low-level helpers
def _patch_access_parser():
    """Patch access-parser to tolerate empty float fields in Jet 3 SPL rows."""
    global _ACCESS_PATCHED
    if _ACCESS_PATCHED:
        return
    import access_parser.utils as apu
    import access_parser.access_parser as apmod

    _orig = apu.parse_type

    def _safe_parse_type(data_type, buffer, length=None, version=3, props=None):
        if data_type in (apu.TYPE_FLOAT64, apu.TYPE_FLOAT32):
            need = 8 if data_type == apu.TYPE_FLOAT64 else 4
            if len(buffer) < need:
                return None
        try:
            return _orig(data_type, buffer, length, version, props)
        except struct.error:
            return None

    apu.parse_type = _safe_parse_type
    apmod.parse_type = _safe_parse_type
    _ACCESS_PATCHED = True


def _clean_str(value):
    if value is None:
        return ""
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return str(value)
    text = str(value).strip()
    if not text or not text.isascii():
        return ""
    return text


def _read_overflow_record(table, record_pointer):
    """Read one Jet record, stripping flags from BOTH bounding row offsets.

    access-parser strips the deleted flag from the target start, but can leave
    0x4000 (a forwarding pointer) on the preceding row's offset. Python then
    slices to the page end and includes neighbouring records. Their trailer is
    mistaken for this row's column map. Keep this correction local to the SPL
    table instance, without modifying the installed dependency or its catalog.
    """
    from access_parser.parsing_primitives import parse_data_page_header
    row = record_pointer & 0xff
    page = table._data_pages.get((record_pointer >> 8) * table.page_size)
    if page is None:
        raise ValueError("Sample list refers to an unavailable record page; no incomplete list was returned.")
    header = parse_data_page_header(page, version=table.version)
    offsets = header.record_offsets
    if row >= len(offsets):
        raise ValueError("Sample list refers to an invalid record number; no incomplete list was returned.")
    start = offsets[row] & 0x0fff
    end = (offsets[row - 1] & 0x0fff) if row else len(page)
    header_end = (10 if table.version == 3 else 14) + 2 * len(offsets)
    if not header_end <= start < end <= len(page):
        raise ValueError("Sample-list record boundaries are invalid; no incomplete list was returned.")
    return page[start:end]


def _normalize_file_name(name):
    """Normalize FILE_NAME values for .raw directory matching."""
    name = _clean_str(name)
    if not name:
        return ""

    # Parser artifacts: ADTP_CC7-2 -> ADTP_CC7_2, ADTP_ISK6_2-2 -> ADTP_ISK6_2
    m = re.match(r"^(.+_\d+)-\d+$", name)
    if m:
        return m.group(1)
    if re.match(r"^[A-Za-z0-9].+-\d+$", name):
        stem, suffix = name.rsplit("-", 1)
        if suffix.isdigit():
            return f"{stem}_{suffix}"

    return name


def _looks_like_file_name(name):
    name = _normalize_file_name(name)
    if not name or len(name) < 2 or name.isdigit():
        return False
    return bool(_FILE_NAME_RE.match(name))


def _cc_prefix_from_name(name):
    m = _CC_PREFIX_RE.match(_normalize_file_name(name))
    return m.group(1) if m else None


def _extract_file_name(raw, cc_prefix=None):
    """Acquisition .raw stem from FILE_TEXT; infer Cont Calib names when empty."""
    for key in ("FILE_TEXT", "FILE_NAME"):
        candidate = _normalize_file_name(raw.get(key))
        if _looks_like_file_name(candidate):
            return candidate

    if _clean_str(raw.get("ID")) == "Cont Calib":
        job = _clean_str(raw.get("JOB"))
        if job.isdigit() and cc_prefix:
            inferred = f"{cc_prefix}{job}"
            if _looks_like_file_name(inferred):
                return inferred

    return ""


def _row_is_garbage(raw, cc_prefix=None):
    job = _clean_str(raw.get("JOB"))
    if job and not job.isdigit():
        return True
    file_name = _extract_file_name(raw, cc_prefix=cc_prefix)
    return not file_name


def _normalize_row(raw, source_index, cc_prefix=None):
    if _row_is_garbage(raw, cc_prefix=cc_prefix):
        return None

    file_name = _extract_file_name(raw, cc_prefix=cc_prefix)
    method = _clean_str(raw.get("MS_TUNE_FILE"))
    detector = _clean_str(raw.get("AUTO_FILE"))
    vial = _clean_str(raw.get("JOB"))
    sample_type = _clean_str(raw.get("ID"))
    description = _clean_str(raw.get("CONC_A"))

    inj_vol = raw.get("INJ_VOL")
    if not inj_vol:
        inj_vol = raw.get("STOCK_DIL")

    # Retain a valid literal filename in addition to the legacy normalized name.
    # Real PE acquisitions can contain distinct A_2, A-2 and A_2-2 directories.
    # Consumers that need exact acquisition identity must not collapse those.
    source_file_name = next((text for key in ("FILE_TEXT", "FILE_NAME")
                             if (text := _clean_str(raw.get(key)))
                             and _FILE_NAME_RE.fullmatch(text)
                             and _looks_like_file_name(text)), "")

    return {
        "source_index": source_index,
        "file_name": file_name,
        "source_file_name": source_file_name,
        "method": method,
        "detector": detector,
        "vial": vial,
        "sample_type": sample_type,
        "description": description,
        "sample_location": vial or _clean_str(raw.get("SAMPLE_LOCATION")),
        "inj_vol": inj_vol,
        "ms_file": _clean_str(raw.get("MS_FILE")),
        "inlet_file": _clean_str(raw.get("INLET_FILE")),
    }


def _cont_calib_prefix(raw_rows):
    """Derive a CC naming prefix (e.g. ADTP_CC) from sibling rows."""
    for raw in raw_rows:
        for key in ("FILE_TEXT", "FILE_NAME"):
            prefix = _cc_prefix_from_name(raw.get(key))
            if prefix:
                return prefix
    return None


# Public API
def is_spl_file(filepath):
    """Check if a file is a Jet DB GC-MS sample list (.SPL)."""
    try:
        p = Path(filepath)
        if not p.is_file() or p.stat().st_size < 0x200:
            return False
        with open(p, "rb") as f:
            f.seek(4)
            return f.read(len(JET_MAGIC)) == JET_MAGIC
    except Exception:
        return False


def parse_spl(filepath):
    """
    Parse a TotalChrom / TurboMass .SPL sample list.

    Returns (meta, rows):
        meta: dict with spl_path, table, vendor, row_count, source_rows
        rows: list of dicts with file_name, method, vial, description, ...
    """
    path = Path(filepath)
    if not is_spl_file(path):
        raise ValueError(
            f"Not a Jet DB sample list (.SPL header missing): {path}")

    _patch_access_parser()
    from access_parser import AccessParser

    db = AccessParser(str(path))
    if TABLE_NAME not in db.catalog:
        tables = ", ".join(sorted(db.catalog))
        raise ValueError(f"No {TABLE_NAME} table in sample list (found: {tables})")

    reader = db.get_table(TABLE_NAME)
    reader._get_overflow_record = partial(_read_overflow_record, reader)
    table = reader.parse()
    if not table:
        raise ValueError(f"{TABLE_NAME} table is empty")

    source_rows = len(next(iter(table.values())))
    raw_rows = [{col: table[col][i] for col in table} for i in range(source_rows)]
    cc_prefix = _cont_calib_prefix(raw_rows)

    rows = []
    skipped_rows = []
    for i, raw in enumerate(raw_rows):
        row = _normalize_row(raw, i, cc_prefix=cc_prefix)
        if row:
            # Preserve source record positions even when a blank or unreadable
            # record is omitted. Vial numbers are independent sample metadata.
            row["index"] = i + 1
            rows.append(row)
        else:
            skipped_rows.append({"index": i + 1, "source_index": i,
                                 "reason": "No supported filename or invalid vial field; blank or unreadable sample record."})

    if not rows:
        raise ValueError("No sample rows found in SPL file")

    meta = {
        "spl_path": str(path),
        "file_name": path.name,
        "table": TABLE_NAME,
        "vendor": VENDOR,
        "row_count": len(rows),
        "source_rows": source_rows,
        "skipped_rows": skipped_rows,
        "warnings": ([f"{len(skipped_rows)} blank or unreadable sample-list record(s) omitted: "
                      + ", ".join(str(r["index"]) for r in skipped_rows)
                      + ". Remaining list-row numbers retain their source positions."] if skipped_rows else []),
    }
    return meta, rows


def spl_raw_name(row):
    """Return the .raw directory/file name for a parsed SPL row."""
    return f"{row['file_name']}.raw"


def match_rows_to_raw(rows, data_folder, finder_fn=None):
    """
    Attach raw_match to each row by looking up FILE_NAME in data_folder.

    finder_fn(folder) should return available .raw names (default: GC-MS dirs).
    Returns the same rows list (mutated in place) for convenience.
    """
    if finder_fn is None:
        from gcviewer.parsers.waters import find_raw_dirs
        finder_fn = find_raw_dirs

    available = {name.lower(): name for name in finder_fn(data_folder)}
    for row in rows:
        target = spl_raw_name(row).lower()
        row["raw_match"] = available.get(target)
    return rows


# Export helpers
