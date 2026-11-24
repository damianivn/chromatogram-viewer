"""On-demand GC-MS inspection; large matrices live only while this dialog is open."""
from gcviewer.analysis.mass_spectra import eic as ms_eic, spectrum as ms_spectrum, tic as ms_tic
from dataclasses import replace
import tempfile

from PySide6.QtCore import Qt, QTimer, Signal, QSignalBlocker
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout, QWidget)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from gcviewer.services.worker import read_ms_result
from gcviewer.desktop.loading import LoadService
from gcviewer.figures.workspace import FigureState, render_figure


class MSInspector(QDialog):
    report_requested = Signal(object)

    def __init__(self, parent, source_trace, *, autoload=True):
        super().__init__(parent)
        self.setWindowTitle("GC-MS tools")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(1000, 690)
        self.setMinimumSize(760, 550)
        self.source_trace = source_trace
        self.functions = []
        self.trace = self.state = None
        self.directory = None
        self.closed = False
        self.loader = LoadService(self)
        self.loader.completed.connect(self.loaded)
        self.loader.failed.connect(lambda key, detail: self.load_failed(detail))
        layout = QVBoxLayout(self)
        title = QLabel(source_trace.name)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)
        self.status = QLabel("Loading mass channels…")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        body = QHBoxLayout()
        layout.addLayout(body, 1)
        self.controls = QWidget()
        self.controls.setFixedWidth(235)
        options = QVBoxLayout(self.controls)
        options.setContentsMargins(0, 0, 12, 0)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        options.addLayout(form)
        self.function = QComboBox()
        self.function.setMinimumContentsLength(12)
        self.function.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        form.addRow("MS function", self.function)
        self.mode = QComboBox()
        for label, key in (("Total ion chromatogram", "tic"), ("Extracted ion chromatogram", "eic"),
                           ("Single-scan spectrum", "single"), ("Averaged spectrum", "mean")):
            self.mode.addItem(label, key)
        form.addRow("View", self.mode)
        self.mz = QLineEdit("91")
        self.start = QLineEdit()
        self.end = QLineEdit()
        self.input_rows = []
        for caption, editor in (("Requested m/z", self.mz), ("Time / From (min)", self.start), ("To (min)", self.end)):
            label = QLabel(caption)
            form.addRow(label, editor)
            self.input_rows.append((label, editor))
            editor.textChanged.connect(self.invalidate)
            editor.returnPressed.connect(self.update_preview)
        self.method = QLabel()
        self.method.setWordWrap(True)
        options.addWidget(self.method)
        self.update_button = QPushButton("Update preview")
        self.update_button.clicked.connect(self.update_preview)
        options.addWidget(self.update_button)
        options.addStretch()
        note = QLabel("Create a report to adjust layout, fonts, labels and axis breaks, then export a figure or full-resolution CSV.")
        note.setWordWrap(True)
        options.addWidget(note)
        body.addWidget(self.controls)
        from gcviewer.desktop.window import FigureViewport
        self.canvas = FigureCanvasQTAgg(Figure())
        self.viewport = FigureViewport(self)
        self.viewport.setWidget(self.canvas)
        body.addWidget(self.viewport, 1)
        self.selection_info = QLabel()
        self.selection_info.setWordWrap(True)
        self.selection_info.setTextFormat(Qt.TextFormat.PlainText)
        self.selection_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.selection_info)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.create_button = QPushButton("Create report")
        self.create_button.setEnabled(False)
        self.create_button.clicked.connect(self.create_report)
        self.create_button.setAutoDefault(False)
        self.update_button.setDefault(True)
        buttons.addWidget(self.create_button)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        close.setAutoDefault(False)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.function.currentIndexChanged.connect(self.function_changed)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.controls.setEnabled(False)
        self.mode_changed()
        if autoload:
            QTimer.singleShot(0, self.load)

    def load(self):
        if self.closed:
            return
        self.directory = tempfile.TemporaryDirectory(prefix="chromatogram-ms-")
        self.loader.start("inspect", "ms-detail", self.source_trace.source, self.directory.name)

    def loaded(self, key):
        try:
            self.set_functions(read_ms_result(self.directory.name))
        except Exception as exc:
            self.load_failed(str(exc))
        finally:
            self.release_loader()

    def release_loader(self):
        self.loader.stop()
        if self.directory is not None:
            self.directory.cleanup()
            self.directory = None

    def load_failed(self, detail):
        self.status.setText("Could not load mass channels: " + detail)
        self.controls.setEnabled(False)
        self.create_button.setEnabled(False)
        self.release_loader()

    def set_functions(self, functions):
        if not functions:
            raise ValueError("No usable MS functions.")
        self.functions = functions
        blocker = QSignalBlocker(self.function)
        self.function.clear()
        for function in functions:
            self.function.addItem(function.name)
        index = next((i for i, f in enumerate(functions) if f.name == self.source_trace.function), 0)
        self.function.setCurrentIndex(index)
        del blocker
        self.controls.setEnabled(True)
        self.function_changed()

    def function_changed(self, *args):
        if not self.functions:
            return
        function = self.functions[self.function.currentIndex()]
        self.start.setText(repr(float(function.time[0])))
        self.end.setText(repr(float(function.time[-1])))
        self.mz.setText(f"{min(max(91, function.masses[0]), function.masses[-1]):g}")
        self.update_preview()

    def mode_changed(self, *args):
        mode = self.mode.currentData()
        self.input_rows[1][0].setText("Time (min)" if mode == "single" else "From (min)")
        for (label, editor), shown in zip(self.input_rows, (mode == "eic", mode in ("single", "mean"), mode == "mean")):
            label.setVisible(shown)
            editor.setVisible(shown)
        self.method.setText({"tic": "Sum of all recorded mass channels per scan.",
                             "eic": "Extract the nearest recorded mass channel. No mass window or interpolation.",
                             "single": "Use the nearest recorded scan to the requested time.",
                             "mean": "Average scans inside From–To, including both endpoints. Every scan has equal weight."}[mode] +
                            "\n\nOriginal counts; no smoothing or normalization.")
        self.update_preview()

    def invalidate(self, *args):
        self.create_button.setEnabled(False)
        if self.functions:
            self.status.setText("Selection changed — update the preview before creating a report.")

    def update_preview(self):
        if not self.functions or self.closed:
            return False
        function = self.functions[self.function.currentIndex()]
        mode = self.mode.currentData()
        try:
            if mode == "tic":
                trace = ms_tic(function)
            elif mode == "eic":
                trace = ms_eic(function, float(self.mz.text()))
            else:
                trace = ms_spectrum(function, float(self.start.text()), float(self.end.text()) if mode == "mean" else None)
            if "sample_list" in self.source_trace.metadata:
                trace = replace(trace, metadata={**trace.metadata, "sample_list": self.source_trace.metadata["sample_list"]})
            self.trace, self.state = trace, FigureState.report(trace)
            self.status.setText(f"{len(function.time):,} scans · {function.time[0]:.6g}–{function.time[-1]:.6g} min · "
                                f"m/z {function.masses[0]:g}–{function.masses[-1]:g}")
            self.selection_info.setText("\n".join(trace.transformations + trace.warnings))
            self.create_button.setEnabled(True)
            self.redraw()
            return True
        except ValueError as exc:
            detail = str(exc)
            if "could not convert string" in detail:
                detail = "Enter a numeric value in each visible field."
            self.status.setText(detail)
            self.create_button.setEnabled(False)
            return False

    def redraw(self):
        if self.closed or self.trace is None:
            return
        settings = self.state.settings
        available = self.viewport.viewport().size()
        scale = min(max(220, available.width() - 20) / settings.width_mm,
                    max(150, available.height() - 20) / settings.height_mm)
        width, height = round(settings.width_mm * scale), round(settings.height_mm * scale)
        self.canvas.setFixedSize(width, height)
        self.canvas.figure.set_dpi(width * self.canvas.devicePixelRatioF() / (settings.width_mm / 25.4))
        render_figure(self.trace, self.state, self.canvas.figure)
        dpi = self.canvas.figure.dpi / self.canvas.devicePixelRatioF()
        self.canvas.figure.set_size_inches(width / dpi, height / dpi, forward=False)
        self.canvas.draw_idle()

    def create_report(self):
        if self.create_button.isEnabled() and self.trace is not None:
            self.report_requested.emit(self.trace)
            self.accept()

    def done(self, result):
        self.shutdown()
        super().done(result)

    def shutdown(self):
        self.closed = True
        self.viewport.timer.stop()
        self.release_loader()
        self.functions.clear()
