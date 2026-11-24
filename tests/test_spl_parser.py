"""Tests for TotalChrom / TurboMass SPL sample list parsing."""

import os
import tempfile
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace

from gcviewer.reports.sample_list import export_spl, sample_list_table_df, spl_to_df
from gcviewer.parsers.spl import is_spl_file, match_rows_to_raw, parse_spl, spl_raw_name, _read_overflow_record

FIXTURE = Path(os.environ.get("GCVIEWER_TEST_SPL") or ".")


@unittest.skipUnless(FIXTURE.is_file(), "Private reference SPL unavailable")
class TestSplParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta, cls.rows = parse_spl(FIXTURE)

    def test_is_spl_file(self):
        self.assertTrue(is_spl_file(FIXTURE))
        self.assertFalse(is_spl_file(__file__))

    def test_parse_ecigs_sample_list(self):
        self.assertEqual(self.meta["table"], "ANALYSIS")
        self.assertEqual(self.meta["vendor"], "totalchrom_turbomass")
        self.assertGreater(self.meta["row_count"], 60)
        self.assertLess(self.meta["row_count"], self.meta["source_rows"])

        names = [r["file_name"] for r in self.rows]
        self.assertIn("ADTP_ISK2", names)
        self.assertIn("ADTP_FB1", names)
        self.assertIn("ADTP_CC2", names)
        self.assertIn("ADTP_ISK2_2", names)

        isk2 = next(r for r in self.rows if r["file_name"] == "ADTP_ISK2")
        self.assertEqual(isk2["method"], "ADTP_ecigs_wk1_slower")
        self.assertEqual(isk2["detector"], "A")
        self.assertEqual(isk2["vial"], "2")
        self.assertEqual(isk2["sample_type"], "Analyte")
        self.assertEqual(isk2["description"], "ISK - 10/80 spike")
        self.assertEqual(spl_raw_name(isk2), "ADTP_ISK2.raw")

        fb1 = self.rows[0]
        self.assertEqual(fb1["file_name"], "ADTP_FB1")
        self.assertEqual(fb1["method"], "ADTP_ecigs_wk1_slower")
        self.assertEqual(fb1["detector"], "A")
        self.assertEqual(fb1["vial"], "6")
        self.assertEqual(fb1["sample_type"], "Analyte")
        self.assertEqual(fb1["description"], "FB- 0/0 spike")

    def test_cont_calib_names_inferred(self):
        names = {r["file_name"] for r in self.rows}
        self.assertIn("ADTP_CC1", names)
        self.assertIn("ADTP_CC2", names)

    def test_forwarded_records_recovered_and_blank_position_disclosed(self):
        self.assertEqual(self.meta["source_rows"], 75)
        self.assertEqual(len(self.rows), 74)
        by_name = {r["source_file_name"]: r for r in self.rows}
        self.assertEqual(by_name["ADTP_CC7"]["vial"], "2")
        self.assertEqual(by_name["ADTP_CC7"]["description"], "Cal 100/800")
        self.assertEqual(by_name["ADTP_SM1_2"]["vial"], "10")
        self.assertEqual(by_name["ADTP_SM1_2"]["description"], "SM - 0/0 spike_2")
        self.assertEqual([r["index"] for r in self.meta["skipped_rows"]], [70])
        self.assertIn("70", self.meta["warnings"][0])
        self.assertEqual([r["index"] for r in self.rows], [i for i in range(1, 76) if i != 70])
        self.assertTrue(all(r["index"] == r["source_index"] + 1 for r in self.rows))

    def test_match_rows_to_raw_empty_folder(self):
        rows = [dict(r) for r in self.rows]
        match_rows_to_raw(rows, "/nonexistent/path", finder_fn=lambda _: [])
        self.assertIsNone(rows[0]["raw_match"])

    def test_match_rows_to_raw_case_insensitive(self):
        rows = [dict(r) for r in self.rows]
        finder = lambda _: ["ADTP_ISK2.raw", "ADTP_FB1.RAW"]
        match_rows_to_raw(rows, "/data", finder_fn=finder)

        isk2 = next(r for r in rows if r["file_name"] == "ADTP_ISK2")
        fb1 = next(r for r in rows if r["file_name"] == "ADTP_FB1")
        self.assertEqual(isk2["raw_match"], "ADTP_ISK2.raw")
        self.assertEqual(fb1["raw_match"], "ADTP_FB1.RAW")

        missing = next(r for r in rows if r["file_name"] == "ADTP_CC2")
        self.assertIsNone(missing["raw_match"])

    def test_spl_to_df_columns(self):
        df = spl_to_df(self.meta, self.rows)
        self.assertEqual(len(df), len(self.rows))
        self.assertIn("File Name", df.columns)
        self.assertIn("Acquisition Method", df.columns)
        self.assertIn("Description", df.columns)
        self.assertEqual(df.attrs["spl_meta"]["vendor"], "totalchrom_turbomass")

    def test_sample_list_table_df_status(self):
        rows = [dict(r) for r in self.rows[:3]]
        rows[0]["raw_match"] = "ADTP_FB1.raw"
        rows[1]["raw_match"] = None

        df = sample_list_table_df(rows)
        self.assertIn("Status", df.columns)
        self.assertNotIn("Load", df.columns)
        self.assertEqual(df.loc[0, "Status"], "Found")
        self.assertEqual(df.loc[1, "Status"], "No data file")
        self.assertEqual(df.loc[0, "_raw"], "ADTP_FB1.raw")

    def test_export_spl_csv_and_xlsx(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "out.csv"
            xlsx_path = Path(tmp) / "out.xlsx"

            meta, rows, out = export_spl(FIXTURE, csv_path)
            self.assertTrue(out.is_file())
            self.assertEqual(meta["row_count"], len(rows))
            self.assertGreater(csv_path.stat().st_size, 100)
            self.assertIn("File Name", csv_path.read_text(encoding="utf-8"))

            export_spl(FIXTURE, xlsx_path)
            self.assertTrue(xlsx_path.is_file())
            self.assertGreater(xlsx_path.stat().st_size, 1000)


class OverflowRecordTests(unittest.TestCase):
    @staticmethod
    def table(offsets):
        page = bytearray(2048)
        struct.pack_into("<2sHIH", page, 0, b"\x01\x01", 0, 1, len(offsets))
        struct.pack_into("<" + "H" * len(offsets), page, 10, *offsets)
        page[1024:1536] = b"R" * 512
        page[1536:] = b"N" * 512
        return SimpleNamespace(version=3, page_size=2048, _data_pages={2048: bytes(page)})

    def test_every_preceding_offset_flag_is_removed_before_slicing(self):
        for flag in (0, 0x4000, 0x8000, 0xc000):
            with self.subTest(flag=flag):
                table = self.table([flag | 1536, 0x8000 | 1024])
                self.assertEqual(_read_overflow_record(table, (1 << 8) | 1), b"R" * 512)

    def test_first_record_ends_at_page_boundary(self):
        table = self.table([0x8000 | 1536])
        self.assertEqual(_read_overflow_record(table, 1 << 8), b"N" * 512)

    def test_invalid_pointers_fail_instead_of_silently_losing_rows(self):
        table = self.table([1536, 0x8000 | 1024])
        for pointer in ((2 << 8), (1 << 8) | 2):
            with self.subTest(pointer=pointer), self.assertRaisesRegex(ValueError, "no incomplete list"):
                _read_overflow_record(table, pointer)
        for offsets in ([1024, 1536], [1536, 5]):
            with self.subTest(offsets=offsets), self.assertRaisesRegex(ValueError, "boundaries"):
                _read_overflow_record(self.table(offsets), (1 << 8) | 1)


if __name__ == "__main__":
    unittest.main()
