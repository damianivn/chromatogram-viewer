# Run from the application root with the isolated Qt build environment.
from PyInstaller.utils.hooks import collect_submodules
from pathlib import Path
import os
import sys

# Resolve Windows components before unrelated tools on the developer's PATH.
# A foreign Poppler ICU DLL has the same name as Windows' ICU but incompatible
# exports; bundling it makes an otherwise valid Qt build fail at startup.
if sys.platform == 'win32':
    windows = Path(os.environ['WINDIR'])
    os.environ['PATH'] = os.pathsep.join(map(str, (windows / 'System32', windows,
        Path(sys.executable).parent, Path(sys.base_prefix) / 'Library' / 'bin', Path(sys.base_prefix))))

# A venv made from Conda does not carry conda-meta. Include the base interpreter's
# runtime DLLs explicitly; never rely on the developer's PATH on another PC.
base_library = Path(sys.base_prefix) / 'Library' / 'bin'
runtime_names = ['ffi.dll', 'libcrypto-3-x64.dll', 'liblzma.dll', 'LIBBZ2.dll',
                 'libexpat.dll', 'libssl-3-x64.dll', 'sqlite3.dll']
runtime_binaries = [(str(base_library / name), '.') for name in runtime_names
                    if (base_library / name).is_file()]

packaging_dir = Path(SPECPATH)
project_dir = packaging_dir.parent
a = Analysis([str(packaging_dir / 'desktop_entry.py')], pathex=[str(project_dir)], binaries=runtime_binaries,
    datas=[(str(project_dir / 'gcviewer/desktop/icons/*.svg'), 'gcviewer/desktop/icons')],
    hiddenimports=collect_submodules('rainbow'),
    hookspath=[], hooksconfig={'matplotlib': {'backends': ['QtAgg', 'Agg', 'pdf', 'svg']}},
    excludes=['streamlit', 'PyQt5', 'PyQt6', 'PySide2', 'tkinter'], noarchive=False)
if sys.platform == 'win32':
    for destination, source, _ in a.binaries:
        if Path(destination).name.lower() == 'icuuc.dll' and Path(source).resolve().parent != windows / 'System32':
            raise RuntimeError('A foreign ICU runtime was selected. Clean the PyInstaller build and use the Windows system DLL.')
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ChromatogramViewer',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ChromatogramViewer')
