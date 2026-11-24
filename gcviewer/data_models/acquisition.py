"""Immutable source trace data, independent of figure state and GUI."""
from dataclasses import dataclass, field
import numpy as np

@dataclass(frozen=True)
class Trace:
    name: str
    source: str
    instrument: str
    time: np.ndarray
    signal: np.ndarray
    function: str = ""
    y_label: str = "Signal (a.u.)"
    metadata: dict = field(default_factory=dict)
    transformations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    synthetic: bool = False
    x_label: str = "Retention time (min)"
    x_unit: str = "min"
    plot_kind: str = "line"

    def __post_init__(self):
        time = np.array(self.time, dtype=float, copy=True)
        signal = np.array(self.signal, dtype=float, copy=True)
        if time.ndim != 1 or signal.ndim != 1 or len(time) != len(signal):
            raise ValueError("Time and signal must be matching one-dimensional arrays.")
        if self.plot_kind not in ("line", "sticks"):
            raise ValueError("Unsupported trace drawing style.")
        if len(time) < (1 if self.plot_kind == "sticks" else 2):
            raise ValueError("The trace needs at least two data points.")
        if not np.isfinite(time).all() or not np.isfinite(signal).all():
            raise ValueError("The trace contains non-finite time or signal values.")
        if not np.all(np.diff(time) > 0):
            raise ValueError("Retention times must be strictly increasing; data was not reordered.")
        time.flags.writeable = signal.flags.writeable = False
        object.__setattr__(self, "time", time)
        object.__setattr__(self, "signal", signal)


