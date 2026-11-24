"""Validated mass-channel data and explicit, unprocessed GC-MS selections.

The desktop loads these matrices on demand, independently of lightweight TICs.
No Qt or Streamlit dependency. Arrays retain original counts and scan times.
"""
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from gcviewer.data_models.acquisition import Trace


from gcviewer.data_models.spectra import MSFunction


def _trace(function, x, y, label, selection, transformation, *, spectrum=False):
    return Trace(f"{Path(function.source).name} Â· {label}", function.source, "GC-MS", x, y,
                 function=function.name, y_label="Ion signal (counts)" if not spectrum else "Ion intensity (counts)",
                 metadata={**function.metadata, "selection": selection, "mass_channels": len(function.masses)},
                 transformations=(transformation, "Smoothing disabled; normalization disabled."),
                 warnings=function.warnings, synthetic=function.synthetic, x_label="m/z" if spectrum else "Retention time (min)",
                 x_unit="m/z" if spectrum else "min", plot_kind="sticks" if spectrum else "line")

def tic(function):
    from gcviewer.analysis.ion_signals import get_tic
    x, y = get_tic(SimpleNamespace(xlabels=function.time, data=function.data), sm=1, norm=False)
    return _trace(function, x, y, "TIC", {"kind": "tic"}, "TIC: sum of all mass channels per scan.")

def eic(function, requested_mz):
    from gcviewer.analysis.ion_signals import get_eic
    requested = float(requested_mz)
    if not np.isfinite(requested) or not function.masses[0] <= requested <= function.masses[-1]:
        raise ValueError(f"Requested m/z must be within {function.masses[0]:g}â€“{function.masses[-1]:g}.")
    x, y, actual = get_eic(SimpleNamespace(xlabels=function.time, ylabels=function.masses, data=function.data), requested, sm=1)
    return _trace(function, x, y, f"EIC {actual:g}",
                       {"kind": "eic", "requested_mz": requested, "actual_mz": float(actual),
                        "channel_index": int(np.argmin(np.abs(function.masses - requested))),
                        "method": "Nearest recorded channel; ties use the lower m/z. No mass window or interpolation."},
                       f"EIC: requested m/z {requested:g}; extracted nearest recorded channel m/z {actual:g}.")

def spectrum(function, start, end=None):
    start = float(start)
    if not np.isfinite(start) or not function.time[0] <= start <= function.time[-1]:
        raise ValueError(f"Scan time must be within {function.time[0]:g}â€“{function.time[-1]:g} min.")
    if end is None:
        first = int(np.argmin(np.abs(function.time - start)))
        stop = first + 1
        requested = [start]
        method = "Nearest recorded scan; ties use the earlier scan."
    else:
        end = float(end)
        if not np.isfinite(end) or end <= start or end > function.time[-1]:
            raise ValueError(f"Interval needs From < To within {function.time[0]:g}â€“{function.time[-1]:g} min.")
        first = int(np.searchsorted(function.time, start, side="left"))
        stop = int(np.searchsorted(function.time, end, side="right"))
        if stop <= first:
            raise ValueError("No scans fall inside this interval. Widen the interval.")
        requested = [start, end]
        method = "Arithmetic mean of scans inside the inclusive interval; equal weight per scan."
    signal = function.data[first:stop].astype(float).mean(axis=0)
    actual = [float(function.time[first]), float(function.time[stop - 1])]
    label = f"Spectrum {actual[0]:.5g} min" if end is None else f"Mean spectrum {actual[0]:.5g}â€“{actual[1]:.5g} min"
    return _trace(function, function.masses, signal, label,
                       {"kind": "spectrum", "requested_time_min": requested, "actual_time_min": actual,
                        "scan_count": stop - first, "first_scan_index": first, "last_scan_index": stop - 1,
                        "method": method}, f"{method} Actual coverage {actual[0]:.9g}â€“{actual[1]:.9g} min; {stop-first} scan(s).",
                       spectrum=True)


def ms_functions(acquisition, source):
    """Exclude non-MS and malformed functions, disclosing any exclusions."""
    from dataclasses import replace
    functions, rejected = [], []
    for datafile in acquisition.datafiles:
        if datafile.detector != "MS":
            continue
        try:
            functions.append(MSFunction(str(Path(source).resolve()), datafile.name,
                                        datafile.xlabels, datafile.ylabels, datafile.data,
                                        {"directory": acquisition.metadata, "function": datafile.metadata}))
        except (ValueError, TypeError, IndexError) as exc:
            rejected.append(f"{datafile.name}: {exc}")
    if not functions:
        raise ValueError("No usable MS functions. " + ("; ".join(rejected) or "No detector MS was found."))
    if rejected:
        functions = [replace(f, warnings=("Excluded invalid MS functions: " + "; ".join(rejected),)) for f in functions]
    return functions
