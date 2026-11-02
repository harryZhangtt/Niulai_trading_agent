"""Helper-only guards; no provider, scheduler or model calls."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import ROOT, SOURCE_STATE
from tuning.evals import datasource_acceptance as acceptance
from investment.research.datasource_query import OUTPUT_SCHEMA


class DatasourceAcceptanceTests(unittest.TestCase):
    def test_relevant_change_is_pinned_but_unrelated_skill_and_host_web_are_not(self):
        names = acceptance.candidate_paths()
        for name in ['investment/research/execution.py', 'shared/research_sources/artifacts.py',
                     'shared/research_sources/batch.py', 'shared/job_runtime/model.py']:
            self.assertIn(name, names)
        self.assertFalse(any('skill_tui' in name or 'host_web' in name or 'information_fetch/acquisition' in name for name in names))
        with tempfile.TemporaryDirectory(dir=ROOT / '.job-runtime/tests') as folder:
            root = Path(folder)
            for name in names:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'synthetic')
            unrelated = root / 'shared/job_runtime/skill_tui.py'; unrelated.write_bytes(b'old')
            with patch.object(acceptance, 'ROOT', root):
                before = acceptance.fingerprint()
                unrelated.write_bytes(b'changed')
                (root / 'shared/research_sources/host_web.py').write_bytes(b'new unrelated module')
                self.assertEqual(before, acceptance.fingerprint())
                (root / 'shared/research_sources/artifacts.py').write_bytes(b'relevant mutation')
                self.assertNotEqual(before, acceptance.fingerprint())

    def test_transport_omits_unsupported_keyword_while_local_schema_keeps_rule(self):
        def contains(value, key):
            if isinstance(value, dict): return key in value or any(contains(item, key) for item in value.values())
            return isinstance(value, list) and any(contains(item, key) for item in value)
        self.assertTrue(contains(OUTPUT_SCHEMA, 'uniqueItems'))
        self.assertFalse(contains(acceptance.catalog_transport_schema(), 'uniqueItems'))

    def test_replay_tree_detects_changed_bytes_and_additional_files(self):
        with tempfile.TemporaryDirectory(dir=SOURCE_STATE / 'runtime') as folder:
            path = Path(folder); item = path / 'immutable.json'; item.write_text('{"value":1}')
            first = acceptance.execution_tree(path)
            item.write_text('{"value":2}')
            self.assertNotEqual(first, acceptance.execution_tree(path))
            second = acceptance.execution_tree(path); (path / 'duplicate.json').write_text('{}')
            self.assertNotEqual(second, acceptance.execution_tree(path))


if __name__ == '__main__': unittest.main()
