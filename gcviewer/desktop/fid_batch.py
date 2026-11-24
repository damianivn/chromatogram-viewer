"""Selected opened FID acquisitions -> one protected combined PDF."""
import json
from pathlib import Path
import tempfile

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from gcviewer.desktop.loading import LoadService
from gcviewer.desktop.tables import FlatTableWidget
from gcviewer.services.fid_workflow import read_preset
from gcviewer.services.fid_batch import write_batch_request
from gcviewer.reports.publication import fingerprint, output_paths, publish


class BatchReportDialog(QDialog):
    def __init__(self, runs, method, layout, sources=(), parent=None, selected_paths=None):
        super().__init__(parent)
        self.setWindowTitle('Batch FID report')
        self.resize(790, 490)
        self.runs = list({str(run.path.resolve()).casefold(): run for run in runs}.values())
        selected = None if selected_paths is None else {str(Path(p).resolve()).casefold() for p in selected_paths}
        self.method, self.report_layout, self.sources = method, layout, sources
        self.job = None
        self.worker = LoadService(self)
        self.worker.completed.connect(self.worker_completed)
        self.worker.failed.connect(lambda key, detail: self.fail(detail))
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.progress)
        root = QVBoxLayout(self)
        hint = QLabel('Choose opened FID samples. One PDF contains a summary and per-sample pages.\nThe chosen method, naming rules and report layout apply to every selected sample.\nAny failure or cancellation prevents saving the report; existing reports stay intact.')
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.settings_label = QLabel()
        self.settings_label.setWordWrap(True)
        self.settings_label.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.settings_label)
        actions = QHBoxLayout()
        self.settings_buttons = []
        for kind in ('method', 'layout'):
            button = QPushButton(f'Load {kind}…')
            button.setToolTip('Load saved integration settings and peak-naming rules.' if kind == 'method'
                              else 'Load saved PDF formatting and visible fields; peak calculations are unchanged.')
            button.clicked.connect(lambda _=False, kind=kind: self.load_preset(kind))
            actions.addWidget(button)
            self.settings_buttons.append(button)
        for label, checked in (('Select all', True), ('Clear selection', False)):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, checked=checked: self.select_all(checked))
            actions.addWidget(button)
            self.settings_buttons.append(button)
        actions.addStretch()
        root.addLayout(actions)
        self.table = FlatTableWidget(len(self.runs), 4, row_hover=True)
        self.table.setHorizontalHeaderLabels(['Use', 'Sample', 'Vial', 'Status'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(24)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for column, width in ((0, 40), (2, 50)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, width)
        self.checks = []
        for row, run in enumerate(self.runs):
            check = QCheckBox()
            check.setChecked(selected is None or str(run.path.resolve()).casefold() in selected)
            check.setAccessibleName(f'Include {run.path.name}')
            self.checks.append(check)
            for column, text in enumerate(('', run.path.name, str(run.header.vial), 'Not started')):
                item = QTableWidgetItem(text)
                item.setToolTip(str(run.path) if column == 1 else text)
                self.table.setItem(row, column, item)
            self.table.setCellWidget(row, 0, check)
        root.addWidget(self.table)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.hide()
        root.addWidget(self.bar)
        actions = QHBoxLayout()
        self.start_button = QPushButton('Create batch PDF…')
        self.start_button.clicked.connect(self.choose_output)
        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.start_button)
        actions.addStretch()
        actions.addWidget(self.close_button)
        root.addLayout(actions)
        self.describe_settings('Current sample method and layout')

    def describe_settings(self, label):
        m = self.method
        solvent = f'exclude before {m.delay_min:g} min' if m.solvent_mode == 'manual' else m.solvent_mode
        self.settings_label.setText(f'{label}\nNoise {m.params.noise_threshold_uv:g} µV; AT {m.params.area_threshold_uv:g} µV; bunch {m.params.bunching_factor}; solvent {solvent}; {len(m.params.events)} events; {len(m.components)} names; {self.report_layout.page_size.upper()}')

    def load_preset(self, kind):
        path, _ = QFileDialog.getOpenFileName(self, f'Load {kind}', '', 'JSON (*.json)')
        if not path:
            return
        try:
            value = read_preset(path, kind)
            if kind == 'method': self.method = value
            else: self.report_layout = value
            self.describe_settings(f'Loaded {kind}: {Path(path).name}')
        except Exception as exc:
            self.status.setText(str(exc))

    def select_all(self, checked):
        for check in self.checks:
            check.setChecked(checked)

    def choose_output(self):
        if not any(check.isChecked() for check in self.checks):
            self.status.setText('Select at least one sample.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Save batch FID report', 'fid-batch.pdf', 'PDF (*.pdf)')
        if not path:
            return
        try:
            paths = output_paths(path, '.pdf', self.sources)
            expected = tuple(fingerprint(p) for p in paths)
            if any(value is not None for value in expected) and QMessageBox.question(self, 'Replace batch report?',
                    'Replace this PDF and its analysis metadata?', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            self.start(paths[0], expected)
        except Exception as exc:
            self.status.setText(str(exc))

    def start(self, target, expected):
        if self.job is not None:
            return
        chosen = [i for i, check in enumerate(self.checks) if check.isChecked()]
        if not chosen:
            self.status.setText('Select at least one sample.')
            return
        directory = tempfile.TemporaryDirectory(prefix='fid-batch-')
        try:
            paths = output_paths(target, '.pdf', self.sources)
            sources = [(self.runs[i].path, self.runs[i].sha256) for i in chosen]
            key = write_batch_request(directory.name, sources, self.method, self.report_layout)
            self.job = dict(directory=directory, paths=paths, expected=expected, key=key, chosen=chosen, sources=sources)
            for i in range(len(self.runs)):
                self.set_row(i, 'Queued' if i in chosen else 'Not selected')
            self.set_busy(True)
            self.status.setText(f'Preparing {len(chosen)} selected samples…')
            self.worker.start(key, 'fid-batch', directory.name, directory.name)
            self.timer.start()
        except Exception as exc:
            if self.job: self.fail(str(exc))
            else:
                directory.cleanup()
                self.status.setText(str(exc))

    def set_row(self, index, text):
        self.table.item(index, 3).setText(text)
        self.table.item(index, 3).setToolTip(text)

    def set_busy(self, busy):
        self.start_button.setEnabled(not busy)
        for widget in self.settings_buttons + self.checks:
            widget.setEnabled(not busy)
        self.close_button.setText('Cancel batch' if busy else 'Close')
        self.bar.setVisible(busy)
        self.bar.setRange(0, 0)

    def progress(self):
        if not self.job:
            return
        path = Path(self.job['directory'].name)/'progress.json'
        if path.exists():
            value = json.loads(path.read_text(encoding='utf-8'))
            self.status.setText(value['message'])
            self.show_rows(value['rows'])

    def show_rows(self, rows):
        for index, row in zip(self.job['chosen'], rows):
            self.set_row(index, row['status'] + ': ' + row['detail'])

    def worker_completed(self, key):
        job = self.job
        if not job or key != job['key']:
            return
        try:
            folder = Path(job['directory'].name)
            value = json.loads((folder/'result.json').read_text(encoding='utf-8'))
            if 'error' in value:
                raise ValueError(value['error'])
            result = value['batch']
            if result['request_key'] != key or len(result['rows']) != len(job['chosen']):
                raise ValueError('The batch result does not match the selected samples.')
            self.show_rows(result['rows'])
            if not result['success']:
                failed = sum(row['status'] == 'Failed' for row in result['rows'])
                self.status.setText(f"{len(result['rows'])} selected; {failed} failed. No report saved. Review the status column, correct or deselect failures, then retry.")
            else:
                for path, before in job['sources']:
                    if fingerprint(path) != before:
                        raise ValueError(f'{path.name} changed. No report saved; reopen it before retrying.')
                publish((folder/'output.pdf', folder/'output.json'), job['paths'], job['expected'])
                for index in job['chosen']: self.set_row(index, 'Saved')
                self.status.setText(f"Saved {len(job['chosen'])} samples, {result['pages']} pages, plus analysis metadata.\n{job['paths'][0]}")
        except Exception as exc:
            for index in job['chosen']: self.set_row(index, 'Not saved')
            self.status.setText(f'No report saved: {exc}')
        finally:
            self.cleanup()

    def fail(self, detail):
        self.status.setText(f'No report saved: {detail}')
        if self.job:
            for index in self.job['chosen']: self.set_row(index, 'Not saved')
        self.cleanup()

    def cleanup(self):
        self.timer.stop()
        self.worker.stop()
        job, self.job = self.job, None
        if job: job['directory'].cleanup()
        self.set_busy(False)

    def reject(self):
        if self.job:
            for index in self.job['chosen']: self.set_row(index, 'Cancelled — not saved')
            self.cleanup()
            self.status.setText('Cancelled. No report saved.')
            return
        self.cleanup()
        super().reject()
