"""Focused menu, theme and scaling smoke; run with QT_SCALE_FACTOR as needed."""
import argparse
import json
from pathlib import Path
import tempfile

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolBar, QToolButton

from gcviewer.desktop.window import Workspace
from gcviewer.services.acquisition import load_fid, fid_trace
from gcviewer.services.fid_workflow import calculate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    with tempfile.TemporaryDirectory() as temporary:
        window = Workspace(QSettings(str(Path(temporary)/'settings.ini'), QSettings.Format.IniFormat))
        window.show()
        try:
            c = window.layout_controller
            c.set_appearance('dark', save=False)
            QTest.qWait(60)
            wide_width = window.width()
            empty = window.canvas.size()
            window.grab().save(str(args.output/'empty.png'))
            run = load_fid(args.source)
            window.add_sample(fid_trace(run), fid_run=run)
            p = window.fid_analysis
            initial_xlim = p.main_axis.get_xlim()
            p.document.result = calculate(run, p.document.method)
            original = p.document.result
            p.show_result()
            assert p.main_axis.get_xlim() == initial_xlim
            assert not window.findChildren(QToolBar, options=Qt.FindChildOption.FindDirectChildrenOnly)
            for theme in ('dark', 'light'):
                c.set_appearance(theme, save=False)
                for index, name in ((0, 'figure'), (1, 'analysis')):
                    c.view_actions[index].trigger()
                    QTest.qWait(100)
                    assert c.view_actions[index].isChecked()
                    assert p.document.result is original
                    assert window.width() == wide_width
                    assert window.sample_search.palette().color(QPalette.ColorRole.Base) == app.palette().color(QPalette.ColorRole.Base)
                    assert not window.viewport.horizontalScrollBar().isVisible()
                    if index == 1:
                        assert p.table.horizontalScrollBar().maximum() == 0
                        assert p.actions_widget.isVisible()
                        assert p.integrate_button.defaultAction() is p.integrate_action
                        assert p.toolbar.mapTo(p.plot_pane, QPoint()).y() >= p.canvas.height()
                        assert p.title.y() > p.toolbar.mapTo(p.plot_pane, QPoint()).y()
                        for row in range(p.table.rowCount()):
                            for column in range(p.table.columnCount()):
                                assert p.table.item(row, column).textAlignment() == Qt.AlignmentFlag.AlignCenter
                        p.forms.setCurrentIndex(2)
                        QTest.qWait(40)
                        advanced = p.forms.widget(2)
                        toggle = next(b for b in advanced.findChildren(QToolButton) if b.text() == 'Timed events')
                        assert toggle.width() >= advanced.width() - 24
                        assert toggle.y() < 30
                        window.grab().save(str(args.output/f'{theme}-advanced-collapsed.png'))
                        toggle.click()
                        QTest.qWait(40)
                        assert p.events.isVisible() and toggle.y() < 30
                        window.grab().save(str(args.output/f'{theme}-advanced-expanded.png'))
                        toggle.click()
                        p.forms.setCurrentIndex(0)
                    else:
                        assert window.toolbar.mapTo(window.viewport.parentWidget(), QPoint()).y() >= window.viewport.height()
                        assert window.active_title.y() > window.toolbar.mapTo(window.viewport.parentWidget(), QPoint()).y()
                    window.grab().save(str(args.output/f'{theme}-{name}.png'))
                view_menu = window.menuBar().actions()[2].menu()
                view_menu.popup(window.menuBar().mapToGlobal(QPoint(0, window.menuBar().height())))
                view_menu.setActiveAction(c.view_actions[1])
                QTest.qWait(60)
                view_menu.grab().save(str(args.output/f'{theme}-menu.png'))
                view_menu.hide()
                c.view_actions[0].trigger()
                combo = window.fields['publication_style'] if 'publication_style' in window.fields else None
                if combo is None:
                    from PySide6.QtWidgets import QComboBox
                    combo = next(widget for widget in c.figure_page.findChildren(QComboBox) if widget.isVisible())
                combo.showPopup()
                QTest.qWait(60)
                combo.view().window().grab().save(str(args.output/f'{theme}-dropdown.png'))
                combo.hidePopup()
            assert window.canvas.size() == empty
            window.resize(920, 600)
            for index in (0, 1):
                c.view_actions[index].trigger()
                QTest.qWait(60)
                assert window.width() == 920
                if index == 1:
                    assert p.table.horizontalScrollBar().maximum() == 0
            result = dict(menu_navigation=True, neutral_child_palettes=True,
                          integration_preserved=True, compact_geometry=True,
                          no_global_toolbar=True, empty_loaded_geometry=True,
                          device_pixel_ratio=window.devicePixelRatioF(), platform=app.platformName())
            (args.output/'checks.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result))
        finally:
            window.close()


if __name__ == '__main__':
    main()
