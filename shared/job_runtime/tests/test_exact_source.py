"""Subprocess probes use stale unchecked-hash pyc, without touching live sources."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class ExactSourceTests(unittest.TestCase):
    def run_python(self, code):
        result = subprocess.run(
            [sys.executable, '-I', '-c', code], cwd=ROOT, capture_output=True,
            text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_ordinary_business_import_is_unattested(self):
        output = self.run_python(
            "import sys;sys.path.insert(0,'.');"
            "import shared.job_runtime.business as business;"
            "print(business.IMPLEMENTATION_SHA256)")
        self.assertEqual(output.strip(), 'None')

    def test_exact_loader_rejects_preloaded_ordinary_module(self):
        self.run_python("""
import sys
sys.path.insert(0, '.')
import shared.job_runtime.business as business
from shared.exact_source import load_exact
path = business.__file__
before = id(business)
try:
    load_exact('shared.job_runtime.business', path)
except ImportError as error:
    assert str(error) == 'EXACT_SOURCE_ALREADY_LOADED'
else:
    raise AssertionError('split identity accepted')
assert id(sys.modules['shared.job_runtime.business']) == before
""")

    def probe(self, package, child):
        with tempfile.TemporaryDirectory(dir=ROOT / '.job-runtime/tests') as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / 'shared', root / 'shared', ignore=shutil.ignore_patterns('__pycache__', 'tests'))
            shutil.copytree(ROOT / 'niulai-runtime/niulai_runtime', root / 'niulai_runtime',
                            ignore=shutil.ignore_patterns('__pycache__'))
            path = root / package.replace('.', '/') / (child + '.py')
            current = path.read_bytes() + b'\nEXACT_PROBE = "new"\n'
            stale = current.replace(b'EXACT_PROBE = "new"', b'EXACT_PROBE = "old"')
            self.assertEqual(len(current), len(stale))
            path.write_bytes(stale)
            cache_prefix = root / 'pycache'
            original_prefix = sys.pycache_prefix
            try:
                sys.pycache_prefix = str(cache_prefix)
                cache = Path(importlib.util.cache_from_source(str(path)))
            finally:
                sys.pycache_prefix = original_prefix
            py_compile.compile(str(path), cfile=str(cache), doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
            path.write_bytes(current)
            # First prove an ordinary loader selects the stale unchecked-hash pyc,
            # then import through the actual package initialization.
            code = '''
import importlib, importlib.machinery, json, sys
name = sys.argv[1]
path = sys.argv[2]
loader = importlib.machinery.SourceFileLoader(name, path)
assert 'old' in loader.get_code(name).co_consts
parent = importlib.import_module(name.rpartition('.')[0])
if name.endswith('.business'):
    from shared.exact_source import load_exact
    module = load_exact(name, path)
else:
    module = importlib.import_module(name)
assert getattr(parent, name.rpartition('.')[2]) is module is sys.modules[name]
assert importlib.import_module(name) is module
if name.endswith('.business'):
    service = importlib.import_module('shared.job_runtime.service')
    assert service.run_business is module.run_business
    assert service.service_generation()['implementations']['business'] == module.IMPLEMENTATION_SHA256
else:
    daily = importlib.import_module('niulai_runtime.daily_job')
    assert daily.gmail_claim is module.gmail_claim
print(json.dumps([module.EXACT_PROBE, module.IMPLEMENTATION_SHA256]))
'''
            env = dict(os.environ, PYTHONPATH=str(root), PYTHONPYCACHEPREFIX=str(cache_prefix))
            # Pin the child to the same temp cache path on macOS and other runtimes.
            env.pop('PYTHONDONTWRITEBYTECODE', None)
            result = subprocess.run([sys.executable, '-c', code, package + '.' + child, str(path)],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ['new', hashlib.sha256(current).hexdigest()])

    def test_business_unchecked_hash_stale_pyc(self):
        self.probe('shared.job_runtime', 'business')

    def test_delivery_unchecked_hash_stale_pyc(self):
        self.probe('niulai_runtime', 'delivery')
