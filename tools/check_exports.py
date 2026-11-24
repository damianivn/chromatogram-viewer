"""Repeatable offscreen visual evidence; does not claim native/manual validation.

Run: python -m tools.check_exports --output <evidence-directory>
QtPdf/QtSvg rasterizations are independent export inspections, not app renderers.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "ChromatogramViewer-matplotlib"))

import numpy as np
from PIL import Image
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gcviewer.figures.workspace import demo_trace, export_figure
from gcviewer.desktop.window import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    window = Workspace()
    window.add_sample(demo_trace())
    window.show()
    QTest.qWait(120)
    window.canvas.draw()

    def point(xy):
        ratio = window.canvas.devicePixelRatioF()
        return QPoint(round(xy[0] / ratio), round(window.canvas.height() - xy[1] / ratio))

    for time, text, position in ((5.05, "Peak A", (.30, .75)), (5.3, "Peak B", (.52, .91)), (5.53, "Peak C", (.73, .75))):
        click = point(window.axes.transData.transform((time, 65)))
        QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton, pos=click)
        app.processEvents()
        window.canvas.draw()
        label = window.active.state.labels[-1]
        start = point(window.axes.transAxes.transform(label.position))
        end = point(window.axes.transAxes.transform(position))
        QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(window.canvas, end, 20)
        QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=end)
        window.label_text.setText(text)
        window.edit_label()
        app.processEvents()
        window.canvas.draw()
    window.fields["title"].setText("Crowded peaks · report example")
    window.fields["x_label"].setText("Retention time / min")
    window.fields["y_label"].setText("Synthetic response / a.u.")
    window.fields["width_mm"].setValue(160)
    window.fields["height_mm"].setValue(100)
    window.fields["dpi"].setValue(200)
    assert window.apply_settings()
    app.processEvents()
    window.canvas.draw()
    window.grab().save(str(output / "workspace-1280.png"))
    window.canvas.grab().save(str(output / "preview.png"))
    for suffix in ("png", "pdf", "svg"):
        export_figure(window.active.trace, window.active.state, output / f"crowded-report.{suffix}", overwrite=True)
    with Image.open(output / "crowded-report.png") as png:
        size = png.size
    doc = QPdfDocument()
    error = doc.load(str(output / "crowded-report.pdf"))
    if error != QPdfDocument.Error.None_:
        raise RuntimeError(f"PDF inspection failed: {error}")
    doc.render(0, QSize(*size)).save(str(output / "pdf-render.png"))
    doc.close()
    svg = QSvgRenderer(str(output / "crowded-report.svg"))
    if not svg.isValid():
        raise RuntimeError("SVG inspection failed")
    raster = QImage(QSize(*size), QImage.Format.Format_ARGB32)
    raster.fill(Qt.GlobalColor.white)
    painter = QPainter(raster)
    svg.render(painter)
    painter.end()
    raster.save(str(output / "svg-render.png"))
    baseline = np.array(Image.open(output / "crowded-report.png").convert("RGB"), dtype=float)
    metrics = {}
    for name in ("pdf-render.png", "svg-render.png"):
        actual = np.array(Image.open(output / name).convert("RGB"), dtype=float)
        difference = np.abs(actual - baseline)
        metrics[name] = {"mean_absolute_channel_error_0_to_255": float(difference.mean()),
                         "fraction_pixels_any_channel_difference_over_32": float(np.mean(difference.max(axis=2) > 32))}
    preview = Image.open(output / "preview.png").convert("RGB")
    resized = Image.open(output / "crowded-report.png").convert("RGB").resize(preview.size, Image.Resampling.LANCZOS)
    metrics["preview_vs_resized_png"] = {"mean_absolute_channel_error_0_to_255": float(np.abs(np.array(preview, dtype=float) - np.array(resized, dtype=float)).mean()), "preview_pixels": preview.size}
    window.resize(1024, 768)
    QTest.qWait(150)
    window.canvas.draw()
    window.grab().save(str(output / "workspace-1024.png"))
    (output / "inspection.json").write_text(json.dumps({"scope": "synthetic offscreen Qt gestures and independent PDF/SVG rasterization; no manual GUI claim",
        "png_pixels": size, "page_mm": [160, 100], "png_dpi": 200, "differences": metrics}, indent=2), encoding="utf-8")
    window.close()
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
