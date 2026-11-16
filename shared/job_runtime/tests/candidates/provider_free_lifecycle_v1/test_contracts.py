import json,unittest
from pathlib import Path
from _loader import module
class ContractTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.c=module("contracts");cls.fx=Path(__file__).resolve().parents[2]/"fixtures"/"provider_free_lifecycle_v1"
 def load(self,name):return json.loads((self.fx/name).read_text())
 def test_bindings_and_authorization_split(self):
  for name in ("nominal.json","post-submit-failure.json"):
   value=self.load(name);binding=self.c.binding_from_mapping(value);self.assertFalse(binding.old_replay_authorized);self.assertTrue(binding.new_logical_job_authorized);self.assertFalse(binding.enabled);self.assertFalse(binding.capability_open)
 def test_identity_mutations_fail(self):
  value=self.load("nominal.json")
  for key in ("source_sha256","config_sha256","allocation_sha256","prompt_sha256","predecessor_r5_sha256","predecessor_r4_slot_sha256","predecessor_r4_attempt_sha256"):
   bad=dict(value);bad[key]="0"*64
   with self.assertRaises(self.c.LifecycleContractError):self.c.binding_from_mapping(bad)
  for key in ("old_replay_authorized","enabled","capability_open"):
   bad=dict(value);bad[key]=True
   with self.assertRaises(self.c.LifecycleContractError):self.c.binding_from_mapping(bad)
  bad=dict(value);bad["new_logical_job_authorized"]=False
  with self.assertRaises(self.c.LifecycleContractError):self.c.binding_from_mapping(bad)
 def test_shape_and_types_fail(self):
  value=self.load("nominal.json");bad=dict(value);bad["extra"]=1
  with self.assertRaises(self.c.LifecycleContractError):self.c.binding_from_mapping(bad)

 def test_schema_couples_scenario_statuses(self):
  schema=json.loads((Path(__file__).resolve().parents[3]/"candidates"/"provider_free_lifecycle_v1"/"evidence-v1.schema.json").read_text())
  branches=schema["allOf"]
  self.assertEqual(branches[0]["if"]["properties"]["scenario"]["const"],"nominal")
  self.assertEqual(branches[0]["then"]["properties"]["slot_status"]["const"],"succeeded")
  self.assertEqual(branches[1]["if"]["properties"]["scenario"]["const"],"post_admission_ambiguity")
  self.assertEqual(branches[1]["then"]["properties"]["slot_status"]["const"],"unknown")

 def test_binding_has_no_mutable_dict(self):
  binding=self.c.binding_from_mapping(self.load("nominal.json"))
  self.assertFalse(hasattr(binding,"__dict__"))
  with self.assertRaises(AttributeError):binding.source_sha256="0"*64
