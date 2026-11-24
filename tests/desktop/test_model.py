"""Synthetic/model tests, explicitly not real acquisition validation."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PIL import Image
from pypdf import PdfReader
from rainbow.datafile import DataFile
from rainbow.datadirectory import DataDirectory

from gcviewer.data_models.acquisition import Trace
from gcviewer.figures.workspace import FigureState, demo_trace, export_figure, render_figure
from gcviewer.services.acquisition import load_source, ms_traces
from gcviewer.services.worker import read_result, write_result


class ModelTests(unittest.TestCase):
    def test_bad_arrays_rejected_without_repair(self):
        for time, signal in (([], []), ([0], [1]), ([0, 1], [2]), ([1, 0], [3, 4]),
                             ([0, 0], [3, 4]), ([0, 1], [np.nan, 4]), ([0, np.inf], [1, 2])):
            with self.subTest(time=time), self.assertRaises(ValueError):
                Trace("bad", "test", "Synthetic", time, signal)

    def test_signal_preserved_and_ranges_validated(self):
        trace = demo_trace()
        source = trace.signal.copy()
        state = FigureState.report(trace)
        state.settings.x_range = (5, 6)
        render_figure(trace, state)
        np.testing.assert_array_equal(source, trace.signal)
        with self.assertRaises(ValueError):
            trace.signal[0] = 123
        for invalid in ((20, 30), (3, 2), (np.nan, 5), (3,)):
            state.settings.x_range = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                render_figure(trace, state)

    def test_flat_and_two_point_traces(self):
        for signal in ([0, 0], [-1, -2], [1, 1]):
            trace = Trace("small", "test", "Synthetic", [0, 1], signal)
            figure, axes, _ = render_figure(trace, FigureState.report(trace))
            FigureCanvasAgg(figure).draw()
            self.assertGreater(axes.get_ylim()[1], axes.get_ylim()[0])

    def test_formats_preserve_dimensions_anchors_and_vector_elements(self):
        trace = demo_trace()
        state = FigureState.report(trace)
        state.settings.title = "Crowded trace report"
        state.settings.x_label = "Retention time / min"
        state.settings.y_label = "Synthetic response / a.u."
        state.settings.width_mm, state.settings.height_mm, state.settings.dpi = 160, 100, 200
        for x, text, pos in ((5.05, "Peak A", (.3, .76)), (5.3, "Peak B", (.52, .9)), (5.53, "Peak C", (.73, .76))):
            state.add_label(trace, x, text, pos)
        preview, axes, artists = render_figure(trace, state)
        expected = [(a.xy, a.get_position()) for a in artists]
        with tempfile.TemporaryDirectory() as folder:
            for suffix in ("png", "pdf", "svg"):
                path, sidecar = export_figure(trace, state, Path(folder) / f"report.{suffix}")
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                self.assertEqual(meta["settings"]["title"], state.settings.title)
                self.assertEqual(meta["annotations"][1]["position"], [.52, .9])
                self.assertEqual(meta["annotations"][1]["anchor_time_min"], trace.time[state.labels[1].index])
                self.assertTrue(meta["synthetic"])
            with Image.open(Path(folder) / "report.png") as img:
                self.assertEqual(img.size, (int(160 / 25.4 * 200), int(100 / 25.4 * 200)))
            page = PdfReader(Path(folder) / "report.pdf").pages[0]
            self.assertAlmostEqual(float(page.mediabox.width), 160 / 25.4 * 72, places=5)
            self.assertAlmostEqual(float(page.mediabox.height), 100 / 25.4 * 72, places=5)
            self.assertEqual(len(page.images), 0)
            self.assertIn("Crowded trace report", page.extract_text())
            self.assertIn("Peak B", page.extract_text())
            svg = (Path(folder) / "report.svg").read_text(encoding="utf-8")
            self.assertIn("<path", svg)
            self.assertNotIn("<image", svg)
            self.assertIn("Peak C", svg)
        _, _, again = render_figure(trace, state)
        self.assertEqual(expected, [(a.xy, a.get_position()) for a in again])

    def test_export_protects_acquisitions_and_existing_sidecar(self):
        trace, state = demo_trace(), FigureState.report(demo_trace())
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            raw = folder / "sample.RAW"
            raw.mkdir()
            with self.assertRaises(ValueError):
                export_figure(trace, state, raw / "report.png")
            path = folder / "report.svg"
            sidecar = folder / "report.svg.json"
            sidecar.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                export_figure(trace, state, path)
            self.assertFalse(path.exists())
            self.assertEqual(sidecar.read_text(), "keep")
            with self.assertRaises(ValueError):
                export_figure(trace, state, folder / "sample.raw")


class AdapterTests(unittest.TestCase):
    def make_acquisition(self):
        time = np.array([0., 1., 2.])
        masses = np.array([50., 51.])
        uv = DataFile("uv.dat", "UV", time, np.array([250.]), np.ones((3, 1)), {})
        one = DataFile("_FUNC001.DAT", "MS", time, masses, np.array([[1., 2.], [30., 40.], [5., 6.]]), {"test": "one"})
        two = DataFile("_func002.dat", "MS", time, masses, np.array([[3., 4.], [50., 60.], [7., 8.]]), {"test": "two"})
        return DataDirectory("test.raw", [uv, one, two], {"synthetic_fixture": True})

    def test_real_rainbow_objects_multiple_functions_no_smoothing(self):
        traces = ms_traces(self.make_acquisition(), "test.raw")
        self.assertEqual([t.function for t in traces], ["_FUNC001.DAT", "_func002.dat"])
        np.testing.assert_array_equal(traces[0].signal, [3, 70, 11])
        self.assertEqual(traces[1].metadata["function"], {"test": "two"})
        with tempfile.TemporaryDirectory() as folder:
            write_result(folder, traces)
            loaded = read_result(folder)
            np.testing.assert_array_equal(loaded[1].signal, traces[1].signal)
            self.assertEqual(loaded[1].function, traces[1].function)

    def test_invalid_and_non_ms_functions(self):
        acquisition = self.make_acquisition()
        acquisition.datafiles[1].data = np.empty((0, 2))
        traces = ms_traces(acquisition, "test.raw")
        self.assertEqual(len(traces), 1)
        self.assertIn("_FUNC001.DAT", traces[0].warnings[0])
        acquisition.datafiles = acquisition.datafiles[:1]
        with self.assertRaisesRegex(ValueError, "No usable MS"):
            ms_traces(acquisition, "test.raw")

    def test_native_input_types_and_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.raw"
            with self.assertRaises(ValueError):
                load_source(path, "ms")
            path.write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "header"):
                load_source(path, "fid")
            with self.assertRaisesRegex(ValueError, "directory"):
                load_source(path, "ms")
            with self.assertRaises(ValueError):
                load_source(Path(folder) / "unsupported.csv", "fid")

    def test_penx_adapter_retains_calibrated_original_signal(self):
        from tests.penx_fixture import synthetic_penx
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.raw"
            synthetic_penx(path, counts=[-20, 0, 100], scale=(2., 4.))
            trace = load_source(path, "fid")[0]
            self.assertIn("no baseline subtraction", trace.transformations[0])
            self.assertFalse(trace.warnings)
            self.assertEqual(trace.y_label, "Response (µV)")
            np.testing.assert_array_equal(trace.signal, [-2.5, 0, 12.5])


if __name__ == "__main__":
    unittest.main()
