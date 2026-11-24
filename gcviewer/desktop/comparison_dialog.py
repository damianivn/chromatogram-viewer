"""Choose and order already loaded chromatograms without changing the library."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from gcviewer.figures.comparisons import Comparison, fitted_settings
from gcviewer.figures.workspace import FigureState


class ComparisonDialog(QDialog):
    def __init__(self, parent, candidates, current=None):
        super().__init__(parent)
        self.setWindowTitle("Compare chromatograms")
        self.resize(640, 470)
        self.candidates = dict(candidates)
        self.comparison = None
        layout = QVBoxLayout(self)
        note = QLabel("Check two or more loaded chromatograms from the same instrument. Drag rows to set their order.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a loaded chromatogram…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_rows)
        layout.addWidget(self.search)
        self.rows = QListWidget()
        self.rows.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.rows.setDefaultDropAction(Qt.DropAction.MoveAction)
        for key, trace in candidates:
            item = QListWidgetItem(f"{trace.name}  /  {trace.function or trace.instrument}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setToolTip(trace.source)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key == current else Qt.CheckState.Unchecked)
            self.rows.addItem(item)
        layout.addWidget(self.rows, 1)
        row = QHBoxLayout()
        for caption, checked in (("Check visible", True), ("Clear", False)):
            button = QPushButton(caption)
            button.clicked.connect(lambda _=False, value=checked: self.check_rows(value))
            row.addWidget(button)
        row.addStretch()
        self.mode = QComboBox()
        self.mode.addItem("Overlay", "overlay")
        self.mode.addItem("Stacked", "stacked")
        row.addWidget(self.mode)
        layout.addLayout(row)
        self.selection_summary = QLabel()
        layout.addWidget(self.selection_summary)
        self.rows.itemChanged.connect(self.update_selection_summary)
        self.update_selection_summary()
        self.title = QLineEdit()
        self.title.setPlaceholderText("Figure title (optional)")
        layout.addWidget(self.title)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #a52a2a;")
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create comparison")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def filter_rows(self, text):
        for i in range(self.rows.count()):
            item = self.rows.item(i)
            item.setHidden(text.casefold() not in (item.text() + item.toolTip()).casefold())
        self.update_selection_summary()

    def update_selection_summary(self, *args):
        selected = [self.rows.item(i) for i in range(self.rows.count()) if self.rows.item(i).checkState() == Qt.CheckState.Checked]
        hidden = sum(item.isHidden() for item in selected)
        self.selection_summary.setText(f"{len(selected)} selected" + (f" · {hidden} hidden by search" if hidden else ""))

    def check_rows(self, checked):
        for i in range(self.rows.count()):
            item = self.rows.item(i)
            if not checked or not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def accept(self):
        selected = [self.candidates[self.rows.item(i).data(Qt.ItemDataRole.UserRole)]
                    for i in range(self.rows.count()) if self.rows.item(i).checkState() == Qt.CheckState.Checked]
        try:
            self.comparison = Comparison(tuple(selected), self.title.text().strip() or f"Chromatogram comparison ({len(selected)} traces)")
            self.state = FigureState.report(self.comparison)
            self.state.settings.comparison_mode = self.mode.currentData()
            self.state.settings = fitted_settings(self.comparison, self.state.settings)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        super().accept()
