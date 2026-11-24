"""Packaged GUI smoke for the structural PENX fixture from check_package."""
import csv
import hashlib
import json
from pathlib import Path
import time

import numpy as np


def smoke_fid(window, output, source):
    from PySide6.QtWidgets import QApplication
    from gcviewer.figures.workspace import export_figure, y_axis_display
    from gcviewer.reports.numeric import export_csv

    output, source = Path(output), Path(source)
    output.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    key = window.start_load(source, "fid", origin_key="package-fid-check")
    deadline = time.monotonic() + 30
    while window.jobs or window.pending:
        QApplication.processEvents()
        if time.monotonic() > deadline:
            raise TimeoutError("Packaged FID GUI load did not finish")
        time.sleep(.025)
    assert not window.failures, window.failures
    sample = window.samples[key]
    assert window.active is sample and sample.fid_run is not None
    run, trace = sample.fid_run, sample.trace
    np.testing.assert_array_equal(run.counts, [-100, 0, 100, 500, 20])
    np.testing.assert_array_equal(trace.signal, [-12.5, 0, 12.5, 62.5, 2.5])
    np.testing.assert_allclose(trace.time, .25 + np.arange(1, 6) / 750, rtol=0, atol=1e-15)
    assert run.sha256 == source_hash and not run.counts.flags.writeable
    assert y_axis_display(trace, sample.state.settings)["label"] == "Response (mV)"
    assert "µV" in window.break_controls.editors["y_break"][0].toolTip()
    for suffix in ("png", "pdf", "svg", "tif"):
        export_figure(trace, sample.state, output / f"fid.{suffix}", overwrite=True)
        info = json.loads((output / f"fid.{suffix}.json").read_text(encoding="utf-8"))
        assert info["y_axis_display"]["divisor"] == 1000.
        assert info["source_metadata"]["fid_acquisition"]["sha256"] == source_hash
    export_csv(trace, output / "fid.csv", settings=sample.state.settings)
    with (output / "fid.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["Retention time (min)", "Response (µV)"]
    np.testing.assert_array_equal([float(row[1]) for row in rows[1:]], trace.signal)
    QApplication.processEvents()
    assert window.grab().save(str(output / "fid-workspace.png"))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    checks = dict(worker_to_active_sample=True, signed_counts_retained=True,
                  original_time_and_microvolts=True, csv_original_microvolts=True,
                  millivolt_figure_axis=True, four_figure_formats_and_provenance=True,
                  source_unchanged=True)
    (output / "fid-checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
