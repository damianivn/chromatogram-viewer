"""FID peak detection, baseline assignment and integration.

NT is the rise between successive bunched points. AT is the running sum
of heights above the starting point. Both thresholds use microvolts.
See docs/tcfid/FORMAT.md for the field map and reference comparisons.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from numbers import Integral
from typing import Callable, Sequence

import numpy as np

CLIPPING_WARNING = "Clipped peaks: areas and heights may be underestimated."

from gcviewer.data_models.totalchrom import CLIP_COUNTS, CLIP_TOLERANCE, RawRun

CLIP_LEVEL = CLIP_COUNTS - CLIP_TOLERANCE

EVENT_KINDS = ("-P", "+P", "NT", "AT")
BACKWARD_SEARCH_BUNCHES = 5


@dataclass(frozen=True)
class TimedEvent:
    time_min: float
    kind: str                    # "-P" peak detection off, "+P" on, "NT"/"AT" new threshold
    value: float | None = None   # µV, required for NT and AT

    def __post_init__(self) -> None:
        if not math.isfinite(self.time_min) or self.time_min < 0:
            raise ValueError("event time must be finite and nonnegative")
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"unsupported timed event {self.kind!r}; supported: {EVENT_KINDS}")
        if self.kind in ("NT", "AT") and (self.value is None or not math.isfinite(self.value) or self.value <= 0):
            raise ValueError(f"{self.kind} event needs a positive value")
        if self.kind in ("-P", "+P") and self.value is not None:
            raise ValueError("detection on/off events do not take a value")

    def to_dict(self) -> dict:
        return {"time_min": self.time_min, "kind": self.kind, "value": self.value}

    @classmethod
    def from_dict(cls, d: dict) -> "TimedEvent":
        return cls(float(d["time_min"]), str(d["kind"]),
                   None if d.get("value") is None else float(d["value"]))


@dataclass(frozen=True)
class IntegrationParams:
    noise_threshold_uv: float
    area_threshold_uv: float
    bunching_factor: int = 1
    width_ratio: float = 0.2              # TotalChrom default (manual)
    valley_to_peak_ratio: float = 0.01    # TotalChrom default (manual)
    events: tuple[TimedEvent, ...] = ()

    def __post_init__(self) -> None:
        if not all(math.isfinite(x) and x > 0 for x in (self.noise_threshold_uv, self.area_threshold_uv)):
            raise ValueError("noise and area thresholds must be positive")
        if isinstance(self.bunching_factor, bool) or not isinstance(self.bunching_factor, Integral) or self.bunching_factor < 1:
            raise ValueError("bunching factor must be a positive integer")
        if not math.isfinite(self.width_ratio) or self.width_ratio != .2:
            raise ValueError("width_ratio is not implemented; only the reserved default 0.2 is supported")
        if not math.isfinite(self.valley_to_peak_ratio) or not 0 <= self.valley_to_peak_ratio <= 1:
            raise ValueError("valley-to-peak ratio must be finite and between 0 and 1")
        seen = set()
        for event in self.events:
            key = (event.time_min, "detection" if event.kind in ("-P", "+P") else event.kind)
            if key in seen:
                raise ValueError("conflicting events at the same time")
            seen.add(key)
        object.__setattr__(self, "events", tuple(sorted(self.events, key=lambda e: e.time_min)))

    def to_dict(self) -> dict:
        """Plain types only, for saving with a method or next to results (JSON-safe)."""
        return {"noise_threshold_uv": self.noise_threshold_uv,
                "area_threshold_uv": self.area_threshold_uv,
                "bunching_factor": int(self.bunching_factor),
                "width_ratio": self.width_ratio,
                "valley_to_peak_ratio": self.valley_to_peak_ratio,
                "events": [e.to_dict() for e in self.events]}

    @classmethod
    def from_dict(cls, d: dict) -> "IntegrationParams":
        return cls(noise_threshold_uv=float(d["noise_threshold_uv"]),
                   area_threshold_uv=float(d["area_threshold_uv"]),
                   bunching_factor=d.get("bunching_factor", 1),
                   width_ratio=float(d.get("width_ratio", 0.2)),
                   valley_to_peak_ratio=float(d.get("valley_to_peak_ratio", 0.01)),
                   events=tuple(TimedEvent.from_dict(e) for e in d.get("events", ())))


@dataclass(frozen=True)
class Peak:
    number: int
    start: int                    # 0-based point indices into the run
    apex: int
    end: int
    start_min: float
    rt_min: float
    end_min: float
    area_uv_s: float
    height_uv: float
    area_pct: float
    baseline_code: str            # BB, BV, VV or VB
    baseline_counts: tuple[float, float]  # baseline value (counts) at start and end
    cluster: int
    clipped: bool
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntegrationResult:
    peaks: tuple[Peak, ...]
    params: IntegrationParams
    uv_per_count: float
    warnings: tuple[str, ...] = field(default=())

    @property
    def total_area_uv_s(self) -> float:
        return float(sum(p.area_uv_s for p in self.peaks))

    def rows(self) -> list[dict]:
        return [dict(peak=p.number, rt_min=p.rt_min, area_uv_s=p.area_uv_s,
                     height_uv=p.height_uv, area_pct=p.area_pct, baseline=p.baseline_code,
                     start_min=p.start_min, end_min=p.end_min, clipped=p.clipped,
                     flags=" ".join(p.flags)) for p in self.peaks]


def peak_metrics(y: np.ndarray, t: np.ndarray, start: int, end: int,
                 base_t0: float, base_y0: float, base_t1: float, base_y1: float
                 ) -> tuple[int, float, float, float]:
    """Retention time, height and area of the points ``start..end`` (inclusive).

    The baseline is the straight line through (base_t0, base_y0) and (base_t1, base_y1).
    Returns (apex_index, rt_s, height_counts, area_counts_s). This reproduces
    TotalChrom's reported values exactly when given TotalChrom's boundaries.
    """
    if end <= start:
        raise ValueError("a peak needs at least two points")
    slope = (base_y1 - base_y0) / (base_t1 - base_t0)

    def base(tt):
        return base_y0 + slope * (np.asarray(tt, dtype=float) - base_t0)

    seg = np.arange(start, end + 1)
    ys = y[seg].astype(np.float64)
    apex = start + int(np.argmax(ys))          # first maximum
    rt, top = t[apex], float(y[apex])
    if y[apex] < CLIP_LEVEL and seg.size >= 5:
        five = seg[np.argsort(ys, kind="stable")[-5:]]
        tc = t[five] - t[apex]
        c2, c1, c0 = np.polyfit(tc, y[five].astype(np.float64), 2)
        if c2 < 0:
            tv = -c1 / (2.0 * c2)
            if t[start] - t[apex] <= tv <= t[end] - t[apex]:
                rt, top = t[apex] + tv, c0 + c1 * tv + c2 * tv * tv
    height = top - float(base(rt))
    dt = float(t[1] - t[0])
    area = float(np.trapezoid(ys - base(t[seg]), dx=dt))
    return apex, float(rt), height, area


def _confirm_rise(b: np.ndarray, k: int, nt: float, at: float) -> int | None:
    """Potential start at bunch k. Return the bunch where the running sum of heights
    above b[k] first exceeds ``at``, or None if the rise drops below ``nt`` first."""
    base, acc, m, n = b[k], 0.0, k + 1, len(b)
    while True:
        acc += b[m] - base
        if acc > at:
            return m
        if m + 1 >= n or b[m + 1] - b[m] <= nt:
            return None
        m += 1


def _find_top(b: np.ndarray, m: int, at: float) -> tuple[int, int | None]:
    """Top = highest point whose following drops sum to more than 2/3 of ``at``."""
    top, acc, need = m, 0.0, at * 2.0 / 3.0
    for j in range(m + 1, len(b)):
        if b[j] > b[top]:
            top, acc = j, 0.0
        else:
            acc += b[top] - b[j]
            if acc > need:
                return top, j
    return top, None


def _find_end(b: np.ndarray, j0: int, nt: float, at: float,
              enabled: Callable[[int], bool]):
    """End = second of two consecutive steps smaller than nt/2; or a new rise (fused peak)."""
    n, half = len(b), nt / 2.0
    for i in range(max(j0, 1), n - 1):
        if enabled(i + 1) and b[i + 1] - b[i] > nt:
            m = _confirm_rise(b, i, nt, at)
            if m is not None:
                return "fused", i, m
        if abs(b[i] - b[i - 1]) < half and abs(b[i + 1] - b[i]) < half:
            return "end", i + 1, None
    return "eof", n - 1, None


def _schedule(events: Sequence[TimedEvent], tb_min: np.ndarray, params: IntegrationParams):
    """Per-bunch detection flag and thresholds (µV) from the timed events."""
    nb = tb_min.size
    enabled = np.ones(nb, dtype=bool)
    nt = np.full(nb, float(params.noise_threshold_uv))
    at = np.full(nb, float(params.area_threshold_uv))
    for ev in events:
        sel = tb_min >= ev.time_min
        if ev.kind == "-P":
            enabled[sel] = False
        elif ev.kind == "+P":
            enabled[sel] = True
        elif ev.kind == "NT":
            nt[sel] = ev.value
        elif ev.kind == "AT":
            at[sel] = ev.value
    return enabled, nt, at


def integrate(run: RawRun, params: IntegrationParams) -> IntegrationResult:
    return integrate_counts(run.counts, run.rate_hz, run.uv_per_count, params,
                            delay_s=run.header.delay_min * 60.0)


def integrate_counts(counts: np.ndarray, rate_hz: float, uv_per_count: float,
                     params: IntegrationParams, delay_s: float = 0.0) -> IntegrationResult:
    y = np.asarray(counts, dtype=np.float64)
    n = y.size
    t = delay_s + (np.arange(n) + 1) / rate_hz
    bf = int(params.bunching_factor)
    nb = n // bf
    b = y[:nb * bf].reshape(nb, bf).mean(axis=1)
    last_raw = np.arange(nb) * bf + (bf - 1)          # a bunch sits at its last raw point
    enabled_b, nt_uv, at_uv = _schedule(params.events, t[last_raw] / 60.0, params)
    nt_c, at_c = nt_uv / uv_per_count, at_uv / uv_per_count
    warnings: list[str] = []
    if bf > 1:
        warnings.append("bunching factor > 1 is not verified against TotalChrom")
    if any(e.kind in ("NT", "AT") for e in params.events):
        warnings.append("NT/AT timed events are not verified against TotalChrom")

    def enabled(k: int) -> bool:
        return bool(enabled_b[k])

    clusters: list[list[tuple[int, int, int, bool]]] = []   # (start, top, end, start_is_valley)
    k = 0
    while k < nb - 1:
        if not (enabled(k + 1) and b[k + 1] - b[k] > nt_c[k]):
            k += 1
            continue
        nt, at = nt_c[k], at_c[k]
        m = _confirm_rise(b, k, nt, at)
        if m is None:
            k += 1
            continue
        cluster, pot, valley_start = [], k, False
        while True:
            top, conf = _find_top(b, m, at)
            if conf is None:
                cluster.append((pot, top, nb - 1, valley_start))
                warnings.append("run ended before the last peak's top was confirmed")
                k = nb
                break
            kind, idx, m2 = _find_end(b, conf, nt, at, enabled)
            if kind == "fused":
                valley = top + int(np.argmin(b[top:idx + 1]))
                cluster.append((pot, top, valley, valley_start))
                pot, m, valley_start = valley, m2, True
                continue
            if kind == "eof":
                warnings.append("run ended before the last peak's end was found")
            cluster.append((pot, top, idx, valley_start))
            k = idx
            break
        clusters.append(cluster)

    raw_clusters: list[list[list[int]]] = []
    prev_end = 0
    for cl in clusters:
        segs = []
        for j, (pot, _top, end, valley_start) in enumerate(cl):
            if j == 0 and not valley_start:
                hi = last_raw[pot]
                lo = max(hi - BACKWARD_SEARCH_BUNCHES * bf, prev_end)
                s = lo + int(np.argmin(y[lo:hi + 1]))
            else:
                s = segs[-1][1]
            e_lo, e_hi = end * bf, last_raw[end]
            e = int(last_raw[end]) if j == len(cl) - 1 else e_lo + int(np.argmin(y[e_lo:e_hi + 1]))
            segs.append([int(s), e])
        prev_end = segs[-1][1]
        raw_clusters.append(segs)

    groups: list[list[list[int]]] = []
    for segs in raw_clusters:
        group = [segs[0]]
        s0, e1 = segs[0][0], segs[-1][1]
        line = y[s0] + (y[e1] - y[s0]) * (t - t[s0]) / (t[e1] - t[s0])
        for seg in segs[1:]:
            v = seg[0]
            hv = y[v] - line[v]
            h_prev = np.max(y[group[-1][0]:group[-1][1] + 1] - line[group[-1][0]:group[-1][1] + 1])
            h_next = np.max(y[seg[0]:seg[1] + 1] - line[seg[0]:seg[1] + 1])
            p = min(h_prev, h_next)
            if p > 0 and hv / p <= params.valley_to_peak_ratio:
                groups.append(group)       # separated: own baselines, valley to valley
                group = [seg]
            else:
                group.append(seg)
        groups.append(group)

    peaks_tmp = []
    for gi, group in enumerate(groups):
        s0, e1 = group[0][0], group[-1][1]
        bt0, by0, bt1, by1 = t[s0], y[s0], t[e1], y[e1]
        line = by0 + (by1 - by0) * (t[s0:e1 + 1] - bt0) / (bt1 - bt0)
        penetrates = bool(np.any(y[s0:e1 + 1] < line - np.median(nt_c) / 2.0))
        starts_at_valley = (gi > 0 and groups[gi - 1][-1][1] == s0)
        for j, (s, e) in enumerate(group):
            apex, rt, h, area = peak_metrics(y, t, s, e, bt0, by0, bt1, by1)
            first = "V" if (j > 0 or starts_at_valley) else "B"
            last_is_valley = (j < len(group) - 1) or (gi + 1 < len(groups) and groups[gi + 1][0][0] == e)
            code = first + ("V" if last_is_valley else "B")
            flags = []
            clipped = bool(np.any(y[s:e + 1] >= CLIP_LEVEL))
            if clipped:
                flags.append("out-of-range")
            if penetrates:
                flags.append("baseline-penetration")
            base_s = by0 + (by1 - by0) * (t[s] - bt0) / (bt1 - bt0)
            base_e = by0 + (by1 - by0) * (t[e] - bt0) / (bt1 - bt0)
            peaks_tmp.append((s, apex, e, rt, h, area, code, (base_s, base_e), gi, clipped, tuple(flags)))

    total = sum(p[5] for p in peaks_tmp)
    peaks = tuple(
        Peak(number=i + 1, start=int(s), apex=int(apex), end=int(e),
             start_min=float(t[s] / 60.0), rt_min=float(rt / 60.0), end_min=float(t[e] / 60.0),
             area_uv_s=float(area * uv_per_count), height_uv=float(h * uv_per_count),
             area_pct=float(100.0 * area / total) if total else 0.0,
             baseline_code=code, baseline_counts=(float(bs), float(be)), cluster=gi,
             clipped=clipped, flags=flags)
        for i, (s, apex, e, rt, h, area, code, (bs, be), gi, clipped, flags) in enumerate(peaks_tmp))
    return IntegrationResult(peaks=peaks, params=params, uv_per_count=uv_per_count,
                             warnings=tuple(dict.fromkeys(warnings)))


SOLVENT_HEIGHT_RATIO = 10.0


def find_solvent_peak(result: IntegrationResult,
                      height_ratio: float = SOLVENT_HEIGHT_RATIO) -> Peak | None:
    """The solvent peak: the earliest peak clipped at the A/D limit; if none is clipped, the
    tallest peak when it is at least ``height_ratio`` times taller than every other one.
    Otherwise None. (Tiny artifacts before the solvent do not count.)"""
    if not result.peaks:
        return None
    clipped = [p for p in result.peaks if p.clipped]
    if clipped:
        return clipped[0]
    ranked = sorted(result.peaks, key=lambda p: p.height_uv, reverse=True)
    if len(ranked) > 1 and ranked[0].height_uv >= height_ratio * ranked[1].height_uv:
        return ranked[0]
    return None


def integrate_skipping_solvent(run: RawRun, params: IntegrationParams,
                               margin_min: float = 0.0) -> tuple[IntegrationResult, float | None]:
    """Integrate with peak detection off until the end of the solvent peak ("auto solvent delay").

    Integrates once to find the solvent peak, then again with -P at 0 and +P at the solvent's
    end (+ margin). Later -P/+P and threshold events are kept. The solvent then drops out of
    the peak table and area % (as does anything before it); later peaks are unchanged.
    Returns (result, delay_min), with
    delay_min None when no solvent peak was found.
    """
    first = integrate(run, params)
    solvent = find_solvent_peak(first)
    if solvent is None:
        return first, None
    delay = solvent.end_min + margin_min
    kept = tuple(e for e in params.events if e.kind not in ("-P", "+P") or e.time_min > delay)
    events = (TimedEvent(0.0, "-P"), TimedEvent(delay, "+P")) + kept
    return integrate(run, replace(params, events=events)), delay
