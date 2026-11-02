"""Atomic action safety, with fixture data and explicit transport fault injection.

No public provider is called. Real frozen workers cover parsing/typing; selected
worker protocol and process failures are injected at the subprocess boundary.
"""
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from shared.actions import ActionError, dispatch, freeze_release, invoke, resolve
from shared.actions import runtime
from shared.actions.releases import verify_release
from shared.research_sources import fetch
from shared.research_sources.artifacts import SOURCE_STATE, digest, read, save


class AtomicSafetyTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.directory = Path(self.tmp.name)
        self.addCleanup(self.cleanup)
        self.releases = {}
        self.stream_fault = False

    def cleanup(self):
        for path in self.directory.rglob('*'):
            if path.is_dir():
                path.chmod(0o700)
            elif path.is_file() and not path.is_symlink():
                path.chmod(0o600)
        self.tmp.cleanup()

    def packet(self):
        source = {'origin': 'synthetic-issuer', 'provider': 'synthetic-filing',
                  'upstream_family': 'synthetic-issuer', 'ref': 'public-fixture', 'sha256': 'a' * 64}
        row = {'subject': 'SYNTHETIC', 'metric': 'revenue', 'definition': 'reported consolidated revenue',
            'unit': 'USD millions', 'basis': 'reported', 'period': {'start': '2026-01-01', 'end': '2026-03-31'},
            'value': '100', 'observed_at': '2026-03-31T00:00:00Z', 'available_at': '2026-04-15T00:00:00Z',
            'source': source}
        return {'version': '2026-10-24-evidence-crosscheck-1', 'as_of': '2026-04-30T00:00:00Z',
            'comparison_kind': 'numeric', 'max_age_seconds': 10000000, 'max_time_skew_seconds': 0,
            'absolute_tolerance': '0', 'relative_tolerance': '0', 'require_source_hashes': True,
            'observations': [row, copy.deepcopy(row)]}

    def request(self, arguments, action='evidence.compare_numeric@1', *, frozen=True):
        request = {'schema_version': 1, 'request_id': 'atomic-fixture', 'action': action, 'arguments': arguments}
        if frozen:
            if action not in self.releases:
                self.releases[action] = freeze_release(action, directory=self.directory / 'releases')
            release = self.releases[action]
            request.update(release_ref=release['release_ref'], expected_release_sha256=release['release_sha256'])
        else:
            request['expected_release_sha256'] = resolve(action)['release_sha256']
        return request

    def compare(self, packet):
        request = self.request({'packet_ref': save(self.directory / 'inputs', packet)})
        return invoke(request, output_directory=self.directory / 'out', timeout_seconds=8)

    def document(self):
        return fetch.document_receipt(self.directory / 'source', provider='official_document',
            url='https://nvidianews.nvidia.com/synthetic-atomic-safety', identifier='synthetic-quarter',
            published_at='2026-04-15T00:00:00Z',
            raw=('<h1>Explicitly synthetic issuer report</h1><p>' +
                 'Quarterly revenue was 100 USD millions under the reported consolidated definition. ' * 8 + '</p>').encode())

    def test_frozen_compare_rejects_bool_nonfinite_and_nonnumeric_values(self):
        for value in (True, False, 100, 'NaN', 'Infinity', '-Infinity', 'one hundred', '1e309', ' 100 '):
            with self.subTest(value=repr(value)):
                packet = self.packet(); packet['observations'][0]['value'] = value
                result = self.compare(packet)
                self.assertEqual(result['status'], 'failure', result)
                self.assertIsNone(result['data'])
                self.assertEqual(result['error']['code'], 'ACTION_COMPARISON_INPUT_INVALID')

    def test_frozen_compare_rejects_nonfinite_json_constants_and_duplicate_keys(self):
        base = json.dumps(self.packet(), sort_keys=True)
        raw_cases = [base.replace('"value": "100"', '"value": ' + token, 1)
                     for token in ('NaN', 'Infinity', '-Infinity', '1e309')]
        raw_cases.append(base.replace('"value": "100"', '"value": "100", "value": "100"', 1))
        for raw in raw_cases:
            with self.subTest(raw=raw[:50]):
                ref = save(self.directory / 'raw-inputs', raw.encode())
                result = invoke(self.request({'packet_ref': ref}), output_directory=self.directory / 'out', timeout_seconds=8)
                self.assertEqual(result['status'], 'failure', result)
                self.assertIsNone(result['data'])

    def test_units_period_basis_are_preserved_as_not_comparable(self):
        changes = [('unit', 'USD billions'), ('basis', 'estimate'),
                   ('period', {'start': '2025-10-01', 'end': '2025-12-31'})]
        for name, value in changes:
            with self.subTest(name=name):
                packet = self.packet(); packet['observations'][1][name] = value
                result = self.compare(packet)
                self.assertEqual(result['status'], 'success', result)
                self.assertEqual(result['data']['status'], 'not_comparable')
                self.assertIn(name, result['data']['reasons'])
                self.assertNotIn('absolute_difference', result['data'])

    def test_missing_stale_future_and_shared_upstream_never_claim_truth(self):
        packet = self.packet(); packet['observations'][1]['source']['provider'] = 'second-wrapper'
        shared = self.compare(packet)
        self.assertEqual(shared['data']['status'], 'shared_upstream_corroboration')
        self.assertFalse(shared['data']['semantic_truth_verified'])
        for mutate in (lambda p: p['observations'][1].update(value=None),
                       lambda p: p.update(max_age_seconds=1)):
            packet = self.packet(); mutate(packet)
            result = self.compare(packet)
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['data']['status'], 'unverified')
            self.assertFalse(result['data']['semantic_truth_verified'])
        packet = self.packet(); packet['observations'][1]['available_at'] = '2026-05-01T00:00:00Z'
        self.assertEqual(self.compare(packet)['status'], 'failure')

    def test_frozen_reader_rejects_metadata_wrong_hash_and_non_utf8(self):
        original = read(self.document())
        cases = []
        metadata = dict(original, access_level='metadata'); cases.append(save(self.directory / 'bad', metadata))
        bad_hash = copy.deepcopy(original); bad_hash['raw']['sha256'] = '0' * 64
        cases.append(save(self.directory / 'bad', bad_hash))
        bad_text = dict(original, text=save(self.directory / 'bad', b'\xff\xfe', suffix='txt'))
        cases.append(save(self.directory / 'bad', bad_text))
        for ref in cases:
            result = invoke(self.request({'source_ref': ref}, 'evidence.read@1'),
                            output_directory=self.directory / 'out', timeout_seconds=8)
            self.assertEqual(result['status'], 'failure', result)
            self.assertIsNone(result['data'])

    def test_frozen_request_and_packet_tamper_are_rejected(self):
        ref = save(self.directory / 'inputs', self.packet())
        request = self.request({'packet_ref': ref})
        altered = dict(request, expected_release_sha256='0' * 64)
        with patch.object(runtime.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ActionError, 'ACTION_RELEASE_MISMATCH'):
                invoke(altered, output_directory=self.directory / 'bad-request')
            spawn.assert_not_called()
        Path(ref['path']).write_text('{}')
        result = invoke(request, output_directory=self.directory / 'bad-packet', timeout_seconds=8)
        self.assertEqual(result['status'], 'failure')
        self.assertEqual(result['error']['code'], 'ARTIFACT_HASH_MISMATCH')

    def test_release_descriptor_cannot_change_immutable_capability_effects_or_schemas(self):
        request = self.request({'packet_ref': save(self.directory / 'inputs', self.packet())})
        metadata = read(request['release_ref'])
        for name, value in (('effects', ['external_write']), ('capability', 'trade.submit'),
                            ('input_schema', 'Acquire'), ('output_schema', 'ReadResult')):
            with self.subTest(name=name):
                changed = copy.deepcopy(metadata); changed['descriptor'][name] = value
                ref = save(self.directory / 'tampered-metadata', changed)
                with self.assertRaises(ActionError):
                    verify_release(ref, selector=request['action'])

    def _protocol_response(self, request, *, data, status='success', error=None, receipt_error=None):
        receipt = {'request_sha256': digest(request), 'status': status, 'data_sha256': digest(data),
                   'release_sha256': request.get('expected_release_sha256') or resolve(request['action'])['release_sha256'], 'error': receipt_error,
                   'action_id': request['action'].rsplit('@', 1)[0]}
        return {'schema_version': 1, 'status': status, 'data': data, 'error': error,
                'execution_ref': save(self.directory / 'protocol', receipt)}

    def test_matching_generic_receipt_cannot_admit_wrong_action_output(self):
        request = self.request({'packet_ref': save(self.directory / 'inputs', self.packet())})
        response = self._protocol_response(request, data={'passage': {'text': 'wrong action shape'}})
        with patch.object(runtime.subprocess, 'Popen', return_value=Mock(returncode=0)), \
                patch.object(runtime, '_stream', return_value=(json.dumps(response).encode(), b'', None)):
            with self.assertRaises(ActionError):
                invoke(request, output_directory=self.directory / 'protocol-out')

    def test_failure_error_cannot_disagree_with_execution_receipt(self):
        request = self.request({'packet_ref': save(self.directory / 'inputs', self.packet())})
        actual = {'code': 'ACTION_EXECUTION_FAILED', 'effect_state': 'unknown', 'retryable': False}
        altered = {'code': 'SOURCE_NETWORK_FAILED', 'effect_state': 'not_started', 'retryable': True}
        response = self._protocol_response(request, data=None, status='failure', error=altered, receipt_error=actual)
        with patch.object(runtime.subprocess, 'Popen', return_value=Mock(returncode=0)), \
                patch.object(runtime, '_stream', return_value=(json.dumps(response).encode(), b'', None)):
            with self.assertRaisesRegex(ActionError, 'ACTION_WORKER_RECEIPT_MISMATCH'):
                invoke(request, output_directory=self.directory / 'protocol-out')

    def test_unreceipted_failure_cannot_authorize_retry_after_worker_started(self):
        request = self.request({'packet_ref': save(self.directory / 'inputs', self.packet())})
        response = {'schema_version': 1, 'status': 'failure', 'data': None, 'execution_ref': None,
            'error': {'code': 'SOURCE_NETWORK_FAILED', 'effect_state': 'not_started', 'retryable': True}}
        with patch.object(runtime.subprocess, 'Popen', return_value=Mock(returncode=0)), \
                patch.object(runtime, '_stream', return_value=(json.dumps(response).encode(), b'', None)):
            with self.assertRaisesRegex(ActionError, 'ACTION_WORKER_RECEIPT_MISMATCH'):
                invoke(request, output_directory=self.directory / 'protocol-out')

    def test_unpinned_request_still_binds_worker_to_selected_release(self):
        request = self.request({'packet_ref': save(self.directory / 'inputs', self.packet())}, frozen=False)
        del request['expected_release_sha256']
        data = dispatch(request, output_directory=self.directory / 'known-answer')['data']
        response = self._protocol_response(request, data=data)
        receipt = read(response['execution_ref']); receipt['release_sha256'] = '0' * 64
        response['execution_ref'] = save(self.directory / 'protocol', receipt)
        with patch.object(runtime.subprocess, 'Popen', return_value=Mock(returncode=0)), \
                patch.object(runtime, '_stream', return_value=(json.dumps(response).encode(), b'', None)):
            with self.assertRaisesRegex(ActionError, 'ACTION_WORKER_RECEIPT_MISMATCH'):
                invoke(request, output_directory=self.directory / 'protocol-out')

    def test_invalid_requests_are_rejected_before_worker_creation(self):
        for request in (None, [], 'invalid'):
            with self.subTest(request=repr(request)), patch.object(runtime.subprocess, 'Popen') as spawn, \
                    patch.object(runtime, '_stream', side_effect=AssertionError('Invalid request reached worker')):
                with self.assertRaises(ActionError):
                    invoke(request, output_directory=self.directory / 'invalid-request')
                spawn.assert_not_called()

    def test_invalid_output_limits_are_rejected_before_worker_creation(self):
        request = self.request({'packet_ref': save(self.directory / 'inputs', self.packet())}, frozen=False)
        for maximum in (None, '1024', 0, -1, True, float('nan'), float('inf')):
            with self.subTest(maximum=repr(maximum)), patch.object(runtime.subprocess, 'Popen') as spawn, \
                    patch.object(runtime, '_stream', side_effect=AssertionError('Invalid limit reached worker')):
                with self.assertRaises(ActionError):
                    invoke(request, output_directory=self.directory / 'invalid-limit', max_output_bytes=maximum)
                spawn.assert_not_called()

    def test_selected_input_schema_is_checked_before_frozen_or_current_worker(self):
        for frozen in (True, False):
            request = self.request({'packet_ref': {'path': 'invalid', 'sha256': 'invalid'}}, frozen=frozen)
            with self.subTest(frozen=frozen), patch.object(runtime.subprocess, 'Popen') as spawn:
                with self.assertRaisesRegex(ActionError, 'ACTION_COMPARE_INVALID'):
                    invoke(request, output_directory=self.directory / 'invalid-input')
                spawn.assert_not_called()

    def test_twenty_actual_normal_frozen_workers_have_no_false_failure(self):
        request = self.request({'packet_ref': save(self.directory / 'inputs', self.packet())})
        for index in range(20):
            with self.subTest(index=index):
                result = invoke(request, output_directory=self.directory / 'normal-workers' / str(index), timeout_seconds=8)
                self.assertEqual(result['status'], 'success', result)
                self.assertEqual(result['data']['status'], 'shared_upstream_corroboration')
                self.assertEqual(read(result['execution_ref'])['release_sha256'], request['expected_release_sha256'])

    def test_ten_tiny_deadlines_preserve_reason_and_reap_each_worker(self):
        request = self.request({'packet_ref': save(self.directory / 'inputs', self.packet())}, frozen=False)
        original = subprocess.Popen
        spawned = []
        def launch(*args, **kwargs):
            process = original(*args, **kwargs); spawned.append(process); return process
        try:
            with patch.object(runtime.subprocess, 'Popen', side_effect=launch):
                for index in range(10):
                    result = invoke(request, output_directory=self.directory / 'tiny-deadlines' / str(index), timeout_seconds=.0001)
                    self.assertEqual(result['error']['code'], 'ACTION_DEADLINE_EXCEEDED', result)
                    self.assertEqual(result['error']['effect_state'], 'unknown')
                    self.assertFalse(result['error']['retryable'])
                    self.assertIsNotNone(spawned[-1].returncode, 'Worker returned before its leader was reaped')
                    self.assertTrue(all(pipe.closed for pipe in (spawned[-1].stdin, spawned[-1].stdout, spawned[-1].stderr)))
        finally:
            for process in spawned:
                if process.returncode is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
                    process.wait(timeout=2)

    def test_http200_error_document_is_not_usable_acquisition(self):
        request = self.request({'kind': 'official_document', 'value': 'https://nvidianews.nvidia.com/synthetic-error'},
                               'evidence.acquire_document@1', frozen=False)
        original = fetch.fetch_document
        for heading in ('503 Service Unavailable', '429 Too Many Requests', 'Authentication failed'):
            payload = ('<html><title>' + heading + '</title><h1>' + heading + '</h1><p>' +
                       'The requested content could not be retrieved. Please try again later. ' * 8 + '</p></html>').encode()
            def injected(url, directory):
                return original(url, directory, getter=lambda _: (payload, 'text/html'))
            with self.subTest(heading=heading), patch.object(runtime.fetch, 'fetch_document', side_effect=injected):
                result = dispatch(request, output_directory=self.directory / 'http-error')
                self.assertEqual(result['status'], 'failure', result)
                self.assertIsNone(result['data'])

    @staticmethod
    def _running(pid):
        result = subprocess.run(['/bin/ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True, timeout=2)
        state = result.stdout.strip()
        return bool(state) and not state.startswith('Z')

    def _process_fault(self, *, timeout, normal_exit=False, output_limit=None):
        request = self.request({'packet_ref': save(self.directory / 'inputs', self.packet())}, frozen=False)
        pid_path = self.directory / 'worker-pids.json'
        script = '''
import json,os,signal,subprocess,sys,time
from pathlib import Path
from shared.actions import runtime
envelope=runtime.decode(sys.stdin.buffer.read())
child=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'],
                       stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
Path(sys.argv[1]).write_text(json.dumps({'worker':os.getpid(),'child':child.pid}))
if sys.argv[2]=='normal':
    print(json.dumps(runtime.dispatch(envelope['request'],output_directory=envelope['output_directory'])))
else:
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    if sys.argv[2]=='flood':
        sys.stderr.write('fixture-output-limit-'*10000);sys.stderr.flush()
    time.sleep(30)
'''
        original = subprocess.Popen
        original_killpg = os.killpg
        spawned = []
        self.worker_signals = []
        def launch(command, **kwargs):
            mode = 'normal' if normal_exit else 'flood' if output_limit else 'timeout'
            process = original([sys.executable, '-B', '-c', script, str(pid_path), mode], **kwargs)
            spawned.append(process)
            return process
        def signal_group(pgid, sig):
            self.worker_signals.append({'pgid': pgid, 'signal': sig,
                'leader_returncodes': [p.returncode for p in spawned if p.pid == pgid]})
            return original_killpg(pgid, sig)
        try:
            def broken_stream(process, envelope, timeout, maximum, cancel):
                process.stdin.write(envelope); process.stdin.close()
                until = time.monotonic() + 2
                while not pid_path.exists() and time.monotonic() < until:
                    time.sleep(.01)
                raise OSError('synthetic-private-stream-error')
            with patch.object(runtime.subprocess, 'Popen', side_effect=launch), \
                    patch.object(runtime.os, 'killpg', side_effect=signal_group):
                if self.stream_fault:
                    with patch.object(runtime, '_stream', side_effect=broken_stream):
                        result = invoke(request, output_directory=self.directory / 'process-out', timeout_seconds=timeout)
                else:
                    result = invoke(request, output_directory=self.directory / 'process-out', timeout_seconds=timeout,
                                    **({'max_output_bytes': output_limit} if output_limit else {}))
            self.assertTrue(pid_path.exists(), 'Fault worker did not reach the injected boundary')
            pids = json.loads(pid_path.read_text())
            self.assertFalse(self._running(pids['worker']))
            # Give the OS a bounded chance to reap the killed descendant.
            for _ in range(10):
                if not self._running(pids['child']):
                    break
                time.sleep(.02)
            self.assertFalse(self._running(pids['child']), 'Action returned while its descendant was still running')
            return result
        finally:
            for process in spawned:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                elif pid_path.exists():
                    child_pid = json.loads(pid_path.read_text())['child']
                    if self._running(child_pid):
                        try:
                            os.kill(child_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                process.wait(timeout=3)

    def test_real_timeout_is_unknown_nonretryable_and_kills_descendants(self):
        result = self._process_fault(timeout=1)
        self.assertEqual(result['status'], 'failure')
        self.assertEqual(result['error'], {'code': 'ACTION_DEADLINE_EXCEEDED', 'effect_state': 'unknown', 'retryable': False})
        self.assertEqual(read(result['execution_ref'])['effect_state'], 'unknown')
        self.assertTrue(self.worker_signals)
        self.assertTrue(all(code is None for item in self.worker_signals for code in item['leader_returncodes']),
                        'Cleanup signaled a process group after releasing its leader PID')

    def test_normal_worker_exit_cannot_leave_live_descendant(self):
        self._process_fault(timeout=8, normal_exit=True)

    def test_unexpected_stream_exception_is_unknown_and_cleans_process_group(self):
        self.stream_fault = True
        result = self._process_fault(timeout=3)
        self.assertEqual(result['error'], {'code': 'ACTION_WORKER_FAILED', 'effect_state': 'unknown', 'retryable': False})
        self.assertNotIn('synthetic-private-stream-error', json.dumps(result) + json.dumps(read(result['execution_ref'])))

    def test_actual_output_overflow_is_unknown_and_cleans_process_group(self):
        result = self._process_fault(timeout=3, output_limit=1024)
        self.assertEqual(result['error'], {'code': 'ACTION_OUTPUT_LIMIT_EXCEEDED', 'effect_state': 'unknown', 'retryable': False})


if __name__ == '__main__':
    unittest.main()
