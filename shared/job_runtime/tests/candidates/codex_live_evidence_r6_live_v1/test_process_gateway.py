import tempfile,threading,unittest
from pathlib import Path
from _loader import module
from _support import NOW,REQUEST,gateway_factory,make
class T(unittest.TestCase):
 def test_nominal_and_durable_nonce_race(self):
  with tempfile.TemporaryDirectory() as d:
   v,a=make(d);r=module("runner").run(v,a,NOW,Path(d).resolve(),REQUEST,module("process").FakeProcess(),gateway_factory());self.assertEqual((r["terminal_outcome"],r["admission_count"]),("PASS",1))
  with tempfile.TemporaryDirectory() as d:
   v,a=make(d,"race-nonce");barrier=threading.Barrier(2);results=[]
   def worker():barrier.wait();results.append(module("preflight").run_preflight(v,a,NOW,Path(d).resolve())["decision"])
   ts=[threading.Thread(target=worker) for _ in range(2)];[x.start() for x in ts];[x.join() for x in ts];self.assertEqual(sorted(results),["PASS","STOP"])
 def test_separate_gateways_share_one_admission_owner(self):
  with tempfile.TemporaryDirectory() as d:
   v,a=make(d);lease=module("preflight").prepare(v,a,NOW,Path(d).resolve());pr=module("process").FakeProcess().start(v["identity"]);g1=module("gateway").FakeGateway(lease.store);g2=module("gateway").FakeGateway(lease.store);g1.admit(REQUEST,v["identity"],lease.operation_key,pr)
   with self.assertRaises(module("contracts").DuplicateAdmissionCriticalStop):g2.admit(REQUEST,v["identity"],lease.operation_key,pr)
   self.assertEqual((g1.upstream_attempt_count,g2.upstream_attempt_count),(1,0));lease.close()
 def test_all_injected_identity_mismatches_fenced(self):
  process_fields=("provider_process_start_identity","engine_identity","operation_id")
  gateway_fields=("request_fingerprint","request_local_gateway_id","request_local_gateway_fingerprint","engine_identity","provider_process_start_identity","operation_id")
  for field in process_fields:
   with tempfile.TemporaryDirectory() as d:
    v,a=make(d);r=module("runner").run(v,a,NOW,Path(d).resolve(),REQUEST,module("process").FakeProcess(identity_overrides={field:"wrong"}),gateway_factory());self.assertEqual((r["terminal_outcome"],r["admission_count"]),("STOP",0))
  for field in gateway_fields:
   with tempfile.TemporaryDirectory() as d:
    v,a=make(d);r=module("runner").run(v,a,NOW,Path(d).resolve(),REQUEST,module("process").FakeProcess(),gateway_factory(identity_overrides={field:"wrong"}));self.assertEqual((r["terminal_outcome"],r["admission_count"]),("UNKNOWN",1))
