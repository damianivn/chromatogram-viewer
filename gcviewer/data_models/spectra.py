"""Validated, immutable mass-channel arrays; selection algorithms live in analysis."""
from dataclasses import dataclass, field
import numpy as np

@dataclass(frozen=True)
class MSFunction:
    source: str
    name: str
    time: np.ndarray
    masses: np.ndarray
    data: np.ndarray
    metadata: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    synthetic: bool = False

    def __post_init__(self):
        time, masses, data = (np.array(a, copy=True) for a in (self.time, self.masses, self.data))
        if time.ndim != 1 or masses.ndim != 1 or data.shape != (len(time), len(masses)):
            raise ValueError("MS scan times, mass channels and matrix dimensions do not match.")
        if len(time) < 2 or not len(masses):
            raise ValueError("An MS function needs at least two scans and one mass channel.")
        if not all(np.issubdtype(a.dtype, np.number) and not np.iscomplexobj(a) for a in (time, masses, data)):
            raise ValueError("MS arrays must contain real numeric values.")
        if not all(np.isfinite(a).all() for a in (time, masses, data)):
            raise ValueError("MS arrays contain non-finite values.")
        if not np.all(np.diff(time.astype(float)) > 0) or not np.all(np.diff(masses.astype(float)) > 0):
            raise ValueError("Scan times and mass channels must be strictly increasing; data was not reordered.")
        if np.any(masses <= 0):
            raise ValueError("Mass channels must be positive m/z values.")
        for name, values in (("time", time), ("masses", masses), ("data", data)):
            values.flags.writeable = False
            object.__setattr__(self, name, values)
        object.__setattr__(self, "warnings", tuple(self.warnings))

