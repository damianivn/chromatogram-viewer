"""Opt-in visual/real-source acceptance for one break on each axis."""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.font_manager import findfont
from PIL import Image
from pypdf import PdfReader
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontDatabase, QImage, QPainter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gcviewer.services.acquisition import load_source
from gcviewer.desktop.window import Workspace
from gcviewer.figures.styles import FIGURE_STYLES, figure_size_presets
from gcviewer.figures.workspace import demo_trace, export_figure, render_figure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if any(path.suffix.lower() == ".raw" for path in (output, *output.parents)):
        raise ValueError("Keep evidence outside acquisitions.")
    output.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve() if args.source else None
    def hashes():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()} if source else {}
    before = hashes()
    trace = load_source(source, "ms")[0] if source else demo_trace()
    original = trace.signal.copy()
    span = float(trace.time[-1] - trace.time[0])
    xb = (float(trace.time[0] + span * .25), float(trace.time[0] + span * .5))
    yb = (float(np.max(trace.signal) * .25), float(np.max(trace.signal) * .65))
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    QFontDatabase.addApplicationFont(findfont("Arial"))
    window = Workspace()
    results = []
    try:
        window.show()
        window.add_sample(trace)
        state = window.active.state
        for mode, xbreak, ybreak in (("time", xb, None), ("signal", None, yb), ("both", xb, yb)):
            for style in FIGURE_STYLES:
                for index, (label, size) in enumerate(figure_size_presets(style)):
                    if size is None:
                        continue
                    state.settings = replace(state.settings, x_break=xbreak, y_break=ybreak,
                        width_mm=size[0], height_mm=size[1], publication_style=style, dpi=180)
                    fig, primary, _ = render_figure(trace, state)
                    canvas = FigureCanvasAgg(fig)
                    canvas.draw()
                    renderer = canvas.get_renderer()
                    texts = [primary.title, primary.xaxis.label, primary.yaxis.label]
                    for ax in fig.report_panels:
                        for axis in (ax.xaxis, ax.yaxis):
                            lo, hi = axis.get_view_interval()
                            texts += [tick.label1 for tick in axis.get_major_ticks()
                                      if lo <= tick.get_loc() <= hi and tick.label1.get_visible()]
                    for text in texts:
                        box = text.get_window_extent(renderer)
                        assert box.x0 >= -1 and box.y0 >= -1 and box.x1 <= fig.bbox.width + 1 and box.y1 <= fig.bbox.height + 1, (mode, style, label, text.get_text(), box.bounds)
                    np.testing.assert_array_equal(trace.signal, original)
                    results.append({"mode": mode, "style": style, "layout": label, "geometry": "passed"})
                    if style == "general" and index in (1, 2, 5) or style == "analytical_chemistry" and index == 5:
                        prefix = output / f"{mode}-{style}-{index}"
                        for suffix in ("png", "pdf", "svg", "tif"):
                            export_figure(trace, state, prefix.with_suffix("." + suffix), overwrite=True)
                        page = PdfReader(prefix.with_suffix(".pdf")).pages[0]
                        assert not page.images
                        assert abs(float(page.mediabox.width) - size[0] / 25.4 * 72) < .001
                        for font in page["/Resources"]["/Font"].values():
                            font = font.get_object()
                            assert "/FontFile2" in font["/DescendantFonts"][0].get_object()["/FontDescriptor"]
                        svg_text = prefix.with_suffix(".svg").read_text(encoding="utf-8")
                        assert "<text" in svg_text and "<image" not in svg_text
                        with Image.open(prefix.with_suffix(".png")) as png:
                            pixels = QSize(*png.size)
                        with Image.open(prefix.with_suffix(".tif")) as tif:
                            assert tif.size == (pixels.width(), pixels.height())
                        doc = QPdfDocument()
                        assert doc.load(str(prefix.with_suffix(".pdf"))) == QPdfDocument.Error.None_
                        assert doc.render(0, pixels).save(str(prefix) + "-pdf.png")
                        doc.close()
                        svg = QSvgRenderer(str(prefix.with_suffix(".svg")))
                        assert svg.isValid()
                        raster = QImage(pixels, QImage.Format.Format_ARGB32)
                        raster.fill(Qt.GlobalColor.white)
                        painter = QPainter(raster)
                        svg.render(painter)
                        painter.end()
                        assert raster.save(str(prefix) + "-svg.png")
        state.settings = replace(state.settings, publication_style="general", width_mm=180, height_mm=110)
        keep = (trace.time <= xb[0]) | (trace.time >= xb[1])
        peak = int(np.argmax(np.where(keep, trace.signal, -np.inf)))
        state.add_label(trace, float(trace.time[peak]), "Selected peak", (.6, .86))
        anchors = [asdict(label) for label in state.labels]
        window.populate_settings()
        window.refresh_labels()
        window.redraw()
        QTest.qWait(100)
        window.canvas.draw()
        window.grab().save(str(output / "workspace.png"))
        export_figure(trace, state, output / "annotated.pdf", overwrite=True)
        export_figure(trace, state, output / "annotated.png", overwrite=True)
        assert [asdict(label) for label in state.labels] == anchors
    finally:
        window.close()
        app.processEvents()
    assert hashes() == before
    evidence = {"scope": "Offscreen source UI, real acquisition read in place if supplied, independent PDF/SVG rasterization; no native/manual claim.",
                "layouts": results, "unchanged_source_files": len(before)}
    (output / "axis-break-check.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(f"Passed {len(results)} break/style/layout checks; {len(before)} source files unchanged.")


if __name__ == "__main__":
    main()
