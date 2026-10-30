import unittest,copy,math
import options_surface_checks as o
import options_scenario_checks as b

def fixture():
 p={'version':o.VERSION,'symbol':'ABC','valuation_at':'2026-10-23T20:00:00Z','spot':100,'rate':.04,'yield':0,'mode':'historical_diagnostic','policy':{'max_age_seconds':60,'max_skew_seconds':10,'max_relative_spread':.5},'contracts':[]}
 for exp in ['2027-01-15T21:00:00Z','2027-04-16T20:00:00Z']:
  t=(o.stamp(exp)-o.stamp(p['valuation_at'])).total_seconds()/(365*86400)
  for k in [80,90,100,110,120]:
   m=b.bsm('call',100,k,t,.04,0,.5)['price'];p['contracts'].append({'contract_id':'ABC'+o.stamp(exp).strftime('%y%m%d')+'C'+f'{k*1000:08d}','expiry_at':exp,'strike':k,'bid':m*.995,'ask':m*1.005,'quote_at':None,'source_ref':'synthetic fixture not market'})
 return p
class Tests(unittest.TestCase):
 def test_flat_surface(self):
  r=o.calculate(fixture());self.assertEqual(r['coverage'],{'input':10,'numeric_nodes':10,'rejected':0});self.assertFalse(r['executable']);self.assertFalse(r['arbitrage_free_certified']);self.assertTrue(all(abs(n['iv_mid']-.5)<1e-8 for n in r['nodes']));self.assertTrue(all(z['status']=='sampled_pass' for z in r['calendar_checks']));self.assertTrue(all(not x['violations'] for x in r['sampled_interpolated_strike_checks']));self.assertLess(r['holdout_summary']['mae_premium'],1e-8)
 def test_interval_roundtrip(self):
  for n in o.calculate(fixture())['nodes']:
   self.assertLess(n['iv_bid'],n['iv_mid']);self.assertLess(n['iv_mid'],n['iv_ask']);self.assertAlmostEqual(b.bsm('call',100,n['strike'],n['years'],.04,0,n['iv_bid'])['price'],n['bid'],places=8)
 def test_no_extrapolation(self):
  s={1:[{'log_moneyness':0,'variance_mid':.2},{'log_moneyness':1,'variance_mid':.4}],2:[{'log_moneyness':.2,'variance_mid':.4},{'log_moneyness':.8,'variance_mid':.6}]}
  for t,k in [(.9,.5),(2.1,.5),(1.5,.1)]:self.assertIsNone(o.surface(s,t,k))
  self.assertAlmostEqual(o.surface(s,1.5,.5),.4)
 def test_nodes_reproduced(self):
  r=o.calculate(fixture());s={}
  for n in r['nodes']:s.setdefault(n['years'],[]).append(n)
  for n in r['nodes']:self.assertEqual(o.surface(s,n['years'],n['log_moneyness']),n['variance_mid'])
 def test_monotonicity(self):self.assertIn('call_price_increases_with_strike',o.price_checks([{'strike':90,'mid':10},{'strike':100,'mid':11}],1))
 def test_vertical_bound(self):self.assertIn('vertical_spread_exceeds_discounted_width',o.price_checks([{'strike':90,'mid':30},{'strike':100,'mid':10}],1))
 def test_butterfly(self):self.assertIn('negative_discrete_butterfly',o.price_checks([{'strike':90,'mid':20},{'strike':100,'mid':18},{'strike':110,'mid':10}],1))
 def test_unknown_research(self):self.assertEqual(o.calculate(fixture())['unknown_quote_times'],10)
 def test_unknown_eligible(self):
  p=fixture();p['mode']='eligible_quote_diagnostic';self.assertEqual(o.calculate(p)['coverage']['numeric_nodes'],0)
 def test_fresh_still_not_executable(self):
  p=fixture();p['mode']='eligible_quote_diagnostic'
  for c in p['contracts']:c['quote_at']='2026-10-23T19:59:59Z'
  r=o.calculate(p);self.assertEqual(len(r['nodes']),10);self.assertFalse(r['executable'])
 def test_skew(self):
  p=fixture();p['mode']='eligible_quote_diagnostic'
  for c in p['contracts']:c['quote_at']='2026-10-23T19:59:59Z'
  p['contracts'][0]['quote_at']='2026-10-23T19:59:30Z'
  with self.assertRaises(ValueError):o.calculate(p)
 def test_stale_future(self):
  for tm in ['2026-10-23T19:00:00Z','2026-10-23T20:01:00Z']:
   p=fixture();p['mode']='eligible_quote_diagnostic'
   for c in p['contracts']:c['quote_at']=tm
   self.assertEqual(o.calculate(p)['coverage']['numeric_nodes'],0)
 def test_naive(self):
  p=fixture();p['valuation_at']='2026-10-23T20:00:00'
  with self.assertRaises(ValueError):o.calculate(p)
 def test_symbol_strike_expiry(self):
  for field,val in [('contract_id','ABC270416C00100000'),('strike',105),('expiry_at','2027-01-16T21:00:00Z')]:
   p=fixture();p['contracts'][0][field]=val
   with self.assertRaises(ValueError):o.calculate(p)
 def test_exact_decimal_strike(self):
  p=fixture();p['contracts'][0].update(strike=99999.99899,contract_id='ABC270115C99999999')
  with self.assertRaises(ValueError):o.calculate(p)
 def test_historical_future_rejected(self):
  p=fixture();p['contracts'][0]['quote_at']='2026-10-23T20:01:00Z'
  self.assertEqual(o.calculate(p)['rejected'][0]['reasons'],['future_quote_relative_to_valuation'])
 def test_invalid_occ_dimensions(self):
  for symbol,k,cid,ex in [('ABCDEFGH',80,'ABCDEFGH270115C00080000','2027-01-15T21:00:00Z'),('ABC',100000,'ABC270115C100000000','2027-01-15T21:00:00Z'),('ABC',80,'ABC270115C00080000','2127-01-15T21:00:00Z')]:
   p=fixture();p['symbol']=symbol;p['contracts']=p['contracts'][:1];p['contracts'][0].update(strike=k,contract_id=cid,expiry_at=ex)
   with self.assertRaises(ValueError):o.calculate(p)
 def test_strict_timestamp_and_policy(self):
  for tm in ['2026-10-23T20:00:00+00:99','2026-10-23X20:00:00Z']:
   p=fixture();p['valuation_at']=tm
   with self.assertRaises(ValueError):o.calculate(p)
  p=fixture();p['policy']['max_skew_seconds']=61
  with self.assertRaises(ValueError):o.calculate(p)
 def test_duplicate(self):
  p=fixture();p['contracts'].append(copy.deepcopy(p['contracts'][0]))
  with self.assertRaises(ValueError):o.calculate(p)
 def test_crossed_zero_wide(self):
  for bid,ask in [(0,1),(2,1),(1,10)]:
   p=fixture();p['contracts'][0].update(bid=bid,ask=ask);self.assertEqual(len(o.calculate(p)['rejected']),1)
 def test_nan_bool(self):
  for v in [float('nan'),float('inf'),True]:
   p=fixture();p['spot']=v
   with self.assertRaises(ValueError):o.calculate(p)
 def test_inversion_bounds(self):
  p=fixture();p['contracts'][0].update(bid=101,ask=102);self.assertIn('inversion_failed',o.calculate(p)['rejected'][0]['reasons'][0])
 def test_json(self):
  for s in ['{"x":1,"x":2}','{"x":NaN}']:
   with self.assertRaises(ValueError):b.decode_packet(s)
 def test_hash(self):
  p=fixture();a=o.calculate(p)['input_sha256'];p['contracts'][0]['ask']+=.01;self.assertNotEqual(a,o.calculate(p)['input_sha256'])
 def test_calendar_bad(self):
  p=fixture()
  for c in p['contracts']:
   t=(o.stamp(c['expiry_at'])-o.stamp(p['valuation_at'])).total_seconds()/(365*86400);v=.8 if '270115' in c['contract_id'] else .1;m=b.bsm('call',100,c['strike'],t,.04,0,v)['price'];c.update(bid=m*.995,ask=m*1.005)
  self.assertTrue(any(x['status']=='sampled_violation' for x in o.calculate(p)['calendar_checks']))
 def test_thin(self):
  p=fixture();p['contracts']=p['contracts'][:2];r=o.calculate(p);self.assertEqual(r['holdout_summary']['count'],0);self.assertIsNone(r['holdout_summary']['mae_premium'])
if __name__=='__main__':unittest.main()
