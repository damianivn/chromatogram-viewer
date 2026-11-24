"""Real SPL metadata fixture, generated acquisitions, and Qt library/queue checks."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "ChromatogramViewer-matplotlib"))

from PySide6.QtCore import Qt, QProcess, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gcviewer.services.library import LibraryEntry, discover_library
from gcviewer.desktop.library_dialog import LibraryDialog
from gcviewer.services.worker import write_result
from gcviewer.desktop.window import Workspace
from gcviewer.figures.workspace import demo_trace, export_figure
from tests.penx_fixture import synthetic_penx

FIXTURE = Path(os.environ.get("GCVIEWER_TEST_SPL") or ".")


class DiscoveryTests(unittest.TestCase):
    @unittest.skipUnless(FIXTURE.is_file(), "Private reference SPL unavailable")
    def test_real_spl_literal_names_prevent_collapsing_distinct_acquisitions(self):
        from gcviewer.parsers.spl import parse_spl
        _, rows = parse_spl(FIXTURE)
        variants = [r for r in rows if r["file_name"] == "ADTP_ISK1_2"]
        self.assertEqual({r["source_file_name"] for r in variants}, {"ADTP_ISK1_2", "ADTP_ISK1-2", "ADTP_ISK1_2-2"})
        with tempfile.TemporaryDirectory() as folder:
            for row in variants:
                (Path(folder) / (row["source_file_name"].lower() + ".raw")).mkdir()
            entries = discover_library(folder, "ms", FIXTURE)["entries"]
            matched = [e for e in entries if e["available"]]
            self.assertEqual(len(matched), 3)
            self.assertEqual(len({e["path"] for e in matched}), 3)
            self.assertTrue(all("Original SPL" in e["list_metadata"]["matching"]["rule"] for e in matched))
            missing_name = "ADTP_ISK1-2"
            (Path(folder) / (missing_name.lower() + ".raw")).rmdir()
            refreshed = discover_library(folder, "ms", FIXTURE)["entries"]
            missing = next(e for e in refreshed if e["name"] == missing_name)
            self.assertFalse(missing["available"])
            self.assertEqual(missing["status"], "Missing acquisition")

    @unittest.skipUnless(FIXTURE.is_file(), "Private reference SPL unavailable")
    def test_real_spl_missing_case_match_and_refresh_without_loading_signal(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("gcviewer.parsers.waters.load_raw", side_effect=AssertionError("Listing parsed a signal")):
                before = discover_library(folder, "ms", FIXTURE)
                self.assertEqual(len(before["entries"]), 74)
                self.assertFalse(any(row["available"] for row in before["entries"]))
                first = before["entries"][0]
                raw = Path(folder) / (first["name"].lower() + ".RAW")
                raw.mkdir()
                after = discover_library(folder, "ms", FIXTURE)
                found = after["entries"][0]
                self.assertTrue(found["available"])
                self.assertEqual(found["key"], first["key"])
                self.assertEqual(Path(found["path"]), raw)
                self.assertEqual(found["list_metadata"]["row"]["description"], first["description"])
                self.assertEqual(found["list_metadata"]["list"]["vendor"], "totalchrom_turbomass")

    @unittest.skipUnless(FIXTURE.is_file(), "Private reference SPL unavailable")
    def test_large_folder_does_not_drop_list_rows_or_confuse_matching_names(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for index in range(1050):
                (root / f"unrelated_{index:04}.raw").mkdir()
            for name in ("ADTP_CC7", "ADTP_SM1_2"):
                (root / f"{name}.raw").mkdir()
            listing = discover_library(root, "ms", FIXTURE)
            self.assertEqual(listing["folder_acquisitions"], 1052)
            self.assertEqual(len(listing["entries"]), 74)
            self.assertEqual({e["name"] for e in listing["entries"] if e["available"]}, {"ADTP_CC7", "ADTP_SM1_2"})
            self.assertIn("70", listing["list_warnings"][0])
            self.assertEqual(len(discover_library(root, "ms")["entries"]), 1052)

    def test_alias_is_disclosed_and_ambiguity_is_not_guessed(self):
        rows = [{"source_index": 0, "index": 1, "file_name": "A_B_C", "description": "", "method": "", "vial": "", "sample_type": ""}]
        with tempfile.TemporaryDirectory() as folder, patch("gcviewer.parsers.spl.parse_spl", return_value=({}, rows)):
            one = Path(folder) / "A-B_C.raw"
            one.mkdir()
            unique = discover_library(folder, "ms", "test.spl")["entries"][0]
            self.assertTrue(unique["available"])
            self.assertIn("alias", unique["status"])
            self.assertEqual(Path(unique["path"]), one)
            (Path(folder) / "A_B-C.raw").mkdir()
            ambiguous = discover_library(folder, "ms", "test.spl")["entries"][0]
            self.assertFalse(ambiguous["available"])
            self.assertEqual(ambiguous["status"], "Ambiguous filename")
            exact = Path(folder) / "A_B_C.raw"
            exact.mkdir()
            final = discover_library(folder, "ms", "test.spl")["entries"][0]
            self.assertTrue(final["available"])
            self.assertEqual(Path(final["path"]), exact)

    def test_fid_headers_and_wrong_input_types(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            synthetic_penx(folder / "good.RAW")
            (folder / "bad.raw").write_bytes(b"bad")
            (folder / "directory.raw").mkdir()
            with patch("gcviewer.parsers.totalchrom.read_raw", side_effect=AssertionError("Discovery parsed signal")):
                entries = discover_library(folder, "fid")["entries"]
            by_name = {e["name"]: e for e in entries}
            self.assertTrue(by_name["good.RAW"]["available"])
            self.assertFalse(by_name["bad.raw"]["available"])
            self.assertFalse(by_name["directory.raw"]["available"])
            for args in ((folder / "missing", "ms", None), (folder / "directory.raw", "ms", None),
                         (folder, "fid", folder / "unsupported.spl"), (folder, "ms", folder / "bad.spl")):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    discover_library(*args)


class LibraryQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.preferences_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.preferences_dir.cleanup)
        self.preferences_file = str(Path(self.preferences_dir.name).resolve() / "library.ini")
        self.window = Workspace()
        self.window.add_sample(demo_trace())
        self.dialog = LibraryDialog(self.window, preferences=QSettings(self.preferences_file, QSettings.Format.IniFormat))

    def tearDown(self):
        self.dialog.shutdown()
        self.window.close()
        self.app.processEvents()

    def test_directories_survive_process_restart_without_restoring_active_list(self):
        d = self.dialog
        data = Path(self.preferences_dir.name).resolve() / "Data folder"
        lists = Path(self.preferences_dir.name).resolve() / "Sample lists"
        data.mkdir()
        lists.mkdir()
        spl = lists / "chosen.SPL"
        spl.touch()
        d.folder.setText(str(data))
        d.spl.setText(str(spl))
        d.reject()
        code = """
