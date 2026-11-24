"""Draw a chromatogram with integration results onto any matplotlib Axes.

Shared by the PDF report and the test viewer. No pyplot, no global state.
"""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
from matplotlib.patches import Patch
from matplotlib.textpath import TextPath
from matplotlib.ticker import AutoMinorLocator, MaxNLocator

from gcviewer.analysis.totalchrom_fid import IntegrationResult, TimedEvent, find_solvent_peak
from gcviewer.data_models.totalchrom import RawRun

SIGNAL = "0.12"
BASELINE = "tab:red"
CLIPPED = "tab:orange"
REFERENCE = "tab:blue"
DISABLED = "0.9"
PEAK_LABEL_MODES = ("name_or_rt", "rt", "name", "name_and_rt", "none")


def detection_off_windows(events: Sequence[TimedEvent], t_end_min: float) -> list[tuple[float, float]]:
    """(start, end) minutes where peak detection is switched off by -P/+P events."""
    windows, off = [], None
    for e in sorted(events, key=lambda e: e.time_min):
        if e.kind == "-P" and off is None:
            off = e.time_min
        elif e.kind == "+P" and off is not None:
            windows.append((off, e.time_min))
            off = None
    if off is not None:
        windows.append((off, t_end_min))
    return windows


def main_view_range(run: RawRun, result: IntegrationResult | None,
                    hide_solvent: bool = True) -> tuple[float, float]:
    """x-range (min) for the main view: the whole run, or starting after the solvent.

    "After the solvent" is the later of the solvent peak's end and the end of a
    detection-off window that starts the run (an explicit or automatic solvent delay).
    """
    t = run.times_min
    x0, x1 = float(t[0]), float(t[-1])
    if not hide_solvent or result is None:
        return x0, x1
    start = x0
    solvent = find_solvent_peak(result)
    if solvent is not None:
        start = max(start, solvent.end_min)
    windows = detection_off_windows(result.params.events, x1)
    if windows and windows[0][0] <= x0 + 1e-9:
        start = max(start, windows[0][1])
    if start > x0:
        start += 2.0 / run.rate_hz / 60.0
    return (start, x1) if start < x1 else (x0, x1)


def view_ylim(run: RawRun, result: IntegrationResult | None,
              x_range: tuple[float, float]) -> tuple[float, float] | None:
    """y-range (mV) fitting the unclipped peaks inside ``x_range``; None if there are none."""
    if result is None:
        return None
    t, mv = run.times_min, run.microvolts / 1000.0
    x0, x1 = x_range
    tops = [mv[p.apex] for p in result.peaks if not p.clipped and x0 <= p.rt_min <= x1]
    if not tops:
        return None
    inside = (t >= x0) & (t <= x1)
    lo, hi = float(np.min(mv[inside])), float(max(tops))
    pad = 0.06 * (hi - lo) if hi > lo else 1.0
    return lo - pad, hi + 2.2 * pad


def _label(p, names: Mapping[int, str], mode: str) -> str:
    name = names.get(p.number, "")
    rt = f"{p.rt_min:.3f}"
    return {"name_or_rt": name or rt, "rt": rt, "name": name,
            "name_and_rt": f"{name} {rt}" if name else rt, "none": ""}[mode]


