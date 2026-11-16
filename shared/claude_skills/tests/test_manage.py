import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.claude_skills.manage import ROOT, InstallError, configure, entries


class SkillInstallTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / 'ui/runtime/claude-skills-tests'
        runtime.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=runtime)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.skills = self.base / 'skills'
        self.sources = entries()

    def test_complete_source_set(self):
        self.assertEqual(len(self.sources), 32)
        self.assertEqual(sum('/mentor/skills/' in str(p) for p in self.sources.values()), 6)
        self.assertEqual(sum('/ui/skills/' in str(p) for p in self.sources.values()), 22)

    def test_install_check_and_idempotency(self):
        self.assertEqual(configure(self.skills, self.sources, install=True), 32)
        original = {p.name: (p.lstat().st_ino, os.readlink(p)) for p in self.skills.iterdir()}
        self.assertEqual(configure(self.skills, self.sources), 0)
        self.assertEqual(configure(self.skills, self.sources, install=True), 0)
        self.assertEqual(original, {p.name: (p.lstat().st_ino, os.readlink(p)) for p in self.skills.iterdir()})
        for name, source in self.sources.items():
            self.assertEqual((self.skills / name / 'SKILL.md').read_bytes(), (source / 'SKILL.md').read_bytes())

    def test_check_never_installs(self):
        with self.assertRaisesRegex(InstallError, 'missing_links:'):
            configure(self.skills, self.sources)
        self.assertFalse(self.skills.exists())

    def test_foreign_directory_is_preserved_before_any_install(self):
        foreign = self.skills / 'shadcn'
        foreign.mkdir(parents=True)
        (foreign / 'custom.txt').write_text('user content')
        with self.assertRaisesRegex(InstallError, 'destination_conflict:shadcn'):
            configure(self.skills, self.sources, install=True)
        self.assertEqual([p.name for p in self.skills.iterdir()], ['shadcn'])
        self.assertEqual((foreign / 'custom.txt').read_text(), 'user content')

    def test_broken_link_is_preserved(self):
        self.skills.mkdir()
        foreign = self.skills / 'shadcn'
        foreign.symlink_to('missing-user-directory')
        with self.assertRaisesRegex(InstallError, 'destination_conflict:shadcn'):
            configure(self.skills, self.sources, install=True)
        self.assertEqual(os.readlink(foreign), 'missing-user-directory')
        self.assertEqual(len(list(self.skills.iterdir())), 1)

    def test_missing_source_is_rejected_before_writes(self):
        sources = dict(self.sources)
        sources['shadcn'] = self.base / 'missing-source'
        with self.assertRaisesRegex(InstallError, 'missing_source:shadcn'):
            configure(self.skills, sources, install=True)
        self.assertFalse(self.skills.exists())

    def test_incomplete_checkout_fails(self):
        with self.assertRaisesRegex(InstallError, 'incomplete_source_set'):
            entries(self.base)

    def test_symlink_root_is_not_followed(self):
        other = self.base / 'other'
        other.mkdir()
        self.skills.symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(InstallError, 'unsafe_skills_root'):
            configure(self.skills, self.sources, install=True)
        self.assertEqual(list(other.iterdir()), [])

    def test_partial_io_failure_rolls_back_new_links(self):
        original = Path.symlink_to
        calls = []

        def interrupted(path, target, target_is_directory=False):
            calls.append(path)
            if len(calls) == 4:
                raise OSError(5, 'synthetic link failure')
            return original(path, target, target_is_directory=target_is_directory)

        with patch.object(Path, 'symlink_to', interrupted):
            with self.assertRaises(OSError):
                configure(self.skills, self.sources, install=True)
        self.assertFalse(self.skills.exists())

    def test_failure_preserves_existing_and_concurrent_replacement(self):
        self.skills.mkdir()
        existing_name = next(iter(self.sources))
        existing = self.skills / existing_name
        existing.symlink_to(self.sources[existing_name], target_is_directory=True)
        inode = existing.lstat().st_ino
        original = Path.symlink_to
        created = []

        def interrupted(path, target, target_is_directory=False):
            if len(created) == 2:
                # Replace one new link with an unrelated user directory before failure.
                created[0].unlink()
                created[0].mkdir()
                (created[0] / 'custom.txt').write_text('concurrent content')
                raise OSError(5, 'synthetic link failure')
            created.append(path)
            return original(path, target, target_is_directory=target_is_directory)

        with patch.object(Path, 'symlink_to', interrupted):
            with self.assertRaises(OSError):
                configure(self.skills, self.sources, install=True)
        self.assertEqual(existing.lstat().st_ino, inode)
        self.assertEqual((created[0] / 'custom.txt').read_text(), 'concurrent content')
        self.assertFalse(os.path.lexists(created[1]))


if __name__ == '__main__':
    unittest.main()
