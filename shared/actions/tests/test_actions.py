import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from shared.actions import ActionError, decode, dispatch, invoke, registry, resolve
from shared.actions import runtime
from shared.research_sources.artifacts import ROOT, SOURCE_STATE, digest, read, save
from shared.research_sources.fetch import document_receipt


class ActionTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def request(self, action='evidence.compare_numeric@1', arguments=None):
        return {'schema_version': 1, 'action': action, 'request_id': 'test-1', 'arguments': arguments or {}}

    def packet(self):
        source = {'origin': 'issuer', 'provider': 'filing', 'upstream_family': 'issuer', 'ref': 'public-fixture', 'sha256': 'a' * 64}
        row = {'subject': 'AAA', 'metric': 'revenue', 'definition': 'reported revenue', 'unit': 'USD millions',
               'basis': 'reported', 'period': {'start': '2026-01-01', 'end': '2026-03-31'}, 'value': '100',
               'observed_at': '2026-03-31T00:00:00Z', 'available_at': '2026-04-15T00:00:00Z', 'source': source}
        return {'version': '2026-10-24-evidence-crosscheck-1', 'as_of': '2026-04-30T00:00:00Z',
                'comparison_kind': 'numeric', 'max_age_seconds': 10000000, 'max_time_skew_seconds': 0,
                'absolute_tolerance': '0', 'relative_tolerance': '0', 'require_source_hashes': True,
                'observations': [row, copy.deepcopy(row)]}

    def test_strict_json_duplicate_nonfinite_and_unknown_keys(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
            with self.assertRaises(ActionError): decode(raw)
        req = self.request(); req['shell'] = 'forbidden'
        result = dispatch(req, output_directory=self.directory)
        self.assertEqual(result['status'], 'failure')
        self.assertEqual(result['error']['effect_state'], 'not_started')
        req = self.request(arguments={'x': float('nan')})
        self.assertEqual(dispatch(req, output_directory=self.directory)['status'], 'failure')

    def test_unknown_action_version_and_bad_arguments_never_dispatch(self):
        for req in (self.request(action='shell.exec@1'), self.request(action='evidence.read@99'),
                    self.request(action='evidence.read@1', arguments={'source_ref': {'path': 'x', 'sha256': 'bad'}})):
            with patch.object(runtime, '_run') as run:
                result = dispatch(req, output_directory=self.directory)
                self.assertEqual(result['status'], 'failure'); run.assert_not_called()

    def test_retired_action_is_excluded_and_rejected(self):
        spec = dict(runtime.SPECS['evidence.read'], lifecycle='retired')
        with patch.dict(runtime.SPECS, {'evidence.read': spec}):
            self.assertNotIn('evidence.read', [row['action_id'] for row in registry()])
            self.assertIn('evidence.read', [row['action_id'] for row in registry(include_retired=True)])
            with self.assertRaisesRegex(ActionError, 'ACTION_RETIRED'):
                resolve('evidence.read@1')

    def test_known_answer_shared_lineage_and_disagreement_are_execution_success(self):
        packet = self.packet()
        for value, expected in [('100', 'shared_upstream_corroboration'), ('103', 'disagreement')]:
            packet['observations'][1]['value'] = value
            req = self.request(arguments={'packet_ref': save(self.directory, packet)})
            result = dispatch(req, output_directory=self.directory)
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['data']['status'], expected)
            self.assertFalse(result['data']['semantic_truth_verified'])
            receipt = read(result['execution_ref'])
            self.assertEqual(receipt['release_sha256'], resolve(req['action'])['release_sha256'])

    def test_numeric_invalid_unit_metadata_preserves_not_comparable(self):
        packet = self.packet(); packet['observations'][1]['unit'] = 'USD billions'
        result = dispatch(self.request(arguments={'packet_ref': save(self.directory, packet)}), output_directory=self.directory)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['data']['status'], 'not_comparable')
        self.assertIn('unit', result['data']['reasons'])

    def test_missing_or_tampered_input_ref_fails(self):
        ref = save(self.directory, self.packet()); Path(ref['path']).write_text('{}')
        result = dispatch(self.request(arguments={'packet_ref': ref}), output_directory=self.directory)
        self.assertEqual(result['status'], 'failure')
        self.assertEqual(result['error']['code'], 'ARTIFACT_HASH_MISMATCH')

    def test_release_pin_mismatch_and_mid_execution_drift_fail_closed(self):
        req = self.request(arguments={'packet_ref': save(self.directory, self.packet())})
        req['expected_release_sha256'] = '0' * 64
        with patch.object(runtime, '_run') as run:
            self.assertEqual(dispatch(req, output_directory=self.directory)['error']['code'], 'ACTION_RELEASE_MISMATCH')
            run.assert_not_called()
        del req['expected_release_sha256']
        original = runtime.manifest
        first = original(); second = copy.deepcopy(first); second['files']['invented'] = 'f' * 64
        with patch.object(runtime, 'manifest', side_effect=[first, second]):
            self.assertEqual(dispatch(req, output_directory=self.directory)['error']['code'], 'ACTION_RELEASE_CHANGED_DURING_EXECUTION')

    def test_malformed_handler_output_is_not_success(self):
        req = self.request(arguments={'packet_ref': save(self.directory, self.packet())})
        with patch.object(runtime, '_run', return_value={'status': 'looks_good'}):
            self.assertEqual(dispatch(req, output_directory=self.directory)['status'], 'failure')

    def test_document_reader_verifies_full_receipt_and_offsets(self):
        ref = document_receipt(self.directory, provider='official_document', url='https://www.sec.gov/synthetic',
            identifier='synthetic', published_at='2026-01-01T00:00:00Z',
            raw=('<h1>Fixture</h1><p>' + 'Explicitly synthetic source text. ' * 20 + '</p>').encode())
        result = dispatch(self.request('evidence.read@1', {'source_ref': ref, 'start': 2, 'max_chars': 30}), output_directory=self.directory)
        self.assertEqual(result['status'], 'success'); self.assertEqual(len(result['data']['passage']['text']), 30)
        with patch.object(runtime.fetch, 'fetch_document', return_value=ref):
            acquired = dispatch(self.request('evidence.acquire_document@1', {'kind': 'official_document', 'value': 'https://www.sec.gov/synthetic'}), output_directory=self.directory)
        self.assertEqual(acquired['data']['source_ref'], ref)

    def test_mutated_worker_data_or_release_is_rejected(self):
        request = self.request(arguments={'packet_ref': save(self.directory, self.packet())})
        request['expected_release_sha256'] = resolve(request['action'])['release_sha256']
        data = {'status': 'corroborated'}
        for wrong in ('data_sha256', 'release_sha256'):
            receipt = {'request_sha256': digest(request), 'status': 'success',
                       'data_sha256': digest(data), 'release_sha256': request['expected_release_sha256']}
            receipt[wrong] = '0' * 64
            result = {'schema_version': 1, 'status': 'success', 'data': data,
                      'error': None, 'execution_ref': save(self.directory, receipt)}
            with patch.object(runtime.subprocess, 'Popen', return_value=Mock(returncode=0)), \
                    patch.object(runtime, '_stream', return_value=(json.dumps(result).encode(), b'', None)):
                with self.assertRaisesRegex(ActionError, 'ACTION_WORKER_RECEIPT_MISMATCH'):
                    invoke(request, output_directory=self.directory)

    def test_actual_worker_handoff_and_deadline_receipts(self):
        request = self.request(arguments={'packet_ref': save(self.directory, self.packet())})
        result = invoke(request, output_directory=self.directory, timeout_seconds=10)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['data']['status'], 'shared_upstream_corroboration')
        timed = invoke(request, output_directory=self.directory, timeout_seconds=0.0001)
        self.assertEqual(timed['error']['code'], 'ACTION_DEADLINE_EXCEEDED')
        self.assertEqual(read(timed['execution_ref'])['effect_state'], 'unknown')


if __name__ == '__main__': unittest.main()
