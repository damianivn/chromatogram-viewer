"""Layout/theme preference changes must preserve live scientific and edit state."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from dataclasses import asdict
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolBar
from gcviewer.services.acquisition import fid_trace
from tests.desktop.test_fid_analysis import fixture
from gcviewer.desktop.window import Workspace
from gcviewer.figures.comparisons import Comparison
from gcviewer.services.fid_workflow import calculate
from gcviewer.figures.workspace import demo_trace


class WorkspaceLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name)/'prefs.ini')
        self.w = Workspace(QSettings(self.path, QSettings.Format.IniFormat))
        self.w.show()
        QTest.qWait(80)

    def tearDown(self):
        self.w.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_fid_action_can_close_view_without_losing_results(self):
        run = fixture(self.temp.name)
        self.w.add_sample(fid_trace(run), fid_run=run)
        p = self.w.fid_analysis
        p.document.result = calculate(run, p.document.method)
        record = p.document.result
        action = self.w.layout_controller.view_actions[1]
        action.trigger()
        self.assertEqual(self.w.workspace_tabs.currentIndex(), 1)
        action.trigger()
        self.assertEqual(self.w.workspace_tabs.currentIndex(), 0)
        self.assertFalse(action.isChecked())
        self.assertTrue(self.w.layout_controller.view_actions[0].isChecked())
        self.assertIs(p.document.result, record)

    def test_mode_and_appearance_changes_keep_drafts_labels_results(self):
        run = fixture(self.temp.name)
        key = self.w.add_sample(fid_trace(run), fid_run=run)
        sample = self.w.active
        p = self.w.fid_analysis
        sample.fid_document.result = calculate(run, sample.fid_document.method)
        sample.state.add_label(sample.trace, 4., 'Keep me', (.2,.8))
        self.w.fields['title'].setText('Unapplied title')
        p.noise.setText('75')
        draft = p.capture()
        state = asdict(sample.state)
        document = sample.fid_document
        p.noise.setText('50')
        record = calculate(run, p.method_value())
        document.result = record
        for mode in ('dark', 'light', 'system'):
            self.w.layout_controller.set_appearance(mode)
            self.w.layout_controller.view_actions[1].trigger()
            QTest.qWait(20)
            self.assertEqual(self.w.active_key, key)
            self.assertIs(sample.fid_document, document)
            self.assertIs(document.result, record)
            self.assertEqual(asdict(sample.state), state)
            self.assertEqual(self.w.fields['title'].text(), 'Unapplied title')
            self.assertEqual(p.forms.count(), 3)
            self.assertEqual(p.forms.tabText(2), 'Advanced')
            self.assertEqual(self.w.splitter.count(), 3)
        p.noise.setText(draft['noise'])
        self.assertEqual(p.capture(), draft)

    def test_saved_preferences_themes_and_panel_visibility(self):
        c = self.w.layout_controller
        for mode, color in (('dark','#2d2d2d'), ('light','#ffffff')):
            c.set_appearance(mode)
            self.app.processEvents()
            self.assertEqual(self.app.palette().color(QPalette.ColorRole.Base).name(), color)
            self.assertEqual(self.w.sample_search.palette().color(QPalette.ColorRole.Base).name(), color)
            self.assertEqual(self.w.sample_list.palette().color(QPalette.ColorRole.Base).name(), color)
        c.browser_action.setChecked(False)
        c.inspector_action.setChecked(False)
        self.assertTrue(self.w.sample_panel.isHidden())
        self.assertTrue(c.inspector.isHidden())
        c.reset()
        self.assertFalse(self.w.sample_panel.isHidden())
        self.assertFalse(c.inspector.isHidden())
        self.w.close()
        self.w = Workspace(QSettings(self.path, QSettings.Format.IniFormat))
        self.w.show()
        self.assertEqual(self.w.layout_controller.appearance, 'light')
        self.assertEqual(self.w.splitter.count(), 3)
        self.w.layout_controller.set_appearance('system')
        self.assertEqual(self.w.layout_controller.appearance, 'system')

    def test_narrow_inspector_pages_and_advanced_controls(self):
        self.w.add_sample(demo_trace())
        c = self.w.layout_controller
        self.w.resize(920, 600)
        for page in ('Style', 'Axes', 'Labels'):
            c.show_figure_page(page)
            QTest.qWait(50)
            self.assertEqual(self.w.width(), 920)
            self.assertFalse(self.w.viewport.horizontalScrollBar().isVisible())
        c.show_figure_page('Style')
        c.advanced.setChecked(True)
        self.assertTrue(self.w.font_family.isEnabled())

    def test_comparison_context_and_busy_integration_survive_mode_change(self):
        run = fixture(self.temp.name)
        self.w.add_sample(fid_trace(run), fid_run=run)
        p = self.w.fid_analysis
        p.integrate_action.trigger()
        self.assertIsNotNone(p.busy)
        self.w.workspace_tabs.setCurrentIndex(1)
        for _ in range(400):
            if p.busy is None: break
            QTest.qWait(25)
        self.assertIsNotNone(p.document.result, p.status.text())
        self.w.add_sample(Comparison((demo_trace(), demo_trace())))
        self.w.layout_controller.sync()
        self.assertTrue(self.w.layout_controller.view_actions[0].isChecked())
        self.assertIn('Comparison', self.w.active_title.text())
        self.assertTrue(self.w.layout_controller.tabs.isTabVisible(3))
        self.assertFalse(self.w.layout_controller.view_actions[1].isEnabled())

    def test_menu_view_shortcuts_and_unavailable_analysis(self):
        c = self.w.layout_controller
        self.assertFalse(c.view_actions[1].isEnabled())
        self.assertTrue(c.view_actions[0].isChecked())
        self.assertFalse(self.w.findChildren(QToolBar, options=Qt.FindChildOption.FindDirectChildrenOnly))
        run = fixture(self.temp.name)
        self.w.add_sample(fid_trace(run), fid_run=run)
        self.w.activateWindow()
        self.w.setFocus()
        QTest.qWait(30)
        self.assertTrue(c.view_actions[1].isEnabled())
        QTest.keyClick(self.w, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        QTest.qWait(30)
        self.assertEqual(self.w.workspace_tabs.currentIndex(), 1)
        self.assertTrue(c.view_actions[1].isChecked())
        self.assertIn('FID Analysis', self.w.fid_analysis.title.text())
        QTest.keyClick(self.w, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        QTest.qWait(30)
        self.assertEqual(self.w.workspace_tabs.currentIndex(), 0)
        self.assertTrue(c.view_actions[0].isChecked())


if __name__ == '__main__':
    unittest.main()
