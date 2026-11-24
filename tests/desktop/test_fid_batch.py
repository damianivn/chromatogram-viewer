"""Batch parity, failure accounting, fixed settings and publication/cancel."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader
from gcviewer.desktop.fid_batch import BatchReportDialog
from tests.desktop.test_fid_analysis import fixture
from gcviewer.services.fid_workflow import AnalysisMethod, calculate
from gcviewer.services.fid_batch import execute_batch, write_batch_request
from gcviewer.reports.publication import fingerprint
from gcviewer.reports.fid_pdf import ReportOptions


class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runs = [fixture(self.root, name=f'run{i}.raw') for i in range(2)]
        self.method = AnalysisMethod(solvent_mode='manual', delay_min=2.)
        self.layout = ReportOptions()
        self.dialog = None

    def tearDown(self):
        if self.dialog:
            self.dialog.cleanup()
            self.dialog.close()
        self.app.processEvents()
        self.temp.cleanup()

    def request(self):
        return write_batch_request(self.root, [(r.path, r.sha256) for r in self.runs], self.method, self.layout)

    def wait(self):
        for _ in range(1600):
            if self.dialog.job is None: return
            QTest.qWait(25)
        self.fail('Batch worker timeout')

    def make_dialog(self):
        self.dialog = BatchReportDialog(self.runs, self.method, self.layout, [r.path for r in self.runs])
        return self.dialog

    def test_combined_report_matches_individual_runs_and_carries_delays(self):
        key = self.request()
        result = execute_batch(self.root)
        self.assertTrue(result['success'])
        self.assertEqual(result['request_key'], key)
        self.assertEqual(len(result['rows']), 2)
        meta = json.loads((self.root/'output.json').read_text())
        for run, record in zip(self.runs, meta['samples']):
            expected = json.loads(json.dumps(calculate(run, self.method)))
            self.assertEqual(record['analysis'], expected)
        self.assertEqual(meta['output_sha256'], fingerprint(self.root/'output.pdf'))
        pages = PdfReader(self.root/'output.pdf').pages
        self.assertEqual(len(pages), 3)
        self.assertIn('Summary', pages[0].extract_text())
        for page in pages[1:]:
            self.assertIn('Solvent excluded before 2 min', page.extract_text())

    def test_changed_corrupt_inputs_accounted_without_pdf(self):
        self.request()
        self.runs[0].path.write_bytes(b'corrupt')
        self.runs[1].path.write_bytes(self.runs[1].path.read_bytes()+b'changed')
        result = execute_batch(self.root)
        self.assertFalse(result['success'])
        self.assertEqual(len(result['rows']), 2)
        self.assertTrue(all(row['status'] == 'Failed' for row in result['rows']))
        self.assertFalse((self.root/'output.pdf').exists())

    def test_source_changed_during_render_discards_pdf(self):
        from gcviewer.reports.fid_pdf import write_report
        self.request()
        def changed(*args):
            info = write_report(*args)
            self.runs[0].path.write_bytes(b'changed')
            return info
        with patch('gcviewer.reports.fid_pdf.write_report', side_effect=changed):
            result = execute_batch(self.root)
        self.assertFalse(result['success'])
        self.assertEqual(result['rows'][0]['status'], 'Failed')
        self.assertFalse((self.root/'output.pdf').exists())

    def test_worker_uses_frozen_settings_and_saves_complete_pair(self):
        dialog = self.make_dialog()
        target = self.root/'batch.pdf'
        dialog.start(target, (None, None))
        dialog.method = AnalysisMethod()
        self.wait()
        self.assertTrue(target.exists(), dialog.status.text())
        meta = json.loads(target.with_suffix('.pdf.json').read_text())
        self.assertEqual(meta['method'], self.method.to_dict())
        self.assertEqual(meta['selected_count'], 2)
        self.assertEqual(dialog.table.item(0, 3).text(), 'Saved')

    def test_cancel_and_failure_preserve_existing_report(self):
        dialog = self.make_dialog()
        target = self.root/'batch.pdf'
        target.write_bytes(b'existing')
        sidecar = target.with_suffix('.pdf.json')
        sidecar.write_bytes(b'existing metadata')
        before = fingerprint(target), fingerprint(sidecar)
        dialog.start(target, before)
        dialog.reject()
        self.assertIsNone(dialog.job)
        self.assertIsNone(dialog.worker.process)
        self.assertEqual((fingerprint(target), fingerprint(sidecar)), before)
        self.runs[0].path.write_bytes(b'corrupt')
        dialog.start(target, before)
        self.wait()
        self.assertIn('1 failed', dialog.status.text())
        self.assertEqual((fingerprint(target), fingerprint(sidecar)), before)

    def test_duplicate_and_empty_selection_rejected(self):
        with self.assertRaises(ValueError): write_batch_request(self.root, [], self.method, self.layout)
        source = self.runs[0].path, self.runs[0].sha256
        with self.assertRaises(ValueError): write_batch_request(self.root, [source, source], self.method, self.layout)
        dialog = self.make_dialog()
        dialog.select_all(False)
        dialog.start(self.root/'empty.pdf', (None, None))
        self.assertIsNone(dialog.job)
        self.assertIn('Select at least', dialog.status.text())
