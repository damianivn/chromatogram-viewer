"""Controls for publication annotations, separate from numerical integration."""
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                              QFormLayout, QLabel, QSpinBox, QVBoxLayout)
from gcviewer.figures.workspace import source_traces
from gcviewer.figures.peak_labels import automatic_labels


class AutomaticLabelsDialog(QDialog):
    def __init__(self, trace, settings, record=None, parent=None):
        super().__init__(parent)
        self.trace, self.settings, self.record = trace, settings, record
        self.labels = []
        self.setWindowTitle('Automatic peak labels')
        self.resize(440, 330)
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)
        self.trace_choice = QComboBox()
        for index, source in enumerate(source_traces(trace)):
            self.trace_choice.addItem(source.name, index)
        form.addRow('Trace', self.trace_choice)
        self.source = QComboBox()
        if record is not None:
            self.source.addItem('Current FID integration and names', 'fid')
        self.source.addItem('Detect peaks in displayed signal', 'detect')
        form.addRow('Peak source', self.source)
        self.mode = QComboBox()
        self.mode.addItem('Top N peaks by intensity', 'top')
        self.mode.addItem('Above an intensity threshold', 'threshold')
        form.addRow('Label', self.mode)
        self.count = QSpinBox()
        self.count.setRange(1, 100)
        self.count.setValue(10)
        form.addRow('Number of peaks', self.count)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0, 100)
        self.threshold.setValue(10.)
        self.threshold.setSuffix(' % of full-trace maximum')
        form.addRow('Minimum intensity', self.threshold)
        self.prominence = QDoubleSpinBox()
        self.prominence.setRange(0, 100)
        self.prominence.setValue(1.)
        self.prominence.setSuffix(' % of signal range')
        self.prominence.setToolTip('Higher prominence ignores smaller fluctuations. Used only for figure peak detection.')
        form.addRow('Detection prominence', self.prominence)
        self.text_mode = QComboBox()
        form.addRow('Label text', self.text_mode)
        note = QLabel('Only peaks in the retained figure view are labeled. Existing automatic labels for this trace are replaced; manual labels stay.\n'
                      'FID names require a current integration in the individual sample. Assigned names are not confirmed identities.')
        note.setWordWrap(True)
        root.addWidget(note)
        self.error = QLabel()
        self.error.setWordWrap(True)
        root.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Generate labels')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.source.currentIndexChanged.connect(self.update_controls)
        self.mode.currentIndexChanged.connect(self.update_controls)
        self.update_controls()

    def update_controls(self):
        fid = self.source.currentData() == 'fid'
        self.count.setEnabled(self.mode.currentData() == 'top')
        self.threshold.setEnabled(self.mode.currentData() == 'threshold')
        self.prominence.setEnabled(not fid)
        previous = self.text_mode.currentData()
        self.text_mode.clear()
        self.text_mode.addItem('Retention times', 'rt')
        if fid:
            self.text_mode.addItem('Assigned names only', 'name')
            self.text_mode.addItem('Names and retention times', 'both')
        index = self.text_mode.findData(previous or ('both' if fid else 'rt'))
        self.text_mode.setCurrentIndex(max(0, index))

    def accept(self):
        try:
            self.labels = automatic_labels(self.trace, self.settings,
                trace_index=self.trace_choice.currentData(),
                record=self.record if self.source.currentData() == 'fid' else None,
                mode=self.mode.currentData(), count=self.count.value(), threshold=self.threshold.value(),
                prominence=self.prominence.value(), text_mode=self.text_mode.currentData())
            if not self.labels:
                raise ValueError('No matching peaks. Adjust the selection or figure range; names-only needs assigned names.')
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        super().accept()
