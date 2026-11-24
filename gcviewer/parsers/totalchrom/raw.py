"""Read TotalChrom PENX type-1 chromatograms. See docs/tcfid/FORMAT.md."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from gcviewer.parsers.totalchrom.binary import MAGIC, PenxFormatError, PenxReader

FILE_TYPE_RAW = 1
KNOWN_VERSIONS = frozenset({10019})

from gcviewer.data_models.totalchrom import CLIP_COUNTS, CLIP_TOLERANCE, RawHeader, RawRun


def read_raw(path: str | Path) -> RawRun:
    path = Path(path)
    return read_raw_bytes(path.read_bytes(), path=path)


def read_raw_bytes(buf: bytes, path: Path | None = None) -> RawRun:
    if buf[:4] != MAGIC:
        raise PenxFormatError(f"not a TotalChrom PENX file (starts with {buf[:4]!r})")
    r = PenxReader(buf, 4)
    warnings: list[str] = []

    # File header
    file_type = r.i32()
    if file_type != FILE_TYPE_RAW:
        raise PenxFormatError(f"PENX file type {file_type} is not a raw data file (1)")
    r.i32()                                   # 48 in every file seen
    version = r.i32()
    if version not in KNOWN_VERSIONS:
        warnings.append(f"unverified format version {version}; checks below still apply")
    r.i32(); r.i32(); r.i32()
    r.text(); r.text()                        # Two checksum fields.

    # Data header
    created_by, created_host, created = r.text(), r.text(), r.timestamp()
    modified_by, modified_host, modified = r.text(), r.text(), r.timestamp()
    r.text(); r.i32(); r.i32(); r.text()
    complete_flag = r.i32()
    r.i32()                                   # run-log entries (0 in every file seen)

    # A/d header
    r.i32()
    injection = r.timestamp()
    r.i32()
    acquired_by = r.text()
    sequence_path, sequence_row = r.text(), r.i32()
    autosampler = r.text(); r.i32(); vial = r.i32()
    run_time_min = r.f64()
    max_counts, min_counts = r.i32(), r.i32()
    r.text(); r.f64(); r.f64()
    n_header = r.i32()
    r.i32(); r.i32()

    # Sequence row
    channel = r.text(); r.i32(); r.i32(); r.i32()
    study, sample_name, sample_number = r.text(), r.text(), r.text()
    recorded_raw_path, result_base = r.text(), r.text()
    r.text(); r.text()
    inst_m, proc_m, cal_m, report_fmt = r.text(), r.text(), r.text(), r.text()
    r.text(); r.text()
    sample_values = tuple(r.f64() for _ in range(8))
    r.i32(); r.text(); r.i32(); r.text(); r.text(); r.i32()
    r.text(); r.text(); r.text(); r.i32()
    for _ in range(11):
        r.text()

    # Data array
    n = r.i32()
    if n != n_header:
        raise PenxFormatError(
            f"header says {n_header} points but the data array holds {n} "
            f"(offset {r.pos - 4:#x}); the header layout differs from the verified one")
    if n < 2:
        raise PenxFormatError("a chromatogram needs at least two recorded points")
    data_offset = r.pos
    counts = r.i32_array(n)
    if int(counts.min()) != min_counts or int(counts.max()) != max_counts:
        raise PenxFormatError(
            f"recorded min/max counts ({min_counts}, {max_counts}) do not match the data "
            f"({int(counts.min())}, {int(counts.max())})")

    # Instrument method copy, a/d box, instrument configuration
    r.text(); r.text(); r.timestamp(); r.text(); r.text(); r.timestamp()
    r.text()
    method_revision = r.i32(); r.i32()
    method_title = r.text()
    r.i32(); r.i32()
    method_notes = r.text()
    delay_min = r.f64(); r.f64(); r.f64()
    rate_hz = r.f64()
    r.i32()
    ad_mv_range = r.i32()
    r.i32(); r.i32(); r.i32(); r.i32()
    instrument_name = r.text(); r.text(); r.text()
    for _ in range(7):
        r.i32()
    scale_a = (r.f64(), r.f64())
    scale_b = (r.f64(), r.f64())

    if not (rate_hz > 0 and np.isfinite(rate_hz)):
        raise PenxFormatError(f"implausible sampling rate {rate_hz!r}")
    if not np.isfinite([run_time_min, delay_min]).all() or min(run_time_min, delay_min) < 0:
        raise PenxFormatError("run time and acquisition delay must be finite and nonnegative")
    if complete_flag != 3:
        warnings.append(f"acquisition is not marked complete (flag {complete_flag}); it may still be being written")
    if abs(run_time_min * 60.0 * rate_hz - n) > 1.0:
        warnings.append(
            f"run time {run_time_min:.4f} min x {rate_hz} Hz does not match {n} points")

    if channel == "A":
        factor, multiplier = scale_a
    elif channel == "B":
        factor, multiplier = scale_b
    else:
        raise PenxFormatError(f"unknown channel {channel!r}")
    if not (np.isfinite([factor, multiplier]).all() and factor > 0 and multiplier > 0):
        raise PenxFormatError(
            f"no usable unit scale for channel {channel}: ({factor}, {multiplier})")
    product = factor * multiplier
    if not np.isfinite(product) or product <= 0:
        raise PenxFormatError("channel scale product must be finite and positive")
    uv_per_count = 1.0 / product
    if not np.isfinite(uv_per_count) or uv_per_count <= 0:
        raise PenxFormatError("channel scale does not yield a finite positive conversion")

    header = RawHeader(
        file_type=file_type, version=version,
        created_by=created_by, created_host=created_host, created_utc=created,
        modified_by=modified_by, modified_host=modified_host, modified_utc=modified,
        file_complete_flag=complete_flag, injection_utc=injection, acquired_by=acquired_by,
        sequence_path=sequence_path, sequence_row=sequence_row,
        autosampler=autosampler, vial=vial, run_time_min=run_time_min,
        recorded_max_counts=max_counts, recorded_min_counts=min_counts,
        channel=channel, study=study, sample_name=sample_name, sample_number=sample_number,
        recorded_raw_path=recorded_raw_path, result_base_path=result_base,
        instrument_method=inst_m, process_method=proc_m, calibration_method=cal_m,
        report_format=report_fmt, sample_values=sample_values,
        method_title=method_title, method_revision=method_revision,
        method_notes=method_notes, delay_min=delay_min,
        ad_mv_range=ad_mv_range, instrument_name=instrument_name,
        scale_a=scale_a, scale_b=scale_b,
    )
    return RawRun(header=header, counts=counts, rate_hz=rate_hz, uv_per_count=uv_per_count,
                  data_offset=data_offset, path=path, warnings=tuple(warnings),
                  sha256=hashlib.sha256(buf).hexdigest())
