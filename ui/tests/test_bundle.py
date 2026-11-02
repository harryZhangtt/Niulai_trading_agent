import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch
import tempfile
import unittest
from verify_bundle import verify


class BundleTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / 'runtime/tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'upstream').mkdir()
        self.resource = self.root / 'skills/example/SKILL.md'
        self.resource.parent.mkdir(parents=True)
        self.resource.write_text('Evidence-bearing local fixture\n')
        self.manifest = {'repositories': {'test': {'commit': 'a' * 40, 'license': 'MIT'}},
                         'files': [{'path': 'skills/example/SKILL.md', 'repository': 'test',
                                    'local_sha256': hashlib.sha256(self.resource.read_bytes()).hexdigest()}]}
        self.write()

    def write(self):
        (self.root / 'upstream/sources.lock.json').write_text(json.dumps(self.manifest))

    def test_valid_snapshot(self):
        self.assertEqual(verify(self.root), [])

    def test_corrupted_resource_is_rejected(self):
        self.resource.write_text('Changed without source review')
        self.assertTrue(any('unreviewed change' in e for e in verify(self.root)))

    def test_outside_resource_is_rejected(self):
        self.manifest['files'][0]['path'] = '../../outside'
        self.write()
        self.assertTrue(any('unsafe path' in e for e in verify(self.root)))

    def test_broken_dependency_is_rejected(self):
        self.resource.write_text('[required](absent.md)')
        self.manifest['files'][0]['local_sha256'] = hashlib.sha256(self.resource.read_bytes()).hexdigest()
        self.write()
        self.assertTrue(any('broken link' in e for e in verify(self.root)))

    def test_added_unpinned_resource_is_rejected(self):
        (self.resource.parent / 'unreviewed.md').write_text('unreviewed')
        self.assertTrue(any('untracked resource' in e for e in verify(self.root)))

    def test_explicit_local_adapter_is_supported_without_exempting_imports(self):
        local = self.resource.parent / 'adapter.md'
        local.write_text('Workspace-authored procedure')
        self.manifest['local_files'] = ['skills/example/adapter.md']
        self.write()
        self.assertEqual(verify(self.root), [])
        (self.resource.parent / 'unreviewed.js').write_text('unreviewed source')
        self.assertTrue(any('untracked resource' in e for e in verify(self.root)))

    def test_rejected_markdown_symlink_is_never_opened_or_echoed(self):
        outside = self.root.parent / (self.root.name + '-outside.md')
        outside.write_text('[SYNTHETIC_PRIVATE_CANARY](secret-reference.md)')
        self.addCleanup(outside.unlink)
        self.resource.unlink()
        self.resource.symlink_to(outside)
        original = Path.open

        def checked_open(path, *args, **kwargs):
            self.assertNotEqual(path.resolve(), outside.resolve(), 'Rejected Markdown was read')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'open', checked_open):
            errors = verify(self.root)
        self.assertTrue(any('unsafe' in error for error in errors))
        self.assertNotIn('secret-reference', json.dumps(errors))
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(errors))

    def test_existing_escaped_markdown_link_is_rejected(self):
        outside = self.root.parent / (self.root.name + '-outside.md')
        outside.write_text('Synthetic external resource')
        self.addCleanup(outside.unlink)
        self.resource.write_text('[resource](../../../' + outside.name + ')')
        self.manifest['files'][0]['local_sha256'] = hashlib.sha256(self.resource.read_bytes()).hexdigest()
        self.write()
        self.assertTrue(any('escaped link' in error for error in verify(self.root)))

    def test_nonregular_and_escaped_manifest_fail_without_reading(self):
        script = self.root / 'tests/verify_bundle.py'
        script.parent.mkdir()
        shutil.copyfile(Path(__file__).with_name('verify_bundle.py'), script)
        manifest = self.root / 'upstream/sources.lock.json'
        original = manifest.read_bytes()
        manifest.unlink()
        os.mkfifo(manifest)
        try:
            result = subprocess.run([sys.executable, '-B', str(script)],
                                    capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 1)
            self.assertIn('unsafe or invalid provenance manifest', result.stdout)
        finally:
            manifest.unlink()
        outside = self.root.parent / (self.root.name + '-manifest.json')
        outside.write_bytes(original)
        self.addCleanup(outside.unlink)
        manifest.symlink_to(outside)
        self.assertEqual(verify(self.root), ['unsafe or invalid provenance manifest'])


if __name__ == '__main__':
    unittest.main()
