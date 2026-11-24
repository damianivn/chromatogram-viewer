"""Processing calculations and agreement between displayed/exported/selected data."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gcviewer.data_models.acquisition import Trace
from gcviewer.figures.workspace import FigureState, demo_trace, render_figure, export_figure, y_axis_display
from gcviewer.figures.comparisons import Comparison
from gcviewer.analysis.processing import display_signal, processing_metadata
from gcviewer.reports.numeric import export_csv
from gcviewer.figures.axis_breaks import view_limits
from gcviewer.desktop.window import Workspace


def trace(values=(0, 0, 9, 0, 0), **kwargs):
    return Trace("Processing example", "synthetic://processing", "GC-MS", np.arange(len(values), dtype=float),
                 np.array(values), synthetic=True, y_label="Signal (counts)", **kwargs)


class ProcessingModelTests(unittest.TestCase):
    def test_off_is_exact_and_input_is_immutable(self):
        t = trace((-2, 0, 9, 0, 1))
        s = FigureState.report(t).settings
        self.assertIs(display_signal(t, s), t.signal)
        original = t.signal.copy()
        for window in range(1, 22, 2):
            y = display_signal(t, replace(s, smoothing_window=window, normalize=True))
            self.assertFalse(y.flags.writeable)
        np.testing.assert_array_equal(t.signal, original)

    def test_centered_edges_use_available_points_without_zero_padding(self):
        t = trace((2, 4, 8, 16, 32))
        s = replace(FigureState.report(t).settings, smoothing_window=3)
        np.testing.assert_allclose(display_signal(t, s), [3, 14 / 3, 28 / 3, 56 / 3, 24])
        constant = trace((7, 7))
        np.testing.assert_allclose(display_signal(constant, replace(s, smoothing_window=21)), [7, 7])
        np.testing.assert_allclose(display_signal(trace((2, 8)), replace(s, smoothing_window=21)), [5, 5])

    def test_smoothing_then_normalization_and_zoom_independence(self):
        t = replace(trace((0, 0, 9, 0, 0)), time=np.array([0, .1, .5, 2, 9]))
        s = replace(FigureState.report(t).settings, smoothing_window=3, normalize=True)
        np.testing.assert_allclose(display_signal(t, s), [0, 100, 100, 100, 0])
        zoomed = replace(s, x_range=(0, .1), x_break=(.02, .07), y_range=(0, 70), y_break=(20, 40))
        np.testing.assert_array_equal(display_signal(t, s), display_signal(t, zoomed))
        m = processing_metadata(t, s)
        self.assertAlmostEqual(m["traces"][0]["normalization_denominator"], 3)
        self.assertEqual(m["order"], ["smoothing", "normalization"])

    def test_zero_negative_and_invalid_processing(self):
        t = trace((-2, 0, 4))
        s = replace(FigureState.report(t).settings, normalize=True)
        np.testing.assert_array_equal(display_signal(t, s), [-50, 0, 100])
        np.testing.assert_array_equal(display_signal(trace((0, 0)), s), [0, 0])
        for values in ((-2, -1), (-1, 0)):
            with self.assertRaisesRegex(ValueError, "positive maximum"):
                display_signal(trace(values), s)
        for window in (0, 2, 23, 3.0, True):
            with self.assertRaisesRegex(ValueError, "odd window"):
                replace(s, smoothing_window=window).validate(t)
        self.assertIn("%", y_axis_display(t, s)["label"])
        self.assertLess(view_limits(t, s)[1][0], -50)

    def test_spectrum_relative_sticks_and_single_zero_channel(self):
        t = trace((0, 40, 10), plot_kind="sticks", x_unit="m/z", x_label="m/z")
        s = FigureState.report(t)
        s.settings.normalize = True
        fig, ax, _ = render_figure(t, s)
        y = ax.lines[0].get_ydata().reshape(-1, 3)
        np.testing.assert_array_equal(y[:, 2], [0, 100, 25])
        self.assertTrue(np.isnan(y[:, 0]).all())
        self.assertEqual(ax.get_ylabel(), "Relative intensity (%)")
        with self.assertRaisesRegex(ValueError, "mass channels"):
            replace(s.settings, smoothing_window=3).validate(t)
        zero = trace((0,), plot_kind="sticks", x_unit="m/z", x_label="m/z")
        self.assertEqual(display_signal(zero, s.settings).tolist(), [0])
        render_figure(zero, FigureState(s.settings))

    def test_unequal_comparison_grids_normalize_independently_in_both_modes(self):
        a, b = trace((0, 0, 900, 0, 0)), trace((0, 20, 0))
        c = Comparison((a, b))
        for mode in ("overlay", "stacked"):
            s = FigureState.report(c)
            s.settings = replace(s.settings, normalize=True, comparison_mode=mode)
            fig, ax, _ = render_figure(c, s)
            FigureCanvasAgg(fig).draw()
            lines = [line for panel in fig.report_panels for line in panel.lines]
            for line, t in zip(lines, (a, b)):
                np.testing.assert_array_equal(line.get_xdata(), t.time)
                self.assertEqual(np.max(line.get_ydata()), 100)
            self.assertEqual(ax.get_ylim(), (0, 117))
            self.assertEqual([r["normalization_denominator"] for r in processing_metadata(c, s.settings)["traces"]], [900, 20])

    def test_annotations_follow_processed_signal_and_breaks_in_all_figures(self):
        a = trace((0, 0, 900, 0, 0))
        b = replace(a, name="Other trace", signal=np.array([0, 200, 0, 200, 0]))
        for report in (a, Comparison((a, b))):
            for mode in ("overlay", "stacked"):
                state = FigureState.report(report)
                state.settings = replace(state.settings, normalize=True, smoothing_window=3, comparison_mode=mode,
                                         height_mm=170, x_break=(.2, .8), y_break=(40, 60))
                state.add_label(report, 2, "Processed apex")
                state.add_label(report, .5, "Hidden X")
                fig, _, artists = render_figure(report, state)
                FigureCanvasAgg(fig).draw()
                self.assertEqual(artists[0].xy, (2, 100))
                for panel in fig.report_panels:
                    for line in panel.lines:
                        if line.get_gid() is None:
                            values = line.get_ydata()
                            finite = values[np.isfinite(values)]
                            self.assertTrue(np.all(finite <= panel.get_ylim()[1] + 1e-9))
                with tempfile.TemporaryDirectory() as folder:
                    _, sidecar = export_figure(report, state, Path(folder) / "processed.svg")
                    m = json.loads(sidecar.read_text())
                    self.assertEqual(m["annotations"][0]["anchor_signal"], 900)
                    self.assertEqual(m["annotations"][0]["displayed_anchor_signal"], 100)
                    self.assertEqual(m["processing"]["smoothing"]["window_points"], 3)

    def test_csv_stays_original_and_discloses_figure_processing(self):
        a = trace((0, 0, 900, 0, 0))
        for report in (a, Comparison((a, replace(a, signal=a.signal * 2)))):
            s = replace(FigureState.report(report).settings, smoothing_window=3, normalize=True)
            with tempfile.TemporaryDirectory() as folder:
                target, sidecar = export_csv(report, Path(folder) / "raw.csv", settings=s)
                rows = np.loadtxt(target, delimiter=",", skiprows=1)
                np.testing.assert_array_equal(rows[:5, -1], a.signal)
                m = json.loads(sidecar.read_text())
                self.assertFalse(m["figure_processing_applied_to_csv"])
                self.assertEqual(m["figure_processing"]["normalization"], "full-trace maximum = 100%")


class ProcessingQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.w = Workspace()
        self.w.add_sample(demo_trace())
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.w.close()
        self.app.processEvents()

    def change(self, normalize=True, window=1):
        self.w.signal_scale.setCurrentIndex(self.w.signal_scale.findData(normalize))
        self.w.smoothing.setCurrentIndex(self.w.smoothing.findData(window))
        self.w.change_processing()

    def test_change_preserves_x_labels_and_raw_title_resets_y_only(self):
        w = self.w
        key = w.active_key
        s = w.active.state
        s.settings = replace(s.settings, x_range=(1, 11), x_break=(4, 7), y_range=(0, 110), y_break=(40, 60), y_label="Custom counts")
        s.add_label(w.active.trace, 8.1, "Keep label")
        w.populate_settings()
        self.change(window=5)
        self.assertEqual(s.settings.x_range, (1, 11))
        self.assertEqual(s.settings.x_break, (4, 7))
        self.assertIsNone(s.settings.y_range)
        self.assertIsNone(s.settings.y_break)
        self.assertEqual(s.labels[0].text, "Keep label")
        self.assertFalse(w.fields["y_label"].isEnabled())
        self.assertIn("%", w.break_controls.enabled["y_break"].text())
        self.assertTrue(w.apply_settings())
        self.assertEqual(s.settings.y_label, "Custom counts")
        w.add_sample(trace())
        self.assertFalse(w.active.state.settings.normalize)
        w.sample_list.setCurrentItem(w.find_item(key))
        self.assertEqual(w.smoothing.currentData(), 5)
        self.change(False)
        self.assertEqual(w.fields["y_label"].text(), "Custom counts")
        w.reset_report()
        self.assertFalse(w.active.state.settings.normalize)
        self.assertEqual(w.active.state.settings.smoothing_window, 1)

    def test_invalid_normalization_rolls_back_and_spectrum_disables_smoothing(self):
        w = self.w
        w.add_sample(trace((-3, -1)))
        self.change()
        self.assertIn("positive maximum", w.error.text())
        self.assertFalse(w.active.state.settings.normalize)
        self.assertFalse(w.signal_scale.currentData())
        w.add_sample(trace((2, 4), plot_kind="sticks", x_unit="m/z", x_label="m/z"))
        self.assertFalse(w.smoothing.isEnabled())
        self.change()
        self.assertEqual(w.axes.get_ylabel(), "Relative intensity (%)")

    def test_processed_overlay_hit_test_chooses_visible_trace(self):
        w = self.w
        a, b = trace((0, 0, 9000, 0, 0)), trace((0, 40, 10, 0, 0))
        w.add_sample(Comparison((a, b)))
        self.change()
        w.canvas.draw()
        x, y = w.axes.transData.transform((1, 100))
        ratio = w.canvas.devicePixelRatioF()
        QTest.mouseClick(w.canvas, Qt.MouseButton.LeftButton,
                         pos=QPoint(round(x / ratio), round(w.canvas.height() - y / ratio)))
        self.app.processEvents()
        self.assertEqual(w.active.state.labels[0].trace_index, 1)
        self.assertEqual(w.artists[0].xy, (1, 100))
        w.toolbar.home()
        self.assertTrue(w.active.state.settings.normalize)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "original.csv"
            with patch("gcviewer.desktop.window.QFileDialog.getSaveFileName", return_value=(str(target), "CSV (*.csv)")):
                w.save_data()
            metadata = json.loads(target.with_suffix(".csv.json").read_text())
            self.assertFalse(metadata["figure_processing_applied_to_csv"])
            self.assertEqual(metadata["figure_processing"]["traces"][1]["normalization_denominator"], 40)


if __name__ == "__main__":
    unittest.main()
