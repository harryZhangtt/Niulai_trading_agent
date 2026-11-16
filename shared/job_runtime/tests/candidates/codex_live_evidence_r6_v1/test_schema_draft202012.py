import copy,json,tempfile,unittest
from pathlib import Path
from _loader import module
from _support import NOW,REQUEST,fixture,make
try:
 from jsonschema import Draft202012Validator
except ImportError:
 Draft202012Validator=None
@unittest.skipUnless(Draft202012Validator is not None,"workspace Draft2020-12 validator unavailable to this interpreter")
class Draft202012SchemaTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.a=module("adapter");cls.r=module("runner");cls.c=module("contracts");root=Path(__file__).resolve().parents[3]/"candidates/codex_live_evidence_r6_v1/schemas";cls.schema=json.loads((root/"live-evidence-v1.schema.json").read_text());Draft202012Validator.check_schema(cls.schema);cls.validator=Draft202012Validator(cls.schema)
 def result(self,name):
  f=fixture(name)
  with tempfile.TemporaryDirectory() as d:
   grant=make(d)
   if name=="pre-dispatch-stop.json":grant["account"]["entitlement"]=False;scenario="nominal";obs=fixture("nominal.json")["observation"]
   else:scenario=f["scenario"];obs=f["observation"]
   value=self.r.run_synthetic(grant=grant,synthetic_root=Path(d),now=NOW,request=REQUEST,adapter=self.a.SyntheticObservationAdapter(scenario,obs));return json.loads(self.c.canonical_bytes(value))
 def test_actual_draft202012_accepts_exact_outcomes(self):
  for name in ("nominal.json","pre-dispatch-stop.json","post-admission-unknown.json"):self.validator.validate(self.result(name))
 def test_nested_extras_rejected(self):
  for outcome,key in (("nominal.json","translator"),("nominal.json","cleanup"),("post-admission-unknown.json","reconciliation"),("pre-dispatch-stop.json","preflight")):
   value=self.result(outcome);value[key]["extra"]=1
   with self.assertRaises(Exception):self.validator.validate(value)
 def test_mixed_outcome_fields_rejected(self):
  mutations=[("nominal.json",{"replay":False}),("pre-dispatch-stop.json",{"terminal_complete":True}),("post-admission-unknown.json",{"submission":"DEFINITELY_NOT_SUBMITTED"})]
  for name,extra in mutations:
   value=self.result(name);value.update(extra)
   with self.assertRaises(Exception):self.validator.validate(value)

 def test_runtime_and_actual_schema_parity_all_outcomes(self):
  for name in ("nominal.json","pre-dispatch-stop.json","post-admission-unknown.json"):
   value=self.result(name);self.c.validate_live_evidence(value);self.validator.validate(value)
 def test_runtime_and_schema_reject_same_closed_contract_mutations(self):
  mutations=[("nominal.json","translator"),("post-admission-unknown.json","reconciliation"),("pre-dispatch-stop.json","preflight")]
  for name,key in mutations:
   value=self.result(name);value[key]["extra"]=1
   with self.assertRaises(self.c.R6ContractError):self.c.validate_live_evidence(value)
   with self.assertRaises(Exception):self.validator.validate(value)
  for name,extra in (("nominal.json",{"replay":False}),("post-admission-unknown.json",{"submission":"DEFINITELY_NOT_SUBMITTED"})):
   value=self.result(name);value.update(extra)
   with self.assertRaises(self.c.R6ContractError):self.c.validate_live_evidence(value)
   with self.assertRaises(Exception):self.validator.validate(value)

 def test_unknown_terminal_status_type_runtime_schema_parity_negative(self):
  value=self.result("post-admission-unknown.json");value["translator"]["sanitized_terminal"]["terminal_status"]=7
  with self.assertRaises(self.c.R6ContractError):self.c.validate_live_evidence(value)
  with self.assertRaises(Exception):self.validator.validate(value)
