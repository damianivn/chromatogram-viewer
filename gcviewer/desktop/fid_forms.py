"""Native Qt forms for FID methods and report layouts."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from gcviewer.reports.fid_pdf import HEADER_FIELDS, ReportOptions
from gcviewer.desktop.tables import FlatTableWidget
from gcviewer.analysis.retention_names import Component


def table_rows(table):
    return [[table.item(r, c).text().strip() if table.item(r, c) else ""
             for c in range(table.columnCount())] for r in range(table.rowCount())]


def fill_table(table, rows):
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(str(text)))


def table_editor(headers, rows=()):
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    table = FlatTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setStretchLastSection(True)
    table.setMinimumHeight(130)
    fill_table(table, rows)
    layout.addWidget(table)
    buttons = QHBoxLayout()
    for label, action in (("Add row", lambda: table.insertRow(table.rowCount())),
                          ("Remove row", lambda: table.removeRow(table.currentRow()))):
        button = QPushButton(label)
        button.clicked.connect(action)
        buttons.addWidget(button)
    buttons.addStretch()
    layout.addLayout(buttons)
    return panel, table


class DetectedPeakNamesDialog(QDialog):
    """Review unnamed integrated peaks before appending reusable naming rules."""
    def __init__(self, peaks, existing, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Use detected peaks for Names")
        self.resize(620, 420)
        self.peaks, self.existing = peaks, existing
        self.components = ()
        layout = QVBoxLayout(self)
        note = QLabel("Choose peaks and edit their proposed names. Existing rules are kept.\nClipped peaks start unchecked. Peak numbers are placeholders, not chemical identities.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setDecimals(6)
        self.tolerance.setRange(.000001, 10000)
        self.tolerance.setValue(.05)
        self.tolerance.setSingleStep(.01)
        form.addRow("Retention-time tolerance ± (min)", self.tolerance)
        layout.addLayout(form)
        self.table = FlatTableWidget(len(peaks), 4)
        self.table.setHorizontalHeaderLabels(["Use", "Proposed name", "RT (min)", "Clipped"])
        self.table.verticalHeader().hide()
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(24)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 42)
        used = {c.name.casefold() for c in existing}
        self.checks = []
        for row, peak in enumerate(peaks):
            base = name = f"Peak {peak['number']}"
            suffix = 2
            while name.casefold() in used:
                name = f"{base} ({suffix})"
                suffix += 1
            used.add(name.casefold())
            for column, text in enumerate(("", name, f"{peak['rt_min']:.6f}", "Yes" if peak['clipped'] else "")):
                item = QTableWidgetItem(text)
                if column != 1:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
            check = QCheckBox()
            check.setChecked(not peak['clipped'])
            check.setAccessibleName(f"Include peak {peak['number']}")
            self.table.setCellWidget(row, 0, check)
            self.checks.append(check)
        layout.addWidget(self.table)
        choices = QHBoxLayout()
        for label, checked in (("Select all", True), ("Clear selection", False)):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, checked=checked: self.select_all(checked))
            choices.addWidget(button)
        choices.addStretch()
        layout.addLayout(choices)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add to Names")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def select_all(self, checked):
        for check in self.checks:
            check.setChecked(checked)

    def accept(self):
        try:
            components = tuple(Component(self.table.item(row, 1).text().strip(), peak['rt_min'], self.tolerance.value())
                               for row, peak in enumerate(self.peaks)
                               if self.checks[row].isChecked())
            if not components:
                raise ValueError("Select at least one peak to add.")
            names = [c.name.casefold() for c in (*self.existing, *components)]
            if len(names) != len(set(names)):
                raise ValueError("Use a different name for each component, including existing rules.")
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.components = components
        super().accept()


class ReportLayoutDialog(QDialog):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FID report layout")
        self.resize(720, 650)
        self.options = options
        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs)
        page = QWidget()
        form = QFormLayout(page)
        self.fields = {}
        for key, label in (("title", "Title"), ("subtitle", "Subtitle"), ("x_label", "Time axis label"), ("y_label", "Signal axis label")):
            edit = QLineEdit(getattr(options, key))
            self.fields[key] = edit
            form.addRow(label, edit)
        self.paper = QComboBox()
        self.paper.addItems(["Letter", "A4"])
        self.paper.setCurrentText(options.page_size.title())
        form.addRow("Paper", self.paper)
        self.heading = QComboBox()
        self.heading.addItem("None", "")
        for key, (label, _) in HEADER_FIELDS.items():
            self.heading.addItem(label, key)
        self.heading.setCurrentIndex(self.heading.findData(options.heading))
        form.addRow("Large heading", self.heading)
        self.flags = {}
        for key, label in (("heading_time", "Show injection time"), ("full_scale_strip", "Full-run overview strip"),
                           ("hide_solvent", "Hide solvent in main plot (view only)"), ("zoom_to_peaks", "Fit signal scale to unclipped peaks"),
                           ("legend", "Show plot legend"), ("minor_ticks", "Minor axis ticks"),
                           ("peak_table_new_page", "Start peak table on a new page")):
            box = QCheckBox(label)
            box.setChecked(getattr(options, key))
            self.flags[key] = box
            form.addRow(box)
        self.labels = QComboBox()
        for label, key in (("Name or retention time", "name_or_rt"), ("Retention time", "rt"), ("Name", "name"), ("Name and retention time", "name_and_rt"), ("None", "none")):
            self.labels.addItem(label, key)
        self.labels.setCurrentIndex(self.labels.findData(options.peak_labels))
        form.addRow("Peak labels", self.labels)
        for key, label in (("main_start_min", "Main plot start (min)"), ("main_end_min", "Main plot end (min)")):
            value = getattr(options, key)
            edit = QLineEdit("" if value is None else str(value))
            edit.setPlaceholderText("Automatic")
            self.fields[key] = edit
            form.addRow(label, edit)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        tabs.addTab(scroll, "Page and plots")
        details = QWidget()
        layout = QVBoxLayout(details)
        layout.addWidget(QLabel("Select, rename and reorder the information printed above the plot."))
        self.header = QTableWidget(0, 3)
        self.header.setHorizontalHeaderLabels(["Include", "Information", "Printed label"])
        ordered = list(options.fields()) + [(k, v[0]) for k, v in HEADER_FIELDS.items() if k not in dict(options.fields())]
        self.header.setRowCount(len(ordered))
        for row, (key, label) in enumerate(ordered):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Checked if key in dict(options.fields()) else Qt.CheckState.Unchecked)
            item = QTableWidgetItem(HEADER_FIELDS[key][0])
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            for col, value in enumerate((check, item, QTableWidgetItem(label))):
                self.header.setItem(row, col, value)
        self.header.horizontalHeader().setStretchLastSection(True)
        self.header.resizeColumnsToContents()
        layout.addWidget(self.header)
        moves = QHBoxLayout()
        for label, step in (("Move up", -1), ("Move down", 1)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, step=step: self.move_row(step))
            moves.addWidget(button)
        moves.addStretch()
        layout.addLayout(moves)
        extras, self.extras = table_editor(["Extra label", "Value"], options.extra_fields)
        layout.addWidget(extras)
        tabs.addTab(details, "Report details")
        notes = QWidget()
        note_layout = QVBoxLayout(notes)
        note_layout.addWidget(QLabel("Notes appear with the report. Method provenance is always retained in the accompanying JSON."))
        self.notes = QPlainTextEdit("\n".join(options.notes))
        note_layout.addWidget(self.notes)
        note_layout.addWidget(QLabel("Report footer"))
        self.disclaimer = QLineEdit(options.disclaimer)
        note_layout.addWidget(self.disclaimer)
        tabs.addTab(notes, "Notes")
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        outer.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def move_row(self, step):
        row = self.header.currentRow()
        other = row + step
        if row < 0 or not 0 <= other < self.header.rowCount():
            return
        for col in range(3):
            a, b = self.header.takeItem(row, col), self.header.takeItem(other, col)
            self.header.setItem(row, col, b)
            self.header.setItem(other, col, a)
        self.header.setCurrentCell(other, 1)

    def accept(self):
        try:
            values = {k: edit.text().strip() for k, edit in self.fields.items()}
            for key in ("main_start_min", "main_end_min"):
                values[key] = float(values[key]) if values[key] else None
            values.update({k: box.isChecked() for k, box in self.flags.items()})
            fields = tuple((self.header.item(r, 1).data(Qt.ItemDataRole.UserRole), self.header.item(r, 2).text().strip())
                           for r in range(self.header.rowCount()) if self.header.item(r, 0).checkState() == Qt.CheckState.Checked)
            extras = tuple(tuple(row) for row in table_rows(self.extras) if any(row))
            self.options = ReportOptions(**values, page_size=self.paper.currentText().lower(), heading=self.heading.currentData(),
                peak_labels=self.labels.currentData(), header_fields=fields, extra_fields=extras,
                notes=tuple(self.notes.toPlainText().splitlines()), disclaimer=self.disclaimer.text())
        except (ValueError, TypeError) as exc:
            self.error.setText(str(exc))
            return
        super().accept()
