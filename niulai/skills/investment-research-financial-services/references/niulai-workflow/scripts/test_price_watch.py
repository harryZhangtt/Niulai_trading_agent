import unittest,sqlite3,json
from unittest.mock import patch
from datetime import timedelta
import price_watch as p
class TestMonitor(unittest.TestCase):
 def setUp(self):
  self.r={'id':'x','ticker':'X','threshold':'100','direction':'below','enabled':True,'updatedAt':'2026-10-01T00:00:00Z'}
  self.b={'open':'110','low':'100','high':'111','close':'105','quote_time':'2026-10-19T20:00:00Z','evidence':'test'}
 def test_equal_and_cross_return(self):
  r=p.classify(self.r,self.b,'110','.005');self.assertTrue(r['threshold_reached']);self.assertTrue(r['directional_entry_supported']);self.assertFalse(r['currently_in_zone'])
 def test_gap(self):
  self.b.update(open='90',low='89',high='95',close='94');self.assertTrue(p.classify(self.r,self.b,'110','.005')['directional_entry_supported'])
 def test_baseline(self):
  self.b.update(open='90',low='89',high='95',close='94');self.assertFalse(p.classify(self.r,self.b,None,'.005')['directional_entry_supported'])
 def test_buffer_not_threshold(self):
  self.b.update(low='100.4');r=p.classify(self.r,self.b,'110','.005');self.assertTrue(r['zone_reached']);self.assertFalse(r['threshold_reached'])
 def test_above(self):
  self.r['direction']='above';self.b.update(open='90',low='89',high='100',close='95');self.assertTrue(p.classify(self.r,self.b,'90','.005')['directional_entry_supported'])
 def test_leverage_buffer(self):
  self.b.update(low='101.4');self.assertFalse(p.classify(self.r,self.b,None,'.005')['zone_reached']);self.assertTrue(p.classify(self.r,self.b,None,'.015')['zone_reached'])
 def test_invalid(self):
  for x in ('NaN','Infinity','-1',True):
   with self.assertRaises(ValueError):p.decimal(x)
 def test_calendar(self):
  self.assertIsNone(p.session(p.instant('2026-10-18T23:00:00Z')))
  self.assertEqual(p.session(p.instant('2026-11-27T19:00:00Z'))['close'].hour,18)
  self.assertEqual(p.session(p.instant('2026-10-19T23:00:00Z'))['close'].hour,20)
  self.assertEqual(p.session(p.instant('2026-11-09T23:00:00Z'))['close'].hour,21)
 def test_rules_duplicate(self):
  with self.assertRaises(ValueError):p.validate_rules([self.r,self.r])
 def test_parse_stale(self):
  m=p.session(p.instant('2026-10-19T19:55:00Z'));stamp=int(p.instant('2026-10-19T18:00:00Z').timestamp())
  payload={'chart':{'result':[{'meta':{'symbol':'X','currency':'USD','exchangeTimezoneName':'America/New_York'},'timestamp':[stamp],'indicators':{'quote':[{'open':[110],'low':[100],'high':[111],'close':[105]}]}}]}}
  with self.assertRaisesRegex(ValueError,'Stale'):p.parse(payload,'X',m,p.instant('2026-10-19T19:55:00Z'))
 def test_replay_does_not_emit(self):
  c={'alert_authority':'niulai_saved_json_sqlite','config_revision':7,'price_monitor':{'buffer_fraction':'.005'}}
  db=sqlite3.connect(':memory:');source={'ticker':'X','bar':self.b,'previous':'110','splits':[],'source_url':'test','retrieved_at':'test'}
  with patch.object(p,'validate_config'),patch.object(p,'fetch',return_value=source):
   out=p.run(c,[self.r],db,p.instant('2026-10-19T23:00:00Z'),'existing_summary','replay')
   self.assertEqual(out['new_signals'],[]);self.assertEqual(db.execute('select count(*) from price_signals').fetchone()[0],0)
   self.assertEqual(p.run(c,[self.r],db,p.instant('2026-10-19T23:00:00Z'),'existing_summary','replay')['status'],'duplicate_completed_slot')
 def test_historical_live_rejected(self):
  with patch.object(p,'validate_config'):
   with self.assertRaisesRegex(ValueError,'Live cutoff'):p.run({'alert_authority':'niulai_saved_json_sqlite'},[self.r],sqlite3.connect(':memory:'),p.instant('2026-10-19T23:00:00Z'),'existing_summary','live')
if __name__=='__main__':unittest.main()
