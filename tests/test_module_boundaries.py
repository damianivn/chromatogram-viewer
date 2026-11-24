"""Guard scientific reuse independently of Qt and application orchestration."""
import ast
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ModuleBoundaries(unittest.TestCase):
    def test_dependencies_point_toward_scientific_core(self):
        allowed = {
            'data_models': {'data_models'},
            'parsers': {'data_models', 'parsers'},
            'analysis': {'data_models', 'analysis'},
            'figures': {'data_models', 'analysis', 'figures'},
            'reports': {'data_models', 'parsers', 'analysis', 'figures', 'reports'},
            'services': {'data_models', 'parsers', 'analysis', 'figures', 'reports', 'services'},
        }
        for layer, dependencies in allowed.items():
            for path in (ROOT/'gcviewer'/layer).rglob('*.py'):
                module = '.'.join(path.relative_to(ROOT).with_suffix('').parts)
                package = module.rsplit('.', 1)[0]
                for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                    imports = []
                    if isinstance(node, ast.Import):
                        imports = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        imports = [importlib.util.resolve_name('.'*node.level + (node.module or ''), package)
                                   if node.level else node.module or '']
                    for name in imports:
                        with self.subTest(file=path.relative_to(ROOT), imported=name):
                            self.assertNotIn(name.split('.')[0], {'PySide6', 'PyQt5', 'PyQt6', 'streamlit', 'desktop', 'shared', 'tcfid', 'instruments'})
                            if name.startswith('gcviewer.'):
                                self.assertIn(name.split('.')[1], dependencies | {'revisions'})

    def test_fid_core_works_without_optional_dependencies(self):
        script = '''
import importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'PySide6','PyQt5','PyQt6','streamlit','matplotlib','scipy','pandas','rainbow','access_parser'}:
            raise AssertionError('Unexpected optional dependency: '+fullname)
sys.meta_path.insert(0, Guard())
from gcviewer.parsers.totalchrom import read_raw_bytes
from gcviewer.analysis.totalchrom_fid import IntegrationParams, integrate
from gcviewer.analysis.retention_names import Component, identify
from tests.penx_fixture import penx_bytes
run = read_raw_bytes(penx_bytes()[0])
result = integrate(run, IntegrationParams(50., 100.))
assert result is not None
assert not any(n.startswith('gcviewer.desktop') for n in sys.modules)
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_library_discovery_does_not_import_ms_reader(self):
        script = '''
import sys
from gcviewer.parsers.spl import match_rows_to_raw
match_rows_to_raw([], '.')
assert 'rainbow' not in sys.modules
assert 'scipy' not in sys.modules
assert 'pandas' not in sys.modules
assert not any(n.startswith('PySide6') for n in sys.modules)
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
