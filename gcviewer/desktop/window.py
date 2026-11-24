"""Qt desktop workspace. All scientific state lives outside widgets."""
from dataclasses import dataclass, replace
from pathlib import Path
import tempfile
import uuid

from PySide6.QtCore import Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QTabWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter, QToolButton, QVBoxLayout, QWidget
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

from gcviewer.figures.workspace import FigureSettings, FigureState, export_figure, export_paths, render_figure, figure_typography, is_comparison, source_traces
from gcviewer.services.worker import read_result, read_fid_result, write_record
from gcviewer.desktop.loading import LoadService
from gcviewer.desktop.sample_list import SampleList, SampleDelegate, DETAIL_ROLE, STATUS_ROLE
from gcviewer.figures.styles import FIGURE_STYLES, figure_size_presets
from gcviewer.figures.axis_breaks import view_limits
from gcviewer.desktop.axis_break_controls import AxisBreakControls
from gcviewer.analysis.processing import display_signal, processing_summary, signal_axis_label


FIGURE_SIZE_PRESETS = figure_size_presets()


@dataclass
class Sample:
    trace: object
    state: FigureState
    fid_run: object = None
    fid_document: object = None


@dataclass
class LoadRequest:
    path: str
    kind: str
    list_metadata: dict
    origin_key: str = ""


class ReportToolbar(NavigationToolbar2QT):
    toolitems = tuple(item for item in NavigationToolbar2QT.toolitems if item[0] in ("Home", "Pan", "Zoom"))

    def __init__(self, canvas, window):
        self.window = window
        self.interaction_axes = None
        super().__init__(canvas, window, coordinates=False)
        self._actions["home"].setToolTip("Show the full trace and remove axis breaks")
        for name in ("pan", "zoom"):
            self._actions[name].setToolTip("With axis breaks, adjust the outer limits of the selected section; break boundaries stay fixed.")

    def pan(self, *args):
        self.window.annotate.setChecked(False)
        super().pan(*args)

    def zoom(self, *args):
        self.window.annotate.setChecked(False)
        super().zoom(*args)

    def home(self, *args):
        sample = self.window.active
        if sample:
            sample.state.settings.x_range = sample.state.settings.y_range = None
            sample.state.settings.x_break = sample.state.settings.y_break = None
            self.window.error.clear()
            self.window.populate_settings()
            self.window.redraw()

    def press_pan(self, event):
        self.interaction_axes = event.inaxes
        super().press_pan(event)

    def press_zoom(self, event):
        self.interaction_axes = event.inaxes
        super().press_zoom(event)

    def release_pan(self, event):
        super().release_pan(event)
        if self.interaction_axes is not None:
            self.window.capture_view(self.interaction_axes)
        self.interaction_axes = None

    def release_zoom(self, event):
        super().release_zoom(event)
        if self.interaction_axes is not None:
            self.window.capture_view(self.interaction_axes)
        self.interaction_axes = None


class FigureViewport(QScrollArea):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(window.redraw)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.timer.start(60)


