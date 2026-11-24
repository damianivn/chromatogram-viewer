"""Focused real-input batch check, usable in source and packaged app."""
from dataclasses import replace
import json
from pathlib import Path
import time


def smoke_batch(window, sources, output):
    from PySide6.QtCore import QModelIndex, Qt
    from PySide6.QtWidgets import QApplication
    from gcviewer.desktop.fid_batch import BatchReportDialog
    from gcviewer.desktop.fid_selection import SelectedIntegrationDialog
    from gcviewer.services.fid_workflow import AnalysisMethod, calculate
    from gcviewer.reports.publication import fingerprint
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    before = [fingerprint(path) for path in sources]

    def wait(predicate):
        deadline = time.monotonic()+90
        while not predicate():
            QApplication.processEvents()
            if time.monotonic() > deadline: raise TimeoutError('Batch smoke timed out')
            time.sleep(.01)
        QApplication.processEvents()

    for source in sources: window.start_load(source, 'fid')
    wait(lambda: not window.pending and not window.jobs)
    view = window.sample_list
    assert view.model().moveRows(QModelIndex(), view.count()-1, 1, QModelIndex(), 0)
    view.clearSelection()
    for row in range(2): view.item(row).setSelected(True)
    assert view.isSelectionRectVisible()
    from gcviewer.desktop.appearance import selection_colors
    QApplication.processEvents()
    row_image = view.viewport().grab().toImage()
    row_rect = view.visualItemRect(view.item(0))
    expected = selection_colors(view.palette(), selected=True)[0].name()
    assert row_image.pixelColor(2, row_rect.top()+1).name() == expected
    samples = window.ordered_fid_samples(selected=True)
    assert len(samples) == 2
    selection = SelectedIntegrationDialog(samples, AnalysisMethod(solvent_mode='automatic'), 'Smoke reference', window)
    selection.show()
    try:
        selection.start()
        wait(lambda: not selection.running)
        for sample in samples:
            assert sample.fid_document.result == json.loads(json.dumps(calculate(sample.fid_run, selection.method)))
        assert selection.grab().save(str(output/'integrated-selection.png'))
    finally:
        selection.reject()
    from gcviewer.services.fid_workflow import assign_names
    from gcviewer.figures.workspace import export_figure
    from gcviewer.figures.peak_labels import automatic_labels, arrange_labels
    from gcviewer.analysis.retention_names import Component
    sample = samples[0]
    document = sample.fid_document
    document.method = replace(document.method, components=(Component('Reference peak', document.result['peaks'][0]['rt_min']),))
    document.result = assign_names(document.result, sample.fid_run, document.method)
    labels = automatic_labels(sample.trace, sample.state.settings, record=document.result, text_mode='both')
    sample.state.labels = labels
    assert any('Reference peak' in label.text for label in labels)
    assert arrange_labels(sample.trace, sample.state, labels) == 0
    for suffix in ('png', 'pdf', 'svg'):
        export_figure(sample.trace, sample.state, output/f'peak-labels.{suffix}')
    from dataclasses import asdict
    controller = window.layout_controller
    for key, candidate in window.samples.items():
        if candidate is sample:
            window.sample_list.setCurrentItem(window.find_item(key))
            break
    panel = window.fid_analysis
    panel.document = sample.fid_document
    panel.fill()
    panel.show_result()
    panel.refresh_enabled()
    saved_labels = asdict(sample.state)
    saved_result = sample.fid_document.result
    for theme in ('dark', 'light'):
        controller.set_appearance(theme, save=False)
        for index, name in ((0, 'figure'), (1, 'analysis')):
            window.workspace_tabs.setCurrentIndex(index)
            controller.sync()
            QApplication.processEvents()
            assert panel.table.rowCount() == len(saved_result['peaks'])
            assert window.grab().save(str(output/f'{theme}-{name}.png'))
        assert sample.fid_document.result is saved_result
        assert asdict(sample.state) == saved_labels
    view.clearSelection()
    for row in range(2): view.item(row).setSelected(True)
    runs = [sample.fid_run for sample in window.ordered_fid_samples()]
    assert len(runs) == len(sources) >= 2
    window.workspace_tabs.setCurrentIndex(1)
    assert window.fid_analysis.batch_action.isEnabled()
    method = AnalysisMethod(solvent_mode='automatic')
    layout = replace(window.fid_analysis.document.layout, subtitle='Batch verification')
    dialog = BatchReportDialog(runs, method, layout, sources, window)
    runs = dialog.runs
    dialog.show()
    QApplication.processEvents()
    assert dialog.grab().save(str(output/'selection.png'))
    target = output/'batch.pdf'
    try:
        dialog.start(target, (None, None))
        wait(lambda: dialog.job is None)
        assert target.exists(), dialog.status.text()
        metadata = json.loads(target.with_suffix('.pdf.json').read_text(encoding='utf-8'))
        assert metadata['selected_count'] == metadata['succeeded_count'] == len(runs)
        assert metadata['failed_count'] == 0
        for run, entry in zip(runs, metadata['samples']):
            assert entry['analysis'] == json.loads(json.dumps(calculate(run, method)))
        assert metadata['output_sha256'] == fingerprint(target)
        assert dialog.grab().save(str(output/'complete.png'))
        cancelled = output/'cancelled.pdf'
        dialog.start(cancelled, (None, None))
        dialog.reject()
        assert dialog.job is None and dialog.worker.process is None
        assert not cancelled.exists() and not cancelled.with_suffix('.pdf.json').exists()
        assert before == [fingerprint(path) for path in sources]
        removed_keys = [item.data(Qt.ItemDataRole.UserRole)
                        for item in view.selectedItems()]
        window.remove_sample()
        assert all(key not in window.samples for key in removed_keys)
        assert len(window.samples) == len(sources)-len(removed_keys)
        assert before == [fingerprint(path) for path in sources]
        (output/'checks.json').write_text(json.dumps(dict(selected=len(runs), pages=metadata['report_pages'],
            numerical_parity=True, selected_integration=True, reordered=True, automatic_labels=True,
            neutral_selection=True, multi_remove=True, workspace=True, appearance=True,
            provenance=True, cancellation=True, sources_unchanged=True), indent=2))
    finally:
        dialog.cleanup()
        dialog.close()


if __name__ == '__main__':
    import argparse
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from gcviewer.desktop.window import Workspace
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', action='append', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    app = QApplication([])
    window = Workspace()
    window.show()
    try: smoke_batch(window, args.source, args.output)
    finally: window.close()
