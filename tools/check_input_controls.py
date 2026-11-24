"""Focused geometry and keyboard/mouse checks for shared desktop inputs."""
import argparse
import json
from pathlib import Path
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QApplication, QWidget, QFormLayout, QLineEdit,
    QSpinBox, QDoubleSpinBox, QComboBox, QPushButton, QStyle, QStyleOptionSpinBox,
    QStyleOptionComboBox)
from gcviewer.desktop.appearance import ensure_ui_font, apply_appearance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    ensure_ui_font()
    app.setCursorFlashTime(0)
    window = QWidget()
    form = QFormLayout(window)
    controls = [QLineEdit('288'), QSpinBox(), QDoubleSpinBox(), QComboBox(), QComboBox()]
    controls[1].setRange(0, 9999)
    controls[1].setValue(288)
    controls[2].setRange(-1000, 1000)
    controls[2].setValue(12.5)
    controls[3].addItems(['Original units', 'Maximum = 100%'])
    controls[4].setEditable(True)
    controls[4].addItems(['Editable value', 'Second value'])
    for name, widget in zip(('Text', 'Integer', 'Decimal', 'Choice', 'Editable choice'), controls):
        form.addRow(name, widget)
    unfocus = QPushButton('Focus target')
    form.addRow(unfocus)
    window.resize(440, 260)
    window.show()
    window.activateWindow()
    checks = {}
    def geometry(widget):
        editor = widget if isinstance(widget, QLineEdit) else widget.findChild(QLineEdit)
        if editor:
            editor.setCursorPosition(0)
            editor.deselect()
            return [editor.geometry().getRect(), editor.cursorRect().getRect()]
        option = QStyleOptionComboBox()
        widget.initStyleOption(option)
        return widget.style().subControlRect(QStyle.ComplexControl.CC_ComboBox,
            option, QStyle.SubControl.SC_ComboBoxEditField, widget).getRect()
    for theme in ('dark', 'light'):
        apply_appearance(theme)
        QTest.qWait(40)
        for metric in (QStyle.PixelMetric.PM_ButtonShiftHorizontal, QStyle.PixelMetric.PM_ButtonShiftVertical):
            assert app.style().pixelMetric(metric) == 0
        for index, widget in enumerate(controls):
            unfocus.setFocus()
            QTest.mouseMove(unfocus, QPoint(5,5))
            before = geometry(widget)
            QTest.qWait(20)
            widget.grab().save(str(args.output/f'{theme}-{index}-normal.png'))
            widget.setFocus(Qt.FocusReason.TabFocusReason)
            after = geometry(widget)
            QTest.qWait(20)
            widget.grab().save(str(args.output/f'{theme}-{index}-focus.png'))
            assert before == after, (theme, index, before, after)
            QTest.mouseMove(widget, QPoint(widget.width()-8, widget.height()//4))
            QTest.qWait(20)
            assert geometry(widget) == before
            widget.grab().save(str(args.output/f'{theme}-{index}-hover.png'))
        window.grab().save(str(args.output/f'{theme}-inputs.png'))
        spin = controls[1]
        option = QStyleOptionSpinBox()
        spin.initStyleOption(option)
        up = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxUp, spin)
        down = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxDown, spin)
        assert up.center().x() == down.center().x()
        initial = spin.value()
        QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=up.center())
        assert spin.value() == initial+1
        QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=down.center())
        assert spin.value() == initial
        spin.setFocus()
        QTest.keyClick(spin, Qt.Key.Key_Up)
        QTest.keyClick(spin, Qt.Key.Key_Down)
        assert spin.value() == initial
        before_popup = geometry(controls[3])
        controls[3].showPopup()
        QTest.qWait(30)
        assert geometry(controls[3]) == before_popup
        controls[3].view().window().grab().save(str(args.output/f'{theme}-popup.png'))
        QTest.keyClick(controls[3].view(), Qt.Key.Key_Down)
        QTest.keyClick(controls[3].view(), Qt.Key.Key_Return)
        assert controls[3].currentIndex() == 1
        controls[3].setCurrentIndex(0)
        for widget in controls: widget.setEnabled(False)
        window.grab().save(str(args.output/f'{theme}-disabled.png'))
        for widget in controls: widget.setEnabled(True)
        checks[theme] = dict(stable_focus_hover_geometry=True, spin_mouse_keyboard=True, combo_keyboard=True)
    window.close()
    (args.output/'checks.json').write_text(json.dumps(checks, indent=2))
    print(json.dumps(checks))

if __name__ == '__main__':
    main()
