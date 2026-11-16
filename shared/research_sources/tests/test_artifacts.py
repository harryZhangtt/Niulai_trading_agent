"""Future-write permission, containment, and unknown-outcome checks."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from shared.research_sources import artifacts
from shared.research_sources.artifacts import (
    ROOT, SOURCE_STATE, PublicationOutcomeUnknown, SourceError,
    atomic_write_private, private_path, publish_json_command, save,
)
from shared.research_sources.store import Store


def mode(path):
    return stat.S_IMODE(Path(path).stat().st_mode)


@contextmanager
def umask(value):
    previous = os.umask(value)
    try:
        yield
    finally:
        os.umask(previous)


class ArtifactPermissionTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def test_new_json_html_temp_and_directories_are_private_under_extreme_umask(self):
        pending_modes = []
        real_link = os.link

        def checked_link(source, destination, **kwargs):
            parent_fd = kwargs['src_dir_fd']
            pending_modes.append(stat.S_IMODE(os.stat(source, dir_fd=parent_fd,
                                                       follow_symlinks=False).st_mode))
            return real_link(source, destination, **kwargs)

        nested = self.directory / 'new' / 'artifacts'
        with umask(0o777), patch.object(artifacts.os, 'link', side_effect=checked_link):
            json_ref = save(nested, {'synthetic': True})
            html_ref = save(nested, b'<html>synthetic</html>', suffix='html')

        self.assertEqual(mode(self.directory / 'new'), 0o700)
        self.assertEqual(mode(nested), 0o700)
        self.assertEqual(mode(json_ref['path']), 0o600)
        self.assertEqual(mode(html_ref['path']), 0o600)
        self.assertEqual(pending_modes, [0o600, 0o600])

    def test_temp_mode_failure_cleans_pending_file(self):
        with patch.object(artifacts.os, 'fchmod', side_effect=OSError('synthetic chmod failure')):
            with self.assertRaisesRegex(OSError, 'synthetic chmod failure'):
                save(self.directory, b'unpublished', suffix='txt')
        self.assertEqual(list(self.directory.glob('.pending-*')), [])
        self.assertEqual(list(self.directory.glob('*.txt')), [])

    def test_existing_history_is_not_recursively_chmodded(self):
        history = self.directory / 'history'
        history.mkdir(); history.chmod(0o755)
        sentinel = history / 'sentinel.txt'
        sentinel.write_bytes(b'preserve historical bytes'); sentinel.chmod(0o644)

        with umask(0o777):
            destination = private_path(history / 'new' / 'destination', create=True)

        self.assertEqual(mode(history), 0o755)
        self.assertEqual(mode(sentinel), 0o644)
        self.assertEqual(sentinel.read_bytes(), b'preserve historical bytes')
        self.assertEqual(mode(history / 'new'), 0o700)
        self.assertEqual(mode(destination), 0o700)

    def test_existing_destination_requires_exact_private_mode_without_repair(self):
        destination = self.directory / 'permissive-destination'
        destination.mkdir(); destination.chmod(0o755)
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_DIRECTORY_MODE_REJECTED'):
            private_path(destination, create=True)
        self.assertEqual(mode(destination), 0o755)

    def test_mkdir_race_to_symlink_is_rejected_without_chmodding_target(self):
        target = self.directory / 'target'; target.mkdir(mode=0o700)
        target.chmod(0o755)
        real_mkdir = os.mkdir

        def raced(name, requested, *, dir_fd=None):
            if name == 'raced':
                os.symlink(target, name, target_is_directory=True, dir_fd=dir_fd)
                raise FileExistsError(name)
            return real_mkdir(name, requested, dir_fd=dir_fd)

        with patch.object(artifacts.os, 'mkdir', side_effect=raced):
            with self.assertRaisesRegex(SourceError, 'ARTIFACT_SYMLINK_REJECTED'):
                private_path(self.directory / 'raced', create=True)
        self.assertEqual(mode(target), 0o755)

    def test_atomic_writer_failures_preserve_prior_and_pending_identity(self):
        destination = self.directory / 'pointer.json'
        destination.write_bytes(b'old bytes'); destination.chmod(0o644)
        with patch.object(artifacts.os, 'replace', side_effect=OSError('synthetic replace failure')):
            with self.assertRaisesRegex(OSError, 'synthetic replace failure'):
                atomic_write_private(destination, b'new bytes')
        self.assertEqual((destination.read_bytes(), mode(destination)), (b'old bytes', 0o644))
        self.assertEqual(list(self.directory.glob('.pointer.json.pending-*')), [])


    def test_post_replace_fsync_failure_is_unknown_with_readback(self):
        destination = self.directory / 'pointer.json'
        atomic_write_private(destination, b'old')
        real_fsync = os.fsync

        def fail_directory(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError('synthetic parent fsync failure')
            return real_fsync(descriptor)

        with patch.object(artifacts.os, 'fsync', side_effect=fail_directory):
            with self.assertRaisesRegex(PublicationOutcomeUnknown,
                                        'ARTIFACT_PUBLICATION_OUTCOME_UNKNOWN') as raised:
                atomic_write_private(destination, b'new')
        self.assertFalse(raised.exception.evidence['replay_safe'])
        self.assertTrue(raised.exception.evidence['matches_expected'])
        self.assertEqual(destination.read_bytes(), b'new')

    def test_hardlink_fsync_failure_is_unknown_and_existing_cas_must_be_private(self):
        real_fsync = os.fsync

        def fail_directory(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise OSError('synthetic parent fsync failure')
            return real_fsync(descriptor)

        with patch.object(artifacts.os, 'fsync', side_effect=fail_directory):
            with self.assertRaisesRegex(PublicationOutcomeUnknown,
                                        'ARTIFACT_PUBLICATION_OUTCOME_UNKNOWN') as raised:
                save(self.directory, b'unknown publication', suffix='txt')
        self.assertFalse(raised.exception.evidence['replay_safe'])
        self.assertTrue(raised.exception.evidence['matches_expected'])

        ref = save(self.directory, b'existing historical mode', suffix='txt')
        Path(ref['path']).chmod(0o644)
        before = Path(ref['path']).read_bytes()
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_EXISTING_FILE_REJECTED'):
            save(self.directory, b'existing historical mode', suffix='txt')
        self.assertEqual((Path(ref['path']).read_bytes(), mode(ref['path'])), (before, 0o644))

    def test_cas_reuse_binds_validated_inode_to_returned_name(self):
        raw = b'cas identity binding'
        ref = save(self.directory, raw, suffix='txt')
        target = Path(ref['path'])
        displaced = target.with_suffix('.displaced')
        real_read = artifacts._read_fd
        swapped = False

        def swap_after_read(descriptor, **kwargs):
            nonlocal swapped
            value = real_read(descriptor, **kwargs)
            if not swapped and os.fstat(descriptor).st_ino == target.stat().st_ino:
                swapped = True
                target.rename(displaced)
                target.write_bytes(b'wrong')
                target.chmod(0o600)
            return value

        with patch.object(artifacts, '_read_fd', side_effect=swap_after_read):
            with self.assertRaisesRegex(SourceError, 'ARTIFACT_NAMESPACE_CHANGED'):
                save(self.directory, raw, suffix='txt')
        self.assertEqual(target.read_bytes(), b'wrong')
        self.assertEqual(displaced.read_bytes(), raw)

    def test_producer_failure_or_invalid_json_preserves_old_pointer(self):
        destination = self.directory / 'contract.json'
        atomic_write_private(destination, b'{"old":true}')
        old = destination.read_bytes()
        validator = lambda value: artifacts.require(value == {'ok': True}, 'SYNTHETIC_CONTRACT_INVALID')
        failing = [sys.executable, '-c', 'import sys;print("{\\"partial\\":");sys.exit(7)']
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_PRODUCER_FAILED'):
            publish_json_command(destination, failing, validator=validator)
        self.assertEqual(destination.read_bytes(), old)
        malformed = [sys.executable, '-c', 'print("not-json")']
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_PRODUCER_JSON_INVALID'):
            publish_json_command(destination, malformed, validator=validator)
        self.assertEqual(destination.read_bytes(), old)
        self.assertEqual(list(self.directory.glob('.producer-*')), [])

    def test_producer_success_validates_and_publishes_same_private_inode(self):
        destination = self.directory / 'contract.json'
        code = ('import json,os,stat; assert stat.S_IMODE(os.fstat(1).st_mode)==0o600; '
                'print(json.dumps({"ok":True}))')
        observed = {}
        real_replace = os.replace

        def validator(item):
            artifacts.require(item == {'ok': True}, 'SYNTHETIC_CONTRACT_INVALID')
            pending = list(self.directory.glob('.producer-*'))
            self.assertEqual(len(pending), 1)
            observed['validated_inode'] = pending[0].stat().st_ino
            observed['validated_bytes'] = pending[0].read_bytes()

        def checked_replace(source, destination_name, **kwargs):
            if source.startswith('.producer-'):
                observed['published_inode'] = os.stat(
                    source, dir_fd=kwargs['src_dir_fd'], follow_symlinks=False).st_ino
            return real_replace(source, destination_name, **kwargs)

        with umask(0o777), patch.object(artifacts.os, 'replace', side_effect=checked_replace):
            value = publish_json_command(destination, [sys.executable, '-c', code], validator=validator)
        self.assertEqual(value, {'ok': True})
        self.assertEqual(observed['validated_inode'], observed['published_inode'])
        self.assertEqual(observed['validated_bytes'], destination.read_bytes())
        self.assertEqual((json.loads(destination.read_text()), mode(destination)), ({'ok': True}, 0o600))

    def test_symlink_components_leaf_and_outside_path_are_rejected(self):
        target = self.directory / 'target'; target.mkdir(mode=0o700)
        component = self.directory / 'linked'; component.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_SYMLINK_REJECTED'):
            private_path(component / 'child', create=True)
        target_file = self.directory / 'target.json'; target_file.write_bytes(b'unchanged')
        leaf = self.directory / 'leaf.json'; leaf.symlink_to(target_file)
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_SYMLINK_REJECTED'):
            atomic_write_private(leaf, b'rejected')
        self.assertEqual(target_file.read_bytes(), b'unchanged')
        with self.assertRaisesRegex(SourceError, 'ARTIFACT_PATH_REJECTED'):
            atomic_write_private(ROOT / 'outside-private-artifact-test.json', b'rejected')

    def test_sqlite_new_primary_is_private_under_umask_022(self):
        with umask(0o022):
            store = Store(self.directory / 'store')
        self.assertEqual(mode(store.directory), 0o700)
        self.assertEqual(mode(store.blobs), 0o700)
        self.assertEqual(mode(store.path), 0o600)
        # New-primary coverage only. Store owns existing-primary chmod/reopen and
        # SQLite journal/WAL governance; this test makes no historical-mode claim.


if __name__ == '__main__':
    unittest.main()
