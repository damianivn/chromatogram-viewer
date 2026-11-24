"""One reusable, cancellable parser process; only one request is in flight."""
import json
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QObject, QProcess, QTimer, Signal, Slot


class LoadService(QObject):
    completed = Signal(str)
    failed = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.directory = None
        self.active = None
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.poll)

    def start(self, key, kind, source, output):
        if self.active is not None:
            raise RuntimeError("The acquisition worker is already busy")
        if self.process is None:
            self.directory = tempfile.TemporaryDirectory(prefix="chromatogram-service-")
            process = QProcess(self)
            process.setProperty("persistent_loader", True)
            self.process = process
            process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
            # QObject-bound slots disconnect during owner destruction. A lambda
            # capturing the child can run after its C++ QProcess is deleted.
            process.finished.connect(self.process_finished)
            process.errorOccurred.connect(self.process_error)
            if getattr(sys, "frozen", False):
                program, args = sys.executable, ["--load-service", self.directory.name]
            else:
                program = str(Path(sys.executable).with_name("pythonw.exe")) if sys.platform == "win32" else sys.executable
                args = ["-m", "gcviewer.services.worker", "--serve", self.directory.name]
            process.start(program, args)
        self.active = (key, Path(output))
        request = Path(self.directory.name) / "request.tmp"
        request.write_text(json.dumps({"kind": kind, "source": source, "output": str(output)}), encoding="utf-8")
        request.replace(request.with_suffix(".json"))
        self.timer.start()
        return self.process

    def poll(self):
        if self.active and (self.active[1] / "result.json").is_file():
            key, _ = self.active
            self.active = None
            self.timer.stop()
            self.completed.emit(key)

    @Slot(int, QProcess.ExitStatus)
    def process_finished(self, *_):
        self.exited(self.sender())

    @Slot(QProcess.ProcessError)
    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.exited(self.sender())

    def exited(self, process):
        if process is None or process is not self.process:
            return
        # A completed file is still usable if the worker exits immediately after it.
        self.poll()
        if process is not self.process:
            return  # a completion callback may have cancelled/replaced the worker
        active = self.active
        detail = process.errorString() + "\n" + bytes(process.readAllStandardError()).decode(errors="replace")[-2000:]
        self.stop()
        if active:
            self.failed.emit(active[0], "The acquisition worker stopped. Retry this sample.\n" + detail)

    def stop(self):
        self.timer.stop()
        self.active = None
        process, self.process = self.process, None
        if process is not None:
            # On Windows kill() during Starting can precede process creation.
            # Resolve the launch first so cancellation cannot leave a child alive
            # holding its request file after we remove the IPC directory.
            if process.state() == QProcess.ProcessState.Starting:
                process.waitForStarted(3000)
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(3000)
            process.deleteLater()
        if self.directory is not None:
            self.directory.cleanup()
            self.directory = None
