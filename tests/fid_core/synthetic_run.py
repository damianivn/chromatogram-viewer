"""Build a RawRun from synthetic counts (no data files needed)."""
from datetime import datetime, timezone

import numpy as np

from gcviewer.data_models.totalchrom import RawHeader, RawRun

UV = 1.0 / (2.0 * 54.01791)


def gaussian_counts(peaks, n=9875, rate=12.5, noise_counts=55.0, seed=0, baseline=537_000.0):
    """peaks = [(rt_s, height_counts, sigma_s), ...]"""
    rng = np.random.default_rng(seed)
    t = (np.arange(n) + 1) / rate
    y = baseline + rng.normal(0.0, noise_counts, n)
    for rt, h, sd in peaks:
        y += h * np.exp(-0.5 * ((t - rt) / sd) ** 2)
    return np.round(y).astype(np.int32)


def synthetic_run(counts, name="synthetic", rate=12.5):
    now = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
    n = len(counts)
    header = RawHeader(
        file_type=1, version=10019, created_by="test", created_host="host", created_utc=now,
        modified_by="test", modified_host="host", modified_utc=now, file_complete_flag=3,
        injection_utc=now, acquired_by="test", sequence_path=r"C:\seq\test.seq", sequence_row=0,
        autosampler="BUILT-IN", vial=1, run_time_min=n / rate / 60.0,
        recorded_max_counts=int(max(counts)), recorded_min_counts=int(min(counts)), channel="A",
        study="synthetic", sample_name=name, sample_number="001",
        recorded_raw_path=rf"C:\data\{name}.raw", result_base_path=rf"C:\data\{name}",
        instrument_method=r"C:\methods\test", process_method=r"C:\methods\test",
        calibration_method=r"C:\methods\test", report_format=r"C:\methods\test",
        sample_values=(1.0,) * 8, method_title="test", method_revision=1, method_notes="",
        delay_min=0.0, ad_mv_range=1000, instrument_name="Clarus 500 FID",
        scale_a=(54.01791, 2.0), scale_b=(54.01791, 0.0))
    from pathlib import Path
    arr = np.asarray(counts, dtype=np.int32)
    return RawRun(header=header, counts=arr, rate_hz=rate, uv_per_count=UV, data_offset=0,
                  path=Path(f"{name}.raw"), sha256="0" * 64)
