"""Read-only dashboard projection of the Engine v5 provider safety ledger."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import shutil
import tempfile
import unittest
from unittest.mock import patch

from shared.job_runtime import dashboard as view
from shared.job_runtime.config import load
from shared.job_runtime.engine import Engine
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1
from shared.job_runtime.provider_contract import (
    FailureKind, Phase, ProviderResultV1, ReconciliationProofV1,
    ResultStatus, Submission, TerminalProof,
)
from shared.job_runtime.service import resource_jobs

UTC = timezone.utc
PRIVATE = view.ROOT / '.job-runtime' / 'dashboard-provider-tests'
PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)


class DashboardProviderRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=PRIVATE)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / '.job-runtime'
        (self.state / 'config').mkdir(parents=True, mode=0o700)
        self.state.chmod(0o700)
        (self.state / 'config').chmod(0o700)
        self.auth = self.state / 'auth'
        self.auth.mkdir(mode=0o700)
        (self.auth / 'auth.json').write_text('{}')
        (self.auth / 'auth.json').chmod(0o600)
        self.prompt = self.state / 'config/provider-prompt.md'
        self.prompt.write_text('synthetic prompt'); self.prompt.chmod(0o600)
        self.prompt_relative = '.job-runtime/config/provider-prompt.md'
        self.now = datetime(2026, 11, 6, 12, tzinfo=UTC)
        class Adapter:
            proof = None
            def reconcile(inner, **_kwargs):
                if inner.proof is None:
                    raise AssertionError('proof not installed')
                return inner.proof
        self.adapter = Adapter()
        self.write_config()

    def write_json(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_text(json.dumps(value))
        target.chmod(0o600)

    def write_config(self, *, effect='idempotent'):
        profile = {'provider': 'codex_cli', 'codex_bin': '/bin/true', 'model': 'synthetic',
                   'effort': 'medium', 'timeout_seconds': 10, 'auth_home': str(self.auth),
                   'circuit': {'failure_threshold': 1, 'open_seconds': 30, 'probe_seconds': 5}}
        job = {'id': 'typed.job', 'enabled': True,
               'schedule': {'kind': 'interval', 'seconds': 60},
               'model_profile': 'primary', 'prompt_file': self.prompt_relative,
               'replay_contract': {'version': 1, 'effect': effect,
                   'automatic_phases': ['not_started', 'connecting'],
                   'slot_operation_scope': 'typed/job',
                   'reconciliation_adapter': 'adapter/one' if effect == 'reconcile_before_replay' else None}}
        config = {'schema_version': 2, 'tick_seconds': 1, 'heartbeat_seconds': 1,
                  'stale_seconds': 30, 'max_workers': 1,
                  'retry': {'version': 2, 'max_attempts': 3, 'base_delay_seconds': 2,
                            'max_delay_seconds': 60},
                  'model_profiles': {'primary': profile},
                  'allocation_files': ['.job-runtime/config/jobs.json'], 'source_paths': []}
        self.write_json('.job-runtime/config/runtime.json', config)
        self.write_json('.job-runtime/config/jobs.json', {'schema_version': 2, 'jobs': [job]})

    def engine(self, dispatcher):
        config, jobs = load(self.state / 'config/runtime.json', self.root)
        prepared = resource_jobs(config, jobs)
        raw = b'synthetic prompt'; digest = hashlib.sha256(raw).hexdigest()
        artifact = PromptArtifactDescriptorV1(
            1, f'pa1:sha256:{digest}:{len(raw)}', digest, len(raw),
            hashlib.sha256(b'fixture://synthetic-prompt').hexdigest(),
            'dashboard-provider-fixture', 'native_v1')
        for job in prepared:
            capture = job.pop('_prompt_capture')
            self.assertEqual(capture.raw, raw)
            self.assertNotIn('synthetic prompt', repr(capture))
            job['_prompt_artifact'] = artifact
        return Engine(self.state / 'engine', prepared,
                      {'max_attempts': 3, 'backoff_seconds': 2, 'max_backoff_seconds': 60},
                      dispatcher, workspace_root=self.root, clock=lambda: self.now,
                      max_workers=1, reconciliation_adapters={'adapter/one': self.adapter})

    def retry(self, context, retry_after=None):
        return ProviderResultV1(
            'codex_cli', context['operation_id'], Phase.CONNECTING, Submission.NOT_SUBMITTED,
            TerminalProof.ABSENT, ResultStatus.RETRYABLE, 'HTTP_RATE_LIMITED',
            failure_kind=FailureKind.HTTP, http_status=429, provider_should_retry=True,
            retry_after_at=retry_after,
            retry_after_source='typed-timestamp' if retry_after else None)

    def project(self):
        return view.project(self.root, at=self.now, job_id='typed.job')

    def test_retry_after_open_circuit_and_read_only_packet_are_exact(self):
        wait = self.now + timedelta(seconds=17)
        engine = self.engine(lambda _job, context: self.retry(context, wait))
        self.assertEqual(engine.tick(self.now)['retry_wait'], 1)
        before = engine.path.read_bytes()
        result = self.project()
        safety = result['jobs'][0]['provider_safety']
        self.assertEqual(result['schema_version'], 1)
        self.assertEqual(result['scope'], 'local_codex_scheduler')
        self.assertEqual((safety['provider'], safety['delay_source']), ('codex_cli', 'circuit'))
        self.assertEqual(safety['delayed_until'], (self.now + timedelta(seconds=30)).isoformat())
        self.assertEqual(safety['retry_reason'], 'RETRY_SCHEDULED')
        self.assertEqual(safety['replay_authorization'], 'authorized')
        self.assertEqual(safety['circuit']['state'], 'open')
        self.assertEqual(safety['queue'], {'depth': 1, 'oldest_delayed_at': wait.isoformat()})
        self.assertEqual(result['provider_safety']['circuits']['open'], 1)
        self.assertEqual(engine.path.read_bytes(), before)
        with sqlite3.connect(engine.path) as db:
            db.execute("UPDATE circuits SET state='closed',transient_failures=0,opened_until=NULL,probe_owner=NULL,probe_expires=NULL")
        closed = self.project()['jobs'][0]['provider_safety']
        self.assertEqual((closed['delay_source'], closed['delayed_until']),
                         ('retry_after', wait.isoformat()))
        with sqlite3.connect(engine.path) as db:
            db.execute("UPDATE circuits SET state='open',opened_until=?,probe_owner=NULL,probe_expires=NULL",
                       ((self.now + timedelta(seconds=10)).timestamp(),))
        expired = view.project(self.root, at=self.now + timedelta(seconds=20),
                               job_id='typed.job')['jobs'][0]['provider_safety']
        self.assertTrue(expired['circuit']['probe_eligible'])
        self.assertIsNone(expired['delayed_until'])
        self.assertEqual(expired['queue']['depth'], 0)
        body = json.dumps(result)
        for forbidden in ('attempt/', str(self.auth), 'auth.json', 'resource_hash',
                          'HTTP_RATE_LIMITED', 'typed-timestamp'):
            self.assertNotIn(forbidden, body)

    def test_backoff_closed_half_open_and_unrelated_resource_scope(self):
        engine = self.engine(lambda _job, context: self.retry(context))
        engine.tick(self.now)
        with sqlite3.connect(engine.path) as db:
            db.execute("UPDATE circuits SET state='closed',transient_failures=0,opened_until=NULL,probe_owner=NULL,probe_expires=NULL")
            # Same provider/profile but a different private resource fence is unrelated.
            db.execute("INSERT INTO circuits VALUES(?,?,?,?,?,?,'open',1,?,?,NULL,?)",
                       ('codex_cli', 'primary', 'f' * 64, 'a' * 64, 'b' * 64, 0,
                        self.now.timestamp() + 999, None, self.now.timestamp()))
        safety = self.project()['jobs'][0]['provider_safety']
        self.assertEqual(safety['delay_source'], 'backoff')
        self.assertEqual(safety['circuit']['state'], 'closed')
        with sqlite3.connect(engine.path) as db:
            attempt_id = db.execute('SELECT attempt_id FROM attempts').fetchone()[0]
            db.execute('DROP TRIGGER immutable_provider_results_delete')
            db.execute('DROP TRIGGER immutable_retry_decisions_delete')
            db.execute('DROP TRIGGER guarded_attempt_update')
            db.execute('DELETE FROM provider_results')
            db.execute('DELETE FROM retry_decisions')
            db.execute("UPDATE attempts SET status='running',ended_at=NULL,receipt=NULL")
            db.execute("UPDATE slots SET status='running',next_attempt_at=NULL,operation_id=NULL")
            db.execute("UPDATE circuits SET state='half_open',opened_until=NULL,probe_owner=?,probe_expires=? WHERE resource_hash != ?",
                       (attempt_id, self.now.timestamp() + 5, 'f' * 64))
        safety = self.project()['jobs'][0]['provider_safety']
        self.assertEqual(safety['circuit']['state'], 'half_open')
        self.assertEqual(safety['circuit']['probe_until'], (self.now + timedelta(seconds=5)).isoformat())
        self.assertNotIn(attempt_id, json.dumps(safety))

    def test_unknown_reconciliation_fence_is_explicit(self):
        self.write_config(effect='reconcile_before_replay')
        engine = self.engine(lambda _job, context: ProviderResultV1(
            'codex_cli', context['operation_id'], Phase.TERMINAL,
            Submission.POSSIBLY_SUBMITTED, TerminalProof.ABSENT, ResultStatus.UNKNOWN,
            'PROVIDER_TIMEOUT', failure_kind=FailureKind.TIMEOUT))
        self.assertEqual(engine.tick(self.now)['unknown'], 1)
        safety = self.project()['jobs'][0]['provider_safety']
        self.assertTrue(safety['unknown_fence'])
        self.assertEqual(safety['replay_authorization'], 'reconciliation_required')
        self.assertEqual(safety['latest_attempt'], {
            'phase': 'terminal', 'submission': 'possibly_submitted',
            'terminal_proof': 'absent', 'status': 'unknown', 'failure': 'timeout'})

    def test_public_tick_claim_then_recover_running_projects_exact_unknown(self):
        self.write_config(effect='reconcile_before_replay')
        engine = self.engine(lambda _job, context: self.retry(context))
        engine._finish = lambda _job, _context, _result, _now: 'unknown'
        self.assertEqual(engine.tick(self.now)['unknown'], 1)
        self.assertEqual(engine.recover_running(self.now + timedelta(seconds=1)), 1)
        safety = view.project(self.root, at=self.now + timedelta(seconds=1),
                              job_id='typed.job')['jobs'][0]['provider_safety']
        self.assertEqual(safety['status'], 'available')
        self.assertEqual(safety['latest_attempt']['status'], 'unknown')
        self.assertTrue(safety['unknown_fence'])
        self.assertEqual(safety['retry_reason'], 'PROCESS_EXITED_OUTCOME_UNKNOWN')
        self.assertEqual(safety['replay_authorization'], 'reconciliation_required')

    def test_reconciliation_consumption_is_required_for_authorized_retry(self):
        self.write_config(effect='reconcile_before_replay')
        engine = self.engine(lambda _job, context: ProviderResultV1(
            'codex_cli', context['operation_id'], Phase.TERMINAL,
            Submission.POSSIBLY_SUBMITTED, TerminalProof.ABSENT, ResultStatus.UNKNOWN,
            'PROVIDER_TIMEOUT', failure_kind=FailureKind.TIMEOUT))
        engine.tick(self.now)
        with sqlite3.connect(engine.path) as db:
            attempt_id, operation_id, digest = db.execute(
                'SELECT a.attempt_id,p.operation_id,p.canonical_sha256 FROM attempts a '
                'JOIN provider_results p ON p.attempt_id=a.attempt_id').fetchone()
        evidence = b'synthetic absence evidence'
        proof = ReconciliationProofV1(
            attempt_id=attempt_id, operation_id=operation_id,
            slot_operation_scope='typed/job', provider_result_sha256=digest,
            outcome='absent', evidence_sha256=hashlib.sha256(evidence).hexdigest(),
            recorded_at=self.now)
        self.adapter.proof = proof
        engine.record_reconciliation_proof(
            proof, evidence, 'synthetic/ref', 'adapter/one', 'v1', self.now,
            adapter=self.adapter)
        engine.authorize_reconciled_retry(attempt_id, self.now + timedelta(seconds=1))
        safety = view.project(self.root, at=self.now + timedelta(seconds=1),
                              job_id='typed.job')['jobs'][0]['provider_safety']
        self.assertEqual(safety['replay_authorization'], 'authorized')
        self.assertEqual(safety['retry_reason'], 'RECONCILIATION_ABSENT_RETRY')
        with sqlite3.connect(engine.path) as db:
            db.execute('DROP TRIGGER immutable_reconciliation_consumptions_delete')
            db.execute('DELETE FROM reconciliation_consumptions')
        self.assertEqual(self.project()['jobs'][0]['provider_safety'], {'status': 'unavailable'})

    def test_cross_row_timing_transition_and_circuit_corruption_fail_closed(self):
        engine = self.engine(lambda _job, context: self.retry(context))
        engine.tick(self.now)
        with sqlite3.connect(engine.path) as db:
            original_status = db.execute('SELECT status FROM attempts').fetchone()[0]
            db.execute('DROP TRIGGER guarded_attempt_update')
            db.execute("UPDATE attempts SET status='failed'")
        self.assertEqual(self.project()['jobs'][0]['provider_safety'], {'status': 'unavailable'})
        with sqlite3.connect(engine.path) as db:
            db.execute('UPDATE attempts SET status=?', (original_status,))
            db.execute('DROP TRIGGER immutable_provider_results_update')
            original_slot = db.execute('SELECT slot_id FROM provider_results').fetchone()[0]
            db.execute("UPDATE provider_results SET slot_id='cross-slot'")
        self.assertEqual(self.project()['jobs'][0]['provider_safety'], {'status': 'unavailable'})
        with sqlite3.connect(engine.path) as db:
            db.execute('UPDATE provider_results SET slot_id=?', (original_slot,))
            original_operation = db.execute('SELECT operation_id FROM provider_results').fetchone()[0]
            db.execute("UPDATE provider_results SET operation_id='attempt/cross-binding'")
        self.assertEqual(self.project()['jobs'][0]['provider_safety'], {'status': 'unavailable'})
        with sqlite3.connect(engine.path) as db:
            db.execute('UPDATE provider_results SET operation_id=?', (original_operation,))
            db.execute('DROP TRIGGER immutable_retry_decisions_update')
            encoded, delay = db.execute(
                'SELECT canonical_json,delay_seconds FROM retry_decisions').fetchone()
            bad = json.loads(encoded); bad['delay_seconds'] = -1
            db.execute('UPDATE retry_decisions SET canonical_json=?,delay_seconds=-1',
                       (json.dumps(bad, sort_keys=True, separators=(',', ':')),))
        self.assertEqual(self.project()['jobs'][0]['provider_safety'], {'status': 'unavailable'})
        with sqlite3.connect(engine.path) as db:
            db.execute('UPDATE retry_decisions SET canonical_json=?,delay_seconds=?', (encoded, delay))
            state = db.execute('SELECT state,opened_until,config_sha256 FROM circuits').fetchone()
            db.execute("UPDATE circuits SET state='half_open',opened_until=NULL,probe_owner=NULL,probe_expires=?",
                       ((self.now + timedelta(seconds=5)).timestamp(),))
        self.assertEqual(self.project()['jobs'][0]['provider_safety'], {'status': 'unavailable'})
        with sqlite3.connect(engine.path) as db:
            db.execute('UPDATE circuits SET state=?,opened_until=?,probe_owner=NULL,probe_expires=NULL,config_sha256=?',
                       state)
            db.execute("UPDATE circuits SET config_sha256=?", ('0' * 64,))
        self.assertEqual(self.project()['jobs'][0]['provider_safety'], {'status': 'unavailable'})

    def test_pristine_ready_running_and_terminal_lifecycle_cross_product(self):
        engine = self.engine(lambda _job, context: self.retry(context))
        engine.tick(self.now)
        with sqlite3.connect(engine.path) as db:
            db.execute('DROP TRIGGER immutable_provider_results_delete')
            db.execute('DROP TRIGGER immutable_retry_decisions_delete')
            db.execute('DROP TRIGGER guarded_attempt_update')
            db.execute('DROP TRIGGER immutable_attempt_delete')
            db.execute('DELETE FROM provider_results')
            db.execute('DELETE FROM retry_decisions')
            db.execute("UPDATE attempts SET status='running',ended_at=NULL,receipt=NULL")
            db.execute("UPDATE slots SET status='ready',next_attempt_at=NULL,operation_id=NULL")
        self.assertEqual(self.project()['jobs'][0]['provider_safety'], {'status': 'unavailable'})
        with sqlite3.connect(engine.path) as db:
            db.execute("UPDATE slots SET status='running'")
        self.assertEqual(self.project()['jobs'][0]['provider_safety']['latest_attempt']['status'],
                         'running')
        with sqlite3.connect(engine.path) as db:
            db.execute('DELETE FROM attempts')
        self.assertEqual(self.project()['jobs'][0]['provider_safety'], {'status': 'unavailable'})
        with sqlite3.connect(engine.path) as db:
            db.execute("UPDATE slots SET status='ready',attempts=0")
        ready = self.project()['jobs'][0]['provider_safety']
        self.assertEqual(ready['status'], 'available')
        self.assertIsNone(ready['latest_attempt'])

    def test_succeeded_and_failed_terminal_matrices(self):
        success = self.engine(lambda _job, context: ProviderResultV1(
            'codex_cli', context['operation_id'], Phase.TERMINAL,
            Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
            ResultStatus.SUCCEEDED, 'COMPLETED'))
        self.assertEqual(success.tick(self.now)['succeeded'], 1)
        self.assertEqual(self.project()['jobs'][0]['provider_safety']['latest_attempt']['status'],
                         'succeeded')
        shutil.rmtree(self.state / 'engine')
        failed = self.engine(lambda _job, context: ProviderResultV1(
            'codex_cli', context['operation_id'], Phase.TERMINAL,
            Submission.POSSIBLY_SUBMITTED, TerminalProof.ABSENT,
            ResultStatus.FAILED, 'PROVIDER_FAILED', failure_kind=FailureKind.PROVIDER))
        self.assertEqual(failed.tick(self.now)['failed'], 1)
        safety = self.project()['jobs'][0]['provider_safety']
        self.assertEqual((safety['latest_attempt']['status'], safety['replay_authorization']),
                         ('failed', 'not_applicable'))

    def test_attempt_deadline_and_generation_corruption_are_independently_rejected(self):
        engine = self.engine(lambda _job, context: self.retry(context))
        engine.tick(self.now)
        with sqlite3.connect(engine.path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 9)
            attempts, deadline = db.execute('SELECT attempts,retry_deadline FROM slots').fetchone()
            generation = db.execute('SELECT generation FROM circuits').fetchone()[0]
            db.execute('UPDATE slots SET attempts=attempts+1')
        self.assertEqual(self.project()['jobs'][0]['provider_safety'], {'status': 'unavailable'})
        with sqlite3.connect(engine.path) as db:
            db.execute('UPDATE slots SET attempts=?', (attempts,))
            db.execute('UPDATE slots SET retry_deadline=retry_deadline+1')
        self.assertEqual(self.project()['jobs'][0]['provider_safety'], {'status': 'unavailable'})
        with sqlite3.connect(engine.path) as db:
            db.execute('UPDATE slots SET retry_deadline=?', (deadline,))
            db.execute('UPDATE circuits SET generation=-1')
        self.assertEqual(self.project()['jobs'][0]['provider_safety'], {'status': 'unavailable'})
        with sqlite3.connect(engine.path) as db:
            db.execute('UPDATE circuits SET generation=?', (generation,))
        self.assertEqual(self.project()['jobs'][0]['provider_safety']['status'], 'available')

    def test_malformed_secret_row_fails_only_provider_item_and_is_suppressed(self):
        engine = self.engine(lambda _job, context: self.retry(context))
        engine.tick(self.now)
        oversized = json.dumps({'error': 'SECRET_OVERSIZED_' * 5000})
        with sqlite3.connect(engine.path) as db:
            db.execute("DROP TRIGGER immutable_provider_results_update")
            db.execute("UPDATE provider_results SET canonical_json=?,canonical_sha256=?,operation_id='SECRET_OPERATION'",
                       (oversized, hashlib.sha256(oversized.encode()).hexdigest()))
        result = self.project()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['jobs'][0]['provider_safety'], {'status': 'unavailable'})
        self.assertEqual(result['provider_safety'], {
            'status': 'unavailable', 'jobs': 1, 'available_jobs': 0,
            'unknown_fences': 0, 'delayed_jobs': 0, 'queue_depth': 0,
            'circuits': {'closed': 0, 'open': 0, 'half_open': 0, 'unavailable': 0}})
        self.assertIn({'job_id': 'typed.job', 'code': 'PROVIDER_SAFETY_UNAVAILABLE'}, result['warnings'])
        packet = json.dumps(result)
        self.assertNotIn('SECRET_', packet)
        self.assertLess(len(packet.encode()), 100_000)

    def test_packet_snapshot_prevents_between_job_mutation_mix(self):
        allocation_path = self.state / 'config/jobs.json'
        allocation = json.loads(allocation_path.read_text())
        second = {**allocation['jobs'][0], 'id': 'typed.other'}
        allocation['jobs'].append(second)
        self.write_json('.job-runtime/config/jobs.json', allocation)
        engine = self.engine(lambda _job, context: self.retry(context))
        engine.tick(self.now)
        real = view._provider_safety_snapshot
        calls = []
        def mutate_between(root, loaded, job, at, db):
            calls.append(job['id'])
            if len(calls) == 1:
                with self.assertRaises(sqlite3.OperationalError):
                    with sqlite3.connect(engine.path, timeout=0) as writer:
                        writer.execute("UPDATE slots SET updated_at=updated_at+1 WHERE job_id='typed.other'")
            return real(root, loaded, job, at, db)
        with patch.object(view, '_provider_safety_snapshot', side_effect=mutate_between):
            result = view.project(self.root, at=self.now)
        self.assertEqual(calls, ['typed.job', 'typed.other'])
        self.assertEqual([job['provider_safety']['status'] for job in result['jobs']],
                         ['available', 'available'])

    def test_provider_selects_share_one_explicit_read_snapshot(self):
        engine = self.engine(lambda _job, context: self.retry(context))
        engine.tick(self.now)
        statements = []
        real_database = view.database
        @contextmanager
        def traced(*args, **kwargs):
            with real_database(*args, **kwargs) as db:
                db.set_trace_callback(statements.append)
                yield db
        with patch.object(view, 'database', traced):
            self.project()
        begin = statements.index('BEGIN')
        commit = statements.index('COMMIT', begin)
        snapshot = '\n'.join(statements[begin:commit + 1])
        for table in ('slots', 'attempts', 'circuits', 'retry_decisions',
                      'reconciliation_consumptions'):
            self.assertIn(table, snapshot)
        self.assertEqual(snapshot.count('BEGIN'), 1)
        self.assertEqual(snapshot.count('COMMIT'), 1)

    def test_query_timeout_is_item_unavailable_and_never_writes(self):
        engine = self.engine(lambda _job, context: self.retry(context))
        engine.tick(self.now)
        before = engine.path.read_bytes()
        real_database = view.database
        class TimedOut:
            def __enter__(self):
                raise sqlite3.OperationalError('interrupted SECRET_DATABASE_PATH')
            def __exit__(self, *_args):
                return False
        with patch.object(view, 'database', side_effect=lambda *_args, **_kw: TimedOut()):
            result = self.project()
        self.assertEqual(result['jobs'][0]['provider_safety'], {'status': 'unavailable'})
        self.assertNotIn('SECRET_DATABASE_PATH', json.dumps(result))
        self.assertEqual(engine.path.read_bytes(), before)
        with real_database(self.root, engine.path) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('DELETE FROM slots')

    def test_schema8_and_schema9_prompt_custody_project_counts_only(self):
        legacy = sqlite3.connect(':memory:')
        legacy.row_factory = sqlite3.Row
        legacy.execute('PRAGMA user_version=8')
        self.assertEqual(view.prompt_custody('typed.job', legacy),
                         {'status': 'legacy_unbound', 'attempts_bound': 0})
        legacy.close()
        engine = self.engine(lambda _job, context: self.retry(context))
        engine.tick(self.now)
        packet = self.project()
        self.assertEqual(packet['jobs'][0]['prompt_custody'],
                         {'status': 'bound', 'attempts_bound': 1})
        encoded = json.dumps(packet)
        for forbidden in ('synthetic prompt', 'provider-prompt.md', 'artifact_ref',
                          'source_identity_sha256', 'binding_sha256'):
            self.assertNotIn(forbidden, encoded)

    def test_legacy_packet_has_no_per_job_provider_fields(self):
        config = {'schema_version': 1, 'tick_seconds': 1, 'heartbeat_seconds': 1,
                  'stale_seconds': 30, 'max_workers': 1, 'retry': {}, 'source_paths': [],
                  'allocation_files': ['.job-runtime/config/jobs.json'],
                  'model_profiles': {'primary': {'auth_home': str(self.auth), 'model': 'synthetic'}}}
        job = {'id': 'legacy.job', 'enabled': True, 'replay_safe': True,
               'model_profile': 'primary', 'prompt_file': 'prompt.md',
               'schedule': {'kind': 'interval', 'seconds': 60}}
        self.write_json('.job-runtime/config/runtime.json', config)
        self.write_json('.job-runtime/config/jobs.json', {'schema_version': 1, 'jobs': [job]})
        result = view.project(self.root, at=self.now)
        self.assertNotIn('provider_safety', result['jobs'][0])
        self.assertEqual(result['provider_safety']['status'], 'not_applicable')


if __name__ == '__main__':
    unittest.main()
