"""Isolated library-preference smoke, also run inside the packaged app."""
import json
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from gcviewer.desktop.library_dialog import LibraryDialog


def smoke_library_preferences(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    data, lists = output / "Data folder", output / "Sample lists"
    data.mkdir(exist_ok=True)
    lists.mkdir(exist_ok=True)
    spl = lists / "selection.spl"
    spl.touch()
    settings_file = output / "isolated-library.ini"
    preferences = QSettings(str(settings_file), QSettings.Format.IniFormat)
    dialog = LibraryDialog(preferences=preferences)
    try:
        dialog.folder.setText(str(data))
        dialog.spl.setText(str(spl))
        dialog.folder.editingFinished.emit()
        dialog.spl.editingFinished.emit()
        dialog.spl.clear()
    finally:
        dialog.shutdown()
    assert preferences.status() == QSettings.Status.NoError
    assert settings_file.is_file()
    restored = LibraryDialog(preferences=QSettings(str(settings_file), QSettings.Format.IniFormat))
    try:
        assert restored.folder.text() == str(data)
        assert restored.preferences.value("library/spl_folder") == str(lists)
        assert restored.browse_start(restored.preferences.value("library/spl_folder"), restored.folder.text()) == str(lists)
        assert not restored.spl.text() and restored.worker is None
        restored.show()
        QApplication.instance().processEvents()
        assert restored.grab().save(str(output / "restored-library.png"))
        restored.folder.setText(str(output / "unavailable"))
    finally:
        restored.shutdown()
    readback = QSettings(str(settings_file), QSettings.Format.IniFormat)
    assert readback.value("library/data_folder") == str(data)
    result = {"data_folder_restored": True, "independent_spl_folder_restored": True,
              "clear_list_retains_spl_folder": True, "invalid_edit_retains_data_folder": True,
              "no_active_list_or_automatic_discovery": True, "settings_file_written": True,
              "scope": "Explicit isolated INI settings; does not alter owner preferences. Fresh-process persistence is covered by the source test suite."}
    (output / "preferences-checks.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
