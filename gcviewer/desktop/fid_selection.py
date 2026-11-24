"""Integrate an ordered selection with one method, keeping per-sample results."""
import json
from pathlib import Path
import tempfile
import uuid

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHeaderView, QLabel, QProgressBar, QPushButton, QTableWidgetItem, QVBoxLayout

from gcviewer.desktop.loading import LoadService
from gcviewer.desktop.tables import FlatTableWidget
from gcviewer.services.fid_workflow import AnalysisDocument, AnalysisMethod, analysis_key, check_source, write_request


class SelectedIntegrationDialog(QDialog):
    def __init__(self, samples, method, method_source, parent=None):
        super().__init__(parent)
        if not samples:
            raise ValueError('Select at least one opened FID sample.')
        self.samples = tuple(samples)
        self.method = AnalysisMethod.from_dict(method.to_dict())
        self.job = None
        self.running = False
        self.next_row = 0
        self.setWindowTitle('Integrate selected FID samples')
        self.resize(650, 400)
        root = QVBoxLayout(self)
        hint = QLabel(f'Use the method and naming rules from {method_source} for these {len(samples)} FID samples.\n'
                      'Successful integrations replace their previous results and method. Report layouts stay unchanged.\n'
                      'Failed or cancelled samples keep their previous results. No files are exported.')
        hint.setTextFormat(Qt.TextFormat.PlainText)
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.table = FlatTableWidget(len(samples), 2, row_hover=True)
        self.table.setHorizontalHeaderLabels(['Sample', 'Result'])
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(self.table.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for row, sample in enumerate(samples):
            self.table.setItem(row, 0, QTableWidgetItem(sample.fid_run.path.name))
            self.table.item(row, 0).setToolTip(str(sample.fid_run.path))
            self.table.setItem(row, 1, QTableWidgetItem('Waiting'))
        root.addWidget(self.table)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(samples))
        self.progress.setValue(0)
        root.addWidget(self.progress)
        self.start_button = QPushButton('Integrate selected')
        self.start_button.clicked.connect(self.start)
        root.addWidget(self.start_button)
        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.reject)
        root.addWidget(self.close_button)
        self.worker = LoadService(self)
        self.worker.completed.connect(self.completed)
        self.worker.failed.connect(self.failed)

    def set_status(self, row, text):
        self.table.item(row, 1).setText(text)
        self.table.item(row, 1).setToolTip(text)

    def start(self):
        if self.running or self.next_row:
            return
        self.running = True
        self.start_button.setEnabled(False)
        self.close_button.setText('Cancel remaining')
        self.advance()

    def advance(self):
        if not self.running:
            return
        if self.next_row == len(self.samples):
            self.running = False
            self.close_button.setText('Close')
            self.worker.stop()
            return
        row = self.next_row
        self.next_row += 1
        sample = self.samples[row]
        directory = None
        try:
            self.method.validate_run(sample.fid_run)
            check_source(sample.fid_run)
            document = sample.fid_document or AnalysisDocument()
            directory = tempfile.TemporaryDirectory(prefix='fid-selected-')
            write_request(directory.name, sample.fid_run, self.method, document.layout, 'integrate')
            key = uuid.uuid4().hex
            self.job = (key, row, directory)
            self.set_status(row, 'Integrating…')
            self.worker.start(key, 'fid-analysis', directory.name, directory.name)
        except Exception as exc:
            self.worker.stop()
            self.job = None
            if directory is not None:
                directory.cleanup()
            self.set_status(row, f'Failed: {exc}')
            self.progress.setValue(row + 1)
            QTimer.singleShot(0, self.advance)

    def completed(self, key):
        if self.job is None or self.job[0] != key:
            return
        _, row, directory = self.job
        sample = self.samples[row]
        try:
            value = json.loads((Path(directory.name) / 'result.json').read_text(encoding='utf-8'))
            if 'error' in value:
                raise ValueError(value['error'])
            result = value['analysis']
            if result['analysis_key'] != analysis_key(sample.fid_run, self.method):
                raise ValueError('Result does not match the acquisition and method.')
            check_source(sample.fid_run)
            document = sample.fid_document or AnalysisDocument()
            document.method, document.result, document.draft = self.method, result, None
            sample.fid_document = document
            self.set_status(row, f"Integrated · {len(result['peaks'])} peaks")
        except Exception as exc:
            self.set_status(row, f'Failed: {exc}')
        finally:
            self.job = None
            directory.cleanup()
            self.progress.setValue(row + 1)
            QTimer.singleShot(0, self.advance)

    def failed(self, key, detail):
        if self.job is not None and self.job[0] == key:
            _, row, directory = self.job
            self.job = None
            directory.cleanup()
            self.set_status(row, f'Failed: {detail}')
            self.progress.setValue(row + 1)
            QTimer.singleShot(0, self.advance)

    def reject(self):
        self.running = False
        self.worker.stop()
        if self.job is not None:
            _, row, directory = self.job
            self.job = None
            directory.cleanup()
            self.set_status(row, 'Cancelled')
        for row in range(self.next_row, len(self.samples)):
            self.set_status(row, 'Not integrated')
        super().reject()
