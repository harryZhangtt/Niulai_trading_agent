"""Synthetic source plumbing; real issuer capture is a separate live check."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from shared.actions import dispatch, resolve
from shared.research_sources.artifacts import SOURCE_STATE, SourceError, digest, read, save
from shared.research_sources.fetch import document_receipt
from investment.research.pilot import FIXTURE, SOURCE, prepare


class PilotTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        # Deliberately synthetic HTML containing the independently reviewed
        # source anchors. It is not a live issuer-data acceptance artifact.
        lines = ['Synthetic fixture: source plumbing only', 'May 22, 2024',
            'NVIDIA reported the first quarter ended April 28, 2024',
            'Record quarterly revenue of $26.0 billion',
            'First Quarter Fiscal 2025 Summary', 'GAAP',
            '($ in millions, except earnings\nper share)', 'Q1 FY25', 'Q4 FY24', 'Q1 FY24',
            'Revenue\n$26,044', 'Three Months Ended\nApril 28,',
            'April 28,\nJanuary 28,\n2024\n2024']
        raw = ('<article><h1>Synthetic fixture only</h1><p>' + '</p><p>'.join('\n'.join(lines).splitlines()) + '</p></article>').encode()
        self.source = document_receipt(self.directory, provider='official_document', url=SOURCE,
            raw=raw, identifier=SOURCE)
        self.pilot = prepare(FIXTURE, self.directory / 'pilot', source_ref=self.source)

    def context(self):
        request = self.pilot.request
        result = dispatch({'schema_version': 1, 'action': 'evidence.compare_numeric@1',
            'request_id': 'test-comparison', 'arguments': {'packet_ref': request['packet_ref']}},
            output_directory=self.directory / 'actions')
        self.assertEqual(result['status'], 'success')
        interpretation = {'schema_version': 1, 'status': 'success', 'error': None, 'execution_ref': None,
            'data': {'conclusion': 'same_release_rounding_reconciled', 'independent_sources': False,
                'source_ref': request['source_ref'], 'comparison_input_sha256': request['packet_ref']['sha256'],
                'explanation': 'The headline is rounded to tenths of a billion; both readings share the issuer source.',
                'unresolved_gaps': []}}
        phases = {'comparison': result, 'interpretation': interpretation}
        refs = {k: save(self.directory, {'schema_version': 1, 'phase_id': k, 'status': 'accepted', 'outcome': v})
                for k, v in phases.items()}
        context = {'run_id': 'pilot-test-run', 'request': request, 'phases': phases, 'phase_refs': refs}
        context['action_records'] = [self.read_record(context)]
        return context

    def read_record(self, context, *, source_ref=None, start=0, max_chars=6000):
        arguments = {'source_ref': source_ref or self.pilot.request['source_ref'], 'start': start, 'max_chars': max_chars}
        selector, call_id = 'evidence.read@1', 'read-source'
        action_request = {'schema_version': 1, 'action': selector,
            'request_id': context['run_id'] + ':' + call_id, 'arguments': arguments,
            'expected_release_sha256': resolve(selector)['release_sha256']}
        result = dispatch(action_request, output_directory=self.directory / 'read-actions')
        self.assertEqual(result['status'], 'success')
        record = {'schema_version': 1, 'run_id': context['run_id'], 'call_id': call_id, 'action': selector,
            'arguments_ref': save(self.directory, arguments), 'outcome_ref': save(self.directory, result),
            'execution_ref': result['execution_ref'], 'occurred_at': datetime.now(timezone.utc).isoformat()}
        return {**record, 'record_ref': save(self.directory, record)}

    def test_coherent_rounding_input_and_source_availability(self):
        request = self.pilot.request
        packet = read(request['packet_ref'])
        self.assertEqual([r['value'] for r in packet['observations']], ['26000', '26044'])
        self.assertEqual(packet['absolute_tolerance'], '50')
        source = read(self.source)
        self.assertTrue(all(row['available_at'] == source['available_at'] for row in packet['observations']))
        requirement = read(request['requirement_ref'])
        self.assertEqual(requirement['minimum_sources'], 1)
        self.assertEqual(requirement['mode'], 'historical')
        self.assertEqual(requirement['interval'], {'start': '2024-01-29', 'end': '2024-04-28'})

    def test_guard_and_scoped_snapshot_use_exact_passages_and_receipts(self):
        context = self.context()
        guard = self.pilot.critical_guard('evidence.compare_numeric', {'packet_ref': self.pilot.request['packet_ref']}, context)
        self.assertEqual(guard['status'], 'supported')
        self.assertFalse(read(guard['receipt_ref'])['independent_sources'])
        final = read(self.pilot.finalizer(context))
        self.assertEqual(final['completion_scope'], 'same_source_rounding_reconciliation')
        snapshot = self.pilot.store.read_snapshot(final['snapshot']['snapshot_id'])
        self.assertTrue(all(b['use_receipt_ref'] == final['use_receipt_ref'] for b in snapshot['manifest']['bindings']))

    def test_unbound_cached_packet_cannot_reach_critical_calculation(self):
        context = self.context()
        packet = read(context['request']['packet_ref']); packet['observations'][0]['value'] = '99999'
        other_ref = save(self.directory, packet)
        with self.assertRaisesRegex(SourceError, 'PILOT_ACTION_INPUT_NOT_BOUND'):
            self.pilot.critical_guard('evidence.compare_numeric', {'packet_ref': other_ref}, context)
        context['request']['packet_ref'] = other_ref
        with self.assertRaisesRegex(SourceError, 'PILOT_REQUEST_CHANGED'):
            self.pilot.critical_guard('evidence.compare_numeric', {'packet_ref': self.pilot.request['packet_ref']}, context)

    def test_source_cannot_be_backdated_to_historical_information_cutoff(self):
        with self.assertRaisesRegex(SourceError, 'PILOT_SOURCE_AFTER_CUTOFF'):
            prepare(FIXTURE, self.directory / 'old-cutoff', source_ref=self.source, cutoff='2024-05-22T23:59:59Z')
        source = read(self.source); source['available_at'] = '2024-05-22T00:00:00Z'
        with self.assertRaisesRegex(SourceError, 'PILOT_AVAILABILITY_BASIS_INVALID'):
            prepare(FIXTURE, self.directory / 'forged-source', source_ref=save(self.directory, source))

    def test_cached_text_must_be_extracted_from_actual_raw_bytes(self):
        source = read(self.source); source['text'] = save(self.directory, b'invented extracted text')
        with self.assertRaisesRegex(SourceError, 'PILOT_EXTRACTED_TEXT_MISMATCH'):
            prepare(FIXTURE, self.directory / 'forged-text', source_ref=save(self.directory, source))

    def test_revised_observation_invalidates_old_bound_use(self):
        context = self.context(); bound = self.pilot.request['bindings'][0]
        record = self.pilot.store.read(bound['observation_id']); payload = record['payload']
        payload['value'] = '999'
        self.pilot.store.revise('test-revision', record['id'], payload, expected_revision=record['revision'])
        with self.assertRaisesRegex(SourceError, 'PILOT_OBSERVATION_CHANGED'):
            self.pilot.finalizer(context)

    def test_missing_actual_comparison_receipt_blocks_publication(self):
        context = self.context(); context['phases'].pop('comparison'); context['phase_refs'].pop('comparison')
        with self.assertRaisesRegex(SourceError, 'PILOT_CALCULATION_REQUIRED'):
            self.pilot.finalizer(context)

    def test_independence_overclaim_and_changed_calculation_are_not_accepted(self):
        context = self.context(); context['phases']['interpretation']['data']['independent_sources'] = True
        context['phase_refs']['interpretation'] = save(self.directory, {'outcome': context['phases']['interpretation']})
        with self.assertRaisesRegex(SourceError, 'PILOT_INTERPRETATION_REQUIRED'):
            self.pilot.finalizer(context)
        context = self.context(); context['phases']['comparison']['data']['absolute_difference'] = '0'
        context['phase_refs']['comparison'] = save(self.directory, {'outcome': context['phases']['comparison']})
        with self.assertRaisesRegex(SourceError, 'PILOT_CALCULATION_RECEIPT_MISMATCH'):
            self.pilot.finalizer(context)

    def test_withdrawal_between_guard_and_snapshot_commit_is_rechecked(self):
        context = self.context(); original = self.pilot.store.commit_snapshot
        def raced(request_id, requirement_ref, bindings):
            b = bindings[0]
            self.pilot.store.withdraw('race-withdrawal', b['observation_id'], b['revision'], 'Race fixture')
            return original(request_id, requirement_ref, bindings)
        self.pilot.store.commit_snapshot = raced
        with self.assertRaisesRegex(SourceError, 'SNAPSHOT_DEPENDENCY_CHANGED'):
            self.pilot.finalizer(context)

    def test_newly_selected_offsets_not_stale_capture_offsets(self):
        # Synthetic page offset differs from the original inspected capture.
        obs = self.pilot.store.read(self.pilot.request['bindings'][0]['observation_id'])
        self.assertNotEqual(obs['payload']['passages']['headline']['start'], 856)
        raw_text = read(read(self.source)['text'], json_value=False).decode()
        for passage in obs['payload']['passages'].values():
            self.assertEqual(raw_text[passage['start']:passage['end']], passage['text'])

    def test_immediate_phase_result_without_actual_source_read_is_rejected(self):
        context = self.context(); context['action_records'] = []
        with self.assertRaisesRegex(SourceError, 'PILOT_SOURCE_READ_REQUIRED'):
            self.pilot.finalizer(context)

    def test_wrong_source_read_and_insufficient_range_do_not_satisfy_gate(self):
        context = self.context()
        source = read(self.source)
        other = document_receipt(self.directory, provider='official_document', url=SOURCE,
            raw=read(source['raw'], json_value=False), identifier=SOURCE)
        context['action_records'] = [self.read_record(context, source_ref=other)]
        with self.assertRaisesRegex(SourceError, 'PILOT_SOURCE_READ_REQUIRED'):
            self.pilot.finalizer(context)
        context['action_records'] = [self.read_record(context, max_chars=20)]
        with self.assertRaisesRegex(SourceError, 'PILOT_SOURCE_READ_REQUIRED'):
            self.pilot.finalizer(context)

    def test_alternative_bounded_ranges_covering_all_anchors_are_accepted(self):
        context = self.context()
        context['action_records'] = [self.read_record(context, max_chars=12000)]
        self.assertEqual(read(self.pilot.finalizer(context))['status'], 'supported')
        source = read(self.source)
        text = read(source['text'], json_value=False).decode()
        start = text.index('Record quarterly revenue of $26.0 billion')
        context['action_records'] = [self.read_record(context, start=start, max_chars=6000)]
        self.assertEqual(read(self.pilot.finalizer(context))['status'], 'supported')

    def test_hash_consistent_wrong_passage_still_rejected(self):
        context = self.context(); record = context['action_records'][0]
        outcome = read(record['outcome_ref']); outcome['data']['passage']['text'] = 'Unrelated but hash-consistent content'
        execution = read(record['execution_ref']); execution['data_sha256'] = digest(outcome['data'])
        record['execution_ref'] = outcome['execution_ref'] = save(self.directory, execution)
        record['outcome_ref'] = save(self.directory, outcome)
        record['record_ref'] = save(self.directory, {k: v for k, v in record.items() if k != 'record_ref'})
        with self.assertRaisesRegex(SourceError, 'PILOT_READ_PASSAGE_MISMATCH'):
            self.pilot.finalizer(context)

    def test_fewer_or_duplicate_observation_bindings_are_rejected(self):
        from investment.research.pilot import Pilot
        for bindings in ([self.pilot.request['bindings'][0]], [self.pilot.request['bindings'][0]] * 2):
            request = self.pilot.request; request['bindings'] = bindings
            with self.assertRaisesRegex(SourceError, 'PILOT_OBSERVATION_ROSTER_CHANGED'):
                Pilot(self.directory / 'bad-roster', request)


if __name__ == '__main__':
    unittest.main()
