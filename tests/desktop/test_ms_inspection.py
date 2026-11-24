"""Known mass matrices, data provenance, Qt choices and owned-worker lifecycle."""
from gcviewer.analysis.mass_spectra import eic as ms_eic, spectrum as ms_spectrum, tic as ms_tic
from dataclasses import replace
import csv
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gcviewer.data_models.spectra import MSFunction
from gcviewer.analysis.mass_spectra import ms_functions
from gcviewer.figures.workspace import FigureState, render_figure, export_figure
from gcviewer.reports.numeric import export_csv
from gcviewer.services.worker import write_ms_result, read_ms_result, write_result, read_result
from gcviewer.desktop.ms_inspector import MSInspector
from gcviewer.desktop.window import Workspace


def mass_fixture():
    return MSFunction("synthetic-source.raw", "MS1", np.array([1., 1.2, 1.4, 2.]), np.array([43., 44., 91., 105.]),
                      np.array([[0, 10, 0, 30], [20, 0, 40, 0], [40, 20, 0, 60], [80, 0, 20, 0]], dtype=np.uint32), synthetic=True)


class MSModelTests(unittest.TestCase):
    def test_tic_eic_nearest_channel_and_immutability(self):
        function = mass_fixture()
        np.testing.assert_array_equal(ms_tic(function).signal, [40, 60, 120, 100])
        eic = ms_eic(function, 90.8)
        np.testing.assert_array_equal(eic.signal, [0, 40, 0, 20])
        self.assertEqual(eic.metadata["selection"]["actual_mz"], 91)
        self.assertEqual(eic.metadata["selection"]["requested_mz"], 90.8)
        self.assertEqual(ms_eic(function, 43.5).metadata["selection"]["actual_mz"], 43)
        for array in (function.time, function.masses, function.data, eic.signal):
            with self.assertRaises(ValueError):
                array.flat[0] = 9
        for invalid in (0, 106, np.nan, np.inf):
            with self.assertRaises(ValueError):
                ms_eic(function, invalid)

    def test_single_and_interval_spectra_actual_scans_and_zero_channels(self):
        function = mass_fixture()
        trace = ms_spectrum(function, 1.25)
        np.testing.assert_array_equal(trace.signal, [20, 0, 40, 0])
        self.assertEqual(trace.metadata["selection"]["actual_time_min"], [1.2, 1.2])
        mean = ms_spectrum(function, 1.19, 1.41)
        np.testing.assert_array_equal(mean.signal, [30, 10, 20, 30])
        self.assertEqual(mean.metadata["selection"]["scan_count"], 2)
        self.assertEqual(mean.metadata["selection"]["first_scan_index"], 1)
        self.assertEqual(mean.metadata["selection"]["last_scan_index"], 2)
        np.testing.assert_array_equal(ms_spectrum(function, 1., 2.).signal, [35, 7.5, 15, 22.5])
        for start, end in ((1.21, 1.39), (1.3, 1.2), (1, 1), (0, 1), (1, 3), (1, np.nan)):
            with self.assertRaises(ValueError):
                ms_spectrum(function, start, end)
        for value in (0, 3, np.inf, np.nan):
            with self.assertRaises(ValueError):
                ms_spectrum(function, value)

    def test_function_validation_and_detector_selection(self):
        function = mass_fixture()
        for changes in ({"time": [1, 1, 2, 3]}, {"masses": [91, 43, 44, 105]},
                        {"data": np.zeros((4, 3))}, {"data": np.full((4, 4), np.inf)},
                        {"masses": [0, 44, 91, 105]}, {"data": np.full((4, 4), "x")}):
            with self.assertRaises(ValueError):
                replace(function, **changes)
        original = function.data.copy()
        copy = replace(function, data=original)
        original[:] = 0
        self.assertEqual(copy.data[1, 2], 40)
        def datafile(name, detector="MS", masses=function.masses):
            return SimpleNamespace(name=name, detector=detector, xlabels=function.time, ylabels=masses,
                                   data=function.data, metadata={"name": name})
        acquisition = SimpleNamespace(datafiles=[datafile("UV", "UV"), datafile("bad", masses=[1]), datafile("MS2"), datafile("MS1")], metadata={})
        functions = ms_functions(acquisition, ".")
        self.assertEqual([f.name for f in functions], ["MS2", "MS1"])
        self.assertIn("bad", functions[0].warnings[0])

    def test_transport_roundtrip_and_spectrum_figures_with_breaks(self):
        function = mass_fixture()
        with tempfile.TemporaryDirectory() as directory:
            write_ms_result(directory, [function, replace(function, name="MS2")])
            restored = read_ms_result(directory)
            self.assertEqual(restored[1].name, "MS2")
            np.testing.assert_array_equal(restored[0].data, function.data)
            trace = ms_spectrum(restored[0], 1.19, 1.41)
            write_result(directory, [trace])
            trace = read_result(directory)[0]
            self.assertEqual(trace.plot_kind, "sticks")
            state = FigureState.report(trace)
            state.settings.x_break, state.settings.y_break = (50, 80), (12, 18)
            state.add_label(trace, 91)
            self.assertEqual(state.labels[0].text, "m/z 91")
            fig, _, _ = render_figure(trace, state)
            FigureCanvasAgg(fig).draw()
            for ax in fig.axes:
                x, y = ax.lines[0].get_data()
                pairs = np.asarray([x, y]).T.reshape(-1, 3, 2)
                for segment in pairs:
                    self.assertTrue(np.isnan(segment[0]).all())
                    self.assertEqual(segment[1, 0], segment[2, 0])
                    self.assertGreaterEqual(segment[1, 1], ax.get_ylim()[0])
                    self.assertLessEqual(segment[2, 1], ax.get_ylim()[1])
            for suffix in ("png", "pdf", "svg", "tif"):
                _, sidecar = export_figure(trace, state, Path(directory) / ("spectrum." + suffix))
                metadata = json.loads(sidecar.read_text())
                self.assertEqual(metadata["annotations"][0]["anchor_mz"], 91)
                self.assertNotIn("anchor_time_min", metadata["annotations"][0])

    def test_one_channel_zero_spectrum_and_full_numeric_export_protection(self):
        function = replace(mass_fixture(), masses=np.array([91.]), data=np.zeros((4, 1)))
        trace = ms_spectrum(function, 1.2)
        state = FigureState.report(trace)
        state.add_label(trace, 91)
        fig, ax, _ = render_figure(trace, state)
        FigureCanvasAgg(fig).draw()
        self.assertLess(ax.get_xlim()[0], 91)
        self.assertGreater(ax.get_xlim()[1], 91)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "data.csv"
            _, sidecar = export_csv(trace, target)
            with target.open() as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[1], ["91", "0", "0"])
            metadata = json.loads(sidecar.read_text())
            self.assertEqual(metadata["source_metadata"]["selection"]["scan_count"], 1)
            with self.assertRaises(FileExistsError):
                export_csv(trace, target)
            with self.assertRaises(ValueError):
                export_csv(trace, Path(directory) / "acquisition.raw" / "data.csv")
            full = ms_spectrum(mass_fixture(), 1.19, 1.41)
            export_csv(full, target, overwrite=True)
            values = np.loadtxt(target, delimiter=",", skiprows=1)
            np.testing.assert_array_equal(values[:, 1], [30, 10, 20, 30])
            np.testing.assert_allclose(values[:, 2], [100, 100/3, 200/3, 100])


class MSQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_choices_invalid_drafts_and_report_state_preserved(self):
        window = Workspace()
        from gcviewer.figures.workspace import demo_trace
        window.add_sample(demo_trace())
        window.show()
        original = window.active
        original.state.settings.x_break = (4, 7)
        original.state.add_label(original.trace, 1.65, "Original label")
        function = mass_fixture()
        dialog = MSInspector(window, ms_tic(function), autoload=False)
        dialog.report_requested.connect(window.add_inspection_report)
        dialog.set_functions([function, replace(function, name="MS2", data=function.data * 2)])
        dialog.show()
        self.app.processEvents()
        dialog.function.setCurrentIndex(1)
        dialog.mode.setCurrentIndex(dialog.mode.findData("eic"))
        dialog.mz.setText("90.8")
        self.assertFalse(dialog.create_button.isEnabled())
        QTest.mouseClick(dialog.update_button, Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.trace.function, "MS2")
        np.testing.assert_array_equal(dialog.trace.signal, [0, 80, 0, 40])
        dialog.mode.setCurrentIndex(dialog.mode.findData("mean"))
        dialog.start.setText("1.21")
        dialog.end.setText("1.39")
        self.assertFalse(dialog.update_preview())
        self.assertIn("No scans", dialog.status.text())
        self.assertFalse(dialog.create_button.isEnabled())
        dialog.start.setText("1.19")
        dialog.end.setText("1.41")
        QTest.mouseClick(dialog.update_button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(window.active.trace.x_unit, "m/z")
        np.testing.assert_array_equal(window.active.trace.signal, [60, 20, 40, 60])
        self.assertEqual(window.break_controls.enabled["x_break"].text(), "m/z")
        self.assertFalse(window.inspect_action.isEnabled())
        self.assertEqual(original.state.settings.x_break, (4, 7))
        self.assertEqual(original.state.labels[0].text, "Original label")
        self.assertTrue(dialog.closed)
        self.assertFalse(dialog.functions)
        window.close()

    def test_close_cancels_owned_loader_and_pending_start(self):
        dialog = MSInspector(None, ms_tic(mass_fixture()), autoload=False)
        with tempfile.TemporaryDirectory() as directory:
            dialog.directory = tempfile.TemporaryDirectory(dir=directory)
            output = Path(dialog.directory.name)
            dialog.reject()
            dialog.load()
            self.assertFalse(output.exists())
            self.assertIsNone(dialog.loader.process)

    def test_inspector_pauses_pending_queue_then_resumes_and_parent_close_hides_it(self):
        window = Workspace()
        window.add_sample(replace(ms_tic(mass_fixture()), synthetic=False))
        window.show()
        with patch.object(MSInspector, "load"):
            window.open_inspector()
            self.app.processEvents()
            dialog = window.inspector
            window.pending["queued"] = object()
            with patch.object(window, "launch_request") as launch:
                window.pump_queue()
                launch.assert_not_called()
                dialog.reject()
                self.assertIsNone(window.inspector)
                launch.assert_called_once()
            window.open_inspector()
            self.app.processEvents()
            dialog = window.inspector
            window.close()
            self.assertTrue(dialog.closed)
            self.assertFalse(dialog.isVisible())

    def test_real_owned_detail_worker_error_is_visible_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = replace(ms_tic(mass_fixture()), source=str(Path(directory) / "missing.raw"))
            dialog = MSInspector(None, trace)
            dialog.show()
            for _ in range(500):
                QTest.qWait(20)
                if dialog.status.text().startswith("Could not"):
                    break
            self.assertIn("acquisition directory", dialog.status.text())
            self.assertFalse(dialog.create_button.isEnabled())
            self.assertIsNone(dialog.loader.process)
            self.assertIsNone(dialog.directory)
            dialog.reject()


if __name__ == "__main__":
    unittest.main()
