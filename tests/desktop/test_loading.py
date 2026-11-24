"""Worker callbacks must not outlive their native Qt owner."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import shiboken6

from gcviewer.desktop.loading import LoadService


class LoadServiceLifetimeTests(unittest.TestCase):
    def test_destroying_owner_disconnects_worker_callbacks(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder, patch("sys.excepthook") as errors:
            owner = QObject()
            service = LoadService(owner)
            process = service.start("probe", "fid", str(Path(folder) / "missing.raw"), folder)
            self.assertTrue(process.waitForStarted(3000))
            shiboken6.delete(owner)
            QTest.qWait(50)
            self.assertFalse(shiboken6.isValid(process))
            errors.assert_not_called()
            service.directory.cleanup()
            service.directory = None
        app.processEvents()
