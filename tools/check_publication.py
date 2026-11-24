"""Opt-in real-acquisition acceptance for publication style/layout/export defaults."""
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
from gcviewer.figures.workspace import export_figure, render_figure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if source == output or source in output.parents:
        raise ValueError("Keep evidence outside the acquisition")
    output.mkdir(parents=True, exist_ok=True)
    def hashes():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file()}
    before = hashes()
    trace = load_source(source, "ms")[0]
    original = trace.signal.copy()
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    window = Workspace()
    QFontDatabase.addApplicationFont(findfont("Arial"))
    results = []
    try:
        window.show()
        window.add_sample(trace)
        state = window.active.state
        state.add_label(trace, float(trace.time[np.argmax(trace.signal)]), "Selected peak", (.58, .84))
        anchors = [asdict(label) for label in state.labels]
        for style in FIGURE_STYLES:
            index = window.figure_style.findData(style)
            window.figure_style.setCurrentIndex(index)
            window.figure_style.activated.emit(index)
            for layout_index, (label, size) in enumerate(figure_size_presets(style)):
                if size is None:
                    continue
                window.size_preset.setCurrentIndex(layout_index)
                window.size_preset.activated.emit(layout_index)
                app.processEvents()
                window.canvas.draw()
                assert (state.settings.width_mm, state.settings.height_mm) == size
                assert [asdict(item) for item in state.labels] == anchors
                np.testing.assert_array_equal(trace.signal, original)
                fig, ax, _ = render_figure(trace, state)
                canvas = FigureCanvasAgg(fig)
                canvas.draw()
                renderer = canvas.get_renderer()
                assert not fig.texts
                texts = [ax.title, ax.xaxis.label, ax.yaxis.label]
                for axis in (ax.xaxis, ax.yaxis):
                    lo, hi = axis.get_view_interval()
                    texts += [tick.label1 for tick in axis.get_major_ticks() if lo <= tick.get_loc() <= hi]
                for text in texts:
                    box = text.get_window_extent(renderer)
                    assert box.x0 >= -1 and box.y0 >= -1 and box.x1 <= fig.bbox.width + 1 and box.y1 <= fig.bbox.height + 1, (style, label, text.get_text(), box.bounds)
                prefix = output / f"{style}-{layout_index}"
                for suffix in ("pdf", "svg"):
                    export_figure(trace, state, prefix.with_suffix("." + suffix), overwrite=True)
                page = PdfReader(prefix.with_suffix(".pdf")).pages[0]
                assert abs(float(page.mediabox.width) - size[0] / 25.4 * 72) < .001
                assert abs(float(page.mediabox.height) - size[1] / 25.4 * 72) < .001
                assert not page.images
                assert "Selected peak" in page.extract_text()
                for font in page["/Resources"]["/Font"].values():
                    font = font.get_object()
                    assert font["/Subtype"] == "/Type0"
                    assert "/FontFile2" in font["/DescendantFonts"][0].get_object()["/FontDescriptor"]
                svg_text = prefix.with_suffix(".svg").read_text(encoding="utf-8")
                assert "<text" in svg_text and "<image" not in svg_text
                preview = replace(state, settings=replace(state.settings, dpi=200))
                export_figure(trace, preview, prefix.with_suffix(".png"), overwrite=True)
                with Image.open(prefix.with_suffix(".png")) as png:
                    pixels = QSize(*png.size)
                if layout_index in (2, 5):
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
                if layout_index == 2:
                    export_figure(trace, state, prefix.with_suffix(".tif"), overwrite=True)
                    with Image.open(prefix.with_suffix(".tif")) as tif:
                        assert tif.info["dpi"] == (state.settings.dpi, state.settings.dpi)
                        assert tif.size == tuple(int(mm / 25.4 * state.settings.dpi) for mm in size)
                results.append({"style": style, "layout": label, "font_pt": ax.xaxis.label.get_fontsize(),
                                "raster_dpi": state.settings.dpi, "geometry_fonts_text_and_identity": "passed"})
            QTest.qWait(100)
            window.canvas.draw()
            assert window.grab().save(str(output / f"{style}-workspace.png"))
    finally:
        window.close()
        app.processEvents()
    assert hashes() == before
    evidence = {"scope": "Real acquisition read in place; offscreen Qt and independent PDF/SVG rendering, no manual claim",
                "layouts": results, "unchanged_source_files": len(before)}
    (output / "publication-check.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