def plot_chromatogram(ax, run: RawRun, result: IntegrationResult | None = None,
                      names: Mapping[int, str] | None = None, *,
                      x_range: tuple[float, float] | None = None,
                      hide_solvent: bool = False, zoom_to_peaks: bool = False,
                      peak_labels: str = "name_or_rt", legend: bool = False,
                      x_label: str = "Time (min)", y_label: str = "Response (mV)",
                      minor_ticks: bool = True,
                      reference_baselines: Sequence[tuple[float, float, float, float]] = (),
                      reference_label: str = "reference baselines",
                      linewidth: float = 0.8, label_size: float = 8.0,
                      avoid_label_overlap: bool = True) -> tuple[float, float]:
    """Draw the run; returns the x-range shown.

    x_range overrides hide_solvent. zoom_to_peaks fits the y-axis to the unclipped peaks in
    view. peak_labels: one of PEAK_LABEL_MODES. legend lists only what is visible (clipped
    points, detection-off windows, reference baselines).
    reference_baselines: extra dashed segments (t0_min, y0_mV, t1_min, y1_mV).
    """
    if peak_labels not in PEAK_LABEL_MODES:
        raise ValueError(f"peak_labels must be one of {PEAK_LABEL_MODES}")
    names = names or {}
    t = run.times_min
    mv = run.microvolts / 1000.0
    k = run.uv_per_count / 1000.0
    x0, x1 = x_range if x_range is not None else main_view_range(run, result, hide_solvent)
    inside = (t >= x0) & (t <= x1)
    handles = []

    ax.plot(t, mv, lw=linewidth, color=SIGNAL)
    if result is not None:
        off = [(a, b) for a, b in detection_off_windows(result.params.events, float(t[-1]))
               if b > x0 and a < x1]
        for a, b in off:
            ax.axvspan(max(a, float(t[0])), b, color=DISABLED, zorder=0, lw=0)
        if off:
            handles.append(Patch(color=DISABLED, label="peak detection off"))
    clipped = run.clipped
    if clipped.any():
        ax.plot(t[clipped], mv[clipped], ".", ms=2, color=CLIPPED)
        if (clipped & inside).any():
            handles.append(ax.plot([], [], ".", color=CLIPPED, label="clipped at A/D limit")[0])
    if result is not None:
        for p in result.peaks:
            b0, b1 = p.baseline_counts[0] * k, p.baseline_counts[1] * k
            seg = slice(p.start, p.end + 1)
            base = np.interp(t[seg], [p.start_min, p.end_min], [b0, b1])
            ax.fill_between(t[seg], base, mv[seg], color=BASELINE, alpha=0.12, lw=0)
            ax.plot([p.start_min, p.end_min], [b0, b1], color=BASELINE, lw=1.2)
    for a0, b0, a1, b1 in reference_baselines:
        ax.plot([a0, a1], [b0, b1], color=REFERENCE, ls="--", lw=1.0, zorder=4)
    if reference_baselines:
        handles.append(ax.plot([], [], color=REFERENCE, ls="--", lw=1.0, label=reference_label)[0])

    ax.set_xlim(x0, x1)
    if zoom_to_peaks:
        ylim = view_ylim(run, result, (x0, x1))
        if ylim is not None:
            ax.set_ylim(*ylim)
    elif x_range is not None or (x0, x1) != (float(t[0]), float(t[-1])):
        lo, hi = float(np.min(mv[inside])), float(np.max(mv[inside]))
        pad = 0.05 * (hi - lo) if hi > lo else 1.0
        ax.set_ylim(lo - pad, hi + pad)
    if result is not None and peak_labels != "none":
        _place_labels(ax, run, result, names, peak_labels, (x0, x1), label_size,
                      avoid_label_overlap)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=14, steps=[1, 2, 2.5, 5, 10]))
    if minor_ticks:
        ax.xaxis.set_minor_locator(AutoMinorLocator())
        ax.yaxis.set_minor_locator(AutoMinorLocator())
    if legend and handles:
        ax.legend(handles=handles, loc="upper right", fontsize=7, frameon=False)
    return x0, x1


def _place_labels(ax, run, result, names, mode, x_range, size, avoid_overlap) -> None:
    """Label peaks (named first, then taller), skipping labels whose boxes would overlap."""
    mv = run.microvolts / 1000.0
    x0, x1 = x_range
    y0, y1 = ax.get_ylim()
    bbox = ax.get_window_extent()
    w_in, h_in = bbox.width / ax.figure.dpi, bbox.height / ax.figure.dpi
    text_h = 1.25 * size / 72.0
    boxes: list[tuple[float, float, float, float]] = []
    for p in sorted(result.peaks, key=lambda p: (p.number not in names, -p.height_uv)):
        text = _label(p, names, mode)
        top = mv[p.apex]
        if not text or not (x0 <= p.rt_min <= x1) or not (y0 <= top <= y1):
            continue
        x = (p.rt_min - x0) / (x1 - x0) * w_in
        y = (top - y0) / (y1 - y0) * h_in + 3 / 72.0
        half = TextPath((0, 0), text, size=size).get_extents().width / 72.0 / 2 + 0.02
        if avoid_overlap and any(abs(x - bx) < half + bh and abs(y - by) < text_h
                                 for bx, by, bh, _ in boxes):
            continue
        boxes.append((x, y, half, text_h))
        ax.annotate(text, (p.rt_min, top), textcoords="offset points", xytext=(0, 3),
                    ha="center", fontsize=size, color=BASELINE)


def peak_view_ylim(run: RawRun, result: IntegrationResult | None) -> tuple[float, float] | None:
    """y-range (mV) fitting every unclipped peak over the whole run (kept for callers)."""
    t = run.times_min
    return view_ylim(run, result, (float(t[0]), float(t[-1])))
