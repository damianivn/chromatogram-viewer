"""Source entry point: python -m gcviewer.desktop (or launch_qt.vbs)."""
from pathlib import Path
import os
import sys
import traceback


def report_failure(exc_type, exc, tb):
    message = "".join(traceback.format_exception(exc_type, exc, tb))
    smoke_flag = next((flag for flag in ('--smoke-output', '--batch-smoke-output') if flag in sys.argv), None)
    if smoke_flag:
        try:
            output = Path(sys.argv[sys.argv.index(smoke_flag) + 1])
            output.mkdir(parents=True, exist_ok=True)
            with (output / "smoke-error.txt").open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")
        finally:
            try:
                from PySide6.QtWidgets import QApplication
            except ImportError:
                pass
            else:
                if QApplication.instance() is not None:
                    QApplication.instance().exit(1)
        return
    folder = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ChromatogramViewer"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / "qt-startup.log"
        with log.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
        detail = f"{exc_type.__name__}: {exc}\n\nDiagnostic log: {log}\nSee docs/USAGE.md for setup and the debug command."
    except OSError:
        detail = message
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, detail, "Chromatogram Viewer could not continue", 0x10)


def main():
    import tempfile
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "ChromatogramViewer-matplotlib"))
    if "--load-service" in sys.argv:
        from gcviewer.services.worker import serve
        return serve(sys.argv[sys.argv.index("--load-service") + 1])
    if "--load-worker" in sys.argv:
        from gcviewer.services.worker import main as load_main
        return load_main(sys.argv[sys.argv.index("--load-worker") + 1:])
    if "--library-worker" in sys.argv:
        from gcviewer.services.library import main as library_main
        return library_main(sys.argv[sys.argv.index("--library-worker") + 1:])
    sys.excepthook = report_failure
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from gcviewer.desktop.window import Workspace
        app = QApplication(sys.argv)
        app.setApplicationName("Chromatogram Viewer")
        window = Workspace()
        window.show()
        if '--batch-smoke-output' in sys.argv:
            from tools.check_fid_batch import smoke_batch
            output = Path(sys.argv[sys.argv.index('--batch-smoke-output') + 1])
            sources = [Path(sys.argv[i+1]) for i, value in enumerate(sys.argv) if value == '--batch-smoke-source']
            def batch_smoke():
                smoke_batch(window, sources, output)
                window.close()
            QTimer.singleShot(100, batch_smoke)
        if "--smoke-output" in sys.argv:
            output = Path(sys.argv[sys.argv.index("--smoke-output") + 1])
            def smoke():
                from gcviewer.figures.workspace import demo_trace, export_figure
                output.mkdir(parents=True, exist_ok=True)
                assert window.active is None and not window.samples and window.sample_list.count() == 0
                assert not window.figure_export_action.isEnabled() and not window.data_export_action.isEnabled()
                assert window.grab().save(str(output / "empty-workspace.png"))
                window.add_sample(demo_trace())
                for suffix in ("png", "pdf", "svg", "tif"):
                    export_figure(window.active.trace, window.active.state, output / f"demo.{suffix}", overwrite=True)
                window.grab().save(str(output / "workspace.png"))
                window.active.state.add_label(window.active.trace, 10.25, "Retained peak", (.3, .85))
                window.active.state.add_label(window.active.trace, 5.3, "Time-hidden peak")
                window.refresh_labels()
                for mode, xbreak, ybreak in (("time", (4, 7), None), ("signal", None, (50, 70)), ("both", (4, 7), (50, 70))):
                    window.break_controls.set_interval("x_break", xbreak)
                    window.break_controls.set_interval("y_break", ybreak)
                    assert window.apply_settings()
                    app.processEvents()
                    window.canvas.draw()
                    for key, fields in window.break_controls.editors.items():
                        if window.break_controls.enabled[key].isChecked():
                            assert all(field.height() >= field.sizeHint().height() for field in fields)
                    assert len(window.canvas.figure.report_panels) == (2 if xbreak else 1) * (2 if ybreak else 1)
                    for suffix in ("png", "pdf", "svg", "tif"):
                        export_figure(window.active.trace, window.active.state, output / f"break-{mode}.{suffix}", overwrite=True)
                    window.grab().save(str(output / f"break-{mode}-workspace.png"))
                from tools.check_inspection_ui import smoke_inspection
                source = Path(sys.argv[sys.argv.index("--ms-smoke-source") + 1]) if "--ms-smoke-source" in sys.argv else None
                smoke_inspection(window, output / "ms", source)
                from tools.check_comparisons import smoke_comparisons
                smoke_comparisons(window, output / "comparisons")
                from tools.check_processing import smoke_processing
                smoke_processing(window, output / "processing")
                from tools.check_library_preferences import smoke_library_preferences
                smoke_library_preferences(output / "library-preferences")
                if "--fid-smoke-source" in sys.argv:
                    from tools.check_fid_ui import smoke_fid
                    smoke_fid(window, output / "fid", Path(sys.argv[sys.argv.index("--fid-smoke-source") + 1]))
                if "--fid-analysis-source" in sys.argv:
                    from tools.check_fid_analysis import smoke_analysis
                    smoke_analysis(window, output / "fid-analysis", Path(sys.argv[sys.argv.index("--fid-analysis-source") + 1]))
                from tools.check_table_ui import smoke_tables
                smoke_tables(output / "table-styling")
                (output / "smoke-ok.txt").write_text("Qt startup, inspection, exports, screenshot and shutdown reached.\n", encoding="utf-8")
                window.close()
            QTimer.singleShot(700, smoke)
        return app.exec()
    except Exception:
        report_failure(*sys.exc_info())
        return 1


if __name__ == "__main__":
    sys.exit(main())
