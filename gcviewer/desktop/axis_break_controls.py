"""Explicit omitted intervals in the current displayed signal units."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QLabel, QLineEdit, QPushButton


class AxisBreakControls(QGroupBox):
    remove_requested = Signal()

    def __init__(self):
        super().__init__("Axis breaks")
        layout = QGridLayout(self)
        layout.setColumnStretch(1, 1)
        explanation = QLabel("Hide the interval between From and To.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation, 0, 0, 1, 2)
        self.enabled, self.editors = {}, {}
        for index, (key, label, examples) in enumerate((("x_break", "Time (min)", ("4", "7")),
                                                       ("y_break", "Signal (original units)", ("2e9", "8e9")))):
            row = 1 + index * 3
            toggle = QCheckBox(label)
            toggle.setToolTip("Enable this axis break, then Apply to figure. Uncheck and Apply to remove it.")
            self.enabled[key] = toggle
            layout.addWidget(toggle, row, 0, 1, 2)
            fields = []
            for offset, (boundary, example) in enumerate(zip(("From", "To"), examples), 1):
                caption = QLabel(boundary)
                caption.hide()
                toggle.toggled.connect(caption.setVisible)
                layout.addWidget(caption, row + offset, 0)
                editor = QLineEdit()
                editor.setMinimumWidth(0)
                editor.setPlaceholderText("e.g. " + example)
                editor.setAccessibleName(f"{label} break {boundary.lower()}")
                editor.setToolTip(f"{boundary} endpoint of the hidden interval. " +
                                  ("Minutes." if key == "x_break" else "Original, unscaled signal units; 2e9 means 2 billion."))
                editor.setEnabled(False)
                editor.hide()
                toggle.toggled.connect(editor.setEnabled)
                toggle.toggled.connect(editor.setVisible)
                layout.addWidget(editor, row + offset, 1)
                fields.append(editor)
            self.editors[key] = tuple(fields)
        units = QLabel("Scientific notation is accepted: 2e9 = 2 billion.")
        units.setWordWrap(True)
        layout.addWidget(units, 7, 0, 1, 2)
        remove = QPushButton("Remove breaks")
        remove.clicked.connect(self.remove_requested.emit)
        layout.addWidget(remove, 8, 0, 1, 2)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status, 9, 0, 1, 2)

    def set_interval(self, key, interval):
        self.enabled[key].setChecked(interval is not None)
        for editor, value in zip(self.editors[key], interval if interval is not None else (None, None)):
            editor.setText("" if value is None else f"{value:.9g}")
            editor.setCursorPosition(0)

    def set_x_quantity(self, label):
        self.enabled["x_break"].setText(label)
        for boundary, editor in zip(("From", "To"), self.editors["x_break"]):
            editor.setAccessibleName(f"{label} break {boundary.lower()}")
            editor.setToolTip(f"{boundary} endpoint of the hidden interval in {label}.")

    def set_y_quantity(self, normalized, smoothed=False, units=None):
        quantity = units or "original units"
        label = "Signal (%)" if normalized else (f"Smoothed signal ({quantity})" if smoothed else f"Signal ({quantity})")
        self.enabled["y_break"].setText(label)
        for boundary, example, editor in zip(("From", "To"), (("20", "80") if normalized else (("2000", "8000") if units else ("2e9", "8e9"))), self.editors["y_break"]):
            editor.setAccessibleName(f"{label} break {boundary.lower()}")
            editor.setPlaceholderText("e.g. " + example)
            editor.setToolTip(f"{boundary} endpoint of the hidden interval. " +
                              ("Percent of the full-trace maximum, after smoothing." if normalized else
                               ("µV after optional smoothing; 1000 µV = 1 mV on the readable axis." if units == "µV" else
                                "Displayed signal after optional smoothing, before tick-label scaling; 2e9 means 2 billion.")))

    def values(self):
        values = {}
        for key, toggle in self.enabled.items():
            if not toggle.isChecked():
                values[key] = None
                continue
            name = self.enabled[key].text()
            try:
                values[key] = tuple(float(editor.text().strip()) for editor in self.editors[key])
            except ValueError:
                raise ValueError(f"{name} break: enter a number in both From and To, or uncheck the break.") from None
        return values
