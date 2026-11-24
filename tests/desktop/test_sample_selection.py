"""Sidebar selection/order and selected-FID result ownership/cancellation."""
import os
import json
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QModelIndex, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gcviewer.services.acquisition import fid_trace
from gcviewer.desktop.fid_batch import BatchReportDialog
from gcviewer.desktop.fid_selection import SelectedIntegrationDialog
from tests.desktop.test_fid_analysis import fixture
from gcviewer.desktop.window import Workspace
from gcviewer.services.fid_workflow import AnalysisDocument, AnalysisMethod, calculate


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window = Workspace()
        self.keys = [self.window.add_sample(fid_trace(run), fid_run=run) for run in
                     [fixture(self.root, name=f'run{i}.raw') for i in range(3)]]
        self.samples = [self.window.samples[key] for key in self.keys]
        self.dialog = None
        self.window.show()
        QTest.qWait(50)

    def tearDown(self):
        if self.dialog:
            self.dialog.reject()
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def wait(self):
        for _ in range(800):
            if not self.dialog.running:
                return
            QTest.qWait(25)
        self.fail('Selected integration did not finish')

    def test_marquee_defers_sample_binding_until_release(self):
        view = self.window.sample_list
        start = QPoint(10, view.viewport().height() - 10)
        end = view.visualItemRect(view.item(0)).center()
        with patch.object(self.window.fid_analysis, 'bind', wraps=self.window.fid_analysis.bind) as bind:
            QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
            self.assertTrue(view.selection_interaction)
            for row in (2, 1, 0):
                QTest.mouseMove(view.viewport(), view.visualItemRect(view.item(row)).center())
                view.setCurrentRow(row, view.selectionModel().SelectionFlag.Select)
            self.assertEqual(bind.call_count, 0)
            QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
            self.assertFalse(view.selection_interaction)
            self.assertEqual(bind.call_count, 1)
            self.assertEqual(len(view.selectedItems()), 3)
            self.assertIn('3', self.window.remove_button.text())

    def test_shift_ctrl_and_move_preserve_identity_and_batch_selection(self):
        view = self.window.sample_list
        def click(row, modifiers=Qt.KeyboardModifier.NoModifier):
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, modifiers,
                             view.visualItemRect(view.item(row)).center())
        click(0)
        click(2, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(len(view.selectedItems()), 3)
        click(1, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.window.ordered_fid_samples(selected=True), [self.samples[0], self.samples[2]])
        self.assertTrue(view.model().moveRows(QModelIndex(), 2, 1, QModelIndex(), 0))
        self.assertEqual(self.window.ordered_fid_samples(), [self.samples[2], self.samples[0], self.samples[1]])
        self.assertEqual(self.window.ordered_fid_samples(selected=True), [self.samples[2], self.samples[0]])
        self.assertTrue(view.showDropIndicator())
        self.assertFalse(view.item(0).flags() & Qt.ItemFlag.ItemIsDropEnabled)
        panel = self.window.fid_analysis
        dialog = BatchReportDialog(panel.runs(), AnalysisMethod(), AnalysisDocument().layout,
                                   selected_paths=[r.path for r in panel.selected_runs()])
        self.assertEqual([r.path.name for r in dialog.runs], ['run2.raw', 'run0.raw', 'run1.raw'])
        self.assertEqual([c.isChecked() for c in dialog.checks], [True, True, False])
        dialog.reject()
        self.window.sample_search.setText('run0')
        self.assertEqual(self.window.ordered_fid_samples(selected=True), [self.samples[0]])

    def test_selected_results_match_individual_keep_layout_and_unselected(self):
        method = AnalysisMethod(solvent_mode='manual', delay_min=2.)
        before = [calculate(s.fid_run, method) for s in self.samples[:2]]
        self.samples[0].fid_document = AnalysisDocument()
        layout = self.samples[0].fid_document.layout
        self.dialog = SelectedIntegrationDialog(self.samples[:2], method, 'run0.raw')
        self.dialog.start()
        self.wait()
        for sample, expected in zip(self.samples, before):
            self.assertEqual(sample.fid_document.result, json.loads(json.dumps(expected)))
            self.assertEqual(sample.fid_document.method, method)
        self.assertIs(self.samples[0].fid_document.layout, layout)
        self.assertIsNone(self.samples[2].fid_document.result)

    def test_corrupt_source_and_cancel_preserve_existing_results(self):
        prior = self.samples[1].fid_document = AnalysisDocument()
        prior.result = calculate(self.samples[1].fid_run, prior.method)
        result = prior.result
        self.samples[1].fid_run.path.write_bytes(b'changed')
        self.dialog = SelectedIntegrationDialog(self.samples[:2], AnalysisMethod(), 'run0.raw')
        self.dialog.start()
        self.wait()
        self.assertIsNotNone(self.samples[0].fid_document.result)
        self.assertTrue(self.dialog.table.item(1, 1).text().startswith('Failed:'))
        self.assertIs(prior.result, result)
        self.dialog.reject()
        self.dialog = SelectedIntegrationDialog(self.samples, AnalysisMethod(), 'run0.raw')
        first_result = self.samples[0].fid_document.result
        self.dialog.start()
        self.dialog.reject()
        self.assertIs(self.samples[0].fid_document.result, first_result)
        self.assertIsNone(self.samples[2].fid_document.result)
        self.assertIsNone(self.dialog.worker.process)


if __name__ == '__main__':
    unittest.main()