import json, sys
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from gcviewer.desktop.library_dialog import LibraryDialog
app = QApplication([])
d = LibraryDialog(preferences=QSettings(sys.argv[1], QSettings.Format.IniFormat))
print(json.dumps([d.folder.text(), d.preferences.value('library/spl_folder'), d.spl.text(), d.worker is None]))
d.shutdown()
"""
        result = subprocess.run([sys.executable, "-c", code, self.preferences_file],
                                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [str(data), str(lists), "", True])

    def test_browsers_remember_separate_folders_and_cancel_keeps_them(self):
        d = self.dialog
        data = Path(self.preferences_dir.name).resolve() / "data"
        lists = Path(self.preferences_dir.name).resolve() / "lists"
        data.mkdir()
        lists.mkdir()
        spl = lists / "chosen.spl"
        spl.touch()
        with patch.object(d, "refresh"), patch("gcviewer.desktop.library_dialog.QFileDialog.getExistingDirectory", return_value=str(data)):
            d.browse_folder()
        with patch.object(d, "refresh"), patch("gcviewer.desktop.library_dialog.QFileDialog.getOpenFileName", return_value=(str(spl), "")) as chooser:
            d.browse_spl()
            self.assertEqual(chooser.call_args.args[2], str(data))
        d.spl.clear()
        with patch("gcviewer.desktop.library_dialog.QFileDialog.getOpenFileName", return_value=("", "")) as chooser:
            d.browse_spl()
            self.assertEqual(chooser.call_args.args[2], str(lists))
        with patch("gcviewer.desktop.library_dialog.QFileDialog.getExistingDirectory", return_value="") as chooser:
            d.browse_folder()
            self.assertEqual(chooser.call_args.args[2], str(data))
        self.assertEqual(d.folder.text(), str(data))
        self.assertEqual(d.preferences.value("library/data_folder"), str(data))
        self.assertEqual(d.preferences.value("library/spl_folder"), str(lists))

    def test_invalid_edits_and_unavailable_saved_folder_do_not_erase_preferences(self):
        d = self.dialog
        data = Path(self.preferences_dir.name).resolve() / "data"
        data.mkdir()
        d.folder.setText(str(data))
        d.folder.editingFinished.emit()
        for path in ("", str(data / "missing")):
            d.folder.setText(path)
            d.folder.editingFinished.emit()
            self.assertEqual(d.preferences.value("library/data_folder"), str(data))
        data.rmdir()
        restored = LibraryDialog(preferences=QSettings(self.preferences_file, QSettings.Format.IniFormat))
        try:
            self.assertEqual(restored.folder.text(), str(data))
            self.assertIsNone(restored.worker)
            with patch("gcviewer.desktop.library_dialog.QFileDialog.getExistingDirectory", return_value="") as chooser:
                restored.browse_folder()
                self.assertEqual(chooser.call_args.args[2], str(Path.home()))
        finally:
            restored.shutdown()
        self.assertEqual(d.preferences.value("library/data_folder"), str(data))

    def test_filter_sort_selection_and_input_changes_keep_correct_paths(self):
        entries = [LibraryEntry("z", "Zulu", "/z.raw", "ms", "Found", True),
                   LibraryEntry("a", "Alpha", "/a.raw", "ms", "Found", True),
                   LibraryEntry("b", "Missing", "/b.raw", "ms", "Missing acquisition", False)]
        d = self.dialog
        d.set_entries(entries)
        d.select_available()
        self.assertEqual({e.key for e in d.selected_entries()}, {"a", "z"})
        d.table.sortItems(0, Qt.SortOrder.AscendingOrder)
        d.search.setText("alpha")
        d.select_available()
        d.table.sortItems(0, Qt.SortOrder.DescendingOrder)
        self.assertEqual([e.path for e in d.selected_entries()], ["/a.raw"])
        captured = []
        d.open_requested.connect(captured.extend)
        d.show()
        d.open_selected()
        self.assertEqual([e.key for e in captured], ["a"])
        self.assertFalse(d.isVisible())
        d.show()
        d.folder.setText("a different folder")
        self.assertFalse(d.open_button.isEnabled())
        d.open_selected()
        self.assertEqual(len(captured), 1)
        self.assertTrue(d.isVisible())

    @unittest.skipUnless(FIXTURE.is_file(), "Private reference SPL unavailable")
    def test_discovery_worker_returns_real_spl_rows_and_refreshes(self):
        d = self.dialog
        with tempfile.TemporaryDirectory() as folder:
            d.folder.setText(folder)
            d.spl.setText(str(FIXTURE))
            d.refresh()
            for _ in range(400):
                if not d.worker:
                    break
                QTest.qWait(25)
            self.assertIsNone(d.worker)
            self.assertEqual(len(d.entries), 74)
            self.assertIn("Sample-list view", d.context.text())
            self.assertIn("omitted: 70", d.context.text())
            self.assertTrue(d.table.verticalHeader().isHidden())
            first = d.entries[0]
            (Path(folder) / (first.name + ".raw")).mkdir()
            d.refresh()
            for _ in range(400):
                if not d.worker:
                    break
                QTest.qWait(25)
            self.assertTrue(next(e for e in d.entries if e.key == first.key).available)

    def test_cancel_discovery_stops_process_and_ignores_old_result(self):
        d = self.dialog
        with tempfile.TemporaryDirectory() as folder:
            d.folder.setText(folder)
            d.refresh()
            token, process, directory, _ = d.worker
            d.cancel_discovery()
            self.assertIsNone(d.worker)
            self.assertEqual(process.state(), QProcess.ProcessState.NotRunning)
            self.assertFalse(Path(directory.name).exists())
            d.finish_discovery(token)
            self.assertFalse(d.entries)

    def test_queue_bounded_cancelled_entry_not_started_provenance_and_dedup(self):
        w = self.window
        original = w.active_key
        w.active.state.add_label(w.active.trace, 5, "Keep me")
        metadata = {"list": {"spl_path": "real-list.SPL"}, "row": {"index": 1, "vial": "3", "sample_type": "Unknown", "description": "Listed sample"}}
        entries = [LibraryEntry(str(i), f"Sample {i}", f"/sample{i}.raw", "ms", "Found", True, list_metadata=metadata) for i in range(3)]
        launched = []
        def fake_launch(key, request):
            launched.append(key)
            directory = tempfile.TemporaryDirectory()
            write_result(directory.name, [replace(demo_trace(), source=request.path, name=Path(request.path).name)])
            w.jobs[key] = (QProcess(w), directory)
        with patch.object(w, "launch_request", side_effect=fake_launch):
            keys = w.open_library_entries(entries)
            self.assertEqual(len(launched), 1)
            self.assertEqual(len(w.pending), 2)
            self.assertEqual(w.open_library_entries(entries), keys)
            w.sample_list.clearSelection()
            w.sample_list.setCurrentItem(w.find_item(keys[1]))
            self.assertEqual([item.data(Qt.ItemDataRole.UserRole) for item in w.sample_list.selectedItems()], [keys[1]])
            w.remove_sample()
            w.sample_list.setCurrentItem(w.find_item(original))
            w.finish_load(keys[0])
            self.app.processEvents()
            self.assertEqual(launched, [keys[0], keys[2]])
            self.assertEqual(w.samples[keys[0]].trace.metadata["sample_list"], metadata)
            with tempfile.TemporaryDirectory() as output:
                sample = w.samples[keys[0]]
                _, sidecar = export_figure(sample.trace, sample.state, Path(output) / "report.svg")
                payload = json.loads(sidecar.read_text(encoding="utf-8"))
                self.assertEqual(payload["source_metadata"]["sample_list"]["row"]["vial"], "3")
            self.assertEqual(w.samples[original].state.labels[0].text, "Keep me")
            w.close()
            self.assertFalse(w.jobs)
            self.assertFalse(w.pending)
            self.app.processEvents()
            self.assertEqual(len(launched), 2)

    def test_failed_batch_row_can_retry_with_same_identity_and_provenance(self):
        w = self.window
        entry = LibraryEntry("retry", "Retry me", "/retry.raw", "ms", "Found", True,
                             list_metadata={"row": {"index": 1, "vial": "2", "sample_type": "Unknown", "description": "Retry"}})
        attempts = []
        def fake_launch(key, request):
            attempts.append(key)
            directory = tempfile.TemporaryDirectory()
            if len(attempts) == 1:
                (Path(directory.name) / "result.json").write_text(json.dumps({"error": "Source unavailable"}))
            else:
                write_result(directory.name, [replace(demo_trace(), source=request.path)])
            w.jobs[key] = (QProcess(w), directory)
        with patch.object(w, "launch_request", side_effect=fake_launch):
            key = w.open_library_entries([entry])[0]
            w.finish_load(key)
            self.assertIn("could not be opened", w.active_title.text())
            self.assertIn("Source unavailable", w.notice.text())
            w.retry_selected()
            self.assertEqual(attempts, [key, key])
            w.finish_load(key)
            self.assertNotIn(key, w.failures)
            self.assertEqual(w.samples[key].trace.metadata["sample_list"], entry.list_metadata)


if __name__ == "__main__":
    unittest.main()
