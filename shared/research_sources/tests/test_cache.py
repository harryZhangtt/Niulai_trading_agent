"""Acquisition cache contracts; fixture stress is not provider-live readiness."""
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from shared.research_sources.artifacts import ROOT, SOURCE_STATE, SourceError, read, save
from shared.research_sources.cache import Cache, FetchKey
from shared.research_sources.store import Store


class CacheTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / 'tmp'; parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.store = Store(self.directory / 'store')
        self.at = datetime.now(timezone.utc)
        self.clock = [self.at]
        self.cache = Cache(self.store, now=lambda: self.clock[0])
        self.key = FetchKey('official_document', 'read', {'url': 'https://example.com/q1', 'period': '2025Q1'})
        self.source = self.document()
        self.calls = 0

    def document(self, *, period='2025Q1', content='reported revenue 123 USD millions', observed=None, available=None):
        raw = save(self.directory, ('Synthetic original report: ' + content).encode(), suffix='txt')
        return save(self.directory, {'schema_version': 1, 'provider': 'official_document',
            'source_url': 'https://example.com/q1', 'upstream_id': 'issuer-q1', 'source_version': None,
            'access_level': 'document', 'raw': raw, 'text': raw,
            'retrieved_at': (observed or self.at).isoformat(),
            'available_at': (available or self.at).isoformat(), 'availability_basis': 'first_observed',
            'metadata': {'period': period}, 'truth_or_independence_certified': False})

    def fetch(self):
        self.calls += 1
        return self.source

    def get(self, **kwargs):
        return self.cache.get_or_fetch(self.key, self.fetch, deadline=time.monotonic() + 3, **kwargs)

    def test_cold_then_warm_and_metadata_not_observation(self):
        cold = self.get(); warm = self.get()
        self.assertEqual((cold.status, cold.route, warm.route, self.calls), ('usable', 'fetch', 'cache_hit', 1))
        self.assertEqual(warm.source_ref, cold.source_ref)
        attempt = read(warm.attempt_refs[0])
        self.assertFalse(attempt['fetch_executed'])
        self.assertEqual(attempt['claim_support'], 'not_established_by_cache')
        self.assertEqual(self.store.find(), [])
        key = FetchKey('openalex', 'discover', {'query': 'FlashAttention'})
        raw = save(self.directory, {'results': [{'id': 'https://openalex.org/W1', 'title': 'FlashAttention'}]})
        metadata = save(self.directory, {'provider': 'openalex', 'access_level': 'metadata', 'raw': raw,
            'retrieved_at': self.at.isoformat(), 'source_url': 'https://api.openalex.org/works?search=FlashAttention',
            'candidates': [{'id': 'https://openalex.org/W1', 'title': 'FlashAttention'}]})
        one = self.cache.get_or_fetch(key, lambda: metadata, deadline=time.monotonic() + 3)
        two = self.cache.get_or_fetch(key, lambda: self.fail('warm called provider'), deadline=time.monotonic() + 3)
        self.assertEqual((one.status, two.route), ('usable', 'cache_hit'))
        self.assertNotIn('upstream_id', read(two.source_ref))

    def test_hundred_warm_reads_zero_provider_calls(self):
        self.get()
        for _ in range(100):
            outcome = self.get()
            self.assertEqual((outcome.status, outcome.route, outcome.fetch_executed), ('usable', 'cache_hit', False))
        self.assertEqual(self.calls, 1)

    def test_expiry_refetch_does_not_rejuvenate_observation(self):
        self.get(max_age_seconds=10)
        original = read(self.source)
        self.clock[0] += timedelta(seconds=11)
        self.source = self.document(observed=self.clock[0], available=self.clock[0])
        refreshed = self.get(max_age_seconds=10)
        self.assertEqual((refreshed.status, refreshed.route, self.calls), ('usable', 'fetch', 2))
        self.assertEqual(read(refreshed.source_ref)['available_at'], original['available_at'])
        self.assertEqual(read(refreshed.source_ref)['retrieved_at'], original['retrieved_at'])
        self.assertNotEqual(read(refreshed.attempt_refs[0])['fetched_source_ref'], refreshed.source_ref)
        self.assertEqual(self.store.cache_read(self.key.sha256)['checked_at'], self.clock[0].isoformat())

    def test_wrong_query_period_version_and_scope_never_alias(self):
        self.get()
        for key in (FetchKey('official_document', 'read', {'url': 'https://example.com/q1', 'period': '2025Q2'}),
                    FetchKey('official_document', 'read', {'url': 'https://example.com/q1'}, native_version='2')):
            outcome = self.cache.get_or_fetch(key, self.fetch, deadline=time.monotonic() + 3)
            self.assertEqual(outcome.status, 'unavailable')
            self.assertFalse(outcome.cache_hit)
        other_scope = FetchKey('official_document', 'read', self.key.parameters, access_scope='public-v2')
        self.assertNotEqual(self.key.sha256, other_scope.sha256)
        scoped = self.cache.get_or_fetch(other_scope, self.fetch, deadline=time.monotonic() + 3)
        self.assertEqual(scoped.route, 'fetch')
        query_key = FetchKey('openalex', 'discover', {'query': 'expected'})
        wrong = save(self.directory, {'provider': 'openalex', 'access_level': 'metadata',
            'source_url': 'https://api.openalex.org/works?search=wrong', 'retrieved_at': self.at.isoformat(),
            'raw': save(self.directory, {'results': ['wrong']}), 'candidates': [{'id': 'wrong'}]})
        outcome = self.cache.get_or_fetch(query_key, lambda: wrong, deadline=time.monotonic() + 3)
        self.assertEqual(outcome.status, 'unavailable')
        self.assertIn('CACHE_QUERY_MISMATCH', outcome.reasons)
        self.assertIsNone(self.store.cache_read(query_key.sha256))

    def test_corrupt_raw_is_quarantined_then_one_fetch_recovers(self):
        first = self.get()
        Path(read(first.source_ref)['raw']['path']).write_bytes(b'corrupt')
        self.source = self.document(content='corrected 124 USD millions')
        recovered = self.get()
        self.assertEqual((recovered.status, recovered.route, self.calls), ('usable', 'fetch', 2))
        self.assertIn('ARTIFACT_HASH_MISMATCH', recovered.reasons)
        events = self.store.events()
        self.assertEqual([e['event_type'] for e in events], ['cache_published', 'cache_quarantined', 'cache_published'])
        self.assertEqual(self.store.cache_read(self.key.sha256)['generation'], 3)
        self.assertEqual(self.get().source_ref, self.source)

    def test_invalid_receipt_and_empty_payload_cannot_be_cached(self):
        invalid = save(self.directory, {'provider': 'official_document', 'access_level': 'document',
            'raw': save(self.directory, b'', suffix='txt')})
        outcome = self.cache.get_or_fetch(self.key, lambda: invalid, deadline=time.monotonic() + 3)
        self.assertEqual(outcome.status, 'unavailable')
        self.assertIn('CACHE_RAW_EMPTY', outcome.reasons)
        self.assertIsNone(self.store.cache_read(self.key.sha256))

    def test_fetch_failure_one_attempt_and_explicit_eligible_fallback(self):
        self.get()
        before = self.store.cache_read(self.key.sha256)
        count = [0]
        def unauthorized():
            count[0] += 1
            raise SourceError('SOURCE_HTTP_401')
        recovered = self.cache.get_or_fetch(self.key, unauthorized, deadline=time.monotonic() + 3,
            force_refresh=True, eligible=lambda _: None)
        self.assertEqual((recovered.status, recovered.route, count[0]), ('usable', 'cache_fallback', 1))
        self.assertIn('SOURCE_HTTP_401', recovered.reasons)
        self.assertEqual(self.store.cache_read(self.key.sha256)['checked_at'], before['checked_at'])
        self.clock[0] += timedelta(hours=2)
        denied = self.cache.get_or_fetch(self.key, unauthorized, deadline=time.monotonic() + 3,
            max_age_seconds=1, eligible=lambda _: None)
        self.assertEqual(denied.status, 'unavailable')
        historical = self.cache.get_or_fetch(self.key, unauthorized, deadline=time.monotonic() + 3,
            max_age_seconds=1, eligible=lambda _: None, allow_stale=True)
        self.assertEqual(historical.route, 'cache_fallback')
        critical = self.cache.get_or_fetch(self.key, unauthorized, deadline=time.monotonic() + 3,
            max_age_seconds=1, eligible=lambda _: 'CURRENT_PERIOD_REQUIRED', allow_stale=True)
        self.assertEqual(critical.status, 'unavailable')
        self.assertIn('CURRENT_PERIOD_REQUIRED', critical.reasons)

    def test_unchanged_refetch_cannot_bypass_critical_staleness(self):
        self.get()
        original = self.source
        self.clock[0] += timedelta(days=7)
        self.source = self.document(observed=self.clock[0], available=self.clock[0])
        cutoff = self.at + timedelta(days=1)
        def current(receipt):
            return 'CURRENT_OBSERVATION_REQUIRED' if datetime.fromisoformat(receipt['available_at']) < cutoff else None
        result = self.get(max_age_seconds=1, eligible=current)
        self.assertEqual(result.status, 'unavailable')
        self.assertIn('CURRENT_OBSERVATION_REQUIRED', result.reasons)
        self.assertEqual(self.store.cache_read(self.key.sha256)['source_ref'], original)

    def test_lock_wait_deadline_is_bounded_and_does_not_fetch(self):
        path = self.cache.locks / (self.key.sha256 + '.lock')
        with path.open('w') as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)
            started = time.monotonic()
            outcome = self.cache.get_or_fetch(self.key, self.fetch, deadline=started + .08)
        self.assertLess(time.monotonic() - started, .5)
        self.assertEqual((outcome.status, outcome.fetch_executed, self.calls), ('unavailable', False, 0))
        self.assertIn('CACHE_DEADLINE_EXPIRED', outcome.reasons)

    def test_late_callback_discarded_not_claimed_preempted(self):
        def late():
            time.sleep(.04)
            return self.source
        started = time.monotonic()
        outcome = self.cache.get_or_fetch(self.key, late, deadline=started + .02)
        self.assertGreater(time.monotonic() - started, .04)
        self.assertEqual((outcome.status, outcome.fetch_executed), ('unavailable', True))
        self.assertIsNone(self.store.cache_read(self.key.sha256))

    def test_generation_fence_and_error_redaction(self):
        self.get()
        prior = self.store.cache_read(self.key.sha256)
        with self.assertRaisesRegex(SourceError, 'CACHE_GENERATION_CONFLICT'):
            self.store.cache_publish('stale-writer', self.key.to_dict(), self.source, self.at.isoformat(), 0)
        self.assertEqual(self.store.cache_read(self.key.sha256), prior)
        def private_error():
            raise RuntimeError('synthetic-secret-value')
        outcome = self.cache.get_or_fetch(self.key, private_error, deadline=time.monotonic() + 3, force_refresh=True)
        self.assertNotIn('synthetic-secret-value', json.dumps(outcome.to_dict()) + json.dumps(read(outcome.attempt_refs[0])))

    def test_source_failure_cooldown_scope_change_and_explicit_refresh(self):
        calls = [0]
        def blocked():
            calls[0] += 1
            raise SourceError('SOURCE_HTTP_403')
        one = self.cache.get_or_fetch(self.key, blocked, deadline=time.monotonic() + 3)
        two = self.cache.get_or_fetch(self.key, blocked, deadline=time.monotonic() + 3)
        self.assertEqual((one.status, two.status, calls[0]), ('unavailable', 'unavailable', 1))
        self.assertIn('CACHE_ACCESS_DEPENDENCY', two.reasons)
        self.assertFalse(two.fetch_executed)
        refreshed = self.get(force_refresh=True)
        self.assertEqual(refreshed.route, 'fetch')
        self.assertIsNone(self.store.cache_failure_read(self.key.sha256))
        changed = FetchKey('official_document', 'read', self.key.parameters, access_scope='public-v2')
        self.assertEqual(self.cache.get_or_fetch(changed, self.fetch, deadline=time.monotonic() + 3).route, 'fetch')
        missing = FetchKey('official_document', 'read', self.key.parameters, access_scope='missing')
        def coverage():
            calls[0] += 1
            raise SourceError('SOURCE_HTTP_404')
        self.cache.get_or_fetch(missing, coverage, deadline=time.monotonic() + 3)
        denied = self.cache.get_or_fetch(missing, coverage, deadline=time.monotonic() + 3)
        self.assertIn('CACHE_PROVIDER_COOLDOWN', denied.reasons)
        count = calls[0]
        self.clock[0] += timedelta(seconds=61)
        self.cache.get_or_fetch(missing, coverage, deadline=time.monotonic() + 3)
        self.assertEqual(calls[0], count + 1)

    def test_optional_receipt_failure_and_cache_write_failure_preserve_usable_response(self):
        with patch('shared.research_sources.cache.save', side_effect=RuntimeError('synthetic log unavailable')):
            result = self.get()
        self.assertEqual((result.status, result.route, result.source_ref), ('usable', 'fetch', self.source))
        self.assertEqual(result.attempt_refs, ())
        self.assertIn('CACHE_RECEIPT_UNAVAILABLE', result.reasons)
        with patch.object(self.store, 'cache_publish', side_effect=SourceError('STORE_BUSY')):
            result = self.get(force_refresh=True)
        self.assertEqual((result.status, result.route, result.source_ref), ('usable', 'fetch_uncached', self.source))
        self.assertIn('CACHE_PUBLICATION_UNAVAILABLE', result.reasons)

    def test_invalid_callback_result_and_invalid_policy_are_visible(self):
        result = self.cache.get_or_fetch(self.key, lambda: object(), deadline=time.monotonic() + 3)
        self.assertEqual(result.status, 'unavailable')
        self.assertIn('ARTIFACT_REF_INVALID', result.reasons)
        self.assertIn('CACHE_RECEIPT_UNAVAILABLE', result.reasons)
        with self.assertRaisesRegex(SourceError, 'CACHE_VALIDATOR_INVALID'):
            self.get(eligible='not-a-function')
        with self.assertRaisesRegex(SourceError, 'CACHE_POLICY_INVALID'):
            self.get(allow_stale='false')

    def test_nested_credentials_rejected_and_capability_access_enforced(self):
        for parameters in ({'options': {'api_key': 'synthetic'}},
                           {'url': 'https://user:synthetic@example.com/report'},
                           {'url': 'https://example.com/report?access_token=synthetic'}):
            with self.assertRaisesRegex(SourceError, 'CACHE_SECRET_PARAMETER'):
                FetchKey('official_document', 'read', parameters)
        wrong = FetchKey('official_document', 'discover', {'url': 'https://example.com/q1'})
        result = self.cache.get_or_fetch(wrong, self.fetch, deadline=time.monotonic() + 3)
        self.assertIn('CACHE_ACCESS_LEVEL_INVALID', result.reasons)

    def _process_wave(self, failure=False):
        counter = self.directory / 'provider-count'; counter.write_text('0')
        gate = self.directory / 'start'
        code = '''
import fcntl,json,sys,time
from pathlib import Path
from shared.research_sources.artifacts import SourceError,read
from shared.research_sources.cache import Cache,FetchKey
from shared.research_sources.store import Store
directory,source,gate=sys.argv[1:4]
failure=len(sys.argv)>4
directory=Path(directory)
store=Store(directory/'store')
key=FetchKey('official_document','read',{'url':'https://example.com/q1','period':'2025Q1'})
def fetch():
    with (directory/'provider-count').open('r+') as count:
        fcntl.flock(count,fcntl.LOCK_EX)
        n=int(count.read());count.seek(0);count.write(str(n+1));count.truncate();count.flush()
    time.sleep(.15)
    if failure:raise SourceError('SOURCE_HTTP_403')
    return json.loads(source)
deadline=time.monotonic()+10
while not Path(gate).exists():
    if time.monotonic()>deadline:raise RuntimeError('gate timeout')
    time.sleep(.01)
result=Cache(store).get_or_fetch(key,fetch,deadline=time.monotonic()+5)
print(json.dumps(result.to_dict()))
'''
        command = [sys.executable, '-c', code, str(self.directory), json.dumps(self.source), str(gate)]
        if failure:
            command.append('blocked')
        children = [subprocess.Popen(command,
            cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(5)]
        def cleanup():
            for child in children:
                if child.poll() is None:
                    child.kill(); child.wait(timeout=3)
        self.addCleanup(cleanup)
        gate.touch()
        outputs = []
        for child in children:
            stdout, stderr = child.communicate(timeout=12)
            self.assertEqual(child.returncode, 0, stderr)
            outputs.append(json.loads(stdout))
        return int(counter.read_text()), outputs

    def test_five_process_same_key_singleflight(self):
        count, outputs = self._process_wave()
        self.assertEqual(count, 1)
        self.assertEqual(sum(o['route'] == 'fetch' for o in outputs), 1)
        self.assertEqual(sum(o['route'] == 'cache_hit' for o in outputs), 4)
        self.assertTrue(all(o['status'] == 'usable' and o['source_ref'] == self.source for o in outputs))
        self.assertEqual(self.store.cache_read(self.key.sha256)['generation'], 1)

    def test_five_process_auth_failure_does_not_refetch_per_peer(self):
        count, outputs = self._process_wave(failure=True)
        self.assertEqual(count, 1)
        self.assertEqual(sum(o['fetch_executed'] for o in outputs), 1)
        self.assertTrue(all(o['status'] == 'unavailable' and not o['cache_hit'] for o in outputs))
        self.assertEqual(sum('CACHE_ACCESS_DEPENDENCY' in o['reasons'] for o in outputs), 4)
        self.assertIsNone(self.store.cache_read(self.key.sha256))


if __name__ == '__main__':
    unittest.main()
