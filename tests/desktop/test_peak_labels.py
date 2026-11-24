"""Automatic annotations preserve signals/integration and export their visibility."""
import json
import os
from pathlib import Path
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.text import Text
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from gcviewer.services.acquisition import fid_trace
from gcviewer.desktop.peak_labels import AutomaticLabelsDialog
from tests.desktop.test_fid_analysis import fixture
from gcviewer.desktop.window import Workspace
from gcviewer.figures.comparisons import Comparison
from gcviewer.data_models.acquisition import Trace
from gcviewer.figures.workspace import FigureState, export_figure, render_figure
from gcviewer.services.fid_workflow import AnalysisMethod, calculate
from gcviewer.figures.peak_labels import automatic_labels, arrange_labels
from gcviewer.analysis.retention_names import Component


class PeakLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def trace(self):
        x = np.linspace(0, 10, 2001)
        y = sum(height*np.exp(-.5*((x-center)/.08)**2) for center, height in ((2, 100), (4, 60), (4.5, 30), (8, 10)))
        return Trace('Peaks', 'test', 'GC-MS', x, y)

    def test_detection_threshold_range_break_and_source_preservation(self):
        trace = self.trace()
        state = FigureState.report(trace)
        before = trace.signal.copy()
        labels = automatic_labels(trace, state.settings, count=2)
        self.assertEqual([label.text for label in labels], ['2.00 min', '4.00 min'])
        labels = automatic_labels(trace, state.settings, mode='threshold', threshold=25.)
        self.assertEqual(len(labels), 3)
        state.settings.x_break = (1, 3)
        state.settings.x_range = (0, 6)
        self.assertEqual([l.text for l in automatic_labels(trace, state.settings)], ['4.00 min', '4.50 min'])
        self.assertEqual(len(automatic_labels(trace, state.settings, prominence=50)), 1)
        np.testing.assert_array_equal(trace.signal, before)

    def test_arrangement_visibility_comparison_and_export(self):
        trace = self.trace()
        state = FigureState.report(trace)
        state.labels = automatic_labels(trace, state.settings)
        self.assertEqual(arrange_labels(trace, state, state.labels), 0)
        fig, _, artists = render_figure(trace, state)
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        boxes = [Text.get_window_extent(a, canvas.get_renderer()) for a in artists]
        self.assertFalse(any(a.overlaps(b) for i, a in enumerate(boxes) for b in boxes[i+1:]))
        state.labels[0].visible = False
        self.assertIsNone(render_figure(trace, state)[2][0])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'labeled.svg'
            export_figure(trace, state, target)
            meta = json.loads(target.with_suffix('.svg.json').read_text())
            self.assertFalse(meta['annotations'][0]['visible'])
            self.assertEqual(meta['annotations'][1]['generation']['source'], 'displayed-signal detection')
            self.assertNotIn('2.00 min', target.read_text())
        comparison = Comparison((trace, trace))
        combined = FigureState.report(comparison)
        combined.labels = automatic_labels(comparison, combined.settings, trace_index=1, count=2)
        self.assertTrue(all(label.trace_index == 1 for label in combined.labels))
        self.assertEqual(arrange_labels(comparison, combined, combined.labels), 0)
        combined.labels[0].visible = False
        self.assertIsNone(render_figure(comparison, combined)[2][0])

    def test_fid_names_ui_replacement_manual_drag_hide_and_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            run = fixture(folder)
            window = Workspace()
            try:
                window.add_sample(fid_trace(run), fid_run=run)
                sample = window.active
                method = AnalysisMethod(components=(Component('Reference', 100/60),))
                record = calculate(run, method)
                sample.fid_document.method = method
                sample.fid_document.result = record
                window.fid_analysis.fill()
                manual = sample.state.add_label(sample.trace, 3., 'Manual note', (.4, .4))
                window.refresh_labels()
                def accept():
                    dialog = QApplication.activeModalWidget()
                    self.assertIsInstance(dialog, AutomaticLabelsDialog)
                    self.assertEqual(dialog.source.currentData(), 'fid')
                    dialog.accept()
                QTimer.singleShot(0, accept)
                window.automatic_labels()
                self.assertIs(sample.state.labels[0], manual)
                self.assertIn('Reference\n1.67 min', [label.text for label in sample.state.labels])
                self.assertIs(sample.fid_document.result, record)
                index = next(i for i,l in enumerate(sample.state.labels) if l.origin == 'automatic')
                window.label_list.setCurrentRow(index)
                window.label_text.setText('Edited')
                window.edit_label()
                window.label_visible.setChecked(False)
                self.assertFalse(sample.state.labels[index].visible)
                self.assertIsNone(window.artists[index])
                original = sample.state.labels
                QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
                window.automatic_labels()
                self.assertIs(sample.state.labels, original)
                QTimer.singleShot(0, accept)
                window.automatic_labels()
                self.assertEqual(len(sample.state.labels), len(record['peaks']) + 1)
                self.assertIs(sample.state.labels[0], manual)
                labels = automatic_labels(sample.trace, sample.state.settings, record=record, text_mode='name')
                self.assertEqual([l.text for l in labels], ['Reference'])
            finally:
                window.close()


if __name__ == '__main__':
    unittest.main()
