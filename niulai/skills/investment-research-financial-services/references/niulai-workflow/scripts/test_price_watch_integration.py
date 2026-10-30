import unittest, sqlite3
from unittest.mock import patch
from datetime import datetime,timezone
import price_watch as p
class Clock(datetime):
 @classmethod
 def now(cls,tz=None):return cls(2026,10,19,19,55,tzinfo=timezone.utc)
class Integration(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:')
  self.config={'alert_authority':'niulai_saved_json_sqlite','config_revision':7,'price_monitor':{'buffer_fraction':'.005'},'schedules':[{'role':'daily_price_watch','enabled':True,'times':['13:00','19:00']}],'notifications':{'policies':{'daily_price_watch':{'enabled':True}}}}
  self.rule={'id':'r','ticker':'X','threshold':'100','direction':'below','enabled':True,'updatedAt':'2026-10-01T00:00:00Z'}
  self.src={'ticker':'X','bar':{'open':'110','low':'100.4','high':'111','close':'101','quote_time':'2026-10-19T19:55:00Z','evidence':'fixture'},'previous':'110','splits':[],'source_url':'fixture','retrieved_at':'fixture'}
 def tearDown(self):self.db.close()
 def run_live(self,source=None,role='daily_price_watch'):
  with patch.object(p,'datetime',Clock),patch.object(p,'validate_config'),patch.object(p,'fetch',return_value=source or self.src):
   return p.run(self.config,[self.rule],self.db,Clock.now(),role,'live')
 def test_live_dedup(self):
  self.assertEqual(len(self.run_live()['new_signals']),1)
  self.assertEqual(self.run_live()['status'],'duplicate_completed_slot')
  self.assertEqual(self.db.execute('select count(*) from price_signals').fetchone()[0],1)
 def test_partial_recovery_dedup(self):
  self.assertEqual(self.run_live({'ticker':'X','error':'timeout'})['status'],'partial')
  self.assertEqual(self.run_live()['status'],'completed')
  self.assertEqual(self.run_live()['status'],'duplicate_completed_slot')
 def test_disabled_no_fetch(self):
  self.rule['enabled']=False
  with patch.object(p,'fetch') as f:
   out=self.run_live();self.assertEqual(out['coverage']['enabled_rules'],0);f.assert_not_called()
 def test_split_blocks(self):
  self.src['splits']=[int(p.instant('2026-10-15T00:00:00Z').timestamp())]
  out=self.run_live();self.assertEqual(out['status'],'partial');self.assertEqual(out['new_signals'],[])
 def test_expired(self):
  self.rule['expires_at']='2026-10-18T00:00:00Z';self.assertEqual(self.run_live()['coverage']['failed_rules'],1)
 def test_intraday_rule_edit(self):
  self.rule['updatedAt']='2026-10-19T16:00:00Z';self.assertEqual(self.run_live()['coverage']['failed_rules'],1)
 def test_approach_then_threshold(self):
  self.assertEqual(len(self.run_live()['new_signals']),1)
  self.src['bar']['low']='99';self.config['schedules'].append({'role':'existing_summary','enabled':True,'times':['15:00'],'runtime_slot_grace_minutes':60});self.config['notifications']['policies']['existing_summary']={'enabled':True}
  self.assertEqual(len(self.run_live(role='existing_summary')['new_signals']),1)
  self.assertEqual(self.db.execute('select count(*) from price_signals').fetchone()[0],2)
 def test_early_wake(self):
  early=p.instant('2026-10-19T19:49:10Z')
  with patch.object(p,'datetime') as dt,patch.object(p,'validate_config'),patch.object(p,'fetch') as f:
   dt.now.return_value=early;out=p.run(self.config,[self.rule],self.db,early,'daily_price_watch','live')
   self.assertEqual(out['retry_after_seconds'],50);f.assert_not_called()
 def test_failed_write_rollback(self):
  p.setup(self.db);self.db.execute("CREATE TRIGGER fail_run BEFORE INSERT ON price_runs BEGIN SELECT RAISE(ABORT,'disk failure fixture'); END")
  with self.assertRaises(sqlite3.IntegrityError):
   with self.db:self.run_live()
  self.assertEqual(self.db.execute('select count(*) from price_signals').fetchone()[0],0)
if __name__=='__main__':unittest.main()
