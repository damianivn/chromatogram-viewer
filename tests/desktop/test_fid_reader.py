"""Strict FID boundaries and app contracts, using structural synthetic files."""
from dataclasses import replace
import csv
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from gcviewer.services.acquisition import load_fid, load_source
from gcviewer.services.worker import main, read_fid_result, read_result
from gcviewer.services.fid_acquisition import restore_run, run_record
from gcviewer.figures.workspace import FigureState, export_figure, y_axis_display
from gcviewer.reports.numeric import export_csv
from gcviewer.parsers.totalchrom import read_raw_bytes
from gcviewer.parsers.totalchrom.discovery import is_penx_file
from gcviewer.data_models.totalchrom import CLIP_COUNTS
from tests.penx_fixture import penx_bytes, synthetic_penx


class FidReaderTests(unittest.TestCase):
    def test_discovery_accepts_only_type_one_files(self):
        with tempfile.TemporaryDirectory() as folder:
            raw = synthetic_penx(Path(folder) / "good.RAW")
            self.assertTrue(is_penx_file(raw))
            bad = bytearray(raw.read_bytes()); bad[4:8] = struct.pack(">i", 19)
            raw.write_bytes(bad)
            self.assertFalse(is_penx_file(raw))
            with self.assertRaisesRegex(ValueError, "header"):
                load_fid(raw)

    def test_worker_roundtrip_retains_original_counts_calibration_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            path = synthetic_penx(folder / "fixture.raw", counts=[-100, 0, 200, 50], scale=(2., 4.), delay=.3)
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(main(["fid", str(path), str(folder)]), 0)
            run, trace = read_fid_result(folder), read_result(folder)[0]
            self.assertEqual(run.sha256, checksum)
            self.assertEqual(run.header.sample_name, "Synthetic FID fixture")
            np.testing.assert_array_equal(run.counts, [-100, 0, 200, 50])
            np.testing.assert_array_equal(trace.time, run.times_min)
            np.testing.assert_array_equal(trace.signal, run.microvolts)
            self.assertFalse(run.counts.flags.writeable)
            self.assertEqual(trace.metadata["fid_acquisition"]["reader_revision"], "tcfid-0.3.1-gcviewer-1")
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), checksum)

    def test_payload_corruption_is_rejected(self):
        run = read_raw_bytes(penx_bytes([0, 10, 20, 50])[0], path=Path("fixture.raw"))
        record = json.loads(json.dumps(run_record(run)))
        with self.assertRaisesRegex(ValueError, "checksum"):
            restore_run(record, np.array([0, 11, 20, 50], dtype=np.int32))
        with self.assertRaisesRegex(ValueError, "counts"):
            restore_run(record, np.array([0, 10, 20, 50], dtype=float))
        record["schema"] = "unknown"
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            restore_run(record, run.counts)

    def test_csv_keeps_microvolts_and_figures_record_display_conversion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = synthetic_penx(root / "fixture.raw", counts=[-100, 0, 200, 50], scale=(2., 4.))
            trace = load_source(path, "fid")[0]
            state = FigureState.report(trace)
            self.assertEqual(y_axis_display(trace, state.settings), {"mode": "readable", "divisor": 1000., "label": "Response (mV)"})
            export_figure(trace, state, root / "figure.svg")
            info = json.loads((root / "figure.svg.json").read_text())
            self.assertEqual(info["y_axis_display"]["divisor"], 1000.)
            self.assertEqual(info["source_metadata"]["fid_acquisition"]["units"], "uV")
            state.settings = replace(state.settings, normalize=True, smoothing_window=3, x_range=(trace.time[1], trace.time[2]))
            export_csv(trace, root / "raw.csv", settings=state.settings)
            with (root / "raw.csv").open(encoding="utf-8", newline="") as file:
                rows = list(csv.reader(file))
            self.assertEqual(rows[0], ["Retention time (min)", "Response (µV)"])
            np.testing.assert_array_equal([float(row[1]) for row in rows[1:]], [-12.5, 0, 25, 6.25])
            self.assertEqual(len(rows), 5)
            self.assertEqual(y_axis_display(trace, state.settings)["label"], "Normalized signal (%)")
            self.assertFalse(json.loads((root / "raw.csv.json").read_text())["figure_processing_applied_to_csv"])

    def test_clipping_disclosed_without_replacing_original_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = synthetic_penx(Path(folder) / "clipped.raw", counts=[0, CLIP_COUNTS - 4, CLIP_COUNTS])
            run = load_fid(path)
            trace = load_source(path, "fid")[0]
            np.testing.assert_array_equal(run.clipped, [False, True, True])
            self.assertIn("2 points", trace.warnings[0])
            self.assertEqual(trace.metadata["fid_acquisition"]["clipped_points"], 2)


if __name__ == "__main__":
    unittest.main()
