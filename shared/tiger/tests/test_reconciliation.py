"""Synthetic client checks; no native authentication or broker calls."""
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib import error

from shared.tiger import reconciliation as r
from shared.tiger.bridge import TigerBridgeError


ATTEMPT = '00000000-0000-4000-8000-000000000001'
COMMIT = '00000000-0000-4000-8000-000000000002'
HEALTH = {'schema': 1, 'initialized': True, 'revision': 17,
          'lease_busy': False, 'last_committed_at': '2026-11-16T12:00:00.000Z'}
ACK = {'committed': True, 'revision': 17, 'idempotent': True, 'released': False}


def context():
    policy = {'project_id': 'synthetic-project', 'origin': 'https://synthetic.chatgpt.site',
              'owner_email': 'synthetic@example.test'}
    owner = {'account_user_id': 'synthetic-owner', 'email': policy['owner_email'], 'role': 'owner'}
    site = {'id': policy['project_id'], 'current_user_role': 'owner', 'status': 'active',
            'current_live_url': policy['origin'], 'latest_version_number': 1,
            'access_mode': 'custom', 'siwc_bypass_bearer_token': 'SYNTHETIC-BEARER-CANARY',
            'access_policy': {'access_mode': 'custom', 'project_id': policy['project_id'],
                'allowed_users': [owner], 'allowed_account_user_ids': [owner['account_user_id']]}}
    version = {'id': r.VERSION_ID, 'project_id': policy['project_id'], 'version_number': 1,
               'source': {'commit_sha': r.SOURCE_COMMIT}, 'deployment_id': r.DEPLOYMENT_ID}
    deployment = {'id': r.DEPLOYMENT_ID, 'project_id': policy['project_id'],
                  'version_id': r.VERSION_ID, 'status': 'succeeded', 'failure_message': None}
    return policy, {'site': site, 'version': version, 'deployment': deployment}


class Response:
    status = 200
    def __init__(self, value):
        self.raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.closed = False
    def read(self, limit): return self.raw[:limit]
    def __enter__(self): return self
    def __exit__(self, *args): self.closed = True


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
    def open(self, req, *, timeout):
        self.calls.append((req, timeout))
        value = self.responses.pop(0)
        if isinstance(value, BaseException): raise value
        return value


class ReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd() / '.niulai-state' / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / '.niulai-state' / 'tiger'
        self.state.mkdir(parents=True, mode=0o700)
        self.fence = self.state / 'unresolved.json'
        self.original = json.dumps({'attempt_id': ATTEMPT, 'commit_id': COMMIT,
            'phase': 'checkpoint', 'automatic_retry': False,
            'profile_retained': 'SYNTHETIC-PRIVATE-REFERENCE'}).encode()
        self.fence.write_bytes(self.original)
        self.fence.chmod(0o600)
        self.lock = self.state / 'bridge.lock'
        self.lock.touch(mode=0o600)
        self.source = self.root / '.niulai-state' / 'source.js'
        self.source.write_bytes(b'// Synthetic isolated source fingerprint.\n')
        self.source.chmod(0o600)
        self.policy, self.context = context()
        self.pin = patch.object(r, 'SOURCE_SHA256', hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.pin.start()
        self.addCleanup(self.pin.stop)

    def tearDown(self):
        self.assertEqual(self.fence.read_bytes(), self.original)

    def diagnose(self, opener):
        return r.diagnose(self.root, self.policy, self.context, self.source, opener=opener)

    def test_exact_two_routes_no_profile_and_current_commit_only(self):
        responses = [Response(HEALTH), Response(ACK)]
        opener = Opener(*responses)
        result = self.diagnose(opener)
        self.assertEqual(len(opener.calls), 2)
        health, probe = [call[0] for call in opener.calls]
        self.assertEqual((health.method, health.full_url, health.data),
                         ('GET', self.policy['origin'] + '/health', None))
        self.assertEqual((probe.method, probe.full_url),
                         ('POST', self.policy['origin'] + '/lease/checkpoint'))
        self.assertEqual(json.loads(probe.data), {'commit_id': COMMIT, 'lease_id': ATTEMPT})
        self.assertEqual([call[1] for call in opener.calls], [15, 15])
        self.assertTrue(all(response.closed for response in responses))
        self.assertEqual(result['original_commit'], 'latest_commit_acknowledged')
        self.assertFalse(result['lease_release_verified'])
        self.assertFalse(result['fence_retired'])
        self.assertNotIn('SYNTHETIC-', json.dumps(result))

    def test_rejected_old_commit_is_not_absent_or_reconciled(self):
        rejected = error.HTTPError('synthetic', 409, 'SYNTHETIC-SECRET-ERROR', {}, io.BytesIO(b'SECRET'))
        opener = Opener(Response(HEALTH), rejected)
        result = self.diagnose(opener)
        self.assertEqual(result['checkpoint_ack'], {'status': 'http_rejected', 'http_status': 409})
        self.assertEqual(result['original_commit'], 'history_unavailable_or_unconfirmed')
        self.assertEqual(len(opener.calls), 2)
        self.assertNotIn('SECRET', json.dumps(result))

    def test_transient_error_is_one_attempt_without_checkpoint(self):
        for status in (401, 403, 429, 503):
            with self.subTest(status=status):
                opener = Opener(error.HTTPError('synthetic', status, 'SECRET', {}, io.BytesIO(b'SECRET')))
                result = self.diagnose(opener)
                self.assertEqual(len(opener.calls), 1)
                self.assertEqual(result['checkpoint_ack']['status'], 'not_run')

    def test_lost_ack_is_unconfirmed_and_not_retried(self):
        opener = Opener(Response(HEALTH), TimeoutError('SECRET'))
        result = self.diagnose(opener)
        self.assertEqual(result['checkpoint_ack']['status'], 'transport_unconfirmed')
        self.assertEqual(len(opener.calls), 2)
        self.assertEqual(result['original_commit'], 'history_unavailable_or_unconfirmed')

    def test_uninitialized_store_skips_probe(self):
        opener = Opener(Response({**HEALTH, 'initialized': False}))
        result = self.diagnose(opener)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(result['checkpoint_ack']['status'], 'not_run')

    def test_secret_fields_or_wrong_scalars_rejected_and_response_closed(self):
        for payload in ({**HEALTH, 'profile': {'token': 'SECRET'}},
                        {**HEALTH, 'revision': True}, {**HEALTH, 'initialized': 'SECRET'},
                        {**HEALTH, 'last_committed_at': 'SECRET'},
                        b'{"revision":17,"revision":18}', b'{"revision":NaN}'):
            with self.subTest(payload=payload):
                response = Response(payload)
                opener = Opener(response)
                with self.assertRaisesRegex(TigerBridgeError, '^READBACK_RESPONSE_INVALID$'):
                    self.diagnose(opener)
                self.assertTrue(response.closed)
                self.assertEqual(len(opener.calls), 1)

    def test_oversized_response_has_one_attempt(self):
        response = Response(b'X' * (65536 + 1))
        opener = Opener(response)
        with self.assertRaisesRegex(TigerBridgeError, '^READBACK_RESPONSE_TOO_LARGE$'):
            self.diagnose(opener)
        self.assertTrue(response.closed)
        self.assertEqual(len(opener.calls), 1)

    def test_ack_must_be_closed_and_idempotent(self):
        for payload in ({**ACK, 'profile': 'SECRET'}, {**ACK, 'idempotent': False},
                        {**ACK, 'committed': False}, {**ACK, 'released': 'SECRET'}):
            with self.subTest(payload=payload):
                opener = Opener(Response(HEALTH), Response(payload))
                with self.assertRaisesRegex(TigerBridgeError, '^READBACK_RESPONSE_INVALID$'):
                    self.diagnose(opener)

    def test_source_drift_precedes_http(self):
        opener = Opener()
        self.source.write_bytes(b'Changed source')
        with self.assertRaisesRegex(TigerBridgeError, '^READBACK_SOURCE_DRIFT$'):
            self.diagnose(opener)
        self.assertEqual(opener.calls, [])

    def test_deployment_or_site_drift_precedes_http(self):
        for object_name, key, bad in (('deployment', 'status', 'failed'),
                                     ('version', 'source', {'commit_sha': 'wrong'}),
                                     ('site', 'latest_version_number', 2),
                                     ('site', 'current_user_role', 'editor')):
            with self.subTest(object_name=object_name):
                old = self.context[object_name][key]
                self.context[object_name][key] = bad
                try:
                    opener = Opener()
                    with self.assertRaises(TigerBridgeError): self.diagnose(opener)
                    self.assertEqual(opener.calls, [])
                finally: self.context[object_name][key] = old

    def test_lock_contention_precedes_http(self):
        fd = os.open(self.lock, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            opener = Opener()
            with self.assertRaisesRegex(TigerBridgeError, '^TIGER_BRIDGE_BUSY$'):
                self.diagnose(opener)
            self.assertEqual(opener.calls, [])
        finally: os.close(fd)

    def test_lock_released_after_malformed_response(self):
        with self.assertRaises(TigerBridgeError): self.diagnose(Opener(Response(b'{')))
        fd = os.open(self.lock, os.O_RDONLY)
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally: os.close(fd)

    def test_profile_phase_cannot_probe(self):
        self.fence.write_bytes(json.dumps({'phase': 'broker_read', 'attempt_id': ATTEMPT}).encode())
        try:
            opener = Opener()
            with self.assertRaisesRegex(TigerBridgeError, '^READBACK_CHECKPOINT_FENCE_REQUIRED$'):
                self.diagnose(opener)
            self.assertEqual(opener.calls, [])
        finally: self.fence.write_bytes(self.original)

    def test_route_and_original_identity_admission(self):
        client = r.ReadbackClient({'origin': self.policy['origin'], 'bearer': 'SYNTHETIC'}, opener=Opener())
        for action in ('/lease/acquire', 'release', 'profile'):
            with self.assertRaisesRegex(TigerBridgeError, '^READBACK_ROUTE_REJECTED$'):
                client.once(action)
        with self.assertRaisesRegex(TigerBridgeError, '^READBACK_ORIGINAL_IDS_REQUIRED$'):
            client.once('checkpoint_ack', commit_id='NEW', lease_id=ATTEMPT)
        self.assertEqual(client.attempts, 0)


if __name__ == '__main__': unittest.main()
