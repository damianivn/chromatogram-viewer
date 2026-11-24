"""Reader tests. Tests needing real acquisitions skip unless $TCFID_TEST_DATA is set."""
import struct
import unittest

import numpy as np

from tests.fid_core.reference import need_file, read_rax_counts
from gcviewer.parsers.totalchrom.binary import PenxFormatError
from gcviewer.parsers.totalchrom.raw import read_raw, read_raw_bytes

RAX_PAIRS = ("sample001", "sample002", "sample003")
TDAP_2025 = tuple(f"tdap_mon_1pm00{i}" for i in range(1, 6))
UV_PER_COUNT = 1.0 / (2.0 * 54.01791)


def need(name):
    return need_file(name)


class TestAgainstTotalChromExport(unittest.TestCase):
    def test_counts_match_rax_point_for_point(self):
        for stem in RAX_PAIRS:
            with self.subTest(stem):
                run = read_raw(need(stem + ".raw"))
                np.testing.assert_array_equal(run.counts, read_rax_counts(need(stem + ".rax")))


class TestHeader(unittest.TestCase):
    def test_every_file_reads_cleanly(self):
        for stem in RAX_PAIRS + TDAP_2025:
            with self.subTest(stem):
                run = read_raw(need(stem + ".raw"))
                self.assertEqual(run.warnings, ())
                self.assertEqual(run.n_points, 9875)
                self.assertEqual(run.rate_hz, 12.5)
                self.assertAlmostEqual(run.uv_per_count, UV_PER_COUNT, places=15)
                self.assertAlmostEqual(run.times_s[0], 0.08, places=12)
                self.assertAlmostEqual(run.header.run_time_min * 60 * run.rate_hz, run.n_points, places=6)
                self.assertEqual(run.header.instrument_name, "Clarus 500 FID")

    def test_known_metadata(self):
        h = read_raw(need("tdap_mon_1pm002.raw")).header
        self.assertEqual((h.sample_name, h.vial, h.sequence_row, h.channel), ("0.2", 2, 1, "A"))
        self.assertEqual(h.injection_utc.strftime("%Y-%m-%d %H:%M:%S"), "2025-10-20 19:05:16")

    def test_header_length_varies_between_files(self):
        a = read_raw(need("sample001.raw")).data_offset
        b = read_raw(need("tdap_mon_1pm001.raw")).data_offset
        self.assertEqual((a, b), (1008, 1020))

    def test_longer_text_field_moves_the_data(self):
        buf = need("sample001.raw").read_bytes()
        old = struct.pack(">I", 17) + b"nicontine in cigs" + b"\0" * 3
        new = struct.pack(">I", 23) + b"nicontine in cigarettes" + b"\0"
        self.assertEqual(buf.count(old), 1)
        edited = read_raw_bytes(buf.replace(old, new))
        original = read_raw_bytes(buf)
        self.assertEqual(edited.data_offset, original.data_offset + 4)
        self.assertEqual(edited.header.study, "nicontine in cigarettes")
        np.testing.assert_array_equal(edited.counts, original.counts)

    def test_bad_files_raise(self):
        buf = need("sample001.raw").read_bytes()
        run = read_raw_bytes(buf)
        with self.assertRaises(PenxFormatError):
            read_raw_bytes(b"XXXX" + buf[4:])
        with self.assertRaises(PenxFormatError):
            read_raw_bytes(buf[:5000])
        corrupt = bytearray(buf)
        corrupt[run.data_offset - 4:run.data_offset] = struct.pack(">i", 9874)
        with self.assertRaises(PenxFormatError):
            read_raw_bytes(bytes(corrupt))


class TestUnits(unittest.TestCase):
    def test_clipping_ceiling_is_993_88_mV(self):
        run = read_raw(need("tdap_mon_1pm001.raw"))
        self.assertAlmostEqual(run.counts.max() * run.uv_per_count / 1000.0, 993.88, places=2)
        self.assertGreater(run.clipped.sum(), 80)
        self.assertFalse(run.clipped[:1000].any())


if __name__ == "__main__":
    unittest.main()
