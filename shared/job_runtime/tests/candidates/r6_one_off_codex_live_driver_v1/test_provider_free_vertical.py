import hashlib,json,os,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from ._support import ROOT,FIXTURES,Clock,config,deps,held,preflight,prompt,raw
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.driver import execute_provider_free
class VerticalTests(unittest.TestCase):
 def run_case(self,scenario='nominal',mutate=None,fault=None,clock=None,deadline=None,engine_fault=None,retain=False,upstream=None):
  td=tempfile.TemporaryDirectory(dir=FIXTURES);parent=Path(td.name);c=config();h=held(c);p=preflight()
  if mutate:mutate(c,p,h)
  d=deps(parent,scenario,fault,clock,deadline,engine_fault,retain,None,upstream);r=execute_provider_free(c,p,h,prompt(),b'{}',ROOT,parent,'execution-'+scenario,d,datetime(2026,11,10,0,1,tzinfo=timezone.utc));files={x.relative_to(parent).as_posix():x.read_bytes() for x in parent.rglob('*') if x.is_file()};exists=(parent/('execution-'+scenario)).exists();td.cleanup();return r,d,files,exists
 def test_nominal_canonical_engine_binding_and_custody_removed(self):
  r,d,files,exists=self.run_case();self.assertEqual((r.outcome,r.code),('PASS','FAKE_NOMINAL_ONE'));self.assertFalse(exists);self.assertEqual(r.engine['counts'],{'jobs':1,'slots':1,'attempts':1,'provider_results':1});self.assertEqual(r.receipts['engine_readback']['status'],'succeeded');self.assertTrue(r.receipts['engine_readback']['exact']);self.assertFalse(r.receipts['engine_readback']['unknown_durable']);self.assertEqual((r.counters['admissions'],r.counters['upstream_attempts'],r.counters['terminals']),(1,1,1));self.assertEqual(len([k for k in files if k.endswith('.commit')]),1)
 def test_unknown_durable_only_on_exact_canonical_readback(self):
  r,_,files,_=self.run_case('malformed');self.assertEqual(r.outcome,'UNKNOWN');self.assertTrue(r.receipts['engine_readback']['unknown_durable']);self.assertEqual(r.receipts['engine_readback']['status'],'unknown')
  for fault in ('after_dispatch_before_finish','readback','status_none'):
   r,_,files,_=self.run_case('malformed',engine_fault=fault);self.assertEqual(r.outcome,'UNKNOWN');self.assertFalse(r.receipts['engine_readback']['unknown_durable'],fault);self.assertTrue(any('non-pass-fence-v3.json.commit' in k for k in files),fault)
 def test_retained_custody_forces_unknown(self):
  r,_,_,exists=self.run_case(retain=True);self.assertEqual((r.outcome,r.code),('UNKNOWN','CUSTODY_RETAINED'));self.assertTrue(exists);self.assertFalse(r.receipts['custody_cleanup']['authoritative_pass_safe'])
 def test_each_held_drift_stops_before_external_effect(self):
  for name in ('binary','argv','config','parser','gateway','prompt','source_closure','grant'):
   r,_,_,_=self.run_case(mutate=lambda c,p,h,n=name:h.__setitem__(n,b'drift'));self.assertEqual(r.outcome,'STOP',name);self.assertEqual(r.counters['upstream_attempts'],0,name)
 def _binary_case(self,symlink=False,swap=False):
  with tempfile.TemporaryDirectory(dir=FIXTURES) as td:
   parent=Path(td);target=parent/'held-fixture';original=raw('fake_codex_process.py');target.write_bytes(original);target.chmod(0o755);path=target
   if symlink:path=parent/'held-link';path.symlink_to(target)
   c=config(path,original);h=held(c,original);d=deps(parent,pre_binary_swap=None) if False else deps(parent);d=type(d)(d.publisher,d.fixture_upstream_path,d.scenario,d.monotonic,d.deadline_monotonic,d.fixture_timeout,d.engine_fault,d.retain_custody,b'changed\n' if swap else None)
   r=execute_provider_free(c,preflight(),h,prompt(),b'{}',ROOT,parent,'binary-race',d,datetime(2026,11,10,0,1,tzinfo=timezone.utc));return r
 def test_real_symlink_and_swap_rejected_prepopen_stop0(self):
  for r in (self._binary_case(symlink=True),self._binary_case(swap=True)):
   self.assertEqual(r.outcome,'STOP');self.assertEqual((r.counters['process_starts'],r.counters['admissions'],r.counters['upstream_attempts']),(0,0,0))
 def test_fixture_entrypoint_rejects_live_url_or_arbitrary_route(self):
  r,_,_,_=self.run_case(upstream=Path('https://example.invalid/live'));self.assertEqual((r.outcome,r.code),('STOP','LIVE_UPSTREAM_FORBIDDEN'))
 def test_terminal_second_timeout_and_leak_faults(self):
  for scenario in ('absent','multiple','contradictory','malformed','post_timeout','exception_secret'):
   r,_,files,_=self.run_case(scenario);self.assertEqual(r.outcome,'UNKNOWN',scenario);public=b''.join(v for k,v in files.items() if '.payload' in k or '.commit' in k).lower();self.assertNotIn(b'bearer',public);self.assertNotIn(b'cookie',public);self.assertNotIn(b'synthetic-exception',public)
  r,_,_,_=self.run_case('second');self.assertEqual((r.outcome,r.counters['upstream_attempts'],r.counters['second_rejections']),('UNKNOWN',1,1));self.assertEqual((r.counters['retries'],r.counters['replays'],r.counters['status_calls'],r.counters['reconciliations']),(0,0,0,0))
  r,_,_,_=self.run_case('pre_timeout');self.assertEqual((r.outcome,r.counters['upstream_attempts']),('STOP',0))
 def test_publication_faults_never_authoritative_pass_and_cleanup_recorded(self):
  for fault in ('destination_race','short_write','file_fsync','link','rename','dir_fsync','marker_dir_fsync'):
   r,d,files,_=self.run_case(fault=fault);self.assertEqual(r.outcome,'UNKNOWN',fault);self.assertTrue(d.publisher.failure_history,fault);last=d.publisher.failure_history[0];self.assertTrue(last['stage_clean'] and last['cleanup_dir_fsynced']);pass_markers=[v for k,v in files.items() if k.endswith('stage-b-execution-v3.json.commit')];self.assertFalse(pass_markers,fault);self.assertTrue(any(k.endswith('non-pass-fence-v3.json.commit') for k in files),fault)
 def test_monotonic_observations_and_late_never_pass(self):
  r,_,files,_=self.run_case(clock=Clock(step=40),deadline=300);self.assertNotEqual(r.outcome,'PASS');self.assertTrue(r.receipts['timing']['late']);self.assertFalse(any(k.endswith('stage-b-execution-v3.json.commit') for k in files));names='|'.join(r.receipts['timing']['observations']);
  for part in ('before_custody','after_custody','before_engine','after_engine','before_primary_publication','after_primary_publication'):self.assertIn(part,names)
 def test_countable_false(self):
  r,_,_,_=self.run_case('malformed');self.assertFalse(r.countable_observation)
if __name__=='__main__':unittest.main()
