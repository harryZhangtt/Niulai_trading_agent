"""Explicit-entrypoint contract tests; no models or production effects."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / 'mentor/entrypoints/ai-tuning/SKILL.md'

class AiTuningEntrypointTests(unittest.TestCase):
    def test_project_discovery_and_workspace_resolution(self):
        discovered = ROOT / '.claude/skills/ai-tuning/SKILL.md'
        self.assertEqual(discovered.resolve(), SKILL)
        self.assertEqual(discovered.resolve().parents[3], ROOT)

    def test_model_callable_and_existing_cards(self):
        text = SKILL.read_text()
        self.assertIn('name: ai-tuning', text)
        self.assertIn('disable-model-invocation: false', text)
        self.assertNotIn('only when explicitly invoked', text)
        cards = json.loads((ROOT / 'mentor/references/llm-engineering/knowledge-cards.json').read_text())['cards']
        for card in cards:
            self.assertIn(card['card_id'], text)
            self.assertTrue((ROOT / 'mentor/skills' / card['owner_route'] / 'SKILL.md').is_file())

    def test_experiment_deliverable_and_nonpromotion_boundary(self):
        text = SKILL.read_text()
        for term in ('Diagnosis:', 'Guidance:', 'Smallest experiment:', 'Measurement:',
                     'Acceptance and stop rules:', 'Next action:',
                     'not protected evidence', 'at most', 'unknown outcomes',
                     'design only', 'protected cases outside development'):
            self.assertIn(term, text)

if __name__ == '__main__':
    unittest.main()
