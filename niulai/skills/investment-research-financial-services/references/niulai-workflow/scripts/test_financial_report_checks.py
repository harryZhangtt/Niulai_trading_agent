import copy,unittest
from financial_report_checks import check,decode
class RewriteChecks(unittest.TestCase):
 def packet(self):
  c={'id':'call65','text':'Historical CRWV270416C00065000 costs $1,080; at 6 months a model assumption gives +20%, before fees.','evidence_class':'assumption','certainty':1,'polarity':'mixed','source_refs':['model:sha256:example'],'units':'USD/one standard 100-share contract','horizon':'6 months','protected_literals':['Historical','6 months','model assumption','before fees']}
  a={'claims':[c],'instrument':{'symbol':'CRWV270416C00065000','side':'BUY','quantity':1,'multiplier_status':'unverified'},'action':{'status':'diagnostic','decision':'wait'}}
  return {'version':1,'before':a,'after':copy.deepcopy(a)}
 def reject(self,mutator):
  p=self.packet();mutator(p['after']);self.assertEqual(check(p)['status'],'rejected')
 def test_plain_reorder_allowed(self):
  p=self.packet();p['after']['claims'][0]['text']='Historical model assumption: at 6 months +20%, before fees; CRWV270416C00065000 costs $1,080.';r=check(p);self.assertEqual(r['status'],'parity_pass_semantic_review_required');self.assertFalse(r['publication_approved']);self.assertTrue(r['warnings'])
 def test_sign(self):self.reject(lambda a:a['claims'][0].update(text=a['claims'][0]['text'].replace('+20%','-20%')))
 def test_percent(self):self.reject(lambda a:a['claims'][0].update(text=a['claims'][0]['text'].replace('20%','20')))
 def test_currency(self):self.reject(lambda a:a['claims'][0].update(text=a['claims'][0]['text'].replace('$1,080','1,080')))
 def test_contract(self):self.reject(lambda a:a['claims'][0].update(text=a['claims'][0]['text'].replace('C00065000','C00070000')))
 def test_horizon(self):self.reject(lambda a:a['claims'][0].update(text=a['claims'][0]['text'].replace('6 months','6 years')))
 def test_caveat(self):self.reject(lambda a:a['claims'][0].update(text=a['claims'][0]['text'].replace('before fees','')))
 def test_assumption_to_fact(self):self.reject(lambda a:a['claims'][0].update(evidence_class='observed_fact'))
 def test_confidence(self):self.reject(lambda a:a['claims'][0].update(certainty=3))
 def test_action(self):self.reject(lambda a:a['action'].update(decision='buy'))
 def test_quantity(self):self.reject(lambda a:a['instrument'].update(quantity=2))
 def test_missing_source(self):
  p=self.packet();p['after']['claims'][0]['source_refs']=[]
  with self.assertRaises(ValueError):check(p)
 def test_guarantee(self):self.reject(lambda a:a['claims'][0].update(text=a['claims'][0]['text']+' Guaranteed profit.'))
 def test_extra_number(self):self.reject(lambda a:a['claims'][0].update(text=a['claims'][0]['text']+' Win rate 90%.'))
 def test_duplicate_claim(self):
  p=self.packet();p['after']['claims']*=2
  with self.assertRaises(ValueError):check(p)
 def test_date(self):
  p=self.packet()
  for obj in [p['before'],p['after']]:obj['claims'][0]['text']+=' Expiry 2027-04-16.'
  p['after']['claims'][0]['text']=p['after']['claims'][0]['text'].replace('2027-04-16','2027-05-16');self.assertEqual(check(p)['status'],'rejected')
 def test_semantics_not_proven_by_same_numbers(self):
  p=self.packet();p['after']['claims'][0]['text']=p['after']['claims'][0]['text'].replace('costs $1,080','may return $1,080');r=check(p);self.assertFalse(r['semantic_truth_verified']);self.assertFalse(r['publication_approved']);self.assertTrue(r['warnings'])
 def test_currency_code_prose(self):
  p=self.packet()
  for o in [p['before'],p['after']]:o['claims'][0]['text']+=' USD 10.'
  p['after']['claims'][0]['text']=p['after']['claims'][0]['text'].replace('USD 10','EUR 10');self.assertEqual(check(p)['status'],'rejected')
 def test_month_prose(self):
  p=self.packet()
  for o in [p['before'],p['after']]:o['claims'][0]['text']+=' April 2027.'
  p['after']['claims'][0]['text']=p['after']['claims'][0]['text'].replace('April 2027','May 2027');self.assertEqual(check(p)['status'],'rejected')
 def test_modal_prose(self):
  p=self.packet()
  for o in [p['before'],p['after']]:o['claims'][0]['text']+=' It may gain.'
  p['after']['claims'][0]['text']=p['after']['claims'][0]['text'].replace('may gain','will gain');self.assertEqual(check(p)['status'],'rejected')
 def test_direction_prose(self):
  p=self.packet()
  for o in [p['before'],p['after']]:o['claims'][0]['text']+=' It may gain.'
  p['after']['claims'][0]['text']=p['after']['claims'][0]['text'].replace('may gain','may lose');self.assertEqual(check(p)['status'],'rejected')
 def test_duplicate_json(self):
  with self.assertRaises(ValueError):decode('{"version":1,"version":1}')
 def test_nonfinite(self):
  with self.assertRaises(ValueError):decode('{"number":NaN}')
if __name__=='__main__':unittest.main()
