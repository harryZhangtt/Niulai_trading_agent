import copy,json,unittest
from unittest.mock import patch
import sqlite3
import price_watch as p
import price_report as report

class Quality(unittest.TestCase):
 def setUp(self):
  self.asof=p.instant('2026-10-22T22:33:00Z');self.market=p.session(self.asof)
  self.data={'chart':{'result':[{'meta':{'symbol':'X','currency':'USD','exchangeTimezoneName':'America/New_York','regularMarketTime':int(self.market['close'].timestamp())+2,'regularMarketPrice':124},'timestamp':[int(self.market['open'].timestamp())],'indicators':{'quote':[{'open':[129],'high':[128.95],'low':[122.57],'close':[124]}]}}]}}
  self.rule={'id':'x','ticker':'X','threshold':'125','direction':'below','enabled':True,'updatedAt':'2026-10-01T00:00:00Z'}
 def test_close_only_never_invents_range_or_crossing(self):
  b,prev,s=p.parse(self.data,'X',self.market,self.asof)
  r=p.classify(self.rule,b,'140','.005')
  self.assertTrue(r['currently_in_zone']);self.assertTrue(r['threshold_reached'])
  self.assertIsNone(r['low']);self.assertIsNone(r['high']);self.assertFalse(r['directional_entry_supported'])
  self.assertIn('仅收盘',report.category(r)[0])
 def test_mismatch_and_wrong_session_rejected(self):
  for key,value in [('regularMarketPrice',110),('regularMarketTime',int(self.market['close'].timestamp())-86400)]:
   d=copy.deepcopy(self.data);d['chart']['result'][0]['meta'][key]=value
   with self.assertRaisesRegex(ValueError,'not corroborated'):p.parse(d,'X',self.market,self.asof)
 def test_low_high_invalid_not_repaired(self):
  self.data['chart']['result'][0]['indicators']['quote'][0]['low']=[130]
  with self.assertRaises(ValueError):p.parse(self.data,'X',self.market,self.asof)
 def test_quote_only_fetched_without_creating_alert(self):
  b,_,_=p.parse(self.data,'X',self.market,self.asof)
  def fetch(t,*args):return {'ticker':t,'bar':b,'previous':None,'splits':[],'source_url':'fixture','retrieved_at':'fixture'}
  c={'alert_authority':'niulai_saved_json_sqlite','config_revision':25,'price_monitor':{'buffer_fraction':'.005','quote_only_symbols':['AEIS','MU','DRAM']}}
  with patch.object(p,'validate_config'),patch.object(p,'fetch',side_effect=fetch):
   r=p.run(c,[self.rule],sqlite3.connect(':memory:'),self.asof,'existing_summary','replay')
  self.assertEqual(r['coverage']['symbols'],4);self.assertEqual(len(r['results']),1);self.assertEqual(len(r['quote_only']),3)
  self.assertEqual(r['status'],'partial');self.assertEqual(r['new_signals'],[])

if __name__=='__main__':unittest.main()
