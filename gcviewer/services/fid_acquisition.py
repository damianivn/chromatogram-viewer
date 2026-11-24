"""FID acquisition boundary: original counts, calibrated traces and safe records."""
from dataclasses import asdict
from datetime import datetime
import hashlib
from pathlib import Path

import numpy as np

from gcviewer.data_models.totalchrom import RawHeader, RawRun
from gcviewer.revisions import TOTALCHROM_VERSION, TOTALCHROM_READER_REVISION
from gcviewer.data_models.acquisition import Trace

READER_ID = TOTALCHROM_READER_REVISION


def run_record(run):
    header = asdict(run.header)
    for key, value in header.items():
        if isinstance(value, datetime):
            header[key] = value.isoformat()
    return {"schema": "gcviewer-fid-run-v1", "parser": "tcfid", "parser_version": TOTALCHROM_VERSION,
            "reader_revision": READER_ID, "header": header, "rate_hz": run.rate_hz,
            "uv_per_count": run.uv_per_count, "data_offset": run.data_offset,
            "source": str(run.path), "sha256": run.sha256, "point_count": run.n_points,
            "counts_sha256": hashlib.sha256(run.counts.astype("<i4").tobytes()).hexdigest(),
            "units": "uV", "time_convention": "delay_min + (index + 1) / (rate_hz * 60)",
            "clipped_points": int(np.count_nonzero(run.clipped)), "warnings": list(run.warnings)}


def restore_run(record, counts):
    """Rehydrate a validated worker payload, without rereading/changing the source."""
    if record.get("schema") != "gcviewer-fid-run-v1":
        raise ValueError("Unsupported FID worker record.")
    counts = np.array(counts, copy=True)
    if counts.dtype != np.dtype("int32") or counts.ndim != 1 or len(counts) != record["point_count"]:
        raise ValueError("FID worker counts do not match the acquisition record.")
    if hashlib.sha256(counts.astype("<i4").tobytes()).hexdigest() != record["counts_sha256"]:
        raise ValueError("FID worker count checksum does not match the acquisition record.")
    header = dict(record["header"])
    for key in ("created_utc", "modified_utc", "injection_utc"):
        header[key] = datetime.fromisoformat(header[key])
    for key in ("sample_values", "scale_a", "scale_b"):
        header[key] = tuple(header[key])
    header = RawHeader(**header)
    if len(counts) < 2 or int(counts.min()) != header.recorded_min_counts or int(counts.max()) != header.recorded_max_counts:
        raise ValueError("FID worker extrema do not match the acquisition header.")
    if not np.isfinite([record["rate_hz"], record["uv_per_count"], header.delay_min]).all() or min(record["rate_hz"], record["uv_per_count"]) <= 0:
        raise ValueError("Invalid FID worker time or unit scale.")
    counts.flags.writeable = False
    return RawRun(header, counts, record["rate_hz"], record["uv_per_count"], record["data_offset"],
                  Path(record["source"]), tuple(record["warnings"]), record["sha256"])


def fid_trace(run):
    """Keep µV in scientific/export state; the readable plot axis displays mV."""
    clipped = int(np.count_nonzero(run.clipped))
    warnings = run.warnings + ((f"{clipped} points reach the known A/D clipping limit; peak heights may be truncated.",) if clipped else ())
    return Trace(run.path.name, str(run.path), "GC-FID", run.times_min, run.microvolts,
                 y_label="Response (µV)", metadata={"fid_acquisition": run_record(run)},
                 transformations=("FID: recorded signed counts converted to µV using the file's channel scale; no baseline subtraction, smoothing or normalization.",),
                 warnings=warnings)
