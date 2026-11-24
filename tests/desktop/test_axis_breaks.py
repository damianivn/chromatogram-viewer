"""Axis-break geometry, exports and real Qt interaction on synthetic signals."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PIL import Image
from pypdf import PdfReader
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gcviewer.figures.workspace import FigureState, demo_trace, render_figure, export_figure
from gcviewer.data_models.acquisition import Trace
from gcviewer.figures.axis_breaks import clipped_path, view_limits
from gcviewer.desktop.window import Workspace


class BreakModelTests(unittest.TestCase):
    def test_each_axis_and_both_preserve_linear_scale_and_source_paths(self):
        trace = demo_trace()
        original = trace.signal.copy()
        for xbreak, ybreak in (((4, 7), None), (None, (25, 65)), ((4, 7), (25, 65))):
            with self.subTest(x=xbreak, y=ybreak):
                state = FigureState.report(trace)
                state.settings.x_break, state.settings.y_break = xbreak, ybreak
                fig, primary, _ = render_figure(trace, state)
                FigureCanvasAgg(fig).draw()
                self.assertEqual(len(fig.axes), (2 if xbreak else 1) * (2 if ybreak else 1))
                xs, ys = [], []
                for ax in fig.axes:
                    xs.append(ax.bbox.width / np.diff(ax.get_xlim())[0])
                    ys.append(ax.bbox.height / np.diff(ax.get_ylim())[0])
                    px, py = ax.lines[0].get_data()
                    finite = np.isfinite(px)
                    self.assertTrue(np.all((px[finite] >= ax.get_xlim()[0]) & (px[finite] <= ax.get_xlim()[1])))
                    self.assertTrue(np.all((py[finite] >= ax.get_ylim()[0]) & (py[finite] <= ax.get_ylim()[1])))
                    np.testing.assert_allclose(py[finite], np.interp(px[finite], trace.time, original), atol=1e-10)
                    self.assertTrue(ax.lines[0].get_clip_on())
                    self.assertEqual(sum(line.get_gid() == "x-axis-break" for line in ax.lines), bool(xbreak and ax.report_row == 0))
                    self.assertEqual(sum(line.get_gid() == "y-axis-break" for line in ax.lines), bool(ybreak and ax.report_column == 0))
                np.testing.assert_allclose(xs, xs[0])
                np.testing.assert_allclose(ys, ys[0])
                self.assertEqual(primary.get_ylim()[0], 0)
                self.assertIn(0, primary.get_yticks())
        np.testing.assert_array_equal(original, trace.signal)

    def test_slash_pairs_are_compact_and_only_on_visible_bottom_left_axes(self):
        trace = demo_trace()
        for width, height in ((180, 110), (90, 70), (180, 60)):
            state = FigureState.report(trace)
            state.settings = replace(state.settings, width_mm=width, height_mm=height, x_break=(4, 7), y_break=(50, 70))
            fig, _, _ = render_figure(trace, state)
            FigureCanvasAgg(fig).draw()
            positions = {"x": [], "y": []}
            for ax in fig.axes:
                for line in ax.lines:
                    if line.get_gid() in ("x-axis-break", "y-axis-break"):
                        points = line.get_transform().transform(line.get_xydata())
                        positions[line.get_gid()[0]].extend(points)
            bottom = min(ax.bbox.y0 for ax in fig.axes)
            left = min(ax.bbox.x0 for ax in fig.axes)
            self.assertEqual(len(positions["x"]), 2)
            self.assertEqual(len(positions["y"]), 2)
            for point in positions["x"]:
                self.assertAlmostEqual(point[1], bottom)
            for point in positions["y"]:
                self.assertAlmostEqual(point[0], left)
            for name, dimension in (("x", 0), ("y", 1)):
                gap_mm = abs(positions[name][1][dimension] - positions[name][0][dimension]) / fig.dpi * 25.4
                self.assertGreater(gap_mm, .5)
                self.assertLess(gap_mm, 1.5)

    def test_display_clipping_interpolates_edges_without_joining_hidden_excursions(self):
        x, y = clipped_path(np.array([0., 1, 2, 3, 4]), np.array([0., 10, 0, 10, 0]), (.5, 3.5), (2, 8))
        np.testing.assert_allclose(x, [np.nan, .5, .8, np.nan, 1.2, 1.8, np.nan, 2.2, 2.8, np.nan, 3.2, 3.5])
        np.testing.assert_allclose(y, [np.nan, 5, 8, np.nan, 8, 2, np.nan, 2, 8, np.nan, 8, 5])
        x, y = clipped_path(np.arange(5.), np.ones(5), (.5, 3.5), (0, 2))
        np.testing.assert_allclose(x, [np.nan, .5, 1, 2, 3, 3.5])
        x, y = clipped_path(np.arange(5.), np.ones(5), (.5, 3.5), (2, 3))
        self.assertEqual(len(x), 0)

    def test_invalid_intervals_and_empty_retained_time_rejected(self):
        trace = demo_trace()
        for axis in ("x", "y"):
            for values in ((2,), (2, 3, 4), (3, 2), (2, 2), (np.nan, 4), (1, np.inf), (-10, 4), (1, 1000)):
                state = FigureState.report(trace)
                setattr(state.settings, axis + "_break", values)
                with self.subTest(axis=axis, values=values), self.assertRaises(ValueError):
                    state.settings.validate(trace)
        state = FigureState.report(trace)
        state.settings.x_range, state.settings.x_break = (-2, 14), (-1, 13)
        with self.assertRaisesRegex(ValueError, "every data point"):
            state.settings.validate(trace)

    def test_hidden_labels_restored_and_positions_use_complete_rectangle(self):
        trace = demo_trace()
        state = FigureState.report(trace)
        visible = state.add_label(trace, 1.65, "Visible", (.8, .9))
        hidden_x = state.add_label(trace, 5.3, "Hidden time")
        hidden_y = state.add_label(trace, 8.1, "Hidden signal")
        labels = [(label.index, label.position) for label in state.labels]
        state.settings.x_break, state.settings.y_break = (4, 7), (50, 70)
        fig, _, artists = render_figure(trace, state)
        FigureCanvasAgg(fig).draw()
        self.assertIsNotNone(artists[0])
        self.assertIsNone(artists[1])
        self.assertIsNone(artists[2])
        self.assertIn(artists[0], fig.artists)
        self.assertGreater(artists[0].get_window_extent().width, 0)
        np.testing.assert_allclose(artists[0].get_transform().transform(visible.position),
                                   fig.report_label_transform.transform(visible.position))
        state.settings.x_break = state.settings.y_break = None
        _, _, artists = render_figure(trace, state)
        self.assertTrue(all(artist is not None for artist in artists))
        self.assertEqual(labels, [(label.index, label.position) for label in state.labels])

    def test_exports_record_breaks_and_hidden_labels_keep_vector_text(self):
        trace = demo_trace()
        state = FigureState.report(trace)
        state.settings = replace(state.settings, x_break=(4, 7), y_break=(50, 70), dpi=100)
        state.add_label(trace, 1.65, "Visible peak")
        state.add_label(trace, 5.3, "Omitted peak")
        with tempfile.TemporaryDirectory() as directory:
            for suffix in ("png", "pdf", "svg", "tif"):
                path, sidecar = export_figure(trace, state, Path(directory) / ("breaks." + suffix))
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                self.assertEqual(meta["axis_breaks"]["x_omitted"], [4, 7])
                self.assertEqual(meta["axis_breaks"]["y_omitted"], [50, 70])
                self.assertFalse(meta["annotations"][0]["hidden_by_axis_break"])
                self.assertTrue(meta["annotations"][1]["hidden_by_axis_break"])
                self.assertEqual(meta["point_count"], len(trace.time))
                if suffix in ("png", "tif"):
                    with Image.open(path) as im:
                        self.assertEqual(im.size, (int(180 / 25.4 * 100), int(110 / 25.4 * 100)))
                elif suffix == "pdf":
                    page = PdfReader(path).pages[0]
                    self.assertAlmostEqual(float(page.mediabox.width), 180 / 25.4 * 72)
                    self.assertEqual(len(page.images), 0)
                    self.assertIn("Visible peak", page.extract_text())
                    self.assertNotIn("Omitted peak", page.extract_text())
                else:
                    svg = path.read_text(encoding="utf-8")
                    self.assertIn("<text", svg)
                    self.assertIn("x-axis-break", svg)
                    self.assertIn("y-axis-break", svg)
                    self.assertNotIn("Omitted peak", svg)

    def test_shared_multiplier_and_negative_ranges(self):
        trace = replace(demo_trace(), signal=demo_trace().signal * 1e9)
        state = FigureState.report(trace)
        state.settings.y_break = (25e9, 65e9)
        state.settings.y_numbers = "scientific"
        fig, _, _ = render_figure(trace, state)
        FigureCanvasAgg(fig).draw()
        self.assertEqual(len({ax.yaxis.get_major_formatter().get_offset() for ax in fig.axes}), 1)
        self.assertEqual(sum(ax.yaxis.get_offset_text().get_visible() for ax in fig.axes), 1)
        small_panel = FigureState.report(demo_trace())
        small_panel.settings.y_break = (.001, 100)
        small_panel.settings.y_numbers = "scientific"
        fig, _, _ = render_figure(demo_trace(), small_panel)
        FigureCanvasAgg(fig).draw()
        self.assertTrue(all(ax.yaxis.get_major_formatter().get_offset() == "" for ax in fig.axes))
        negative = Trace("negative", "test", "Synthetic", [0, 1, 2, 3], [-10, -3, 2, 10])
        state = FigureState.report(negative)
        state.settings.y_break = (-2, 2)
        fig, _, _ = render_figure(negative, state)
        FigureCanvasAgg(fig).draw()
        self.assertLess(fig.axes[0].get_ylim()[0], -10)
        self.assertGreater(fig.axes[1].get_ylim()[1], 10)


class BreakQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = Workspace()
        self.window.add_sample(demo_trace())
        self.window.show()
        QTest.qWait(100)
        self.window.break_controls.set_interval("x_break", (4, 7))
        self.window.break_controls.set_interval("y_break", (50, 70))
        self.assertTrue(self.window.apply_settings())
        self.window.canvas.draw()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def point(self, xy):
        canvas = self.window.canvas
        return QPoint(round(xy[0] / canvas.devicePixelRatioF()), round(canvas.height() - xy[1] / canvas.devicePixelRatioF()))

    def test_fields_validation_switch_remove_and_home(self):
        w = self.window
        first = w.active_key
        self.assertEqual(len(w.canvas.figure.report_panels), 4)
        w.break_controls.set_interval("x_break", (4, 20))
        self.assertFalse(w.apply_settings())
        self.assertEqual(w.active.state.settings.x_break, (4, 7))
        w.add_sample(demo_trace())
        self.assertFalse(w.break_controls.enabled["x_break"].isChecked())
        self.assertEqual([editor.text() for editor in w.break_controls.editors["x_break"]], ["", ""])
        w.sample_list.setCurrentItem(w.find_item(first))
        self.assertTrue(w.break_controls.enabled["x_break"].isChecked())
        self.assertEqual([editor.text() for editor in w.break_controls.editors["x_break"]], ["4", "7"])
        w.remove_breaks()
        self.assertEqual(len(w.canvas.figure.report_panels), 1)
        w.break_controls.set_interval("x_break", (4, 7))
        w.apply_settings()
        w.toolbar.home()
        self.assertIsNone(w.active.state.settings.x_break)
        self.assertIsNone(w.active.state.settings.x_range)
        self.assertEqual(len(w.canvas.figure.report_panels), 1)

    def test_explicit_from_to_reject_incomplete_input_and_toggle_each_axis(self):
        w = self.window
        w.layout_controller.show_figure_page('Axes')
        controls = w.break_controls
        first, last = controls.editors["x_break"]
        first.clear()
        self.assertFalse(w.apply_settings())
        self.assertIn("both From and To", w.error.text())
        self.assertEqual(w.active.state.settings.x_break, (4, 7))
        first.setText("8")
        self.assertFalse(w.apply_settings())
        self.assertIn("From < To", w.error.text())
        controls.enabled["x_break"].setChecked(False)
        self.assertFalse(first.isEnabled())
        self.assertFalse(last.isEnabled())
        self.assertFalse(first.isVisible())
        self.assertFalse(last.isVisible())
        self.assertTrue(w.apply_settings())
        self.assertIsNone(w.active.state.settings.x_break)
        self.assertEqual(w.active.state.settings.y_break, (50, 70))
        controls.enabled["x_break"].setChecked(True)
        first.setText("4e0")
        self.assertTrue(w.apply_settings())
        self.assertEqual(w.active.state.settings.x_break, (4, 7))
        controls.set_interval("y_break", (435641451, 1.13266777e9))
        w.resize(920, 600)
        QTest.qWait(80)
        for editor in controls.editors["y_break"]:
            self.assertTrue(editor.isVisible())
            self.assertLessEqual(editor.fontMetrics().horizontalAdvance(editor.text()) + 10, editor.width())

    def test_click_and_drag_across_panels_then_restore_hidden_label(self):
        w = self.window
        panel = w.canvas.figure.report_panels[1]
        QTest.mouseClick(w.canvas, Qt.MouseButton.LeftButton, pos=self.point(panel.transData.transform((10.25, 30))))
        self.app.processEvents()
        w.canvas.draw()
        self.assertEqual(len(w.active.state.labels), 1)
        label = w.active.state.labels[0]
        index = label.index
        start = self.point(w.canvas.figure.report_label_transform.transform(label.position))
        end = self.point(w.canvas.figure.report_label_transform.transform((.25, .88)))
        QTest.mousePress(w.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(w.canvas, end, 20)
        QTest.mouseRelease(w.canvas, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(label.index, index)
        self.assertAlmostEqual(label.position[0], .25, delta=.01)
        self.assertAlmostEqual(label.position[1], .88, delta=.01)
        w.active.state.add_label(w.active.trace, 5.3, "Hidden")
        w.refresh_labels()
        w.redraw()
        self.assertIsNone(w.artists[1])
        self.assertIn("1 label", w.break_status.text())
        w.remove_breaks()
        self.assertIsNotNone(w.artists[1])

    def test_pan_keeps_break_boundaries_and_invalid_view_restores_previous_limits(self):
        w = self.window
        before_x, before_y = view_limits(w.active.trace, w.active.state.settings)
        panel = w.canvas.figure.report_panels[0]
        w.toolbar.pan()
        start = self.point(panel.transData.transform((2, 10)))
        end = self.point(panel.transData.transform((2.5, 15)))
        QTest.mousePress(w.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(w.canvas, end, 20)
        QTest.mouseRelease(w.canvas, Qt.MouseButton.LeftButton, pos=end)
        self.app.processEvents()
        s = w.active.state.settings
        self.assertEqual(s.x_break, (4, 7))
        self.assertEqual(s.y_break, (50, 70))
        self.assertLess(s.x_range[0], before_x[0])
        self.assertEqual(s.x_range[1], before_x[1])
        self.assertLess(s.y_range[0], before_y[0])
        self.assertEqual(s.y_range[1], before_y[1])
        previous = s.x_range
        panel = w.canvas.figure.report_panels[0]
        panel.set_xlim(5, 6)
        w.capture_view(panel)
        self.assertEqual(w.active.state.settings.x_range, previous)
        self.assertIn("strictly inside", w.error.text())

    def test_click_time_with_omitted_signal_does_not_create_hidden_label(self):
        w = self.window
        panel = w.canvas.figure.report_panels[1]
        QTest.mouseClick(w.canvas, Qt.MouseButton.LeftButton, pos=self.point(panel.transData.transform((8.1, 20))))
        self.app.processEvents()
        self.assertFalse(w.active.state.labels)
        self.assertIn("outside the visible", w.statusBar().currentMessage())

    def test_zoom_selected_section_preserves_breaks_and_other_outer_limits(self):
        w = self.window
        before_x, before_y = view_limits(w.active.trace, w.active.state.settings)
        panel = w.canvas.figure.report_panels[1]
        w.toolbar.zoom()
        start = self.point(panel.transData.transform((8, 5)))
        end = self.point(panel.transData.transform((11, 40)))
        QTest.mousePress(w.canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(w.canvas, end, 20)
        QTest.mouseRelease(w.canvas, Qt.MouseButton.LeftButton, pos=end)
        self.app.processEvents()
        s = w.active.state.settings
        self.assertEqual(s.x_break, (4, 7))
        self.assertEqual(s.y_break, (50, 70))
        self.assertEqual(s.x_range[0], before_x[0])
        self.assertAlmostEqual(s.x_range[1], 11, delta=.1)
        self.assertAlmostEqual(s.y_range[0], 5, delta=1)
        self.assertEqual(s.y_range[1], before_y[1])


if __name__ == "__main__":
    unittest.main()
