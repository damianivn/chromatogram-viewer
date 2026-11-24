"""Single-run FID analysis view; numerical work and PDF rendering use a process."""
import json
from pathlib import Path
import tempfile
import uuid

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget, QToolButton, QTableWidget, QVBoxLayout, QWidget
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from gcviewer.desktop.fid_forms import DetectedPeakNamesDialog, ReportLayoutDialog, fill_table, table_editor, table_rows
from gcviewer.desktop.loading import LoadService
from gcviewer.desktop.tables import FlatTableWidget
from gcviewer.desktop.sections import disclosure_header
from gcviewer.services.fid_workflow import AnalysisDocument, AnalysisMethod, analysis_key, assign_names, check_source, digest, integration_key, preset_record, read_preset, typed_result, write_request
from gcviewer.reports.publication import fingerprint, output_paths, publish, save_json
from gcviewer.analysis.retention_names import Component
from gcviewer.analysis.totalchrom_fid import IntegrationParams, TimedEvent
from gcviewer.figures.fid_plot import plot_chromatogram


class AnalysisToolbar(NavigationToolbar2QT):
    toolitems = tuple(item for item in NavigationToolbar2QT.toolitems
                      if item[0] in ("Home", "Back", "Forward", "Pan", "Zoom", None))


class AnalysisPanel(QWidget):
    def __init__(self, parent=None, sources=lambda: (), runs=lambda: (), selected_runs=lambda: ()):
        super().__init__(parent)
        self.sources = sources
        self.runs = runs
        self.selected_runs = selected_runs
        self.sample = None
        self.document = None
        self.busy = None
        self.filling = False
        self.worker = LoadService(self)
        self.worker.completed.connect(self.finished)
        self.worker.failed.connect(self.failed)
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(100)
        self.progress_timer.timeout.connect(self.read_progress)
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        self.title = QLabel("Open a GC-FID acquisition to analyse it.")
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.actions_widget = QWidget()
        actions = QHBoxLayout(self.actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        self.integrate_action = QAction("Integrate current FID sample", self)
        self.integrate_action.setIconText("Integrate")
        self.integrate_action.triggered.connect(lambda: self.start("integrate"))
        self.csv_action = QAction("Export peak table…", self)
        self.csv_action.triggered.connect(lambda: self.choose_export("csv"))
        self.pdf_action = QAction("Create PDF report…", self)
        self.pdf_action.setIconText("PDF report")
        self.pdf_action.triggered.connect(lambda: self.choose_export("pdf"))
        self.layout_action = QAction("Report layout…", self)
        self.layout_action.triggered.connect(self.edit_layout)
        self.integrate_button = QToolButton()
        self.integrate_button.setDefaultAction(self.integrate_action)
        self.integrate_button.setText("Integrate")
        actions.addWidget(self.integrate_button)
        self.report_button = QToolButton()
        self.report_button.setDefaultAction(self.pdf_action)
        self.report_button.setText("PDF report...")
        actions.addWidget(self.report_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        root.addWidget(self.actions_widget)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumHeight(6)
        results = QWidget()
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = FigureCanvasQTAgg(Figure(figsize=(7, 5)))
        navigation = QHBoxLayout()
        self.toolbar = AnalysisToolbar(self.canvas, self)
        navigation.addWidget(self.toolbar)
        self.hide_solvent = QCheckBox("Hide solvent (view only)")
        self.hide_solvent.setChecked(False)
        self.fit_peaks = QCheckBox("Fit peaks")
        self.fit_peaks.setChecked(True)
        self.hide_solvent.toggled.connect(lambda: self.draw(reset_view=True))
        self.fit_peaks.toggled.connect(self.draw)
        navigation.addWidget(self.hide_solvent)
        navigation.addWidget(self.fit_peaks)
        navigation.addStretch()
        vertical = self.results_split = QSplitter(Qt.Orientation.Vertical)
        self.plot_pane = QWidget()
        plot_layout = QVBoxLayout(self.plot_pane)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.addWidget(self.canvas, 1)
        plot_layout.addLayout(navigation)
        plot_layout.addWidget(self.title)
        plot_layout.addWidget(self.status)
        plot_layout.addWidget(self.progress)
        vertical.addWidget(self.plot_pane)
        self.table = FlatTableWidget(0, 11, row_hover=True)
        self.table.setHorizontalHeaderLabels(["Peak", "Assigned\ncomponent", "RT\n(min)", "Area\n(µV·s)", "Height\n(µV)", "Area\n(%)", "Start (min)", "End (min)", "Baseline", "Clipped", "Flags"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self.focus_peak)
        self.table.setMinimumHeight(110)
        self.table.verticalHeader().hide()
        for column in range(6, 11):
            self.table.setColumnHidden(column, True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.horizontalHeader().setMinimumSectionSize(24)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.horizontalHeaderItem(0).setText("#")
        self.result_pane = QWidget()
        result_layout = QVBoxLayout(self.result_pane)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.addWidget(self.table)
        vertical.addWidget(self.result_pane)
        vertical.setSizes([480, 180])
        results_layout.addWidget(vertical)
        self.peak_details = QLabel("Select a peak for its boundaries, baseline and flags. Home restores the overview.")
        self.peak_details.setWordWrap(True)
        self.peak_details.setTextFormat(Qt.TextFormat.PlainText)
        self.peak_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        result_layout.addWidget(self.peak_details)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        result_layout.addWidget(self.summary)
        root.addWidget(results, 1)
        self.forms = QTabWidget(self)
        self.forms.hide()
        self.forms.setMinimumWidth(245)
        method = QWidget()
        method_layout = QVBoxLayout(method)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.noise = QLineEdit("50")
        self.area = QLineEdit("100")
        self.area.setToolTip("TotalChrom AT: accumulated rise in µV, not a minimum peak area in µV·s.")
        self.bunch = QSpinBox()
        self.bunch.setRange(1, 100000)
        self.solvent = QComboBox()
        for label, key in (("Include all", "include"), ("Exclude before a time", "manual"), ("Automatic exclusion", "automatic")):
            self.solvent.addItem(label, key)
        self.delay = QLineEdit("0")
        for label, widget in (("Noise threshold (µV)", self.noise), ("Detection threshold AT (µV)", self.area),
                              ("Bunching factor", self.bunch), ("Solvent integration", self.solvent), ("Exclude before (min)", self.delay)):
            form.addRow(label, widget)
        method_layout.addLayout(form)
        note = QLabel("Automatic exclusion uses a tall/clipped-peak heuristic. Review the effective delay. Excluded peaks do not contribute to area %.\n\nFigure smoothing, normalization and axis breaks do not affect analysis.")
        note.setWordWrap(True)
        method_layout.addWidget(note)
        row = QHBoxLayout()
        for verb in ("Load", "Save"):
            button = QPushButton(f"{verb} method…")
            button.clicked.connect(lambda checked=False, save=verb == "Save": self.preset("method", save))
            row.addWidget(button)
        method_layout.addLayout(row)
        self.batch_action = QAction('Batch PDF report…', self)
        self.batch_action.setToolTip('Choose opened FID samples and use one method/layout for a combined report.')
        self.batch_action.triggered.connect(self.batch_report)
        method_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(method)
        self.forms.addTab(scroll, "Method")
        component_page, self.components = table_editor(["Name", "RT (min)", "± (min)"])
        self.components.horizontalHeaderItem(1).setToolTip("Expected retention time in minutes")
        self.components.horizontalHeaderItem(2).setToolTip("Retention-time tolerance in minutes")
        self.components.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.components.horizontalHeader().setStretchLastSection(False)
        self.components.horizontalHeader().setMinimumSectionSize(24)
        self.components.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.components.setToolTip("Names are assigned by retention-time windows, not confirmed chemical identities. Leave empty for unnamed peaks.")
        self.detected_names_button = QPushButton("Use detected peaks for Names…")
        self.detected_names_button.setToolTip("Integrate first, then select unnamed peaks to create reusable retention-time rules.")
        self.detected_names_button.clicked.connect(self.use_detected_names)
        component_page.layout().insertWidget(0, self.detected_names_button)
        self.forms.addTab(component_page, "Names")
        event_page, self.events = table_editor(["Time (min)", "Event", "Value (µV)"])
        self.events.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.events.horizontalHeader().setStretchLastSection(False)
        self.events.horizontalHeader().setMinimumSectionSize(24)
        self.events.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        event_hint = QLabel("Optional: change detection at a chosen time in the run. Leave empty for one set of settings throughout.\n\n-P turns detection off; +P turns it on. NT changes the noise threshold; AT changes the detection threshold. Only NT/AT need a positive value.")
        event_hint.setWordWrap(True)
        event_page.layout().insertWidget(0, event_hint)
        advanced = QWidget()
        advanced_layout = QVBoxLayout(advanced)
        events_toggle = disclosure_header("Timed events", event_page)
        advanced_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        advanced_layout.addWidget(events_toggle)
        advanced_layout.addWidget(event_page, 1)
        event_page.hide()
        self.forms.addTab(advanced, "Advanced")
        for editor in (self.noise, self.area, self.delay):
            editor.textChanged.connect(self.edited)
        self.bunch.valueChanged.connect(self.edited)
        self.solvent.currentIndexChanged.connect(self.edited)
        for table, handler in ((self.components, self.names_edited), (self.events, self.edited)):
            table.itemChanged.connect(handler)
            table.model().rowsRemoved.connect(handler)
            table.model().rowsInserted.connect(handler)
        self.refresh_enabled()

    def capture(self):
        return {"noise": self.noise.text(), "area": self.area.text(), "bunch": self.bunch.value(),
                "mode": self.solvent.currentData(), "delay": self.delay.text(),
                "components": table_rows(self.components), "events": table_rows(self.events)}

    def method_value(self, *, include_names=True):
        components = (tuple(Component(row[0], float(row[1]), float(row[2]))
                            for row in table_rows(self.components) if any(row)) if include_names else ())
        events = tuple(TimedEvent(float(row[0]), row[1], float(row[2]) if row[2] else None) for row in table_rows(self.events) if any(row))
        previous = self.document.method.params
        params = IntegrationParams(float(self.noise.text()), float(self.area.text()), self.bunch.value(),
                                   valley_to_peak_ratio=previous.valley_to_peak_ratio, events=events)
        mode = self.solvent.currentData()
        return AnalysisMethod(params, mode, float(self.delay.text()) if mode == "manual" else 0., components)

    def fill(self):
        self.filling = True
        try:
            m = self.document.method
            d = self.document.draft or dict(noise=str(m.params.noise_threshold_uv), area=str(m.params.area_threshold_uv),
                bunch=m.params.bunching_factor, mode=m.solvent_mode, delay=str(m.delay_min),
                components=[[c.name, c.rt_min, c.window_min] for c in m.components],
                events=[[e.time_min, e.kind, "" if e.value is None else e.value] for e in m.params.events])
            self.noise.setText(d["noise"])
            self.area.setText(d["area"])
            self.bunch.setValue(d["bunch"])
            self.solvent.setCurrentIndex(self.solvent.findData(d["mode"]))
            self.delay.setText(d["delay"])
            fill_table(self.components, d["components"])
            fill_table(self.events, d["events"])
        finally:
            self.filling = False
        self.delay.setEnabled(self.solvent.currentData() == "manual")

    def bind(self, sample):
        if sample is self.sample:
            return
        self.cancel(announce=False, stop_idle=False)
        self.main_axis = None
        self.sample = sample if sample is not None and sample.fid_run is not None else None
        self.document = None
        if self.sample is not None:
            if self.sample.fid_document is None:
                self.sample.fid_document = AnalysisDocument()
            self.document = self.sample.fid_document
            self.fill()
            run = self.sample.fid_run
            self.title.setText(f"FID Analysis · {run.path.name}  ·  {run.header.sample_name}  ·  {run.n_points:,} points")
        else:
            self.title.setText("Open a GC-FID acquisition to analyse it.")
        self.status.clear()
        self.show_result()
        self.refresh_enabled()

    def edited(self, *args):
        if self.filling or self.document is None:
            return
        self.cancel(announce=False, stop_idle=False)
        self.document.draft = self.capture()
        self.document.result = None
        self.delay.setEnabled(self.solvent.currentData() == "manual")
        self.status.setText("Settings changed. Integrate to update the results.")
        self.show_result()
        self.refresh_enabled()

    def names_edited(self, *args):
        if self.filling or self.document is None:
            return
        if self.busy and self.busy["action"] != "integrate":
            self.cancel(announce=False)
        self.document.draft = self.capture()
        self.apply_names()
        self.refresh_enabled()

    def apply_names(self):
        try:
            method = self.method_value()
            method.validate_run(self.sample.fid_run)
        except ValueError:
            self.status.setText("Complete each Names row with a name, retention time and positive tolerance (or remove it). Existing integration is kept; export is paused.")
            return
        record = self.document.result
        if record is not None and record["analysis_key"] != analysis_key(self.sample.fid_run, method):
            try:
                self.document.result = assign_names(record, self.sample.fid_run, method)
            except ValueError as exc:
                self.status.setText(str(exc))
                return
            self.show_result()
        self.document.method = method
        if self.busy is None:
            self.status.setText("Names updated; integration values are unchanged." if record is not None
                                else "Naming rules saved. Integrate to find peaks.")

    def refresh_enabled(self):
        active, busy = self.document is not None, self.busy is not None
        ready = active and self.document.result is not None and not busy
        if ready:
            try:
                method = self.method_value()
                method.validate_run(self.sample.fid_run)
                ready = self.document.result["analysis_key"] == analysis_key(self.sample.fid_run, method)
            except ValueError:
                ready = False
        self.integrate_action.setEnabled(active and not busy)
        self.csv_action.setEnabled(ready)
        self.pdf_action.setEnabled(ready)
        self.detected_names_button.setEnabled(bool(ready and any(
            str(p['number']) not in self.document.result['names'] for p in self.document.result['peaks'])))
        self.layout_action.setEnabled(active and not busy)
        self.batch_action.setEnabled(active and not busy)
        self.forms.setEnabled(active)
        self.cancel_button.setEnabled(busy)
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)

    def batch_report(self):
        if self.document is None or self.busy:
            return
        try:
            from gcviewer.desktop.fid_batch import BatchReportDialog
            method = self.method_value()
            dialog = BatchReportDialog(self.runs() or (self.sample.fid_run,), method,
                                       self.document.layout, self.sources(), self,
                                       selected_paths=[run.path for run in self.selected_runs()] or None)
            dialog.exec()
        except Exception as exc:
            self.status.setText(str(exc))

    def use_detected_names(self):
        if not self.detected_names_button.isEnabled():
            return
        method = self.method_value()
        record = self.document.result
        peaks = [p for p in record['peaks'] if str(p['number']) not in record['names']]
        dialog = DetectedPeakNamesDialog(peaks, method.components, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        rows = [row for row in table_rows(self.components) if any(row)]
        rows.extend([c.name, str(c.rt_min), str(c.window_min)] for c in dialog.components)
        self.filling = True
        try:
            fill_table(self.components, rows)
        finally:
            self.filling = False
        self.names_edited()
        self.status.setText(f"Added {len(dialog.components)} naming rules. Edit names as needed; Save method keeps them for other samples.")

    def start(self, action="integrate", target=None, expected=None):
        if self.document is None or self.busy is not None:
            return
        directory = None
        try:
            method = self.method_value()
            method.validate_run(self.sample.fid_run)
            check_source(self.sample.fid_run)
            self.document.method = method
            if action != "integrate" and (self.document.result is None or self.document.result["analysis_key"] != analysis_key(self.sample.fid_run, method)):
                raise ValueError("Integrate the current settings before exporting.")
            directory = tempfile.TemporaryDirectory(prefix="fid-analysis-")
            write_request(directory.name, self.sample.fid_run, method, self.document.layout, action)
            key = uuid.uuid4().hex
            self.busy = dict(key=key, directory=directory, document=self.document, sample=self.sample,
                analysis_key=analysis_key(self.sample.fid_run, method), layout_key=digest(self.document.layout.to_dict()),
                integration_key=integration_key(self.sample.fid_run, method),
                action=action, target=target, expected=expected)
            self.worker.start(key, "fid-analysis", directory.name, directory.name)
            self.progress_timer.start()
            self.status.setText("Integrating original acquisition…")
        except Exception as exc:
            self.worker.stop()
            self.busy = None
            if directory is not None:
                directory.cleanup()
            self.status.setText(str(exc))
        self.refresh_enabled()

    def read_progress(self):
        if self.busy:
            path = Path(self.busy["directory"].name) / "progress.txt"
            if path.exists():
                self.status.setText(path.read_text(encoding="utf-8"))

    def finished(self, key):
        job = self.busy
        if job is None or key != job["key"]:
            return
        try:
            folder = Path(job["directory"].name)
            value = json.loads((folder / "result.json").read_text(encoding="utf-8"))
            if "error" in value:
                raise ValueError(value["error"])
            result = value["analysis"]
            if (self.document is not job["document"] or result["analysis_key"] != job["analysis_key"]
                    or integration_key(self.sample.fid_run, self.method_value(include_names=False)) != job["integration_key"]
                    or digest(self.document.layout.to_dict()) != job["layout_key"]):
                raise ValueError("Settings or acquisition changed; this result was discarded.")
            check_source(self.sample.fid_run)
            if job["action"] != "integrate":
                if analysis_key(self.sample.fid_run, self.method_value()) != job["analysis_key"]:
                    raise ValueError("Naming rules changed; this export was discarded.")
                paths = output_paths(job["target"], "." + job["action"], self.sources())
                publish((folder / f"output.{job['action']}", folder / "output.json"), paths, job["expected"])
                self.status.setText(f"Saved {paths[0].name} and its analysis metadata.")
            else:
                self.status.setText("Integration complete. Select a peak row to inspect its boundaries.")
            self.document.result = result
            self.show_result()
            if job["action"] == "integrate":
                self.apply_names()
        except Exception as exc:
            self.status.setText(str(exc))
        finally:
            self.busy = None
            self.progress_timer.stop()
            job["directory"].cleanup()
            self.refresh_enabled()

    def failed(self, key, detail):
        if self.busy and self.busy["key"] == key:
            self.cancel(announce=False)
            self.status.setText(detail)

    def cancel(self, checked=False, *, announce=True, stop_idle=True):
        job, self.busy = self.busy, None
        self.progress_timer.stop()
        if job or stop_idle:
            self.worker.stop()
        if job:
            job["directory"].cleanup()
            if announce:
                self.status.setText("Cancelled. No output was published.")
        self.refresh_enabled()

    def show_result(self):
        record = self.document.result if self.document else None
        self.table.blockSignals(True)
        try:
            rows = []
            if record:
                for p in record["peaks"]:
                    rows.append([p["number"], record["names"].get(str(p["number"]), ""), f"{p['rt_min']:.6f}",
                        f"{p['area_uv_s']:.4f}", f"{p['height_uv']:.4f}", f"{p['area_pct']:.4f}",
                        f"{p['start_min']:.6f}", f"{p['end_min']:.6f}", p["baseline_code"], "Yes" if p["clipped"] else "", " ".join(p["flags"])])
            fill_table(self.table, rows)
            for row, values in enumerate(rows):
                details = self.details_text(record["peaks"][row])
                for column, value in enumerate(values):
                    item = self.table.item(row, column)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setToolTip(f"{self.table.horizontalHeaderItem(column).text()}: {value}\n{details}")
                    if 2 <= column <= 5:
                        precision = 3 if column == 2 else 4 if column == 5 else 2
                        item.setText(f"{float(value):.{precision}f}")
            self.table.clearSelection()
        finally:
            self.table.blockSignals(False)
        if record:
            delay = record["effective_delay_min"]
            text = f"{len(record['peaks'])} peaks · total area {record['total_area_uv_s']:,.4f} µV·s"
            if delay is not None:
                text += f" · excluded before {delay:.6g} min"
            text += "\nArea % uses only included peaks."
            if record["missing"]:
                text += "\nUnmatched components: " + ", ".join(record["missing"])
            if record["warnings"]:
                text += "\n" + "\n".join(dict.fromkeys(record["warnings"]))
            self.summary.setText(text)
        else:
            self.summary.setText("No current integration results. Choose a method and press Integrate.")
        self.peak_details.setText("Select a peak for its boundaries, baseline and flags. Home restores the overview.")
        self.draw()

    @staticmethod
    def details_text(peak):
        return (f"Peak {peak['number']} · Start {peak['start_min']:.6f} min · End {peak['end_min']:.6f} min"
                f" · Baseline {peak['baseline_code']} · Clipped: {'Yes' if peak['clipped'] else 'No'}"
                f" · Flags: {', '.join(peak['flags']) or 'None'}")

    def draw(self, *args, reset_view=False):
        previous = getattr(self, 'main_axis', None)
        x_range = previous.get_xlim() if previous is not None and not reset_view else None
        home_range = getattr(self, '_overview_xlim', x_range) if x_range is not None else None
        fig = self.canvas.figure
        fig.clear()
        fig.set_layout_engine("constrained", w_pad=.04, h_pad=.04, hspace=.10)
        self.main_axis = None
        self.peak_span = None
        if self.sample is not None:
            run = self.sample.fid_run
            record = self.document.result
            result = typed_result(record, run) if record else None
            names = {int(k): v for k, v in record["names"].items()} if record else {}
            main = fig.subplots()
            plot_chromatogram(main, run, result, names, x_range=x_range, hide_solvent=self.hide_solvent.isChecked(),
                             zoom_to_peaks=self.fit_peaks.isChecked(), legend=True, label_size=8)
            main.xaxis.set_major_locator(MaxNLocator(nbins="auto", steps=[1, 2, 2.5, 5, 10]))
            for spine in ("top", "right"):
                main.spines[spine].set_visible(False)
            main.tick_params(labelsize=8)
            main.xaxis.label.set_size(9)
            main.yaxis.label.set_size(9)
            self.main_axis = main
        if self.main_axis is not None:
            self._overview_xlim = home_range or self.main_axis.get_xlim()
            self.main_axis.set_xlim(self._overview_xlim)
        self.toolbar.update()
        self.toolbar.push_current()
        if x_range is not None and self.main_axis is not None:
            self.main_axis.set_xlim(x_range)
            self.toolbar.push_current()
        self.canvas.draw_idle()

    def focus_peak(self):
        row = self.table.currentRow()
        if row < 0 or not self.document or not self.document.result or self.main_axis is None:
            return
        p = self.document.result["peaks"][row]
        if self.peak_span is not None:
            self.peak_span.remove()
        margin = max(.02, (p["end_min"] - p["start_min"]) * .4)
        self.main_axis.set_xlim(p["start_min"] - margin, p["end_min"] + margin)
        run = self.sample.fid_run
        section = run.microvolts[p["start"]:p["end"] + 1] / 1000.
        low, high = float(section.min()), float(section.max())
        pad = max((high - low) * .12, .001)
        self.main_axis.set_ylim(low - pad, high + pad * 2)
        self.peak_span = self.main_axis.axvspan(p["start_min"], p["end_min"], color="tab:blue", alpha=.09)
        self.peak_details.setText(self.details_text(p))
        self.toolbar.push_current()
        self.canvas.draw_idle()

    def choose_export(self, extension):
        if self.document is None or self.document.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save FID report" if extension == "pdf" else "Save peak table",
            self.sample.fid_run.path.stem + "-analysis." + extension, f"{extension.upper()} (*.{extension})")
        if not path:
            return
        try:
            paths = output_paths(path, "." + extension, self.sources())
            expected = tuple(fingerprint(p) for p in paths)
            if any(x is not None for x in expected) and QMessageBox.question(self, "Replace export?",
                    "Replace the report/table and its analysis metadata?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            self.start(extension, paths[0], expected)
        except Exception as exc:
            self.status.setText(str(exc))

    def edit_layout(self):
        if self.document is None:
            return
        dialog = ReportLayoutDialog(self.document.layout, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.document.layout = dialog.options
            self.status.setText("Report layout updated. Integration values are unchanged.")

    def preset(self, kind, save):
        if self.document is None:
            return
        chooser = QFileDialog.getSaveFileName if save else QFileDialog.getOpenFileName
        path, _ = chooser(self, ("Save " if save else "Load ") + kind, f"fid-{kind}.json" if save else "", "JSON (*.json)")
        if not path:
            return
        try:
            if save:
                value = self.method_value() if kind == "method" else self.document.layout
                paths = output_paths(path, ".json", self.sources(), sidecar=False)
                exists = paths[0].exists()
                if exists and QMessageBox.question(self, "Replace preset?", "Replace this saved preset?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                    return
                save_json(path, preset_record(kind, value), self.sources(), overwrite=exists)
            else:
                value = read_preset(path, kind)
                self.cancel(announce=False, stop_idle=False)
                if kind == "method":
                    previous = self.document.result
                    if previous is not None:
                        try:
                            previous = assign_names(previous, self.sample.fid_run, value)
                        except ValueError:
                            previous = None
                    self.document.method = value
                    self.document.draft = None
                    self.document.result = previous
                    self.fill()
                    self.show_result()
                else:
                    self.document.layout = value
            self.status.setText(("Saved " if save else "Loaded ") + kind + "." + (" Integrate to update results." if kind == "method" and not save and self.document.result is None else ""))
        except Exception as exc:
            self.status.setText(str(exc))
        self.refresh_enabled()
