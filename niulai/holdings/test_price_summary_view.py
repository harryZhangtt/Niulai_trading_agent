import unittest,copy,json,html
from pathlib import Path
from decimal import Decimal as D
from price_summary_view import build,render,from_database

def row(price='99',threshold='100',direction='below'):
 return {'rule_id':'r1','ticker':'EXAMPLE','direction':direction,'threshold':threshold,'zone_edge':'100.5' if direction=='below' else '99.5','close':price,'quote_time':'2026-10-23T20:00:00+00:00','threshold_reached':D(price)<=D(threshold) if direction=='below' else D(price)>=D(threshold),'currently_in_zone':D(price)<=D('100.5') if direction=='below' else D(price)>=D('99.5'),'zone_reached':False,'directional_entry_supported':False}
def run(rows,as_of='2026-10-23T23:00:00+00:00',errors=None):
 return {'id':as_of,'status':'completed','mode':'live','role':'existing_summary','as_of':as_of,'session':'2026-10-23','coverage':{'enabled_rules':len(rows)+len(errors or [])},'results':rows,'errors':errors or [],'new_signals':[]}
def previous(price='101',threshold='100',direction='below'):
 r=row(price,threshold,direction);r['quote_time']='2026-10-23T17:00:00+00:00';return run([r],'2026-10-23T17:10:00+00:00')
class PriceViewTests(unittest.TestCase):
 def test_new_observed_attainment_not_claimed_cross_time(self):
  m=build(run([row()]),previous());self.assertEqual(m['groups']['newly_satisfied'],1);self.assertEqual(m['directional_evidence_count'],0);self.assertIn('两次观察之间',m['rows'][0]['reason'])
 def test_already_satisfied_no_new_market_hit(self):self.assertEqual(build(run([row()]),previous('98'))['groups']['already_satisfied'],1)
 def test_missing_prior_not_new_hit(self):
  p=run([],'2026-10-23T17:10:00+00:00',[{'rule_id':'r1','ticker':'EXAMPLE','direction':'below','threshold':'100','error':'provider failed'}]);m=build(run([row()]),p);self.assertEqual(m['groups']['newly_confirmed'],1);self.assertIn('缺失',m['rows'][0]['reason'])
 def test_engine_record_independent_of_price_transition(self):
  r=run([row()]);r['new_signals']=[copy.deepcopy(r['results'][0])];m=build(r,previous('98'));self.assertEqual(m['groups']['already_satisfied'],1);self.assertTrue(m['rows'][0]['new_engine_record'])
 def test_changed_threshold_invalidates_comparison(self):self.assertEqual(build(run([row()]),previous('101','102'))['groups']['newly_confirmed'],1)
 def test_same_quote_timestamp_cannot_prove_transition(self):
  p=previous();p['results'][0]['quote_time']='2026-10-23T20:00:00+00:00';self.assertEqual(build(run([row()]),p)['groups']['newly_confirmed'],1)
 def test_replay_never_creates_market_comparison(self):
  p=previous();p['mode']='replay';self.assertEqual(build(run([row()]),p)['groups']['newly_confirmed'],1)
 def test_inclusive_threshold_equality(self):self.assertTrue(build(run([row('100')]),previous())['rows'][0]['currently_satisfied'])
 def test_above_rules_and_gap(self):
  m=build(run([row('102',direction='above')]),previous('99',direction='above'));self.assertEqual(m['groups']['newly_satisfied'],1);self.assertEqual(D(m['rows'][0]['gap_pct']),D('-2'))
 def test_approach_only(self):self.assertEqual(build(run([row('100.2')]))['groups']['approach_only'],1)
 def test_touched_then_exited(self):
  r=row('101');r['threshold_reached']=True;self.assertEqual(build(run([r]))['groups']['exited'],1)
 def test_errors_in_scope_not_not_reached(self):
  e={'rule_id':'r1','ticker':'EXAMPLE','direction':'below','threshold':'100','error':'stale'};m=build(run([],errors=[e]));self.assertEqual(m['groups']['unverifiable'],1);self.assertEqual(m['groups']['not_reached'],0)
 def test_duplicate_or_missing_scope_rejected(self):
  with self.assertRaises(ValueError):build(run([row(),row()]))
  r=run([row()]);r['coverage']['enabled_rules']=2
  with self.assertRaises(ValueError):build(r)
 def test_future_evidence_rejected(self):
  with self.assertRaises(ValueError):build(run([row()]),run([row()],'2026-10-24T00:00:00+00:00'))
 def test_replay_signals_rejected(self):
  r=run([row()]);r['mode']='replay';r['new_signals']=[row()]
  with self.assertRaises(ValueError):build(r)
 def test_output_escapes_external_notes(self):
  r=row();r['note']='<script>bad</script>';self.assertNotIn('<script>',render(build(run([r]))))
 def test_all_saved85_and_four_missing_data_not_crossings(self):
  p=Path(__file__).parent/'price_visual_test';fixture=json.loads((p/'frozen_price_runs.json').read_text());m=build(fixture['current'],fixture['prior'])
  self.assertEqual(m['groups'],{'newly_satisfied':0,'already_satisfied':28,'newly_confirmed':4,'approach_only':0,'exited':1,'not_reached':52,'unverifiable':0});self.assertEqual(len(m['rows']),85);self.assertEqual(len(m['new_signal_records']),4)
  self.assertEqual({r['ticker'] for r in m['rows'] if r['group']=='newly_confirmed'},{'IFNNY','SIVEF'});self.assertEqual(m['directional_evidence_count'],0)
  output=render(m)
  for r in m['rows']:self.assertIn(html.escape(r['ticker']),output)
