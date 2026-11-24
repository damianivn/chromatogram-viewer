"""Native sample library with cancellable discovery and stable row identities."""
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import Qt, QProcess, QSettings, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QTableWidgetItem, QVBoxLayout,
)

from gcviewer.services.library import read_library
from gcviewer.desktop.tables import FlatTableWidget


class LibraryDialog(QDialog):
    open_requested = Signal(object)

    def __init__(self, parent=None, *, preferences=None):
        super().__init__(parent)
        self.preferences = preferences if preferences is not None else QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, "gcviewer", "ChromatogramViewer")
        self.preferences.setFallbacksEnabled(False)
        self.setWindowTitle("Sample library · Chromatogram Viewer")
        self.resize(1050, 640)
        self.setMinimumSize(760, 480)
        self.entries = []
        self.snapshot = None
        self.worker = None
        self._generation = 0
        self._closing = False
        self._refresh_selection = set()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Find acquisitions or match a Perkin-Elmer GC-MS sample list."))
        row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItem("GC-MS · .raw directories", "ms")
        self.kind.addItem("GC-FID · PENX .raw files", "fid")
        row.addWidget(self.kind)
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("Folder containing acquisitions")
        self.folder.setText(self.preferences.value("library/data_folder", "", type=str))
        self.folder.setCursorPosition(0)
        row.addWidget(self.folder, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self.browse_folder)
        row.addWidget(browse)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Optional PE SPL"))
        self.spl = QLineEdit()
        self.spl.setPlaceholderText("Leave blank to list acquisitions in the folder")
        row.addWidget(self.spl, 1)
        self.spl_browse = QPushButton("Choose list…")
        self.spl_browse.clicked.connect(self.browse_spl)
        row.addWidget(self.spl_browse)
        clear_list = QPushButton("Clear list")
        clear_list.clicked.connect(self.spl.clear)
        row.addWidget(clear_list)
        self.refresh_button = QPushButton("Refresh library")
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)
        self.context = QLabel("Choose a folder, then refresh. Browsing does not load chromatogram signals.")
        self.context.setTextFormat(Qt.TextFormat.PlainText)
        self.context.setWordWrap(True)
        layout.addWidget(self.context)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search sample name, description, vial, type, method or status")
        self.search.textChanged.connect(self.filter_rows)
        layout.addWidget(self.search)
        self.table = FlatTableWidget(0, 7, row_hover=True)
        self.table.setHorizontalHeaderLabels(["Sample", "Description", "Vial", "Type", "Method", "Status", "List row"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeaderItem(2).setToolTip("Vial position recorded by the instrument; independent of list order.")
        self.table.horizontalHeaderItem(6).setToolTip("Original record position in the sample list, preserved when blank or unreadable records are omitted.")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 190)
        self.table.setColumnWidth(1, 205)
        self.table.setColumnWidth(2, 60)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 155)
        self.table.itemSelectionChanged.connect(self.update_selection)
        self.table.model().layoutChanged.connect(self.filter_rows)
        layout.addWidget(self.table, 1)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        row = QHBoxLayout()
        select = QPushButton("Select all available")
        select.clicked.connect(self.select_available)
        row.addWidget(select)
        clear = QPushButton("Clear selection")
        clear.clicked.connect(self.table.clearSelection)
        row.addWidget(clear)
        self.cancel_button = QPushButton("Cancel discovery")
        self.cancel_button.clicked.connect(self.cancel_discovery)
        self.cancel_button.setEnabled(False)
        row.addWidget(self.cancel_button)
        row.addStretch()
        self.open_button = QPushButton("Open selected (0)")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_selected)
        row.addWidget(self.open_button)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        layout.addLayout(row)
        self.kind.currentIndexChanged.connect(self.inputs_changed)
        self.folder.textChanged.connect(self.inputs_changed)
        self.spl.textChanged.connect(self.inputs_changed)
        self.folder.editingFinished.connect(self.remember_folders)
        self.spl.editingFinished.connect(self.remember_folders)

    def remember_folders(self):
        """Save accepted locations; blank/invalid edits never erase good choices."""
        folder, spl = self.folder.text().strip(), self.spl.text().strip()
        if folder:
            path = Path(folder).expanduser()
            if path.is_dir() and path.suffix.casefold() != ".raw":
                self.preferences.setValue("library/data_folder", str(path.resolve()))
        if spl:
            path = Path(spl).expanduser()
            if path.is_file() and path.suffix.casefold() == ".spl":
                self.preferences.setValue("library/spl_folder", str(path.resolve().parent))
        self.preferences.sync()

    @staticmethod
    def browse_start(*locations):
        for location in locations:
            if location and Path(location).expanduser().is_dir():
                return str(Path(location).expanduser())
        return str(Path.home())

    def input_identity(self):
        return (self.kind.currentData(), self.folder.text().strip(), self.spl.text().strip())

    def inputs_changed(self, *args):
        if self.worker:
            self.cancel_discovery()
        is_ms = self.kind.currentData() == "ms"
        self.spl.setEnabled(is_ms)
        self.spl_browse.setEnabled(is_ms)
        if not is_ms and self.spl.text():
            self.spl.clear()
        self.update_selection()
        if self.snapshot and self.input_identity() != self.snapshot:
            self.message.setText("Folder or list changed. Refresh before opening samples.")

    def browse_folder(self):
        start = self.browse_start(self.folder.text().strip(), self.preferences.value("library/data_folder", "", type=str))
        path = QFileDialog.getExistingDirectory(self, "Folder containing acquisitions", start)
        if path:
            self.folder.setText(path)
            self.remember_folders()
            self.refresh()

    def browse_spl(self):
        start = self.browse_start(self.preferences.value("library/spl_folder", "", type=str), self.folder.text().strip())
        path, _ = QFileDialog.getOpenFileName(self, "Perkin-Elmer Jet sample list", start, "PE sample lists (*.SPL *.spl)")
        if path:
            self.spl.setText(path)
            if not self.folder.text().strip():
                self.folder.setText(str(Path(path).parent))
            self.remember_folders()
            self.refresh()

    def refresh(self):
        self.cancel_discovery()
        self.remember_folders()
        identity = self.input_identity()
        if not identity[1]:
            self.message.setText("Choose the parent folder containing acquisitions first.")
            return
        self._refresh_selection = {entry.key for entry in self.selected_entries()}
        token = self._generation
        directory = tempfile.TemporaryDirectory(prefix="chromatogram-library-")
        process = QProcess(self)
        self.worker = (token, process, directory, identity)
        self.cancel_button.setEnabled(True)
        self.open_button.setEnabled(False)
        self.message.setText("Reading folder and sample-list metadata…")
        if getattr(sys, "frozen", False):
            program, args = sys.executable, ["--library-worker", *identity, directory.name]
        else:
            executable = Path(sys.executable).with_name("pythonw.exe") if sys.platform == "win32" else Path(sys.executable)
            program, args = str(executable), ["-m", "gcviewer.services.library", *identity, directory.name]
        process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        process.finished.connect(lambda *_: self.finish_discovery(token))
        process.errorOccurred.connect(lambda error: self.finish_discovery(token) if error == QProcess.ProcessError.FailedToStart else None)
        process.start(program, args)

    def finish_discovery(self, token):
        if self._closing or not self.worker or self.worker[0] != token:
            return
        _, process, directory, identity = self.worker
        self.worker = None
        try:
            result, entries = read_library(directory.name)
            if identity != self.input_identity():
                return
            self.set_entries(entries, identity, self._refresh_selection)
            if result["source_list"]:
                context = (f"{result['folder']}\nList: {result['source_list']}\n"
                           f"Sample-list view · {len(entries)} entries · {result.get('folder_acquisitions', '?')} .raw items in folder. "
                           "Clear list to browse all folder acquisitions; missing list entries remain visible.")
            else:
                context = f"{result['folder']}\nFolder contents · no sample list"
            warnings = result.get("list_warnings", [])
            self.context.setText(context + ("\n" + "\n".join(warnings) if warnings else ""))
        except Exception as exc:
            self.snapshot = None
            self.message.setText(f"Could not read library: {exc}")
        finally:
            directory.cleanup()
            process.deleteLater()
            self.cancel_button.setEnabled(False)
            self.update_selection()

    def set_entries(self, entries, identity=None, selected_keys=()):
        self.entries = list(entries)
        self.snapshot = identity or self.input_identity()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            for col, value in enumerate((entry.name, entry.description, entry.vial, entry.sample_type, entry.method, entry.status, entry.index)):
                item = QTableWidgetItem()
                item.setData(Qt.ItemDataRole.DisplayRole, value)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                match = entry.list_metadata.get("matching", {})
                item.setToolTip(f"{entry.path}\n{entry.status}\n{match.get('rule', '')}" +
                                ("\nCandidates: " + ", ".join(match["alias_candidates"]) if match.get("alias_candidates") else ""))
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.filter_rows()
        for row in range(self.table.rowCount()):
            if self.entry_at(row).key in selected_keys and not self.table.isRowHidden(row):
                self.select_row(row)
        found = sum(e.available for e in entries)
        self.message.setText(f"{len(entries)} samples · {found} available · {len(entries) - found} missing/unsupported. Select rows to open.")
        self.update_selection()

    def entry_at(self, row):
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def filter_rows(self, *args):
        needle = self.search.text().casefold().strip()
        for row in range(self.table.rowCount()):
            entry = self.entry_at(row)
            if entry is None:
                continue
            text = " ".join(str(value) for value in (entry.name, entry.description, entry.vial, entry.sample_type, entry.method, entry.status)).casefold()
            hidden = bool(needle and needle not in text)
            self.table.setRowHidden(row, hidden)
            if hidden:
                for col in range(self.table.columnCount()):
                    self.table.item(row, col).setSelected(False)
        self.update_selection()

    def selected_entries(self):
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [entry for row in rows if not self.table.isRowHidden(row)
                and (entry := self.entry_at(row)) is not None and entry.available]

    def update_selection(self):
        if not hasattr(self, "open_button"):
            return
        count = len(self.selected_entries())
        self.open_button.setText(f"Open selected ({count})")
        self.open_button.setEnabled(bool(count) and not self.worker and self.snapshot == self.input_identity())

    def select_row(self, row):
        for col in range(self.table.columnCount()):
            self.table.item(row, col).setSelected(True)

    def select_available(self):
        self.table.clearSelection()
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row) and self.entry_at(row).available:
                self.select_row(row)

    def open_selected(self):
        if not self.open_button.isEnabled():
            return
        entries = self.selected_entries()
        self.open_requested.emit(entries)
        self.accept()

    def cancel_discovery(self):
        self._generation += 1
        worker, self.worker = self.worker, None
        if worker:
            _, process, directory, _ = worker
            process.kill()
            process.waitForFinished(3000)
            directory.cleanup()
            process.deleteLater()
            self.message.setText("Discovery cancelled. Previous list retained; refresh to check for changes.")
        self.cancel_button.setEnabled(False)
        self.update_selection()

    def done(self, result):
        self.remember_folders()
        self.cancel_discovery()
        super().done(result)

    def shutdown(self):
        self._closing = True
        self.cancel_discovery()
        self.close()
