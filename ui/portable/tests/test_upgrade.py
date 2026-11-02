"""Owned atomic exchanges use disposable directories inside the workspace only."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

AREA = Path(__file__).resolve().parents[1]
WORKSPACE = AREA.parents[1]
RUNTIME = WORKSPACE / 'ui/runtime/harry-ui-persistence-20261102/unit'
sys.path.insert(0, str(AREA))
from manage import install, upgrade, restore_upgrade, atomic_exchange, UpgradeError
import manage
from verify import verify, receipt_name
from test_sessions import make_bundle

NAME = 'harry-ui-skill-set'


def snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mode, p.read_bytes())
            for p in root.rglob('*') if p.is_file()}


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        RUNTIME.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=RUNTIME)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.old = make_bundle(self.root / 'old')
        self.new = make_bundle(self.root / 'new')
        guide = self.new / 'experts/expert-0/GUIDE.md'
        guide.write_text('# Candidate generation two\n')
        manifest = json.loads((self.new / 'manifest.json').read_text())
        manifest['files']['experts/expert-0/GUIDE.md']['sha256'] = hashlib.sha256(guide.read_bytes()).hexdigest()
        (self.new / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True))
        self.assertEqual(verify(self.new), [])
        self.skills = self.root / 'skills'
        self.stage = self.root / 'staging'
        self.skills.mkdir()
        self.stage.mkdir()
        self.installed = install(self.old, self.skills, self.stage, allowed_root=self.root)
        self.target = self.skills / NAME
        self.before = snapshot(self.target)
        self.inode = self.target.stat().st_ino

    def upgrade(self, **options):
        return upgrade(self.new, self.skills, self.stage, self.installed['installation_id'],
                       allowed_root=self.root, **options)

    def restore(self, result, **options):
        return restore_upgrade(self.skills, self.stage, result['installation_id'],
                               result['rollback_path'], result['rollback_installation_id'],
                               allowed_root=self.root, name=NAME, **options)

    def test_atomic_upgrade_retains_exact_old_inode_receipt_and_reversible_restore(self):
        result = self.upgrade()
        self.assertEqual(result['status'], 'upgraded')
        self.assertNotEqual(result['installation_id'], self.installed['installation_id'])
        self.assertEqual(verify(self.target), [])
        previous = Path(result['rollback_path'])
        self.assertEqual(previous.parent, self.stage)
        self.assertEqual(previous.stat().st_ino, self.inode)
        self.assertEqual(snapshot(previous), self.before)
        self.assertEqual(result['rollback_installation_id'], self.installed['installation_id'])
        replacement = snapshot(self.target)
        replacement_inode = self.target.stat().st_ino
        restored = self.restore(result)
        self.assertEqual(restored['status'], 'restored_previous_payload')
        self.assertEqual(self.target.stat().st_ino, self.inode)
        self.assertEqual(snapshot(self.target), self.before)
        self.assertEqual(previous.stat().st_ino, replacement_inode)
        self.assertEqual(snapshot(previous), replacement)
        self.assertEqual(restored['rollback_installation_id'], result['installation_id'])

    def test_current_exact_receipt_and_same_name_are_required(self):
        for identity in ('wrong', 'f' * 32, None):
            with self.subTest(identity=identity):
                with self.assertRaisesRegex(ValueError, 'ownership_mismatch'):
                    upgrade(self.new, self.skills, self.stage, identity, allowed_root=self.root)
        with self.assertRaisesRegex(ValueError, 'upgrade_identity_mismatch'):
            self.upgrade(name='ui-skill-router')
        self.assertEqual(snapshot(self.target), self.before)
        self.assertEqual(list(self.stage.iterdir()), [])

    def test_user_additions_edits_and_changed_receipt_block_upgrade_without_overwrite(self):
        paths = [('user-added.txt', b'preserve this addition'),
                 ('experts/expert-0/GUIDE.md', b'preserve this edit'),
                 (receipt_name(NAME), b'{"installation_id":"other"}')]
        for relative, changed in paths:
            with self.subTest(relative=relative):
                path = self.target / relative
                original = path.read_bytes() if path.exists() else None
                path.write_bytes(changed)
                altered = snapshot(self.target)
                with self.assertRaises(ValueError):
                    self.upgrade()
                self.assertEqual(snapshot(self.target), altered)
                self.assertEqual(list(self.stage.iterdir()), [])
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)

    def test_invalid_candidate_and_already_owned_source_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'source_contains_install_receipt'):
            upgrade(self.target, self.skills, self.stage, self.installed['installation_id'], allowed_root=self.root)
        (self.new / 'SKILL.md').write_text('corrupt')
        with self.assertRaisesRegex(ValueError, 'source_bundle_invalid'):
            self.upgrade()
        self.assertEqual(snapshot(self.target), self.before)
        self.assertEqual(list(self.stage.iterdir()), [])

    def test_staged_candidate_validation_happens_before_exchange(self):
        original = shutil.copytree
        def corrupt_after_copy(source, destination, *arguments, **options):
            copied = original(source, destination, *arguments, **options)
            if Path(source) == self.new:
                (Path(destination) / 'SKILL.md').write_text('corrupt staged copy')
            return copied
        with mock.patch.object(manage.shutil, 'copytree', side_effect=corrupt_after_copy):
            with self.assertRaisesRegex(ValueError, 'staged_bundle_invalid'):
                self.upgrade()
        self.assertEqual(snapshot(self.target), self.before)
        self.assertEqual(list(self.stage.iterdir()), [])

    def test_current_changes_during_staging_are_preserved_and_block_exchange(self):
        original = shutil.copytree
        def edit_during_copy(source, destination, *arguments, **options):
            copied = original(source, destination, *arguments, **options)
            if Path(source) == self.new:
                (self.target / 'user-added.txt').write_text('concurrent user change')
            return copied
        with mock.patch.object(manage.shutil, 'copytree', side_effect=edit_during_copy):
            with self.assertRaisesRegex(ValueError, 'owned_payload_changed'):
                self.upgrade()
        self.assertEqual((self.target / 'user-added.txt').read_text(), 'concurrent user change')
        self.assertEqual(self.target.stat().st_ino, self.inode)
        self.assertEqual(list(self.stage.iterdir()), [])

    def test_exchange_failure_leaves_current_payload_and_preserves_stage_for_reconciliation(self):
        with mock.patch.object(manage, 'atomic_exchange', side_effect=OSError('injected exchange failure')):
            with self.assertRaisesRegex(UpgradeError, 'outcome_requires_reconciliation') as failed:
                self.upgrade()
        self.assertEqual(snapshot(self.target), self.before)
        preserved = Path(failed.exception.recovery['preserved_path'])
        self.assertEqual(verify(preserved), [])
        self.assertNotEqual(preserved.stat().st_ino, self.inode)

    def test_interruption_after_native_swap_cannot_delete_prior_payload(self):
        def swap_then_interrupt(source, destination):
            atomic_exchange(source, destination)
            raise KeyboardInterrupt()
        with mock.patch.object(manage, 'atomic_exchange', side_effect=swap_then_interrupt):
            with self.assertRaisesRegex(UpgradeError, 'outcome_requires_reconciliation') as failed:
                self.upgrade()
        preserved = Path(failed.exception.recovery['preserved_path'])
        self.assertEqual(preserved.stat().st_ino, self.inode)
        self.assertEqual(snapshot(preserved), self.before)
        self.assertEqual(verify(self.target), [])
        self.assertTrue(failed.exception.recovery['reconcile_before_retry'])

    def test_post_exchange_old_mismatch_restores_and_preserves_user_changes(self):
        calls = []
        def exchange_then_edit(source, destination):
            atomic_exchange(source, destination)
            calls.append(1)
            if len(calls) == 1:
                (Path(source) / 'user-added.txt').write_text('old payload user change')
        with mock.patch.object(manage, 'atomic_exchange', side_effect=exchange_then_edit):
            with self.assertRaisesRegex(UpgradeError, 'post_exchange_mismatch_restored') as failed:
                self.upgrade()
        self.assertEqual(self.target.stat().st_ino, self.inode)
        self.assertEqual((self.target / 'user-added.txt').read_text(), 'old payload user change')
        retained = Path(failed.exception.recovery['preserved_path'])
        self.assertTrue(retained.is_dir())
        self.assertEqual(verify(retained), [])
        self.assertEqual(len(calls), 2)

    def test_post_exchange_new_mismatch_restores_and_keeps_displaced_evidence(self):
        calls = []
        def exchange_then_edit(source, destination):
            atomic_exchange(source, destination)
            calls.append(1)
            if len(calls) == 1:
                (Path(destination) / 'user-added.txt').write_text('new payload user change')
        with mock.patch.object(manage, 'atomic_exchange', side_effect=exchange_then_edit):
            with self.assertRaisesRegex(UpgradeError, 'post_exchange_mismatch_restored') as failed:
                self.upgrade()
        self.assertEqual(snapshot(self.target), self.before)
        retained = Path(failed.exception.recovery['preserved_path'])
        self.assertEqual((retained / 'user-added.txt').read_text(), 'new payload user change')
        self.assertTrue(failed.exception.recovery['reconcile_before_retry'])

    def test_failed_recovery_preserves_both_locations_and_marks_unknown_outcome(self):
        calls = []
        def fail_restoration(source, destination):
            calls.append(1)
            if len(calls) > 1:
                raise OSError('injected restoration failure')
            atomic_exchange(source, destination)
            (Path(destination) / 'user-added.txt').write_text('preserve candidate change')
        with mock.patch.object(manage, 'atomic_exchange', side_effect=fail_restoration):
            with self.assertRaisesRegex(UpgradeError, 'exchange_recovery_failed') as failed:
                self.upgrade()
        retained = Path(failed.exception.recovery['preserved_path'])
        self.assertEqual(snapshot(retained), self.before)
        self.assertEqual((self.target / 'user-added.txt').read_text(), 'preserve candidate change')
        self.assertTrue(failed.exception.recovery['reconcile_before_retry'])

    def test_restore_refuses_modified_current_or_retained_payload(self):
        result = self.upgrade()
        retained = Path(result['rollback_path'])
        (retained / 'user-added.txt').write_text('keep backup edit')
        current = snapshot(self.target)
        backup = snapshot(retained)
        with self.assertRaisesRegex(ValueError, 'owned_payload_changed'):
            self.restore(result)
        self.assertEqual(snapshot(self.target), current)
        self.assertEqual(snapshot(retained), backup)
        (retained / 'user-added.txt').unlink()
        (self.target / 'user-added.txt').write_text('keep live edit')
        with self.assertRaisesRegex(ValueError, 'owned_payload_changed'):
            self.restore(result)
        self.assertEqual((self.target / 'user-added.txt').read_text(), 'keep live edit')

    def test_restore_rejects_foreign_stage_and_wrong_ownership(self):
        result = self.upgrade()
        with self.assertRaisesRegex(ValueError, 'ownership_mismatch'):
            restore_upgrade(self.skills, self.stage, result['installation_id'], result['rollback_path'],
                            'f' * 32, allowed_root=self.root, name=NAME)
        other = self.root / 'other-stage'
        other.mkdir()
        with self.assertRaisesRegex(ValueError, 'rollback_path_not_owned_stage'):
            restore_upgrade(self.skills, self.stage, result['installation_id'], other,
                            result['rollback_installation_id'], allowed_root=self.root, name=NAME)

    def test_symlink_source_or_target_and_discovery_staging_are_rejected(self):
        linked = self.root / 'linked-bundle'
        linked.symlink_to(self.new, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'directory_unsafe'):
            upgrade(linked, self.skills, self.stage, self.installed['installation_id'], allowed_root=self.root)
        hidden = self.skills / 'hidden-stage'
        hidden.mkdir()
        with self.assertRaisesRegex(ValueError, 'staging_must_be_outside'):
            upgrade(self.new, self.skills, hidden, self.installed['installation_id'], allowed_root=self.root)
        retained = self.root / 'retained-live'
        self.target.rename(retained)
        self.target.symlink_to(retained, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'directory_unsafe'):
            self.upgrade()
        self.assertEqual(snapshot(retained), self.before)

    def test_upgrade_and_restore_cli_use_explicit_ids(self):
        arguments = ['--skills-root', str(self.skills), '--stage-parent', str(self.stage),
                     '--allowed-root', str(self.root), '--name', NAME]
        result = subprocess.run([sys.executable, '-B', str(AREA / 'manage.py'), 'upgrade',
                                 '--bundle', str(self.new), '--installation-id', self.installed['installation_id'],
                                 *arguments], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        upgraded = json.loads(result.stdout)
        self.assertEqual(upgraded['status'], 'upgraded')
        result = subprocess.run([sys.executable, '-B', str(AREA / 'manage.py'), 'restore-upgrade',
                                 '--installation-id', upgraded['installation_id'],
                                 '--rollback-path', upgraded['rollback_path'],
                                 '--rollback-installation-id', upgraded['rollback_installation_id'],
                                 *arguments], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'restored_previous_payload')
        self.assertEqual(snapshot(self.target), self.before)

    def test_legacy_router_identity_uses_the_same_owned_upgrade_contract(self):
        name = 'ui-skill-router'
        for bundle in (self.old, self.new):
            entry = bundle / 'SKILL.md'
            entry.write_text(entry.read_text().replace('name: ' + NAME, 'name: ' + name, 1))
            manifest = json.loads((bundle / 'manifest.json').read_text())
            manifest['name'] = name
            manifest['files']['SKILL.md']['sha256'] = hashlib.sha256(entry.read_bytes()).hexdigest()
            (bundle / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True))
        installed = install(self.old, self.skills, self.stage, allowed_root=self.root)
        before = snapshot(self.skills / name)
        result = upgrade(self.new, self.skills, self.stage, installed['installation_id'], allowed_root=self.root)
        self.assertEqual(result['name'], name)
        restore_upgrade(self.skills, self.stage, result['installation_id'], result['rollback_path'],
                        result['rollback_installation_id'], allowed_root=self.root, name=name)
        self.assertEqual(snapshot(self.skills / name), before)


if __name__ == '__main__':
    unittest.main()
