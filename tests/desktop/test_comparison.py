"""Comparison identity, unmodified data, exports and complete Qt report workflow."""
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
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gcviewer.figures.comparisons import Comparison
from gcviewer.data_models.acquisition import Trace
from gcviewer.figures.workspace import FigureState, render_figure, export_figure, export_paths
from gcviewer.reports.numeric import export_csv
from gcviewer.desktop.window import Workspace
from gcviewer.desktop.comparison_dialog import ComparisonDialog


def samples(instrument="GC-MS"):
    one = Trace("Sample A", "synthetic://A", instrument, np.linspace(0, 12, 101),
                np.sin(np.linspace(0, np.pi, 101)) * 100, function="MS1" if instrument == "GC-MS" else "FID",
                synthetic=True, y_label="Signal (counts)")
    two = replace(one, name="Sample B", source="synthetic://B", time=np.linspace(2, 15, 57),
                  signal=np.cos(np.linspace(0, np.pi, 57))**2 * 50)
    return one, two


class ComparisonModelTests(unittest.TestCase):
    def test_preserves_order_separate_grids_and_original_arrays(self):
        a, b = samples()
        c = Comparison([b, a])
        self.assertIs(c.traces[0], b)
        self.assertIs(c.traces[1], a)
        for mode in ("overlay", "stacked"):
            s = FigureState.report(c)
            s.settings.comparison_mode = mode
            fig, ax, _ = render_figure(c, s)
            FigureCanvasAgg(fig).draw()
            lines = [line for p in fig.report_panels for line in p.lines]
            self.assertEqual(len(lines), 2)
            for line, original in zip(lines, (b, a)):
                np.testing.assert_array_equal(line.get_xdata(), original.time)
                np.testing.assert_array_equal(line.get_ydata(), original.signal)
                self.assertFalse(original.signal.flags.writeable)
            for p in fig.report_panels:
                self.assertEqual(p.get_xlim(), ax.get_xlim())
                self.assertEqual(p.get_ylim(), ax.get_ylim())
                self.assertEqual(p.get_ylim()[0], 0)
            self.assertLess(ax.get_xlim()[0], 0)
            self.assertGreater(ax.get_xlim()[1], 15)

    def test_rejects_incompatible_signals_spectra_and_nested_comparisons(self):
        a, b = samples()
        for members in ((a,), (a, replace(b, instrument="GC-FID")),
                        (a, replace(b, y_label="pA")), (a, replace(b, synthetic=False)),
                        (a, replace(b, plot_kind="sticks", x_unit="m/z")), (a, Comparison((a, b)))):
            with self.subTest(members=len(members)), self.assertRaises(ValueError):
                Comparison(members)

    def test_shared_scale_handles_negative_and_zero_signals_and_partial_ranges(self):
        a, b = samples("GC-FID")
        c = Comparison((replace(a, signal=a.signal - 20), replace(b, signal=b.signal * 0)))
        s = FigureState.report(c)
        s.settings.comparison_mode = "stacked"
        s.settings.x_range = (13, 15)
        fig, ax, _ = render_figure(c, s)
        self.assertLess(ax.get_ylim()[0], -20)
        self.assertEqual(fig.axes[0].get_ylim(), fig.axes[1].get_ylim())
        s.settings.x_range = (30, 40)
        with self.assertRaisesRegex(ValueError, "no data"):
            render_figure(c, s)

    def test_breaks_and_annotations_keep_source_identity_in_both_modes(self):
        a, b = samples()
        c = Comparison((a, b))
        for mode in ("overlay", "stacked"):
            s = FigureState.report(c)
            s.settings = replace(s.settings, comparison_mode=mode, height_mm=160, x_break=(4, 7), y_break=(20, 35))
            s.add_label(c, 2.1, "Second acquisition", trace_index=1)
            s.add_label(c, 5, "Hidden time", trace_index=0)
            fig, _, artists = render_figure(c, s)
            FigureCanvasAgg(fig).draw()
            self.assertEqual(s.labels[0].trace_index, 1)
            self.assertEqual(artists[0].xy, (b.time[s.labels[0].index], b.signal[s.labels[0].index]))
            self.assertIsNone(artists[1])
            self.assertEqual(sum(line.get_gid() == "x-axis-break" and line.get_visible() for p in fig.axes for line in p.lines), 2)
            for panel in fig.axes:
                self.assertFalse(panel.spines["top"].get_visible())
                self.assertFalse(panel.spines["right"].get_visible())
            with tempfile.TemporaryDirectory() as folder:
                for suffix in ("png", "pdf", "svg", "tif"):
                    target, sidecar = export_figure(c, s, Path(folder) / f"{mode}.{suffix}")
                    self.assertGreater(target.stat().st_size, 100)
                    metadata = json.loads(sidecar.read_text())
                    self.assertEqual(metadata["traces"][1]["source"], b.source)
                    self.assertEqual(metadata["annotations"][0]["trace_id"], 2)
                    self.assertTrue(metadata["annotations"][1]["hidden_by_axis_break"])

    def test_csv_retains_all_unequal_grids_and_protects_every_source(self):
        a, b = samples()
        c = Comparison((b, a))
        with tempfile.TemporaryDirectory() as folder:
            target, sidecar = export_csv(c, Path(folder) / "data.csv")
            rows = np.loadtxt(target, delimiter=",", skiprows=1)
            for i, trace in enumerate(c.traces, 1):
                np.testing.assert_array_equal(rows[rows[:, 0] == i, 1], trace.time)
                np.testing.assert_array_equal(rows[rows[:, 0] == i, 2], trace.signal)
            records = json.loads(sidecar.read_text())["traces"]
            self.assertEqual([r["point_count"] for r in records], [57, 101])
            with self.assertRaises(FileExistsError):
                export_csv(c, target)
            protected = Comparison((replace(a, synthetic=False, source=str(Path(folder) / "a.raw")),
                                    replace(b, synthetic=False, source=str(target))))
            with self.assertRaisesRegex(ValueError, "cannot be overwritten"):
                export_paths(target, protected, extensions=(".csv",))

    def test_long_names_require_space_instead_of_silently_clipping(self):
        a, b = samples()
        c = Comparison((a, b))
        s = FigureState.report(c)
        s.settings = replace(s.settings, height_mm=40, width_mm=90, trace_names=("Long sample name " * 8,) * 2)
        with self.assertRaisesRegex(ValueError, "height"):
            render_figure(c, s)


class ComparisonQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = Workspace()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_selection_order_filter_validation_and_fitted_stacked_report(self):
        a, b = samples()
        dialog = ComparisonDialog(self.window, [("a", a), ("b", b)], "a")
        dialog.accept()
        self.assertIn("two", dialog.status.text())
        dialog.search.setText("Sample B")
        dialog.check_rows(True)
        item = dialog.rows.takeItem(1)
        dialog.rows.insertItem(0, item)
        dialog.mode.setCurrentIndex(1)
        dialog.accept()
        self.assertEqual(dialog.comparison.traces, (b, a))
        self.assertEqual(dialog.state.settings.comparison_mode, "stacked")
        dialog.state.settings.validate(dialog.comparison)
        dialog.deleteLater()

    def test_create_style_annotate_switch_remove_sources_and_export(self):
        w = self.window
        a, b = samples()
        original = w.add_sample(a)
        w.active.state.add_label(a, 2, "Individual label")
        w.active.state.settings.title = "Individual title"
        second = w.add_sample(b)
        def choose():
            dialog = self.app.activeModalWidget()
            self.assertIsInstance(dialog, ComparisonDialog)
            dialog.search.setText("Sample")
            dialog.check_rows(True)
            dialog.accept()
        QTimer.singleShot(20, choose)
        w.open_comparison()
        comparison_key = w.active_key
        self.assertIsInstance(w.active.trace, Comparison)
        self.assertFalse(w.inspect_action.isEnabled())
        w.comparison_trace.setCurrentIndex(1)
        w.comparison_name.setText("Second trace")
        w.rename_comparison_trace()
        with patch("gcviewer.desktop.window.QColorDialog.getColor", return_value=QColor("#123456")):
            w.choose_comparison_color()
        self.assertEqual(w.active.state.settings.trace_names[1], "Second trace")
        self.assertEqual(w.active.state.settings.trace_colors[1], "#123456")
        w.comparison_mode.setCurrentIndex(1)
        w.change_comparison_mode(1)
        self.app.processEvents()
        w.canvas.draw()
        axes = w.canvas.figure.report_panels[1]
        x, y = axes.transData.transform((b.time[10], b.signal[10]))
        ratio = w.canvas.devicePixelRatioF()
        point = QPoint(round(x / ratio), round(w.canvas.height() - y / ratio))
        QTest.mouseClick(w.canvas, Qt.MouseButton.LeftButton, pos=point)
        self.app.processEvents()
        self.assertEqual(w.active.state.labels[0].trace_index, 1)
        w.sample_list.setCurrentItem(w.find_item(original))
        self.assertEqual(w.active.state.settings.title, "Individual title")
        self.assertEqual(w.active.state.labels[0].text, "Individual label")
        w.remove_sample()
        w.sample_list.setCurrentItem(w.find_item(second))
        w.remove_sample()
        w.sample_list.setCurrentItem(w.find_item(comparison_key))
        self.assertEqual(len(w.active.trace.traces), 2)
        with tempfile.TemporaryDirectory() as folder:
            for method, suffix in ((w.save_figure, "svg"), (w.save_data, "csv")):
                target = Path(folder) / f"comparison.{suffix}"
                with patch("gcviewer.desktop.window.QFileDialog.getSaveFileName", return_value=(str(target), f"{suffix.upper()} (*.{suffix})")):
                    method()
                self.assertTrue(target.is_file())
        w.reset_report()
        self.assertFalse(w.active.state.labels)

    def test_small_layout_rejection_preserves_renderable_state(self):
        c = Comparison(samples() * 3)
        state = FigureState.report(c)
        state.settings.height_mm = 230
        state.settings.comparison_mode = "stacked"
        w = self.window
        w.add_sample(c, state=state)
        w.fields["height_mm"].setValue(40)
        self.assertEqual(w.active.state.settings.height_mm, 230)
        self.assertIn("height", w.error.text())
        w.choose_figure_style(1)
        self.assertEqual(w.active.state.settings.height_mm, 230)
        w.redraw()

    def test_navigation_and_breaks_apply_to_every_stacked_trace(self):
        w = self.window
        w.add_sample(Comparison(samples()))
        w.change_comparison_mode(1)
        panel = w.canvas.figure.report_panels[1]
        panel.set_xlim(2, 10)
        panel.set_ylim(0, 80)
        w.capture_view(panel)
        for p in w.canvas.figure.report_panels:
            self.assertEqual(p.get_xlim(), (2, 10))
            self.assertEqual(p.get_ylim(), (0, 80))
        w.break_controls.set_interval("x_break", (4, 6))
        w.break_controls.set_interval("y_break", (20, 30))
        self.assertTrue(w.apply_settings())
        self.assertEqual(len(w.canvas.figure.report_panels), 8)
        w.toolbar.home()
        self.assertIsNone(w.active.state.settings.x_break)
        self.assertIsNone(w.active.state.settings.y_break)
        self.assertEqual(len(w.canvas.figure.report_panels), 2)

    def test_reset_refits_original_long_labels_after_compact_custom_labels(self):
        a, b = samples()
        c = Comparison((replace(a, name="Long original sample name " * 6), replace(b, name="Another original sample name " * 6)))
        from gcviewer.figures.comparisons import fitted_settings
        state = FigureState.report(c)
        state.settings = fitted_settings(c, state.settings)
        w = self.window
        w.add_sample(c, state=state)
        w.active.state.settings = replace(w.active.state.settings, trace_names=("A", "B"), height_mm=70)
        w.reset_report()
        w.active.state.settings.validate(c)
        self.assertIn("Long original", w.active.state.settings.trace_names[0])


if __name__ == "__main__":
    unittest.main()
