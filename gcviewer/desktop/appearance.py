"""Shared rectangular desktop controls, neutral states and light/dark palettes."""
import os
from pathlib import Path

from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QPalette
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCommonStyle, QProxyStyle, QStyle, QStyleFactory, QStyleOptionViewItem


CONTROL_STYLE = """
QPushButton, QToolButton {
    border: 1px solid palette(mid); border-radius: 0;
    background: palette(button); color: palette(button-text);
    padding: 3px 8px; min-height: 1.25em;
}
QToolButton { border-color: transparent; padding: 3px; }
QToolButton[disclosure="true"] { border: 1px solid palette(mid); padding: 2px 5px; text-align: left; }
QPushButton:hover, QToolButton:hover { background: palette(alternate-base); border-color: palette(placeholder-text); }
QPushButton:pressed, QToolButton:pressed, QPushButton:checked, QToolButton:checked {
    background: palette(highlight); border-color: palette(placeholder-text);
}
QPushButton:default { border-color: palette(placeholder-text); }
QPushButton:focus, QToolButton:focus { border-color: palette(window-text); }
QPushButton:disabled, QToolButton:disabled { background: palette(window); color: palette(button-text); }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    border: 1px solid palette(mid); border-radius: 0;
    background: palette(base); color: palette(text);
    padding: 2px 4px; min-height: 1.25em;
    selection-background-color: palette(highlight); selection-color: palette(highlighted-text);
}
/* The outer control owns the only frame. Keep arrow hit areas inside it;
   never inherit the standalone editor frame/padding in an embedded editor. */
QComboBox, QSpinBox, QDoubleSpinBox { padding-right: 24px; }
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: center right;
    border: 0; width: 20px; background: transparent;
}
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: padding; subcontrol-position: top right;
    width: 20px; border: 0; background: transparent;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: padding; subcontrol-position: bottom right;
    width: 20px; border: 0; background: transparent;
}
QComboBox::drop-down:hover, QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: palette(alternate-base); }
QComboBox::down-arrow, QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("@DOWN@"); width: 12px; height: 8px; top: 0; left: 0;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("@UP@"); width: 12px; height: 8px; top: 0; left: 0;
}
QAbstractSpinBox QLineEdit, QAbstractSpinBox QLineEdit:focus,
QComboBox QLineEdit, QComboBox QLineEdit:focus {
    border: 0; padding: 0; margin: 0; min-height: 0; background: transparent;
}
QComboBox QAbstractItemView {
    border: 1px solid palette(mid); padding: 2px 0; outline: 0;
    background: palette(base); color: palette(text);
    selection-background-color: palette(highlight); selection-color: palette(highlighted-text);
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: palette(window-text); }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    background: palette(window); color: palette(placeholder-text);
}
QAbstractSpinBox:disabled QLineEdit, QComboBox:disabled QLineEdit { color: palette(placeholder-text); }
QAbstractItemView, QTextEdit, QPlainTextEdit {
    border: 1px solid palette(mid); border-radius: 0;
    selection-background-color: palette(highlight); selection-color: palette(highlighted-text);
}
QAbstractItemView:focus, QTextEdit:focus, QPlainTextEdit:focus { border-color: palette(placeholder-text); }
QMenuBar { border: 0; border-bottom: 1px solid palette(mid); background: palette(window); }
QMenuBar::item { border: 0; border-radius: 0; padding: 4px 8px; background: transparent; }
QMenuBar::item:selected, QMenuBar::item:pressed { background: palette(highlight); }
QMenu { border: 1px solid palette(mid); border-radius: 0; padding: 2px 0; background: palette(base); }
QMenu::item { border: 0; border-radius: 0; padding: 4px 24px 4px 12px; }
QMenu::item:selected { background: palette(highlight); color: palette(highlighted-text); }
QMenu::indicator { width: 16px; height: 16px;
    subcontrol-origin: padding; subcontrol-position: center left; left: 5px; }
QMenu::indicator:checked { image: url("@CHECK@"); }
QMenu::indicator:unchecked { image: none; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid palette(mid);
    border-radius: 0; background: palette(base); }
QCheckBox::indicator:checked { image: url("@CHECK@"); }
QCheckBox::indicator:hover, QCheckBox::indicator:focus { border-color: palette(window-text); }
QScrollBar:vertical { background: palette(window); width: 12px; margin: 0; border: 0; }
QScrollBar:horizontal { background: palette(window); height: 12px; margin: 0; border: 0; }
QScrollBar::handle { background: palette(mid); border: 0; border-radius: 0; }
QScrollBar::handle:vertical { min-height: 28px; margin: 2px; }
QScrollBar::handle:horizontal { min-width: 28px; margin: 2px; }
QScrollBar::handle:hover, QScrollBar::handle:pressed { background: palette(placeholder-text); }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: 0; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QMenu::separator { height: 1px; background: palette(mid); margin: 4px 6px; }
QTabWidget::pane { border: 1px solid palette(mid); border-radius: 0; }
QTabBar::tab {
    border: 1px solid palette(mid); border-radius: 0;
    padding: 4px 8px; background: palette(window); color: palette(window-text);
}
QTabBar::tab:selected { background: palette(base); border-bottom-color: palette(base); }
QTabBar::tab:hover:!selected { background: palette(alternate-base); }
QGroupBox { border: 1px solid palette(mid); border-radius: 0; margin-top: 0.7em; padding-top: 0.5em; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 6px; padding: 0 3px; }
QHeaderView::section { border: 0; border-right: 1px solid palette(mid); border-bottom: 1px solid palette(mid);
    border-radius: 0; padding: 3px 4px; background: palette(button); }
QProgressBar { border: 1px solid palette(mid); border-radius: 0; text-align: center; background: palette(base); }
QProgressBar::chunk { background: palette(placeholder-text); border-radius: 0; }
QToolBar { border: 0; background: palette(window); spacing: 2px; padding: 0; }
QToolTip { border: 1px solid palette(mid); border-radius: 0; padding: 4px; }
QSplitter::handle { background: palette(window); }
QSplitter::handle:hover { background: palette(mid); }
"""


