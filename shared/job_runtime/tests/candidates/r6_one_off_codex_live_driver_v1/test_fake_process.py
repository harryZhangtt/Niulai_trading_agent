import tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from ._support import ROOT,config,deps,held,preflight,prompt
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.driver import execute_provider_free
class ProcessTests(unittest.TestCase):
 def run_case(self,scenario):
  with tempfile.TemporaryDirectory(dir=ROOT/'shared/job_runtime/tests/fixtures/r6_one_off_codex_live_driver_v1') as td:
   p=Path(td);d=deps(p,scenario);r=execute_provider_free(config(),preflight(),held(config()),prompt(),b'{}',ROOT,p,'process-'+scenario,d,datetime(2026,11,10,0,1,tzinfo=timezone.utc));return r
 def test_verified_private_copy_shell_env_stdin(self):
  r=self.run_case('nominal');x=r.receipts['process'];self.assertTrue(x['executed_private_copy']);self.assertFalse(x['shell']);self.assertTrue(x['new_process_group']);self.assertEqual(x['stdin_bytes'],526);self.assertEqual(x['environment_keys'],['CODEX_HOME','HOME','PATH']);self.assertTrue(x['descriptors_closed'] and x['pid_gone'] and x['verified_copy_removed'])
 def test_resistant_descendant_erased_after_parent_exit(self):
  r=self.run_case('resistant_child');x=r.receipts['process'];self.assertGreater(x['child_pid'],0);self.assertTrue(x['process_group_reaped'] and x['descendants_reaped'] and x['child_pid_gone'] and x['pid_gone']);self.assertEqual(r.outcome,'PASS')
 def test_timeout_children_erased(self):
  for scenario in ('child','signal'):
   r=self.run_case(scenario);x=r.receipts['process'];self.assertGreater(x['child_pid'],0);self.assertTrue(x['process_group_reaped'] and x['child_pid_gone']);self.assertEqual(r.outcome,'UNKNOWN')
if __name__=='__main__':unittest.main()
