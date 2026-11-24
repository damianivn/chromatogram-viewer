"""Square selection, box selection, multi-remove and themed empty canvas."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem
from gcviewer.desktop.tables import FlatTableWidget
from gcviewer.desktop.window import Workspace
from gcviewer.figures.workspace import demo_trace


class SelectionAppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = Workspace()
        self.window.show()
        QTest.qWait(90)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_full_width_neutral_rows_and_generic_item_accent(self):
        view = self.window.sample_list
        self.window.add_sample(demo_trace())
        generic = QListWidget()
        generic.addItem(QListWidgetItem('Selected item'))
        generic.setCurrentRow(0)
        generic.resize(200, 80)
        generic.show()
        table = FlatTableWidget(0, 1)
        try:
            for dark in (False, True):
                palette = QPalette(view.palette())
                palette.setColor(QPalette.ColorRole.Base, QColor('#2d2d2d' if dark else '#ffffff'))
                palette.setColor(QPalette.ColorRole.Text, QColor('#ffffff' if dark else '#000000'))
                for widget in (view, generic): widget.setPalette(palette)
                QTest.qWait(20)
                expected = '#414141' if dark else '#d9d9d9'
                self.assertEqual(table.itemDelegate().colors(palette, selected=True)[0].name(), expected)
                for widget in (view, generic):
                    shot = widget.viewport().grab().toImage()
                    rect = widget.visualItemRect(widget.item(0))
                    right = min(rect.right(), shot.width()-1)
                    for x in (rect.left(), rect.left()+2, right-2, right):
                        self.assertEqual(shot.pixelColor(x, rect.top()+1).name(), expected,
                                         (type(widget).__name__, x, rect.getRect()))
        finally:
            generic.close()
            table.close()

    def test_marquee_and_multi_remove_keep_unselected(self):
        view = self.window.sample_list
        keys = [self.window.add_sample(demo_trace()) for _ in range(4)]
        QTest.qWait(50)
        start = QPoint(view.viewport().width()-8, view.visualItemRect(view.item(3)).bottom()+25)
        end = QPoint(8, view.visualItemRect(view.item(1)).top()+2)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), end, 30)
        QTest.qWait(30)
        image = view.viewport().grab().toImage()
        self.assertTrue(any(image.pixelColor(x, y).name() == '#0078d4'
                            for x in range(image.width()) for y in (end.y(), end.y()+1)))
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(len(view.selectedItems()), 3)
        self.window.remove_sample()
        self.assertEqual(list(self.window.samples), [keys[0]])
        self.assertEqual(view.count(), 1)

    def test_empty_plot_matches_default_plot_geometry_and_dark_surface(self):
        window = self.window
        palette = QPalette(window.palette())
        palette.setColor(QPalette.ColorRole.Base, QColor('#2d2d2d'))
        palette.setColor(QPalette.ColorRole.Text, QColor('#ffffff'))
        window.setPalette(palette)
        window.redraw()
        size = window.canvas.size()
        self.assertAlmostEqual(size.width()/size.height(), 180/110, delta=.01)
        self.assertEqual(tuple(round(c*255) for c in window.canvas.figure.get_facecolor()[:3]), (45,45,45))
        window.add_sample(demo_trace())
        QTest.qWait(90)
        self.assertEqual(window.canvas.size(), size)
        self.assertEqual(window.canvas.figure.get_facecolor(), (1.,1.,1.,1.))


if __name__ == '__main__':
    unittest.main()
