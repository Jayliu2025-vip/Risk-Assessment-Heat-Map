"""Process-level resource defaults for the desktop entrypoint."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DesktopRuntimeTests(unittest.TestCase):
    def test_blas_thread_default_is_set_before_numpy_import_without_overriding_user(self):
        code = '''
import importlib.abc, json, os, sys
seen = []
class Probe(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'numpy':
            seen.append(os.environ.get('OPENBLAS_NUM_THREADS'))
sys.meta_path.insert(0, Probe())
import desktop.app
print(json.dumps({'value':os.environ.get('OPENBLAS_NUM_THREADS'), 'at_import':seen}))
'''
        for existing in (None, "3"):
            with self.subTest(existing=existing):
                env = os.environ.copy()
                if existing is None:
                    env.pop("OPENBLAS_NUM_THREADS", None)
                else:
                    env["OPENBLAS_NUM_THREADS"] = existing
                completed = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                                           text=True, capture_output=True, check=True)
                result = json.loads(completed.stdout)
                self.assertEqual(result["value"], existing or "1")
                self.assertTrue(result["at_import"])
                self.assertEqual(set(result["at_import"]), {existing or "1"})
