"""Thin adapters around existing parsers; no Qt or Streamlit imports."""
from pathlib import Path
import numpy as np
from gcviewer.data_models.acquisition import Trace
from gcviewer.services.fid_acquisition import fid_trace


def ms_traces(acquisition, source):
    """Use rainbow DataFile.detector/name, not an assumed function ordering."""
    from gcviewer.analysis.ion_signals import get_tic
    candidates, rejected = [], []
    for datafile in acquisition.datafiles:
        if datafile.detector != "MS":
            continue
        try:
            data = np.asarray(datafile.data)
            masses = np.asarray(datafile.ylabels)
            if data.ndim != 2 or masses.ndim != 1 or not masses.size or data.shape != (len(datafile.xlabels), len(masses)):
                raise ValueError("MS time/mass matrix dimensions do not match")
            if not np.isfinite(data).all() or not np.isfinite(masses).all():
                raise ValueError("MS data contains non-finite values")
            time, signal = get_tic(datafile, sm=1, norm=False)
            candidates.append(Trace(Path(source).name, str(Path(source).resolve()), "GC-MS", time, signal,
                function=datafile.name, y_label="Total ion signal (counts)",
                metadata={"directory": acquisition.metadata, "function": datafile.metadata,
                          "mass_channels": len(masses)},
                transformations=("TIC: sum of all mass channels per scan; smoothing disabled; normalization disabled.",)))
        except (ValueError, TypeError, IndexError) as exc:
            rejected.append(f"{datafile.name}: {exc}")
    if not candidates:
        detail = "; ".join(rejected) or "No DataFile with detector MS was found."
        raise ValueError(f"No usable MS functions. {detail}")
    if rejected:
        from dataclasses import replace
        candidates = [replace(trace, warnings=("Excluded invalid MS functions: " + "; ".join(rejected),)) for trace in candidates]
    return candidates


def load_source(path, kind):
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() != ".raw":
        raise ValueError("Select a .raw acquisition: a directory for GC-MS or a PENX file for GC-FID.")
    if kind == "ms":
        if not path.is_dir():
            raise ValueError("GC-MS needs a .raw directory, not a single file.")
        from gcviewer.parsers.waters import load_raw
        return ms_traces(load_raw(str(path)), path)
    if kind != "fid":
        raise ValueError("Unknown instrument type.")
    if not path.is_file():
        raise ValueError("GC-FID needs a PENX .raw file, not a directory.")
    return [fid_trace(load_fid(path))]


def load_fid(path):
    from gcviewer.parsers.totalchrom import read_raw
    from gcviewer.parsers.totalchrom.discovery import is_penx_file
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() != ".raw" or not path.is_file():
        raise ValueError("GC-FID needs a PENX .raw file, not a directory.")
    if not is_penx_file(path):
        raise ValueError("This file does not have a supported PENX TotalChrom header.")
    return read_raw(path)
