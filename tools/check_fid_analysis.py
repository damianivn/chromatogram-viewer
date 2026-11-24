"""Source/packaged single-run analysis acceptance; explicit private input only."""
from dataclasses import replace
import json
from pathlib import Path
import time


def smoke_analysis(window, output, source):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from gcviewer.desktop.fid_forms import fill_table
    from gcviewer.services.fid_workflow import read_preset, preset_record
    from gcviewer.reports.publication import fingerprint, save_json
    output, source = Path(output), Path(source)
    output.mkdir(parents=True, exist_ok=True)
    source_hash = fingerprint(source)

    def wait(predicate):
        deadline = time.monotonic() + 45
        while not predicate():
            QApplication.processEvents()
            if time.monotonic() > deadline:
                raise TimeoutError("FID analysis smoke timed out")
            time.sleep(.025)
        QApplication.processEvents()

    key = window.start_load(source, "fid", origin_key="analysis-smoke")
    wait(lambda: not window.pending and not window.jobs)
    assert key in window.samples, window.failures
    window.workspace_tabs.setCurrentIndex(1)
    panel = window.fid_analysis

    def integrate():
        panel.start()
        wait(lambda: panel.busy is None)
        assert panel.document.result is not None, panel.status.text()
        return panel.document.result

    initial = integrate()
    assert len(panel.canvas.figure.axes) == 1
    peak_count = len(initial["peaks"])
    if initial["peaks"]:
        peak = next((p for p in initial["peaks"] if not p["clipped"]), initial["peaks"][0])
        fill_table(panel.components, [["Reference window", peak["rt_min"], .03], ["Unmatched window", .2, .001]])
        result = panel.document.result
        assert result["peaks"] is initial["peaks"]
        assert panel.busy is None and panel.pdf_action.isEnabled()
        assert "Reference window" in result["names"].values()
        assert "Unmatched window" in result["missing"]
        def review_names():
            dialog = QApplication.activeModalWidget()
            assert dialog.grab().save(str(output / 'detected-names.png'))
            if any(check.isChecked() for check in dialog.checks):
                dialog.accept()
            else:
                dialog.reject()
        if panel.detected_names_button.isEnabled():
            QTimer.singleShot(50, review_names)
            panel.detected_names_button.click()
        result = panel.document.result
        assert result['peaks'] is initial['peaks']
        assert 'Reference window' in result['names'].values()
        assert all(str(p['number']) in result['names'] for p in result['peaks'] if not p['clipped'])
    else:
        result = initial
    peaks = result["peaks"]
    for kind, value in (("method", panel.document.method), ("layout", panel.document.layout)):
        path = output / f"{kind}.json"
        save_json(path, preset_record(kind, value), (source,), overwrite=path.exists())
        assert read_preset(path, kind).to_dict() == value.to_dict()
    for paper in ("letter", "a4"):
        panel.document.layout = replace(panel.document.layout, page_size=paper, subtitle="FID analysis verification")
        target = output / f"analysis-{paper}.pdf"
        sidecar = target.with_suffix('.pdf.json')
        panel.start("pdf", target, (fingerprint(target), fingerprint(sidecar)))
        wait(lambda: panel.busy is None)
        assert target.is_file(), panel.status.text()
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        assert metadata["analysis"]["peaks"] == peaks
        assert metadata["acquisition"]["sha256"] == source_hash
        assert metadata["output_sha256"] == fingerprint(target)
    target = output / "peaks.csv"
    panel.start("csv", target, (fingerprint(target), fingerprint(target.with_suffix('.csv.json'))))
    wait(lambda: panel.busy is None)
    assert target.is_file(), panel.status.text()
    window.active.state.settings = replace(window.active.state.settings, normalize=True, smoothing_window=3)
    window.redraw()
    assert panel.document.result["peaks"] == peaks
    panel.hide_solvent.setChecked(False)
    assert panel.document.result["peaks"] == peaks
    panel.hide_solvent.setChecked(True)
    window.resize(1400, 880)
    QApplication.processEvents()
    panel.canvas.draw()
    assert window.grab().save(str(output / "analysis-workspace.png"))
    if peaks:
        overview = panel.main_axis.get_xlim(), panel.main_axis.get_ylim()
        panel.table.selectRow(len(peaks)-1)
        QApplication.processEvents()
        panel.canvas.draw()
        assert window.grab().save(str(output / "selected-peak.png"))
        panel.toolbar.home()
        assert (panel.main_axis.get_xlim(), panel.main_axis.get_ylim()) == overview
    window.resize(920, 680)
    QApplication.processEvents()
    panel.canvas.draw()
    assert window.grab().save(str(output / "analysis-small.png"))
    for index, table in ((0, panel.table), (1, panel.components), (2, panel.events)):
        panel.forms.setCurrentIndex(index)
        if index == 2:
            from PySide6.QtWidgets import QToolButton
            panel.forms.widget(2).findChild(QToolButton).setChecked(True)
        QApplication.processEvents()
        assert table.isVisible()
        assert table.horizontalScrollBar().maximum() == 0
        assert window.grab().save(str(output / f"fit-table-{index}.png"))
    panel.forms.setCurrentIndex(0)
    window.resize(1280, 820)
    cancelled = output / "cancelled-report.pdf"
    assert not cancelled.exists()
    panel.start("pdf", cancelled, (None, None))
    panel.cancel()
    assert not cancelled.exists() and not cancelled.with_suffix('.pdf.json').exists()
    assert panel.worker.process is None
    panel.solvent.setCurrentIndex(panel.solvent.findData("automatic"))
    automatic = integrate()
    if any(p["clipped"] for p in initial["peaks"]):
        assert automatic["effective_delay_min"] is not None
        assert len(automatic["peaks"]) < peak_count
        assert abs(sum(p["area_pct"] for p in automatic["peaks"]) - 100) < 1e-8
    assert fingerprint(source) == source_hash
    assert not window.active.fid_run.counts.flags.writeable
    checks = dict(source_sha256=source_hash, included_peak_count=peak_count,
        automatic_peak_count=len(automatic["peaks"]), automatic_delay_min=automatic["effective_delay_min"],
        original_counts_retained=True, saved_presets_roundtrip=True, pdf_csv_table_agree=True,
        letter_a4_reports=True, view_edits_independent=True, cancellation_no_output=True, source_unchanged=True,
        names_reuse_integration=True, home_restores_overview=True, tables_fit_without_horizontal_scroll=True,
        detected_peaks_prefill_names=True,
        scope="Single-run worker/UI/report smoke on the development PC; no RST runtime dependency.")
    (output / "analysis-checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    panel.cancel(announce=False)


def main():
    import argparse
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from gcviewer.desktop.window import Workspace
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    app = QApplication([])
    window = Workspace()
    window.show()
    try:
        smoke_analysis(window, args.output, args.source.resolve())
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    main()
