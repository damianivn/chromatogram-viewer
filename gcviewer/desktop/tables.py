"""Flat table cells without the native per-cell selection accents.

Keep native controls elsewhere. Windows 11 decorates selected items with rounded
tiles and accent bars, even in a table whose selection unit is the whole row.
"""
from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QBrush, QPainter, QPalette
from PySide6.QtWidgets import (
    QCommonStyle, QLineEdit, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QTableWidget,
)
from gcviewer.desktop.appearance import selection_colors


class FlatCellDelegate(QStyledItemDelegate):
    def __init__(self, table):
        super().__init__(table)
        self.table = table
        self.contents = QCommonStyle()
        self.contents.setParent(self)

    def colors(self, palette, selected=False, hovered=False):
        return selection_colors(palette, selected, hovered)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        hovered = (index.row() == self.table.hover_row if self.table.row_hover else
                   bool(opt.state & QStyle.StateFlag.State_MouseOver))
        background, foreground = self.colors(opt.palette, selected, hovered)
        painter.save()
        if background is not None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            transform = painter.deviceTransform()
            inverse, _ = transform.inverted()
            bounds = inverse.mapRect(QRectF(transform.mapRect(QRectF(opt.rect)).toAlignedRect()))
            painter.fillRect(bounds, background)
            opt.backgroundBrush = QBrush(Qt.BrushStyle.NoBrush)
            opt.features &= ~QStyleOptionViewItem.ViewItemFeature.Alternate
        opt.state &= ~(QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver |
                       QStyle.StateFlag.State_HasFocus)
        opt.palette.setColor(QPalette.ColorRole.Text, foreground)
        self.contents.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, self.table)
        painter.restore()

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            background, foreground = self.colors(option.palette, selected=True)
            editor.setFrame(False)
            editor.setStyleSheet(
                "QLineEdit { border: 0; border-radius: 0; padding: 0 3px; "
                f"background: {background.name()}; color: {foreground.name()}; "
                "selection-background-color: #808080; selection-color: white; }")
        return editor

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class FlatTableWidget(QTableWidget):
    def __init__(self, rows, columns, parent=None, *, row_hover=False):
        super().__init__(rows, columns, parent)
        self.row_hover = row_hover
        self.hover_row = -1
        self._hover_position = None
        self.setShowGrid(False)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setItemDelegate(FlatCellDelegate(self))
        self.model().layoutChanged.connect(self.refresh_hover)
        self.model().modelReset.connect(self.refresh_hover)

    def refresh_hover(self, *args):
        row = self.indexAt(self._hover_position).row() if self._hover_position is not None else -1
        if row != self.hover_row:
            self.hover_row = row
            self.viewport().update()

    def viewportEvent(self, event):
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
            self._hover_position = event.position().toPoint()
            self.refresh_hover()
        elif event.type() in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            self._hover_position = None
            self.refresh_hover()
        return super().viewportEvent(event)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.refresh_hover()
