"""Offscreen Qt interaction checks; native dialog behavior remains manual."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "ChromatogramViewer-matplotlib"))

from PySide6.QtCore import QPoint, Qt, QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QPushButton
from gcviewer.figures.workspace import demo_trace
from gcviewer.desktop.window import Workspace
from gcviewer.services.worker import write_result


class QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = Workspace()
        self.window.add_sample(demo_trace())
        self.window.show()
        QTest.qWait(100)
        self.window.canvas.draw()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def qt_point(self, xy):
        ratio = self.window.canvas.devicePixelRatioF()
        return QPoint(round(xy[0] / ratio), round(self.window.canvas.height() - xy[1] / ratio))

    def test_empty_startup_and_remove_last_sample_have_no_demo(self):
        window = Workspace()
        try:
            window.show()
            self.app.processEvents()
            def check_empty():
                self.assertIsNone(window.active)
                self.assertEqual(window.sample_list.count(), 0)
                self.assertFalse(window.samples)
                self.assertEqual(window.queue_status.text(), "0 open")
                self.assertIn("Open an acquisition", window.active_title.text())
                self.assertFalse(window.canvas.figure.axes)
                self.assertFalse(window.figure_export_action.isEnabled())
                self.assertFalse(window.data_export_action.isEnabled())
                self.assertFalse(window.layout_controller.figure_page.isEnabled())
                self.assertFalse(window.toolbar.isEnabled())
                self.assertFalse(window.compare_action.isEnabled())
                self.assertFalse(any(b.text() == "Demo" for b in window.findChildren(QPushButton)))
                with patch("gcviewer.desktop.window.QFileDialog.getSaveFileName") as chooser:
                    window.save_figure()
                    window.save_data()
                    chooser.assert_not_called()
            check_empty()
            with tempfile.TemporaryDirectory() as folder:
                from tests.desktop.test_library import synthetic_penx
                path = Path(folder) / "test.raw"
                synthetic_penx(path)
                key = window.start_load(path, "fid")
                for _ in range(400):
                    if not window.jobs:
                        break
                    QTest.qWait(25)
                self.assertFalse(window.jobs)
                self.assertEqual(window.active_key, key)
                self.assertEqual(window.active.trace.instrument, "GC-FID")
                self.assertTrue(window.figure_export_action.isEnabled())
                self.assertTrue(window.data_export_action.isEnabled())
                self.assertTrue(window.layout_controller.figure_page.isEnabled())
                window.active.state.add_label(window.active.trace, float(window.active.trace.time[5]), "Temporary")
                window.refresh_labels()
                window.remove_sample()
                check_empty()
                self.assertEqual(window.label_list.count(), 0)
        finally:
            window.close()

    def test_click_drag_edit_export_switch_and_reset(self):
        w = self.window
        original = w.active_key
        anchor = self.qt_point(w.axes.transData.transform((5.3, 75)))
        QTest.mouseClick(w.canvas, Qt.MouseButton.LeftButton, pos=anchor)
        self.app.processEvents()
        w.canvas.draw()
        self.assertEqual(len(w.active.state.labels), 1)
        index = w.active.state.labels[0].index
        text = self.qt_point(w.axes.transAxes.transform(w.active.state.labels[0].position))
        destination = self.qt_point(w.axes.transAxes.transform((.7, .9)))
        QTest.mousePress(w.canvas, Qt.MouseButton.LeftButton, pos=text)
        QTest.mouseMove(w.canvas, destination, 20)
        QTest.mouseRelease(w.canvas, Qt.MouseButton.LeftButton, pos=destination)
        label = w.active.state.labels[0]
        self.assertEqual(label.index, index)
        self.assertAlmostEqual(label.position[0], .7, delta=.01)
        w.label_text.setText("Moved peak")
        QTest.keyClick(w.label_text, Qt.Key.Key_Return)
        w.fields["title"].setText("Edited report")
        w.fields["width_mm"].setValue(160)
        self.assertTrue(w.apply_settings())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "qt.svg"
            with patch("gcviewer.desktop.window.QFileDialog.getSaveFileName", return_value=(str(path), "SVG (*.svg)")):
                w.save_figure()
            self.assertTrue(path.exists())
            self.assertIn("Moved peak", path.read_text())
            self.assertIn("Edited report", path.read_text())
        w.add_sample(demo_trace())
        self.assertEqual(len(w.active.state.labels), 0)
        w.sample_list.setCurrentItem(w.find_item(original))
        self.assertEqual(w.active.state.labels[0].text, "Moved peak")
        self.assertEqual(w.active.state.settings.width_mm, 160)
        w.reset_report()
        self.assertEqual(w.active.state.labels, [])
        self.assertEqual(w.active.state.settings.width_mm, 180)

    def test_invalid_range_preserves_figure_and_navigation_disables_annotation(self):
        w = self.window
        w.fields["x_range"].setText("90, 100")
        self.assertFalse(w.apply_settings())
        self.assertIsNone(w.active.state.settings.x_range)
        self.assertIn("no data", w.error.text())
        w.toolbar.pan()
        self.assertFalse(w.annotate.isChecked())
        QTest.mouseClick(w.canvas, Qt.MouseButton.LeftButton, pos=self.qt_point(w.axes.transData.transform((5, 50))))
        self.assertFalse(w.active.state.labels)
        w.annotate.setChecked(True)
        self.assertFalse(w.toolbar.mode)

    def test_late_result_keeps_request_identity_and_chooses_function(self):
        from dataclasses import replace
        w = self.window
        original = w.active_key
        key = w.add_sample(demo_trace())
        directory = tempfile.TemporaryDirectory()
        traces = [replace(demo_trace(), name="Requested sample", function="_FUNC001.DAT"),
                  replace(demo_trace(), name="Requested sample", function="_FUNC002.DAT")]
        write_result(directory.name, traces)
        w.jobs[key] = (QProcess(w), directory)
        w.sample_list.setCurrentItem(w.find_item(original))
        with patch.object(QInputDialog, "getItem", return_value=("2. _FUNC002.DAT · 6,001 scans · 0–12 min", True)):
            w.finish_load(key)
        self.assertEqual(w.active_key, original)
        self.assertEqual(w.samples[key].trace.function, "_FUNC002.DAT")
        self.assertEqual(w.samples[original].trace.function, "")
        self.assertFalse(w.jobs)

    def test_close_stops_owned_loader_and_ignores_late_callback(self):
        import sys
        w = self.window
        process = QProcess(w)
        directory = tempfile.TemporaryDirectory()
        w.jobs["slow"] = (process, directory)
        process.start(sys.executable, ["-c", "import time; time.sleep(30)"])
        self.assertTrue(process.waitForStarted(3000))
        w.close()
        self.assertEqual(process.state(), QProcess.ProcessState.NotRunning)
        self.assertFalse(w.jobs)
        w.finish_load("slow")

    def test_worker_error_is_actionable_and_cleans_up(self):
        w = self.window
        with patch.object(QMessageBox, "warning") as warning:
            w.start_load("missing-input.raw", "ms")
            for _ in range(200):
                if not w.jobs:
                    break
                QTest.qWait(25)
            self.assertFalse(w.jobs)
            self.assertTrue(warning.called)
            self.assertIn("directory", warning.call_args.args[2])

    def test_window_closed_during_function_choice_does_not_attach_result(self):
        from dataclasses import replace
        w = self.window
        key = w.active_key
        original_trace = w.active.trace
        directory = tempfile.TemporaryDirectory()
        traces = [replace(demo_trace(), function="one"), replace(demo_trace(), function="two")]
        write_result(directory.name, traces)
        w.jobs[key] = (QProcess(w), directory)
        def close_during_choice(*args):
            w.close()
            return "2. two · 6,001 scans · 0–12 min", True
        with patch.object(QInputDialog, "getItem", side_effect=close_during_choice):
            w.finish_load(key)
        self.assertIs(w.samples[key].trace, original_trace)

    def test_successful_worker_with_explicitly_synthetic_penx_bytes(self):
        from tests.penx_fixture import synthetic_penx
        w = self.window
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic-parser-fixture.raw"
            synthetic_penx(path)
            key = w.start_load(path, "fid")
            for _ in range(400):
                if not w.jobs:
                    break
                QTest.qWait(25)
            self.assertFalse(w.jobs)
            self.assertEqual(w.samples[key].trace.instrument, "GC-FID")
            self.assertEqual(len(w.samples[key].trace.time), 1200)
            sample = w.samples[key]
            self.assertAlmostEqual(sample.trace.signal[0], 400000 / (2 * 54.01791))
            self.assertAlmostEqual(sample.trace.signal[-1], 411990 / (2 * 54.01791))
            self.assertAlmostEqual(sample.trace.time[0], 1 / (60 * 12.5))
            self.assertEqual(sample.fid_run.counts[0], 400000)
            self.assertFalse(sample.fid_run.counts.flags.writeable)
            self.assertIn("no baseline subtraction", sample.trace.transformations[0])
            self.assertIn("µV", w.break_controls.enabled["y_break"].text())


if __name__ == "__main__":
    unittest.main()