def control_style():
    icons = Path(__file__).parent / 'icons'
    theme = QApplication.instance().property('renderedTheme') or 'light'
    return CONTROL_STYLE.replace('@CHECK@', (icons / f'check-{theme}.svg').as_posix()).replace('@DOWN@', (icons / 'arrow-down.svg').as_posix()).replace(
        '@UP@', (icons / 'arrow-up.svg').as_posix())


def selection_colors(palette, selected=False, hovered=False):
    dark = palette.color(QPalette.ColorRole.Base).lightness() < 128
    background = QColor('#414141' if dark else '#d9d9d9') if selected else (
        QColor('#353535' if dark else '#eeeeee') if hovered else None)
    return background, palette.color(QPalette.ColorRole.Text)


def apply_appearance(mode):
    """App-local preference; publication renderers always use white paper."""
    app = QApplication.instance()
    app.setProperty('appearanceMode', mode)
    scheme = {'system': Qt.ColorScheme.Unknown, 'light': Qt.ColorScheme.Light,
              'dark': Qt.ColorScheme.Dark}[mode]
    app.styleHints().setColorScheme(scheme)
    update_palette()


def update_palette(*_):
    app = QApplication.instance()
    mode = app.property('appearanceMode') or 'system'
    dark = mode == 'dark' or (mode == 'system' and app.styleHints().colorScheme() == Qt.ColorScheme.Dark)
    theme = 'dark' if dark else 'light'
    if app.property('renderedTheme') == theme:
        return
    app.setProperty('renderedTheme', theme)
    palette = QPalette()
    values = dict(Window='#1e1e1e' if dark else '#f3f3f3',
        Base='#2d2d2d' if dark else '#ffffff', AlternateBase='#353535' if dark else '#eeeeee',
        Button='#3c3c3c' if dark else '#ffffff', Text='#ffffff' if dark else '#202020',
        WindowText='#ffffff' if dark else '#202020', ButtonText='#ffffff' if dark else '#202020',
        PlaceholderText='#b9b9b9' if dark else '#606060', Highlight='#414141' if dark else '#d9d9d9',
        HighlightedText='#ffffff' if dark else '#202020', ToolTipBase='#2d2d2d' if dark else '#ffffff',
        ToolTipText='#ffffff' if dark else '#202020', Link='#8cbff0' if dark else '#005a9e',
        Mid='#555555' if dark else '#c7c7c7')
    for role, color in values.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    for role in ('Text', 'WindowText', 'ButtonText'):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role),
                         QColor('#858585' if dark else '#767676'))
    app.setPalette(palette)
    app.setStyleSheet(control_style())


class NeutralItemStyle(QProxyStyle):
    """Predictable Fusion geometry with seamless neutral item selections."""
    def __init__(self, base):
        super().__init__(base)
        self.contents = QCommonStyle()
        self.contents.setParent(self)

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ComboBox_Popup:
            return 0
        return super().styleHint(hint, option, widget, returnData)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (QStyle.PixelMetric.PM_ButtonShiftHorizontal,
                      QStyle.PixelMetric.PM_ButtonShiftVertical):
            return 0
        return super().pixelMetric(metric, option, widget)

    def drawControl(self, element, option, painter, widget=None):
        if element == QStyle.ControlElement.CE_ItemViewItem:
            opt = QStyleOptionViewItem(option)
            background, foreground = selection_colors(opt.palette,
                bool(opt.state & QStyle.StateFlag.State_Selected),
                bool(opt.state & QStyle.StateFlag.State_MouseOver))
            if background is not None:
                painter.fillRect(opt.rect, background)
                opt.backgroundBrush = QBrush(Qt.BrushStyle.NoBrush)
                opt.features &= ~QStyleOptionViewItem.ViewItemFeature.Alternate
            opt.state &= ~(QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_HasFocus)
            opt.palette.setColor(QPalette.ColorRole.Text, foreground)
            self.contents.drawControl(element, opt, painter, widget)
        elif element == QStyle.ControlElement.CE_RubberBand:
            painter.save()
            painter.setPen(QColor('#0078d4'))
            painter.setBrush(QColor(0, 120, 212, 45))
            painter.drawRect(option.rect.adjusted(0, 0, -1, -1))
            painter.restore()
        else:
            super().drawControl(element, option, painter, widget)


def ensure_ui_font():
    """Keep the native font; provide a real font when offscreen Qt has no fonts."""
    app = QApplication.instance()
    if not app.property('scientificStyleInstalled'):
        app.setStyle(NeutralItemStyle(QStyleFactory.create('Fusion')))
        app.setStyleSheet(control_style())
        app.styleHints().colorSchemeChanged.connect(update_palette)
        app.setProperty('scientificStyleInstalled', True)
    if app.font().family() in QFontDatabase.families():
        return
    system_font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
    if system_font.is_file() and QFontDatabase.addApplicationFont(str(system_font)) >= 0:
        app.setFont(QFont("Segoe UI", 9))
        return
    from matplotlib import get_data_path
    QFontDatabase.addApplicationFont(str(Path(get_data_path()) / "fonts/ttf/DejaVuSans.ttf"))
    app.setFont(QFont("DejaVu Sans", 9))
