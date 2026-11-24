"""Offscreen acceptance of physical figure presets and dense real sample navigation."""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "ChromatogramViewer-matplotlib"))

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PIL import Image
from pypdf import PdfReader
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from tools.check_library import wait_until
from gcviewer.services.library import LibraryEntry, discover_library
from gcviewer.desktop.window import Workspace, FIGURE_SIZE_PRESETS
from gcviewer.figures.workspace import export_figure, render_figure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--spl", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    source_folder = args.folder.resolve()
    if output == source_folder or source_folder in output.parents:
        raise ValueError("Save evidence outside the acquisition folder")
    output.mkdir(parents=True, exist_ok=True)
    entries = [LibraryEntry(**e) for e in discover_library(source_folder, "ms", args.spl)["entries"] if e["available"]][:32]
    def hashes():
        result = {}
        for entry in entries:
            for path in Path(entry.path).rglob("*"):
                if path.is_file():
                    with path.open("rb") as handle:
                        result[str(path)] = hashlib.file_digest(handle, "sha256").hexdigest()
        return result
    before = hashes()
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    window = Workspace()
    results = {"scope": "Real acquisitions in place; offscreen Qt preset/list interactions and PNG/PDF/SVG geometry. Not manual desktop validation.", "presets": []}
    try:
        window.show()
        keys = window.open_library_entries(entries)
        wait_until(lambda: not window.jobs and not window.pending)
        assert not window.failures, window.failures
        assert len(keys) == len(entries)
        window.sample_list.setCurrentItem(window.find_item(keys[0]))
        sample = window.active
        original = sample.trace.signal.copy()
        peak = float(sample.trace.time[np.argmax(sample.trace.signal)])
        sample.state.add_label(sample.trace, peak, "Selected peak", (.58, .84))
        labels = [asdict(label) for label in sample.state.labels]
        for index, (name, size) in enumerate(FIGURE_SIZE_PRESETS):
            if size is None:
                continue
            window.size_preset.setCurrentIndex(index)
            window.size_preset.activated.emit(index)
            app.processEvents()
            window.canvas.draw()
            settings = sample.state.settings
            assert (settings.width_mm, settings.height_mm) == size
            assert abs(window.canvas.width() / window.canvas.height() - size[0] / size[1]) < .02
            assert [asdict(label) for label in sample.state.labels] == labels
            np.testing.assert_array_equal(sample.trace.signal, original)
            fig, ax, _ = render_figure(sample.trace, sample.state)
            assert not fig.texts, "Experimental figures must not carry a provenance footer"
            assert ax.xaxis.label.get_fontsize() == window.fields["font_size"].value()
            canvas = FigureCanvasAgg(fig)
            canvas.draw()
            renderer = canvas.get_renderer()
            xlabels = [label for location, label in zip(ax.get_xticks(), ax.get_xticklabels()) if ax.get_xlim()[0] <= location <= ax.get_xlim()[1]]
            ylabels = [label for location, label in zip(ax.get_yticks(), ax.get_yticklabels()) if ax.get_ylim()[0] <= location <= ax.get_ylim()[1]]
            texts = [ax.xaxis.label, ax.yaxis.label, ax.title, *xlabels, *ylabels, *fig.texts]
            for text in texts:
                if not text.get_visible() or not text.get_text():
                    continue
                bounds = text.get_window_extent(renderer)
                assert bounds.x0 >= -1 and bounds.y0 >= -1 and bounds.x1 <= fig.bbox.width + 1 and bounds.y1 <= fig.bbox.height + 1, (name, text.get_text(), bounds.bounds, fig.bbox.bounds)
            base = output / f"preset-{index}"
            for suffix in ("png", "pdf", "svg"):
                export_figure(sample.trace, sample.state, base.with_suffix("." + suffix), overwrite=True)
            with Image.open(base.with_suffix(".png")) as raster:
                assert raster.size == tuple(int(mm / 25.4 * settings.dpi) for mm in size)
            page = PdfReader(base.with_suffix(".pdf")).pages[0]
            assert abs(float(page.mediabox.width) - size[0] / 25.4 * 72) < .001
            assert abs(float(page.mediabox.height) - size[1] / 25.4 * 72) < .001
            assert not page.images
            assert "<image" not in base.with_suffix(".svg").read_text(encoding="utf-8")
            results["presets"].append({"name": name, "width_mm": size[0], "height_mm": size[1],
                                       "font_size_pt": ax.xaxis.label.get_fontsize(), "font_family": ax.xaxis.label.get_fontfamily(),
                                       "geometry_and_labels": "passed"})
        window.fields["width_mm"].setValue(175.5)
        assert sample.state.settings.width_mm == 175.5
        assert window.size_preset.currentIndex() == 0
        window.sample_list.setCurrentItem(window.find_item(keys[1]))
        assert window.active.state.settings.width_mm == 180
        window.sample_list.setCurrentItem(window.find_item(keys[0]))
        assert window.fields["width_mm"].value() == 175.5
        assert window.size_preset.currentIndex() == 0
        window.size_preset.setCurrentIndex(len(FIGURE_SIZE_PRESETS) - 1)
        window.size_preset.activated.emit(len(FIGURE_SIZE_PRESETS) - 1)
        window.sample_search.setText(entries[1].name)
        window.sample_search.clear()
        assert window.active.trace.source == entries[0].path
        QTest.qWait(100)
        window.canvas.draw()
        visible = sum(window.sample_list.viewport().rect().contains(window.sample_list.visualItemRect(window.sample_list.item(i)))
                      for i in range(window.sample_list.count()))
        assert visible >= 20, visible
        results.update(loaded_sources=len(keys), fully_visible_rows=visible,
                       row_height=window.sample_list.sizeHintForRow(0), custom_size_and_sample_switch="passed")
        assert window.grab().save(str(output / "workspace-wide.png"))
        window.resize(1024, 768)
        QTest.qWait(120)
        window.canvas.draw()
        assert window.canvas.buffer_rgba().shape[:2] == (window.canvas.height(), window.canvas.width())
        assert window.grab().save(str(output / "workspace-1024.png"))
    finally:
        window.close()
        app.processEvents()
    assert hashes() == before
    results["unchanged_source_files"] = len(before)
    (output / "layout-check.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
