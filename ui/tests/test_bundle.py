import hashlib
import json
from pathlib import Path
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


if __name__ == '__main__':
    unittest.main()
