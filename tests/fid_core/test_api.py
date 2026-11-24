"""Settings round-trips, provenance, explicit reader API and file discovery."""
import hashlib
import json
import unittest

import numpy as np

from tests.fid_core.reference import need_file
from gcviewer.analysis.retention_names import Component
from gcviewer.analysis.totalchrom_fid import IntegrationParams, TimedEvent
from gcviewer.parsers.totalchrom import read_raw
from gcviewer.parsers.totalchrom.discovery import find_raw_files, is_penx_file


class TestSettingsRoundTrip(unittest.TestCase):
    def test_params_json(self):
        p = IntegrationParams(50.0, 100.0, 2, 0.2, 0.02,
                              (TimedEvent(1.931, "+P"), TimedEvent(0.0, "-P"), TimedEvent(5.0, "NT", 20.0)))
        q = IntegrationParams.from_dict(json.loads(json.dumps(p.to_dict())))
        self.assertEqual(p, q)

    def test_component_json(self):
        c = Component("nicotine", 5.34, 0.04)
        self.assertEqual(Component.from_dict(json.loads(json.dumps(c.to_dict()))), c)
        with self.assertRaises(ValueError):
            Component(" ", 1.0)


class TestProvenance(unittest.TestCase):
    def test_sha256_of_file(self):
        p = need_file("sample001.raw")
        self.assertEqual(read_raw(p).sha256, hashlib.sha256(p.read_bytes()).hexdigest())


class TestReaderAPI(unittest.TestCase):
    def test_read_raw_returns_original_and_calibrated_data(self):
        p = need_file("sample001.raw")
        run = read_raw(p)
        self.assertEqual(run.n_points, 9875)
        self.assertAlmostEqual(run.times_min[0] * 60, 0.08, places=12)
        np.testing.assert_allclose(run.microvolts, run.counts * run.uv_per_count)
        self.assertEqual((run.rate_hz, run.data_offset), (12.5, 1008))

    def test_only_raw_data_files_count(self):
        folder = need_file("sample001.raw").parent
        names = find_raw_files(folder)
        self.assertIn("sample001.raw", names)
        rst = next((f for f in folder.iterdir() if f.suffix.lower() == ".rst" and f.stat().st_size), None)
        if rst is not None:
            self.assertFalse(is_penx_file(rst))


if __name__ == "__main__":
    unittest.main()
