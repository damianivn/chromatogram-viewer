"""Processing smoke for source and packaged apps; optional read-only real MS data."""
from gcviewer.analysis.mass_spectra import eic as ms_eic, spectrum as ms_spectrum, tic as ms_tic
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np


def smoke_processing(window, output, traces=None, spectrum=None, eic=None):
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication
    from gcviewer.figures.workspace import demo_trace, export_figure
    from gcviewer.figures.comparisons import Comparison
    from gcviewer.data_models.spectra import MSFunction
    from gcviewer.reports.numeric import export_csv
    from gcviewer.analysis.processing import display_signal

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance()
    if traces is None:
        a = demo_trace()
        traces = (replace(a, name="Synthetic sample A"), replace(a, name="Synthetic sample B",
                  time=a.time[::3], signal=a.signal[::3] * .02 + .25 * np.sin(a.time[::3] * 150)))
    if spectrum is None:
        function = MSFunction("synthetic://processing-ms", "MS1", np.array([1., 2., 3.]),
                              np.array([43., 44., 91., 105.]),
                              np.array([[0, 10, 0, 30], [20, 0, 40, 0], [40, 20, 0, 60]]), synthetic=True)
        spectrum = ms_spectrum(function, 1, 3)
    originals = [t.signal.copy() for t in traces]
    original_spectrum = spectrum.signal.copy()
    cases = [("individual", traces[0]), ("overlay", Comparison(traces)),
             ("stacked", Comparison(traces)), ("spectrum", spectrum)]
    if eic is not None:
        cases.append(("eic", eic))
    checks = {"cases": {}, "csv_original_values": True}
    for name, report in cases:
        window.add_sample(report)
        if name == "stacked":
            window.change_comparison_mode(1)
        window.smoothing.setCurrentIndex(window.smoothing.findData(1 if name == "spectrum" else 7))
        window.signal_scale.setCurrentIndex(window.signal_scale.findData(True))
        window.change_processing()
        assert not window.error.text(), window.error.text()
        state = window.active.state
        source = report.traces[0] if isinstance(report, Comparison) else report
        values = display_signal(source, state.settings)
        apex = int(np.argmax(values))
        state.add_label(report, float(source.time[apex]), "Base peak" if name == "spectrum" else "Processed maximum")
        window.refresh_labels()
        window.redraw()
        app.processEvents()
        window.canvas.draw()
        assert np.isclose(window.artists[0].xy[1], 100) or not np.any(values)
        assert not window.smoothing.isEnabled() if name == "spectrum" else window.smoothing.isEnabled()
        window.grab().save(str(output / f"{name}-workspace.png"))
        for suffix in ("png", "pdf", "svg", "tif"):
            _, sidecar = export_figure(report, state, output / f"{name}.{suffix}", overwrite=True)
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            assert metadata["processing"]["normalization"] == "full-trace maximum = 100%"
        csv, sidecar = export_csv(report, output / f"{name}.csv", settings=state.settings, overwrite=True)
        rows = np.loadtxt(csv, delimiter=",", skiprows=1, ndmin=2)
        if isinstance(report, Comparison):
            for index, t in enumerate(report.traces, 1):
                np.testing.assert_array_equal(rows[rows[:, 0] == index, 1], t.time)
                np.testing.assert_array_equal(rows[rows[:, 0] == index, 2], t.signal)
        else:
            np.testing.assert_array_equal(rows[:, 0], report.time)
            np.testing.assert_array_equal(rows[:, 1], report.signal)
        assert not json.loads(sidecar.read_text())["figure_processing_applied_to_csv"]
        if name == "stacked":
            state.settings.y_break = (25, 60)
            start, end = float(traces[0].time[0]), float(traces[0].time[-1])
            state.settings.x_break = (start + (end - start) * .4, start + (end - start) * .55)
            export_figure(report, state, output / "stacked-breaks.svg", overwrite=True)
            window.resize(920, 600)
            app.processEvents()
            window.redraw()
            window.canvas.draw()
            window.grab().save(str(output / "stacked-920.png"))
            window.resize(1280, 820)
        checks["cases"][name] = {"smoothing_window": state.settings.smoothing_window,
                                 "normalize": state.settings.normalize, "formats": ["png", "pdf", "svg", "tif", "csv"]}
    for t, signal in zip(traces, originals):
        np.testing.assert_array_equal(t.signal, signal)
    np.testing.assert_array_equal(spectrum.signal, original_spectrum)
    pdf = QPdfDocument()
    assert pdf.load(str(output / "stacked.pdf")) == QPdfDocument.Error.None_
    size = pdf.pagePointSize(0)
    image_size = QSize(1400, round(1400 * size.height() / size.width()))
    pdf.render(0, image_size).save(str(output / "stacked-pdf-render.png"))
    pdf.close()
    svg = QSvgRenderer(str(output / "stacked-breaks.svg"))
    assert svg.isValid()
    raster = QImage(image_size, QImage.Format.Format_ARGB32)
    raster.fill(Qt.GlobalColor.white)
    painter = QPainter(raster)
    svg.render(painter)
    painter.end()
    raster.save(str(output / "stacked-breaks-svg-render.png"))
    checks["source_arrays_unchanged"] = True
    (output / "processing-checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    return checks


def main():
    import argparse
    from PySide6.QtWidgets import QApplication
    from gcviewer.desktop.window import Workspace
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ms-source", type=Path, action="append")
    args = parser.parse_args()
    app = QApplication([])
    app.setStyle("Fusion")
    window = Workspace()
    window.show()
    traces = spectrum = eic = None
    before = {}
    try:
        if args.ms_source:
            from gcviewer.parsers.waters import load_raw
            from gcviewer.analysis.mass_spectra import ms_functions
            traces = []
            for source in args.ms_source:
                before.update({p: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()})
                function = ms_functions(load_raw(str(source)), source)[0]
                traces.append(ms_tic(function))
                if spectrum is None:
                    first, last = len(function.time) // 3, len(function.time) // 2
                    spectrum = ms_spectrum(function, float(function.time[first]), float(function.time[last]))
                    eic = ms_eic(function, float(function.masses[len(function.masses) // 3]))
            traces = tuple(traces)
        checks = smoke_processing(window, args.output, traces, spectrum, eic)
        assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
        checks["source_files_unchanged"] = len(before)
        (args.output / "processing-checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
        print(json.dumps(checks, indent=2))
    finally:
        window.close()


if __name__ == "__main__":
    main()
