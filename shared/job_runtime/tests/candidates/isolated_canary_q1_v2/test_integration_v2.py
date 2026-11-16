import json,unittest
from dataclasses import replace
from pathlib import Path
from shared.job_runtime.candidates.isolated_canary_q1_v2.contracts import AuthorityV2Error
from shared.job_runtime.candidates.isolated_canary_q1_v2.integration import build_treatment_binding,treatment_gate
class IntegrationV2Tests(unittest.TestCase):
 def config(self):return {"configured_model":"gpt-test","effort":"low","profile_sha256":"1"*64,"config_sha256":"2"*64,"payload_sha256":"3"*64,"source_cutoff_sha256":"4"*64}
 def test_expected_fixture(self):
  value = dict(build_treatment_binding(self.config()))
  fixture = Path(__file__).parents[2] / "fixtures/isolated_canary_q1_v2/treatment-binding-v2.expected.json"
  with fixture.open() as handle:
   expected = json.load(handle)
  self.assertEqual(value, expected)
 def test_gate_partial_and_closed(self):
  gate=treatment_gate();self.assertTrue(gate.source_authority_verified and gate.source_grammar_verified and gate.binary_asset_verified);self.assertFalse(gate.capability_open or gate.retry_zero_live_verified)
 def test_mutate_every_config_field(self):
  base=self.config()
  bad={"configured_model":"","effort":[],"profile_sha256":int("1"*64),"config_sha256":int("2"*64),"payload_sha256":int("3"*64),"source_cutoff_sha256":int("4"*64)}
  for key,value in bad.items():
   with self.subTest(key=key),self.assertRaises(AuthorityV2Error):build_treatment_binding({**base,key:value})
 def test_missing_extra_and_wrong_types(self):
  base=self.config()
  for value in ({k:v for k,v in base.items() if k!="effort"},{**base,"extra":1},{**base,"effort":True}):
   with self.assertRaises(AuthorityV2Error):build_treatment_binding(value)
 def test_frozen_and_fingerprint_changes(self):
  one=build_treatment_binding(self.config());two=build_treatment_binding({**self.config(),"payload_sha256":"5"*64});self.assertNotEqual(one["treatment_fingerprint_sha256"],two["treatment_fingerprint_sha256"])
  with self.assertRaises(TypeError):one["provider"]="x"
 def test_no_invocation_surface(self):
  import shared.job_runtime.candidates.isolated_canary_q1_v2.integration as i
  text=Path(i.__file__).read_text()
  for token in ("subprocess","socket","requests","Popen","shared.job_runtime.service","shared.job_runtime.model") : self.assertNotIn(token,text)
 def test_every_config_input_changes_fingerprint_and_nested_is_immutable(self):
  base=self.config();original=build_treatment_binding(base)
  changes={"configured_model":"gpt-other","effort":"medium","profile_sha256":"5"*64,"config_sha256":"6"*64,"payload_sha256":"7"*64,"source_cutoff_sha256":"8"*64}
  for key,value in changes.items():
   with self.subTest(key=key):self.assertNotEqual(original["treatment_fingerprint_sha256"],build_treatment_binding({**base,key:value})["treatment_fingerprint_sha256"])
  for key in ("loader","retry","capabilities"):
   with self.assertRaises(TypeError):original[key][next(iter(original[key]))]="x"

 def test_schema_nested_objects_are_closed_constants(self):
  schema_path = Path(__file__).parents[3] / "candidates/isolated_canary_q1_v2/treatment-binding-v2.schema.json"
  with schema_path.open() as handle:
   schema = json.load(handle)
  for key in ("loader","capabilities"):
   node=schema["properties"][key];self.assertFalse(node["additionalProperties"]);self.assertEqual(set(node["required"]),set(node["properties"]));self.assertTrue(all("const" in item for item in node["properties"].values()))

if __name__=="__main__":unittest.main()
