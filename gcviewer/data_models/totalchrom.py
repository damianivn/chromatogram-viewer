"""TotalChrom acquisition data and detector constants; no I/O or analysis."""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import numpy as np

CLIP_COUNTS = 107_374_178
CLIP_TOLERANCE = 16


@dataclass(frozen=True)
class RawHeader:
    """Metadata decoded from a raw file. Field meanings are verified unless noted."""

    file_type: int
    version: int
    created_by: str
    created_host: str
    created_utc: datetime
    modified_by: str
    modified_host: str
    modified_utc: datetime
    file_complete_flag: int
    injection_utc: datetime
    acquired_by: str
    sequence_path: str
    sequence_row: int              # 0-based row within the sequence
    autosampler: str
    vial: int
    run_time_min: float
    recorded_max_counts: int
    recorded_min_counts: int
    channel: str
    study: str
    sample_name: str
    sample_number: str
    recorded_raw_path: str
    result_base_path: str
    instrument_method: str
    process_method: str
    calibration_method: str
    report_format: str             # inferred: 4th method path of the sequence row
    sample_values: tuple[float, ...]  # unlabeled per-sample numbers (volume, amounts, ...)
    method_title: str              # description line of the method's data header
    method_revision: int
    method_notes: str
    delay_min: float
    ad_mv_range: int
    instrument_name: str
    scale_a: tuple[float, float]   # (54.01791, 2.0) on this instrument
    scale_b: tuple[float, float]


@dataclass(frozen=True, eq=False)
class RawRun:
    """A decoded chromatogram. ``counts`` are the stored integers, unmodified."""

    header: RawHeader
    counts: np.ndarray
    rate_hz: float
    uv_per_count: float
    data_offset: int
    path: Path | None = None
    warnings: tuple[str, ...] = field(default=())
    sha256: str = ""               # of the file bytes, for provenance records

    @property
    def n_points(self) -> int:
        return int(self.counts.size)

    @property
    def times_s(self) -> np.ndarray:
        """TotalChrom time of each point: point i (0-based) is at delay + (i+1)/rate."""
        return self.header.delay_min * 60.0 + (np.arange(self.n_points) + 1) / self.rate_hz

    @property
    def times_min(self) -> np.ndarray:
        return self.times_s / 60.0

    @property
    def microvolts(self) -> np.ndarray:
        return self.counts.astype(np.float64) * self.uv_per_count

    @property
    def clipped(self) -> np.ndarray:
        """True where the signal sits at the A/D ceiling."""
        return self.counts >= CLIP_COUNTS - CLIP_TOLERANCE


