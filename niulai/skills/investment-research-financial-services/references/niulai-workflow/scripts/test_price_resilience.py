import json,sqlite3,unittest,tempfile,sys
from pathlib import Path
from unittest.mock import patch,MagicMock
from urllib.error import HTTPError,URLError
import price_watch as p
from test_price_watch_integration import Integration,Clock

class Resilience(Integration):
 def summary(self,stamp):
  t=p.instant(stamp)
  self.config['schedules']=[{'role':'existing_summary','enabled':True,'times':['13:00','19:00']}]
  self.config['notifications']['policies']['existing_summary']={'enabled':True}
  self.config['price_monitor']['late_run_recovery']={'enabled':True}
  with patch.object(p,'datetime',wraps=p.datetime) as clock,patch.object(p,'validate_config'),patch.object(p,'fetch',return_value=self.src):
   clock.now.return_value=t
   return p.run(self.config,[self.rule],self.db,t,'existing_summary','live')
 def test_late_summary_is_retrospective_and_deduped(self):
  out=self.summary('2026-10-19T20:15:00Z')
  self.assertTrue(out['delayed_catchup']);self.assertTrue(out['retrospective'])
  self.assertEqual(out['intended_slot'],'13:00');self.assertEqual(out['new_signals'],[])
  self.assertEqual(self.summary('2026-10-19T20:20:00Z')['status'],'duplicate_completed_slot')
  self.assertEqual(self.summary('2026-10-19T23:20:00Z')['status'],'completed')
 def test_weekend_and_before_first_slot_still_skip(self):
  self.assertEqual(self.summary('2026-10-24T23:20:00Z')['reason'],'not_a_session')
  self.assertEqual(self.summary('2026-10-20T15:00:00Z')['reason'],'outside_slot')
 def test_unexpected_worker_failure_becomes_coverage_gap(self):
  with patch.object(p,'fetch',side_effect=RuntimeError('worker failure')):
   self.assertIn('worker failure',p.fetch_safe('X',None,None,None)['error'])
 def test_one_bad_symbol_does_not_discard_good_symbol(self):
  other=dict(self.rule,id='second',ticker='Y')
  def fetch(t,*args):
   if t=='Y':raise RuntimeError('transport broke')
   return self.src
  with patch.object(p,'datetime',Clock),patch.object(p,'validate_config'),patch.object(p,'fetch',side_effect=fetch):
   out=p.run(self.config,[self.rule,other],self.db,Clock.now(),'daily_price_watch','live')
  self.assertEqual(out['coverage']['valid_rules'],1);self.assertEqual(out['coverage']['failed_rules'],1)
  self.assertEqual(self.db.execute('select count(*) from price_sources').fetchone()[0],2)
 def test_transport_retry_bounded(self):
  response=MagicMock();response.__enter__.return_value.read.return_value=b'{}'
  with patch.object(p,'urlopen',side_effect=[URLError('timeout'),response]) as f,patch.object(p.time,'sleep'):
   self.assertEqual(p.request_text('https://example.org'),'{}');self.assertEqual(f.call_count,2)
  with patch.object(p,'urlopen',side_effect=URLError('timeout')) as f,patch.object(p.time,'sleep'):
   with self.assertRaises(RuntimeError):p.request_text('https://example.org')
   self.assertEqual(f.call_count,3)
 def test_permanent_http_error_not_retried(self):
  with patch.object(p,'urlopen',side_effect=HTTPError('url',404,'not found',{},None)) as f:
   with self.assertRaises(RuntimeError):p.request_text('https://example.org')
   self.assertEqual(f.call_count,1)
 def test_missing_db_replaces_stale_success(self):
  with tempfile.TemporaryDirectory() as directory:
   output=Path(directory)/'result.json';output.write_text('{"status":"completed"}')
   argv=['price_watch','--config','missing-config','--rules','missing-rules','--db',str(Path(directory)/'absent.sqlite'),'--output',str(output)]
   with patch.object(sys,'argv',argv),patch('builtins.print'):
    with self.assertRaises(SystemExit):p.main()
   self.assertEqual(json.loads(output.read_text())['status'],'failed')
 def test_completed_source_survives_finalization_failure(self):
  p.setup(self.db);self.db.execute("CREATE TRIGGER fail_final BEFORE UPDATE ON price_runs BEGIN SELECT RAISE(ABORT,'disk full fixture'); END")
  with self.assertRaises(sqlite3.IntegrityError):
   with self.db:self.run_live()
  self.assertEqual(self.db.execute('select count(*) from price_sources').fetchone()[0],1)
  self.assertEqual(json.loads(self.db.execute('select payload from price_runs').fetchone()[0])['status'],'collecting')
  self.assertEqual(self.db.execute('select count(*) from price_signals').fetchone()[0],0)
if __name__=='__main__':unittest.main()
