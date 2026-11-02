import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from shared.actions import ActionError, dispatch, freeze_release, invoke, resolve
from shared.actions import runtime
from shared.actions.releases import verify_release, _paths
from shared.research_sources.artifacts import SOURCE_STATE, digest, read, save


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.directory = Path(self.temp.name)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        # Release code modes are read-only in normal use; tests own their sandbox.
        for p in self.directory.rglob('*'):
            if p.is_dir(): p.chmod(0o700)
            elif p.is_file(): p.chmod(0o600)
        self.temp.cleanup()

    def request(self):
        source = {'origin': 'issuer', 'provider': 'filing', 'upstream_family': 'issuer', 'ref': 'fixture', 'sha256': 'a' * 64}
        row = {'subject': 'AAA', 'metric': 'revenue', 'definition': 'reported revenue', 'unit': 'USD millions',
               'basis': 'reported', 'period': {'start': '2026-01-01', 'end': '2026-03-31'}, 'value': '100',
               'observed_at': '2026-03-31T00:00:00Z', 'available_at': '2026-04-15T00:00:00Z', 'source': source}
        packet = {'version': '2026-10-24-evidence-crosscheck-1', 'as_of': '2026-04-30T00:00:00Z',
            'comparison_kind': 'numeric', 'max_age_seconds': 10000000, 'max_time_skew_seconds': 0,
            'absolute_tolerance': '0', 'relative_tolerance': '0', 'require_source_hashes': True,
            'observations': [row, copy.deepcopy(row)]}
        release = freeze_release('evidence.compare_numeric@1', directory=self.directory / 'releases')
        request = {'schema_version': 1, 'action': 'evidence.compare_numeric@1', 'request_id': 'frozen-1',
            'arguments': {'packet_ref': save(self.directory, packet)}, 'release_ref': release['release_ref'],
            'expected_release_sha256': release['release_sha256']}
        return release, request

    def test_frozen_worker_keeps_original_data_root_and_numeric_dependency(self):
        release, request = self.request()
        result = invoke(request, output_directory=self.directory / 'result')
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(result['data']['values'], ['100', '100'])
        receipt = read(result['execution_ref'])
        self.assertEqual(receipt['release_sha256'], release['release_sha256'])
        self.assertTrue(Path(result['execution_ref']['path']).is_relative_to(self.directory / 'result'))
        bundle = Path(read(release['release_ref'])['bundle_directory'])
        self.assertFalse((bundle / '.niulai-state').exists())
        self.assertEqual(read(release['schema_registry_ref'])['$defs']['Read']['type'], 'object')

    def test_pinned_run_survives_current_catalog_retirement_and_tree_drift(self):
        release, request = self.request()
        retired = dict(runtime.SPECS['evidence.compare_numeric'], lifecycle='retired')
        changed_manifest = runtime.manifest(); changed_manifest['files']['invented.py'] = 'f' * 64
        with patch.dict(runtime.SPECS, {'evidence.compare_numeric': retired}), patch.object(runtime, 'manifest', return_value=changed_manifest):
            with self.assertRaisesRegex(ActionError, 'ACTION_RETIRED'):
                resolve('evidence.compare_numeric@1')
            historical = resolve('evidence.compare_numeric@1', release_ref=release['release_ref'])
            self.assertEqual(historical['release_sha256'], release['release_sha256'])
            self.assertEqual(dispatch(request, output_directory=self.directory / 'historical')['status'], 'success')

    def test_bundle_tamper_rejected_before_worker_dispatch(self):
        release, request = self.request()
        bundle = Path(read(release['release_ref'])['bundle_directory'])
        path = bundle / 'shared/actions/runtime.py'; path.chmod(0o600); path.write_text('raise RuntimeError("tampered")')
        with patch.object(runtime.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ActionError, 'ACTION_RELEASE_HASH_MISMATCH'):
                invoke(request, output_directory=self.directory / 'bad')
            spawn.assert_not_called()

    def test_metadata_escape_action_substitution_and_unknown_fields_rejected(self):
        release, request = self.request()
        metadata = read(release['release_ref'])
        metadata['bundle_directory'] = '/tmp/untrusted'
        bad = dict(request, release_ref=save(self.directory, metadata))
        with self.assertRaises(Exception): invoke(bad, output_directory=self.directory / 'escape')
        bad = dict(request, action='evidence.read@1')
        with self.assertRaisesRegex(ActionError, 'ACTION_RELEASE_ACTION_MISMATCH'):
            invoke(bad, output_directory=self.directory / 'substitution')
        bad = dict(request, executable='/bin/sh')
        with self.assertRaisesRegex(ActionError, 'ACTION_REQUEST_INVALID'):
            invoke(bad, output_directory=self.directory / 'unknown')

    def test_content_identity_deduplicates_and_schema_is_frozen(self):
        release, request = self.request()
        again = freeze_release('evidence.compare_numeric@1', directory=self.directory / 'releases')
        self.assertEqual(release['release_ref'], again['release_ref'])
        self.assertEqual(release['release_sha256'], again['release_sha256'])
        # A different current catalog contract cannot replace this pinned schema.
        with patch.object(runtime, 'CONTRACTS', self.directory / 'absent.json'):
            resolved = resolve('evidence.compare_numeric@1', release_ref=release['release_ref'])
            self.assertEqual(read(resolved['schema_registry_ref'])['$defs']['Compare']['required'], ['packet_ref'])
            self.assertEqual(invoke(request, output_directory=self.directory / 'old-contract')['status'], 'success')

    def test_real_controlled_source_change_does_not_change_frozen_execution(self):
        original_root = runtime.SOURCE_ROOT
        source = self.directory / 'source-copy'
        for relative, path in _paths(original_root).items():
            target = source / relative; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        with patch.object(runtime, 'SOURCE_ROOT', source):
            release, request = self.request()
        legacy = source / 'niulai/skills/investment-research-financial-services/references/niulai-workflow/scripts/evidence_crosscheck.py'
        legacy.write_text('raise RuntimeError("working source changed after release")\n')
        (source / 'shared/actions/contracts.json').write_text('{}')
        result = invoke(request, output_directory=self.directory / 'still-frozen')
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(result['data']['values'], ['100', '100'])

    def test_published_version_rejects_different_code_in_same_catalog(self):
        release, request = self.request()
        source = self.directory / 'changed-source'
        for relative, path in _paths(runtime.SOURCE_ROOT).items():
            target = source / relative; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        legacy = source / 'niulai/skills/investment-research-financial-services/references/niulai-workflow/scripts/evidence_crosscheck.py'
        legacy.write_bytes(legacy.read_bytes() + b'\n# Different unpublished source.\n')
        with patch.object(runtime, 'SOURCE_ROOT', source):
            with self.assertRaisesRegex(ActionError, 'ACTION_RELEASE_VERSION_REUSED'):
                freeze_release(request['action'], directory=self.directory / 'releases')
        self.assertEqual(resolve(request['action'], release_ref=release['release_ref'])['release_sha256'], release['release_sha256'])

    def test_rehashed_descriptor_cannot_misrepresent_any_frozen_semantic_field(self):
        release, request = self.request()
        metadata = read(release['release_ref'])
        mutations = {'action_id': 'evidence.read', 'version': '99.0.0', 'lifecycle': 'retired',
                     'input_schema': 'Read', 'output_schema': 'ReadResult', 'effects': [],
                     'retry_owner': 'agent', 'capability': 'document.read', 'limits': 'Changed contract meaning'}
        for name, value in mutations.items():
            with self.subTest(field=name):
                changed = copy.deepcopy(metadata)
                changed['descriptor'][name] = value
                bad = dict(request, release_ref=save(self.directory, changed))
                with patch.object(runtime.subprocess, 'Popen') as spawn:
                    with self.assertRaisesRegex(ActionError, 'ACTION_RELEASE_DESCRIPTOR_(INVALID|MISMATCH)'):
                        invoke(bad, output_directory=self.directory / ('rejected-' + name))
                    spawn.assert_not_called()
        self.assertEqual(verify_release(release['release_ref'])['descriptor'], metadata['descriptor'])

    def test_previous_literal_version_is_bound_to_its_bundle_not_current_catalog(self):
        release, request = self.request()
        source = self.directory / 'previous-version-source'
        for relative, path in _paths(runtime.SOURCE_ROOT).items():
            target = source / relative; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        # A controlled prior contract, never a rewritten historical publication.
        path = source / 'shared/actions/runtime.py'
        text = path.read_text()
        for spec in runtime.SPECS.values():
            text = text.replace("'version': '" + spec['version'] + "'", "'version': '1.1.0'")
        path.write_text(text)
        previous = {name: dict(spec, version='1.1.0') for name, spec in runtime.SPECS.items()}
        with patch.object(runtime, 'SOURCE_ROOT', source), patch.dict(runtime.SPECS, previous):
            legacy = freeze_release('evidence.compare_numeric@1.1.0', directory=self.directory / 'previous-catalog')
        historical = resolve('evidence.compare_numeric@1.1.0', release_ref=legacy['release_ref'])
        self.assertEqual(historical['version'], '1.1.0')
        current = resolve(request['action'], release_ref=release['release_ref'])
        self.assertEqual(current['version'], read(release['release_ref'])['descriptor']['version'])
        old_request = dict(request, action='evidence.compare_numeric@1.1.0',
                           release_ref=legacy['release_ref'], expected_release_sha256=legacy['release_sha256'])
        result = invoke(old_request, output_directory=self.directory / 'previous-result')
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(result['data']['values'], ['100', '100'])


if __name__ == '__main__':
    unittest.main()
