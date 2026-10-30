"""Offline replay pipeline using synthetic rules/quotes and real preserved code."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from niulai_runtime import e2e_prepare as e

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / '.niulai-state' / 'tests'
TESTS.mkdir(parents=True, exist_ok=True)
UTC = timezone.utc
NOW = datetime(2020, 1, 4, 12, tzinfo=UTC)


class Calendar:
    name = 'XNYS'

    def sessions_in_range(self, start, end):
        return [datetime(2020, 1, d, tzinfo=UTC) for d in (2, 3)]

    def session_close(self, day):
        return day.replace(hour=21)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TESTS)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / '.niulai-state' / 'e2e'
        self.base.mkdir(mode=0o700, parents=True)
        self.out = self.base / 'prepared'
        self.workflow = self.base / 'workflow.json'
        self.rules = self.base / 'alerts.json'
        self.dbpath = self.base / 'alerts.sqlite'
        scripts = Path('niulai/skills/investment-research-financial-services/references/niulai-workflow/scripts')
        holdings = Path('niulai/holdings')
        (self.root / scripts).mkdir(mode=0o700, parents=True)
        (self.root / holdings).mkdir(mode=0o700, parents=True)
        for name in ('price_watch.py', 'niulai_state.py', 'price_report.py'):
            shutil.copyfile(ROOT / scripts / name, self.root / scripts / name)
        for name in ('price_summary_view.py', 'render_price_pdf.py'):
            shutil.copyfile(ROOT / holdings / name, self.root / holdings / name)
        shutil.copytree(ROOT / holdings / 'fonts', self.root / holdings / 'fonts')
        self.config = {'config_revision': 1, 'alert_authority': 'niulai_saved_json_sqlite',
            '_meta': {'user_timezone': 'Asia/Shanghai', 'session_timezone': 'America/New_York'},
            'price_monitor': {'studio_dependency': False, 'engine': 'scripts/price_watch.py', 'buffer_fraction': '.005'},
            'schedules': [{'role': 'existing_summary', 'enabled': True, 'automation_id': 'synthetic', 'times': ['13:00', '19:00']}],
            'notifications': {'configuration_managed': False}}
        self.definitions = [{'id': 'synthetic-rule', 'ticker': 'TEST', 'direction': 'below', 'threshold': '100',
            'enabled': True, 'updatedAt': '2019-01-01T00:00:00Z', 'note': 'Synthetic fixture'}]
        self.workflow.write_text(json.dumps(self.config))
        self.rules.write_text(json.dumps({'alerts': self.definitions}))
        spec = importlib.util.spec_from_file_location('synthetic_preserved_price_watch', ROOT / scripts / 'price_watch.py')
        self.engine = importlib.util.module_from_spec(spec)
        before_path = list(sys.path)
        old_state = sys.modules.get('niulai_state')
        sys.path.insert(0, str(ROOT / scripts))
        try:
            spec.loader.exec_module(self.engine)
        finally:
            sys.path[:] = before_path
            if old_state is None:
                sys.modules.pop('niulai_state', None)
            else:
                sys.modules['niulai_state'] = old_state
        self.market = {'date': '2020-01-03', 'previous': '2020-01-02',
            'open': datetime(2020, 1, 3, 14, 30, tzinfo=UTC), 'close': datetime(2020, 1, 3, 21, tzinfo=UTC)}
        bar = {'open': '110', 'high': '112', 'low': '90', 'close': '95', 'quote_time': '2020-01-03T21:00:00+00:00',
               'evidence': 'synthetic_completed_daily_range'}
        self.source = {'ticker': 'TEST', 'bar': bar, 'previous': '105', 'splits': [],
            'source_url': 'https://synthetic.example.test/quote', 'retrieved_at': NOW.isoformat(), 'raw': '{}', 'sha256': 'synthetic'}
        prior_row = self.engine.classify(self.definitions[0], {**bar, 'close': '105', 'low': '101', 'high': '112',
            'open': '110', 'quote_time': '2020-01-02T21:00:00+00:00'}, '110', '.005')
        prior = {'id': 'synthetic-live-prior', 'status': 'completed', 'mode': 'live', 'role': 'existing_summary',
            'as_of': '2020-01-02T21:01:00+00:00', 'session': '2020-01-02', 'retrospective': False,
            'coverage': {'enabled_rules': 1}, 'results': [prior_row], 'errors': [], 'new_signals': []}
        with sqlite3.connect(self.dbpath) as db:
            self.engine.setup(db)
            db.execute('INSERT INTO price_runs VALUES(?,?)', (prior['id'], json.dumps(prior)))
            db.execute('INSERT INTO price_completed_slots VALUES(?,?)', ('synthetic-live-slot', prior['id']))
            db.execute('INSERT INTO price_runs VALUES(?,?)', ('old-replay', json.dumps({'mode': 'replay'})))
            db.execute('INSERT INTO price_sources VALUES(?,?,?)', ('old-replay', 'TEST', '{}'))
            db.execute('INSERT INTO price_completed_slots VALUES(?,?)', ('old-replay-slot', 'old-replay'))
            db.execute('INSERT INTO price_signals VALUES(?,?,?,?,?,?)', ('old-event', '2020-01-02', 'synthetic-rule', 'synthetic', '{}', 'unconfirmed'))
        self.initial = e.digest(self.dbpath)

    def run_synthetic(self, command, **kwargs):
        if Path(command[1]).name == 'price_watch.py':
            dbpath = Path(command[command.index('--db') + 1])
            with sqlite3.connect(dbpath) as db, patch.object(self.engine, 'session', return_value=self.market), \
                    patch.object(self.engine, 'fetch_safe', return_value=self.source):
                cutoff = datetime.fromisoformat(command[command.index('--as-of') + 1])
                result = self.engine.run(self.config, self.definitions, db, cutoff, 'existing_summary', 'replay')
            Path(command[command.index('--output') + 1]).write_text(json.dumps(result))
            kwargs['log'].write_text('Synthetic network transport only; no external call.')
        else:
            e.run_stage(command, **kwargs)

    def prepare(self, runner=None):
        return e.prepare(self.root, self.workflow, self.rules, self.dbpath, self.out, '2020-01-03',
                         now=NOW, calendar=Calendar(), runner=runner or self.run_synthetic)

    def test_real_preserved_replay_and_renderers_keep_inputs_live_events_unchanged(self):
        receipt = self.prepare()
        self.assertEqual(receipt['status'], 'completed')
        self.assertEqual(receipt['copied_replay_cache_removed'], 1)
        self.assertTrue(receipt['inputs_unchanged'])
        self.assertTrue(receipt['live_state_unchanged'])
        self.assertEqual(e.digest(self.dbpath), self.initial)
        self.assertEqual(receipt['new_live_events'], 0)
        view = json.loads((self.out / 'price_view/price_view.json').read_text())
        self.assertTrue(view['historical_presentation'])
        self.assertEqual(len(view['rows']), 1)
        self.assertEqual(view['new_signal_records'], [])
        self.assertEqual(view['groups']['newly_satisfied'], 1)
        self.assertIn('TEST', (self.out / 'price_message.txt').read_text())
        self.assertTrue((self.out / 'price.pdf').read_bytes().startswith(b'%PDF-'))
        with sqlite3.connect(self.out / 'evaluation.sqlite') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM price_signals').fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM price_runs WHERE id='synthetic-live-prior'").fetchone()[0], 1)

    def test_only_latest_completed_session_and_close_plus_one_minute_are_allowed(self):
        close, cutoff = e.completed_cutoff('2020-01-03', NOW, Calendar())
        self.assertEqual(cutoff - close, timedelta(minutes=1))
        for day in ('2020-01-02', '2020-01-04'):
            with self.assertRaisesRegex(e.PreparationError, 'LAST_COMPLETED_SESSION_REQUIRED'):
                e.completed_cutoff(day, NOW, Calendar())
        with self.assertRaises(e.PreparationError):
            e.completed_cutoff('not-a-date', NOW, Calendar())
        with self.assertRaisesRegex(e.PreparationError, 'AWARE_CLOCK_REQUIRED'):
            e.completed_cutoff('2020-01-03', NOW.replace(tzinfo=None), Calendar())

    def test_live_event_or_wrong_mode_result_is_rejected_before_render(self):
        def corrupted(command, **kwargs):
            self.run_synthetic(command, **kwargs)
            if Path(command[1]).name == 'price_watch.py':
                result_path = Path(command[command.index('--output') + 1])
                result = json.loads(result_path.read_text());result['new_signals'] = [{'rule_id': 'synthetic-rule'}]
                result_path.write_text(json.dumps(result))
        with self.assertRaisesRegex(e.PreparationError, 'HISTORICAL_RESULT_REQUIRED'):
            self.prepare(corrupted)
        self.assertEqual(e.digest(self.dbpath), self.initial)
        self.assertEqual(json.loads((self.out / 'preparation_receipt.json').read_text())['status'], 'failed')
        self.assertFalse((self.out / 'price.pdf').exists())

    def test_nonprivate_paths_and_reused_output_fail_before_mutation(self):
        outside = self.root / 'archive-output'
        with self.assertRaisesRegex(e.PreparationError, 'E2E_PATH_OUTSIDE_BOUNDARY'):
            e.prepare(self.root, self.workflow, self.rules, self.dbpath, outside, '2020-01-03', now=NOW, calendar=Calendar())
        self.assertFalse(outside.exists())
        self.out.mkdir()
        with self.assertRaisesRegex(e.PreparationError, 'FRESH_OUTPUT_REQUIRED'):
            self.prepare()
        self.assertEqual(e.digest(self.dbpath), self.initial)


if __name__ == '__main__':
    unittest.main()
