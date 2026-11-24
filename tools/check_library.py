"""Read-only acquisition/library verification and offscreen screenshots.

Pass private data paths explicitly. Outputs belong in a local evidence folder;
they may contain source identities and plotted signals. No acquisitions copied.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "ChromatogramViewer-matplotlib"))

from PySide6.QtCore import Qt, QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gcviewer.services.acquisition import load_source
from gcviewer.services.library import discover_library
from gcviewer.desktop.library_dialog import LibraryDialog
from gcviewer.desktop.window import Workspace


def wait_until(predicate, seconds=60):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("Qt library/load check did not finish")
        QTest.qWait(25)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--spl", type=Path)
    parser.add_argument("--kind", choices=("ms", "fid"), default="ms")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--search", default="")
    parser.add_argument("--check-all", action="store_true")
    parser.add_argument("--load-count", type=int, default=3)
    args = parser.parse_args()
    output = args.output.resolve()
    source_folder = args.folder.resolve()
    if output == source_folder or source_folder in output.parents:
        raise ValueError("Keep evidence outside the acquisition folder")
    output.mkdir(parents=True, exist_ok=True)
    listing = discover_library(source_folder, args.kind, args.spl)
    paths = sorted({Path(e["path"]) for e in listing["entries"] if e["available"]})
    assert paths, "No available acquisitions"
    source_files = sorted({p for path in paths for p in (path.rglob("*") if path.is_dir() else [path]) if p.is_file()})
    def hashes():
        result = {}
        for path in source_files:
            with path.open("rb") as handle:
                result[str(path)] = hashlib.file_digest(handle, "sha256").hexdigest()
        return result
    before = hashes()
    results = {"list_rows": len(listing["entries"]), "available_rows": sum(e["available"] for e in listing["entries"]),
               "distinct_sources": len(paths), "matching_rules": dict(Counter(e["list_metadata"].get("matching", {}).get("rule", "Folder entry") for e in listing["entries"]))}
    if args.check_all:
        start = time.monotonic()
        points = Counter()
        functions = Counter()
        for path in paths:
            traces = load_source(path, args.kind)
            functions[len(traces)] += 1
            points.update(len(trace.time) for trace in traces)
        results.update(adapter_seconds=round(time.monotonic() - start, 3), point_counts=dict(points), functions_per_source=dict(functions), adapter_sources_checked=len(paths))
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    window = Workspace()
    window.library_dialog = LibraryDialog(window, preferences=QSettings(str(output / "library-preferences.ini"), QSettings.Format.IniFormat))
    window.library_dialog.open_requested.connect(window.open_library_entries)
    try:
        window.show()
        window.open_library()
        dialog = window.library_dialog
        dialog.kind.setCurrentIndex(dialog.kind.findData(args.kind))
        dialog.folder.setText(str(source_folder))
        dialog.folder.setCursorPosition(0)
        if args.spl:
            dialog.spl.setText(str(args.spl.resolve()))
            dialog.spl.setCursorPosition(0)
        dialog.refresh()
        wait_until(lambda: dialog.worker is None)
        assert len(dialog.entries) == len(listing["entries"]), dialog.message.text()
        dialog.table.sortItems(6, Qt.SortOrder.AscendingOrder)
        dialog.search.setText(args.search)
        available = [row for row in range(dialog.table.rowCount()) if not dialog.table.isRowHidden(row) and dialog.entry_at(row).available]
        assert available
        for row in available[:max(1, args.load_count)]:
            dialog.select_row(row)
        selected = dialog.selected_entries()
        dialog.table.scrollToItem(dialog.table.item(available[0], 0))
        QTest.qWait(150)
        assert dialog.grab().save(str(output / "sample-library.png"))
        dialog.open_selected()
        dialog.close()
        wait_until(lambda: not window.jobs and not window.pending)
        assert not window.failures, window.failures
        loaded = [sample for key, sample in window.samples.items() if key in window.requests]
        assert {sample.trace.source for sample in loaded} == {entry.path for entry in selected}
        for entry in selected:
            key = next(key for key, request in window.requests.items() if request.origin_key == entry.key)
            trace = window.samples[key].trace
            if entry.list_metadata:
                assert trace.metadata["sample_list"] == entry.list_metadata
        results["qt_worker_sources_checked"] = len(loaded)
        results["qt_source_identity_and_provenance"] = "passed"
        QTest.qWait(150)
        window.canvas.draw()
        assert window.grab().save(str(output / "loaded-workspace.png"))
    finally:
        window.close()
        app.processEvents()
    assert hashes() == before, "Acquisition source hashes changed"
    results["unchanged_source_files"] = len(before)
    results["scope"] = "Real acquisitions read in place; offscreen Qt workers and UI. No vendor-output, native/manual or clean-PC validation. Timings are one development-host pass, not a comparative benchmark."
    (output / "library-check.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
