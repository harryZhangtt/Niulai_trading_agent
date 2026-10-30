import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from price_watch import classify
from triggered_research import baselines, digest, plan, validate_results


class TriggeredResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'research.sqlite'
        with sqlite3.connect(self.db) as db:
            db.executescript('''CREATE TABLE securities(symbol TEXT,payload TEXT);
              CREATE TABLE security_artifact_relations(security_symbol TEXT,artifact_id TEXT,section_id TEXT,relationship TEXT,payload TEXT);
              CREATE TABLE research_sections(id TEXT,artifact_id TEXT,payload TEXT);
              CREATE TABLE artifacts(library_file_id TEXT,payload TEXT);
              CREATE TABLE model_revisions(id TEXT,symbol TEXT,payload TEXT);''')
        self.config = {'config_revision': 8, 'alert_authority': 'niulai_saved_json_sqlite',
                       'price_monitor': {'studio_dependency': False, 'engine': 'scripts/price_watch.py', 'buffer_fraction': '.005'},
                       '_meta': {'user_timezone': 'Asia/Shanghai', 'session_timezone': 'America/New_York'},
                       'schedules': [], 'research': {'daily_triggered_review': {'enabled': False, 'batch_size': 1}}}
        self.rules = [dict(id='r1', ticker='ABC', direction='below', threshold='100', enabled=True, updatedAt='2026-10-01T00:00:00Z')]
        bar = dict(open='105', low='99', high='106', close='101', quote_time='2026-10-19T20:00:00Z', evidence='completed_daily_range_retrieved_retrospectively')
        row = classify(self.rules[0], bar, '104', '.005')
        row.update(session='2026-10-19', daily_leverage_multiplier='1')
        self.snapshot = dict(id='test', status='completed', mode='live', session='2026-10-19', config_revision=8,
                             as_of='2026-10-19T23:00:00Z', results=[row], errors=[],
                             coverage=dict(enabled_rules=1, valid_rules=1, failed_rules=0, symbols=1))

    def make_plan(self):
        self.snapshot['config_sha256'] = digest(self.config)
        self.snapshot['rules_sha256'] = digest(self.rules)
        return plan(self.config, self.rules, self.snapshot, '2026-10-19', self.db)

    def complete(self):
        planned = self.make_plan()
        item = dict(ticker='ABC', status='complete', evidence_delta='no_new_edge', alpha_claim=False,
                    checked_sources=[dict(url='https://example.test/filing', claim='test fixture only',
                                          published_at='2026-10-18T00:00:00Z', retrieved_at='2026-10-19T23:00:00Z')],
                    gaps=[], baseline_id='new_baseline', baseline_reconstruction_ref='new-model.json', action='wait', market_expectations='explicit gap',
                    position_proposal_reason='wait for better entry', alert_range_proposals=[], alert_range_proposal_reason='retain current ranges',
                    counter_evidence='competing supply', catalyst='earnings', invalidation='share loss', confidence='low',
                    independent_review_ref='review.json', causal_chain={k: 'fixture' for k in ('evidence', 'business_driver', 'owner_profit', 'valuation', 'market_gap', 'falsifier')},
                    model=dict(artifact_ref='model.json', checks_passed=True, probability_basis='illustrative', entry_price='100', horizon_years='2',
                               scenarios=[dict(probability='.5', terminal_wealth_per_share='50'), dict(probability='.5', terminal_wealth_per_share='150')]))
        return planned, dict(plan_id=planned['plan_id'], items=[item])

    def test_rebounded_hit_is_selected_and_stable(self):
        result = self.make_plan()
        self.assertEqual(result, self.make_plan())
        self.assertEqual(result['items'][0]['rules'][0]['location'], 'rebounded_outside_zone')
        self.assertEqual(result['items'][0]['baseline']['status'], 'not_catalogued')

    def test_disabled_rule_not_required(self):
        self.rules.append(dict(self.rules[0], id='disabled', enabled=False, ticker='DEF'))
        self.assertEqual(len(self.make_plan()['items']), 1)

    def test_same_ticker_multiple_rules_one_job(self):
        self.rules.append(dict(self.rules[0], id='r2'))
        self.snapshot['results'].append(dict(self.snapshot['results'][0], rule_id='r2'))
        self.snapshot['coverage'].update(enabled_rules=2, valid_rules=2)
        self.assertEqual(len(self.make_plan()['items']), 1)
        self.assertEqual(len(self.make_plan()['items'][0]['rules']), 2)

    def test_missing_rule_is_not_silently_dropped(self):
        self.snapshot['results'] = []
        with self.assertRaises(ValueError): self.make_plan()

    def test_explicit_coverage_failure_retained(self):
        self.snapshot.update(status='partial', results=[], errors=[dict(rule_id='r1', ticker='ABC', error='missing data')])
        self.snapshot['coverage'].update(valid_rules=0, failed_rules=1)
        self.assertEqual(self.make_plan()['status'], 'partial_coverage')

    def test_stale_revision_rejected(self):
        self.snapshot['config_revision'] = 7
        with self.assertRaises(ValueError): self.make_plan()

    def test_stale_quote_rejected(self):
        self.snapshot['results'][0]['quote_time'] = '2026-10-19T19:55:00Z'
        with self.assertRaises(ValueError): self.make_plan()

    def test_rule_change_rejected(self):
        self.rules[0]['threshold'] = '95'
        with self.assertRaises(ValueError): self.make_plan()

    def test_replay_requires_explicit_opt_in(self):
        self.snapshot['mode'] = 'replay'
        with self.assertRaises(ValueError): self.make_plan()
        self.assertTrue(plan(self.config, self.rules, self.snapshot, '2026-10-19', self.db, True)['retrospective'])

    def test_approach_only_not_threshold(self):
        row = self.snapshot['results'][0]
        row.update(low='100.2', close='100.3', threshold_reached=False, currently_in_zone=True)
        self.assertEqual(self.make_plan()['items'][0]['rules'][0]['attainment'], 'approach_only')

    def test_inconsistent_classification_rejected(self):
        self.snapshot['results'][0]['threshold_reached'] = False
        with self.assertRaises(ValueError): self.make_plan()

    def test_models_from_relations_not_empty_model_table(self):
        with sqlite3.connect(self.db) as db:
            db.execute('INSERT INTO securities VALUES(?,?)', ('ABC', json.dumps(dict(status='researched', latest_analysis_section_ids=['latest']))))
            db.execute('INSERT INTO security_artifact_relations VALUES(?,?,?,?,?)', ('ABC', 'model', 'old', 'supporting_model', json.dumps(dict(artifact_id='model', relationship='supporting_model'))))
            for sid, aid in [('latest', 'price'), ('old', 'model')]:
                db.execute('INSERT INTO research_sections VALUES(?,?,?)', (sid, aid, json.dumps(dict(id=sid))))
                db.execute('INSERT INTO artifacts VALUES(?,?)', (aid, json.dumps(dict(library_file_id=aid))))
        baseline = baselines(self.db, ['ABC'])['ABC']
        self.assertEqual(len(baseline['model_candidates']), 1)
        self.assertEqual({s['id'] for s in baseline['sections']}, {'latest', 'old'})

    def test_ev_arithmetic(self):
        planned, result = self.complete()
        output = validate_results(planned, result)
        self.assertEqual(output['items'][0]['expected_horizon_return'], '0.0')
        self.assertEqual(output['items'][0]['loss_probability'], '0.5')
        self.assertFalse(output['semantic_truth_verified'])

    def test_bad_probabilities_rejected(self):
        planned, result = self.complete()
        result['items'][0]['model']['scenarios'][0]['probability'] = '.6'
        with self.assertRaises(ValueError): validate_results(planned, result)

    def test_no_forced_alpha(self):
        planned, result = self.complete()
        result['items'][0]['alpha_claim'] = True
        with self.assertRaises(ValueError): validate_results(planned, result)

    def test_missing_ticker_rejected(self):
        planned, result = self.complete()
        result['items'] = []
        with self.assertRaises(ValueError): validate_results(planned, result)

    def test_partial_cannot_carry_model(self):
        planned, result = self.complete()
        result['items'][0].update(status='partial', action='pending_research', gaps=['missing sources'])
        with self.assertRaises(ValueError): validate_results(planned, result)
        result['items'][0]['model'] = None
        self.assertFalse(validate_results(planned, result)['all_research_complete'])

    def test_nan_rejected(self):
        planned, result = self.complete()
        result['items'][0]['model']['scenarios'][0]['terminal_wealth_per_share'] = 'NaN'
        with self.assertRaises(ValueError): validate_results(planned, result)

    def test_corrupt_zone_edge_rejected(self):
        self.snapshot['results'][0].update(zone_edge='1000', currently_in_zone=True)
        with self.assertRaises(ValueError): self.make_plan()

    def test_corrupt_leverage_rejected(self):
        self.snapshot['results'][0]['daily_leverage_multiplier'] = '3'
        with self.assertRaises(ValueError): self.make_plan()

    def test_leverage_requires_path_model(self):
        planned, result = self.complete()
        planned['items'][0]['research_profile'] = 'leveraged_fund'
        with self.assertRaises(ValueError): validate_results(planned, result)

    def test_missing_baseline_reconstruction_rejected(self):
        planned, result = self.complete()
        result['items'][0]['baseline_id'] = 'invented'
        with self.assertRaises(ValueError): validate_results(planned, result)

    def test_position_does_not_double_allocate(self):
        planned, result = self.complete()
        result['items'][0].update(action='add', position_proposal=dict(conditional=True, assumed_current_weight='.04', target_weight='.04', tranches=[dict(portfolio_weight='.04', condition='lower price')]))
        with self.assertRaises(ValueError): validate_results(planned, result)

    def test_snapshot_hash_mismatch_rejected(self):
        self.make_plan()
        self.snapshot['rules_sha256'] = 'wrong'
        with self.assertRaises(ValueError): plan(self.config, self.rules, self.snapshot, '2026-10-19', self.db)

    def test_missing_fingerprints_not_allowed_live(self):
        with self.assertRaises(ValueError): plan(self.config, self.rules, self.snapshot, '2026-10-19', self.db, True, True)


if __name__ == '__main__':
    unittest.main()
