"""Comparison smoke shared by source and the self-contained package."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path

import numpy as np


def smoke_comparisons(window, output, traces=None):
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication
    from gcviewer.figures.comparisons import Comparison
    from gcviewer.figures.workspace import demo_trace, export_figure
    from gcviewer.reports.numeric import export_csv
    from gcviewer.desktop.comparison_dialog import ComparisonDialog

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance()
    if traces is None:
        a = demo_trace()
        traces = (replace(a, name="Sample A · synthetic"),
                  replace(a, name="Sample B · synthetic", source="synthetic://comparison-B", time=a.time[::3] + .3, signal=a.signal[::3] * .65),
                  replace(a, name="Sample C · synthetic", source="synthetic://comparison-C", time=a.time[::2], signal=a.signal[::2] * .8))
    individual_keys = [window.add_sample(t) for t in traces]
    original = window.active
    original.state.settings.title = "Individual report kept"
    original.state.add_label(original.trace, float(original.trace.time[len(original.trace.time) // 3]), "Individual annotation")
    dialog = ComparisonDialog(window, list(zip(individual_keys, traces)), individual_keys[0])
    dialog.check_rows(True)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(output / "choose-samples.png"))
    dialog.accept()
    assert dialog.comparison is not None
    comparison, state = dialog.comparison, dialog.state
    assert isinstance(comparison, Comparison)
    key = window.add_sample(comparison, state=state)
    dialog.deleteLater()
    state.settings.trace_names = tuple(f"{i + 1}. {t.name}" for i, t in enumerate(traces))
    checks = {"traces": len(traces), "modes": {}, "point_counts": [len(t.time) for t in traces]}
    for mode in ("overlay", "stacked"):
        window.comparison_mode.setCurrentIndex(window.comparison_mode.findData(mode))
        window.change_comparison_mode(window.comparison_mode.currentIndex())
        app.processEvents()
        window.redraw()
        window.canvas.draw()
        window.grab().save(str(output / f"{mode}-workspace.png"))
        for extension in ("png", "pdf", "svg", "tif"):
            target, sidecar = export_figure(comparison, window.active.state, output / f"{mode}.{extension}", overwrite=True)
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            assert metadata["mode"] == mode
            for i, record in enumerate(metadata["traces"]):
                assert record["source"] == traces[i].source and record["function"] == traces[i].function
                assert record["point_count"] == len(traces[i].time)
        pdf = QPdfDocument()
        assert pdf.load(str(output / f"{mode}.pdf")) == QPdfDocument.Error.None_
        image_size = QSize(1400, round(1400 * window.active.state.settings.height_mm / window.active.state.settings.width_mm))
        pdf.render(0, image_size).save(str(output / f"{mode}-pdf-render.png"))
        pdf.close()
        svg = QSvgRenderer(str(output / f"{mode}.svg"))
        assert svg.isValid()
        raster = QImage(image_size, QImage.Format.Format_ARGB32)
        raster.fill(Qt.GlobalColor.white)
        painter = QPainter(raster)
        svg.render(painter)
        painter.end()
        raster.save(str(output / f"{mode}-svg-render.png"))
        checks["modes"][mode] = {"panels": len(window.canvas.figure.report_panels), "formats": ["png", "pdf", "svg", "tif"]}
    export_csv(comparison, output / "comparison.csv", overwrite=True)
    rows = np.loadtxt(output / "comparison.csv", delimiter=",", skiprows=1, ndmin=2)
    for i, trace in enumerate(traces, 1):
        np.testing.assert_array_equal(rows[rows[:, 0] == i, 1], trace.time)
        np.testing.assert_array_equal(rows[rows[:, 0] == i, 2], trace.signal)
    assert original.state.settings.title == "Individual report kept"
    assert original.state.labels[0].text == "Individual annotation"
    window.resize(920, 600)
    app.processEvents()
    window.redraw()
    window.canvas.draw()
    window.grab().save(str(output / "stacked-920.png"))
    window.resize(1280, 820)
    window.sample_list.setCurrentItem(window.find_item(key))
    checks["csv_all_points"] = True
    checks["individual_report_preserved"] = True
    (output / "comparison-checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    return checks


def main():
    import argparse
    from PySide6.QtWidgets import QApplication
    from gcviewer.services.acquisition import load_source
    from gcviewer.desktop.window import Workspace
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ms-source", action="append", type=Path)
    args = parser.parse_args()
    app = QApplication([])
    app.setStyle("Fusion")
    window = Workspace()
    window.show()
    before = {}
    traces = None
    if args.ms_source:
        for source in args.ms_source:
            for file in source.rglob("*"):
                if file.is_file():
                    before[file] = hashlib.sha256(file.read_bytes()).hexdigest()
        traces = tuple(load_source(source, "ms")[0] for source in args.ms_source)
    try:
        checks = smoke_comparisons(window, args.output, traces)
        assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
        checks["source_files_unchanged"] = len(before)
        (args.output / "comparison-checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
        print(json.dumps(checks, indent=2))
    finally:
        window.close()


if __name__ == "__main__":
    main()
