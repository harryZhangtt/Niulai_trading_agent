import tempfile,unittest
from pathlib import Path
from _loader import module
from _support import NOW,REQUEST,gateway_factory,make
class T(unittest.TestCase):
 def test_every_post_admission_exception_is_durable_unknown(self):
  cases=[(module("process").FakeProcess(),gateway_factory(raise_after_persist=True)),(module("process").FakeProcess(raise_at="invoke"),gateway_factory()),(module("process").FakeProcess(terminal="MALFORMED"),gateway_factory()),(module("process").FakeProcess(raise_at="cleanup"),gateway_factory())]
  for process,gf in cases:
   with tempfile.TemporaryDirectory() as d:
    v,a=make(d);r=module("runner").run(v,a,NOW,Path(d).resolve(),REQUEST,process,gf);self.assertEqual((r["terminal_outcome"],r["retry"],r["replay"],r["provider_status_calls"]),("UNKNOWN",False,False,0));p=Path(r["unknown_evidence_path"]);self.assertTrue(p.is_file());self.assertEqual(module("reconciliation").reconstruct_unknown(p)["terminal_outcome"],"UNKNOWN");self.assertEqual(process.cleanup_calls,1)
 def test_predispatch_exception_stops_and_cleans(self):
  with tempfile.TemporaryDirectory() as d:
   v,a=make(d);p=module("process").FakeProcess(raise_at="start");r=module("runner").run(v,a,NOW,Path(d).resolve(),REQUEST,p,gateway_factory());self.assertEqual((r["terminal_outcome"],r["admission_count"],p.cleanup_calls),("STOP",0,1));self.assertIn("cleanup_receipt",r)
