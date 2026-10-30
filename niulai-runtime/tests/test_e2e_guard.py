"""Synthetic canonical-email guard checks; no broker, model or mail calls."""
import base64
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from niulai_runtime import e2e_guard as g
from niulai_runtime.delivery import DeliveryError

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / '.niulai-state' / 'tests'
PRIVATE.mkdir(parents=True, exist_ok=True)
RECIPIENT = 'owner@example.test'
REQUEST = 'synthetic-e2e-02'


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=PRIVATE)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / '.niulai-state/e2e' / REQUEST
        self.out.mkdir(mode=0o700, parents=True)
        code = self.root / 'niulai/holdings'
        code.mkdir(mode=0o700, parents=True)
        for name in ('compose_digest.py', 'price_summary_view.py'):
            shutil.copyfile(ROOT / 'niulai/holdings' / name, code / name)
        self.portfolio = {'accounts': [{
            'daily_performance': {'session': '2020-01-03', 'aggregate_pnl': '10', 'capital_return_pct': '1',
                'positions': [{'symbol': 'TEST', 'pnl': '10', 'pnl_pct': '1'},
                              {'symbol': 'MISS', 'pnl': None, 'pnl_pct': None}], 'note': 'Synthetic missing-price coverage.'},
            'position_totals': {'snapshot_nav': '1000', 'snapshot_net': '900', 'snapshot_cash': '100',
                'snapshot_residual': '0', 'snapshot_query_at': '2020-01-04T12:00:00+00:00',
                'assets_query_at': '2020-01-04T12:00:01+00:00'}}]}
        self.result = {'id': 'synthetic-replay', 'status': 'partial', 'session': '2020-01-03',
            'as_of': '2020-01-03T21:01:00+00:00', 'mode': 'replay', 'retrospective': True,
            'coverage': {'enabled_rules': 2, 'valid_rules': 1, 'failed_rules': 1},
            'results': [{'rule_id': 'rule-1', 'ticker': 'TEST', 'direction': 'below', 'threshold': '100',
                'close': '90', 'zone_edge': '100.5', 'quote_time': '2020-01-03T21:00:00+00:00',
                'retrieved_at': '2020-01-04T12:00:02+00:00', 'currently_in_zone': True, 'threshold_reached': True}],
            'errors': [{'rule_id': 'rule-2', 'id': 'rule-2', 'ticker': 'MISS', 'direction': 'below',
                'threshold': '10', 'error': 'Synthetic missing dated quote'}], 'new_signals': []}
        renderer, _ = g._preserved(self.root, 'price_summary_view.py')
        self.view = renderer.build(self.result, historical=True)
        self.tiger = {'status': 'rendered_partial', 'committed': True, 'release_requested': True,
            'session': '2020-01-03', 'mode': 'run', 'source': 'existing_owner_private_store'}
        self.prep = {'status': 'partial', 'inputs_unchanged': True, 'live_state_unchanged': True,
            'new_live_events': 0, 'production_slot_completed': False, 'mode': 'replay',
            'session': '2020-01-03', 'run_id': 'synthetic-replay', 'coverage': self.result['coverage']}
        self.write('holdings/daily.json', self.portfolio)
        self.write('holdings/tiger_status.json', self.tiger)
        self.write('prices/price_result.json', self.result)
        self.write('prices/price_view/price_view.json', self.view)
        self.write('prices/preparation_receipt.json', self.prep)
        for name, raw in [('holdings/daily.pdf', b'%PDF-1.4\nsynthetic-holdings\n%%EOF\n'),
                          ('prices/price.pdf', b'%PDF-1.4\nsynthetic-price\n%%EOF\n'),
                          ('prices/price_message.txt', b'Complete synthetic price results, not a link.')]:
            p = self.out / name;p.parent.mkdir(parents=True, exist_ok=True);p.write_bytes(raw)

    def write(self, name, value):
        p = self.out / name;p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        p.write_text(json.dumps(value));p.chmod(0o600)

    def compose(self, request=REQUEST):
        return g.compose(self.root, self.out, RECIPIENT, request)

    def test_deterministic_full_scope_partial_banner_and_two_exact_pdf_bytes(self):
        a = self.compose();b = self.compose()
        self.assertEqual(a, b)
        self.assertEqual(a['subject'], 'Niulai triggered | FULL scheduled E2E test | ' + REQUEST)
        html = a['payload']['parts'][0]['body']['content']
        self.assertIn('PARTIAL', html)
        self.assertIn('逐股盈亏可计算 1/2', html)
        self.assertIn('价格有效规则 1/2', html)
        self.assertIn('TEST', html);self.assertIn('MISS', html)
        self.assertIn('2020-01-04T12:00:02+00:00', html)
        pdfs = a['payload']['parts'][1:]
        self.assertEqual(len(pdfs), 2)
        self.assertEqual(base64.urlsafe_b64decode(pdfs[0]['body']['base64_url_content']), (self.out / 'holdings/daily.pdf').read_bytes())
        self.assertEqual(base64.urlsafe_b64decode(pdfs[1]['body']['base64_url_content']), (self.out / 'prices/price.pdf').read_bytes())
        self.assertEqual((self.out / 'source_integrity.json').stat().st_mode & 0o777, 0o600)
        self.assertTrue(g.validate(self.root, self.out, a, RECIPIENT, REQUEST)['digest'])

    def test_model_body_edit_subject_change_or_attachment_omission_rejected(self):
        original = self.compose()
        for mode in ('body', 'subject', 'attachment'):
            candidate = copy.deepcopy(original)
            if mode == 'body':candidate['payload']['parts'][0]['body']['content'] = '<html>Model summary only</html>'
            if mode == 'subject':candidate['subject'] += ' changed'
            if mode == 'attachment':candidate['payload']['parts'].pop()
            with self.subTest(mode=mode), self.assertRaises(DeliveryError):
                g.validate(self.root, self.out, candidate, RECIPIENT, REQUEST)

    def test_source_pdf_or_json_change_after_pin_cannot_be_recomposed(self):
        self.compose()
        p = self.out / 'prices/price.pdf'
        p.write_bytes(p.read_bytes() + b'changed')
        with self.assertRaisesRegex(DeliveryError, 'GUARD_IMMUTABLE_SOURCE_CHANGED'):
            self.compose()

    def test_session_commit_and_replay_provenance_are_enforced(self):
        bad = dict(self.tiger, committed=False)
        self.write('holdings/tiger_status.json', bad)
        with self.assertRaisesRegex(DeliveryError, 'GUARD_TIGER_COMMIT_REQUIRED'):
            self.compose()
        self.write('holdings/tiger_status.json', self.tiger)
        self.write('prices/preparation_receipt.json', dict(self.prep, inputs_unchanged=False))
        with self.assertRaisesRegex(DeliveryError, 'GUARD_PRICE_REPLAY_REQUIRED'):
            self.compose()
        self.write('prices/preparation_receipt.json', dict(self.prep, session='2020-01-02'))
        with self.assertRaisesRegex(DeliveryError, 'GUARD_SESSION_MISMATCH'):
            self.compose()

    def test_source_result_hash_and_no_live_event_proof_cannot_be_bypassed(self):
        changed = copy.deepcopy(self.result);changed['results'][0]['close'] = '80'
        self.write('prices/price_result.json', changed)
        with self.assertRaisesRegex(DeliveryError, 'GUARD_PRICE_SOURCE_HASH_MISMATCH'):
            self.compose()
        self.write('prices/price_result.json', self.result)
        self.write('prices/preparation_receipt.json', dict(self.prep, new_live_events=1))
        with self.assertRaisesRegex(DeliveryError, 'GUARD_PRICE_REPLAY_REQUIRED'):
            self.compose()

    def test_reusing_output_for_different_request_or_recipient_fails(self):
        self.compose()
        with self.assertRaisesRegex(DeliveryError, 'GUARD_IMMUTABLE_SOURCE_CHANGED'):
            self.compose('synthetic-other-request')
        with self.assertRaises(DeliveryError):
            g.compose(self.root, self.out, 'other@example.test', REQUEST)

    def test_outside_and_symlink_sources_are_rejected_before_read(self):
        with self.assertRaisesRegex(DeliveryError, 'GUARD_PATH_OUTSIDE_E2E'):
            g.compose(self.root, self.root / 'archive', RECIPIENT, REQUEST)
        p = self.out / 'prices/price.pdf'
        raw = p.read_bytes();p.unlink()
        outside = self.root / 'outside.pdf';outside.write_bytes(raw);p.symlink_to(outside)
        with self.assertRaises(DeliveryError):
            self.compose()


if __name__ == '__main__':
    unittest.main()
