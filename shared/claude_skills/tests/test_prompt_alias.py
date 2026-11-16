import json
from pathlib import Path
import subprocess
import sys
import unittest

from shared.claude_skills.manage import ROOT, entries
from shared.claude_skills.prompt_alias import expand


class PromptAliasTests(unittest.TestCase):
    def payload(self, prompt, model='claude-gpt-6-1-sol-max[1m]'):
        return {'hook_event_name': 'UserPromptSubmit', 'prompt': prompt,
                'cwd': '/synthetic/target', 'model': model, 'session_id': 'synthetic-session'}

    def test_all_32_aliases_load_exact_body_for_claude_and_gpt(self):
        sources = entries()
        for model in ('claude-opus-5-5', 'claude-gpt-6-1-sol-max[1m]'):
            for name, source in sources.items():
                with self.subTest(model=model, name=name):
                    result = expand(self.payload('$' + name + ' check this task', model), sources)
                    context = result['hookSpecificOutput']['additionalContext']
                    self.assertIn((source / 'SKILL.md').read_text(), context)
                    self.assertIn(str(source), context)
                    self.assertEqual(result['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')

    def test_model_does_not_change_expansion(self):
        self.assertEqual(expand(self.payload('$mentor-skill-set', 'claude-opus-5-5')),
                         expand(self.payload('$mentor-skill-set', 'any-gpt-model')))

    def test_consecutive_aliases_deduplicate(self):
        result = expand(self.payload(' $mentor-skill-set $harry-ui-skill-set $mentor-skill-set repair UI'))
        self.assertEqual(result['systemMessage'], 'CLAUDE_SKILL_ALIAS_OK mentor-skill-set,harry-ui-skill-set')

    def test_native_slash_and_ordinary_text_are_untouched(self):
        for prompt in ('/harry-ui-skill-set', 'explain $mentor-skill-set',
                       '`$harry-ui-skill-set`', '$HOME', '$harry-ui-skill-set; rm -rf /',
                       '$../settings', '```\n$mentor-skill-set\n```', 'ordinary backend work'):
            with self.subTest(prompt=prompt):
                self.assertEqual(expand(self.payload(prompt)), {})

    def test_wrong_event_is_untouched(self):
        self.assertEqual(expand({'hook_event_name': 'SessionStart', 'prompt': '$mentor-skill-set'}), {})

    def test_pipe_protocol_works_outside_checkout(self):
        completed = subprocess.run(
            [sys.executable, '-B', str(ROOT / 'shared/claude_skills/prompt_alias.py')],
            input=json.dumps(self.payload('$harry-ui-skill-set')).encode(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(Path.home()), timeout=5, check=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result['systemMessage'], 'CLAUDE_SKILL_ALIAS_OK harry-ui-skill-set')
        self.assertIn('Harry UI for Claude Code', result['hookSpecificOutput']['additionalContext'])
        self.assertEqual(completed.stderr, b'')

    def test_failure_diagnostic_does_not_echo_input(self):
        completed = subprocess.run(
            [sys.executable, '-B', str(ROOT / 'shared/claude_skills/prompt_alias.py')],
            input=b'invalid JSON synthetic-secret-never-print', stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=5, check=True,
        )
        self.assertIn('CLAUDE_SKILL_ALIAS_FAILED', completed.stdout.decode())
        self.assertNotIn(b'synthetic-secret-never-print', completed.stdout + completed.stderr)


if __name__ == '__main__':
    unittest.main()
