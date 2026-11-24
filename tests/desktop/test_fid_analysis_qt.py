"""FID analysis UI independence, drafts, worker cancellation and stale replies."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QTableWidgetItem, QToolButton
from gcviewer.services.acquisition import fid_trace
from gcviewer.desktop.fid_forms import DetectedPeakNamesDialog, ReportLayoutDialog, fill_table
from tests.desktop.test_fid_analysis import fixture
from gcviewer.desktop.window import Workspace
from gcviewer.services.fid_workflow import AnalysisMethod, calculate
from gcviewer.figures.workspace import demo_trace


class AnalysisQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.run=fixture(self.root)
        self.window=Workspace()
        self.key=self.window.add_sample(fid_trace(self.run),fid_run=self.run)
        self.window.show()
        self.window.workspace_tabs.setCurrentIndex(1)
        self.panel=self.window.fid_analysis
        QTest.qWait(50)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def wait(self):
        for _ in range(1200):
            if self.panel.busy is None: return
            QTest.qWait(25)
        self.fail("Analysis worker timed out")

    def ready(self):
        self.panel.start()
        self.wait()
        self.assertIsNotNone(self.panel.document.result,self.panel.status.text())

    def test_integration_keeps_time_range_and_home(self):
        p = self.panel
        overview = p.main_axis.get_xlim()
        chosen = (overview[0] + 0.1, overview[1] - 0.1)
        p.main_axis.set_xlim(chosen)
        self.ready()
        self.assertEqual(p.main_axis.get_xlim(), chosen)
        p.toolbar.home()
        self.assertEqual(p.main_axis.get_xlim(), overview)
        p.hide_solvent.setChecked(True)
        hidden = p.main_axis.get_xlim()
        p.show_result()
        self.assertEqual(p.main_axis.get_xlim(), hidden)

    def test_detected_names_append_once_keep_existing_and_cancel_unchanged(self):
        self.assertFalse(self.panel.detected_names_button.isEnabled())
        self.ready()
        peaks = self.panel.document.result['peaks']
        fill_table(self.panel.components, [['Existing', peaks[0]['rt_min'], .02]])
        method = self.panel.document.method
        def cancel():
            QApplication.activeModalWidget().reject()
        QTimer.singleShot(0, cancel)
        self.panel.detected_names_button.click()
        self.assertEqual(self.panel.document.method, method)
        def choose():
            dialog = QApplication.activeModalWidget()
            dialog.table.item(0, 1).setText('Second component')
            dialog.tolerance.setValue(.03)
            dialog.accept()
        QTimer.singleShot(0, choose)
        self.panel.detected_names_button.click()
        self.assertIs(self.panel.document.result['peaks'], peaks)
        self.assertEqual(self.panel.document.result['names'], {'1': 'Existing', '2': 'Second component'})
        self.assertEqual(self.panel.document.method.components[0], method.components[0])
        self.assertEqual(self.panel.document.method.components[1].rt_min, peaks[1]['rt_min'])
        self.assertEqual(self.panel.document.method.components[1].window_min, .03)
        self.assertFalse(self.panel.detected_names_button.isEnabled())
        self.assertTrue(self.panel.pdf_action.isEnabled())

    def test_detected_names_selection_clipping_and_duplicate_validation(self):
        from gcviewer.analysis.retention_names import Component
        self.ready()
        peaks = [dict(p) for p in self.panel.document.result['peaks']]
        peaks[0]['clipped'] = True
        dialog = DetectedPeakNamesDialog(peaks, (Component('Peak 2', 7),), self.panel)
        self.assertFalse(dialog.checks[0].isChecked())
        self.assertEqual(dialog.table.item(1, 1).text(), 'Peak 2 (2)')
        dialog.select_all(False); dialog.accept()
        self.assertIn('Select at least', dialog.error.text())
        dialog.checks[1].setChecked(True)
        dialog.table.item(1, 1).setText('peak 2'); dialog.accept()
        self.assertIn('different name', dialog.error.text())
        dialog.table.item(1, 1).setText('Later'); dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(len(dialog.components), 1)
        self.assertEqual(dialog.components[0].rt_min, peaks[1]['rt_min'])

    def test_real_worker_and_pdf_export_match_table_and_preserve_figure(self):
        state=self.window.active.state
        self.ready()
        self.assertEqual(len(self.panel.canvas.figure.axes),1)
        self.assertEqual(self.panel.table.rowCount(),2)
        before=self.panel.document.result["peaks"]
        self.window.active.state.settings=replace(state.settings,normalize=True,smoothing_window=7,x_break=(2,3))
        self.window.redraw()
        self.panel.hide_solvent.setChecked(False)
        self.assertEqual(self.panel.document.result["peaks"],before)
        target=self.root/"analysis.pdf"
        self.panel.start("pdf",target,(None,None));self.wait()
        self.assertTrue(target.is_file(),self.panel.status.text())
        meta=json.loads(target.with_suffix('.pdf.json').read_text(encoding='utf-8'))
        self.assertEqual(meta["analysis"]["peaks"],before)
        self.assertFalse(meta["figure_processing_applied"])
        self.panel.table.selectRow(1)
        lo,hi=self.panel.main_axis.get_xlim()
        self.assertLess(lo,before[1]['start_min'])
        self.assertGreater(hi,before[1]['end_min'])
        self.assertIs(self.window.active.state,state)

    def test_home_and_history_restore_overview_after_peak_and_manual_zoom(self):
        self.ready()
        axis = self.panel.main_axis
        overview = (axis.get_xlim(), axis.get_ylim())
        self.panel.table.selectRow(1)
        self.assertIs(self.panel.main_axis, axis)
        self.assertNotEqual(axis.get_xlim(), overview[0])
        self.panel.toolbar.home()
        self.assertEqual((axis.get_xlim(), axis.get_ylim()), overview)
        axis.set_xlim(1.5, 2)
        self.panel.toolbar.push_current()
        self.panel.toolbar.home()
        self.assertEqual((axis.get_xlim(), axis.get_ylim()), overview)
        self.panel.toolbar.back()
        self.assertEqual(axis.get_xlim(), (1.5, 2))

    def test_names_keep_peaks_and_worker_and_update_export_without_integration(self):
        self.ready()
        initial = self.panel.document.result
        process = self.panel.worker.process
        self.panel.components.insertRow(0)
        self.assertIs(self.panel.document.result, initial)
        self.assertTrue(self.panel.pdf_action.isEnabled())
        self.panel.components.setItem(0, 0, QTableWidgetItem('First'))
        self.assertIs(self.panel.document.result, initial)
        self.assertFalse(self.panel.pdf_action.isEnabled())
        for column, text in ((1, str(100/60)), (2, '.05')):
            self.panel.components.setItem(0, column, QTableWidgetItem(text))
        self.assertEqual(self.panel.document.result['names'], {'1': 'First'})
        self.assertIs(self.panel.document.result['peaks'], initial['peaks'])
        self.assertIs(self.panel.worker.process, process)
        self.assertTrue(self.panel.pdf_action.isEnabled())
        target = self.root / 'renamed.csv'
        self.panel.start('csv', target, (None, None)); self.wait()
        meta = json.loads(target.with_suffix('.csv.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['analysis']['names'], {'1': 'First'})
        self.assertEqual(meta['analysis']['peaks'], initial['peaks'])
        self.panel.components.removeRow(0)
        self.assertEqual(self.panel.document.result['names'], {})
        self.panel.noise.setText('49')
        self.assertIsNone(self.panel.document.result)
        self.assertIs(self.panel.worker.process, process)

    def test_names_while_integrating_keep_results_but_export_edits_cancel(self):
        self.panel.start()
        self.panel.components.insertRow(0)
        self.panel.components.setItem(0, 0, QTableWidgetItem('Pending name'))
        self.assertIsNotNone(self.panel.busy)
        self.wait()
        self.assertIsNotNone(self.panel.document.result)
        self.assertFalse(self.panel.pdf_action.isEnabled())
        for column, text in ((1, str(100/60)), (2, '.05')):
            self.panel.components.setItem(0, column, QTableWidgetItem(text))
        self.assertTrue(self.panel.pdf_action.isEnabled())
        self.assertEqual(self.panel.document.result['names'], {'1': 'Pending name'})
        target = self.root / 'stale-names.pdf'
        self.panel.start('pdf', target, (None, None))
        self.panel.components.item(0, 0).setText('Changed name')
        self.assertIsNone(self.panel.busy)
        self.assertFalse(target.exists())
        self.assertEqual(self.panel.document.result['names'], {'1': 'Changed name'})

    def test_tables_have_no_horizontal_offset_and_keep_last_column_accessible(self):
        self.ready()
        for size in ((1400, 880), (920, 680)):
            self.window.resize(*size)
            for index, table in ((0, self.panel.table), (1, self.panel.components), (2, self.panel.events)):
                self.panel.forms.setCurrentIndex(index)
                if index == 2:
                    self.panel.forms.widget(2).findChild(QToolButton).setChecked(True)
                if table.rowCount() == 0:
                    with QSignalBlocker(table):
                        table.insertRow(0)
                        for c in range(table.columnCount()):
                            table.setItem(0, c, QTableWidgetItem(''))
                self.app.processEvents()
                self.assertTrue(table.isVisible())
                visible = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
                table.setCurrentCell(0, visible[-1])
                self.app.processEvents()
                self.assertEqual(table.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                self.assertEqual(table.horizontalScrollBar().maximum(), 0,
                                 (size, index, table.horizontalHeader().length(), table.viewport().width(),
                                  [table.columnWidth(c) for c in visible]))
                rect = table.visualItemRect(table.item(0, visible[-1]))
                self.assertLessEqual(rect.right(), table.viewport().width(),
                                     (size, index, table.isVisible()))

    def test_per_sample_drafts_and_results_survive_switching(self):
        self.ready(); first=self.panel.document
        self.panel.noise.setText('bad value')
        self.assertIsNone(first.result)
        key2=self.window.add_sample(demo_trace())
        self.assertFalse(self.window.workspace_tabs.isTabEnabled(1))
        self.assertEqual(self.window.workspace_tabs.currentIndex(),0)
        self.window.sample_list.setCurrentItem(self.window.find_item(self.key))
        self.assertIs(self.panel.document,first)
        self.assertEqual(self.panel.noise.text(),'bad value')
        self.panel.start()
        self.assertIsNone(self.panel.busy)
        self.assertFalse(self.panel.pdf_action.isEnabled())
        self.panel.noise.setText('50');self.ready()

    def test_cancel_and_method_edit_during_export_publish_nothing(self):
        self.ready()
        target=self.root/'cancelled.pdf'
        self.panel.start('pdf',target,(None,None))
        self.assertIsNotNone(self.panel.busy)
        self.panel.cancel()
        self.assertFalse(target.exists())
        self.assertFalse(target.with_suffix('.pdf.json').exists())
        self.assertIsNone(self.panel.worker.process)
        self.panel.start('pdf',target,(None,None))
        self.panel.noise.setText('25')
        self.assertIsNone(self.panel.busy)
        self.assertIsNone(self.panel.document.result)
        QTest.qWait(80)
        self.assertFalse(target.exists())

    def test_stale_reply_and_changed_source_are_rejected(self):
        with patch.object(self.panel.worker,'start'):
            self.panel.start()
        job=self.panel.busy
        record=calculate(self.run,AnalysisMethod())
        (Path(job['directory'].name)/'result.json').write_text(json.dumps({'analysis':record}))
        with QSignalBlocker(self.panel.noise): self.panel.noise.setText('30')
        self.panel.finished(job['key'])
        self.assertIn('discarded',self.panel.status.text())
        self.assertIsNone(self.panel.document.result)
        self.run.path.write_bytes(self.run.path.read_bytes()+b'changed')
        self.panel.start()
        self.assertIsNone(self.panel.busy)
        self.assertIn('changed',self.panel.status.text())

    def test_layout_dialog_rejects_bad_range_then_accepts_details(self):
        dialog=ReportLayoutDialog(self.panel.document.layout,self.window)
        dialog.fields['main_start_min'].setText('nan')
        dialog.accept()
        self.assertEqual(dialog.result(),QDialog.DialogCode.Rejected)
        self.assertIn('finite',dialog.error.text())
        dialog.fields['main_start_min'].setText('')
        dialog.paper.setCurrentText('A4')
        dialog.fields['subtitle'].setText('Student lab')
        dialog.accept()
        self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.options.page_size,'a4')
        self.assertEqual(dialog.options.subtitle,'Student lab')

    def test_closing_or_switching_cancels_owned_analysis_process(self):
        self.panel.start()
        self.window.add_sample(demo_trace())
        self.assertIsNone(self.panel.busy)
        self.assertIsNone(self.panel.worker.process)
        self.window.sample_list.setCurrentItem(self.window.find_item(self.key))
        self.panel.start()
        self.window.close()
        self.assertIsNone(self.panel.busy)
        self.assertIsNone(self.panel.worker.process)
