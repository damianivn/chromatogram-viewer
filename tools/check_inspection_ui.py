"""Opt-in inspection smoke, shared by source and standalone package checks."""
from gcviewer.analysis.mass_spectra import eic as ms_eic, spectrum as ms_spectrum, tic as ms_tic
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

import numpy as np


def smoke_inspection(window, output, source=None):
    from PySide6.QtWidgets import QApplication
    from gcviewer.desktop.ms_inspector import MSInspector
    from gcviewer.services.acquisition import ms_traces
    from gcviewer.figures.workspace import export_figure
    from gcviewer.data_models.spectra import MSFunction
    from gcviewer.reports.numeric import export_csv
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance()
    before = {}
    start = time.monotonic()
    if source:
        source = Path(source).resolve()
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()}
        from gcviewer.parsers.waters import load_raw
        from gcviewer.analysis.ion_signals import get_tic, get_eic
        acquisition = load_raw(str(source))
        initial = ms_traces(acquisition, source)[0]
        dialog = MSInspector(window, initial)
        dialog.show()
        deadline = time.monotonic() + 40
        while not dialog.functions and time.monotonic() < deadline:
            app.processEvents()
            if dialog.directory is None and dialog.status.text().startswith("Could not"):
                raise AssertionError(dialog.status.text())
            time.sleep(.01)
        assert dialog.functions, dialog.status.text()
        functions = dialog.functions
        for function in functions:
            datafile = next(f for f in acquisition.datafiles if f.name == function.name and f.detector == "MS")
            np.testing.assert_array_equal(function.data, datafile.data)
            np.testing.assert_array_equal(function.time, datafile.xlabels)
            np.testing.assert_array_equal(function.masses, datafile.ylabels)
            np.testing.assert_array_equal(ms_tic(function).signal, get_tic(datafile, sm=1, norm=False)[1])
            requested = float(function.masses[len(function.masses) // 3]) + .1
            requested = min(requested, float(function.masses[-1]))
            np.testing.assert_array_equal(ms_eic(function, requested).signal, get_eic(datafile, requested, sm=1)[1])
            first, last = len(function.time) // 3, len(function.time) // 2
            mean = ms_spectrum(function, float(function.time[first]), float(function.time[last]))
            np.testing.assert_array_equal(mean.signal, datafile.data[first:last + 1].astype(float).mean(axis=0))
            single = ms_spectrum(function, float(function.time[first]))
            np.testing.assert_array_equal(single.signal, datafile.data[first].astype(float))
    else:
        time_values = np.array([1., 1.2, 1.4, 2.])
        masses = np.array([43., 44., 91., 105.])
        counts = np.array([[0, 10, 0, 30], [20, 0, 40, 0], [40, 20, 0, 60], [80, 0, 20, 0]], dtype=np.uint32)
        one = MSFunction("synthetic://mass-matrix", "MS1", time_values, masses, counts, synthetic=True)
        functions = [one, replace(one, name="MS2", data=counts * 2)]
        dialog = MSInspector(window, ms_tic(one), autoload=False)
        dialog.set_functions(functions)
        dialog.show()
    try:
        dialog.function.setCurrentIndex(len(functions) - 1)
        function = functions[-1]
        results = {"function_count": len(functions), "selected_function": function.name,
                   "matrix_bytes": sum(f.data.nbytes for f in functions), "selections": {}}
        dialog.mz.setText(str(min(max(90.8, float(function.masses[0])), float(function.masses[-1]))))
        first, last = len(function.time) // 3, len(function.time) // 2
        for mode in ("eic", "single", "mean"):
            dialog.mode.setCurrentIndex(dialog.mode.findData(mode))
            dialog.start.setText(repr(float(function.time[first])))
            dialog.end.setText(repr(float(function.time[last])))
            assert dialog.update_preview(), dialog.status.text()
            app.processEvents()
            dialog.redraw()
            dialog.canvas.draw()
            app.processEvents()
            assert all(editor.height() >= editor.sizeHint().height() for _, editor in dialog.input_rows if editor.isVisible())
            dialog.grab().save(str(output / f"{mode}-inspector.png"))
            trace = dialog.trace
            results["selections"][mode] = trace.metadata["selection"]
            for suffix in ("png", "pdf", "svg", "tif"):
                export_figure(trace, dialog.state, output / f"{mode}.{suffix}", overwrite=True)
            export_csv(trace, output / f"{mode}.csv", overwrite=True)
            rows = np.loadtxt(output / f"{mode}.csv", delimiter=",", skiprows=1, ndmin=2)
            np.testing.assert_array_equal(rows[:, 0], trace.time)
            np.testing.assert_array_equal(rows[:, 1], trace.signal)
        assert dialog.trace.plot_kind == "sticks"
        original = window.active
        labels = list(original.state.labels)
        settings = original.state.settings
        dialog.report_requested.connect(window.add_inspection_report)
        dialog.create_report()
        assert window.active.trace.plot_kind == "sticks"
        assert original.state.settings is settings and original.state.labels == labels
        app.processEvents()
        window.redraw()
        window.canvas.draw()
        window.grab().save(str(output / "spectrum-workspace.png"))
        assert not dialog.functions and dialog.loader.process is None and dialog.directory is None
        if before:
            after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()}
            assert before == after
        results["source_files_unchanged"] = len(before)
        results["elapsed_seconds"] = round(time.monotonic() - start, 3)
        (output / "inspection-checks.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        return results
    finally:
        dialog.reject()
        dialog.deleteLater()


def main():
    import argparse
    from PySide6.QtWidgets import QApplication
    from gcviewer.desktop.window import Workspace
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    app = QApplication([])
    app.setStyle("Fusion")
    window = Workspace()
    window.show()
    app.processEvents()
    try:
        print(json.dumps(smoke_inspection(window, args.output, args.source), indent=2))
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    main()
