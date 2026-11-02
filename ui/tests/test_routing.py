import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from ui.route import MAX_CATALOG_BYTES, ROOT, read_catalog, resolve


class RoutingTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'ui/runtime/tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = {
            'schema_version': 1,
            'skills': {
                'base': {'role': 'engineering'},
                'motion': {'role': 'engineering', 'requires': ['base'], 'aliases': ['gsap']},
                'plain': {'role': 'visual-authority'},
                'cinema': {'role': 'visual-authority'},
                'pencil': {'role': 'workflow', 'tools': ['pencil']},
            },
            'decisions': {'animate': ['motion'], 'visual': ['plain'], 'backend-only': []},
        }
        for name in self.catalog['skills']:
            folder = self.root / 'ui/skills' / name
            folder.mkdir(parents=True)
            (folder / 'SKILL.md').write_text('---\nname: {}\ndescription: Synthetic fixture.\n---\n'.format(name))
        self.write_catalog()

    def write_catalog(self):
        (self.root / 'ui/catalog.json').write_text(json.dumps(self.catalog))

    def plan(self, **kwargs):
        return resolve(root=self.root, **kwargs)

    def test_alias_dependency_closure_and_deduplication(self):
        result = self.plan(decisions=['animate'], requested=['gsap', 'base'])
        self.assertEqual(result['status'], 'UI_ROUTE_OK')
        self.assertEqual([s['skill'] for s in result['selected']], ['base', 'motion'])
        self.assertEqual(result['selected_body_bytes'], sum(s['bytes'] for s in result['selected']))

    def test_compatible_composition_and_non_ui_route(self):
        result = self.plan(decisions=['visual', 'animate'])
        self.assertEqual(result['status'], 'UI_ROUTE_OK')
        self.assertEqual(len(result['selected']), 3)
        empty = self.plan(decisions=['backend-only'])
        self.assertEqual(empty['status'], 'UI_ROUTE_OK')
        self.assertEqual(empty['selected'], [])

    def test_visual_alternatives_cannot_silently_override_each_other(self):
        result = self.plan(requested=['plain', 'cinema'])
        self.assertEqual(result['status'], 'UI_ROUTE_FAILED')
        self.assertEqual(result['selected'], [])
        self.assertIn('conflicting_visual_authorities', result['errors'])

    def test_missing_external_tool_is_blocked_not_installed_success(self):
        blocked = self.plan(requested=['pencil'])
        self.assertEqual(blocked['status'], 'UI_ROUTE_BLOCKED')
        self.assertFalse(blocked['declared_tools_satisfied'])
        self.assertEqual(blocked['missing_tools'], ['pencil'])
        guidance = self.plan(requested=['pencil'], guidance_only=True)
        self.assertEqual(guidance['status'], 'UI_ROUTE_OK')
        self.assertFalse(guidance['declared_tools_satisfied'])
        declared = self.plan(requested=['pencil'], available_tools=['pencil'])
        self.assertTrue(declared['declared_tools_satisfied'])
        self.assertIn('caller-declared', declared['capability_evidence'])

    def test_bad_requests_are_sanitized(self):
        for kwargs in ({}, {'requested': ['SYNTHETIC_PRIVATE_CANARY']},
                       {'decisions': ['SYNTHETIC_PRIVATE_CANARY']}):
            result = self.plan(**kwargs)
            self.assertEqual(result['status'], 'UI_ROUTE_FAILED')
            self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(result))

    def test_missing_wrong_duplicate_or_non_utf8_entrypoints_fail_closed(self):
        source = self.root / 'ui/skills/base/SKILL.md'
        original = source.read_bytes()
        source.unlink()
        self.assertEqual(self.plan(requested=['motion'])['status'], 'UI_ROUTE_FAILED')
        for data in [b'\xff', b'', original.replace(b'name: base', b'name: wrong'),
                     original.replace(b'name: base', b'name: base\nname: wrong')]:
            source.write_bytes(data)
            self.assertEqual(self.plan(requested=['motion'])['status'], 'UI_ROUTE_FAILED')

    def test_valid_quoted_yaml_names_remain_callable(self):
        source = self.root / 'ui/skills/base/SKILL.md'
        for name in ["'base'", '"base"']:
            source.write_text('---\nname: {}\ndescription: Fixture.\n---\n'.format(name))
            self.assertEqual(self.plan(requested=['base'])['status'], 'UI_ROUTE_OK')

    def test_escaped_skill_and_catalog_sources_are_not_read(self):
        outside = self.root / 'private.txt'
        outside.write_text('SYNTHETIC_PRIVATE_CANARY')
        source = self.root / 'ui/skills/base/SKILL.md'
        source.unlink()
        source.symlink_to(outside)
        result = self.plan(requested=['base'])
        self.assertEqual(result['status'], 'UI_ROUTE_FAILED')
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(result))
        catalog = self.root / 'ui/catalog.json'
        catalog.unlink()
        catalog.symlink_to(outside)
        self.assertEqual(self.plan(requested=['base'])['status'], 'UI_ROUTE_FAILED')

    def test_catalog_cycles_alias_collisions_and_unknown_dependencies_fail(self):
        for mutation in ('cycle', 'alias', 'unknown'):
            self.catalog['skills']['base'] = {'role': 'engineering'}
            if mutation == 'cycle':
                self.catalog['skills']['base']['requires'] = ['motion']
            elif mutation == 'alias':
                self.catalog['skills']['base']['aliases'] = ['gsap']
            else:
                self.catalog['skills']['base']['requires'] = ['missing']
            self.write_catalog()
            self.assertEqual(self.plan(requested=['base'])['status'], 'UI_ROUTE_FAILED')

    def test_duplicate_and_oversized_catalog_fail(self):
        source = self.root / 'ui/catalog.json'
        for data in ['{"schema_version":1,"schema_version":1}', 'x' * (MAX_CATALOG_BYTES + 1)]:
            source.write_text(data)
            self.assertEqual(self.plan(requested=['base'])['status'], 'UI_ROUTE_FAILED')

    def test_fifo_catalog_and_entrypoint_fail_without_blocking_cli(self):
        script = self.root / 'ui/route.py'
        shutil.copyfile(ROOT / 'ui/route.py', script)
        for source in (self.root / 'ui/catalog.json', self.root / 'ui/skills/base/SKILL.md'):
            original = source.read_bytes()
            source.unlink()
            os.mkfifo(source)
            try:
                result = subprocess.run([sys.executable, '-B', str(script), '--skill', 'base'],
                                        capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout)['status'], 'UI_ROUTE_FAILED')
            finally:
                source.unlink()
                source.write_bytes(original)


class InstalledCatalogTests(unittest.TestCase):
    def test_every_installed_skill_is_independently_resolvable(self):
        catalog = read_catalog()
        for name in catalog['skills']:
            with self.subTest(skill=name):
                result = resolve(requested=[name], guidance_only=True)
                self.assertEqual(result['status'], 'UI_ROUTE_OK', result)
                self.assertIn(name, [item['skill'] for item in result['selected']])


if __name__ == '__main__':
    unittest.main()
