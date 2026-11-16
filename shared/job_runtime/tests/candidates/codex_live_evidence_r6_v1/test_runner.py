import json,tempfile,unittest
from pathlib import Path
from _loader import module
from _support import REQUEST,NOW,fixture,make
class RunnerTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.a=module("adapter");cls.g=module("gateway");cls.r=module("runner");cls.rec=module("reconciliation");cls.c=module("contracts");cls.t=module("translator")
 def run_case(self,name):
  f=fixture(name)
  with tempfile.TemporaryDirectory() as d:
   grant=make(d)
   if f.get("mutation")=="account_mismatch":grant["account"]["opaque_account_fingerprint"]="d"*64
   adapter=self.a.SyntheticObservationAdapter(f["scenario"] if "observation" in f else "nominal",f.get("observation",{"terminal_status":"completed","process_exit":0,"output":"synthetic"}))
   result=self.r.run_synthetic(grant=grant,synthetic_root=Path(d),now=NOW,request=REQUEST,adapter=adapter)
   return self.c.canonical_bytes(dict(result)),dict(result),adapter.observation_count
 def test_nominal_single_admission_pass(self):
  _,r,count=self.run_case("nominal.json");self.assertEqual((r["terminal_outcome"],r["upstream_attempt_count"],count),("PASS",1,1));self.assertFalse(r["countable_observation"])
 def test_pre_dispatch_auth_stop_upstream_zero(self):
  _,r,count=self.run_case("pre-dispatch-stop.json");self.assertEqual((r["terminal_outcome"],r["upstream_attempt_count"],count),("STOP",0,0));self.assertEqual(r["submission"],"DEFINITELY_NOT_SUBMITTED")
 def test_unknown_reconstruction_no_replay(self):
  raw,r,count=self.run_case("post-admission-unknown.json");rebuilt=self.rec.reconstruct_unknown(raw);self.assertEqual((rebuilt["terminal_outcome"],rebuilt["reconciliation"]["dispatch_count"],rebuilt["provider_status_calls"],count),("UNKNOWN",0,0,1));self.assertFalse(rebuilt["replay"])
 def test_duplicate_admission_critical_stop(self):
  with tempfile.TemporaryDirectory() as d:
   grant=make(d);gateway=self.g.GatewayObserver();gateway.admit(REQUEST,grant["identity"])
   with self.assertRaisesRegex(self.g.DuplicateAdmissionCriticalStop,"R6_SECOND_ADMISSION_CRITICAL_STOP"):gateway.admit(REQUEST,grant["identity"])
   self.assertEqual(gateway.admission_count,1)
 def test_malformed_and_missing_terminal(self):
  for name,code in (("malformed-terminal.json","R6_MALFORMED_TERMINAL"),("missing-terminal.json","R6_MISSING_TERMINAL")):
   f=fixture(name)
   with tempfile.TemporaryDirectory() as d:
    grant=make(d)
    with self.assertRaisesRegex(self.c.R6ContractError,code):
     adapter=self.a.SyntheticObservationAdapter(f["scenario"],f["observation"]);self.r.run_synthetic(grant=grant,synthetic_root=Path(d),now=NOW,request=REQUEST,adapter=adapter)
 def test_prompt_identity_mismatch_stops(self):
  with tempfile.TemporaryDirectory() as d:
   grant=make(d);grant["prompt_process"]["job_id"]="r6-job-other";adapter=self.a.SyntheticObservationAdapter("nominal",fixture("nominal.json")["observation"])
   r=self.r.run_synthetic(grant=grant,synthetic_root=Path(d),now=NOW,request=REQUEST,adapter=adapter);self.assertEqual((r["terminal_outcome"],r["upstream_attempt_count"]),("STOP",0))
 def test_request_identity_mismatch_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   grant=make(d);gateway=self.g.GatewayObserver()
   with self.assertRaisesRegex(self.c.R6ContractError,"R6_REQUEST_IDENTITY_MISMATCH"):gateway.admit(b"other",grant["identity"])
 def test_live_boundary_deny_default(self):
  boundary=self.a.DenyByDefaultLiveBoundary()
  for name in ("provider","network","account","login","private_state","email"):
   with self.assertRaisesRegex(self.c.R6ContractError,"R6_LIVE_BOUNDARY_DENIED"):getattr(boundary,name)
 def test_all_identity_participants_equal(self):
  _,r,_=self.run_case("nominal.json");self.assertEqual(set(r["identity_receipts"]),set(self.c.PARTICIPANTS));self.assertTrue(all(v==r["identity"] for v in r["identity_receipts"].values()))
 def test_cleanup_complete_and_no_effects(self):
  _,r,_=self.run_case("nominal.json");self.assertTrue(all(r["cleanup"][k]=={"applicable":False,"evidence":"provider_free_no_resource_created"} for k in ("process_group","listener","socket_path","file_descriptors","temporary_paths")));self.assertEqual((r["cleanup"]["residual_children"],r["cleanup"]["unlisted_effects"]),(0,0));self.assertEqual(sum(r[k] for k in ("provider_calls","network_calls","account_calls","email_calls","private_state_calls")),0)
 def test_account_cost_window_private_root_gates_stop(self):
  mutations=[lambda g:g["account"].update(model_access=False),lambda g:g["budget"].update(hard_maximum=0),lambda g:g["window"].update(deadline="2029-01-01T00:00:00Z"),lambda g:g["private_root"].update(mode_0700=False)]
  for mutate in mutations:
   with tempfile.TemporaryDirectory() as d:
    grant=make(d);mutate(grant);adapter=self.a.SyntheticObservationAdapter("nominal",fixture("nominal.json")["observation"]);r=self.r.run_synthetic(grant=grant,synthetic_root=Path(d),now=NOW,request=REQUEST,adapter=adapter);self.assertEqual((r["terminal_outcome"],r["upstream_attempt_count"],adapter.observation_count),("STOP",0,0))
 def test_call_budget_constants(self):
  self.assertEqual(dict(self.c.CALL_BUDGET),{"catalog_preflight_count":1,"concurrency":1,"gateway_admission_max":1,"gateway_retries":0,"inference_invocation_max":1,"max_attempts":1,"max_workers":1,"request_retries":0,"stream_retries":0,"upstream_attempt_max":1,"second_admission_rejected":True})
 def test_pre_dispatch_config_drift_stop_upstream_zero(self):
  with tempfile.TemporaryDirectory() as d:
   grant=make(d);grant["artifacts"]["canonical_config"]["sha256"]="0"*64
   adapter=self.a.SyntheticObservationAdapter("nominal",fixture("nominal.json")["observation"])
   r=self.r.run_synthetic(grant=grant,synthetic_root=Path(d),now=NOW,request=REQUEST,adapter=adapter)
   self.assertEqual((r["terminal_outcome"],r["upstream_attempt_count"],adapter.observation_count),("STOP",0,0))
 def test_exact_r3_r4_identity_values_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   identity=make(d)["identity"]
   for field,token in (("job_id","claude-live-smoke-20261109T123642Z"),("slot_id","edbc12c8e6d6754920a7b76d2e25b6c80e118a65047d17a8223e8923bbf6059f"),("attempt_id","c72c078909328d1e8096090c9a4fd3efc5695837ce208d5f89a396d2dce9cc1c"),("slot_id","66ca95b8a8cd1b6471b893a13169249d8a36713e5475665e42352a13dbec2186"),("attempt_id","f8ddc6225b89f25cff3a39ae0cc310ef7348d7fd507783eb597d61ed9c35ae08")):
    bad=dict(identity);bad[field]=token
    with self.assertRaisesRegex(self.c.R6ContractError,"R6_PRIOR_IDENTITY_REUSE"):self.c.validate_identity(bad)

 def test_ambiguity_rejects_non_string_terminal_status(self):
  with tempfile.TemporaryDirectory() as d:
   grant=make(d);observation={"terminal_status":7,"process_exit":70,"output":"synthetic ambiguity"}
   with self.assertRaisesRegex(self.c.R6ContractError,"R6_MALFORMED_TERMINAL"):
    adapter=self.a.SyntheticObservationAdapter("post_admission_ambiguity",observation);self.r.run_synthetic(grant=grant,synthetic_root=Path(d),now=NOW,request=REQUEST,adapter=adapter)

 def test_adapter_directly_rejects_ambiguity_non_string_terminal_status(self):
  with self.assertRaisesRegex(self.c.R6ContractError,"R6_MALFORMED_TERMINAL"):
   self.a.SyntheticObservationAdapter("post_admission_ambiguity",{"terminal_status":7,"process_exit":70,"output":"synthetic ambiguity"})
