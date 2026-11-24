"""Test-only helpers: TotalChrom reference data (not used by the tcfid package).

* read_rax_counts: point values from TotalChrom's own ASCII export (.rax).
* read_rst: peak table, integration settings and timed events from a result
  file (.rst, PENX file type 2). Locating the sections relies on anchors that
  hold for the files examined so far; every value read is sanity-checked.
* REPORT_TABLES: peak tables transcribed from the printed 2025 reports.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from gcviewer.analysis.totalchrom_fid import IntegrationParams, TimedEvent

DATA_ENV = "TCFID_TEST_DATA"


def _env_value() -> str | None:
    d = os.environ.get(DATA_ENV)
    if d is None:
        return None
    return d.strip().strip('"').strip("'").strip()


def data_dir() -> Path | None:
    d = _env_value()
    return Path(d) if d and Path(d).is_dir() else None


def need_file(name: str) -> Path:
    """Return the test file or skip the test, saying exactly why."""
    import unittest
    raw = os.environ.get(DATA_ENV)
    if raw is None:
        raise unittest.SkipTest(f"{DATA_ENV} is not set in this terminal")
    if data_dir() is None:
        raise unittest.SkipTest(f"{DATA_ENV}={raw!r} is not a folder")
    p = data_file(name)
    if p is None:
        raise unittest.SkipTest(f"{name} not found in {data_dir()}")
    return p


def _norm(name: str) -> str:
    return name.lower().replace(" ", "_")


def data_file(name: str) -> Path | None:
    """Find a test file ignoring case and treating spaces and underscores alike
    (TotalChrom writes 'tdap mon 1pm001.raw'; uploads may say 'tdap_mon_1pm001.raw')."""
    d = data_dir()
    if d is None:
        return None
    for p in d.iterdir():
        if _norm(p.name) == _norm(name):
            return p
    return None


def read_rax_counts(path: Path) -> np.ndarray:
    lines = path.read_text(encoding="latin-1").splitlines()
    i = lines.index("[Raw Data Points]") + 1
    vals: list[int] = []
    for line in lines[i:]:
        s = line.strip()
        if not s:
            if vals:
                break
            continue
        try:
            vals.append(int(s))
        except ValueError:
            break
    return np.array(vals, dtype=np.int64)


def _i32(b: bytes, o: int) -> int:
    return struct.unpack_from(">i", b, o)[0]


def _f64(b: bytes, o: int) -> float:
    lo, hi = struct.unpack_from(">II", b, o)
    return struct.unpack(">d", struct.pack(">II", hi, lo))[0]


def _xdr(s: str) -> bytes:
    raw = s.encode("latin-1")
    return struct.pack(">I", len(raw)) + raw + b"\0" * (-len(raw) % 4)


PEAK_RECORD = 0xEC
EVENT_RECORD = 28
EVENT_CODES = {-4: "-P", 4: "+P"}


@dataclass(frozen=True)
class RefPeak:
    start: int
    apex: int
    end: int
    start_s: float
    rt_s: float
    end_s: float
    area_uv_s: float
    height_uv: float
    area_frac: float
    baseline_intercept_counts: float
    baseline_slope_counts_per_s: float


@dataclass(frozen=True)
class RefResult:
    peaks: tuple[RefPeak, ...]
    bunching_factor: int
    noise_threshold: int
    area_threshold: float
    width_ratio: float
    valley_to_peak_ratio: float
    skim_ratios: tuple[float, float, float]
    events: tuple[tuple[float, int, float], ...]

    def params(self) -> IntegrationParams:
        return IntegrationParams(
            noise_threshold_uv=float(self.noise_threshold),
            area_threshold_uv=float(self.area_threshold),
            bunching_factor=self.bunching_factor,
            width_ratio=self.width_ratio,
            valley_to_peak_ratio=self.valley_to_peak_ratio,
            events=tuple(TimedEvent(tm, EVENT_CODES[c]) for tm, c, _v in self.events),
        )


def _find_peak_table(b: bytes, rate_hz: float) -> tuple[int, list[RefPeak]]:
    for off in range(0x40, len(b) - PEAK_RECORD, 4):
        n = _i32(b, off)
        if not 1 <= n <= 500 or off + 4 + n * PEAK_RECORD > len(b):
            continue
        peaks, r = [], off + 4
        for _ in range(n):
            s, a, e = _i32(b, r), _i32(b, r + 4), _i32(b, r + 8)
            ts, trt, te = _f64(b, r + 0x18), _f64(b, r + 0x20), _f64(b, r + 0x28)
            if not (0 <= s < a < e and abs(ts - (s + 1) / rate_hz) < 1e-6
                    and abs(te - (e + 1) / rate_hz) < 1e-6 and ts < trt < te):
                break
            peaks.append(RefPeak(s, a, e, ts, trt, te, _f64(b, r + 0x30), _f64(b, r + 0x38),
                                 _f64(b, r + 0x8C), _f64(b, r + 0xC4), _f64(b, r + 0xCC)))
            r += PEAK_RECORD
        if len(peaks) == n:
            return off, peaks
    raise ValueError("no peak table found")


def _title_offset(b: bytes) -> int:
    """Offset of the replot title string, found as the string just before 'Time [min]'."""
    p = b.find(_xdr("Time [min]"))
    if p < 0:
        raise ValueError("replot labels not found")
    for n in range(0, 256):
        o = p - 4 - n - (-n % 4)
        if o >= 0 and _i32(b, o) == n:
            return o
    raise ValueError("replot title not found")


def read_rst(path: Path, rate_hz: float = 12.5) -> RefResult:
    b = path.read_bytes()
    if b[:4] != b"PENX" or _i32(b, 4) != 2:
        raise ValueError(f"{path.name} is not a TotalChrom result file")
    _, peaks = _find_peak_table(b, rate_hz)
    o = _title_offset(b) - 104
    bf, nt, at = _i32(b, o), _i32(b, o + 4), _f64(b, o + 8)
    wr, vp = _f64(b, o + 16), _f64(b, o + 24)
    skim = (_f64(b, o + 32), _f64(b, o + 40), _f64(b, o + 48))
    if not (1 <= bf <= 100 and nt > 0 and at > 0 and 0 < wr < 100 and 0 <= vp < 1):
        raise ValueError(f"implausible integration settings {bf, nt, at, wr, vp}")
    q = b.rfind(_xdr("$RST"))
    if q < 0:
        raise ValueError("user-program block not found")
    q += len(_xdr("$RST"))
    n_ev = _i32(b, q)
    events, r = [], q + 4
    for _ in range(n_ev):
        events.append((_f64(b, r), _i32(b, r + 8), _f64(b, r + 12)))
        r += EVENT_RECORD
    return RefResult(tuple(peaks), bf, nt, at, wr, vp, skim, tuple(events))


REPORT_TABLES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "tdap_mon_1pm001": ((2.328, 9453930.50, 988672.00), (4.227, 53219.75, 27392.55)),
    "tdap_mon_1pm002": ((2.328, 9351874.34, 988710.80), (4.229, 78023.50, 38765.03),
                        (5.346, 23072.08, 15437.25)),
    "tdap_mon_1pm003": ((2.331, 9215711.76, 988700.74), (4.223, 82872.21, 41663.68),
                        (5.340, 75064.48, 49637.38)),
    "tdap_mon_1pm004": ((2.331, 8658330.98, 988718.05), (4.228, 78035.79, 41383.91),
                        (5.346, 110078.32, 73482.75)),
    "tdap_mon_1pm005": ((2.328, 9085633.09, 988724.95), (4.224, 86155.88, 43701.23),
                        (5.346, 188622.13, 118972.87), (5.892, 324.48, 342.66)),
}

TDAP_2025_PARAMS = IntegrationParams(
    noise_threshold_uv=50.0, area_threshold_uv=100.0, bunching_factor=1,
    events=(TimedEvent(0.01093, "-P"), TimedEvent(1.93141, "+P")))
