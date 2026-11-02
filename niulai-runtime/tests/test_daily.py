"""Domain recovery regression: no broker/network/Gmail effects."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import os
import subprocess
import sys
import io
import tempfile
import unittest
from unittest.mock import patch

from niulai_runtime.daily_work import Work, atomic, sha
from niulai_runtime import daily_prices, daily_report, daily_job
from niulai_runtime.delivery import DeliveryError
from niulai_runtime.scheduler import ParallelRunEvidence
import test_config_scheduler as scheduler_fixture
import test_e2e_guard as guard_fixture
import test_replay as replay_fixture
ROOT, RECIPIENT, REQUEST = guard_fixture.ROOT, guard_fixture.RECIPIENT, guard_fixture.REQUEST


class ParallelAdmissionTests(scheduler_fixture.ConfigSchedulerTests):
    def test_explicit_parallel_authorization_does_not_fake_cutover(self):
        policy = self.config(mode='production', production_enabled=True)
        self.assertFalse(self.admit(config=policy).allowed)
        receipt = ParallelRunEvidence('synthetic-user-authorization', 'fixture-runtime')
        self.assertTrue(self.admit(config=policy, parallel=receipt).send_allowed)
        self.assertFalse(self.admit(config=policy, parallel=ParallelRunEvidence('x', 'wrong')).allowed)
        # Still rejects weekend/outside slot, and respects DST after Nov1.
        self.assertFalse(self.admit('2026-10-31T17:00:00+00:00', config=policy, parallel=receipt).allowed)
        self.assertFalse(self.admit('2026-11-02T17:00:00+00:00', config=policy, parallel=receipt).allowed)
        self.assertEqual(self.admit('2026-11-02T18:00:00+00:00', config=policy, parallel=receipt).slot, '13:00')
        self.assertFalse(self.admit('2026-11-02T19:00:01+00:00', config=policy, parallel=receipt).allowed)


class WorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / '.niulai-state/tests'); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.now = datetime.now(timezone.utc)
        self.work = Work(self.root)
        self.meta = {'purpose': 'test', 'scheduled_at': self.now.isoformat(),
                     'deadline': (self.now + timedelta(hours=1)).isoformat()}
        self.row = self.work.create('test-only-key', self.meta)

    def test_concurrent_claim_and_restart_keep_one_identity_and_checkpoint(self):
        self.assertTrue(self.work.claim(self.row['id'], 'attempt-one', self.now))
        restarted = Work(self.root)
        self.assertFalse(restarted.claim(self.row['id'], 'attempt-two', self.now))
        self.assertEqual(restarted.create('test-only-key', {**self.meta, 'ignored': 'new config'})['meta'], self.meta)
        self.assertEqual(restarted.get(self.row['id'])['tries'], 1)

    def test_due_recovery_bounded_backoff_deadline_and_access_failure(self):
        self.work.claim(self.row['id'], 'attempt-one', self.now)
        row = self.work.settle(self.row['id'], pending=True, now=self.now)
        self.assertEqual(row['state'], 'retry_wait')
        self.assertIsNone(self.work.due('test', self.now))
        later = self.now + timedelta(minutes=3)
        self.assertEqual(self.work.due('test', later)['id'], self.row['id'])
        self.assertTrue(self.work.claim(self.row['id'], 'attempt-two', later))
        self.assertEqual(self.work.settle(self.row['id'], pending=True, blocked=True, now=later)['state'], 'waiting_access')
        self.assertIsNone(self.work.due('test', later + timedelta(hours=2)))

    def test_uncertain_send_is_not_replayed_after_lease_expires(self):
        self.work.claim(self.row['id'], 'attempt-one', self.now)
        self.work.bind_delivery(self.row['id'], 'unknown-key')
        with self.work.connect() as db:
            db.execute("INSERT INTO outbox VALUES(?,?,?,'sending',?,NULL,?,?,NULL)",
                       ('unknown-key', 'synthetic-digest', '{}', 'send-attempt', self.now.isoformat(), self.now.isoformat()))
        self.assertFalse(Work(self.root).claim(self.row['id'], 'attempt-two', self.now + timedelta(minutes=31)))
        self.assertEqual(self.work.get(self.row['id'])['state'], 'delivery_unknown')


class DailyReportTests(guard_fixture.GuardTests):
    def setUp(self):
        super().setUp()
        # Reuse only synthetic source fixtures, under a separate domain directory.
        self.inputs = self.out / 'inputs'; self.inputs.mkdir()
        definitions = [{'id': r.get('rule_id') or r.get('id'), 'enabled': True, **r}
                       for r in self.result['results'] + self.result['errors']]
        atomic(self.inputs / 'alerts.json', {'alerts': definitions})
        renderer, _ = daily_report._preserved(self.root, 'price_summary_view.py')
        atomic(self.out / 'prices/price_view.json', renderer.build(self.result, definitions=definitions, historical=True))
        atomic(self.out / 'prices/prior.json', None)
        atomic(self.out / 'prices/branch.json', {'status': 'partial', 'pending': True, 'blocked': False})
        self.meta = {'inputs': str(self.inputs), 'recipient': RECIPIENT, 'purpose': 'test',
                     'ny_date': '2020-01-03', 'slot': '19:00'}

    def test_new_combined_path_brands_full_scope_and_exact_offline_pdfs(self):
        result = daily_report.compose(self.root, self.out, self.meta, REQUEST)
        payload = json.loads((Path(result['directory']) / 'payload.json').read_text())
        self.assertTrue(payload['subject'].startswith('[CODEX]'))
        self.assertIn('PARTIAL', payload['subject'])
        self.assertEqual(len(payload['payload']['parts']), 3)
        body = payload['payload']['parts'][0]['body']['content']
        for expected in ('TEST', 'MISS', REQUEST, '19:00', 'P&amp;L', 'PARTIAL'):
            self.assertIn(expected, body)
        self.assertEqual(daily_report.validate(self.root, Path(result['directory']), self.meta, REQUEST)['digest'], result['digest'])

    def test_prepared_report_stays_immutable_when_branch_recovers(self):
        result = daily_report.compose(self.root, self.out, self.meta, REQUEST)
        raw = (Path(result['directory']) / 'payload.json').read_bytes()
        self.write('prices/branch.json', {'status': 'completed', 'pending': False, 'blocked': False})
        self.assertEqual(daily_report.compose(self.root, self.out, self.meta, REQUEST)['digest'], result['digest'])
        self.assertEqual((Path(result['directory']) / 'payload.json').read_bytes(), raw)
        correction = daily_report.compose(self.root, self.out, self.meta, REQUEST, True, '0123456789abcdef')
        payload = json.loads((Path(correction['directory']) / 'payload.json').read_text())
        self.assertIn('补发', payload['subject'])
        self.assertIn('0123456789abcdef', payload['payload']['parts'][0]['body']['content'])

    def test_missing_holdings_explicit_unknown_pdf_and_preserved_price_groups(self):
        self.write('holdings/tiger_status.json', {'status': 'failed', 'committed': False,
                   'error': 'PROFILE_BUSY', 'reconciliation_required': True})
        daily_report.failure_holdings(self.root, self.out / 'holdings', '2020-01-03', 'PROFILE_BUSY')
        result = daily_report.compose(self.root, self.out, self.meta, REQUEST)
        self.assertFalse(result['holdings_ok']); self.assertTrue(result['partial'])
        self.assertTrue((self.out / 'holdings/daily.pdf').read_bytes().startswith(b'%PDF-'))
        payload = json.loads((Path(result['directory']) / 'payload.json').read_text())
        body = payload['payload']['parts'][0]['body']['content']
        self.assertIn('PROFILE_BUSY', body); self.assertIn('TEST', body); self.assertIn('待补', body)
        self.assertTrue(json.loads((self.out / 'holdings/tiger_original_status.json').read_text())['reconciliation_required'])

    def test_ready_holdings_are_not_replaced_by_a_failure_placeholder(self):
        with self.assertRaisesRegex(DeliveryError, 'READY_HOLDINGS_MUST_BE_REUSED'):
            daily_report.failure_holdings(self.root, self.out / 'holdings', '2020-01-03', 'PROFILE_BUSY')


class CheckpointTests(unittest.TestCase):
    def test_failed_symbol_only_is_fetched_on_recovery_and_raw_bytes_survive(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.niulai-state/tests') as folder:
            root = Path(folder); inputs = root / '.niulai-state/inputs'; inputs.mkdir(parents=True)
            workflow = {'config_revision': 1, 'alert_authority': 'niulai_saved_json_sqlite',
                        'price_monitor': {'buffer_fraction': '0.005', 'quote_only_symbols': ['QUOTE']}}
            rules = [{'id': s, 'ticker': s, 'threshold': '100', 'enabled': True, 'direction': 'below',
                      'updatedAt': '2019-12-01T00:00:00Z'} for s in ('TEST', 'MISS')]
            atomic(inputs / 'workflow.json', workflow); atomic(inputs / 'alerts.json', {'alerts': rules})
            with sqlite3.connect(inputs / 'alerts.sqlite') as db:
                db.execute('create table fixture(value text)')
            meta = {'purpose': 'test', 'scope': 'synthetic-checkpoints', 'inputs': str(inputs),
                    'price_asof': '2020-01-03T21:01:00Z',
                    'input_sha256': {p.name: sha(p.read_bytes()) for p in inputs.iterdir()}}
            counts = {}; original = daily_prices.module; original_stage = daily_prices.stage
            def load(path, name):
                value = original(path, name)
                if path.name == 'price_watch.py':
                    value.validate_config = lambda _: None
                    def fetch(symbol, *_):
                        counts[symbol] = counts.get(symbol, 0) + 1
                        if symbol == 'MISS' and counts[symbol] == 1:
                            return {'ticker': symbol, 'error': 'HTTP Error 500: Internal Server Error', 'retrieved_at': '2020-01-04T00:00:00Z'}
                        raw = json.dumps({'fixture': symbol})
                        return {'ticker': symbol, 'raw': raw, 'sha256': sha(raw.encode()), 'source_url': 'https://fixture.example/quote',
                            'retrieved_at': '2020-01-04T00:00:00Z', 'previous': '110', 'splits': [],
                            'bar': {'open': '100', 'close': '90', 'low': '89', 'high': '101',
                                    'quote_time': '2020-01-03T21:00:00Z', 'evidence': 'synthetic_completed_daily_range'}}
                    value.fetch = fetch
                return value
            out = root / '.niulai-state/prices'
            with patch.object(daily_prices, 'module', side_effect=load), patch.object(daily_prices, 'stage', side_effect=lambda _, code: original_stage(ROOT, code)):
                first = daily_prices.prepare(root, out, meta)
                self.assertTrue(first['pending']); self.assertEqual(first['coverage']['valid_rules'], 1)
                second = daily_prices.prepare(root, out, meta)
            self.assertEqual(counts, {'TEST': 1, 'MISS': 2, 'QUOTE': 1})
            self.assertFalse(second['pending']); self.assertEqual(second['coverage']['valid_rules'], 2)
            self.assertEqual(second['mode'], 'replay')
            with sqlite3.connect(out / 'observations.sqlite') as db:
                self.assertEqual(db.execute('select count(*) from daily_sources').fetchone()[0], 3)
                self.assertEqual(db.execute('select count(*) from price_sources').fetchone()[0], 6)
                self.assertEqual(db.execute('select count(*) from price_signals').fetchone()[0], 0)


class DraftTransportTests(unittest.TestCase):
    def test_prepared_mail_is_completed_before_refreshing_its_price_branch(self):
        from niulai_runtime.replay import from_raw
        with tempfile.TemporaryDirectory(dir=ROOT / '.niulai-state/tests') as folder:
            root = Path(folder); work = Work(root); now = datetime.now(timezone.utc)
            row = work.create('prepared-before-data-retry', {'scheduled_at': now.isoformat(),
                'deadline': (now + timedelta(hours=1)).isoformat(), 'purpose': 'test'})
            out = root / '.niulai-state/daily' / row['id']; (out / 'prices').mkdir(parents=True)
            atomic(out / 'prices/branch.json', {'status': 'partial', 'pending': True, 'blocked': False})
            payload = from_raw(replay_fixture.encode(replay_fixture.raw_message()), RECIPIENT)
            work.outbox.prepare('prepared-key', payload, recipient=RECIPIENT, profile_email=RECIPIENT)
            work.bind_delivery(row['id'], 'prepared-key')
            with patch.object(sys, 'argv', ['daily_job', 'prices', '--workspace', str(root), '--work-id', row['id']]), \
                 patch('niulai_runtime.daily_prices.prepare') as acquire, patch('sys.stdout', io.StringIO()) as output:
                daily_job.main()
            acquire.assert_not_called()
            self.assertTrue(json.loads(output.getvalue())['deferred_until_delivery_verified'])

    def test_draft_requires_exact_mime_and_cannot_change_identity(self):
        from niulai_runtime.replay import from_raw
        encoded = replay_fixture.encode(replay_fixture.raw_message())
        payload = from_raw(encoded, RECIPIENT)
        with tempfile.TemporaryDirectory(dir=ROOT / '.niulai-state/tests') as folder:
            directory = Path(folder)
            value = daily_job.bind_draft(directory, payload, RECIPIENT, 'r123456789', '0123456789abcdef', encoded)
            self.assertEqual(value['draft_id'], 'r123456789')
            self.assertEqual(daily_job.bind_draft(directory, payload, RECIPIENT, 'r123456789', '0123456789abcdef', encoded), value)
            with self.assertRaisesRegex(DeliveryError, 'DAILY_DRAFT_IMMUTABLE'):
                daily_job.bind_draft(directory, payload, RECIPIENT, 'r987654321', '0123456789abcdef', encoded)
            altered = copy.deepcopy(payload); altered['subject'] += ' altered'
            with self.assertRaisesRegex(DeliveryError, 'CONTENT_PARITY_FAILED'):
                daily_job.bind_draft(directory, altered, RECIPIENT, 'r123456789', '0123456789abcdef', encoded)

    def test_large_tty_readback_is_not_truncated_or_echoed(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.niulai-state/tests') as folder:
            root = Path(folder); out = root / '.niulai-state/daily/synthetic'; target = out / 'mail/initial/draft_readback.b64'
            target.parent.mkdir(parents=True); raw = b'QUFB' * 25000
            code = ('from niulai_runtime.daily_job import capture_readback; from pathlib import Path; '
                    'capture_readback(Path(__import__("sys").argv[1]),Path(__import__("sys").argv[2]),'
                    'Path(__import__("sys").argv[3]),100000)')
            master, slave = os.openpty()
            try:
                child = subprocess.Popen([sys.executable, '-c', code, str(root), str(out), str(target)],
                    stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
                self.assertEqual(child.stdout.readline().strip(), b'RAW_INPUT_READY')
                sent = 0
                while sent < len(raw):
                    sent += os.write(master, raw[sent:sent + 8192])
                stdout, stderr = child.communicate(timeout=5)
                self.assertEqual(child.returncode, 0, stderr.decode())
                self.assertNotIn(raw[:1000], stdout + stderr)
                self.assertEqual(target.read_bytes(), raw)
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            finally:
                os.close(master); os.close(slave)


if __name__ == '__main__':
    unittest.main()
