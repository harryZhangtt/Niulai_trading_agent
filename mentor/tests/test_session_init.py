import json
from pathlib import Path
import shutil
import tempfile
import unittest

from mentor.session_init import CORE, ROOT, SKILLS, initialize


class SessionInitTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'mentor/runtime/test-tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in CORE + tuple('mentor/skills/{}/SKILL.md'.format(s) for s in SKILLS):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        links = self.root / '.agents/skills'
        links.mkdir(parents=True)
        for name in SKILLS:
            (links / name).symlink_to('../../mentor/skills/' + name, target_is_directory=True)
        self.event = {'hook_event_name': 'SessionStart', 'cwd': str(self.root), 'source': 'startup'}

    def context(self, event=None):
        return initialize(self.root, event or self.event)['hookSpecificOutput']['additionalContext']

    def test_loads_canonical_policy_and_router_but_not_six_full_bodies(self):
        context = self.context()
        self.assertIn('MENTOR_INIT_OK', context)
        for name in CORE:
            self.assertIn((self.root / name).read_text(), context)
        self.assertNotIn('# Development discipline\n', context)

    def test_nested_directory_and_all_start_sources(self):
        nested = self.root / 'shared/component'
        nested.mkdir(parents=True)
        for source in ['startup', 'resume', 'clear', 'compact', 'fork']:
            self.assertIn('MENTOR_INIT_OK', self.context({**self.event, 'source': source, 'cwd': str(nested)}))

    def test_missing_router_is_visible_and_never_success(self):
        (self.root / 'mentor/ROUTING.md').unlink()
        result = initialize(self.root, self.event)
        self.assertIn('MENTOR_INIT_FAILED', result['systemMessage'])
        self.assertIn('Tell the user', result['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('MENTOR_INIT_OK', json.dumps(result))

    def test_broken_discovery_link_and_invalid_skill_are_reported(self):
        (self.root / '.agents/skills/development-discipline').unlink()
        self.assertIn('MENTOR_INIT_FAILED', self.context())

    def test_bad_event_foreign_cwd_and_oversize_policy_fail_visibly(self):
        self.assertIn('MENTOR_INIT_FAILED', self.context({'cwd': str(self.root), 'hook_event_name': 'Other'}))
        self.assertIn('MENTOR_INIT_FAILED', self.context({**self.event, 'cwd': '/'}))
        (self.root / 'mentor/AGENTS.md').write_text('x' * 13000)
        self.assertIn('context_size_limit', self.context())


if __name__ == '__main__':
    unittest.main()
