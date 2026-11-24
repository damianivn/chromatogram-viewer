"""Owner feedback: bounded warm loading, priority, navigation and honest axes."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "ChromatogramViewer-matplotlib"))

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PySide6.QtCore import QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gcviewer.services.library import LibraryEntry
from gcviewer.services.worker import write_result
from gcviewer.desktop.sample_list import STATUS_ROLE
from tests.desktop.test_library import synthetic_penx
from gcviewer.desktop.window import Workspace
from gcviewer.figures.styles import figure_size_presets
from gcviewer.data_models.acquisition import Trace
from gcviewer.figures.workspace import FigureState, demo_trace, render_figure, export_figure, y_axis_display, figure_typography


def wait_for(predicate):
    end = time.monotonic() + 15
    while not predicate():
        if time.monotonic() > end:
            raise AssertionError("Background load timed out")
        QTest.qWait(25)


class AxisTests(unittest.TestCase):
    def test_journal_defaults_fixed_text_tiff_and_raster_limit(self):
        from PIL import Image
        trace = demo_trace()
        state = FigureState.report(trace)
        state.settings.publication_style = "analytical_chemistry"
        state.settings.dpi = 1200
        sizes = figure_size_presets("analytical_chemistry")
        self.assertEqual(sizes[2][1][0], 84.6)
        self.assertEqual(sizes[3][1][0], 177.8)
        for _, size in sizes[1:]:
            state.settings.width_mm, state.settings.height_mm = size
            self.assertEqual(figure_typography(state.settings)["font_size_pt"], 8)
        with tempfile.TemporaryDirectory() as folder:
            state.settings.width_mm, state.settings.height_mm = 84.6, 70
            path, _ = export_figure(trace, state, Path(folder) / "single.tif")
            with Image.open(path) as raster:
                self.assertEqual(raster.format, "TIFF")
                self.assertEqual(raster.size, (int(84.6 / 25.4 * 1200), int(70 / 25.4 * 1200)))
                self.assertEqual(raster.info["dpi"], (1200, 1200))
            state.settings.width_mm, state.settings.height_mm = 177.8, 120
            with self.assertRaisesRegex(ValueError, "24 megapixels"):
                export_figure(trace, state, Path(folder) / "large.tif")
            self.assertFalse((Path(folder) / "large.tif").exists())
            export_figure(trace, state, Path(folder) / "large.pdf")

    def test_layout_lettering_footer_and_editable_exports(self):
        from matplotlib import rcParams
        from pypdf import PdfReader
        trace = replace(demo_trace(), synthetic=False, instrument="GC-MS", source="test.raw", function="_func001.dat")
        state = FigureState.report(trace)
        state.add_label(trace, 5.05, "Peak A")
        original = trace.signal.copy()
        full_size = figure_typography(state.settings)["font_size_pt"]
        state.settings.width_mm, state.settings.height_mm = 90, 70
        typography = figure_typography(state.settings)
        self.assertGreaterEqual(typography["font_size_pt"], 7)
        self.assertLess(typography["font_size_pt"], full_size)
        fig, ax, labels = render_figure(trace, state)
        self.assertFalse(fig.texts)
        self.assertEqual(ax.title.get_fontsize(), typography["font_size_pt"])
        self.assertEqual(labels[0].get_fontsize(), typography["font_size_pt"])
        np.testing.assert_array_equal(trace.signal, original)
        old_rc = (rcParams["pdf.fonttype"], rcParams["svg.fonttype"])
        with tempfile.TemporaryDirectory() as folder:
            path, sidecar = export_figure(trace, state, Path(folder) / "figure.svg")
            self.assertIn("<text", path.read_text(encoding="utf-8"))
            metadata = json.loads(sidecar.read_text())
            self.assertEqual(metadata["typography"], typography)
            self.assertEqual(metadata["function"], "_func001.dat")
            path, _ = export_figure(trace, state, Path(folder) / "figure.pdf")
            page = PdfReader(path).pages[0]
            self.assertIn("Peak A", page.extract_text())
            for font in page["/Resources"]["/Font"].values():
                font = font.get_object()
                self.assertEqual(font["/Subtype"], "/Type0")
                self.assertIn("/FontFile2", font["/DescendantFonts"][0].get_object()["/FontDescriptor"])
        self.assertEqual((rcParams["pdf.fonttype"], rcParams["svg.fonttype"]), old_rc)
        synthetic, _, _ = render_figure(demo_trace(), FigureState.report(demo_trace()))
        self.assertIn("SYNTHETIC DEMO", synthetic.texts[0].get_text())

    def test_auto_zero_negative_and_explicit_ranges_preserve_values(self):
        for signal in ([2, 10], [0, 0], [-2, 10], [-3, -2]):
            trace = Trace("trace", "test", "Synthetic", [0, 1], signal)
            state = FigureState.report(trace)
            _, ax, _ = render_figure(trace, state)
            if min(signal) >= 0:
                self.assertEqual(ax.get_ylim()[0], 0)
            else:
                self.assertLessEqual(ax.get_ylim()[0], min(signal))
                self.assertGreaterEqual(ax.get_ylim()[1], max(signal))
            state.settings.y_range = (-20, 20)
            _, ax, _ = render_figure(trace, state)
            self.assertEqual(ax.get_ylim(), (-20, 20))
            np.testing.assert_array_equal(trace.signal, signal)

    def test_readable_billions_and_export_scale_without_signal_scaling(self):
        trace = Trace("large", "test", "GC-MS", [0, 1], [0, 1e10], y_label="Total ion signal (counts)")
        state = FigureState.report(trace)
        fig, ax, _ = render_figure(trace, state)
        FigureCanvasAgg(fig).draw()
        self.assertIn("billions", ax.get_ylabel())
        self.assertEqual(ax.yaxis.get_major_formatter()(2e9), "2")
        self.assertEqual(ax.yaxis.get_offset_text().get_text(), "")
        np.testing.assert_array_equal(ax.lines[0].get_ydata(), trace.signal)
        state.settings.y_range = (1e10, 1e10 + 100)
        zoomed, zoom_axes, _ = render_figure(trace, state)
        FigureCanvasAgg(zoomed).draw()
        labels = [label.get_text() for label in zoom_axes.get_yticklabels()]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual(zoom_axes.yaxis.get_major_formatter()(1e10 + 20), "10.00000002")
        state.settings.y_range = None
        with tempfile.TemporaryDirectory() as folder:
            _, sidecar = export_figure(trace, state, Path(folder) / "large.svg")
            self.assertEqual(json.loads(sidecar.read_text())["y_axis_display"]["divisor"], 1e9)
        state.settings.y_numbers = "plain"
        fig, ax, _ = render_figure(trace, state)
        FigureCanvasAgg(fig).draw()
        self.assertEqual(ax.yaxis.get_offset_text().get_text(), "")
        state.settings.y_numbers = "scientific"
        self.assertIsNone(y_axis_display(trace, state.settings)["divisor"])
        fig, ax, _ = render_figure(trace, state)
        FigureCanvasAgg(fig).draw()
        self.assertIn("10", ax.yaxis.get_offset_text().get_text())


class RefinementQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = Workspace()
        self.window.add_sample(demo_trace())

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_auto_lettering_manual_override_and_sample_switch(self):
        w = self.window
        w.layout_controller.advanced.setChecked(True)
        first = w.active_key
        w.fields["title"].setText("Unapplied draft")
        w.choose_figure_size(5)
        automatic_size = w.fields["font_size"].value()
        self.assertLess(automatic_size, 10)
        self.assertFalse(w.fields["font_size"].isEnabled())
        self.assertEqual(w.axes.xaxis.label.get_fontsize(), automatic_size)
        self.assertNotEqual(w.active.state.settings.title, "Unapplied draft")
        w.auto_font_size.setChecked(False)
        self.assertTrue(w.fields["font_size"].isEnabled())
        self.assertEqual(w.fields["font_size"].value(), automatic_size)
        w.fields["font_size"].setValue(7)
        w.font_family.setCurrentText("DejaVu Sans")
        self.assertTrue(w.apply_settings())
        w.choose_figure_size(1)
        self.assertEqual(w.axes.xaxis.label.get_fontsize(), 7)
        w.add_sample(demo_trace())
        self.assertTrue(w.auto_font_size.isChecked())
        w.sample_list.setCurrentItem(w.find_item(first))
        self.assertFalse(w.auto_font_size.isChecked())
        self.assertEqual(w.fields["font_size"].value(), 7)
        self.assertEqual(w.font_family.currentText(), "DejaVu Sans")

    def test_journal_style_changes_layout_defaults_without_losing_data_or_drafts(self):
        w = self.window
        first = w.active_key
        w.choose_figure_size(2)
        w.active.state.add_label(w.active.trace, 5, "Retain")
        signal = w.active.trace.signal.copy()
        w.fields["title"].setText("Unapplied title")
        index = w.figure_style.findData("analytical_chemistry")
        w.figure_style.setCurrentIndex(index)
        w.figure_style.activated.emit(index)
        self.assertEqual(w.active.state.settings.width_mm, 84.6)
        self.assertEqual(w.fields["font_size"].value(), 8)
        self.assertEqual(w.fields["dpi"].value(), 1200)
        self.assertEqual(w.fields["title"].text(), "Unapplied title")
        self.assertNotEqual(w.active.state.settings.title, "Unapplied title")
        self.assertEqual(w.active.state.labels[0].text, "Retain")
        np.testing.assert_array_equal(w.active.trace.signal, signal)
        w.choose_figure_size(5)
        self.assertEqual(w.fields["font_size"].value(), 8)
        w.add_sample(demo_trace())
        self.assertEqual(w.figure_style.currentData(), "general")
        w.sample_list.setCurrentItem(w.find_item(first))
        self.assertEqual(w.figure_style.currentData(), "analytical_chemistry")
        self.assertEqual(w.size_preset.currentIndex(), 5)

    def test_click_promotes_pending_sample_without_interrupting_active_load(self):
        w = self.window
        launched = []
        def launch(key, request):
            launched.append(key)
            directory = tempfile.TemporaryDirectory()
            write_result(directory.name, [replace(demo_trace(), source=request.path, name=Path(request.path).name)])
            w.jobs[key] = (QProcess(w), directory)
        entries = [LibraryEntry(str(i), str(i), f"/sample{i}.raw", "ms", "Found", True) for i in range(4)]
        with patch.object(w, "launch_request", side_effect=launch):
            keys = w.open_library_entries(entries)
            w.sample_list.setCurrentItem(w.find_item(keys[3]))
            self.assertEqual(launched, [keys[0]])
            self.assertEqual(list(w.pending), [keys[3], keys[1], keys[2]])
            self.assertEqual(w.find_item(keys[3]).data(STATUS_ROLE), "Next")
            w.finish_load(keys[0])
            self.app.processEvents()
            self.assertEqual(launched, [keys[0], keys[3]])
            self.assertEqual(w.active_key, keys[3])

    def test_search_preserves_selected_sample_and_report_settings(self):
        w = self.window
        first = w.add_sample(replace(demo_trace(), name="A very long sample name with distinct suffix - 01.raw"))
        w.active.state.add_label(w.active.trace, 5, "Keep this")
        w.y_numbers.setCurrentIndex(w.y_numbers.findData("plain"))
        self.assertTrue(w.apply_settings())
        second = w.add_sample(replace(demo_trace(), name="Second sample.raw"))
        w.sample_search.setText("distinct suffix")
        self.assertFalse(w.find_item(first).isHidden())
        self.assertTrue(w.find_item(second).isHidden())
        w.sample_list.setCurrentItem(w.find_item(first))
        self.assertEqual(w.active.state.labels[0].text, "Keep this")
        self.assertEqual(w.y_numbers.currentData(), "plain")
        w.sample_search.clear()
        self.assertEqual(w.active_key, first)

    def test_worker_reused_after_success_and_error_then_closed(self):
        w = self.window
        with tempfile.TemporaryDirectory() as folder:
            good = Path(folder) / "good.raw"
            synthetic_penx(good)
            first = w.start_load(good, "fid", origin_key="one")
            process = w.loader.process
            wait_for(lambda: first in w.samples)
            failed = w.start_load(Path(folder) / "missing.raw", "fid", origin_key="bad")
            last = w.start_load(good, "fid", origin_key="two", select=False)
            wait_for(lambda: not w.jobs and not w.pending)
            self.assertIs(w.loader.process, process)
            self.assertEqual(process.state(), QProcess.ProcessState.Running)
            self.assertIn(failed, w.failures)
            np.testing.assert_array_equal(w.samples[first].trace.signal, w.samples[last].trace.signal)
            w.close()
            self.assertIsNone(w.loader.process)
            self.assertEqual(process.state(), QProcess.ProcessState.NotRunning)

    def test_crashed_worker_fails_only_active_request_and_restarts_queue(self):
        w = self.window
        with tempfile.TemporaryDirectory() as folder:
            good = Path(folder) / "good.raw"
            synthetic_penx(good)
            first = w.start_load(good, "fid", origin_key="one")
            old = w.loader.process
            self.assertTrue(old.waitForStarted(3000))
            second = w.start_load(good, "fid", origin_key="two", select=False)
            old.kill()
            wait_for(lambda: first in w.failures and second in w.samples)
            self.assertIsNot(w.loader.process, old)
            self.assertNotIn(first, w.samples)
            w.sample_list.setCurrentItem(w.find_item(first))
            w.retry_selected()
            wait_for(lambda: first in w.samples)
            self.assertNotIn(first, w.failures)

    def test_cancel_running_request_restarts_worker_for_remaining_queue(self):
        w = self.window
        with tempfile.TemporaryDirectory() as folder:
            good = Path(folder) / "good.raw"
            synthetic_penx(good)
            first = w.start_load(good, "fid", origin_key="one")
            old = w.loader.process
            self.assertTrue(old.waitForStarted(3000))
            second = w.start_load(good, "fid", origin_key="two", select=False)
            w.remove_sample()
            wait_for(lambda: second in w.samples)
            self.assertNotIn(first, w.requests)
            self.assertNotIn(first, w.samples)
            self.assertIsNone(w.find_item(first))
            self.assertIsNot(w.loader.process, old)


if __name__ == "__main__":
    unittest.main()
