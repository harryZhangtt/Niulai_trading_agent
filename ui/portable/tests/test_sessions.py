"""Independent native-thread receipt checks; all writes stay in UI unit runtime."""
import concurrent.futures
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

AREA = Path(__file__).resolve().parents[1]
WORKSPACE = AREA.parents[1]
RUNTIME = WORKSPACE / 'ui/runtime/harry-ui-persistence-20261102/unit'
sys.path.insert(0, str(AREA))
spec = importlib.util.spec_from_file_location('session_under_test', AREA / 'templates/session.py')
sessions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sessions)
from verify import verify


def make_bundle(root):
    root.mkdir()
    content = {'SKILL.md': '---\nname: harry-ui-skill-set\ndescription: UI test fixture.\n---\n',
               'ROUTING-CARD.md': '# Test routing\n'}
    skills = {f'expert-{i}': {} for i in range(22)}
    content['catalog.json'] = json.dumps({'skills': skills})
    content.update({f'experts/{name}/GUIDE.md': '# Fixture\n' for name in skills})
    for name, text in content.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    manifest = {'schema_version': 1, 'name': 'harry-ui-skill-set', 'expert_count': 22,
                'decision_count': 23, 'routing_card_sha256': hashlib.sha256(content['ROUTING-CARD.md'].encode()).hexdigest(),
                'files': {name: {'sha256': hashlib.sha256(text.encode()).hexdigest()}
                          for name, text in content.items()}}
    (root / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True))
    assert verify(root) == []
    return root


