"""Full-resolution numeric exports; display zoom/breaks never crop the data."""
import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile

import numpy as np

from gcviewer.figures.workspace import export_paths, is_comparison


def export_csv(trace, path, *, overwrite=False, settings=None):
    target, sidecar = export_paths(path, trace, extensions=(".csv",))
    if not overwrite and (target.exists() or sidecar.exists()):
        raise FileExistsError("The data export or metadata sidecar already exists.")
    if is_comparison(trace):
        from gcviewer.figures.comparisons import trace_record
        metadata = {"schema": "chromatogram-comparison-data-v1", "traces": [trace_record(t, i) for i, t in enumerate(trace.traces)],
                    "scope": "All original points, in trace order with a stable trace_id; independent time grids, no resampling or processing. Figure ranges and breaks do not crop numeric data."}
    else:
        metadata = trace_metadata(trace)
    if settings is not None:
        from gcviewer.analysis.processing import processing_metadata
        metadata["figure_processing"] = processing_metadata(trace, settings)
        metadata["figure_processing_applied_to_csv"] = False
        metadata["figure_processing_note"] = "Recorded for context only. CSV retains original trace values; smoothing/normalization, ranges and breaks from the figure are not applied. Spectrum relative intensity is the separately named original-data column."
    staged = []
    try:
        for suffix in (".csv", ".json"):
            fd, name = tempfile.mkstemp(prefix=".data-", suffix=suffix, dir=target.parent)
            os.close(fd)
            staged.append(Path(name))
        with staged[0].open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if is_comparison(trace):
                writer.writerow(["trace_id", trace.x_label, trace.y_label])
                for index, item in enumerate(trace.traces):
                    writer.writerows((index + 1, format(x, ".17g"), format(y, ".17g")) for x, y in zip(item.time, item.signal))
            else:
                spectrum = trace.plot_kind == "sticks"
                writer.writerow([trace.x_label, trace.y_label] + (["Relative intensity (%)"] if spectrum else []))
                base = float(np.max(trace.signal))
                for x, y in zip(trace.time, trace.signal):
                    writer.writerow([format(x, ".17g"), format(y, ".17g")] +
                                    ([format(y / base * 100 if base > 0 else 0, ".17g")] if spectrum else []))
                if spectrum:
                    metadata["relative_column"] = "100 × intensity / largest intensity; all zero if no positive base peak. Raw counts are retained in the intensity column."
        staged[1].write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        if not overwrite and (target.exists() or sidecar.exists()):
            raise FileExistsError("The data export or metadata sidecar already exists.")
        os.replace(staged[0], target)
        os.replace(staged[1], sidecar)
    finally:
        for file in staged:
            file.unlink(missing_ok=True)
    return target, sidecar


def trace_metadata(trace):
    checksum = hashlib.sha256(trace.time.astype("<f8").tobytes() + trace.signal.astype("<f8").tobytes()).hexdigest()
    return {"schema": "chromatogram-data-v1", "source": trace.source, "sample": trace.name,
                "instrument": trace.instrument, "function": trace.function, "synthetic": trace.synthetic,
                "x_quantity": trace.x_label, "x_unit": trace.x_unit, "signal_quantity": trace.y_label,
                "point_count": len(trace.time), "trace_sha256": checksum,
                "source_metadata": trace.metadata, "transformations": list(trace.transformations),
                "warnings": list(trace.warnings),
                "scope": "All points of this derived trace, including zero channels; figure ranges and breaks do not crop numeric data."}
