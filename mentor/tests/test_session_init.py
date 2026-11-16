import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from mentor.session_init import CORE, MAX_INPUT_BYTES, ROOT, SKILLS, initialize


class SessionInitTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'mentor/runtime/test-tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in CORE + tuple('mentor/skills/{}/SKILL.md'.format(skill) for skill in SKILLS):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        for catalog in ('.agents', '.claude'):
            links = self.root / catalog / 'skills'
            links.mkdir(parents=True)
            for name in SKILLS:
                (links / name).symlink_to('../../mentor/skills/' + name,
                                          target_is_directory=True)
        self.event = {
            'hook_event_name': 'SessionStart',
            'cwd': str(self.root),
            'source': 'startup',
            'session_id': 'session-test-123',
        }

    def result(self, event=None):
        return initialize(self.root, event or self.event)

    def context(self, event=None):
        return self.result(event)['hookSpecificOutput']['additionalContext']

    def test_loads_canonical_policy_router_and_visible_success(self):
        result = self.result()
        context = result['hookSpecificOutput']['additionalContext']
        self.assertEqual(result['systemMessage'], 'MENTOR_INIT_OK source=startup')
        self.assertEqual(result['hookSpecificOutput']['hookEventName'], 'SessionStart')
        self.assertIn('MENTOR_INIT_OK', context)
        self.assertLessEqual(len(context.encode()), 13000)
        for name in CORE:
            self.assertIn((self.root / name).read_text(), context)
        self.assertNotIn('# Development discipline\n', context)

    def test_nested_directory_and_exact_start_sources(self):
        nested = self.root / 'shared/component'
        nested.mkdir(parents=True)
        for source in ['startup', 'resume', 'clear', 'compact', 'fork']:
            result = self.result({**self.event, 'source': source, 'cwd': str(nested)})
            self.assertEqual(result['systemMessage'], 'MENTOR_INIT_OK source=' + source)
        for source in (None, '', 'unknown', 'manual'):
            result = self.result({**self.event, 'source': source})
            self.assertIn('unexpected_source', result['systemMessage'])
            self.assertNotIn('MENTOR_INIT_OK', json.dumps(result))

    def test_missing_router_is_visible_and_never_success(self):
        (self.root / 'mentor/ROUTING.md').unlink()
        result = self.result()
        self.assertIn('MENTOR_INIT_FAILED', result['systemMessage'])
        self.assertIn('directly as the disclosed fallback',
                      result['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('MENTOR_INIT_OK', json.dumps(result))

    def test_each_discovery_catalog_fails_independently(self):
        for catalog, marker in (('.agents', 'codex_discovery'),
                                ('.claude', 'claude_discovery')):
            with self.subTest(catalog=catalog):
                link = self.root / catalog / 'skills/development-discipline'
                target = os.readlink(link)
                link.unlink()
                result = self.result()
                self.assertIn(marker + ':development-discipline',
                              result['systemMessage'])
                self.assertNotIn('MENTOR_INIT_OK', json.dumps(result))
                link.symlink_to(target, target_is_directory=True)

    def test_invalid_skill_source_permissions_and_symlink_fail(self):
        skill = self.root / 'mentor/skills/development-discipline/SKILL.md'
        skill.write_text(skill.read_text().replace('name: development-discipline',
                                                   'name: wrong-name', 1))
        self.assertIn('mentor/skills/development-discipline/SKILL.md',
                      self.result()['systemMessage'])

        shutil.copyfile(ROOT / 'mentor/skills/development-discipline/SKILL.md', skill)
        skill.chmod(0o666)
        self.assertIn('mentor/skills/development-discipline/SKILL.md',
                      self.result()['systemMessage'])

        skill.unlink()
        skill.symlink_to(ROOT / 'mentor/skills/development-discipline/SKILL.md')
        self.assertIn('mentor/skills/development-discipline/SKILL.md',
                      self.result()['systemMessage'])

    def test_bad_event_cwd_session_and_oversize_policy_fail_visibly(self):
        cases = [
            {'cwd': str(self.root), 'hook_event_name': 'Other',
             'source': 'startup', 'session_id': 'session-test-123'},
            {**self.event, 'cwd': '/'},
            {**self.event, 'session_id': '../bad'},
            {**self.event, 'session_id': ''},
            {**self.event, 'session_id': 'x' * 129},
        ]
        for event in cases:
            with self.subTest(event=event):
                result = self.result(event)
                self.assertIn('MENTOR_INIT_FAILED', result['systemMessage'])
                self.assertNotIn('MENTOR_INIT_OK', json.dumps(result))
        (self.root / 'mentor/AGENTS.md').write_text('x' * 13000)
        self.assertIn('context_size_limit', self.result()['systemMessage'])

    def run_executable(self, raw):
        process = subprocess.run(
            [sys.executable, '-B', str(ROOT / 'mentor/session_init.py')],
            input=raw, capture_output=True, timeout=5)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(process.stderr, b'')
        return json.loads(process.stdout)

    def test_executable_accepts_all_sources_and_emits_one_json_object(self):
        for source in ['startup', 'resume', 'clear', 'compact', 'fork']:
            event = {'hook_event_name': 'SessionStart', 'cwd': str(ROOT),
                     'source': source, 'session_id': 'exec-session-' + source}
            result = self.run_executable(json.dumps(event).encode())
            self.assertEqual(result['systemMessage'], 'MENTOR_INIT_OK source=' + source)
            self.assertEqual(result['hookSpecificOutput']['hookEventName'], 'SessionStart')

    def test_executable_malformed_oversized_and_secret_input_fail_safely(self):
        for raw in (b'{bad-json SECRET_CANARY', b'x' * (MAX_INPUT_BYTES + 1),
                    json.dumps(['not-an-object', 'SECRET_CANARY']).encode()):
            result = self.run_executable(raw)
            serialized = json.dumps(result)
            self.assertIn('MENTOR_INIT_FAILED', serialized)
            self.assertNotIn('MENTOR_INIT_OK', serialized)
            self.assertNotIn('SECRET_CANARY', serialized)


if __name__ == '__main__':
    unittest.main()
