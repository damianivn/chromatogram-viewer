"""Compact single-line sample rows with a separate inline loading state."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import QListWidget, QStyle, QStyledItemDelegate
from gcviewer.desktop.appearance import selection_colors

DETAIL_ROLE = int(Qt.ItemDataRole.UserRole) + 1
STATUS_ROLE = int(Qt.ItemDataRole.UserRole) + 2


class SampleList(QListWidget):
    """Native range/toggle selection and insertion-only internal drag moves."""
    interactionFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selection_interaction = False
        self.setSelectionMode(self.SelectionMode.ExtendedSelection)
        self.setDragDropMode(self.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)
        self.setDropIndicatorShown(True)
        self.setSelectionRectVisible(True)
        self.setMouseTracking(True)
        self.model().rowsInserted.connect(self.prepare_rows)
        self.setToolTip('Drag a row to reorder. Drag empty space to box-select. Shift-click selects a range; Ctrl-click toggles samples.')

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selection_interaction = True
        super().mousePressEvent(event)

    def finish_interaction(self):
        if self.selection_interaction:
            self.selection_interaction = False
            self.interactionFinished.emit()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.finish_interaction()

    def startDrag(self, actions):
        self.finish_interaction()
        super().startDrag(actions)

    def prepare_rows(self, parent, first, last):
        for row in range(first, last + 1):
            item = self.item(row)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)


class SampleDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(220, max(24, option.fontMetrics.height() + 8))

    def paint(self, painter, option, index):
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        background, foreground = selection_colors(option.palette, selected,
            bool(option.state & QStyle.StateFlag.State_MouseOver))
        painter.fillRect(option.rect, background or option.palette.color(QPalette.ColorRole.Base))
        rect = option.rect.adjusted(7, 2, -7, -2)
        primary = QFont(option.font)
        small = QFont(option.font)
        small.setPointSizeF(max(8, small.pointSizeF() - 1))
        painter.setFont(small)
        status = index.data(STATUS_ROLE) or ""
        status_width = painter.fontMetrics().horizontalAdvance(status) + 10
        painter.setPen(foreground if selected else option.palette.color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, status)
        painter.setFont(primary)
        painter.setPen(foreground)
        name_rect = rect.adjusted(0, 0, -status_width, 0)
        name = painter.fontMetrics().elidedText(str(index.data() or ""), Qt.TextElideMode.ElideMiddle, name_rect.width())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter, name)
        painter.restore()
