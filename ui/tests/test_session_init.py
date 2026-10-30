import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from ui.session_init import CORE, MAX_CONTEXT_BYTES, MAX_INPUT_BYTES, ROOT, SKILLS, SOURCES, initialize


class UIInitializationTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'ui/runtime/tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='ui init with spaces ', dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in CORE + ('ui/session_init.py',) + tuple('ui/skills/{}/SKILL.md'.format(s) for s in SKILLS):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        links = self.root / '.agents/skills'
        links.mkdir(parents=True)
        for name in SKILLS:
            (links / name).symlink_to('../../ui/skills/' + name, target_is_directory=True)
        self.event = {'hook_event_name': 'SessionStart', 'source': 'startup', 'cwd': str(self.root)}

    def check_failure(self, result):
        self.assertIn('UI_INIT_FAILED', result['systemMessage'])
        self.assertNotIn('UI_INIT_OK', json.dumps(result))
        self.assertTrue(result['continue'])
        return result['hookSpecificOutput']['additionalContext']

    def protocol(self, raw):
        result = subprocess.run([sys.executable, '-B', str(self.root / 'ui/session_init.py')],
                                input=raw, capture_output=True, timeout=3,
                                env={**os.environ, 'TMPDIR': str(self.root), 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b'')
        self.assertEqual(len(result.stdout.splitlines()), 1)
        return json.loads(result.stdout)

    def test_happy_path_visible_status_compact_context_no_full_skill_bodies(self):
        result = initialize(self.root, self.event)
        self.assertIn('UI_INIT_OK', result['systemMessage'])
        context = result['hookSpecificOutput']['additionalContext']
        for name in CORE:
            self.assertIn((self.root / name).read_text(), context)
        for name in SKILLS:
            self.assertNotIn((self.root / 'ui/skills' / name / 'SKILL.md').read_text(), context)
        self.assertLess(len(context.encode()), MAX_CONTEXT_BYTES + 1024)

    def test_all_sources_and_nested_directory(self):
        nested = self.root / 'component/nested'
        nested.mkdir(parents=True)
        for source in SOURCES:
            result = initialize(self.root, {**self.event, 'source': source, 'cwd': str(nested)})
            self.assertIn('UI_INIT_OK', result['systemMessage'])

    def test_missing_policy_and_broken_discovery_are_actionable(self):
        (self.root / 'ui/ROUTING.md').unlink()
        (self.root / '.agents/skills/shadcn').unlink()
        context = self.check_failure(initialize(self.root, self.event))
        self.assertIn('ui/ROUTING.md', context)
        self.assertIn('ui/skills/shadcn/SKILL.md', context)

    def test_escaped_source_is_not_read_or_echoed(self):
        outside = self.root.parent / (self.root.name + '-outside')
        outside.write_text('SYNTHETIC_PRIVATE_CANARY')
        self.addCleanup(outside.unlink)
        policy = self.root / 'ui/AGENTS.md'
        policy.unlink()
        policy.symlink_to(outside)
        result = initialize(self.root, self.event)
        self.check_failure(result)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(result))
        self.assertNotIn(str(outside), json.dumps(result))

    def test_escaped_or_nonsymlink_discovery_is_rejected(self):
        link = self.root / '.agents/skills/shadcn'
        link.unlink()
        link.symlink_to(ROOT / 'ui/skills/shadcn', target_is_directory=True)
        self.check_failure(initialize(self.root, self.event))
        link.unlink()
        link.mkdir()
        self.check_failure(initialize(self.root, self.event))

    def test_symlink_to_other_workspace_data_is_not_loaded(self):
        private = self.root / 'private-data.txt'
        private.write_text('SYNTHETIC_PRIVATE_CANARY')
        policy = self.root / 'ui/AGENTS.md'
        policy.unlink()
        policy.symlink_to(private)
        result = initialize(self.root, self.event)
        self.check_failure(result)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(result))

    def test_invalid_skill_name_duplicate_metadata_and_encoding_fail(self):
        target = self.root / 'ui/skills/shadcn/SKILL.md'
        original = target.read_text()
        for data in [original.replace('name: shadcn', 'name: wrong').encode(),
                     original.replace('name: shadcn', 'name: shadcn\nname: wrong').encode(), b'\xff']:
            target.write_bytes(data)
            self.check_failure(initialize(self.root, self.event))

    def test_invalid_event_source_and_foreign_cwd_are_not_echoed(self):
        for event in [{}, None, [], {**self.event, 'hook_event_name': 'Stop'},
                      {**self.event, 'source': 'SYNTHETIC_PRIVATE_CANARY'},
                      {**self.event, 'cwd': '/'}, {**self.event, 'cwd': '../relative'}]:
            result = initialize(self.root, event)
            self.check_failure(result)
            self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(result))

    def test_empty_and_oversize_sources_fail_before_output(self):
        target = self.root / 'ui/AGENTS.md'
        for data in ['', 'x' * 65537, 'x' * (MAX_CONTEXT_BYTES + 1)]:
            target.write_text(data)
            self.check_failure(initialize(self.root, self.event))

    def test_subprocess_protocol_success_and_no_side_effects(self):
        before = {str(p.relative_to(self.root)) for p in self.root.rglob('*')}
        result = self.protocol(json.dumps(self.event).encode())
        self.assertIn('UI_INIT_OK', result['systemMessage'])
        self.assertEqual(before, {str(p.relative_to(self.root)) for p in self.root.rglob('*')})

    def test_subprocess_invalid_oversize_duplicate_and_nonobject_input(self):
        for raw in [b'', b'{bad', b'\xff', b'[]', b'null', b'"string"',
                    b'{"cwd":"one","cwd":"two"}', b'x' * (MAX_INPUT_BYTES + 1)]:
            self.check_failure(self.protocol(raw))


if __name__ == '__main__':
    unittest.main()
