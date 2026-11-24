"""Explicit, reversible figure processing; acquisition arrays are never edited."""
import hashlib

import numpy as np


def validate_processing(trace, settings):
    window = settings.smoothing_window
    if type(window) is not int or window not in range(1, 22, 2):
        raise ValueError("Smoothing needs an odd window from 1 to 21 points (1 means Off).")
    if type(settings.normalize) is not bool:
        raise ValueError("Normalization must be on or off.")
    if window > 1 and (trace.plot_kind == "sticks" or trace.x_unit != "min"):
        raise ValueError("Smoothing is available for chromatograms only, not mass channels.")


def process_signal(trace, settings):
    """Centered mean of available samples, then full-trace positive-maximum scale.

    Windows count points, even on an uneven time grid. Short/edge windows use
    only existing samples. No zero padding, resampling, baseline shift or crop.
    """
    validate_processing(trace, settings)
    signal = trace.signal
    window = settings.smoothing_window
    if window > 1:
        kernel = np.ones(window) / window
        start = window // 2
        values = np.convolve(signal, kernel, mode="full")[start:start + len(signal)]
        weights = np.convolve(np.ones(len(signal)), kernel, mode="full")[start:start + len(signal)]
        signal = values / weights
    maximum = float(np.max(signal))
    if settings.normalize:
        if maximum <= 0 and np.any(signal != 0):
            raise ValueError(f"{trace.name}: 100% normalization requires a positive maximum or an all-zero signal.")
        with np.errstate(over="ignore", invalid="ignore"):
            signal = signal / maximum * 100 if maximum > 0 else np.zeros_like(signal)
    if not np.isfinite(signal).all():
        raise ValueError("Processing exceeds the supported numeric range. Use original signal or a smaller smoothing window.")
    signal.flags.writeable = False
    return signal, maximum


def display_signal(trace, settings):
    return process_signal(trace, settings)[0]


def signal_axis_label(trace, settings):
    if settings.normalize:
        return "Relative intensity (%)" if trace.plot_kind == "sticks" else "Normalized signal (%)"
    return settings.y_label


def processing_metadata(trace, settings):
    records = []
    for index, item in enumerate(getattr(trace, "traces", (trace,))):
        signal, maximum = process_signal(item, settings)
        records.append({"trace_id": index + 1,
                        "normalization_denominator": maximum if settings.normalize else None,
                        "all_zero": bool(np.all(signal == 0)),
                        "display_signal_sha256": hashlib.sha256(signal.astype("<f8").tobytes()).hexdigest()})
    return {"smoothing": {"method": "centered moving average" if settings.smoothing_window > 1 else "none",
                          "window_points": settings.smoothing_window,
                          "edges": "Average only available samples; no zero padding.",
                          "sampling": "Point-based window on the original time grid; no resampling."},
            "normalization": "full-trace maximum = 100%" if settings.normalize else "none",
            "order": ["smoothing", "normalization"],
            "scope": "Full trace before view ranges/breaks, independently for each source; source arrays unchanged.",
            "signal_quantity": signal_axis_label(trace, settings),
            "traces": records}


def processing_summary(trace, settings):
    parts = []
    if settings.smoothing_window > 1:
        parts.append(f"Moving average: {settings.smoothing_window} points")
    if settings.normalize:
        parts.append("Base peak = 100%" if trace.plot_kind == "sticks" else "Each full-trace maximum = 100%")
    return " · ".join(parts) if parts else "Original signal · processing off"