class Workspace(QMainWindow):
    def __init__(self, preferences=None):
        super().__init__()
        from gcviewer.desktop.appearance import ensure_ui_font
        ensure_ui_font()
        self.setWindowTitle("Chromatogram Viewer")
        self.resize(1280, 820)
        self.setMinimumSize(920, 600)
        self.samples = {}
        self.jobs = {}
        self.pending = {}
        self.requests = {}
        self.failures = {}
        self.loader = LoadService(self)
        self.loader.completed.connect(self.finish_load)
        self.loader.failed.connect(self.service_failed)
        self.library_dialog = None
        self.inspector = None
        self.max_loaders = 1
        self._closing = False
        self._drag = None
        self.artists = []
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        self.setCentralWidget(root)
        self.figure_export_action = QAction("Figure…", self)
        self.figure_export_action.triggered.connect(self.save_figure)
        splitter = self.splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        left = self.sample_panel = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        sample_heading = QHBoxLayout()
        sample_heading.addWidget(QLabel("<b>Samples</b>"), 1)
        add = QPushButton("Add…")
        add.clicked.connect(self.open_library)
        sample_heading.addWidget(add)
        left_layout.addLayout(sample_heading)
        self.sample_search = QLineEdit()
        self.sample_search.setPlaceholderText("Find an opened sample…")
        self.sample_search.setClearButtonEnabled(True)
        self.sample_search.textChanged.connect(self.filter_samples)
        left_layout.addWidget(self.sample_search)
        self.compare_action = QAction("Compare samples…", self)
        self.compare_action.setToolTip("Create an overlay or stacked report from loaded chromatograms")
        self.compare_action.triggered.connect(self.open_comparison)
        self.sample_list = SampleList()
        self.sample_list.setMinimumWidth(195)
        self.sample_list.setItemDelegate(SampleDelegate(self.sample_list))
        self.sample_list.setSpacing(0)
        self.sample_list.setUniformItemSizes(True)
        self.sample_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.sample_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sample_list.currentItemChanged.connect(self.select_sample)
        self.sample_list.interactionFinished.connect(self.select_sample)
        self.sample_list.itemSelectionChanged.connect(self.update_selected_actions)
        left_layout.addWidget(self.sample_list, 1)
        self.integrate_selected_action = QAction("Integrate selected…", self)
        self.integrate_selected_action.setToolTip('Integrate selected FID samples using the active sample’s method and naming rules.')
        self.integrate_selected_action.triggered.connect(self.integrate_selected)
        self.queue_status = QLabel()
        self.queue_status.setWordWrap(True)
        left_layout.addWidget(self.queue_status)
        actions = QHBoxLayout()
        self.remove_button = QPushButton("Remove")
        self.remove_button.setToolTip("Remove selected samples from this session, or cancel their pending loads. Source files stay unchanged.")
        self.remove_button.clicked.connect(self.remove_sample)
        actions.addWidget(self.remove_button)
        self.retry_button = QPushButton("Retry")
        self.retry_button.clicked.connect(self.retry_selected)
        actions.addWidget(self.retry_button)
        left_layout.addLayout(actions)
        self.details_toggle = QToolButton()
        self.details_toggle.setText("Sample details")
        self.details_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.details_toggle.setCheckable(True)
        self.details_toggle.toggled.connect(self.toggle_details)
        left_layout.addWidget(self.details_toggle)
        self.source_info = QLabel()
        self.source_info.hide()
        self.source_info.setWordWrap(True)
        self.source_info.setTextFormat(Qt.TextFormat.PlainText)
        self.source_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        left_layout.addWidget(self.source_info)
        splitter.addWidget(left)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        self.active_title = QLabel()
        self.active_title.setWordWrap(True)
        self.active_title.setTextFormat(Qt.TextFormat.PlainText)
        active_row = QHBoxLayout()
        active_row.addWidget(self.active_title, 1)
        self.inspect_action = QAction("GC-MS inspection / EIC…", self)
        self.inspect_action.triggered.connect(self.open_inspector)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        self.canvas = FigureCanvasQTAgg(Figure())
        self.viewport = FigureViewport(self)
        self.viewport.setWidget(self.canvas)
        tools = QHBoxLayout()
        self.annotate = QCheckBox("Annotate")
        self.annotate.setChecked(True)
        self.annotate.toggled.connect(self.annotation_mode)
        self.toolbar = ReportToolbar(self.canvas, self)
        tools.addWidget(self.toolbar)
        tools.addWidget(self.annotate)
        tools.addStretch()
        self.data_export_action = QAction("Trace data…", self)
        self.data_export_action.setToolTip("Export all original trace values as CSV. Figure smoothing/normalization are recorded in metadata but do not change these values.")
        self.data_export_action.triggered.connect(self.save_data)
        center_layout.addWidget(self.viewport, 1)
        center_layout.addLayout(tools)
        center_layout.addLayout(active_row)
        center_layout.addWidget(self.notice)
        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.addTab(center, "Figure")
        from gcviewer.desktop.fid_analysis import AnalysisPanel
        self.fid_analysis = AnalysisPanel(self, sources=lambda: tuple(
            trace.source for sample in self.samples.values() for trace in source_traces(sample.trace) if not trace.synthetic),
            runs=lambda: tuple(sample.fid_run for sample in self.ordered_fid_samples()),
            selected_runs=lambda: tuple(sample.fid_run for sample in self.ordered_fid_samples(selected=True)))
        self.workspace_tabs.addTab(self.fid_analysis, "FID Analysis")
        self.workspace_tabs.setTabEnabled(1, False)
        splitter.addWidget(self.workspace_tabs)
        self.workspace_tabs.currentChanged.connect(self.change_workspace)
        splitter.setStretchFactor(1, 1)
        for event, callback in (("button_press_event", self.press), ("motion_notify_event", self.motion), ("button_release_event", self.release)):
            self.canvas.mpl_connect(event, callback)
        from gcviewer.desktop.workspace_layout import WorkspaceLayout
        self.layout_controller = WorkspaceLayout(self, preferences)
        self.select_sample()
        self.update_queue_status()
        self.layout_controller.sync()

    @property
    def active_key(self):
        item = self.sample_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def change_workspace(self, index):
        if hasattr(self, 'layout_controller'):
            self.layout_controller.sync()
        QTimer.singleShot(0, self.redraw if index == 0 else self.fid_analysis.draw)

    @property
    def active(self):
        return self.samples.get(self.active_key)

    def make_settings(self, forms, pages):
        form = forms["Style"]
        self.fields = {}
        self.figure_style = QComboBox()
        for key, spec in FIGURE_STYLES.items():
            self.figure_style.addItem(spec.label, key)
        self.figure_style.activated.connect(self.choose_figure_style)
        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Style"))
        style_row.addWidget(self.figure_style, 1)
        form.addRow(style_row)
        self.size_preset = QComboBox()
        self.size_preset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.size_preset.setMinimumContentsLength(15)
        for label, dimensions in FIGURE_SIZE_PRESETS:
            self.size_preset.addItem(label, dimensions)
        self.size_preset.activated.connect(self.choose_figure_size)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Size"))
        size_row.addWidget(self.size_preset, 1)
        form.addRow(size_row)
        for key, label in (("title", "Title"), ("x_label", "X axis"), ("y_label", "Signal axis")):
            editor = QLineEdit()
            self.fields[key] = editor
            forms["Style" if key == "title" else "Axes"].addRow(label, editor)
        self.font_family = QComboBox()
        self.font_family.addItems(("Arial", "Helvetica", "DejaVu Sans", "Times New Roman"))
        forms["Advanced"].addRow("Font", self.font_family)
        self.auto_font_size = QCheckBox("Auto text size")
        self.auto_font_size.setToolTip("General adapts within 7–10 pt; journal styles keep 8 pt across layouts. Turn off to set your own point size.")
        self.auto_font_size.toggled.connect(self.change_auto_text_size)
        forms["Advanced"].addRow(self.auto_font_size)
        for key, label, lo, hi, decimals in (("width_mm", "Width (mm)", 80, 300, 1), ("height_mm", "Height (mm)", 40, 250, 1),
                ("font_size", "Font (pt)", 6, 24, 1), ("line_width", "Line (pt)", .2, 5, 1), ("dpi", "Raster DPI", 72, 1200, 0)):
            editor = QDoubleSpinBox()
            editor.setRange(lo, hi)
            editor.setDecimals(decimals)
            self.fields[key] = editor
            forms["Advanced" if key in ("font_size", "dpi") else "Style"].addRow(label, editor)
            if key in ("width_mm", "height_mm"):
                editor.setKeyboardTracking(False)
                editor.valueChanged.connect(self.apply_figure_size)
        self.color = QComboBox()
        for label, color in (("Graphite", "#20252b"), ("Blue", "#205b91"), ("Burgundy", "#8c3a4b"), ("Green", "#30705b")):
            self.color.addItem(label, color)
        form.addRow("Trace", self.color)
        self.y_numbers = QComboBox()
        for label, value in (("Readable units", "readable"), ("Scientific notation", "scientific"), ("Full numbers", "plain")):
            self.y_numbers.addItem(label, value)
        forms["Axes"].addRow("Axis numbers", self.y_numbers)
        for key, label in (("x_range", "X min, max"), ("y_range", "Signal min, max")):
            editor = QLineEdit()
            editor.setPlaceholderText("Auto — leave blank")
            self.fields[key] = editor
            forms["Axes"].addRow(label, editor)
        self.break_controls = AxisBreakControls()
        self.break_controls.remove_requested.connect(self.remove_breaks)
        self.break_status = self.break_controls.status
        forms["Axes"].addRow(self.break_controls)
        apply = QPushButton("Apply to figure")
        apply.clicked.connect(self.apply_settings)
        forms["Actions"].addRow(apply)
        reset = QPushButton("Reset report + labels")
        reset.clicked.connect(self.reset_report)
        forms["Actions"].addRow(reset)
        guide = QPushButton("Figure guidelines…")
        guide.clicked.connect(self.show_figure_guidelines)
        forms["Actions"].addRow(guide)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #a52a2a;")
        forms["Actions"].addRow(self.error)
        self.comparison_controls = QGroupBox("Comparison")
        comparison_form = QFormLayout(self.comparison_controls)
        self.comparison_mode = QComboBox()
        self.comparison_mode.addItem("Overlay", "overlay")
        self.comparison_mode.addItem("Stacked · shared scale", "stacked")
        self.comparison_mode.activated.connect(self.change_comparison_mode)
        comparison_form.addRow("View", self.comparison_mode)
        self.comparison_trace = QComboBox()
        self.comparison_trace.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.comparison_trace.setMinimumContentsLength(14)
        self.comparison_trace.currentIndexChanged.connect(self.populate_trace_controls)
        comparison_form.addRow("Trace", self.comparison_trace)
        self.comparison_name = QLineEdit()
        self.comparison_name.editingFinished.connect(self.rename_comparison_trace)
        comparison_form.addRow("Label", self.comparison_name)
        self.comparison_color = QPushButton("Choose color…")
        self.comparison_color.clicked.connect(self.choose_comparison_color)
        comparison_form.addRow("Color", self.comparison_color)
        note = QLabel("All traces share time and signal scales. Signal processing applies to each trace independently; no alignment.")
        note.setWordWrap(True)
        comparison_form.addRow(note)
        pages["Traces"].insertWidget(0, self.comparison_controls)
        processing = self.processing_group = QGroupBox("Signal processing")
        processing_form = QFormLayout(processing)
        self.signal_scale = QComboBox()
        self.signal_scale.addItem("Original units", False)
        self.signal_scale.addItem("Maximum = 100%", True)
        self.signal_scale.setToolTip("Uses each full trace's maximum after smoothing, regardless of zoom or breaks. Negative values remain negative; all-zero signals remain zero.")
        self.signal_scale.activated.connect(self.change_processing)
        processing_form.addRow("Scale", self.signal_scale)
        self.smoothing = QComboBox()
        self.smoothing.addItem("Off", 1)
        for window in range(3, 22, 2):
            self.smoothing.addItem(f"{window} points", window)
        self.smoothing.setToolTip("Centered moving average; edges use only available samples. Window is measured in points, not minutes. Chromatograms only.")
        self.smoothing.activated.connect(self.change_processing)
        processing_form.addRow("Smoothing", self.smoothing)
        self.processing_note = QLabel()
        self.processing_note.setWordWrap(True)
        processing_form.addRow(self.processing_note)
        pages["Style"].insertWidget(pages["Style"].count()-1, processing)
        labels = self.labels_group = QGroupBox("Peak labels")
        label_layout = QVBoxLayout(labels)
        self.auto_labels_button = QPushButton('Automatic labels…')
        self.auto_labels_button.clicked.connect(self.automatic_labels)
        label_layout.addWidget(self.auto_labels_button)
        self.label_list = QListWidget()
        self.label_list.setMaximumHeight(105)
        self.label_list.currentRowChanged.connect(self.select_label)
        label_layout.addWidget(self.label_list)
        self.label_text = QLineEdit()
        self.label_text.setPlaceholderText("Select a label to edit its text")
        self.label_text.returnPressed.connect(self.edit_label)
        label_layout.addWidget(self.label_text)
        self.label_visible = QCheckBox('Show selected label')
        self.label_visible.toggled.connect(self.toggle_label)
        label_layout.addWidget(self.label_visible)
        row = QHBoxLayout()
        for text, action in (("Update", self.edit_label), ("Delete", self.delete_label), ("Clear", self.clear_labels)):
            button = QPushButton(text)
            button.clicked.connect(action)
            row.addWidget(button)
        label_layout.addLayout(row)
        pages["Labels"].insertWidget(0, labels)

    def add_sample(self, trace, key=None, select=True, state=None, fid_run=None):
        key = key or uuid.uuid4().hex
        self.samples[key] = Sample(trace, state or FigureState.report(trace), fid_run)
        item = self.find_item(key)
        if item is None:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.sample_list.addItem(item)
        item.setText(trace.name)
        item.setToolTip(f"{trace.source}\n{trace.function}")
        self.update_queue_status()
        if select:
            self.sample_list.setCurrentItem(item)
        if self.active_key == key:
            self.select_sample()
        return key

    def open_comparison(self):
        from gcviewer.desktop.comparison_dialog import ComparisonDialog
        candidates = [(self.sample_list.item(i).data(Qt.ItemDataRole.UserRole), self.samples[self.sample_list.item(i).data(Qt.ItemDataRole.UserRole)].trace)
                      for i in range(self.sample_list.count()) if self.sample_list.item(i).data(Qt.ItemDataRole.UserRole) in self.samples]
        candidates = [(key, trace) for key, trace in candidates if trace.plot_kind == "line" and trace.x_unit == "min"]
        if len(candidates) < 2:
            self.statusBar().showMessage("Open at least two chromatograms before comparing samples.", 8000)
            return
        dialog = ComparisonDialog(self, candidates, self.active_key)
        if dialog.exec() == QDialog.DialogCode.Accepted and not self._closing:
            self.add_sample(dialog.comparison, state=dialog.state)
            self.statusBar().showMessage("Comparison created. Individual sample reports are unchanged.", 8000)
        dialog.deleteLater()

    def populate_comparison_controls(self):
        enabled = bool(self.active and is_comparison(self.active.trace))
        self.comparison_controls.setVisible(enabled)
        self.color.setEnabled(not enabled)
        self.color.setToolTip("Choose each trace color in Comparison above." if enabled else "")
        if not enabled:
            return
        settings = self.active.state.settings
        self.comparison_mode.setCurrentIndex(self.comparison_mode.findData(settings.comparison_mode))
        index = self.comparison_trace.currentIndex()
        blocker = QSignalBlocker(self.comparison_trace)
        self.comparison_trace.clear()
        self.comparison_trace.addItems(settings.trace_names)
        self.comparison_trace.setCurrentIndex(max(0, min(index, len(settings.trace_names) - 1)))
        blocker.unblock()
        self.populate_trace_controls()

    def populate_trace_controls(self, *args):
        index = self.comparison_trace.currentIndex()
        if not self.active or not is_comparison(self.active.trace) or index < 0:
            return
        s = self.active.state.settings
        self.comparison_name.setText(s.trace_names[index])
        self.comparison_name.setToolTip(self.active.trace.traces[index].source)
        self.comparison_color.setText(f"Trace color… {s.trace_colors[index]}")

    def rename_comparison_trace(self):
        if not self.active or not is_comparison(self.active.trace):
            return
        index = self.comparison_trace.currentIndex()
        if index < 0:
            return
        names = list(self.active.state.settings.trace_names)
        names[index] = self.comparison_name.text().strip()
        settings = replace(self.active.state.settings, trace_names=tuple(names))
        try:
            settings.validate(self.active.trace)
        except ValueError as exc:
            self.error.setText(str(exc))
            self.populate_trace_controls()
            return
        self.active.state.settings = settings
        self.comparison_trace.setItemText(index, names[index])
        self.error.clear()
        self.redraw()

    def choose_comparison_color(self):
        if not self.active or not is_comparison(self.active.trace):
            return
        from PySide6.QtGui import QColor
        index = self.comparison_trace.currentIndex()
        colors = list(self.active.state.settings.trace_colors)
        color = QColorDialog.getColor(QColor(colors[index]), self, "Choose trace color")
        if color.isValid():
            colors[index] = color.name()
            self.active.state.settings = replace(self.active.state.settings, trace_colors=tuple(colors))
            self.populate_trace_controls()
            self.redraw()

    def change_comparison_mode(self, index):
        if not self.active or not is_comparison(self.active.trace):
            return
        settings = replace(self.active.state.settings, comparison_mode=self.comparison_mode.itemData(index))
        from gcviewer.figures.comparisons import fitted_settings
        try:
            settings = fitted_settings(self.active.trace, settings)
        except ValueError as exc:
            self.error.setText(str(exc))
            self.populate_comparison_controls()
            return
        self.active.state.settings = settings
        self.populate_settings()
        self.error.clear()
        self.redraw()

    def find_item(self, key):
        return next((self.sample_list.item(i) for i in range(self.sample_list.count())
                     if self.sample_list.item(i).data(Qt.ItemDataRole.UserRole) == key), None)

    def ordered_fid_samples(self, *, selected=False):
        result = []
        for row in range(self.sample_list.count()):
            item = self.sample_list.item(row)
            sample = self.samples.get(item.data(Qt.ItemDataRole.UserRole))
            if sample and sample.fid_run is not None and (not selected or (item.isSelected() and not item.isHidden())):
                result.append(sample)
        return result

    def update_selected_actions(self):
        if not hasattr(self, 'fid_analysis') or self.sample_list.selection_interaction:
            return
        count = len(self.ordered_fid_samples(selected=True))
        selected = len([item for item in self.sample_list.selectedItems() if not item.isHidden()])
        self.remove_button.setText(f'Remove ({selected})' if selected else 'Remove')
        self.remove_button.setEnabled(bool(selected))
        self.integrate_selected_action.setText(f'Integrate selected ({count})…' if count else 'Integrate selected…')
        self.integrate_selected_action.setEnabled(bool(count and self.active and self.active.fid_run is not None))

    def integrate_selected(self):
        panel = self.fid_analysis
        if panel.document is None or panel.busy:
            self.statusBar().showMessage('Finish or cancel the current integration first.', 6000)
            return
        try:
            from gcviewer.desktop.fid_selection import SelectedIntegrationDialog
            dialog = SelectedIntegrationDialog(self.ordered_fid_samples(selected=True), panel.method_value(),
                                               panel.sample.fid_run.path.name, self)
            dialog.exec()
            panel.document = panel.sample.fid_document
            panel.fill()
            panel.show_result()
            panel.refresh_enabled()
            self.workspace_tabs.setCurrentIndex(1)
        except Exception as exc:
            QMessageBox.warning(self, 'Selected integration', str(exc))

    def select_sample(self, *args):
        if self.sample_list.selection_interaction:
            return
        if self.active_key in self.pending:
            request = self.pending.pop(self.active_key)
            self.pending = {self.active_key: request, **self.pending}
            self.update_queue_status()
        self.remove_button.setEnabled(self.active_key is not None)
        self.retry_button.setEnabled(self.active_key in self.failures)
        self._drag = None
        self.error.clear()
        sample = self.active
        fid = bool(sample and sample.fid_run is not None)
        self.workspace_tabs.setTabEnabled(1, fid)
        if not fid:
            self.workspace_tabs.setCurrentIndex(0)
        self.fid_analysis.bind(sample)
        self.update_selected_actions()
        self.auto_labels_button.setEnabled(bool(sample and sample.trace.x_unit == 'min' and sample.trace.plot_kind in ('line', 'comparison')))
        self.inspect_action.setEnabled(bool(sample and not is_comparison(sample.trace) and sample.trace.instrument == "GC-MS" and not sample.trace.synthetic))
        self.data_export_action.setEnabled(sample is not None)
        self.figure_export_action.setEnabled(sample is not None)
        self.toolbar.setEnabled(sample is not None)
        self.annotate.setEnabled(sample is not None)
        self.layout_controller.figure_page.setEnabled(sample is not None)
        self.populate_comparison_controls()
        if not sample:
            self.refresh_labels()
            self.draw_empty()
            if self.active_key in self.failures:
                title = "Acquisition could not be opened. Retry or remove this sample."
            elif self.active_key in self.jobs:
                title = "Loading acquisition…"
            elif self.active_key in self.pending:
                title = "Up next — this sample will load after the current acquisition."
            else:
                title = "Open an acquisition to begin."
            self.active_title.setText(title)
            self.set_notice(self.failures.get(self.active_key, ""))
            self.source_info.clear()
            self.artists = []
            return
        trace = sample.trace
        self.active_title.setText(("Comparison" if is_comparison(trace) else "Figure") + " · " + trace.name + (f"  /  {trace.function}" if trace.function else ""))
        self.active_title.setToolTip(trace.source)
        self.set_notice("\n".join(trace.warnings or trace.transformations))
        traces = source_traces(trace)
        self.source_info.setText(f"{trace.instrument}\n{sum(len(t.time) for t in traces):,} points\n" + "\n".join(
            f"{i + 1}. {t.name}: {t.time[0]:g}–{t.time[-1]:g} {t.x_unit}" for i, t in enumerate(traces)))
        if sample.fid_run is not None:
            run = sample.fid_run
            self.source_info.setText(self.source_info.text() +
                f"\n{run.header.sample_name}\nVial {run.header.vial} · channel {run.header.channel}\n"
                f"{run.rate_hz:g} Hz · calibrated µV\nOriginal counts retained · tcfid {trace.metadata['fid_acquisition']['parser_version']}")
        if trace.metadata.get("sample_list"):
            row = trace.metadata["sample_list"]["row"]
            self.source_info.setText(self.source_info.text() + f"\nSPL row {row['index']} · vial {row['vial']}\n{row['sample_type']}\n{row['description']}")
        self.populate_settings()
        self.refresh_labels()
        self.redraw()

    def populate_settings(self):
        if not self.active:
            return
        settings = self.active.state.settings
        self.break_controls.set_x_quantity(self.active.trace.x_label)
        for key, editor in self.fields.items():
            value = getattr(settings, key)
            if isinstance(editor, QDoubleSpinBox):
                blocker = QSignalBlocker(editor)
                editor.setValue(value)
                blocker.unblock()
            elif key.endswith("_range"):
                editor.setText("" if value is None else f"{value[0]:.9g}, {value[1]:.9g}")
                editor.setCursorPosition(0)
            else:
                editor.setText(value)
                editor.setCursorPosition(0)
        for key in ("x_break", "y_break"):
            self.break_controls.set_interval(key, getattr(settings, key))
        self.color.setCurrentIndex(max(0, self.color.findData(settings.color)))
        self.y_numbers.setCurrentIndex(self.y_numbers.findData(settings.y_numbers))
        self.font_family.setCurrentText(settings.font_family)
        self.figure_style.setCurrentIndex(self.figure_style.findData(settings.publication_style))
        self.refresh_size_presets()
        self.sync_text_size()
        self.sync_figure_size()
        self.populate_comparison_controls()
        self.signal_scale.setCurrentIndex(self.signal_scale.findData(settings.normalize))
        self.signal_scale.setItemText(1, "Base peak = 100%" if self.active.trace.plot_kind == "sticks" else "Maximum = 100%")
        self.smoothing.setCurrentIndex(self.smoothing.findData(settings.smoothing_window))
        self.smoothing.setEnabled(self.active.trace.plot_kind != "sticks")
        self.fields["y_label"].setEnabled(not settings.normalize)
        if settings.normalize:
            self.fields["y_label"].setText(signal_axis_label(self.active.trace, settings))
        fid = self.active.trace.instrument == "GC-FID" and self.active.trace.y_label == "Response (µV)"
        self.break_controls.set_y_quantity(settings.normalize, settings.smoothing_window > 1, units="µV" if fid else None)
        self.fields["y_range"].setToolTip("Percent of the full-trace maximum." if settings.normalize else
            ("Enter µV (1000 µV = 1 mV on the readable axis)." if fid else "Signal units before tick-label scaling."))
        self.processing_note.setText(processing_summary(self.active.trace, settings) +
                                    "\nChanges reset Y limits and the Y break. Original data is retained.")

    def change_processing(self, *args):
        if not self.active:
            return
        old = self.active.state.settings
        normalized = self.signal_scale.currentData()
        window = self.smoothing.currentData()
        if (old.normalize, old.smoothing_window) == (normalized, window):
            return
        settings = replace(old, normalize=normalized, smoothing_window=window, y_range=None, y_break=None)
        try:
            settings.validate(self.active.trace)
        except ValueError as exc:
            self.populate_settings()
            self.error.setText(str(exc))
            return
        self.active.state.settings = settings
        self._drag = None
        self.populate_settings()
        self.error.clear()
        self.redraw()
        self.statusBar().showMessage("Processing updated; Y limits are automatic and the Y break has been removed.", 8000)

    def sync_text_size(self):
        settings = self.active.state.settings
        blocker = QSignalBlocker(self.auto_font_size)
        self.auto_font_size.setChecked(settings.auto_font_size)
        blocker.unblock()
        typography = figure_typography(settings)
        editor = self.fields["font_size"]
        editor.setEnabled(not settings.auto_font_size)
        editor.setValue(typography["font_size_pt"])
        editor.setToolTip("Actual lettering size in the exported figure. Turn off Auto text size to edit.")
        self.font_family.setToolTip(f"Rendered font: {typography['font_family']}. PDF embeds it; SVG requires it in the viewing application.")

    def change_auto_text_size(self, enabled):
        if not self.active:
            return
        settings = replace(self.active.state.settings, auto_font_size=enabled,
                           font_size=self.fields["font_size"].value())
        try:
            settings.validate(self.active.trace)
        except ValueError as exc:
            self.error.setText(str(exc))
            self.sync_text_size()
            return
        self.active.state.settings = settings
        self.sync_text_size()
        self.redraw()

    def sync_figure_size(self):
        dimensions = (self.fields["width_mm"].value(), self.fields["height_mm"].value())
        index = next((i for i in range(self.size_preset.count()) if self.size_preset.itemData(i) == dimensions), 0)
        self.size_preset.setCurrentIndex(index)
        self.size_preset.setToolTip(f"{dimensions[0]:g} × {dimensions[1]:g} mm · {dimensions[0] / dimensions[1]:.2f}:1\n"
                                   "Preview fits the window; export keeps these physical dimensions.")

    def refresh_size_presets(self):
        self.size_preset.clear()
        for label, dimensions in figure_size_presets(self.active.state.settings.publication_style):
            self.size_preset.addItem(label, dimensions)

    def choose_figure_style(self, index):
        if not self.active:
            return
        key = self.figure_style.itemData(index)
        spec = FIGURE_STYLES[key]
        layout_index = self.size_preset.currentIndex()
        settings = replace(self.active.state.settings, publication_style=key, font_family="Arial",
                           auto_font_size=True, font_size=spec.text_pt or 10,
                           dpi=spec.raster_dpi, line_width=1)
        dimensions = figure_size_presets(key)[layout_index][1]
        if dimensions:
            settings.width_mm, settings.height_mm = dimensions
        try:
            settings.validate(self.active.trace)
        except ValueError as exc:
            self.error.setText(str(exc))
            self.figure_style.setCurrentIndex(self.figure_style.findData(self.active.state.settings.publication_style))
            return
        self.active.state.settings = settings
        for name in ("width_mm", "height_mm", "dpi", "line_width"):
            blocker = QSignalBlocker(self.fields[name])
            self.fields[name].setValue(getattr(settings, name))
            blocker.unblock()
        self.font_family.setCurrentText(settings.font_family)
        self.refresh_size_presets()
        self.sync_figure_size()
        self.sync_text_size()
        self.error.clear()
        self.redraw()

    def show_figure_guidelines(self):
        spec = FIGURE_STYLES[self.figure_style.currentData()]
        QMessageBox.information(self, spec.label + " — figure guidelines", spec.guidance + "\n\nSource: " + spec.source_url)

    def choose_figure_size(self, index):
        dimensions = self.size_preset.itemData(index)
        if dimensions is None:
            self.fields["width_mm"].setFocus()
            self.fields["width_mm"].selectAll()
            return
        for name, value in zip(("width_mm", "height_mm"), dimensions):
            blocker = QSignalBlocker(self.fields[name])
            self.fields[name].setValue(value)
            blocker.unblock()
        self.apply_figure_size()

    def apply_figure_size(self, *args):
        if not self.active:
            return
        self.sync_figure_size()
        settings = replace(self.active.state.settings,
                           width_mm=self.fields["width_mm"].value(), height_mm=self.fields["height_mm"].value())
        try:
            settings.validate(self.active.trace)
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.active.state.settings = settings
        if settings.auto_font_size:
            self.sync_text_size()
        self.error.clear()
        self.redraw()

    def apply_settings(self):
        if not self.active:
            return False
        try:
            values = {}
            for key, editor in self.fields.items():
                if isinstance(editor, QDoubleSpinBox):
                    values[key] = editor.value()
                elif key.endswith("_range"):
                    raw = editor.text().strip()
                    try:
                        values[key] = tuple(float(v.strip()) for v in raw.split(",")) if raw else None
                    except ValueError:
                        raise ValueError("Ranges need two numbers separated by a comma; leave blank for Auto.") from None
                else:
                    values[key] = editor.text()
            if self.active.state.settings.normalize:
                values["y_label"] = self.active.state.settings.y_label
            values["dpi"] = int(values["dpi"])
            values["color"] = self.color.currentData()
            values["y_numbers"] = self.y_numbers.currentData()
            values["font_family"] = self.font_family.currentText()
            values["auto_font_size"] = self.auto_font_size.isChecked()
            values.update(self.break_controls.values())
            settings = replace(self.active.state.settings, **values)
            settings.validate(self.active.trace)
        except ValueError as exc:
            self.error.setText(str(exc))
            return False
        self.active.state.settings = settings
        self.sync_text_size()
        self.error.clear()
        self.redraw()
        return True

    def fit_canvas(self, s):
        available = self.viewport.viewport().size()
        scale = min(max(220, available.width() - 20) / s.width_mm,
                    max(150, available.height() - 20) / s.height_mm)
        width, height = round(s.width_mm * scale), round(s.height_mm * scale)
        self.canvas.setFixedSize(width, height)
        self.canvas.figure.set_dpi(width * self.canvas.devicePixelRatioF() / (s.width_mm / 25.4))
        return width, height

    def draw_empty(self):
        from PySide6.QtGui import QPalette
        s = FigureSettings()
        width, height = self.fit_canvas(s)
        fig = self.canvas.figure
        fig.clear()
        fig.set_facecolor(self.palette().color(QPalette.ColorRole.Base).name())
        pixels_per_inch = fig.dpi / self.canvas.devicePixelRatioF()
        fig.set_size_inches(width / pixels_per_inch, height / pixels_per_inch, forward=False)
        if self.active_key is None:
            fig.text(.5, .5, "Open your data to begin\n\nUse the Open menu to choose acquisitions or the sample library",
                     ha='center', va='center', fontsize=10,
                     color=self.palette().color(QPalette.ColorRole.Text).name())
        self.canvas.draw_idle()

    def redraw(self):
        if self._closing:
            return
        if not self.active:
            self.draw_empty()
            return
        s = self.active.state.settings
        notes = list(self.active.trace.warnings)
        if not notes and self.active.trace.transformations:
            notes.append("Source trace: " + " ".join(self.active.trace.transformations))
        if s.normalize or s.smoothing_window > 1:
            notes.append("Figure: " + processing_summary(self.active.trace, s))
        self.set_notice("\n".join(notes))
        width, height = self.fit_canvas(s)
        _, self.axes, self.artists = render_figure(self.active.trace, self.active.state, self.canvas.figure)
        hidden = sum(artist is None for artist in self.artists)
        self.break_status.setText(f"{hidden} label(s) hidden or outside the retained view." if hidden else "")
        self.break_status.setVisible(bool(hidden))
        for index, artist in enumerate(self.artists):
            item = self.label_list.item(index)
            if item is not None:
                item.setToolTip("Hidden by Show selected label, or outside the retained view." if artist is None else "")
        pixels_per_inch = self.canvas.figure.dpi / self.canvas.devicePixelRatioF()
        self.canvas.figure.set_size_inches(width / pixels_per_inch, height / pixels_per_inch, forward=False)
        self.canvas.draw_idle()

    def remove_breaks(self):
        if not self.active:
            return
        self.active.state.settings = replace(self.active.state.settings, x_break=None, y_break=None)
        self.break_controls.set_interval("x_break", None)
        self.break_controls.set_interval("y_break", None)
        self.error.clear()
        self.redraw()

    def capture_view(self, axes=None):
        if not self.active:
            return
        axes = axes or self.axes
        if axes not in self.canvas.figure.report_panels:
            return
        old = self.active.state.settings
        x_range, y_range = view_limits(self.active.trace, old)
        x, y = tuple(axes.get_xlim()), tuple(axes.get_ylim())
        if old.x_break:
            x = (x[0], x_range[1]) if axes.report_column == 0 else (x_range[0], x[1])
        if old.y_break:
            y = (y[0], y_range[1]) if axes.report_row == 0 else (y_range[0], y[1])
        settings = replace(old, x_range=x, y_range=y)
        try:
            settings.validate(self.active.trace)
        except ValueError as exc:
            self.error.setText(str(exc))
        else:
            self.active.state.settings = settings
            self.error.clear()
            self.populate_settings()
        self.redraw()

    def annotation_mode(self, enabled):
        if enabled and hasattr(self, "toolbar"):
            if self.toolbar.mode == "pan/zoom":
                NavigationToolbar2QT.pan(self.toolbar)
            elif self.toolbar.mode == "zoom rect":
                NavigationToolbar2QT.zoom(self.toolbar)

    def press(self, event):
        if not self.active or not self.annotate.isChecked() or self.toolbar.mode or event.button != 1:
            return
        for i, artist in reversed(list(enumerate(self.artists))):
            if artist is not None and artist.get_bbox_patch().contains_point((event.x, event.y)):
                self.label_list.setCurrentRow(i)
                self._drag = (self.active_key, i)
                return
        if event.inaxes in self.canvas.figure.report_panels and event.xdata is not None:
            traces = source_traces(self.active.trace)
            signals = [display_signal(trace, self.active.state.settings) for trace in traces]
            candidates = range(len(traces))
            panel_index = getattr(event.inaxes, "report_trace_index", None)
            if panel_index is not None:
                candidates = (panel_index,)
            import numpy as np
            def distance(i):
                trace = traces[i]
                point = int(np.argmin(np.abs(trace.time - event.xdata)))
                x, y = trace.time[point], signals[i][point]
                if not (event.inaxes.get_xlim()[0] <= x <= event.inaxes.get_xlim()[1] and event.inaxes.get_ylim()[0] <= y <= event.inaxes.get_ylim()[1]):
                    return float("inf")
                px, py = event.inaxes.transData.transform((x, y))
                return (px - event.x)**2 + (py - event.y)**2
            trace_index = min(candidates, key=distance)
            label = self.active.state.add_label(self.active.trace, event.xdata, trace_index=trace_index)
            trace = traces[trace_index]
            t, y = trace.time[label.index], signals[trace_index][label.index]
            anchor_axes = next((ax for ax in self.canvas.figure.report_panels if
                               getattr(ax, "report_trace_index", None) in (None, trace_index) and ax.get_xlim()[0] <= t <= ax.get_xlim()[1] and
                               ax.get_ylim()[0] <= y <= ax.get_ylim()[1]), None)
            if anchor_axes is None:
                self.active.state.labels.pop()
                self.statusBar().showMessage("That trace point is outside the visible sections. Choose a visible peak or adjust the break.", 8000)
                return
            if is_comparison(self.active.trace) or self.active.state.settings.x_break or self.active.state.settings.y_break:
                x_fraction = self.canvas.figure.report_label_transform.inverted().transform(anchor_axes.transData.transform((t, y)))[0]
                y_fraction = self.canvas.figure.report_label_transform.inverted().transform(anchor_axes.transAxes.transform((.5, .8)))[1] if is_comparison(self.active.trace) else .8
                label.position = (float(max(.1, min(.9, x_fraction))), float(y_fraction))
            self.refresh_labels(len(self.active.state.labels) - 1)
            self.redraw()

    def motion(self, event):
        if not self._drag or not self.active or self._drag[0] != self.active_key or event.x is None or event.y is None:
            return
        index = self._drag[1]
        position = self.canvas.figure.report_label_transform.inverted().transform((event.x, event.y))
        position = tuple(float(max(.02, min(.98, p))) for p in position)
        self.active.state.labels[index].position = position
        if self.artists[index] is not None:
            self.artists[index].set_position(position)
        self.canvas.draw_idle()

    def release(self, event):
        self._drag = None

    def refresh_labels(self, row=-1):
        self.label_list.clear()
        if self.active:
            for label in self.active.state.labels:
                self.label_list.addItem(label.text)
        self.label_list.setCurrentRow(row)
        if row < 0:
            self.label_text.clear()

    def select_label(self, row):
        blocked = QSignalBlocker(self.label_visible)
        valid = bool(self.active and 0 <= row < len(self.active.state.labels))
        self.label_visible.setEnabled(valid)
        self.label_visible.setChecked(valid and self.active.state.labels[row].visible)
        if self.active and 0 <= row < len(self.active.state.labels):
            self.label_text.setText(self.active.state.labels[row].text)
        else:
            self.label_text.clear()

    def toggle_label(self, visible):
        row = self.label_list.currentRow()
        if self.active and 0 <= row < len(self.active.state.labels):
            self.active.state.labels[row].visible = visible
            self.redraw()

    def automatic_labels(self):
        if self.active is None:
            return
        from gcviewer.desktop.peak_labels import AutomaticLabelsDialog
        from gcviewer.figures.peak_labels import arrange_labels
        from gcviewer.services.fid_workflow import analysis_key
        sample = self.active
        record = None
        if sample.fid_run is not None and sample.fid_document and sample.fid_document.result:
            try:
                method = self.fid_analysis.method_value()
                if sample.fid_document.result['analysis_key'] == analysis_key(sample.fid_run, method):
                    record = sample.fid_document.result
            except ValueError:
                pass
        dialog = AutomaticLabelsDialog(sample.trace, sample.state.settings, record, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        previous = sample.state.labels
        trace_index = dialog.trace_choice.currentData()
        sample.state.labels = [label for label in previous if label.origin != 'automatic' or label.trace_index != trace_index] + dialog.labels
        try:
            crowded = arrange_labels(sample.trace, sample.state, dialog.labels)
        except Exception as exc:
            sample.state.labels = previous
            QMessageBox.warning(self, 'Automatic labels', str(exc))
            return
        self.refresh_labels(len(sample.state.labels) - len(dialog.labels))
        self.redraw()
        message = f'Added {len(dialog.labels)} automatic labels. Use Annotate to drag them; select a label to edit or hide it.'
        if crowded:
            message += f' {crowded} could not fit without overlap; use fewer labels or a larger figure.'
        self.statusBar().showMessage(message, 20000)

    def edit_label(self):
        row = self.label_list.currentRow()
        text = self.label_text.text().strip()
        if self.active and row >= 0 and text:
            self.active.state.labels[row].text = text
            self.refresh_labels(row)
            self.redraw()

    def delete_label(self):
        row = self.label_list.currentRow()
        if self.active and row >= 0:
            del self.active.state.labels[row]
            self.refresh_labels()
            self.redraw()

    def clear_labels(self):
        if self.active:
            self.active.state.labels.clear()
            self.refresh_labels()
            self.redraw()

    def reset_report(self):
        if self.active:
            state = FigureState.report(self.active.trace)
            if is_comparison(self.active.trace):
                from gcviewer.figures.comparisons import fitted_settings
                state.settings = fitted_settings(self.active.trace, state.settings)
            self.active.state = state
            self.select_sample()

    def open_ms(self):
        path = QFileDialog.getExistingDirectory(self, "Select a GC-MS .raw acquisition directory")
        if path:
            self.start_load(path, "ms")

    def open_inspector(self):
        if not self.active or not self.inspect_action.isEnabled():
            return
        if self.inspector is not None:
            self.inspector.raise_()
            return
        from gcviewer.desktop.ms_inspector import MSInspector
        dialog = MSInspector(self, self.active.trace)
        self.inspector = dialog
        dialog.report_requested.connect(self.add_inspection_report)
        dialog.finished.connect(self.inspector_finished)
        dialog.open()

    def add_inspection_report(self, trace):
        self.add_sample(trace)
        self.statusBar().showMessage("Report created. Figure settings, labels and exports are available for this selection.", 10000)

    def inspector_finished(self, *args):
        dialog, self.inspector = self.inspector, None
        if dialog is not None:
            dialog.deleteLater()
        self.pump_queue()

    def open_fid(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select a PENX GC-FID .raw file", "", "PENX acquisitions (*.raw *.RAW)")
        if path:
            self.start_load(path, "fid")

    def open_library(self):
        if self.library_dialog is None:
            from gcviewer.desktop.library_dialog import LibraryDialog
            self.library_dialog = LibraryDialog(self)
            self.library_dialog.open_requested.connect(self.open_library_entries)
        self.library_dialog.show()
        self.library_dialog.raise_()
        self.library_dialog.activateWindow()

    def open_library_entries(self, entries):
        keys = []
        for entry in entries:
            if not entry.available:
                continue
            existing = next((key for key, request in self.requests.items() if request.origin_key == entry.key), None)
            if existing is not None:
                keys.append(existing)
                continue
            keys.append(self.start_load(entry.path, entry.kind, entry.list_metadata, entry.key, select=False))
        if keys:
            self.sample_list.setCurrentItem(self.find_item(keys[0]))
        return keys

    def toggle_details(self, shown):
        self.source_info.setVisible(shown)
        self.details_toggle.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)

    def set_notice(self, text):
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def update_sample_row(self, key):
        item = self.find_item(key)
        if item is None:
            return
        sample, request = self.samples.get(key), self.requests.get(key)
        row = request.list_metadata.get("row", {}) if request else {}
        if sample:
            trace = sample.trace
            name = trace.name
            detail = f"{trace.instrument} · {len(trace.traces)} traces" if is_comparison(trace) else f"{trace.instrument} · {trace.function or 'Chromatogram'}"
        elif request:
            name = Path(request.path).name
            detail = "GC-MS" if request.kind == "ms" else "GC-FID"
        else:
            return
        if row:
            detail = f"Vial {row.get('vial', '—')} · {row.get('description') or detail}"
        if key in self.failures:
            state = "Failed"
        elif key in self.jobs:
            state = "Loading…"
        elif key in self.pending:
            state = "Next" if key == next(iter(self.pending)) else "Queued"
        else:
            state = "Compare" if sample and is_comparison(sample.trace) else ("Demo" if sample and sample.trace.synthetic else "Ready")
        item.setText(name)
        item.setData(DETAIL_ROLE, detail)
        item.setData(STATUS_ROLE, state)
        source = sample.trace.source if sample else request.path
        function = sample.trace.function if sample else ""
        item.setToolTip("\n".join(text for text in (source, detail, function, state) if text))

    def filter_samples(self, *args):
        needle = self.sample_search.text().strip().casefold()
        for i in range(self.sample_list.count()):
            item = self.sample_list.item(i)
            content = " ".join((item.text(), item.data(DETAIL_ROLE) or "", item.data(STATUS_ROLE) or "", item.toolTip())).casefold()
            item.setHidden(bool(needle and needle not in content))
        self.update_selected_actions()

    def service_failed(self, key, detail):
        if key in self.jobs:
            write_record(self.jobs[key][1].name, {"error": detail})
            self.finish_load(key)

    def start_load(self, path, kind, list_metadata=None, origin_key="", select=True):
        key = uuid.uuid4().hex
        item = QListWidgetItem(Path(path).name)
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setToolTip(str(path))
        self.sample_list.addItem(item)
        request = LoadRequest(str(Path(path).resolve()), kind, list_metadata or {}, origin_key)
        self.requests[key] = request
        self.pending[key] = request
        if select:
            self.sample_list.setCurrentItem(item)
        self.pump_queue()
        return key

    def update_queue_status(self):
        ready = len(self.samples)
        self.update_selected_actions()
        self.compare_action.setEnabled(sum(s.trace.plot_kind == "line" and s.trace.x_unit == "min" for s in self.samples.values()) >= 2)
        self.queue_status.setText(f"{ready} open · {len(self.jobs)} loading · {len(self.pending)} waiting" if self.jobs or self.pending else f"{ready} open")
        for i in range(self.sample_list.count()):
            self.update_sample_row(self.sample_list.item(i).data(Qt.ItemDataRole.UserRole))
        self.filter_samples()

    def pump_queue(self):
        if self._closing or self.inspector is not None:
            return
        while self.pending and len(self.jobs) < self.max_loaders:
            key = next(iter(self.pending))
            request = self.pending.pop(key)
            self.launch_request(key, request)
        self.update_queue_status()

    def launch_request(self, key, request):
        item = self.find_item(key)
        if item is None:
            return
        directory = tempfile.TemporaryDirectory(prefix="chromatogram-load-")
        process = self.loader.start(key, request.kind, request.path, directory.name)
        self.jobs[key] = (process, directory)
        if self.active_key == key:
            self.select_sample()

    def finish_load(self, key):
        if key not in self.jobs or self._closing:
            return
        process, directory = self.jobs[key]
        item = self.find_item(key)
        try:
            traces = read_result(directory.name)
            if item is None:
                return
            selected = 0
            if len(traces) > 1:
                choices = [f"{i + 1}. {trace.function} · {len(trace.time):,} scans · {trace.time[0]:g}–{trace.time[-1]:g} min"
                           for i, trace in enumerate(traces)]
                choice, accepted = QInputDialog.getItem(self, "Choose MS function", f"{traces[0].name}\nEligible MS functions (TIC):", choices, 0, False)
                if not accepted:
                    self.sample_list.takeItem(self.sample_list.row(item))
                    return
                selected = choices.index(choice)
            if self._closing or self.find_item(key) is None:
                return
            request = self.requests.get(key)
            trace = traces[selected]
            if request and request.list_metadata:
                trace = replace(trace, metadata={**trace.metadata, "sample_list": request.list_metadata})
            fid_run = read_fid_result(directory.name) if request and request.kind == "fid" else None
            self.add_sample(trace, key=key, select=False, fid_run=fid_run)
            self.statusBar().showMessage(f"Loaded {traces[selected].name}", 8000)
        except Exception as exc:
            detail = str(exc)
            if not (Path(directory.name) / "result.json").exists():
                detail = "The acquisition loader could not finish. " + process.errorString() + "\n" + bytes(process.readAllStandardError()).decode(errors="replace")[-2000:]
            self.failures[key] = detail
            if item is not None:
                if self.active_key == key:
                    self.select_sample()
            request = self.requests.get(key)
            if not request or not request.origin_key:
                QMessageBox.warning(self, "Could not open acquisition", detail)
        finally:
            if key in self.jobs:
                self.jobs.pop(key)
                directory.cleanup()
                if not process.property("persistent_loader"):
                    process.deleteLater()
            if self.find_item(key) is None:
                self.requests.pop(key, None)
            self.update_queue_status()
            QTimer.singleShot(0, self.pump_queue)

    def cancel_job(self, key):
        self.pending.pop(key, None)
        job = self.jobs.pop(key, None)
        if job:
            process, directory = job
            if process.property("persistent_loader"):
                self.loader.stop()
            else:
                process.kill()
                process.waitForFinished(3000)
                process.deleteLater()
            directory.cleanup()
        self.update_queue_status()

    def remove_sample(self):
        keys = [item.data(Qt.ItemDataRole.UserRole) for item in self.sample_list.selectedItems() if not item.isHidden()]
        blocker = QSignalBlocker(self.sample_list)
        for key in keys:
            self.cancel_job(key)
            self.samples.pop(key, None)
            self.requests.pop(key, None)
            self.failures.pop(key, None)
            item = self.find_item(key)
            if item is not None:
                self.sample_list.takeItem(self.sample_list.row(item))
        del blocker
        self.select_sample()
        self.update_queue_status()
        self.pump_queue()

    def retry_selected(self):
        key = self.active_key
        if key in self.failures and key in self.requests:
            self.failures.pop(key)
            self.pending[key] = self.requests[key]
            self.select_sample()
            self.pump_queue()

    def save_figure(self):
        if not self.active or not self.apply_settings():
            return
        import re
        trace, state = self.active.trace, self.active.state
        base = re.sub(r'[^\w.-]+', '_', Path(trace.name).stem + ("_" + trace.function if trace.function else ""))
        path, selected = QFileDialog.getSaveFileName(self, "Export report figure", base + ".pdf", "PDF (*.pdf);;SVG (*.svg);;PNG (*.png);;TIFF (*.tif *.tiff)", options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return
        if not Path(path).suffix:
            path += {"PNG (*.png)": ".png", "PDF (*.pdf)": ".pdf", "SVG (*.svg)": ".svg", "TIFF (*.tif *.tiff)": ".tif"}[selected]
        try:
            target, sidecar = export_paths(path, trace)
            existing = [p.name for p in (target, sidecar) if p.exists()]
            if existing and QMessageBox.question(self, "Replace existing export?", "Replace these files?\n" + "\n".join(existing),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            export_figure(trace, state, target, overwrite=bool(existing))
            self.statusBar().showMessage(f"Saved {target.name} and {sidecar.name}", 15000)
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def save_data(self):
        if not self.active:
            return
        import re
        from gcviewer.reports.numeric import export_csv
        trace = self.active.trace
        base = re.sub(r'[^\w.-]+', '_', trace.name)
        path, _ = QFileDialog.getSaveFileName(self, "Export full-resolution data", base + ".csv", "CSV (*.csv)",
                                             options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return
        if not Path(path).suffix:
            path += ".csv"
        try:
            target, sidecar = export_paths(path, trace, extensions=(".csv",))
            existing = [p.name for p in (target, sidecar) if p.exists()]
            if existing and QMessageBox.question(self, "Replace existing export?", "Replace these files?\n" + "\n".join(existing),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            export_csv(trace, target, overwrite=bool(existing), settings=self.active.state.settings)
            self.statusBar().showMessage(f"Saved {target.name} and {sidecar.name}", 15000)
        except Exception as exc:
            QMessageBox.warning(self, "Data export failed", str(exc))

    def closeEvent(self, event):
        self._closing = True
        if hasattr(self, 'layout_controller'):
            self.layout_controller.timer.stop()
        self.fid_analysis.cancel(announce=False)
        self.viewport.timer.stop()
        if self.library_dialog is not None:
            self.library_dialog.shutdown()
        if self.inspector is not None:
            self.inspector.reject()
        self.pending.clear()
        for key in list(self.jobs):
            self.cancel_job(key)
        self.loader.stop()
        event.accept()
