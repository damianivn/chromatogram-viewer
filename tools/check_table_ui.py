"""Exercise real table widgets in the shared scientific-desktop themes."""
import json
from pathlib import Path
import tempfile

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QVBoxLayout, QWidget

from gcviewer.desktop.fid_analysis import AnalysisPanel
from gcviewer.desktop.appearance import apply_appearance
from gcviewer.desktop.fid_forms import fill_table
from gcviewer.services.library import LibraryEntry
from gcviewer.desktop.library_dialog import LibraryDialog


def smoke_tables(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance()
    old_palette = app.palette()
    old_mode = app.property('appearanceMode') or 'system'
    old_scheme = app.styleHints().colorScheme()
    results = {}

    def settle():
        QTest.qWait(40)

    def click_cell(table, row, column):
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton,
                         pos=table.visualItemRect(table.item(row, column)).center())
        settle()

    def band(table, row, color):
        shot = table.viewport().grab().toImage()
        scale = shot.devicePixelRatio()
        rect = table.visualItemRect(table.item(row, 0))
        y = round((rect.top() + 2) * scale)
        for x in range(2, shot.width() - 2):
            assert shot.pixelColor(x, y).name() == color, (row, x, shot.pixelColor(x, y).name(), color)

    try:
        for style in ('scientific',):
            for dark in (False, True):
                key = style.lower() + ("-dark" if dark else "-light")
                apply_appearance('dark' if dark else 'light')
                with tempfile.TemporaryDirectory() as tmp:
                    library = LibraryDialog(preferences=QSettings(str(Path(tmp) / "prefs.ini"), QSettings.Format.IniFormat))
                    panel = AnalysisPanel()
                    host = QWidget()
                    layout = QVBoxLayout(host)
                    library.set_entries([LibraryEntry(str(i), f"Standard {i}", f"/std{i}.raw", "fid", "Found", True,
                                                      description="Teaching laboratory", vial=str(i), index=i) for i in range(1, 5)])
                    fill_table(panel.table, [[i, "", "4.223736", "86155.8768", "43701.2313", ".9204", "4.176", "4.278", "BB", "No", ""] for i in range(1, 5)])
                    fill_table(panel.components, [["Reference", "4.22", "0.05"], ["Later peak", "5.34", "0.05"], ["", "", ""]])
                    tables = (library.table, panel.table, panel.components)
                    for label, table in zip(("Sample library", "Integrated peaks", "Names: retention-time rules"), tables):
                        layout.addWidget(QLabel(label))
                        table.setMinimumHeight(155)
                        layout.addWidget(table)
                    host.resize(1060, 640)
                    host.show()
                    host.activateWindow()
                    settle()
                    try:
                        selected = "#414141" if dark else "#d9d9d9"
                        hover = "#353535" if dark else "#eeeeee"
                        for table, color in ((library.table, selected), (panel.table, selected)):
                            click_cell(table, 1, 1)
                            position = table.visualItemRect(table.item(2, 2)).center()
                            app.sendEvent(table.viewport(), QMouseEvent(QEvent.Type.MouseMove,
                                QPointF(position), QPointF(table.viewport().mapToGlobal(position)),
                                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
                            settle()
                            band(table, 1, color)
                            band(table, 2, hover)
                            assert len(table.selectionModel().selectedRows()) == 1
                        click_cell(panel.components, 0, 0)
                        assert host.grab().save(str(output / f"{key}-rows.png"))
                        header = panel.components.verticalHeader()
                        QTest.mouseClick(header.viewport(), Qt.MouseButton.LeftButton,
                                         pos=QPoint(5, header.sectionViewportPosition(1) + header.sectionSize(1) // 2))
                        settle()
                        band(panel.components, 1, selected)
                        assert len(panel.components.selectionModel().selectedRows()) == 1
                        assert host.grab().save(str(output / f"{key}-names-row.png"))
                        click_cell(panel.components, 0, 0)
                        QTest.keyClick(panel.components, Qt.Key.Key_F2)
                        settle()
                        editor = panel.components.findChild(QLineEdit)
                        assert editor is not None and editor.isVisible()
                        assert editor.geometry() == panel.components.visualItemRect(panel.components.item(0, 0))
                        editor.setText("Assigned peak")
                        assert host.grab().save(str(output / f"{key}-editing.png"))
                        QTest.keyClick(editor, Qt.Key.Key_Return)
                        settle()
                        assert panel.components.item(0, 0).text() == "Assigned peak"
                        QTest.keyClick(panel.components, Qt.Key.Key_Tab)
                        settle()
                        assert panel.components.currentColumn() == 1
                        library.select_available()
                        assert len(library.selected_entries()) == 4
                        library.table.sortItems(0, Qt.SortOrder.AscendingOrder)
                        library.search.setText("Standard 2")
                        assert [e.key for e in library.selected_entries()] == ["2"]
                        results[key] = dict(continuous_selected_rows=True, neutral_row_hover=True,
                                            rectangular_header_selection=True, edit_commit_and_tab=True,
                                            sorted_filtered_selection=True)
                    finally:
                        panel.cancel(announce=False)
                        library.shutdown()
                        host.close()
                        panel.close()
    finally:
        apply_appearance(old_mode)
        app.styleHints().setColorScheme(old_scheme)
        app.setPalette(old_palette)
    (output / "table-checks.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


if __name__ == "__main__":
    import argparse
    from gcviewer.desktop.appearance import ensure_ui_font
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    app = QApplication([])
    ensure_ui_font()
    print(json.dumps(smoke_tables(args.output), indent=2))
