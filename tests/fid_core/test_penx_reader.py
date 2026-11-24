"""Read and validate synthetic TotalChrom acquisitions."""
import hashlib
import struct
import unittest

import numpy as np

from gcviewer.parsers.totalchrom import PenxFormatError, read_raw_bytes
from tests.penx_fixture import penx_bytes


class PenxReaderTests(unittest.TestCase):
    def test_counted_signed_signal_and_shifted_header_ignore_footer(self):
        counts = [-100, 0, 200, 123456, -50]
        short, _ = penx_bytes(counts, sample_name="Short", scale=(2., 4.))
        long, _ = penx_bytes(counts, sample_name="Long synthetic sample " * 40, scale=(2., 4.))
        for data in (short, long):
            run = read_raw_bytes(data)
            np.testing.assert_array_equal(run.counts, counts)
            np.testing.assert_array_equal(run.microvolts, np.array(counts) / 8.)
            self.assertEqual(run.sha256, hashlib.sha256(data).hexdigest())
            self.assertFalse(run.counts.flags.writeable)
        self.assertLess(read_raw_bytes(short).data_offset, 1024)
        self.assertGreater(read_raw_bytes(long).data_offset, 1024)

    def test_time_uses_stored_rate_delay_and_one_based_point_time(self):
        run = read_raw_bytes(penx_bytes([-1, 3, 9], rate=20., delay=.5)[0])
        np.testing.assert_allclose(run.times_s, [30.05, 30.10, 30.15], rtol=0, atol=1e-14)
        np.testing.assert_allclose(run.times_min, run.times_s / 60, rtol=0, atol=0)

    def test_corrupt_counts_and_truncated_records_fail_instead_of_guessing(self):
        good, offsets = penx_bytes()
        corrupt = bytearray(good)
        corrupt[offsets["data"]:offsets["data"] + 4] = struct.pack(">i", -100)
        wrong_type = bytearray(good); wrong_type[4:8] = struct.pack(">i", 2)
        bad_count = bytearray(good); bad_count[offsets["array_count"]:offsets["array_count"] + 4] = struct.pack(">i", 1100)
        for data in (b"XXXX" + good[4:], bytes(corrupt), bytes(wrong_type), bytes(bad_count),
                     good[:offsets["data"] + 8], good[:offsets["scale"] + 16]):
            with self.subTest(length=len(data)), self.assertRaises(PenxFormatError):
                read_raw_bytes(data)

    def test_invalid_calibration_and_timing_rejected(self):
        for kwargs in ({"scale": (float("inf"), 2.)}, {"scale": (float("nan"), 2.)},
                       {"scale": (1e308, 1e308)}, {"scale": (1e-300, 1e-300)},
                       {"scale": (0., 2.)}, {"channel": "B"}, {"rate": -1.},
                       {"rate": float("nan")}, {"delay": float("nan")},
                       {"delay": -1.}, {"runtime": float("inf")}, {"counts": []}):
            with self.subTest(kwargs=kwargs), self.assertRaises(PenxFormatError):
                read_raw_bytes(penx_bytes(**kwargs)[0])

    def test_incomplete_version_runtime_warnings_preserved(self):
        data, _ = penx_bytes(complete=1, version=10020, runtime=42.)
        run = read_raw_bytes(data)
        self.assertEqual(len(run.warnings), 3)
        self.assertTrue(any("not marked complete" in w for w in run.warnings))
        self.assertTrue(any("unverified format" in w for w in run.warnings))
        self.assertTrue(any("does not match" in w for w in run.warnings))