class SessionTests(unittest.TestCase):
    def setUp(self):
        RUNTIME.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=RUNTIME)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = make_bundle(self.root / 'bundle')
        self.project = self.root / 'project'
        self.project.mkdir()

    def run_session(self, action='restore', thread='thread-A', project=None):
        values = {} if thread is None else {'CODEX_THREAD_ID': thread}
        with mock.patch.dict(os.environ, values, clear=True):
            return sessions.session(project or self.project, action, root=self.bundle)

    def record(self, thread='thread-A', project=None):
        key = hashlib.sha256(('harry-ui-thread-v1:' + thread).encode()).hexdigest()
        return (project or self.project) / '.ui-skill-runtime/harry-ui-sessions' / (key + '.json')

    def change_bundle(self):
        guide = self.bundle / 'experts/expert-0/GUIDE.md'
        guide.write_text('# Changed fixture\n')
        manifest = json.loads((self.bundle / 'manifest.json').read_text())
        manifest['files']['experts/expert-0/GUIDE.md']['sha256'] = hashlib.sha256(guide.read_bytes()).hexdigest()
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True))
        self.assertEqual(verify(self.bundle), [])

    def test_absent_thread_is_inactive_and_restore_does_not_create_state(self):
        self.assertEqual(self.run_session()['status'], 'HARRY_UI_SESSION_INACTIVE')
        self.assertEqual(list(self.project.iterdir()), [])

    def test_missing_invalid_identity_has_no_shared_session_fallback(self):
        for thread in (None, '', '../escape', 'a/b', 'a' * 129, 'native id'):
            with self.subTest(thread=thread):
                self.assertEqual(self.run_session('enable', thread)['code'], 'native_thread_identity_unavailable')
        with mock.patch.dict(os.environ, {'CODEX_SESSION_ID': 'session-tree', 'SESSION_ID': 'ambient'}, clear=True):
            self.assertEqual(sessions.session(self.project, 'enable', root=self.bundle)['code'],
                             'native_thread_identity_unavailable')
        self.assertEqual(list(self.project.iterdir()), [])

    def test_enable_once_restore_is_read_only_and_bundle_is_immutable(self):
        before = {str(p.relative_to(self.bundle)): p.read_bytes() for p in self.bundle.rglob('*') if p.is_file()}
        result = self.run_session('enable')
        self.assertEqual(result['status'], 'HARRY_UI_SESSION_ENABLED')
        self.assertTrue(result['new_activation'])
        record = self.record()
        original = (record.read_bytes(), record.stat().st_mtime_ns)
        self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
        self.assertEqual(record.parent.joinpath('.gitignore').read_bytes(), b'*\n')
        for action in ('restore', 'enable'):
            restored = self.run_session(action)
            self.assertEqual(restored['state'], 'enabled')
            self.assertFalse(restored['new_activation'])
            self.assertFalse(restored['state_changed'])
            self.assertEqual((record.read_bytes(), record.stat().st_mtime_ns), original)
        self.assertEqual(before, {str(p.relative_to(self.bundle)): p.read_bytes() for p in self.bundle.rglob('*') if p.is_file()})
        state = json.loads(record.read_text())
        self.assertNotIn('thread-A', record.read_text())
        self.assertEqual(set(state), sessions.FIELDS)

    def test_native_threads_and_target_projects_are_isolated(self):
        self.run_session('enable')
        first = self.record().read_bytes()
        self.assertEqual(self.run_session(thread='thread-B')['status'], 'HARRY_UI_SESSION_INACTIVE')
        self.assertEqual(self.run_session('disable', thread='thread-B')['state'], 'disabled')
        self.assertEqual(self.run_session()['state'], 'enabled')
        self.assertEqual(self.record().read_bytes(), first)
        other = self.root / 'other-project'
        other.mkdir()
        self.assertEqual(self.run_session(project=other)['status'], 'HARRY_UI_SESSION_INACTIVE')
        self.assertEqual(list(other.iterdir()), [])

    def test_disable_survives_changed_bundle_then_explicit_reenable(self):
        self.run_session('enable')
        disabled = self.run_session('disable')
        self.assertEqual(disabled['status'], 'HARRY_UI_SESSION_DISABLED')
        record = self.record()
        original = record.read_bytes()
        self.change_bundle()
        restored = self.run_session()
        self.assertEqual(restored['status'], 'HARRY_UI_SESSION_DISABLED')
        self.assertFalse(restored['state_changed'])
        self.assertEqual(record.read_bytes(), original)
        enabled = self.run_session('enable')
        self.assertTrue(enabled['new_activation'])
        self.assertTrue(enabled['state_changed'])
        self.assertNotEqual(json.loads(record.read_text())['bundle_fingerprint'],
                            json.loads(original)['bundle_fingerprint'])

    def test_enabled_changed_fingerprint_revalidates_without_new_activation(self):
        self.run_session('enable')
        self.change_bundle()
        restored = self.run_session()
        self.assertEqual(restored['status'], 'HARRY_UI_SESSION_ACTIVE')
        self.assertTrue(restored['state_changed'])
        self.assertFalse(restored['new_activation'])

    def test_unknown_or_malformed_state_is_preserved_for_every_action(self):
        self.run_session('enable')
        valid = json.loads(self.record().read_text())
        variants = []
        for field, value in [('schema_version', True), ('state', 'unknown'), ('thread_key', 'other'),
                             ('project_key', 'other'), ('bundle_fingerprint', 'bad'),
                             ('created_at', '2026-11-02'), ('updated_at', None)]:
            modified = dict(valid, **{field: value})
            variants.append(json.dumps(modified).encode())
        variants += [b'{"schema_version":1,"schema_version":1}', b'not json', b'\xff', b' ' * 8193,
                     json.dumps(dict(valid, extra='untrusted')).encode()]
        for raw in variants:
            for action in ('restore', 'enable', 'disable'):
                with self.subTest(raw=raw[:40], action=action):
                    self.record().write_bytes(raw)
                    result = self.run_session(action)
                    self.assertEqual(result['status'], 'HARRY_UI_SESSION_FAILED')
                    self.assertEqual(self.record().read_bytes(), raw)

    def test_scope_cannot_be_transferred_by_copying_record(self):
        self.run_session('enable')
        copied = self.record('thread-B')
        copied.write_bytes(self.record().read_bytes())
        copied.chmod(0o600)
        self.assertEqual(self.run_session(thread='thread-B')['code'], 'session_scope_mismatch')

    def test_group_writable_directory_or_public_state_is_rejected(self):
        self.run_session('enable')
        directory = self.record().parent
        directory.chmod(0o770)
        self.assertEqual(self.run_session()['code'], 'session_directory_writable')
        directory.chmod(0o700)
        self.record().chmod(0o644)
        self.assertEqual(self.run_session()['code'], 'session_state_unsafe')

    def test_symlink_directory_state_lock_and_ignore_cannot_escape(self):
        outside = self.root / 'outside'
        outside.mkdir()
        foreign = outside / 'foreign'
        foreign.write_text('preserve')
        runtime = self.project / '.ui-skill-runtime'
        runtime.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.run_session('enable')['status'], 'HARRY_UI_SESSION_FAILED')
        runtime.unlink()
        self.run_session('enable')
        record = self.record()
        raw = record.read_bytes()
        record.unlink()
        record.symlink_to(foreign)
        self.assertEqual(self.run_session()['status'], 'HARRY_UI_SESSION_FAILED')
        record.unlink()
        record.write_bytes(raw)
        record.chmod(0o600)
        lock = record.with_suffix('.lock')
        lock.unlink()
        lock.symlink_to(foreign)
        self.assertEqual(self.run_session()['status'], 'HARRY_UI_SESSION_FAILED')
        lock.unlink()
        ignored = record.parent / '.gitignore'
        ignored.unlink()
        ignored.symlink_to(foreign)
        self.assertEqual(self.run_session('enable')['status'], 'HARRY_UI_SESSION_FAILED')
        self.assertEqual(foreign.read_text(), 'preserve')
        self.assertEqual(record.read_bytes(), raw)

    def test_ignore_validation_is_bounded_and_precedes_state_commit(self):
        directory = self.project / '.ui-skill-runtime/harry-ui-sessions'
        directory.mkdir(parents=True)
        ignored = directory / '.gitignore'
        ignored.write_bytes(b'x' * 1024)
        result = self.run_session('enable')
        self.assertEqual(result['status'], 'HARRY_UI_SESSION_FAILED')
        self.assertFalse(self.record().exists())
        self.assertEqual(ignored.stat().st_size, 1024)
        self.assertFalse(list(directory.glob('.*pending-*')))

    def test_busy_lock_is_bounded_and_does_not_change_record(self):
        self.run_session('enable')
        before = self.record().read_bytes()
        with self.record().with_suffix('.lock').open('r+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_session('disable')['code'], 'session_busy')
        self.assertEqual(self.record().read_bytes(), before)

    def test_corrupt_bundle_never_writes_activation(self):
        (self.bundle / 'SKILL.md').write_text('tampered')
        self.assertEqual(self.run_session('enable')['code'], 'bundle_verification_failed')
        self.assertEqual(list(self.project.iterdir()), [])

    def test_atomic_write_failure_preserves_prior_state(self):
        self.run_session('enable')
        before = self.record().read_bytes()
        with mock.patch.object(sessions.os, 'replace', side_effect=OSError('injected')):
            self.assertEqual(self.run_session('disable')['status'], 'HARRY_UI_SESSION_FAILED')
        self.assertEqual(self.record().read_bytes(), before)
        self.assertFalse(list(self.record().parent.glob('.pending-*')))

    def test_two_processes_enable_different_native_threads_without_partial_ignore(self):
        code = ('import importlib.util,json,pathlib,sys;sys.path.insert(0,sys.argv[3]);'
                'spec=importlib.util.spec_from_file_location("receipt",sys.argv[3]+"/templates/session.py");'
                'm=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);'
                'print(json.dumps(m.session(sys.argv[1],"enable",root=pathlib.Path(sys.argv[2]))))')
        def invoke(thread):
            environment = {'PATH': os.environ.get('PATH', ''), 'CODEX_THREAD_ID': thread}
            result = subprocess.run([sys.executable, '-B', '-c', code, str(self.project),
                                     str(self.bundle), str(AREA)], env=environment,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(invoke, ['native-one', 'native-two']))
        self.assertEqual([r['status'] for r in results], ['HARRY_UI_SESSION_ENABLED'] * 2)
        self.assertTrue(self.record('native-one').is_file())
        self.assertTrue(self.record('native-two').is_file())
        directory = self.record().parent
        self.assertEqual((directory / '.gitignore').read_bytes(), b'*\n')
        self.assertFalse(list(directory.glob('.*pending-*')))


if __name__ == '__main__':
    unittest.main()
